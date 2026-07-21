from __future__ import annotations

import dataclasses
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ..portfolio_handler import Portfolio


@dataclasses.dataclass
class BacktestOutput:
    """The minimal record of a backtest run ("tout").

    Everything a report needs, and nothing a live ``Portfolio`` carries
    (accounts, holdings, executioner, ...). Build one from a finished
    ``Portfolio`` via :meth:`from_portfolio` and keep/pickle/compare that
    instead of the ``Portfolio`` itself.
    """

    name: str
    starting_cash: float
    portfolio_value: pd.Series  # index: timestamp (sorted), values: portfolio value
    order_book: pd.DataFrame  # raw Portfolio.order_book, one row per fill

    def __post_init__(self):
        pv = self.portfolio_value.copy()
        pv.index = pd.DatetimeIndex(pv.index)
        self.portfolio_value = pv.sort_index()

    @classmethod
    def from_portfolio(cls, portfolio: Portfolio, starting_cash: float, name: str = "strategy") -> "BacktestOutput":
        hist = portfolio.account_history
        return cls(
            name=name,
            starting_cash=starting_cash,
            portfolio_value=hist["value"],
            order_book=portfolio.order_book.copy(),
        )


class BacktestReport:
    """Computes scalar metrics and plots from a single :class:`BacktestOutput`."""

    def __init__(self, tout: BacktestOutput, risk_free_rate: float = 0.0):
        self.tout = tout
        self.risk_free_rate = risk_free_rate

    # ------------------------------------------------------------------ core series

    def equity_curve(self, base: float = 100.0) -> pd.Series:
        """Portfolio value rescaled so it starts at ``base``."""
        return self.tout.portfolio_value / self.tout.starting_cash * base

    @property
    def returns(self) -> pd.Series:
        """Per-bar simple returns of the portfolio value series."""
        return self.tout.portfolio_value.pct_change().dropna()

    def _periods_per_year(self) -> float:
        idx = self.tout.portfolio_value.index
        if len(idx) < 2:
            return 252.0
        median_days = np.median(np.diff(idx.values).astype("timedelta64[D]").astype(float))
        return 365.25 / median_days if median_days > 0 else 252.0

    def _yearly_returns(self) -> pd.Series:
        pv = self.tout.portfolio_value
        yearly_last = pv.resample("YE").last()
        prev = yearly_last.shift(1)
        prev.iloc[0] = self.tout.starting_cash
        return yearly_last / prev - 1

    def trade_pnls(self) -> pd.DataFrame:
        """One row per *closed* round-trip trade (matched by order id).

        Open positions (an id with only one fill so far) are excluded since
        they have no realized pnl yet.
        """
        ob = self.tout.order_book
        columns = ["id", "symbol", "entry_time", "exit_time", "entry_price", "exit_price", "pnl", "return_pct"]
        if ob.empty:
            return pd.DataFrame(columns=columns)

        ob = ob.copy()
        ob["cash_change"] = np.where(ob["order_type"] == "buy", -ob["total_cost"], ob["total_cost"])

        rows = []
        for order_id, g in ob.groupby("id"):
            g = g.sort_values("fill_timestamp")
            if len(g) < 2:
                continue
            entry, exit_ = g.iloc[0], g.iloc[-1]
            pnl = g["cash_change"].sum()
            rows.append({
                "id": order_id,
                "symbol": entry["symbol"],
                "entry_time": entry["fill_timestamp"],
                "exit_time": exit_["fill_timestamp"],
                "entry_price": entry["fill_price"],
                "exit_price": exit_["fill_price"],
                "pnl": pnl,
                "return_pct": pnl / entry["total_cost"] if entry["total_cost"] else np.nan,
            })
        return pd.DataFrame(rows, columns=columns)

    # ------------------------------------------------------------------ scalars

    def scalars(self) -> pd.Series:
        pv = self.tout.portfolio_value
        rets = self.returns
        ppy = self._periods_per_year()
        n_years = (pv.index[-1] - pv.index[0]).days / 365.25

        total_return = pv.iloc[-1] / self.tout.starting_cash - 1
        cagr = (pv.iloc[-1] / self.tout.starting_cash) ** (1 / n_years) - 1 if n_years > 0 else np.nan

        ann_vol = rets.std() * np.sqrt(ppy)
        sharpe = (rets.mean() * ppy - self.risk_free_rate) / ann_vol if ann_vol else np.nan

        downside_std = rets[rets < 0].std()
        sortino = (rets.mean() * ppy - self.risk_free_rate) / (downside_std * np.sqrt(ppy)) if downside_std else np.nan

        drawdown = pv / pv.cummax() - 1
        max_dd = drawdown.min()
        calmar = cagr / abs(max_dd) if max_dd else np.nan

        yearly = self._yearly_returns()

        trades = self.trade_pnls()
        n_trades = len(trades)
        wins = trades.loc[trades["pnl"] > 0, "pnl"] if n_trades else pd.Series(dtype=float)
        losses = trades.loc[trades["pnl"] < 0, "pnl"] if n_trades else pd.Series(dtype=float)
        win_rate = len(wins) / n_trades if n_trades else np.nan
        profit_factor = wins.sum() / -losses.sum() if len(losses) and losses.sum() != 0 else np.nan
        avg_holding_days = (
            (trades["exit_time"] - trades["entry_time"]).dt.total_seconds().mean() / 86400 if n_trades else np.nan
        )

        return pd.Series({
            "total_return": total_return,
            "cagr": cagr,
            "ann_volatility": ann_vol,
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown": max_dd,
            "calmar": calmar,
            "yearly_return_mean": yearly.mean(),
            "yearly_return_std": yearly.std(),
            "num_trades": n_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win": wins.mean() if len(wins) else np.nan,
            "avg_loss": losses.mean() if len(losses) else np.nan,
            "avg_holding_days": avg_holding_days,
        }, name=self.tout.name)

    # ------------------------------------------------------------------ plots

    def plot_equity_curve(self, base: float = 100.0) -> go.Figure:
        eq = self.equity_curve(base)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines", name=self.tout.name))
        fig.update_layout(title="Equity Curve", xaxis_title="Date", yaxis_title=f"Value (start={base})")
        return fig

    def plot_drawdown(self) -> go.Figure:
        pv = self.tout.portfolio_value
        dd = (pv / pv.cummax() - 1) * 100
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dd.index, y=dd.values, mode="lines", fill="tozeroy", name=self.tout.name))
        fig.update_layout(title="Drawdown", xaxis_title="Date", yaxis_title="Drawdown (%)")
        return fig

    def plot_yearly_returns(self) -> go.Figure:
        yearly = self._yearly_returns() * 100
        fig = go.Figure()
        fig.add_trace(go.Bar(x=yearly.index.year.astype(str), y=yearly.values, name=self.tout.name))
        fig.update_layout(title="Yearly Returns", xaxis_title="Year", yaxis_title="Return (%)")
        return fig

    def plot_returns_distribution(self) -> go.Figure:
        rets = self.returns * 100
        fig = go.Figure()
        fig.add_trace(go.Histogram(x=rets.values, name=self.tout.name))
        fig.update_layout(title="Period Returns Distribution", xaxis_title="Return (%)", yaxis_title="Count")
        return fig


