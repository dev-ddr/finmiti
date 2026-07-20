"""Module consisting of the abstract base class of stock.

`Stock` defines the contract shared by every storage backend (parquet/DuckDB in
`StockDDB`, Postgres in `StockPG`, ...): the symbol/exchange identity, the
`hist_data0` state bag poked by client code (e.g. `clients.client_5paisa`), and
the four data-handling operations every backend must implement.
"""

from abc import ABC, abstractmethod
import datetime as _dtm
from typing import Optional, Union

import pandas as _pd

from ..constants import EXCHANGE, EXCHANGE_TYPE, INTERVAL


class Stock(ABC):
    def __init__(
        self,
        symbol: str,
        exchange: EXCHANGE = EXCHANGE.nse,
        exchange_type: EXCHANGE_TYPE = EXCHANGE_TYPE.cash,
    ) -> None:
        """Manages the data for a stock.

        Parameters
        ----------
        symbol : str
            Stock symbol as available online.
        exchange : EXCHANGE
            Stock Exchange. can be N, B, M for Nifty, BSE and MCX respectively. By default N
        exchange_type : EXCHANGE_TYPE
            Type of Stock Exchange. can be C, D or U for Cash, Derivative or Currency respectively. By default C.
        """
        self.symbol = symbol
        if isinstance(exchange, EXCHANGE):
            self.exchange = exchange.value
        else:
            raise ValueError("exchange can only be of type EXCHANGE enum")

        if isinstance(exchange_type, EXCHANGE_TYPE):
            self.exchange_type = exchange_type.value
        else:
            raise ValueError("exchange_type can only be of type EXCHANGE_TYPE enum")

        self.hist_data0: Optional[_pd.DataFrame] = None

    def __repr__(self):
        return f"{self.symbol} {self.__class__.__name__} class"

    @abstractmethod
    def save_historical_data(self, data: _pd.DataFrame, interval: INTERVAL, *args, **kwargs):
        """Persists historical OHLCV data for this stock. Backend-specific signature/semantics."""
        raise NotImplementedError

    @abstractmethod
    def load_historical_data(self, start: Union[str, _dtm.datetime], end: Union[str, _dtm.datetime], *args, interval: INTERVAL = INTERVAL.one_day, **kwargs) -> _pd.DataFrame:
        """Loads historical OHLCV data for this stock over [start, end]."""
        raise NotImplementedError

    @abstractmethod
    def coverage(self, *args, interval: Optional[INTERVAL] = None, **kwargs) -> list:
        """Returns coverage records (start/end/rows, at least) for this stock."""
        raise NotImplementedError

    @abstractmethod
    def update_hist_data(self, client, *args, interval: INTERVAL = INTERVAL.one_day, end: Union[str, _dtm.datetime, None] = None, default_start: str = "2017-01-01", overwrite: bool = False, start: Union[str, _dtm.datetime, None] = None, **kwargs) -> Optional[_pd.DataFrame]:
        """Brings stored historical data up to ``end`` by downloading only the missing tail."""
        raise NotImplementedError
