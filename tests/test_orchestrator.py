"""End-to-end tests for the orchestrated pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from wealth_advisor.agents.orchestrator import OrchestratorAgent
from wealth_advisor.config import CLIENTS_DIR
from wealth_advisor.errors import PipelineError
from wealth_advisor.memory.long_term import LongTermMemory

from .conftest import build_offline_registry


def _orch(tmp_path: Path) -> OrchestratorAgent:
    return OrchestratorAgent(
        tools=build_offline_registry(),
        long_term_memory=LongTermMemory(path=tmp_path / "mem.json"),
    )


def _run(orch: OrchestratorAgent, client: str):
    return orch.run(
        run_id="testrun",
        raw_input={"path": str(CLIENTS_DIR / client)},
        interactive=False,
        auto_approve=True,
    )


def test_pipeline_flags_risky_client(tmp_path):
    ctx = _run(_orch(tmp_path), "client_002.json")
    report = ctx.report
    assert report.risk_posture == "high"
    assert len(report.anomalies) >= 5
    assert report.hitl.decision == "approved"
    assert report.hitl.performed is False  # auto-approved (non-interactive)


def test_pipeline_healthy_client_is_stable(tmp_path):
    ctx = _run(_orch(tmp_path), "client_001.json")
    assert ctx.report.risk_posture == "stable"
    assert ctx.report.anomalies == []


def test_pipeline_degrades_on_edge_client(tmp_path):
    ctx = _run(_orch(tmp_path), "client_003.json")
    assert ctx.report.degraded_mode is True


def test_pipeline_raises_on_fatal_input(tmp_path):
    orch = _orch(tmp_path)
    with pytest.raises(PipelineError):
        orch.run(
            run_id="bad",
            raw_input={"data": {"name": "no client id"}},
            auto_approve=True,
        )


def test_long_term_memory_drives_second_run(tmp_path):
    orch = _orch(tmp_path)
    first = _run(orch, "client_002.json")
    assert first.analysis.memory_comparison.get("first_review") is True

    second = _run(orch, "client_002.json")
    comp = second.analysis.memory_comparison
    assert comp.get("first_review") is False
    # Concentration risk recurs between the two identical runs.
    assert "concentration_risk" in comp.get("recurring_anomaly_types", [])
    # Recurring anomalies are flagged on the finding itself.
    assert any(a.recurring for a in second.report.anomalies)


def test_trace_events_recorded(tmp_path):
    ctx = _run(_orch(tmp_path), "client_001.json")
    kinds = {e["kind"] for e in ctx.memory.events}
    assert {"plan", "tool_call", "agent_result"} <= kinds
