"""Tool: a simulated market-data API (benchmarks, index returns, avg fees).

Provides the "additional context via APIs" the assignment asks for. Like the
CRM tool it reads a local JSON file but is treated as an external service.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config import MARKET_DATA_PATH
from ..errors import ToolError
from .base import Tool


class MarketDataTool(Tool):
    name = "market_data"
    description = "Fetch benchmark allocations, index returns, and average fees."
    retryable = True

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self._path = path or MARKET_DATA_PATH
        self._cache: dict[str, Any] | None = None

    def _execute(self, risk_tolerance: str | None = None, **_: Any) -> dict[str, Any]:
        if self._cache is None:
            if not self._path.exists():
                raise ToolError(f"market data unavailable: {self._path}")
            with self._path.open("r", encoding="utf-8") as fh:
                self._cache = json.load(fh)

        time.sleep(0.02)  # simulate network latency

        data = dict(self._cache)  # shallow copy so callers can't mutate cache
        # Attach the benchmark matching the client's risk tolerance, if known.
        benchmarks = data.get("benchmarks", {})
        key = (risk_tolerance or "").lower()
        data["benchmark_for_client"] = benchmarks.get(key)
        return data
