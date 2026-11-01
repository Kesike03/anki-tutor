"""Provider-independent Anki action proposals and native collection operations."""

import html
import json
import re


INSTRUCTIONS = """
Anki editing tools are available when the user explicitly asks to change their collection.
To propose changes, finish your answer with exactly one fenced block named anki-actions
containing a JSON object {"actions": [...]} (up to 10 actions). Supported actions:
- {"type":"add_card","front":"text","back":"text","deck":"existing deck name"}
  Optional: "notetype":"Basic". The deck and note type must already exist.
- {"type":"edit_card","card_id":123,"front":"new text","back":"new text"}
  Provide at least one side; omitted card_id targets the card being discussed.
  For non-Basic note types, use "fields":{"Field Name":"new text"} instead.
- {"type":"delete_card","card_id":123} (card_id optional for the current card).
- {"type":"set_review_options","deck":"existing deck name","changes":{
    "new.perDay":20,"new.delays":[1,10],"rev.perDay":200,
    "rev.maxIvl":36500,"lapse.delays":[10],"lapse.minInt":1,
    "desiredRetention":0.9}}
  Include only the settings the user requested; omitted deck targets the current card's deck.
These are proposals, not executed until the user confirms them in Anki. Never claim a
change has already happened in your answer. Do not emit this block for ordinary tutoring.
"""

BLOCK = re.compile(r"(?m)^```anki-actions[ \t]*\n(.*?)\n```[ \t]*$", re.DOTALL)
OPTIONS = {
    "new.perDay": (int, 0, 10000),
    "rev.perDay": (int, 0, 10000),
    "rev.maxIvl": (int, 1, 36500),
    "lapse.minInt": (int, 1, 36500),
    "desiredRetention": (float, 0.7, 0.99),
    "new.delays": (list, 0.1, 10080),
    "lapse.delays": (list, 0.1, 10080),
}


def extract_plan(answer: str) -> tuple[str, list[dict] | None]:
    matches = list(BLOCK.finditer(answer))
    if not matches:
        return answer, None
    if len(matches) != 1 or answer[matches[0].end():].strip():
        raise ValueError("Expected one action block at the end of the response")
    try:
        payload = json.loads(matches[0].group(1))
    except json.JSONDecodeError as error:
        raise ValueError("Invalid Anki action JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("actions"), list):
        raise ValueError("Invalid Anki actions")
    actions = payload["actions"]
    if not 1 <= len(actions) <= 10:
        raise ValueError("Anki actions must contain 1 to 10 changes")
    for action in actions:
        validate_action(action)
    return answer[:matches[0].start()].rstrip(), actions


def validate_action(action: dict) -> None:
    if not isinstance(action, dict):
        raise ValueError("Invalid Anki action")
    kind = action.get("type")
    allowed = {
        "add_card": {"type", "front", "back", "deck", "notetype"},
        "edit_card": {"type", "front", "back", "fields", "card_id"},
        "delete_card": {"type", "card_id"},
        "set_review_options": {"type", "deck", "changes"},
    }
    if kind not in allowed or set(action) - allowed[kind]:
        raise ValueError("Unsupported Anki action or parameter")
    if "card_id" in action and (type(action["card_id"]) is not int or action["card_id"] <= 0):
        raise ValueError("Card ID must be a positive integer")
    if "deck" in action and (not isinstance(action["deck"], str) or not action["deck"].strip()):
        raise ValueError("Deck name cannot be empty")
    if kind == "add_card":
        if any(not isinstance(action.get(side), str) or not action[side].strip() for side in ("front", "back")):
            raise ValueError("A new card requires front and back text")
        if "notetype" in action and not isinstance(action["notetype"], str):
            raise ValueError("Invalid note type")
    elif kind == "edit_card":
        if not any(key in action for key in ("front", "back", "fields")):
            raise ValueError("Specify at least one field to update")
        if any(key in action and not isinstance(action[key], str) for key in ("front", "back")):
            raise ValueError("Card text must be a string")
        fields = action.get("fields")
        if fields is not None and (not isinstance(fields, dict) or not fields or
            any(not isinstance(name, str) or not isinstance(value, str) for name, value in fields.items())):
            raise ValueError("Invalid note fields")
    elif kind == "set_review_options":
        changes = action.get("changes")
        if not isinstance(changes, dict) or not changes or set(changes) - set(OPTIONS):
            raise ValueError("Unsupported review option")
        for name, value in changes.items():
            expected, low, high = OPTIONS[name]
            if expected is list:
                if not isinstance(value, list) or len(value) > 20 or any(
                    type(step) not in (int, float) or not low <= step <= high for step in value
                ):
                    raise ValueError(f"Invalid value for {name}")
            elif expected is int:
                if type(value) is not int or not low <= value <= high:
                    raise ValueError(f"Invalid value for {name}")
            elif type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f"Invalid value for {name}")


