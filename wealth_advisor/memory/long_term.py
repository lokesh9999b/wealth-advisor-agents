"""Long-term memory — persistent, cross-run history keyed by client.

Implemented as a single JSON document on disk. It stores a compact summary of
each run (AUM, anomaly types, risk posture, timestamp) so later runs can detect
*recurring* anomalies and material changes since the previous review.

Trade-off: a JSON file is intentionally simple and dependency-free. For
production this would become SQLite (concurrency, querying) or a vector store
(semantic recall of advisor notes). The interface here is deliberately small so
that swap is localized.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import MEMORY_STORE_PATH
from ..logging_config import get_logger

log = get_logger("memory.long_term")


class LongTermMemory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or MEMORY_STORE_PATH
        self._store: dict[str, list[dict[str, Any]]] = self._load()

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("memory store is not a JSON object")
            return data
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            # Corrupt/unreadable store must not break a run — start fresh.
            log.warning("Could not read long-term memory (%s); starting empty.", exc)
            return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as fh:
                json.dump(self._store, fh, indent=2)
        except OSError as exc:  # pragma: no cover - disk failure is rare
            log.error("Failed to persist long-term memory: %s", exc)

    # -- read ---------------------------------------------------------------
    def get_history(self, client_id: str) -> list[dict[str, Any]]:
        """All stored run summaries for a client (oldest first)."""
        return list(self._store.get(client_id, []))

    def get_last(self, client_id: str) -> dict[str, Any] | None:
        """The most recent stored run summary for a client, if any."""
        history = self._store.get(client_id, [])
        return history[-1] if history else None

    # -- write --------------------------------------------------------------
    def append(self, client_id: str, summary: dict[str, Any]) -> None:
        """Append a run summary for a client and persist to disk."""
        self._store.setdefault(client_id, []).append(summary)
        self._save()
        log.debug("Stored long-term memory entry for client %s", client_id)
