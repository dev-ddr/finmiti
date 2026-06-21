"""
This module contains the objects related to 5paisa client

@author: Rathod Darshan
"""

import py5paisa as p5
import pandas as pd
import datetime as dtm
from typing import Union, TypedDict

from ..stocks_handler import Stock, StockDict

from ..constants import INTERVAL


class ScripMaster:
    """ScripMaster contains all the scipts of 5paisa client.

    To get the name and symbol of any script, this class needs to be accessed. This class just filters the data from single .csv.
    """

    def __init__(self, filepath: str = None) -> None:
        """Initializes the ScripMaster class.

        Loads the .csv file into data attribute.

        Parameters
        ----------
        filepath : str, optional
            filepath to .csv file. If filepath is given then it reads the file, else it will download the file. by default None
        """
        if filepath is not None:
            self.data = pd.read_pickle(filepath)
        else:
            self.data = pd.read_csv("https://images.5paisa.com/website/scripmaster-csv-format.csv")

        self.data["Expiry"] = pd.to_datetime(self.data["Expiry"], format="%Y-%m-%d %H:%M:%S")
        self.data["Name"] = self.data["Name"].apply(str.upper)
        self.data["Symbol"] = self.data["Name"]

    def __repr__(self):
        return f"scrip master data"

    def __call__(self):
        return self.data

    def save(self, filepath: str) -> None:
        """saves the scrip master data

        Parameters
        ----------
        filepath : str
            filepath with filename with .pkl extention

        Returns
        -------
        _type_
            None
        """
        return self.data.to_pickle(filepath)

    def get_scrip(self, stock: Stock) -> pd.DataFrame:
        """returns the scrips of the stock

        Parameters
        ----------
        stock : Stock
            a stock object

        Returns
        -------
        pd.DataFrame
            Scrip data of a given stock
        """
        try:
            return stock.scrip
        except:
            pass
        d1 = self.data
        f1 = (d1["Exch"] == stock.exchange) & (d1["ExchType"] == stock.exchange_type) & (d1["Symbol"] == stock.symbol)
        f2 = (d1["Series"] == "EQ") | (d1["Series"] == "XX")
        d2 = d1[f1 & f2]
        if d2.empty:
            raise ValueError(f"No Scrip found for {stock.symbol} in scrip_master")
        d2 = d2.set_index("Name")
        ### setting the scrip to stock object
        stock.scrip = d2
        return d2


class Client5paisaCred(TypedDict):
    APP_NAME: str
    APP_SOURCE: str
    USER_ID: str
    PASSWORD: str
    USER_KEY: str
    ENCRYPTION_KEY: str


