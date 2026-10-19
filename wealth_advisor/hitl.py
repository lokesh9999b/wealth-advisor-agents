"""Human-in-the-loop (HITL) checkpoint.

Sits between analysis and advice. When the Analyzer surfaces HIGH-severity
findings, a human can review them and approve, dismiss false positives, adjust
severity, or attach a note before the advisory is finalized.

The checkpoint auto-skips (recording why) when there is nothing high-severity
to review, or when the run is non-interactive (``--yes`` / no TTY), so the
system runs unattended in CI without ever blocking on stdin.
"""

from __future__ import annotations

from .context import SessionContext
from .logging_config import get_logger
from .schemas import (
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    Anomaly,
    HITLRecord,
)

log = get_logger("hitl")

_LEVELS = {SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH}


def run_checkpoint(
    context: SessionContext, interactive: bool, auto_approve: bool
) -> HITLRecord:
    """Run (or skip) the HITL checkpoint; return an auditable record.

    Mutates ``context.analysis.anomalies`` in place if the reviewer dismisses or
    re-rates findings, and stores the record on ``context.hitl``.
    """
    analysis = context.analysis
    record = HITLRecord()
    context.hitl = record

    high = [a for a in (analysis.anomalies if analysis else []) if a.severity == SEVERITY_HIGH]

    if not high:
        record.decision = "approved"
        record.skipped_reason = "no high-severity findings required review"
        log.info("HITL skipped: %s", record.skipped_reason)
        return record

    if auto_approve or not interactive:
        record.decision = "approved"
        record.skipped_reason = (
            "auto-approved (non-interactive session or --yes/--no-hitl)"
        )
        log.info(
            "HITL auto-approved %d high-severity finding(s): %s",
            len(high),
            ", ".join(a.type for a in high),
        )
        context.record_event("hitl", performed=False, decision="approved")
        return record

    record.performed = True
    log.info("HITL checkpoint engaged for %d high-severity finding(s)", len(high))
    _interactive_review(context, record)
    context.record_event(
        "hitl",
        performed=True,
        decision=record.decision,
        overrides=len(record.overrides),
    )
    return record


def _interactive_review(context: SessionContext, record: HITLRecord) -> None:
    analysis = context.analysis
    print("\n" + "=" * 70)
    print("  HUMAN-IN-THE-LOOP CHECKPOINT — high-severity findings need review")
    print("=" * 70)
    _print_findings(analysis.anomalies)
    print(
        "\nCommands:  [Enter]=approve all   d <n>=dismiss finding   "
        "s <n> <LOW|MEDIUM|HIGH>=set severity\n"
        "           note <text>=add a note   done=finish review"
    )

    while True:
        try:
            raw = input("hitl> ").strip()
        except EOFError:  # stdin closed mid-review — approve what we have
            log.warning("stdin closed during HITL; approving remaining findings")
            break

        if raw == "" or raw.lower() in {"a", "approve", "done"}:
            break

        parts = raw.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "d" and len(parts) >= 2:
            _dismiss(analysis.anomalies, parts[1], record)
        elif cmd == "s" and len(parts) >= 3:
            _set_severity(analysis.anomalies, parts[1], parts[2], record)
        elif cmd == "note" and len(parts) >= 2:
            note = raw[len("note "):].strip()
            record.notes = (record.notes + " " + note).strip()
            context.note(f"HITL note: {note}")
            print(f"  noted.")
        else:
            print("  (unrecognized command)")

        _print_findings(analysis.anomalies)

    record.decision = "overridden" if record.overrides else "approved"
    print(f"Review complete: {record.decision}.\n")


def _print_findings(anomalies: list[Anomaly]) -> None:
    print("\nCurrent findings:")
    if not anomalies:
        print("  (none)")
        return
    for i, a in enumerate(anomalies):
        print(f"  [{i}] {a.severity:<6} {a.type:<22} {a.title}")


def _dismiss(anomalies: list[Anomaly], idx_str: str, record: HITLRecord) -> None:
    idx = _parse_index(idx_str, anomalies)
    if idx is None:
        print("  (invalid index)")
        return
    removed = anomalies.pop(idx)
    record.overrides.append(
        {"action": "dismiss", "type": removed.type, "title": removed.title}
    )
    print(f"  dismissed finding [{idx}] {removed.type}")


def _set_severity(
    anomalies: list[Anomaly], idx_str: str, level: str, record: HITLRecord
) -> None:
    idx = _parse_index(idx_str, anomalies)
    level = level.upper()
    if idx is None or level not in _LEVELS:
        print("  (invalid index or severity level)")
        return
    old = anomalies[idx].severity
    anomalies[idx].severity = level
    record.overrides.append(
        {
            "action": "set_severity",
            "type": anomalies[idx].type,
            "from": old,
            "to": level,
        }
    )
    print(f"  finding [{idx}] severity {old} -> {level}")


def _parse_index(idx_str: str, anomalies: list[Anomaly]) -> int | None:
    try:
        idx = int(idx_str)
    except ValueError:
        return None
    return idx if 0 <= idx < len(anomalies) else None
