"""Agent abstraction.

Every agent receives the shared :class:`ToolRegistry` and operates on the
:class:`SessionContext`. Agents reach the outside world *only* through tools
resolved by name from the registry — they never import a concrete tool.

``execute`` returns an :class:`AgentResult` describing what happened (status +
any errors/warnings). The orchestrator inspects these to decide how to proceed
(e.g. continue in degraded mode vs. abort).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..context import SessionContext
from ..logging_config import get_logger
from ..schemas import STATUS_SUCCESS
from ..tools.base import ToolRegistry


@dataclass
class AgentResult:
    agent: str
    status: str = STATUS_SUCCESS
    output: Any = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status != "failed"


class Agent(ABC):
    name: str = "agent"

    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools
        self.log = get_logger(f"agent.{self.name}")

    @abstractmethod
    def execute(self, context: SessionContext) -> AgentResult:  # pragma: no cover
        ...

    # Small helper so subclasses get consistent tracing for free.
    def _trace_tool(self, context: SessionContext, result: Any) -> None:
        meta = getattr(result, "meta", {}) or {}
        context.record_event(
            "tool_call",
            agent=self.name,
            tool=meta.get("tool"),
            ok=getattr(result, "ok", None),
            latency_ms=meta.get("latency_ms"),
            attempts=meta.get("attempts"),
            error=getattr(result, "error", None),
        )
