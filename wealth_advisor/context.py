"""SessionContext — the shared state object threaded through a single run.

The orchestrator creates one ``SessionContext`` per run and passes it to each
agent. It carries the ``run_id``, the short-term memory, and typed "handoff"
slots that agents populate as the pipeline progresses (the DataFetcher fills
``profile``; the Analyzer fills ``analysis``; the Advisor fills ``report``).

Keeping handoff explicit (rather than a loose dict) keeps agent contracts
readable and makes the data flow easy to follow.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .memory.short_term import SessionMemory
from .schemas import AdvisoryReport, AnalysisResult, ClientProfile, HITLRecord


@dataclass
class SessionContext:
    run_id: str
    client_id: str | None = None
    started_at: float = field(default_factory=time.time)
    memory: SessionMemory = field(default_factory=SessionMemory)

    # Handoff slots, populated in order by the agents.
    raw_input: dict[str, Any] | None = None
    profile: ClientProfile | None = None
    analysis: AnalysisResult | None = None
    report: AdvisoryReport | None = None

    # Most recent prior-run summary for this client (from long-term memory),
    # injected by the orchestrator so the Analyzer can detect trends/recurrence.
    history: dict[str, Any] | None = None

    # Human-in-the-loop outcome, set by the orchestrator at the checkpoint.
    hitl: HITLRecord | None = None

    # Convenience wrappers around the short-term memory ---------------------
    def record_event(self, kind: str, **data: Any) -> None:
        self.memory.record_event(kind, **data)

    def remember(self, key: str, value: Any) -> None:
        self.memory.remember(key, value)

    def note(self, message: str) -> None:
        self.memory.note(message)

    @property
    def elapsed_seconds(self) -> float:
        return round(time.time() - self.started_at, 3)
