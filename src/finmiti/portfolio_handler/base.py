from typing import Dict, List, Optional, TypedDict
import pandas as pd
from datetime import datetime
import numpy as np

from ..executioners import ExecutionModel
from ..constants import Order, MarketGraphData, ORDERTYPE, NegativeCashError, OrderTypeError


class PorfolioSnapshot(TypedDict):
    """A snapshot of the portfolio at a given Datetime."""

    timestamp: str | datetime | np.datetime64
    value: float


class Portfolio:
    def __init__(self, executioner: ExecutionModel, starting_cash: float = 100.0, total_accounts: int = 1):
        self.executioner = executioner
        self.total_accounts = total_accounts

        self.accounts: List[Account] = [Account(account_idx=i, starting_cash=starting_cash / self.total_accounts, executioner=self.executioner) for i in range(total_accounts)]
        self.history: List[PorfolioSnapshot] = []

    def mark_to_market(self, market_data: MarketGraphData):
        value = 0.0
        for account in self.accounts:
            account.mark_to_market(market_data=market_data)
            account_snapshot = account.account_history[-1]
            value += account_snapshot["cash"] + account_snapshot["holdings_value"]
        self.history.append(PorfolioSnapshot(timestamp=market_data.timestamp, value=value))
        return

    def on_order(self, order: Order):
        account = self.accounts[order.account_idx]
        account.on_order(order=order)
        return

    def get_exit_orders(self, market: MarketGraphData) -> List[Order]:
        exit_orders: List[Order] = []
        for account in self.accounts:
            exit_orders += account.get_exit_orders(market=market)
        return exit_orders

    @property
    def order_book(self) -> pd.DataFrame:
        d1 = pd.DataFrame()
        for account in self.accounts:
            account_ob = pd.DataFrame(account.order_book)
            d1 = pd.concat([d1, account_ob], ignore_index=True)
        d1["order_type"] = d1["order_type"].apply(lambda x: x.value)
        return d1

    @property
    def arranged_order_book(self) -> pd.DataFrame:
        keys = ["symbol", "fill_price", "fill_qty", "fill_timestamp", "total_cost", "account_idx", "hold_uptill", "remarks"]
        d1 = self.order_book
        d2 = d1.groupby("order_type").get_group("buy").set_index("id")[keys].add_prefix("buy_")
        d3 = d1.groupby("order_type").get_group("sell").set_index("id")[keys].add_prefix("sell_")
        d4 = pd.concat([d2, d3], axis=1).sort_values(by="buy_fill_timestamp")
        return d4

    @property
    def account_history(self) -> pd.DataFrame:
        return pd.DataFrame(self.history).set_index("timestamp")

    @property
    def holdings(self) -> pd.DataFrame:
        d1 = pd.DataFrame()
        for account in self.accounts:
            account_hd = pd.DataFrame(account.holdings.values())
            d1 = pd.concat([d1, account_hd], axis=0, ignore_index=True)
        return d1


class Holding(TypedDict):
    """A holding entry."""

    order_id: str
    account_idx: int
    symbol: str
    qty: float
    entry_price: float
    ltp: float
    target: Optional[float] = None
    stop_loss: Optional[float] = None
    holding_start_date: Optional[datetime]
    holding_end_date: Optional[datetime]


class AccountSnapshot(TypedDict):
    """A snapshot of the portfolio at a given Datetime."""

    timestamp: str | datetime | np.datetime64
    holdings_value: float
    cash: float


