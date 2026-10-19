"""Presentation: render the advisory report for the console and write artifacts.

Keeps all formatting/IO out of the agents so they stay focused on logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import OUTPUTS_DIR
from .context import SessionContext
from .schemas import AdvisoryReport

_BAR = "=" * 70
_DASH = "-" * 70


def render_text(report: AdvisoryReport) -> str:
    """Return a human-readable console report."""
    m = report.metrics
    lines: list[str] = [
        _BAR,
        f"  WEALTH ADVISORY REPORT — {report.client_name} ({report.client_id})",
        _BAR,
        f"Run ID        : {report.run_id}",
        f"Generated     : {report.generated_at}",
        f"Risk posture  : {report.risk_posture.upper()}",
        f"Narrative via : {report.narrative_source}",
    ]
    if report.degraded_mode:
        lines.append("Mode          : DEGRADED (some context unavailable)")
    lines.append("")

    # Metrics ---------------------------------------------------------------
    if m:
        lines.append("PORTFOLIO METRICS")
        lines.append(_DASH)
        lines.append(f"  Total AUM           : ${m.total_aum:,.0f}")
        lines.append(f"  Cash                : ${m.total_cash:,.0f} ({m.cash_pct:.0%})")
        lines.append(f"  Holdings            : {m.holdings_count}")
        if m.top_holding:
            th = m.top_holding
            lines.append(
                f"  Largest position    : {th['symbol']} "
                f"(${th['value']:,.0f}, {th['pct']:.0%})"
            )
        if m.allocation:
            alloc = ", ".join(f"{k} {v:.0%}" for k, v in sorted(m.allocation.items()))
            lines.append(f"  Allocation          : {alloc}")
        if m.weighted_expense_ratio:
            lines.append(f"  Weighted fee        : {m.weighted_expense_ratio:.2%}")
        lines.append("")

    # Anomalies -------------------------------------------------------------
    lines.append(f"ANOMALIES & RISK SIGNALS ({len(report.anomalies)})")
    lines.append(_DASH)
    if report.anomalies:
        for a in report.anomalies:
            tag = " [recurring]" if a.recurring else ""
            lines.append(f"  • [{a.severity}] {a.title}{tag}")
            lines.append(f"      {a.explanation}")
    else:
        lines.append("  None detected.")
    lines.append("")

    # Recommendations -------------------------------------------------------
    lines.append(f"RECOMMENDATIONS ({len(report.recommendations)})")
    lines.append(_DASH)
    for i, r in enumerate(report.recommendations, 1):
        lines.append(f"  {i}. [{r.priority}] {r.title}")
        lines.append(f"      Action: {r.action}")
    lines.append("")

    # Narrative -------------------------------------------------------------
    lines.append("ADVISORY SUMMARY")
    lines.append(_DASH)
    lines.append(report.summary_narrative)
    lines.append("")

    # HITL ------------------------------------------------------------------
    h = report.hitl
    lines.append("HUMAN-IN-THE-LOOP")
    lines.append(_DASH)
    status = "performed" if h.performed else f"skipped ({h.skipped_reason})"
    lines.append(f"  Checkpoint : {status}")
    if h.decision:
        lines.append(f"  Decision   : {h.decision}")
    if h.overrides:
        lines.append(f"  Overrides  : {len(h.overrides)}")
    if h.notes:
        lines.append(f"  Notes      : {h.notes}")

    if report.warnings:
        lines.append("")
        lines.append("WARNINGS")
        lines.append(_DASH)
        for w in report.warnings:
            lines.append(f"  ! {w}")

    lines.append(_BAR)
    return "\n".join(lines)


def write_outputs(
    context: SessionContext, outputs_dir: Path | None = None
) -> dict[str, Path]:
    """Write the structured report JSON and the run trace JSON. Return paths."""
    outputs_dir = outputs_dir or OUTPUTS_DIR
    outputs_dir.mkdir(parents=True, exist_ok=True)
    report = context.report

    base = f"{context.run_id}_{report.client_id}"
    report_path = outputs_dir / f"{base}_report.json"
    trace_path = outputs_dir / f"{context.run_id}_trace.json"

    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, default=str)

    trace = {
        "run_id": context.run_id,
        "client_id": report.client_id,
        "elapsed_seconds": context.elapsed_seconds,
        "facts": context.memory.facts,
        "notes": context.memory.notes,
        "events": context.memory.events,
    }
    with trace_path.open("w", encoding="utf-8") as fh:
        json.dump(trace, fh, indent=2, default=str)

    return {"report": report_path, "trace": trace_path}
