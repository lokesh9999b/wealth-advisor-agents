"""Tool abstraction: uniform interface + result envelope + registry.

Design goals (directly mapped to the assignment's "Tool Usage Abstraction"):
  * Agents depend on the :class:`Tool` interface, never on raw implementations.
  * Tools never raise into their caller — every call returns a :class:`ToolResult`
    envelope (``ok`` / ``data`` / ``error`` / ``meta``). This keeps agent code
    free of scattered try/except and makes error handling uniform.
  * Cross-cutting concerns (timing, logging, retries) live here in the base
    ``run`` method, so concrete tools only implement ``_execute``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..config import settings
from ..errors import DataValidationError, ToolError, ToolNotFoundError
from ..logging_config import get_logger


@dataclass
class ToolResult:
    """Uniform envelope returned by every tool call."""

    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # Avoid dumping large payloads into the trace; summarize instead.
        return {"ok": self.ok, "error": self.error, "meta": self.meta}


class Tool(ABC):
    """Base class for all tools.

    Subclasses set ``name`` / ``description`` and implement ``_execute``.
    ``_execute`` returns the raw result on success, or raises:
      * :class:`DataValidationError` for deterministic bad input (not retried)
      * :class:`ToolError` for transient failures (retried if ``retryable``)
    """

    name: str = "tool"
    description: str = ""
    retryable: bool = False

    def __init__(self) -> None:
        self._log = get_logger(f"tool.{self.name}")

    @abstractmethod
    def _execute(self, **kwargs: Any) -> Any:  # pragma: no cover - abstract
        ...

    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool, never raising. Handles timing, retries, logging."""
        attempts = (settings.api_max_retries + 1) if self.retryable else 1
        start = time.perf_counter()
        last_error: str | None = None
        attempt = 0

        for attempt in range(1, attempts + 1):
            try:
                data = self._execute(**kwargs)
                latency = round((time.perf_counter() - start) * 1000, 1)
                self._log.debug(
                    "ok in %sms (attempt %d/%d)", latency, attempt, attempts
                )
                return ToolResult(
                    ok=True,
                    data=data,
                    meta={
                        "tool": self.name,
                        "latency_ms": latency,
                        "attempts": attempt,
                    },
                )
            except DataValidationError as exc:
                # Deterministic — retrying won't help.
                last_error = f"validation: {exc}"
                self._log.error("%s", last_error)
                break
            except ToolError as exc:
                last_error = str(exc)
                self._log.warning(
                    "failed attempt %d/%d: %s", attempt, attempts, exc
                )
                if attempt < attempts:
                    time.sleep(settings.api_retry_backoff_seconds * attempt)
                    continue
            except Exception as exc:  # noqa: BLE001 - last-resort safety net
                last_error = f"unexpected: {exc}"
                self._log.exception("unexpected error in tool '%s'", self.name)
                break

        latency = round((time.perf_counter() - start) * 1000, 1)
        return ToolResult(
            ok=False,
            error=last_error,
            meta={"tool": self.name, "latency_ms": latency, "attempts": attempt},
        )


class ToolRegistry:
    """A name -> Tool registry. Agents request tools by name only."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._log = get_logger("tool.registry")

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            self._log.warning("overwriting already-registered tool '%s'", tool.name)
        self._tools[tool.name] = tool
        self._log.debug("registered tool '%s'", tool.name)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"No tool named '{name}' is registered") from exc

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)
