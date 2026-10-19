"""Typed data models for the whole pipeline.

We use stdlib ``dataclasses`` (rather than pydantic) to keep the project
dependency-free and transparent. Light validation is done explicitly in the
``from_dict`` constructors and in ``financial_data_tool``.

The models form three layers:
  * Input   — :class:`ClientFinancialData`, :class:`CRMProfile` (raw-ish data)
  * Enriched — :class:`ClientProfile` (what the DataFetcher produces)
  * Output  — :class:`PortfolioMetrics`, :class:`Anomaly`, :class:`AnalysisResult`,
              :class:`Recommendation`, :class:`AdvisoryReport`
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# --- Simple string constants (kept as plain strings for clean JSON) ---------

# Severity levels, ordered.
SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"
SEVERITY_ORDER = {SEVERITY_LOW: 1, SEVERITY_MEDIUM: 2, SEVERITY_HIGH: 3}

# Agent execution statuses.
STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"  # ran but in degraded mode
STATUS_FAILED = "failed"


def _to_serializable(value: Any) -> Any:
    """Recursively convert dataclasses/containers into JSON-safe primitives."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {k: _to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(v) for v in value]
    return value


@dataclass
class _Serializable:
    """Mixin giving every model a recursive ``to_dict``."""

    def to_dict(self) -> dict[str, Any]:
        return {k: _to_serializable(v) for k, v in asdict(self).items()}


# --------------------------------------------------------------------------- #
# Input models
# --------------------------------------------------------------------------- #
@dataclass
class Holding(_Serializable):
    symbol: str
    asset_class: str
    quantity: float
    price: float
    market_value: float
    expense_ratio: float = 0.0  # annual fund fee as a fraction, optional

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Holding":
        qty = float(d.get("quantity", 0) or 0)
        price = float(d.get("price", 0) or 0)
        # Derive market_value when absent; fall back to quantity * price.
        mv = d.get("market_value")
        market_value = float(mv) if mv is not None else qty * price
        return cls(
            symbol=str(d.get("symbol", "UNKNOWN")),
            asset_class=str(d.get("asset_class", "unknown")).lower(),
            quantity=qty,
            price=price,
            market_value=market_value,
            expense_ratio=float(d.get("expense_ratio", 0.0) or 0.0),
        )


@dataclass
class Account(_Serializable):
    account_id: str
    type: str
    cash_balance: float
    holdings: list[Holding] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Account":
        return cls(
            account_id=str(d.get("account_id", "UNKNOWN")),
            type=str(d.get("type", "unknown")),
            cash_balance=float(d.get("cash_balance", 0) or 0),
            holdings=[Holding.from_dict(h) for h in d.get("holdings", []) or []],
        )


@dataclass
class Transaction(_Serializable):
    date: str
    type: str
    symbol: str
    amount: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Transaction":
        return cls(
            date=str(d.get("date", "")),
            type=str(d.get("type", "unknown")).lower(),
            symbol=str(d.get("symbol", "")),
            amount=float(d.get("amount", 0) or 0),
        )


@dataclass
class ClientFinancialData(_Serializable):
    """The raw client financial input (parsed + lightly validated)."""

    client_id: str
    name: str
    as_of_date: str
    accounts: list[Account] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    target_allocation: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClientFinancialData":
        return cls(
            client_id=str(d["client_id"]),
            name=str(d.get("name", "Unknown Client")),
            as_of_date=str(d.get("as_of_date", "")),
            accounts=[Account.from_dict(a) for a in d.get("accounts", []) or []],
            transactions=[
                Transaction.from_dict(t) for t in d.get("transactions", []) or []
            ],
            target_allocation={
                str(k).lower(): float(v)
                for k, v in (d.get("target_allocation", {}) or {}).items()
            },
        )


@dataclass
class CRMProfile(_Serializable):
    """Context fetched from the (mock) CRM API."""

    risk_tolerance: str = "unknown"
    investment_horizon_years: int | None = None
    kyc_status: str = "unknown"
    annual_income: float | None = None
    liquidity_needs: str = "unknown"
    advisor_notes: str = ""
    last_review_date: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CRMProfile":
        horizon = d.get("investment_horizon_years")
        income = d.get("annual_income")
        return cls(
            risk_tolerance=str(d.get("risk_tolerance", "unknown")).lower(),
            investment_horizon_years=int(horizon) if horizon is not None else None,
            kyc_status=str(d.get("kyc_status", "unknown")).lower(),
            annual_income=float(income) if income is not None else None,
            liquidity_needs=str(d.get("liquidity_needs", "unknown")).lower(),
            advisor_notes=str(d.get("advisor_notes", "")),
            last_review_date=d.get("last_review_date"),
        )


# --------------------------------------------------------------------------- #
# Enriched model (DataFetcher output)
# --------------------------------------------------------------------------- #
@dataclass
class ClientProfile(_Serializable):
    """Normalized, enriched client view handed from DataFetcher to Analyzer."""

    financial: ClientFinancialData
    crm: CRMProfile | None = None
    market_context: dict[str, Any] = field(default_factory=dict)
    # Non-fatal data issues collected during fetch/enrichment.
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False  # True if CRM/market context could not be fetched


# --------------------------------------------------------------------------- #
# Analysis / output models
# --------------------------------------------------------------------------- #
@dataclass
class Anomaly(_Serializable):
    type: str  # e.g. "concentration_risk"
    severity: str  # SEVERITY_*
    title: str
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation_hint: str = ""
    recurring: bool = False  # seen in a previous run (set via long-term memory)


@dataclass
class PortfolioMetrics(_Serializable):
    total_aum: float = 0.0
    total_cash: float = 0.0
    cash_pct: float = 0.0
    allocation: dict[str, float] = field(default_factory=dict)  # actual weights
    target_allocation: dict[str, float] = field(default_factory=dict)
    allocation_drift: dict[str, float] = field(default_factory=dict)  # actual-target
    top_holding: dict[str, Any] = field(default_factory=dict)  # {symbol, pct, value}
    holdings_count: int = 0
    weighted_expense_ratio: float = 0.0


@dataclass
class AnalysisResult(_Serializable):
    metrics: PortfolioMetrics
    anomalies: list[Anomaly] = field(default_factory=list)
    risk_signals: list[str] = field(default_factory=list)
    memory_comparison: dict[str, Any] = field(default_factory=dict)

    @property
    def highest_severity(self) -> str | None:
        if not self.anomalies:
            return None
        return max(self.anomalies, key=lambda a: SEVERITY_ORDER.get(a.severity, 0)).severity


@dataclass
class Recommendation(_Serializable):
    title: str
    action: str
    rationale: str
    priority: str  # SEVERITY_* reused as priority level
    related_anomaly_type: str | None = None


@dataclass
class HITLRecord(_Serializable):
    """Audit trail of the human-in-the-loop checkpoint."""

    performed: bool = False
    skipped_reason: str | None = None  # why it was auto-skipped, if applicable
    decision: str | None = None  # "approved" / "overridden"
    notes: str = ""
    overrides: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AdvisoryReport(_Serializable):
    """The final structured output of the whole pipeline."""

    run_id: str
    client_id: str
    client_name: str
    generated_at: str
    risk_posture: str  # overall assessment, e.g. "elevated"
    summary_narrative: str
    narrative_source: str  # "llm" | "template"
    recommendations: list[Recommendation] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    metrics: PortfolioMetrics | None = None
    degraded_mode: bool = False
    warnings: list[str] = field(default_factory=list)
    hitl: HITLRecord = field(default_factory=HITLRecord)
    meta: dict[str, Any] = field(default_factory=dict)
