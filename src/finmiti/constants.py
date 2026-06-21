from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import TypedDict, Optional, get_type_hints, Dict, Tuple
import pandas as pd
import uuid
from datetime import datetime

import numpy as np


class EXCHANGE(Enum):
    nse = "N"
    bse = "B"
    mcx = "MCX"


class EXCHANGE_TYPE(Enum):
    cash = "C"
    derivative = "D"
    currency = "U"


class INTERVAL(Enum):
    one_day = "1d"
    one_min = "1m"
    five_min = "5m"
    fifteen_min = "15m"


class ORDERTYPE(Enum):
    buy = "buy"
    sell = "sell"


@dataclass
class Order:
    timestamp: datetime | np.datetime64
    symbol: str
    price: float
    order_type: ORDERTYPE
    ### most of the below attributes are for backtesting and evaluation purpose.
    ### value_frac decides how much fraction of the total cash goes into this order
    value_frac: float = None
    id: Optional[str] = None
    target: Optional[float] = None
    stop_loss: Optional[float] = None
    hold_uptill: Optional[datetime] = None
    remarks: Optional[str] = None
    ### items for handling order fill related noise. These will be handlerd by executioner object. They will fill these values hence they are None initialized.
    fill_price: float = None
    fill_qty: float = None
    fill_timestamp: datetime | np.datetime64 = None
    fill_remarks: Optional[str] = None
    brokerage_cost: float = 0
    total_cost: float = None
    ### the account id is for isolating the cash.
    account_idx: int = 0

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class StockData:
    """
    Strategy input data (TorchGeometric-style Data object).
    All arrays must be aligned on the last dimension. Here, the data could be only the last value or it could be the array of historical data. The timestamps must match those values as well.
    """

    symbol: str
    ### market data entry
    timestamp: datetime | np.datetime64
    open: float
    high: float
    low: float
    close: float
    volume: float
    ### anything else you want
    features: Optional[Dict[str, np.ndarray]] = None


@dataclass(frozen=True, slots=True)
class DiEdgeData:
    """Directed edge from one stock to another."""

    start_node_symbol: str
    end_node_symbol: str
    features: Optional[Dict[str, np.ndarray]] = None


@dataclass(frozen=True, slots=True)
class MarketGraphData:
    """
    Multi-asset market snapshot.
    """

    ### the time of the data. The StockData could have historical data upto this timestamp.
    timestamp: datetime | np.datetime64
    ### nodes, named after its symbol
    stocks: Dict[str, StockData]
    ### edges: (src, dst) --> edge feature vector. from one node to other.
    edges: Optional[DiEdgeData] = None
    ### optional global features (VIX, index returns, liquidity, etc.)
    global_features: Optional[Dict[str, np.ndarray]] = None


### Error class
class StockDataNotAvailableError(Exception):
    """Raised when stock data is missing for a given timestamp."""
    def __init__(self, timestamp:datetime=None, symbol: str=None):
        message = f"Stock data not available. No data for {symbol} on {timestamp}."
        super().__init__(message)
    

class NegativeCashError(Exception):
    """Raised when the cash of an account goes negative."""
    def __init__(self, account_idx:int=None):
        message=f"The cash in an account cannot go negative. Negative cash registered in account - {account_idx}"
        super().__init__(message)

class OrderTypeError(Exception):
    """Raised when the ordertype is out of pre-defined orders"""
    def __init__(self, order: Order=None):
        message=f"The ordertype must be from finmetry.constants.ORDERTYPE. For {order.symbol} on {order.timestamp} got {order.order_type}."
        super().__init__(message)

class NotEnoughData(Exception):
    """Raised when there are not enough historical data for feature computation"""
    def __init__(self, timestamp:datetime=None, symbol: str=None):
        message = f"Not enough data available. for {symbol} on {timestamp}."
        super().__init__(message)
    