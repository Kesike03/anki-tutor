"""Snapshot, apply, and undo Anki writes from every authoring workflow."""

from __future__ import annotations

import copy
import html
from dataclasses import dataclass, field

try:
    from .authoring import FieldChange, safe_html
except ImportError:
    from authoring import FieldChange, safe_html


class WriteError(ValueError):
    """A requested write cannot be applied safely."""


@dataclass
class WriteOperation:
    kind: str
    data: dict


@dataclass
class WriteReceipt:
    description: str = "Anki changes"
    operations: list[WriteOperation] = field(default_factory=list)
    lossy: bool = False

    @property
    def undoable(self) -> bool:
        return bool(self.operations)

    def extend(self, other: WriteReceipt) -> None:
        self.operations.extend(other.operations)
        self.lossy = self.lossy or other.lossy

    def undo(self, col) -> None:
        for operation in reversed(self.operations):
            if operation.kind == "fields":
                self._undo_fields(col, operation.data)
            elif operation.kind == "added":
                self._undo_added(col, operation.data)
            elif operation.kind == "deleted":
                self._undo_deleted(col, operation.data)
            elif operation.kind == "preset":
                self._undo_preset(col, operation.data)
        self.operations.clear()

    @staticmethod
    def _undo_fields(col, data: dict) -> None:
        note = col.get_note(data["note_id"])
        for name, value in data["before"].items():
            if name in note:
                note[name] = value
        col.update_note(note)

    @staticmethod
    def _remove_notes(col, note_ids: list[int]) -> None:
        if not note_ids:
            return
        if hasattr(col, "remove_notes"):
            col.remove_notes(note_ids)
            return
        card_ids = []
        for note_id in note_ids:
            try:
                card_ids.extend(col.find_cards(f"nid:{note_id}"))
            except Exception:
                continue
        if card_ids:
            col.remove_cards_and_orphaned_notes(card_ids)

    @classmethod
    def _undo_added(cls, col, data: dict) -> None:
        cls._remove_notes(col, data["note_ids"])

    @staticmethod
    def _undo_deleted(col, data: dict) -> None:
        model = col.models.get(data["model_id"]) if data.get("model_id") else None
        if model is None and data.get("model_name"):
            model = col.models.by_name(data["model_name"])
        if model is None:
            raise WriteError("The deleted note type is no longer available.")
        note = col.new_note(model)
        for name, value in data["fields"].items():
            if name in note:
                note[name] = value
        note.tags = list(data.get("tags", []))
        col.add_note(note, data["deck_id"])

    @staticmethod
    def _undo_preset(col, data: dict) -> None:
        col.decks.update_config(data["before"])


