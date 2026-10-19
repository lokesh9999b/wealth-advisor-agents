"""Tests for the anomaly-detection tool and portfolio analytics."""

from __future__ import annotations

from wealth_advisor.analytics import compute_portfolio_metrics
from wealth_advisor.schemas import SEVERITY_HIGH
from wealth_advisor.tools.anomaly_tool import AnomalyDetectionTool

from .conftest import make_financial


def _detect(financial, market_avg_fee=0.012, history=None):
    metrics = compute_portfolio_metrics(financial)
    res = AnomalyDetectionTool().run(
        financial=financial, metrics=metrics, market_avg_fee=market_avg_fee, history=history
    )
    assert res.ok, res.error
    return metrics, res.data["anomalies"]


def test_balanced_portfolio_has_no_anomalies(balanced_financial):
    _metrics, anomalies = _detect(balanced_financial)
    assert anomalies == []


def test_concentration_is_flagged_high():
    fin = make_financial(
        holdings=[
            {"symbol": "TSLA", "asset_class": "equity", "quantity": 1, "price": 60000},
            {"symbol": "BND", "asset_class": "fixed_income", "quantity": 1, "price": 40000},
        ],
        cash=0,
    )
    _m, anomalies = _detect(fin)
    conc = [a for a in anomalies if a.type == "concentration_risk"]
    assert conc and conc[0].severity == SEVERITY_HIGH


def test_allocation_drift_detected():
    fin = make_financial(
        holdings=[
            {"symbol": "VTI", "asset_class": "equity", "quantity": 1, "price": 90000},
        ],
        cash=10000,  # equity 90% vs 60% target -> drift +30%
        target={"equity": 0.60, "fixed_income": 0.30, "cash": 0.10},
    )
    _m, anomalies = _detect(fin)
    assert any(a.type == "allocation_drift" for a in anomalies)


def test_drift_skipped_without_target():
    fin = make_financial(
        holdings=[{"symbol": "VTI", "asset_class": "equity", "quantity": 1, "price": 90000}],
        cash=10000,
        target={},  # no target -> drift not computed
    )
    metrics = compute_portfolio_metrics(fin)
    assert metrics.allocation_drift == {}


def test_large_transaction_and_iqr_outlier():
    # Many small txns + one modest outlier (IQR) + one huge (large vs AUM).
    txns = [
        {"date": "2026-08-01", "type": "buy", "symbol": "A", "amount": 1000},
        {"date": "2026-08-02", "type": "buy", "symbol": "B", "amount": 1100},
        {"date": "2026-08-03", "type": "buy", "symbol": "C", "amount": 1050},
        {"date": "2026-08-04", "type": "buy", "symbol": "D", "amount": 950},
        {"date": "2026-08-05", "type": "sell", "symbol": "E", "amount": 15000},  # IQR outlier
        {"date": "2026-08-06", "type": "buy", "symbol": "F", "amount": 60000},   # 30% AUM -> large
    ]
    fin = make_financial(
        holdings=[{"symbol": "VTI", "asset_class": "equity", "quantity": 1, "price": 190000}],
        cash=10000,  # AUM = 200k
        transactions=txns,
    )
    _m, anomalies = _detect(fin)
    types = {a.type for a in anomalies}
    assert "large_transaction" in types
    assert "transaction_outlier" in types


def test_duplicate_transaction_detected():
    txns = [
        {"date": "2026-09-15", "type": "buy", "symbol": "AAPL", "amount": 7000},
        {"date": "2026-09-16", "type": "buy", "symbol": "AAPL", "amount": 7000},
    ]
    fin = make_financial(
        holdings=[{"symbol": "AAPL", "asset_class": "equity", "quantity": 1, "price": 90000}],
        cash=10000,
        transactions=txns,
    )
    _m, anomalies = _detect(fin)
    assert any(a.type == "duplicate_transaction" for a in anomalies)


def test_negative_cash_detected():
    fin = make_financial(
        holdings=[{"symbol": "VTI", "asset_class": "equity", "quantity": 1, "price": 50000}],
        cash=-2000,
    )
    _m, anomalies = _detect(fin)
    neg = [a for a in anomalies if a.type == "negative_cash"]
    assert neg and neg[0].severity == SEVERITY_HIGH


def test_recurring_flag_from_history():
    fin = make_financial(
        holdings=[
            {"symbol": "TSLA", "asset_class": "equity", "quantity": 1, "price": 60000},
            {"symbol": "BND", "asset_class": "fixed_income", "quantity": 1, "price": 40000},
        ],
        cash=0,
    )
    history = {"anomaly_types": ["concentration_risk"]}
    _m, anomalies = _detect(fin, history=history)
    conc = [a for a in anomalies if a.type == "concentration_risk"][0]
    assert conc.recurring is True


def test_empty_portfolio_does_not_crash():
    fin = make_financial(holdings=[], cash=0)
    metrics, anomalies = _detect(fin)
    assert metrics.total_aum == 0
    assert isinstance(anomalies, list)
