"""Module consisting of base class of stock"""

import os as _os
from pathlib import Path
import datetime as _dtm
import numpy as _np
import pandas as _pd

from typing import TypeVar, Union, Optional

from enum import Enum

import duckdb

from ..constants import EXCHANGE, EXCHANGE_TYPE, INTERVAL


def append_it(data: _pd.DataFrame, filepath: str) -> None:
    """Appends the data on the given filepath after comparing Indexes of both the data.

    This compares the data already at the given filepath, and then appends only the data not already present.

    Parameters
    ----------
    data : _pd.DataFrame
        data frame with Datetime like index
    filepath : str
        filepath, where the dataframe will be appended.
    """
    try:
        df1 = data.combine_first(_pd.read_parquet(filepath)).sort_index()
        df1.to_parquet(filepath)
    except FileNotFoundError as e:
        print(f"Creating the file - {filepath}")
        data.to_parquet(filepath)
    return


class Stock:
    def __init__(
        self,
        symbol: str,
        exchange: EXCHANGE = EXCHANGE.nse,
        exchange_type: EXCHANGE_TYPE = EXCHANGE_TYPE.cash,
    ) -> None:
        """Manages the data for list of stocks.

        Parameters
        ----------
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

    @property
    def foldname(self):
        return self.exchange + "_" + self.exchange_type + "_" + self.symbol
    
    def __repr__(self):
        return f"{self.symbol} stock class"

    def get_filename(self, date: _dtm.datetime, interval: INTERVAL):
        return f"{date.year}{str(date.month).zfill(2)}_{interval.value}.parquet"

    def save_historical_data(
        self,
        data: _pd.DataFrame,
        interval: INTERVAL,
        local_data_foldpath: str,
        overwrite: bool = False,
    ) -> None:
        """saves the historical stock data.

        Multiple files, each for saparate month data is created.

        Parameters
        ----------
        data : _pd.DataFrame
            Data to be saved. It should be indexed with Datetime values.
        interval : str
            time interval of the data
        local_data_foldpath : str
            path to folder where the data will be stored. Inside this folder, multiple folders of individual stocks are created and inside that stock folder, historical data and other data is stored.
        overwrite : bool, False
            wheather to overwrite the existing file or just append the new data. default False. If True then it will overwrite the present data.
        """
        ### creating the folder
        data_foldpath = Path(local_data_foldpath) / self.foldname
        Path(data_foldpath).mkdir(exist_ok=True)
        
        ### writing the data
        data["filename"] = data.index.to_series().apply(lambda x: self.get_filename(x, interval))
        for fnm, df in data.groupby("filename"):
            df = df.drop(columns="filename")
            filepath = data_foldpath / fnm

            if overwrite:
                print("Overwriting:-", filepath)
                df.to_parquet(filepath)
            else:
                append_it(df, filepath)
            pass
        return

    def load_historical_data(
        self, 
        start: Union[str, _dtm.datetime], 
        end: Union[str, _dtm.datetime], 
        local_data_foldpath: str,
        interval: INTERVAL = INTERVAL.one_day,
        fill_holidays: bool = False,
        remove_weekends: bool = True,
    ) -> _pd.DataFrame:
        """Loads the data from local_directory

        Parameters
        ----------
        start : Union[str, _dtm.datetime]
            start date of the data. The data for this date will be downloaded
        end : Union[str, _dtm.datetime]
            end date of the data. The data for this date will be downloaded
        local_data_foldpath : str
            path to folder where the data is stored. inside this folder there are multiple sub-folders of individual stock. You only have to give the parent folder path.
        interval : INTERVAL, Optional
            time interval of data. it should be of type INTERVAL enum. Defaults to one day interval
        fill_holidays : bool, Default is False
            The data is not available for the holidays. If this is made True then the previous day data will be filled in as that day's data and that missing holiday row will be inserted.
        remove_weekends : bool, Default is True
            Sometimes the markets are open on saturdays and sundays. These are vary rare and thus are removed from historical data while loading.

        Returns
        -------
        _pd.DataFrame
            data

        Raises
        ------
        ValueError
            if no data is found
        """
        data_foldpath = Path(local_data_foldpath) / self.foldname
        Path(data_foldpath).mkdir(exist_ok=True)

        if isinstance(start, _dtm.datetime):
            start = start.strftime("%Y-%m-%d")
        if isinstance(end, _dtm.datetime):
            end = end.strftime("%Y-%m-%d")

        # DuckDB SQL
        query = f"""
        SELECT *
        FROM read_parquet('{data_foldpath}/*_{interval.value}.parquet')
        WHERE Datetime BETWEEN TIMESTAMP '{start}' AND TIMESTAMP '{end}'
        ORDER BY Datetime
        """
        with duckdb.connect() as con:
            df = con.execute(query).df()
        d1 = df.set_index("Datetime")
        if fill_holidays:
            # Create full business day range
            full_range = _pd.date_range(start=d1.index.min(), end=d1.index.max(), freq="B")
            d1 = d1.reindex(full_range).ffill()
            d1.index.name = "Datetime"
        if remove_weekends:
            d1 = d1[d1.index.weekday < 5]
        return d1
    
    @property
    def scrip(self) -> _pd.DataFrame:
        """scrip for client 5paisa.

        Returns
        -------
        _pd.DataFrame
            scrip data.
        """
        return self._scrip

    @scrip.setter
    def scrip(self, data: _pd.DataFrame) -> None:
        """saves the scrip

        Parameters
        ----------
        data : _pd.DataFrame
            scrip data. This can be optained by ScripMaster.get_scrip() method.
        """
        self._scrip = data
        return


