from importlib.metadata import version
__version__ = version("finmetry")


from . import clients
from .stocks_handler import Stock, StockDict
from . import constants
from .strategy_handler import StrategyBase, StgDataLoader
from .portfolio_handler import Portfolio, Account
from .backtest_handler import Backtester

from .utils import *