class Client5paisa(p5.FivePaisaClient):
    def __init__(self, totp: str, mpin: str, client_code: str, cred: Client5paisaCred, scrip_master: ScripMaster = None, **kwargs):
        super().__init__(cred=cred)
        self.get_totp_session(client_code, f"{totp}", mpin)

        print("downloading the scrip-master")

        self.scrip_master = ScripMaster() if scrip_master is None else scrip_master
        return

    def download_historical_data(
        self,
        stock: Stock,
        interval: INTERVAL = INTERVAL.one_day,
        start: Union[str, dtm.datetime] = "2023-01-01",
        end: Union[str, dtm.datetime] = "2023-03-30",
    ) -> pd.DataFrame:
        """Downloads the historical data and saves it to local drive or in Stock.data variable.

        Parameters
        ----------
        stock : Stock
            Stock object
        interval : str, optional
            time interval of data. it should be within [1m,5m,10m,15m,30m,60m,1d], by default "1d"
        start : Union[str, dtm.datetime], optional
            start date of the data. The data for this date will be downloaded, by default "2023-01-01"
        end : Union[str, dtm.datetime], optional
            end date of the data. The data for this date will be downloaded, by default "2023-03-30"

        Returns
        ----------
        pd.DataFrame
            A dataframe containing a historical data.

        """
        # scrip = self.scrip_master.get_scrip(stock)

        # if isinstance(start, dtm.datetime):
        #     start = start.strftime("%Y-%m-%d")
        # if isinstance(end, dtm.datetime):
        #     end = end.strftime("%Y-%m-%d")

        # df = self.historical_data(stock.exchange, stock.exchange_type, scrip.loc[stock.symbol, "Scripcode"], interval.value, start, end)
        # df.columns = ["Datetime", "Open", "High", "Low", "Close", "Volume"]
        # df["Datetime"] = pd.to_datetime(df["Datetime"])
        # df = df.set_index("Datetime")

        # return df

        scrip = self.scrip_master.get_scrip(stock)
        if isinstance(start, str):
            start_dt = dtm.datetime.strptime(start, "%Y-%m-%d")
        else:
            start_dt = start

        if isinstance(end, str):
            end_dt = dtm.datetime.strptime(end, "%Y-%m-%d")
        else:
            end_dt = end

        def _fetch_chunk(s: dtm.datetime, e: dtm.datetime) -> pd.DataFrame:
            df = self.historical_data(stock.exchange, stock.exchange_type, scrip.loc[stock.symbol, "Scripcode"], interval.value, s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"))
            if df is None or df.empty:
                return pd.DataFrame()
            df.columns = ["Datetime", "Open", "High", "Low", "Close", "Volume"]
            df["Datetime"] = pd.to_datetime(df["Datetime"])
            return df.set_index("Datetime")

        dfs = []
        curr_start = start_dt

        while curr_start < end_dt:
            curr_end = min(curr_start + dtm.timedelta(days=90), end_dt)
            chunk = _fetch_chunk(curr_start, curr_end)
            if not chunk.empty:
                dfs.append(chunk)

            curr_start = curr_end

        if not dfs:
            return pd.DataFrame()

        df = pd.concat(dfs).sort_index()
        df = df.loc[~df.index.duplicated(keep="first")]

        return df

    def get_market_depth(self, stockdict: Union[list[Stock], StockDict]) -> pd.DataFrame:
        """Gets the market depth for given list of Stocks

        Parameters
        ----------
        StockDict : list[Stock]|StockDict
            list of Stock class instances or StockDict type object.

        Returns
        -------
        _pd.DataFrame
            Live Market Depth for all the Stocks in list.
        """
        scrips = pd.concat(self.scrip_master.get_scrip(stock) for stock in stockdict)
        a = scrips.rename(columns={"Exch": "Exchange", "ExchType": "ExchangeType"})[["Exchange", "ExchangeType", "Symbol"]].to_dict(orient="records")
        d1 = pd.DataFrame(self.fetch_market_depth_by_symbol(a)["Data"])

        d1.set_index("ScripCode", inplace=True)
        d1["Datetime"] = dtm.datetime.now()
        scrips.set_index("Scripcode", inplace=True)
        d1["Symbol"] = scrips["Symbol"]
        d1.set_index("Symbol", inplace=True)
        d1.rename(columns={"Close": "PrevClose"}, inplace=True)
        d1.rename(columns={"LastTradedPrice": "Close"}, inplace=True)
        return d1

    def update_stock_histdata0_to_ltp(self, stockdict: Union[list[Stock], StockDict]) -> None:
        """Updates the market depth to stock.hist_data0 attribute

        Parameters
        ----------
        StockDict : list[Stock]|StockDict
            list of Stock class instances or StockDict type object.

        Returns
        -------
        None
        """
        d1 = self.get_market_depth(stockdict)
        d1 = d1[["Datetime", "Open", "High", "Low", "Close", "Volume"]]
        d1["Datetime"] = d1["Datetime"].dt.normalize()
        ### Convert datatypes of specific columns
        float_cols = ["Open", "High", "Low", "Close"]
        d1[float_cols] = d1[float_cols].astype(float)
        d1["Volume"] = d1["Volume"].astype(int)

        for s1 in stockdict:
            try:
                d = d1.loc[s1.symbol]
                s1.hist_data0.loc[d.Datetime] = d
            except:
                print(f"Error in {s1.symbol}")
                continue
        return