def describe(action: dict, current_card_id: int, current_deck: str) -> str:
    kind = action["type"]
    if kind == "add_card":
        return f"Add a card to {action.get('deck', current_deck)}: {action['front'][:100]} / {action['back'][:100]}"
    if kind == "delete_card":
        return f"Delete card {action.get('card_id', current_card_id)} (and its note if orphaned)"
    if kind == "edit_card":
        changes = {key: action[key] for key in ("front", "back") if key in action}
        changes.update(action.get("fields", {}))
        return f"Edit note for card {action.get('card_id', current_card_id)}: " + ", ".join(
            f"{key}={value[:100]}" for key, value in changes.items()
        )
    return f"Change shared deck preset for {action.get('deck', current_deck)}: " + ", ".join(
        f"{key}={value}" for key, value in action["changes"].items()
    )


def execute(col, action: dict, current_card_id: int, current_deck: str):
    """Return OpChanges (or OpChangesWithCount) for CollectionOp."""
    validate_action(action)
    kind = action["type"]
    if kind == "add_card":
        deck_id = col.decks.id_for_name(action.get("deck", current_deck))
        if deck_id is None:
            raise ValueError("The requested deck does not exist")
        notetype = col.models.by_name(action.get("notetype", "Basic"))
        if notetype is None:
            raise ValueError("The requested note type does not exist")
        note = col.new_note(notetype)
        names = note.keys()
        if len(names) < 2:
            raise ValueError("The note type needs two fields")
        note[names[0]] = html.escape(action["front"]).replace("\n", "<br>")
        note[names[1]] = html.escape(action["back"]).replace("\n", "<br>")
        return col.add_note(note, deck_id)
    if kind == "delete_card":
        card = col.get_card(action.get("card_id", current_card_id))
        return col.remove_cards_and_orphaned_notes([card.id])
    if kind == "edit_card":
        card = col.get_card(action.get("card_id", current_card_id))
        note = card.note()
        names = note.keys()
        for key, position in (("front", 0), ("back", 1)):
            if key in action:
                if len(names) <= position:
                    raise ValueError(f"Note has no {key} field")
                note[names[position]] = html.escape(action[key]).replace("\n", "<br>")
        for name, value in action.get("fields", {}).items():
            if name not in note:
                raise ValueError(f"Unknown note field: {name}")
            note[name] = html.escape(value).replace("\n", "<br>")
        return col.update_note(note)
    deck_id = col.decks.id_for_name(action.get("deck", current_deck))
    if deck_id is None:
        raise ValueError("The requested deck does not exist")
    deck = col.decks.get(deck_id, default=False)
    if not deck or "conf" not in deck:
        raise ValueError("Review options require a normal deck")
    preset = col.decks.get_config(int(deck["conf"]))
    if preset is None:
        raise ValueError("Deck preset not found")
    for key, value in action["changes"].items():
        if "." in key:
            group, field = key.split(".", 1)
            preset[group][field] = value
        else:
            preset[key] = value
    col.decks.update_config(preset)
    from anki.collection import OpChanges

    return OpChanges(deck_config=True, study_queues=True, mtime=True)
