"""AnalyzerAgent — computes portfolio metrics and detects anomalies.

It combines deterministic portfolio math (``analytics.compute_portfolio_metrics``)
with the ``anomaly_detection`` tool, and compares the current run against the
client's most recent prior run (long-term memory) to surface trends and mark
recurring anomalies.
"""

from __future__ import annotations

from typing import Any

from ..analytics import compute_portfolio_metrics
from ..context import SessionContext
from ..schemas import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    AnalysisResult,
    PortfolioMetrics,
)
from .base import Agent, AgentResult


class AnalyzerAgent(Agent):
    name = "analyzer"

    def execute(self, context: SessionContext) -> AgentResult:
        result = AgentResult(agent=self.name)
        profile = context.profile
        if profile is None:  # pragma: no cover - orchestrator guarantees ordering
            result.status = STATUS_FAILED
            result.errors.append("no client profile available to analyze")
            return result

        # --- Deterministic metrics ----------------------------------------
        metrics: PortfolioMetrics = compute_portfolio_metrics(profile.financial)
        context.remember("total_aum", metrics.total_aum)
        self.log.info(
            "computed metrics: AUM=%.0f, cash=%.0f%%, top=%s",
            metrics.total_aum,
            metrics.cash_pct * 100,
            metrics.top_holding.get("symbol", "-"),
        )

        # --- Anomaly detection (via tool) ---------------------------------
        market_avg_fee = (profile.market_context or {}).get("average_fee_ratio")
        anomaly_tool = self.tools.get("anomaly_detection")
        res = anomaly_tool.run(
            financial=profile.financial,
            metrics=metrics,
            history=context.history,
            market_avg_fee=market_avg_fee,
        )
        self._trace_tool(context, res)
        if not res.ok:
            # Anomaly detection is core; if it genuinely fails, report but still
            # return metrics so the advisor can produce a (reduced) report.
            self.log.error("anomaly detection failed: %s", res.error)
            result.errors.append(f"anomaly_detection: {res.error}")
            analysis = AnalysisResult(metrics=metrics)
        else:
            anomalies = res.data["anomalies"]
            analysis = AnalysisResult(
                metrics=metrics,
                anomalies=anomalies,
                risk_signals=res.data["risk_signals"],
                memory_comparison=self._compare_to_history(context, metrics, anomalies),
            )
            self.log.info(
                "detected %d anomaly(ies): %s",
                len(anomalies),
                ", ".join(a.type for a in anomalies) or "none",
            )

        context.analysis = analysis
        result.output = analysis
        result.status = STATUS_SUCCESS
        return result

    def _compare_to_history(
        self, context: SessionContext, metrics: PortfolioMetrics, anomalies: list
    ) -> dict[str, Any]:
        """Build a trend comparison against the previous run, if available."""
        prior = context.history
        if not prior:
            context.note("No prior run on record — this is the first review.")
            return {"first_review": True}

        comparison: dict[str, Any] = {"first_review": False}
        prior_aum = prior.get("total_aum")
        if prior_aum:
            change = metrics.total_aum - prior_aum
            comparison["aum_change"] = round(change, 2)
            comparison["aum_change_pct"] = round(change / prior_aum, 4) if prior_aum else None

        prior_types = set(prior.get("anomaly_types", []))
        current_types = {a.type for a in anomalies}
        comparison["new_anomaly_types"] = sorted(current_types - prior_types)
        comparison["recurring_anomaly_types"] = sorted(current_types & prior_types)
        comparison["resolved_anomaly_types"] = sorted(prior_types - current_types)
        comparison["last_reviewed"] = prior.get("generated_at")

        if comparison.get("recurring_anomaly_types"):
            context.note(
                "Recurring issues since last review: "
                + ", ".join(comparison["recurring_anomaly_types"])
            )
        return comparison