class BacktestComparison:
    """Compares several :class:`BacktestReport` (strategies and/or a benchmark).

    A benchmark is just another ``BacktestReport`` (e.g. built from a
    buy-and-hold ``BacktestOutput``) - pass it separately only so it can be
    labelled distinctly in the scalar table if desired; it is otherwise
    treated exactly like the other reports.
    """

    def __init__(self, reports: Sequence[BacktestReport], benchmark: Optional[BacktestReport] = None):
        self.reports = list(reports)
        self.benchmark = benchmark

    @property
    def _all(self) -> List[BacktestReport]:
        return self.reports + ([self.benchmark] if self.benchmark is not None else [])

    def scalar_table(self) -> pd.DataFrame:
        return pd.concat([r.scalars() for r in self._all], axis=1)

    def plot_equity_curves(self, base: float = 100.0) -> go.Figure:
        fig = go.Figure()
        for r in self._all:
            eq = r.equity_curve(base)
            fig.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines", name=r.tout.name))
        fig.update_layout(title="Equity Curve Comparison", xaxis_title="Date", yaxis_title=f"Value (start={base})")
        return fig

    def plot_drawdowns(self) -> go.Figure:
        fig = go.Figure()
        for r in self._all:
            pv = r.tout.portfolio_value
            dd = (pv / pv.cummax() - 1) * 100
            fig.add_trace(go.Scatter(x=dd.index, y=dd.values, mode="lines", name=r.tout.name))
        fig.update_layout(title="Drawdown Comparison", xaxis_title="Date", yaxis_title="Drawdown (%)")
        return fig

    def plot_yearly_returns(self) -> go.Figure:
        fig = go.Figure()
        for r in self._all:
            yearly = r._yearly_returns() * 100
            fig.add_trace(go.Bar(x=yearly.index.year.astype(str), y=yearly.values, name=r.tout.name))
        fig.update_layout(title="Yearly Returns Comparison", xaxis_title="Year", yaxis_title="Return (%)", barmode="group")
        return fig
