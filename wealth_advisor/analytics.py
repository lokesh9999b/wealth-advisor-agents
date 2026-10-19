"""Pure, deterministic portfolio math.

Separated from agents and tools so it can be unit-tested in isolation and
reused. No I/O, no logging — just numbers in, :class:`PortfolioMetrics` out.
"""

from __future__ import annotations

from collections import defaultdict

from .schemas import ClientFinancialData, PortfolioMetrics


def compute_portfolio_metrics(financial: ClientFinancialData) -> PortfolioMetrics:
    """Compute allocation, concentration, drift, cash, and fee metrics.

    Gracefully handles an empty / cashless portfolio (returns zeroed metrics
    instead of dividing by zero).
    """
    total_cash = sum(acct.cash_balance for acct in financial.accounts)

    by_class: dict[str, float] = defaultdict(float)
    total_invested = 0.0
    top_symbol = None
    top_value = 0.0
    fee_weighted_sum = 0.0
    holdings_count = 0

    # Aggregate holdings by symbol for concentration (same symbol across accts).
    by_symbol: dict[str, float] = defaultdict(float)

    for acct in financial.accounts:
        for h in acct.holdings:
            holdings_count += 1
            by_class[h.asset_class] += h.market_value
            by_symbol[h.symbol] += h.market_value
            total_invested += h.market_value
            fee_weighted_sum += h.market_value * h.expense_ratio

    for symbol, value in by_symbol.items():
        if value > top_value:
            top_value, top_symbol = value, symbol

    total_aum = total_invested + total_cash

    allocation: dict[str, float] = {}
    if total_aum > 0:
        for cls, value in by_class.items():
            allocation[cls] = round(value / total_aum, 4)
        allocation["cash"] = round(total_cash / total_aum, 4)

    target = financial.target_allocation
    drift: dict[str, float] = {}
    # Drift is only meaningful when a target allocation is provided.
    if target:
        for cls in set(allocation) | set(target):
            drift[cls] = round(allocation.get(cls, 0.0) - target.get(cls, 0.0), 4)

    weighted_expense = (
        round(fee_weighted_sum / total_invested, 5) if total_invested > 0 else 0.0
    )

    top_holding: dict[str, object] = {}
    if top_symbol is not None and total_aum > 0:
        top_holding = {
            "symbol": top_symbol,
            "value": round(top_value, 2),
            "pct": round(top_value / total_aum, 4),
        }

    return PortfolioMetrics(
        total_aum=round(total_aum, 2),
        total_cash=round(total_cash, 2),
        cash_pct=round(total_cash / total_aum, 4) if total_aum > 0 else 0.0,
        allocation=allocation,
        target_allocation=dict(target),
        allocation_drift=drift,
        top_holding=top_holding,
        holdings_count=holdings_count,
        weighted_expense_ratio=weighted_expense,
    )
