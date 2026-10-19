"""Short-term memory — the working memory for a single advisory run.

This is a lightweight, in-process scratchpad that lives for the duration of one
run. Agents write intermediate facts, decisions, and a structured event trace
here; the orchestrator reads it to build the run trace artifact and to hand a
summary to long-term memory at the end.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionMemory:
    """Per-run working memory (short-term)."""

    # Key/value facts discovered during the run (e.g. "total_aum": 123456).
    facts: dict[str, Any] = field(default_factory=dict)
    # Free-form notes / decisions, in order.
    notes: list[str] = field(default_factory=list)
    # Structured, timestamped event trace (tool calls, routing, agent steps).
    events: list[dict[str, Any]] = field(default_factory=list)

    def remember(self, key: str, value: Any) -> None:
        self.facts[key] = value

    def recall(self, key: str, default: Any = None) -> Any:
        return self.facts.get(key, default)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def record_event(self, kind: str, **data: Any) -> None:
        """Append a timestamped event to the trace."""
        self.events.append({"t": round(time.time(), 3), "kind": kind, **data})

    def to_dict(self) -> dict[str, Any]:
        return {"facts": self.facts, "notes": self.notes, "events": self.events}