class Account:
    def __init__(self, account_idx: int, executioner: ExecutionModel, starting_cash: float = 100.0) -> None:
        self.executioner = executioner
        self.idx = account_idx
        self.cash = starting_cash

        ### holdings are indexed by its holding_id, which is order_id.
        self.holdings: Dict[str, Holding] = {}
        self.order_book: List[Order] = []
        self.account_history: List[AccountSnapshot] = []

    def mark_to_market(self, market_data: MarketGraphData):
        """
        Update the ltp of holdings from the latest market_data
        Also records portfolio value and cash at this point in time.
        """
        holdings_value = 0.0
        for _, holding in self.holdings.items():
            symbol = holding["symbol"]
            try:
                holding["ltp"] = market_data.stocks[symbol].close
            except KeyError:
                print(f"Cannot update the data for {symbol}, due to missing data on {market_data.timestamp}")
            holdings_value += holding["qty"] * holding["ltp"]

        self.account_history.append(AccountSnapshot(timestamp=market_data.timestamp, holdings_value=holdings_value, cash=self.cash))
        return

    def on_order(self, order: Order) -> None:
        order = self.executioner.fill_order(available_cash=self.cash, order=order)

        qty = order.fill_qty
        price = order.fill_price
        total_cost = order.total_cost

        if order.order_type == ORDERTYPE.buy:
            qty *= 1
            total_cost *= 1
        elif order.order_type == ORDERTYPE.sell:
            qty *= -1
            total_cost *= -1
        else:
            raise OrderTypeError(order=order)

        ### change the cash available in the portfolio. If it is sell order then total_cost will be negative and thus that amount will be added to self.cash.
        self.cash = self.cash - total_cost
        if self.cash < 0:
            raise NegativeCashError(account_idx=self.idx)

        ### add new holding or edit the holding
        holding = self.holdings.get(order.id, None)
        if holding is None:
            holding = Holding(
                order_id=order.id,
                account_idx=self.idx,
                symbol=order.symbol,
                qty=qty,
                entry_price=price,
                ltp=price,
                target=order.target,
                stop_loss=order.stop_loss,
                holding_start_date=order.timestamp,
                holding_end_date=order.hold_uptill,
            )
            self.holdings[order.id] = holding
        else:
            assert (holding["qty"] + qty) == 0, "If you are trying to exit a position then quantity must match with the order_id. Partial fills shall be applied as separate orders."
            self.holdings.pop(order.id, None)

        ### add order to orderbook
        self.order_book.append(order)

        return

    def get_exit_orders(self, market: MarketGraphData) -> List[Order]:
        """
        Check stops, targets, expiry.
        Emits exit Orders if needed.
        """
        exit_orders: List[Order] = []

        for order_id, holding in self.holdings.items():
            try:
                close = market.stocks[holding["symbol"]].close
                low = market.stocks[holding["symbol"]].low
                high = market.stocks[holding["symbol"]].high
                ### sometimes the data for any particular stock may be missing on a given timestamp. It will thus hault the backtest. To avoid haulting, bypass it.
            except KeyError:
                print(f"Cannot check for exit orders for {holding['symbol']}, due to missing data on {market.timestamp}")
                continue

            # reason = None
            # if holding["stop_loss"] and close <= holding["stop_loss"]:
            #     reason = "stop_loss"
            #     # exit_price = holding["stop_loss"]
            # elif holding["target"] and close >= holding["target"]:
            #     reason = "target"
            #     # exit_price = holding["target"]
            # elif holding["holding_end_date"] and market.timestamp >= holding["holding_end_date"]:
            #     reason = "expiry"
            # else:
            #     continue
            # exit_price = close

            reason = None
            if holding["stop_loss"] and  low<= holding["stop_loss"]:
                reason = "stop_loss"
                exit_price = holding["stop_loss"]
            elif holding["target"] and high >= holding["target"]:
                reason = "target"
                exit_price = holding["target"]
            elif holding["holding_end_date"] and market.timestamp >= holding["holding_end_date"]:
                reason = "expiry"
                exit_price = close
            else:
                continue


            exit_order_type = ORDERTYPE.sell if holding["qty"] > 0 else ORDERTYPE.buy
            exit_orders.append(
                Order(
                    timestamp=market.timestamp,
                    symbol=holding["symbol"],
                    price=exit_price,
                    order_type=exit_order_type,
                    fill_qty=abs(holding["qty"]),
                    remarks=reason,
                    account_idx=self.idx,
                    id=order_id,
                )
            )

        return exit_orders
