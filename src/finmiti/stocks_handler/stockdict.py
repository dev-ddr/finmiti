import numpy as np
import pandas as pd

from concurrent.futures import ThreadPoolExecutor

from .stock import Stock
import duckdb


class StockDict:
    """Class to handle functionalities related to multiple stocks, using symbol as keys."""

    def __init__(self, stocks: list[Stock]=None) -> None:
        self.stockdict: dict[str, Stock] = {}
        if stocks is not None:
            for stock in stocks:
                self.add(stock)
            


    def __repr__(self) -> str:
        return f"StockList object with {len(self.stockdict)} Stocks"

    def __type__(self) -> str:
        return "StockDict"

    def __getitem__(self, i: str|int):
        if isinstance(i, str):
            return self.stockdict[i]
        elif isinstance(i, int):
            return list(self.stockdict.values())[i]
        else:
            raise ValueError("can only give string or integer values")

    def __len__(self):
        return len(self.stockdict)

    def __iter__(self):
        return iter(self.stockdict.values())

    def __contains__(self, symbol: str) -> bool:
        return symbol in self.stockdict

    def add(self, stock: Stock) -> None:
        """Adds or replaces a Stock object using its ticker symbol."""
        self.stockdict[stock.symbol] = stock
        return

    def remove(self, symbol: str) -> None:
        """Removes a stock by its symbol, if it exists."""
        self.stockdict.pop(symbol, None)
        return

    def get(self, symbol: str) -> Stock | None:
        return self.stockdict.get(symbol)

    @property
    def symbols(self) -> list[str]:
        return list(self.stockdict.keys())

    @property
    def stocklist(self) -> list[Stock]:
        return list(self.stockdict.values())

    def load_multiple_stocks(self, symbols: list[str], *args, **kwargs) -> None:
        """Loads multiple stocks using their symbols and adds them to the stockdict."""
        for symbol in symbols:
            try:
                stock = Stock(symbol, *args, **kwargs)
                self.add(stock)
            except Exception as e:
                print(f"[{symbol}] Error loading stock:\n{e}")
        return

    def apply(self, method_name: str, *args, **kwargs) -> dict[str, any]:
        """Applies a method to all Stock objects and returns a dict of results."""
        results = {}
        for symbol, stock in self.stockdict.items():
            method = getattr(stock, method_name, None)
            if callable(method):
                results[symbol] = method(*args, **kwargs)
            else:
                results[symbol] = None
        return results

    def load_historical_data(self, *args, max_workers: int = 5, remove_error_stocks: bool = True, print_info: bool = True, **kwargs) -> None:
        """Calls stock.load_historical_data() for all stocks using multithreading."""

        def _load(stock: Stock):
            try:
                if print_info:
                    print(f"[{stock.symbol}] Loading historical data...")
                stock.hist_data0 = stock.load_historical_data(*args, **kwargs)
                stock.hist_data0 = stock.hist_data0[~stock.hist_data0.index.duplicated(keep="first")]  # removing duplicate timestamps
                if print_info:
                    print(f"[{stock.symbol}] Data loaded successfully.")
            except Exception as e:
                print(f"[{stock.symbol}] Error loading data:\n{e}")
                errors.append(stock.symbol)

        errors = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(_load, self.stockdict.values())
        if remove_error_stocks:
            for symbol in errors:
                print(f"[{symbol}] Removing stock due to loading error.")
                self.remove(symbol)

        return
