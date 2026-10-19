"""Tests for the tool abstraction, registry, and individual tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from wealth_advisor.config import CLIENTS_DIR
from wealth_advisor.errors import ToolNotFoundError
from wealth_advisor.tools.base import Tool, ToolRegistry, ToolResult
from wealth_advisor.tools.crm_tool import CRMTool
from wealth_advisor.tools.financial_data_tool import FinancialDataTool


class _OkTool(Tool):
    name = "ok_tool"

    def _execute(self, **kwargs):
        return {"value": 42}


def test_tool_returns_envelope_and_never_raises():
    res = _OkTool().run()
    assert isinstance(res, ToolResult)
    assert res.ok and res.data == {"value": 42}
    assert res.meta["tool"] == "ok_tool"
    assert "latency_ms" in res.meta


def test_registry_resolves_by_name_and_errors_on_missing():
    reg = ToolRegistry()
    tool = _OkTool()
    reg.register(tool)
    assert reg.get("ok_tool") is tool
    assert reg.has("ok_tool")
    with pytest.raises(ToolNotFoundError):
        reg.get("does_not_exist")


def test_financial_data_tool_loads_valid_file():
    res = FinancialDataTool().run(path=str(CLIENTS_DIR / "client_001.json"))
    assert res.ok
    assert res.data.client_id == "C001"
    assert len(res.data.accounts) == 1


def test_financial_data_tool_rejects_missing_client_id():
    res = FinancialDataTool().run(data={"name": "no id"})
    assert not res.ok
    assert "client_id" in res.error


def test_financial_data_tool_handles_missing_file():
    res = FinancialDataTool().run(path="does/not/exist.json")
    assert not res.ok


def test_crm_tool_returns_none_for_unknown_client():
    res = CRMTool().run(client_id="ZZZ_UNKNOWN")
    assert res.ok  # "not found" is a success with no data
    assert res.data is None


def test_crm_tool_fails_and_retries_when_db_missing(tmp_path: Path):
    tool = CRMTool(db_path=tmp_path / "no_such_db.json")
    res = tool.run(client_id="C001")
    assert not res.ok
    # retryable tool should have attempted more than once
    assert res.meta["attempts"] >= 2


def test_market_value_derived_from_quantity_and_price():
    # client_003 has a holding with no explicit market_value.
    res = FinancialDataTool().run(path=str(CLIENTS_DIR / "client_003.json"))
    assert res.ok
    holding = res.data.accounts[0].holdings[0]
    assert holding.market_value == holding.quantity * holding.price
