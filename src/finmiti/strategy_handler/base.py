from abc import ABC, abstractmethod
from typing import List, Iterator
import datetime as dtm

from ..stocks_handler import StockDict
from ..constants import Order
from ..constants import MarketGraphData, StockData
from ..utils import str_to_dtm


class StgDataLoader(ABC):
    @abstractmethod
    def __getitem__(self, idx: str | dtm.datetime) -> MarketGraphData:
        raise NotImplementedError
    
    @abstractmethod
    def __len__(self) -> int:
        raise NotImplementedError
    
    @abstractmethod
    def __iter__(self) -> Iterator[MarketGraphData]:
        raise NotImplementedError
    

class StrategyBase(ABC):
    def __call__(self, data: MarketGraphData) -> List[Order]:
        orders = self.forward(data)

        if not isinstance(orders, list):
            raise TypeError("Strategy.forward must return List[Order]")

        return orders

    @abstractmethod
    def forward(self, data: MarketGraphData) -> List[Order]:
        raise NotImplementedError