class SafeWriter:
    """Apply collection changes while retaining enough state to reverse them."""

    def __init__(self, col) -> None:
        self.col = col

    def apply_fields(self, changes: list[FieldChange]) -> WriteReceipt:
        grouped: dict[int, list[FieldChange]] = {}
        for change in changes:
            if change.changed and not change.error:
                grouped.setdefault(change.note_id, []).append(change)
        receipt = WriteReceipt("Field changes")
        pending = []
        try:
            for note_id, note_changes in grouped.items():
                note = self.col.get_note(note_id)
                before = {}
                for change in note_changes:
                    if change.field not in note:
                        raise WriteError(f"Unknown note field: {change.field}")
                    before[change.field] = note[change.field]
                pending.append((note, note_changes, before))
            for note, note_changes, before in pending:
                for change in note_changes:
                    note[change.field] = change.after
                self.col.update_note(note)
                receipt.operations.append(WriteOperation("fields", {
                    "note_id": int(note.id),
                    "before": before,
                }))
        except Exception:
            if receipt.operations:
                receipt.undo(self.col)
            raise
        return receipt

    def add_notes(self, drafts, model, deck_id: int) -> WriteReceipt:
        receipt = WriteReceipt("Added cards")
        note_ids = []
        try:
            for draft in drafts:
                note = self.col.new_note(model)
                for name, value in draft.fields.items():
                    if name not in note:
                        raise WriteError(f"Unknown note field: {name}")
                    note[name] = value
                result = self.col.add_note(note, deck_id)
                note_id = result if isinstance(result, int) and result > 0 else getattr(note, "id", 0)
                if note_id:
                    note_ids.append(note_id)
        except Exception:
            self._remove_notes(self.col, note_ids)
            raise
        if note_ids:
            receipt.operations.append(WriteOperation("added", {"note_ids": note_ids}))
        return receipt

    def delete_cards(self, card_ids: list[int]) -> WriteReceipt:
        receipt = WriteReceipt("Deleted cards")
        for card_id in card_ids:
            card = self.col.get_card(card_id)
            note = card.note()
            model = note.note_type() if hasattr(note, "note_type") else None
            model_id = int(model.get("id", 0)) if model else int(getattr(note, "mid", 0) or 0)
            data = {
                "card_id": card_id,
                "fields": {name: note[name] for name in note.keys()},
                "tags": list(note.tags),
                "deck_id": getattr(card, "odid", 0) or card.did,
                "model_id": model_id,
                "model_name": str(model.get("name", "")) if model else "",
            }
            self.col.remove_cards_and_orphaned_notes([card_id])
            receipt.operations.append(WriteOperation("deleted", data))
            receipt.lossy = True
        return receipt

    def apply_action(self, action: dict, current_card_id: int, current_deck: str) -> WriteReceipt:
        kind = action.get("type")
        if kind == "add_card":
            deck_id = self.col.decks.id_for_name(action.get("deck", current_deck))
            if deck_id is None:
                raise WriteError("The requested deck does not exist.")
            model = self.col.models.by_name(action.get("notetype", "Basic"))
            if model is None:
                raise WriteError("The requested note type does not exist.")
            fields = [str(field.get("name", "")) for field in model.get("flds", [])]
            names = [name for name in fields if name]
            if len(names) < 2:
                raise WriteError("The note type needs two fields.")
            fields = {
                names[0]: safe_html(action["front"]),
                names[1]: safe_html(action["back"]),
            }
            from types import SimpleNamespace

            return self.add_notes([SimpleNamespace(fields=fields)], model, deck_id)
        if kind == "delete_card":
            return self.delete_cards([action.get("card_id", current_card_id)])
        if kind == "edit_card":
            card = self.col.get_card(action.get("card_id", current_card_id))
            note = card.note()
            names = note.keys()
            changes = []
            for key, position in (("front", 0), ("back", 1)):
                if key in action:
                    if len(names) <= position:
                        raise WriteError(f"Note has no {key} field.")
                    changes.append(FieldChange(
                        int(note.id), names[position], note[names[position]],
                        safe_html(action[key]),
                    ))
            for name, value in action.get("fields", {}).items():
                if name not in note:
                    raise WriteError(f"Unknown note field: {name}")
                changes.append(FieldChange(
                    int(note.id), name, note[name], safe_html(value),
                ))
            return self.apply_fields(changes)
        if kind == "set_review_options":
            deck_id = self.col.decks.id_for_name(action.get("deck", current_deck))
            if deck_id is None:
                raise WriteError("The requested deck does not exist.")
            deck = self.col.decks.get(deck_id, default=False)
            if not deck or "conf" not in deck:
                raise WriteError("Review options require a normal deck.")
            preset = self.col.decks.get_config(int(deck["conf"]))
            if preset is None:
                raise WriteError("Deck preset not found.")
            before = copy.deepcopy(preset)
            for key, value in action["changes"].items():
                if "." in key:
                    group, field_name = key.split(".", 1)
                    preset[group][field_name] = value
                else:
                    preset[key] = value
            self.col.decks.update_config(preset)
            receipt = WriteReceipt("Review options")
            receipt.operations.append(WriteOperation("preset", {"before": before, "deck_id": deck_id}))
            return receipt
        raise WriteError("Unsupported Anki action.")


def escaped_field_value(value: str) -> str:
    return html.escape(value).replace("\n", "<br>")
