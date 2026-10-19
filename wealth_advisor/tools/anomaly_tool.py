"""Tool: explainable anomaly / risk-signal detection.

Deliberately rule-based + statistical (not a black-box ML model) so every
finding is explainable with concrete evidence — appropriate for a regulated,
advice-giving context and runnable with no training data. Thresholds come from
``config.AnomalyThresholds``.

Each detector returns zero or more :class:`Anomaly` objects carrying a type,
severity, human explanation, and the numeric evidence that triggered it.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

from ..config import settings
from ..schemas import (
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    Anomaly,
    ClientFinancialData,
    PortfolioMetrics,
)
from .base import Tool

_T = settings.thresholds


class AnomalyDetectionTool(Tool):
    name = "anomaly_detection"
    description = "Detect unusual transactions, allocations, and risk signals."
    retryable = False

    def _execute(
        self,
        financial: ClientFinancialData | None = None,
        metrics: PortfolioMetrics | None = None,
        history: dict[str, Any] | None = None,
        market_avg_fee: float | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if financial is None or metrics is None:
            # Pure computation; this would be a programming error, so raise.
            from ..errors import ToolError

            raise ToolError("anomaly_detection requires 'financial' and 'metrics'")

        anomalies: list[Anomaly] = []
        anomalies += self._concentration(metrics)
        anomalies += self._allocation_drift(metrics)
        anomalies += self._cash_drag(metrics)
        anomalies += self._negative_cash(financial)
        anomalies += self._transaction_outliers(financial, metrics)
        anomalies += self._duplicate_transactions(financial)
        anomalies += self._fee_ratio(metrics, market_avg_fee)

        # Mark anomalies that also appeared in the previous run as recurring.
        prior_types = set((history or {}).get("anomaly_types", []))
        for a in anomalies:
            if a.type in prior_types:
                a.recurring = True

        risk_signals = sorted({a.type for a in anomalies})
        return {"anomalies": anomalies, "risk_signals": risk_signals}

    # -- individual detectors ----------------------------------------------
    def _concentration(self, m: PortfolioMetrics) -> list[Anomaly]:
        top = m.top_holding
        if not top or top.get("pct", 0) <= _T.concentration_pct:
            return []
        pct = top["pct"]
        severity = SEVERITY_HIGH if pct >= 0.40 else SEVERITY_MEDIUM
        return [
            Anomaly(
                type="concentration_risk",
                severity=severity,
                title=f"Over-concentration in {top['symbol']}",
                explanation=(
                    f"{top['symbol']} is {pct:.0%} of total AUM, above the "
                    f"{_T.concentration_pct:.0%} single-holding limit. This "
                    "exposes the client to idiosyncratic risk."
                ),
                evidence={"symbol": top["symbol"], "pct": pct, "value": top["value"]},
                recommendation_hint="Consider trimming and diversifying the position.",
            )
        ]

    def _allocation_drift(self, m: PortfolioMetrics) -> list[Anomaly]:
        out: list[Anomaly] = []
        for cls, drift in m.allocation_drift.items():
            if abs(drift) <= _T.allocation_drift_pct:
                continue
            severity = SEVERITY_HIGH if abs(drift) >= 0.20 else SEVERITY_MEDIUM
            direction = "over" if drift > 0 else "under"
            out.append(
                Anomaly(
                    type="allocation_drift",
                    severity=severity,
                    title=f"Allocation drift in {cls}",
                    explanation=(
                        f"{cls} is {direction}-weight by {abs(drift):.0%} vs target "
                        f"({m.allocation.get(cls, 0):.0%} actual vs "
                        f"{m.target_allocation.get(cls, 0):.0%} target)."
                    ),
                    evidence={
                        "asset_class": cls,
                        "actual": m.allocation.get(cls, 0),
                        "target": m.target_allocation.get(cls, 0),
                        "drift": drift,
                    },
                    recommendation_hint=f"Rebalance {cls} toward its target weight.",
                )
            )
        return out

    def _cash_drag(self, m: PortfolioMetrics) -> list[Anomaly]:
        if m.cash_pct <= _T.cash_drag_pct:
            return []
        return [
            Anomaly(
                type="cash_drag",
                severity=SEVERITY_LOW,
                title="Excess idle cash",
                explanation=(
                    f"{m.cash_pct:.0%} of AUM sits in cash (above the "
                    f"{_T.cash_drag_pct:.0%} guideline), creating cash drag."
                ),
                evidence={"cash_pct": m.cash_pct, "cash": m.total_cash},
                recommendation_hint="Deploy excess cash per the target allocation.",
            )
        ]

    def _negative_cash(self, fin: ClientFinancialData) -> list[Anomaly]:
        out: list[Anomaly] = []
        for acct in fin.accounts:
            if acct.cash_balance < 0:
                out.append(
                    Anomaly(
                        type="negative_cash",
                        severity=SEVERITY_HIGH,
                        title=f"Negative cash in account {acct.account_id}",
                        explanation=(
                            f"Account {acct.account_id} has a negative cash balance "
                            f"of {acct.cash_balance:,.0f}, suggesting an overdraft "
                            "or margin usage."
                        ),
                        evidence={
                            "account_id": acct.account_id,
                            "cash_balance": acct.cash_balance,
                        },
                        recommendation_hint="Investigate the overdraft/margin usage.",
                    )
                )
        return out

    def _transaction_outliers(
        self, fin: ClientFinancialData, m: PortfolioMetrics
    ) -> list[Anomaly]:
        txns = fin.transactions
        out: list[Anomaly] = []
        if not txns:
            return out

        # (a) Single transaction that is huge relative to AUM.
        flagged: set[tuple[str, str, float]] = set()
        if m.total_aum > 0:
            for t in txns:
                frac = abs(t.amount) / m.total_aum
                if frac >= _T.large_txn_pct:
                    flagged.add((t.symbol, t.date, round(t.amount, 2)))
                    out.append(
                        Anomaly(
                            type="large_transaction",
                            severity=SEVERITY_HIGH,
                            title=f"Large {t.type} transaction ({t.symbol})",
                            explanation=(
                                f"A {t.type} of {abs(t.amount):,.0f} in {t.symbol} on "
                                f"{t.date} is {frac:.0%} of AUM — an unusually large "
                                "single move."
                            ),
                            evidence={
                                "symbol": t.symbol,
                                "amount": t.amount,
                                "date": t.date,
                                "pct_of_aum": round(frac, 4),
                            },
                            recommendation_hint="Confirm this transaction was intended.",
                        )
                    )

        # (b) Statistical outliers among the *remaining* transactions. We use
        # a plain z-score AND a robust MAD-based modified z-score: on small
        # samples a single extreme value inflates the standard deviation (and
        # even an IQR fence) enough to mask itself, whereas the median/MAD are
        # resistant to it.
        baseline = [
            t for t in txns
            if (t.symbol, t.date, round(t.amount, 2)) not in flagged
        ]
        amounts = [abs(t.amount) for t in baseline]
        if len(amounts) >= 4:
            mean = statistics.mean(amounts)
            stdev = statistics.pstdev(amounts)
            median = statistics.median(amounts)
            mad = statistics.median([abs(a - median) for a in amounts])
            for t in baseline:
                amt = abs(t.amount)
                z = (amt - mean) / stdev if stdev > 0 else 0.0
                mod_z = 0.6745 * (amt - median) / mad if mad > 0 else 0.0
                by_z = z >= _T.txn_zscore
                by_mad = mad > 0 and mod_z >= _T.txn_modified_zscore
                if not (by_z or by_mad):
                    continue
                method = "z-score" if by_z else "modified z-score (MAD)"
                out.append(
                    Anomaly(
                        type="transaction_outlier",
                        severity=SEVERITY_MEDIUM,
                        title=f"Outlier transaction ({t.symbol})",
                        explanation=(
                            f"A {t.type} of {amt:,.0f} in {t.symbol} on {t.date} is a "
                            f"statistical outlier ({method}) vs the client's typical "
                            "transaction size."
                        ),
                        evidence={
                            "symbol": t.symbol,
                            "amount": t.amount,
                            "date": t.date,
                            "zscore": round(z, 2),
                            "modified_zscore": round(mod_z, 2),
                            "flagged_by": method,
                        },
                        recommendation_hint="Review for error or unusual activity.",
                    )
                )
        return out

    def _duplicate_transactions(self, fin: ClientFinancialData) -> list[Anomaly]:
        out: list[Anomaly] = []
        seen: dict[tuple[str, str, float], date] = {}
        for t in fin.transactions:
            key = (t.type, t.symbol, round(t.amount, 2))
            d = _parse_date(t.date)
            prev = seen.get(key)
            if prev is not None and d is not None and abs((d - prev).days) <= _T.duplicate_window_days:
                out.append(
                    Anomaly(
                        type="duplicate_transaction",
                        severity=SEVERITY_MEDIUM,
                        title=f"Possible duplicate {t.type} ({t.symbol})",
                        explanation=(
                            f"Two {t.type} transactions of {abs(t.amount):,.0f} in "
                            f"{t.symbol} occurred within {_T.duplicate_window_days} "
                            "days — possible double entry."
                        ),
                        evidence={"symbol": t.symbol, "amount": t.amount, "date": t.date},
                        recommendation_hint="Verify this is not a duplicate submission.",
                    )
                )
            if d is not None:
                seen[key] = d
        return out

    def _fee_ratio(
        self, m: PortfolioMetrics, market_avg_fee: float | None
    ) -> list[Anomaly]:
        # The benchmark average fee comes from market data; fall back to a
        # conservative default when market context is unavailable.
        benchmark = market_avg_fee if market_avg_fee else 0.01
        if m.weighted_expense_ratio <= benchmark * _T.fee_ratio_multiple:
            return []
        return [
            Anomaly(
                type="high_fees",
                severity=SEVERITY_LOW,
                title="Above-average fund fees",
                explanation=(
                    f"Weighted expense ratio is {m.weighted_expense_ratio:.2%}, above "
                    f"{_T.fee_ratio_multiple:.1f}x the market average of {benchmark:.2%}."
                ),
                evidence={
                    "weighted_expense_ratio": m.weighted_expense_ratio,
                    "benchmark_avg": benchmark,
                },
                recommendation_hint="Review high-cost funds for cheaper equivalents.",
            )
        ]


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None
