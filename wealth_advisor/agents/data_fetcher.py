"""DataFetcherAgent — loads, validates, and enriches the client's data.

Responsibilities:
  1. Load + validate the raw client financial JSON (``financial_data`` tool).
  2. Enrich with the CRM profile (``crm_api`` tool).
  3. Enrich with market context / benchmarks (``market_data`` tool).

Enrichment failures are non-fatal: the agent degrades gracefully (continuing
with whatever data it has) and records warnings. Only a failure to load the
core financial data is fatal.
"""

from __future__ import annotations

from ..context import SessionContext
from ..schemas import (
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    ClientProfile,
)
from .base import Agent, AgentResult


class DataFetcherAgent(Agent):
    name = "data_fetcher"

    def execute(self, context: SessionContext) -> AgentResult:
        result = AgentResult(agent=self.name)

        # --- 1. Core financial data (fatal if this fails) -----------------
        fd_tool = self.tools.get("financial_data")
        fd = fd_tool.run(**(context.raw_input or {}))
        self._trace_tool(context, fd)
        if not fd.ok:
            self.log.error("could not load client financial data: %s", fd.error)
            result.status = STATUS_FAILED
            result.errors.append(f"financial_data: {fd.error}")
            return result

        financial = fd.data
        context.client_id = financial.client_id
        context.remember("client_id", financial.client_id)
        context.remember("client_name", financial.name)
        self.log.info(
            "loaded client %s (%s) with %d account(s), %d transaction(s)",
            financial.client_id,
            financial.name,
            len(financial.accounts),
            len(financial.transactions),
        )

        warnings: list[str] = []
        degraded = False

        # --- 2. CRM enrichment (non-fatal) --------------------------------
        crm_tool = self.tools.get("crm_api")
        crm_res = crm_tool.run(client_id=financial.client_id)
        self._trace_tool(context, crm_res)
        crm = None
        if crm_res.ok and crm_res.data is not None:
            crm = crm_res.data
            self.log.info("CRM profile found (risk tolerance: %s)", crm.risk_tolerance)
        elif crm_res.ok:  # ok but no record
            warnings.append("No CRM record found for this client.")
            degraded = True
            self.log.warning("no CRM record for client %s", financial.client_id)
        else:  # API failure after retries
            warnings.append(f"CRM unavailable ({crm_res.error}); proceeding without it.")
            degraded = True
            self.log.warning("CRM tool failed: %s", crm_res.error)

        # --- 3. Market context (non-fatal) --------------------------------
        market_tool = self.tools.get("market_data")
        risk = crm.risk_tolerance if crm else None
        mkt_res = market_tool.run(risk_tolerance=risk)
        self._trace_tool(context, mkt_res)
        market_context: dict = {}
        if mkt_res.ok:
            market_context = mkt_res.data
        else:
            warnings.append(f"Market data unavailable ({mkt_res.error}).")
            degraded = True
            self.log.warning("market data tool failed: %s", mkt_res.error)

        # Flag empty portfolios as a data-quality warning (edge case).
        if not financial.accounts:
            warnings.append("Client has no accounts/holdings — analysis will be limited.")

        profile = ClientProfile(
            financial=financial,
            crm=crm,
            market_context=market_context,
            warnings=warnings,
            degraded=degraded,
        )
        context.profile = profile
        for w in warnings:
            context.note(w)

        result.output = profile
        result.warnings = warnings
        result.status = STATUS_PARTIAL if degraded else STATUS_SUCCESS
        return result
