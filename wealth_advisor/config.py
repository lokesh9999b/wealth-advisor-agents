"""Central configuration: paths, environment flags, and tunable thresholds.

Everything that an evaluator might want to tweak (anomaly thresholds, the model
id, failure-injection toggle) lives here rather than being scattered as magic
numbers across the codebase. Values are read once at import time.

Environment variables (all optional) are loaded from a ``.env`` file if
``python-dotenv`` is installed; otherwise the process environment is used
directly. The system is designed to run with none of them set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --- Load .env if python-dotenv is available (optional dependency) ----------
try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


# --- Filesystem layout ------------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
CLIENTS_DIR = DATA_DIR / "clients"
CRM_DB_PATH = DATA_DIR / "crm_db.json"
MARKET_DATA_PATH = DATA_DIR / "market_data.json"
MEMORY_STORE_PATH = DATA_DIR / "memory_store.json"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
LOGS_DIR = OUTPUTS_DIR / "logs"


def _env_flag(name: str, default: bool = False) -> bool:
    """Interpret an env var as a boolean (``1/true/yes/on`` => True)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AnomalyThresholds:
    """Tunable thresholds for the (explainable) anomaly detectors."""

    # Flag a single holding that is more than this fraction of total AUM.
    concentration_pct: float = 0.25
    # Flag an asset class whose actual weight drifts from its target by more
    # than this many percentage points (absolute).
    allocation_drift_pct: float = 0.10
    # A transaction is a statistical outlier if its z-score exceeds this.
    txn_zscore: float = 2.5
    # ...or (robust alternative) if its MAD-based modified z-score exceeds this.
    # The modified z-score (Iglewicz & Hoaglin) uses the median and MAD, so a
    # single extreme value can't mask itself the way it can with a plain z-score
    # or an IQR fence on a small sample. 3.5 is the conventional threshold.
    txn_modified_zscore: float = 3.5
    # Flag any single transaction larger than this fraction of total AUM.
    large_txn_pct: float = 0.20
    # Flag if idle cash exceeds this fraction of AUM (cash drag).
    cash_drag_pct: float = 0.20
    # Flag if the weighted expense ratio exceeds the market average by this
    # multiple (e.g. 1.5x the benchmark average fee).
    fee_ratio_multiple: float = 1.5
    # Two transactions with the same symbol+amount within this many days are
    # treated as potential duplicates.
    duplicate_window_days: int = 3


@dataclass(frozen=True)
class Settings:
    """Top-level settings resolved from the environment."""

    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None
    )
    model: str = field(default_factory=lambda: os.getenv("WA_MODEL", "claude-opus-5"))
    simulate_crm_failure: bool = field(
        default_factory=lambda: _env_flag("WA_SIMULATE_CRM_FAILURE", False)
    )
    log_level: str = field(default_factory=lambda: os.getenv("WA_LOG_LEVEL", "INFO"))

    # Retry policy for the simulated "API" tools.
    api_max_retries: int = 2
    api_retry_backoff_seconds: float = 0.2

    thresholds: AnomalyThresholds = field(default_factory=AnomalyThresholds)

    @property
    def llm_enabled(self) -> bool:
        """True when an API key is present (the narrative *may* use the LLM)."""
        return bool(self.anthropic_api_key)


# A single shared instance imported across the codebase.
settings = Settings()
