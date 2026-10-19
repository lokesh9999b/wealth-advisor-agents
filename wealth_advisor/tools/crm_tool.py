"""Tool: a simulated external CRM API.

Reads from a local JSON "database" but behaves like a remote API: it has
latency, can be forced to fail (to exercise retries + fallback), and returns a
clean "not found" for unknown clients rather than raising.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config import CRM_DB_PATH, settings
from ..errors import ToolError
from ..schemas import CRMProfile
from .base import Tool


class CRMTool(Tool):
    name = "crm_api"
    description = "Fetch a client's CRM profile (risk tolerance, KYC, notes)."
    retryable = True  # simulated network call — transient failures are retried

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._db_path = db_path or CRM_DB_PATH
        self._db: dict[str, Any] | None = None  # lazy-loaded cache

    def _load_db(self) -> dict[str, Any]:
        if self._db is None:
            if not self._db_path.exists():
                raise ToolError(f"CRM database unavailable: {self._db_path}")
            with self._db_path.open("r", encoding="utf-8") as fh:
                self._db = json.load(fh)
        return self._db

    def _execute(self, client_id: str | None = None, **_: Any) -> CRMProfile | None:
        if not client_id:
            raise ToolError("client_id is required to query the CRM")

        # Simulate a flaky/unavailable external service on demand.
        if settings.simulate_crm_failure:
            raise ToolError("simulated CRM API outage (WA_SIMULATE_CRM_FAILURE=1)")

        time.sleep(0.03)  # simulate network latency

        record = self._load_db().get(client_id)
        if record is None:
            # Legitimate "no record" — not an error. Caller degrades gracefully.
            return None
        return CRMProfile.from_dict(record)
