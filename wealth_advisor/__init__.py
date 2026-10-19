"""Wealth Advisor Assistant — a lightweight multi-agent system.

A small, framework-free multi-agent system that ingests client financial data,
enriches it from a mock CRM API, runs financial analysis + anomaly detection,
and produces a structured advisory report.

The public entry point is the CLI (`wealth_advisor.cli:main`), but the
orchestrator (`wealth_advisor.agents.orchestrator.OrchestratorAgent`) can also
be driven programmatically.
"""

__version__ = "1.0.0"
