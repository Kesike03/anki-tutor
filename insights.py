"""Local, read-only collection insights for the Anki Tutor home screen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

try:
    from .context import readable_text
except ImportError:
    from context import readable_text


DAY_MS = 86_400_000


@dataclass(frozen=True)
class WeakCard:
    card_id: int
    note_id: int
    front: str
    back: str
    deck: str
    tags: tuple[str, ...]
    lapses: int
    reps: int
    ease: int
    interval: int
    recent_again: int
    memory_difficulty: float | None
    reasons: tuple[str, ...]

    @property
    def score(self) -> float:
        ease_penalty = max(0, 2500 - self.ease) / 100
        difficulty = self.memory_difficulty or 0
        return (
            self.lapses * 4
            + self.recent_again * 3
            + ease_penalty
            + difficulty * 2
            + (3 if "leech" in self.tags else 0)
        )


@dataclass(frozen=True)
class WeakArea:
    name: str
    count: int


@dataclass
class CollectionInsights:
    due: int = 0
    new: int = 0
    learning: int = 0
    total: int = 0
    leeches: int = 0
    reviews_30d: int = 0
    retention_30d: float | None = None
    today_reviews: int = 0
    today_again: int = 0
    weak_cards: list[WeakCard] = field(default_factory=list)
    weak_decks: list[WeakArea] = field(default_factory=list)
    weak_tags: list[WeakArea] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def weak_count(self) -> int:
        return len(self.weak_cards)

    def context_text(self) -> str:
        retention = (
            f"{self.retention_30d * 100:.0f}%"
            if self.retention_30d is not None else "unknown"
        )
        lines = [
            "Anki collection snapshot (local, read-only):",
            f"- Cards: {self.total}; due now: {self.due}; new: {self.new}; learning: {self.learning}",
            f"- Leeches: {self.leeches}; 30-day reviews: {self.reviews_30d}; "
            f"30-day retention: {retention}",
            f"- Today: {self.today_reviews} reviews, {self.today_again} rated Again",
        ]
        if self.weak_decks:
            lines.append(
                "- Weak decks: "
                + ", ".join(f"{area.name} ({area.count})" for area in self.weak_decks[:6])
            )
        if self.weak_tags:
            lines.append(
                "- Weak tags: "
                + ", ".join(f"{area.name} ({area.count})" for area in self.weak_tags[:8])
            )
        if self.weak_cards:
            lines.append("- Weak-card examples:")
            for card in self.weak_cards[:8]:
                lines.append(
                    f"  - {card.deck}: {card.front[:140]} "
                    f"[{', '.join(card.reasons)}]"
                )
        return "\n".join(lines)

    def focus_lines(self) -> list[str]:
        lines = []
        if self.due or self.new or self.learning:
            lines.append(
                f"Today has {self.due} due reviews, {self.new} new cards, "
                f"and {self.learning} learning cards."
            )
        if self.leeches:
            lines.append(
                f"{self.leeches} leech cards deserve error-focused review: "
                "explain the miss before looking at the answer."
            )
        if self.retention_30d is not None and self.retention_30d < 0.85:
            lines.append(
                "Recent retention is below 85%; consider reducing new-card load "
                "before adding more material."
            )
        if self.weak_tags:
            labels = ", ".join(area.name for area in self.weak_tags[:5])
            lines.append(
                f"Weak topics: {labels}. Use short, mixed retrieval sets rather than rereading."
            )
        if not lines:
            lines.append(
                "No weak-area signal yet. Review a few cards and refresh this analysis."
            )
        return lines


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _find(col, query: str) -> list[int]:
    try:
        return list(col.find_cards(query))
    except Exception:
        return []


def _count(col, query: str) -> int:
    try:
        return len(col.find_cards(query))
    except Exception:
        return 0


def _sql_one(col, sql: str, args: Iterable = ()) -> tuple:
    try:
        rows = col.db.all(sql, *args)
    except Exception:
        return ()
    return rows[0] if rows else ()


def _retention(col, cutoff: int) -> tuple[int, float | None]:
    row = _sql_one(
        col,
        "SELECT COUNT(*), SUM(CASE WHEN ease > 1 THEN 1 ELSE 0 END) "
        "FROM revlog WHERE id >= ? AND ease > 0",
        (cutoff,),
    )
    if not row:
        return 0, None
    total = _int(row[0])
    passed = _int(row[1]) if len(row) > 1 else 0
    return total, (passed / total if total else None)


def _recent_again(col, cutoff: int) -> dict[int, int]:
    try:
        rows = col.db.all(
            "SELECT cid, COUNT(*) FROM revlog "
            "WHERE ease = 1 AND id >= ? GROUP BY cid",
            cutoff,
        )
    except Exception:
        return {}
    return {_int(card_id): _int(count) for card_id, count in rows}


def _card_front_back(card) -> tuple[str, str]:
    try:
        render = card.render_output()
        return (
            readable_text(render.question_text)[:260],
            readable_text(render.answer_text)[:260],
        )
    except Exception:
        return "", ""


def _reason(card, recent_again: int) -> tuple[list[str], list[str]]:
    tags = tuple(str(tag) for tag in getattr(card.note(), "tags", ()))
    reasons = []
    if "leech" in tags:
        reasons.append("leech")
    if _int(getattr(card, "lapses", 0)) >= 2:
        reasons.append("lapses>=2")
    if recent_again:
        reasons.append(f"again x{recent_again}")
    if _int(getattr(card, "factor", 0)) and _int(card.factor) < 2200:
        reasons.append("low ease")
    memory = getattr(card, "memory_state", None)
    if memory is not None and _float(getattr(memory, "difficulty", None), 0) >= 7:
        reasons.append("high FSRS difficulty")
    if not reasons:
        reasons.append("recent difficulty")
    return reasons, list(tags)


def analyze(col, limit: int = 25, now: datetime | None = None) -> CollectionInsights:
    """Read local Anki data without modifying scheduling or card content."""
    limit = max(1, min(50, int(limit)))
    now = now or datetime.now().astimezone()
    cutoff = int((now - timedelta(days=30)).timestamp() * 1000)
    today = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    insights = CollectionInsights(
        due=_count(col, "is:due"),
        new=_count(col, "is:new"),
        learning=_count(col, "is:learn"),
        leeches=_count(col, "is:leech"),
        reviews_30d=0,
        today_reviews=0,
        today_again=0,
    )
    total_row = _sql_one(col, "SELECT COUNT(*) FROM cards")
    try:
        insights.total = _int(total_row[0]) if total_row else len(col.find_cards(""))
    except Exception:
        insights.total = 0
    reviews, retention = _retention(col, cutoff)
    insights.reviews_30d = reviews
    insights.retention_30d = retention
    today_row = _sql_one(
        col,
        "SELECT COUNT(*), SUM(CASE WHEN ease = 1 THEN 1 ELSE 0 END) "
        "FROM revlog WHERE id >= ? AND ease > 0",
        (today,),
    )
    if today_row:
        insights.today_reviews = _int(today_row[0])
        insights.today_again = _int(today_row[1]) if len(today_row) > 1 else 0
    recent = _recent_again(col, cutoff)

    candidates: dict[int, str] = {}
    for query, reason in (
        ("is:leech", "leech"),
        ("prop:lapses>=2 -is:suspended", "lapses"),
        ("rated:14:1 -is:suspended", "recent"),
    ):
        for card_id in _find(col, query):
            candidates.setdefault(_int(card_id), reason)
    cards = []
    for card_id, seed in candidates.items():
        try:
            card = col.get_card(card_id)
            front, back = _card_front_back(card)
            reasons, tags = _reason(card, recent.get(card_id, 0))
            if seed not in reasons and seed != "recent":
                reasons.append(seed)
            memory = getattr(card, "memory_state", None)
            cards.append(WeakCard(
                card_id=card_id,
                note_id=_int(getattr(card, "nid", 0)),
                front=front,
                back=back,
                deck=str(col.decks.name(card.current_deck_id())),
                tags=tuple(tags),
                lapses=_int(getattr(card, "lapses", 0)),
                reps=_int(getattr(card, "reps", 0)),
                ease=_int(getattr(card, "factor", 0)),
                interval=_int(getattr(card, "ivl", 0)),
                recent_again=recent.get(card_id, 0),
                memory_difficulty=_float(getattr(memory, "difficulty", None)) if memory else None,
                reasons=tuple(dict.fromkeys(reasons)),
            ))
        except Exception as error:
            insights.skipped.append(f"{card_id}: {error}")
    cards.sort(key=lambda item: item.score, reverse=True)
    insights.weak_cards = cards[:limit]
    insights.weak_decks = _areas(card.deck for card in insights.weak_cards)
    insights.weak_tags = _areas(
        tag for card in insights.weak_cards for tag in card.tags
        if tag not in {"leech", "marked"}
    )
    return insights


def _areas(values: Iterable[str], limit: int = 8) -> list[WeakArea]:
    counts: dict[str, int] = {}
    for value in values:
        value = str(value).strip()
        if value:
            counts[value] = counts.get(value, 0) + 1
    return [
        WeakArea(name, count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def brief(insights: CollectionInsights) -> str:
    """Return a compact local study brief suitable for copying or sending to a tutor."""
    lines = ["Anki Tutor — study brief (local data, read-only)"]
    lines.extend(insights.focus_lines())
    if insights.weak_decks:
        lines.append("Weak decks: " + ", ".join(f"{a.name} ({a.count})" for a in insights.weak_decks))
    if insights.weak_tags:
        lines.append("Weak tags: " + ", ".join(f"{a.name} ({a.count})" for a in insights.weak_tags))
    if insights.weak_cards:
        lines.append("Weak cards:")
        for card in insights.weak_cards[:10]:
            lines.append(
                f"- {card.deck}: {card.front[:180]} — {', '.join(card.reasons)}"
            )
    lines.append(
        "This is a focus summary, not a review order. Anki's scheduler remains authoritative."
    )
    return "\n".join(lines)
