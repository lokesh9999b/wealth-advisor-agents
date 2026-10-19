"""Shared test fixtures and builders."""

from __future__ import annotations

import pytest

from wealth_advisor.schemas import ClientFinancialData
from wealth_advisor.tools.anomaly_tool import AnomalyDetectionTool
from wealth_advisor.tools.base import ToolRegistry
from wealth_advisor.tools.crm_tool import CRMTool
from wealth_advisor.tools.financial_data_tool import FinancialDataTool
from wealth_advisor.tools.market_data_tool import MarketDataTool


def build_offline_registry() -> ToolRegistry:
    """A registry with every tool EXCEPT the LLM, so tests never hit the network.

    The AdvisorAgent falls back to its deterministic template when no ``llm``
    tool is registered, making these tests fully offline and reproducible.
    """
    reg = ToolRegistry()
    for tool in (
        FinancialDataTool(),
        CRMTool(),
        MarketDataTool(),
        AnomalyDetectionTool(),
    ):
        reg.register(tool)
    return reg


def make_financial(
    client_id: str = "T1",
    holdings: list[dict] | None = None,
    cash: float = 10000,
    transactions: list[dict] | None = None,
    target: dict | None = None,
) -> ClientFinancialData:
    """Build a ClientFinancialData from minimal pieces for unit tests."""
    return ClientFinancialData.from_dict(
        {
            "client_id": client_id,
            "name": f"Test {client_id}",
            "accounts": [
                {
                    "account_id": "A1",
                    "type": "brokerage",
                    "cash_balance": cash,
                    "holdings": holdings or [],
                }
            ],
            "transactions": transactions or [],
            "target_allocation": target or {},
        }
    )


@pytest.fixture
def balanced_financial() -> ClientFinancialData:
    """A healthy, on-target portfolio with no anomalies."""
    return make_financial(
        holdings=[
            # Equity split so no single holding exceeds the 25% concentration limit.
            {"symbol": "VTI", "asset_class": "equity", "quantity": 1, "price": 20000},
            {"symbol": "SPY", "asset_class": "equity", "quantity": 1, "price": 20000},
            {"symbol": "AAPL", "asset_class": "equity", "quantity": 1, "price": 20000},
            {"symbol": "BND", "asset_class": "fixed_income", "quantity": 1, "price": 15000},
            {"symbol": "AGG", "asset_class": "fixed_income", "quantity": 1, "price": 15000},
        ],
        cash=10000,  # 10% of 100k
        transactions=[
            {"date": "2026-09-01", "type": "buy", "symbol": "VTI", "amount": 1000},
            {"date": "2026-09-08", "type": "buy", "symbol": "BND", "amount": 1100},
            {"date": "2026-09-15", "type": "buy", "symbol": "VTI", "amount": 950},
            {"date": "2026-09-22", "type": "buy", "symbol": "BND", "amount": 1050},
        ],
        target={"equity": 0.60, "fixed_income": 0.30, "cash": 0.10},
    )
