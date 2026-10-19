"""Tool: load, validate, and normalize client financial data (JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import DataValidationError, ToolError
from ..schemas import ClientFinancialData
from .base import Tool


class FinancialDataTool(Tool):
    name = "financial_data"
    description = "Load and validate a client's financial data from JSON."
    retryable = False  # reading a local file is deterministic

    def _execute(
        self,
        path: str | Path | None = None,
        data: dict[str, Any] | None = None,
        **_: Any,
    ) -> ClientFinancialData:
        """Return a validated :class:`ClientFinancialData`.

        Accepts either a file ``path`` or an already-parsed ``data`` dict.
        Raises :class:`DataValidationError` on malformed/empty input.
        """
        if data is None:
            if path is None:
                raise DataValidationError("either 'path' or 'data' is required")
            data = self._read_file(Path(path))

        if not isinstance(data, dict):
            raise DataValidationError("client data must be a JSON object")
        if not data.get("client_id"):
            raise DataValidationError("client data is missing required 'client_id'")

        try:
            return ClientFinancialData.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise DataValidationError(f"could not parse client data: {exc}") from exc

    @staticmethod
    def _read_file(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise DataValidationError(f"client data file not found: {path}")
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError as exc:
            raise DataValidationError(f"invalid JSON in {path.name}: {exc}") from exc
        except OSError as exc:  # pragma: no cover - rare IO error
            raise ToolError(f"could not read {path}: {exc}") from exc
