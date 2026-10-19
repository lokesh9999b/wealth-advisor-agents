"""Command-line interface for the Wealth Advisor Assistant.

Examples::

    python run.py                                   # run on the default sample
    python run.py --client data/clients/client_002.json
    python run.py --client data/clients/client_002.json --yes   # headless
    python run.py --list-clients
    python run.py --client data/clients/client_002.json --format json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from .agents.orchestrator import OrchestratorAgent
from .config import CLIENTS_DIR, OUTPUTS_DIR, settings
from .errors import WealthAdvisorError
from .logging_config import configure_logging, get_logger
from .reporting import render_text, write_outputs


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wealth-advisor",
        description="Run the multi-agent Wealth Advisor Assistant on a client.",
    )
    p.add_argument(
        "--client",
        type=Path,
        default=CLIENTS_DIR / "client_001.json",
        help="Path to the client financial data JSON (default: sample client_001).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=OUTPUTS_DIR,
        help="Directory for the report + trace artifacts (default: outputs/).",
    )
    # Two spellings of the same intent: skip the interactive HITL prompt.
    p.add_argument(
        "--yes", "--no-hitl",
        dest="auto_approve",
        action="store_true",
        help="Auto-approve the human-in-the-loop checkpoint (non-interactive).",
    )
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Console output format (default: text). Files are always written.",
    )
    p.add_argument(
        "--log-level",
        default=settings.log_level,
        help="Console log level: DEBUG, INFO, WARNING, ERROR (default: INFO).",
    )
    p.add_argument(
        "--list-clients",
        action="store_true",
        help="List the available sample clients and exit.",
    )
    return p


def _list_clients() -> int:
    files = sorted(CLIENTS_DIR.glob("*.json"))
    if not files:
        print(f"No client files found in {CLIENTS_DIR}")
        return 1
    print(f"Available clients in {CLIENTS_DIR}:")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            desc = f"{data.get('client_id', '?')} — {data.get('name', '?')}"
        except (json.JSONDecodeError, OSError):
            desc = "(unreadable)"
        print(f"  {f.name:<22} {desc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Ensure Unicode (em-dashes, bullets, LLM text) prints on any console.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - stream may not support it
            pass

    args = _build_parser().parse_args(argv)

    if args.list_clients:
        return _list_clients()

    run_id = uuid.uuid4().hex[:8]
    configure_logging(run_id, level=args.log_level)
    log = get_logger("cli")

    # Interactive only when attached to a terminal and not auto-approving.
    interactive = (not args.auto_approve) and sys.stdin.isatty()

    try:
        orchestrator = OrchestratorAgent()
        context = orchestrator.run(
            run_id=run_id,
            raw_input={"path": str(args.client)},
            interactive=interactive,
            auto_approve=args.auto_approve,
        )
    except WealthAdvisorError as exc:
        log.error("run failed: %s", exc)
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    paths = write_outputs(context, outputs_dir=args.output)

    print()  # separate logs (stderr) from the report (stdout)
    if args.format == "json":
        print(json.dumps(context.report.to_dict(), indent=2, default=str))
    else:
        print(render_text(context.report))

    print(f"\nArtifacts written:")
    print(f"  report : {paths['report']}")
    print(f"  trace  : {paths['trace']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
