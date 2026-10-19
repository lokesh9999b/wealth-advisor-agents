"""Tests for the individual agents (data fetching, analysis, advice)."""

from __future__ import annotations

from wealth_advisor.agents.advisor import AdvisorAgent
from wealth_advisor.agents.analyzer import AnalyzerAgent
from wealth_advisor.agents.data_fetcher import DataFetcherAgent
from wealth_advisor.config import CLIENTS_DIR
from wealth_advisor.context import SessionContext
from wealth_advisor.schemas import STATUS_FAILED, STATUS_PARTIAL

from .conftest import build_offline_registry


def _ctx(path: str) -> SessionContext:
    return SessionContext(run_id="test", raw_input={"path": path})


def test_data_fetcher_degrades_without_crm_record():
    reg = build_offline_registry()
    ctx = _ctx(str(CLIENTS_DIR / "client_003.json"))  # C003 is not in the CRM
    res = DataFetcherAgent(reg).execute(ctx)
    assert res.status == STATUS_PARTIAL
    assert ctx.profile.degraded is True
    assert ctx.profile.crm is None
    assert ctx.profile.warnings  # a warning was recorded


def test_data_fetcher_fatal_on_missing_client_id():
    reg = build_offline_registry()
    ctx = SessionContext(run_id="test", raw_input={"data": {"name": "no id"}})
    res = DataFetcherAgent(reg).execute(ctx)
    assert res.status == STATUS_FAILED
    assert ctx.profile is None


def test_agent_chain_produces_template_advice():
    reg = build_offline_registry()
    ctx = _ctx(str(CLIENTS_DIR / "client_002.json"))

    assert DataFetcherAgent(reg).execute(ctx).ok
    assert AnalyzerAgent(reg).execute(ctx).ok
    assert AdvisorAgent(reg).execute(ctx).ok

    report = ctx.report
    assert report.narrative_source == "template"  # no llm tool registered
    assert report.risk_posture == "high"
    assert report.anomalies
    assert report.recommendations
    # KYC recommendation comes from the CRM profile (C002 is 'pending').
    assert any("KYC" in r.title for r in report.recommendations)
