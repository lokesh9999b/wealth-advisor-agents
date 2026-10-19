"""Tool: optional LLM narrative generation via the Anthropic SDK (Claude).

This is the ONLY place the system talks to an LLM, and it is entirely optional.
If the ``anthropic`` package is not installed or no API key is configured, the
tool returns ``ok=False`` and the AdvisorAgent falls back to a deterministic
templated narrative — so the whole pipeline runs with zero external
dependencies.

The deterministic analysis (metrics + anomalies) is never produced by the LLM;
the LLM only turns already-computed, structured findings into advisor-friendly
prose. This keeps results reproducible and prevents the model from inventing
numbers.
"""

from __future__ import annotations

from typing import Any

from ..config import settings
from ..errors import ToolError
from .base import Tool


class LLMTool(Tool):
    name = "llm"
    description = "Generate a natural-language advisory narrative from findings."
    retryable = False  # the anthropic SDK already retries 429/5xx internally

    def _execute(
        self, system: str = "", prompt: str = "", max_tokens: int = 1024, **_: Any
    ) -> str:
        if not settings.anthropic_api_key:
            raise ToolError("no ANTHROPIC_API_KEY configured")

        try:
            import anthropic  # imported lazily — optional dependency
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ToolError("anthropic SDK not installed") from exc

        try:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model=settings.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - normalize any SDK/network error
            raise ToolError(f"LLM call failed: {exc}") from exc

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        if not text:
            raise ToolError("LLM returned no text content")
        return text
