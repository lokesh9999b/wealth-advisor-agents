"""OrchestratorAgent — the central coordinator.

It owns the execution flow and routing: it instantiates the specialized agents,
runs them in order, threads the shared :class:`SessionContext` between them,
injects long-term memory, drives the HITL checkpoint, and persists results.

The pipeline is intentionally a fixed, inspectable sequence (not an
LLM-planned one) — appropriate for a regulated advisory workflow where every
step must be predictable and auditable:

    DataFetcher -> [load history] -> Analyzer -> HITL checkpoint -> Advisor
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import hitl
from ..context import SessionContext
from ..errors import PipelineError
from ..logging_config import get_logger
from ..memory.long_term import LongTermMemory
from ..schemas import STATUS_FAILED, AdvisoryReport
from ..tools.anomaly_tool import AnomalyDetectionTool
from ..tools.base import ToolRegistry
from ..tools.crm_tool import CRMTool
from ..tools.financial_data_tool import FinancialDataTool
from ..tools.llm_tool import LLMTool
from ..tools.market_data_tool import MarketDataTool
from .advisor import AdvisorAgent
from .analyzer import AnalyzerAgent
from .data_fetcher import DataFetcherAgent


class OrchestratorAgent:
    name = "orchestrator"

    def __init__(
        self,
        tools: ToolRegistry | None = None,
        long_term_memory: LongTermMemory | None = None,
    ) -> None:
        self.log = get_logger("orchestrator")
        self.tools = tools or build_registry()
        self.memory = long_term_memory or LongTermMemory()
        self.data_fetcher = DataFetcherAgent(self.tools)
        self.analyzer = AnalyzerAgent(self.tools)
        self.advisor = AdvisorAgent(self.tools)

    def run(
        self,
        run_id: str,
        raw_input: dict,
        interactive: bool = False,
        auto_approve: bool = True,
    ) -> SessionContext:
        """Execute the full advisory pipeline; return the populated context."""
        context = SessionContext(run_id=run_id, raw_input=raw_input)
        plan = ["data_fetcher", "analyzer", "hitl_checkpoint", "advisor"]
        context.record_event("plan", steps=plan)
        self.log.info("run %s starting; plan: %s", run_id, " -> ".join(plan))

        # --- Step 1: fetch + enrich (fatal on failure) --------------------
        self._route("data_fetcher")
        fetch = self.data_fetcher.execute(context)
        context.record_event("agent_result", agent=fetch.agent, status=fetch.status)
        if fetch.status == STATUS_FAILED:
            raise PipelineError(
                "data fetching failed: " + "; ".join(fetch.errors)
            )

        # --- Inject long-term memory now that we know the client ----------
        prior = self.memory.get_last(context.client_id) if context.client_id else None
        context.history = prior
        if prior:
            self.log.info(
                "loaded prior run for client %s (as of %s)",
                context.client_id,
                prior.get("generated_at"),
            )

        # --- Step 2: analyze ----------------------------------------------
        self._route("analyzer")
        analysis = self.analyzer.execute(context)
        context.record_event("agent_result", agent=analysis.agent, status=analysis.status)
        if analysis.status == STATUS_FAILED:
            raise PipelineError("analysis failed: " + "; ".join(analysis.errors))

        # --- Step 3: human-in-the-loop checkpoint -------------------------
        self._route("hitl_checkpoint")
        hitl.run_checkpoint(context, interactive=interactive, auto_approve=auto_approve)

        # --- Step 4: advise -----------------------------------------------
        self._route("advisor")
        advice = self.advisor.execute(context)
        context.record_event("agent_result", agent=advice.agent, status=advice.status)
        if advice.status == STATUS_FAILED:
            raise PipelineError("advisory generation failed: " + "; ".join(advice.errors))

        # --- Persist to long-term memory ----------------------------------
        self._persist(context)
        self.log.info("run %s complete in %.2fs", run_id, context.elapsed_seconds)
        return context

    def _route(self, step: str) -> None:
        """Log a routing decision (central coordination made observable)."""
        self.log.debug("routing -> %s", step)

    def _persist(self, context: SessionContext) -> None:
        report: AdvisoryReport = context.report
        if report is None:  # pragma: no cover - guaranteed by caller
            return
        summary = {
            "run_id": report.run_id,
            "generated_at": report.generated_at
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_aum": report.metrics.total_aum if report.metrics else None,
            "risk_posture": report.risk_posture,
            "anomaly_types": sorted({a.type for a in report.anomalies}),
            "num_recommendations": len(report.recommendations),
        }
        self.memory.append(report.client_id, summary)
        context.record_event("memory_persisted", client_id=report.client_id)


def build_registry() -> ToolRegistry:
    """Wire up the standard set of tools used by the system."""
    registry = ToolRegistry()
    for tool in (
        FinancialDataTool(),
        CRMTool(),
        MarketDataTool(),
        AnomalyDetectionTool(),
        LLMTool(),
    ):
        registry.register(tool)
    return registry
