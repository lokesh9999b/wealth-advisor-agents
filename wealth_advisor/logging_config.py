"""Structured logging setup for observability.

Every log line carries the ``run_id`` so a single advisory run can be traced
end-to-end across agents and tools. Output goes to both the console and a
per-run rotating file under ``outputs/logs/``.

Usage::

    from wealth_advisor.logging_config import configure_logging, get_logger
    log_path = configure_logging(run_id, level="INFO")
    log = get_logger("orchestrator")
    log.info("starting run")
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LOGS_DIR

_ROOT_LOGGER_NAME = "wealth_advisor"
_configured = False


class _RunIdFilter(logging.Filter):
    """Injects the active run_id into every record so the format can use it."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


def configure_logging(
    run_id: str, level: str = "INFO", logs_dir: Path | None = None
) -> Path:
    """Configure the package logger. Returns the path of the run log file.

    Safe to call once per process. Re-calling replaces handlers so a new run_id
    takes effect (useful in tests).
    """
    global _configured

    logs_dir = logs_dir or LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"run_{run_id}.log"

    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)  # handlers decide what is emitted
    logger.propagate = False

    # Clear any handlers from a previous configuration (idempotent).
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(run_id)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    run_filter = _RunIdFilter(run_id)

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(fmt)
    console.addFilter(run_filter)
    logger.addHandler(console)

    # File handler always captures DEBUG for full traceability.
    file_handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(run_filter)
    logger.addHandler(file_handler)

    _configured = True
    return log_file


def get_logger(component: str) -> logging.Logger:
    """Return a child logger named ``wealth_advisor.<component>``.

    If logging has not been configured yet (e.g. in a unit test that imports a
    tool directly), a minimal fallback keeps calls from crashing.
    """
    if not _configured:
        logging.getLogger(_ROOT_LOGGER_NAME).addHandler(logging.NullHandler())
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{component}")
