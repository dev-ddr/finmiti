"""Module consisting of base class of stock"""

import os as _os
import json as _json
import tempfile as _tempfile
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


### ------------------------------------------------------------------
### manifest helpers (per-stock coverage + freshness sidecar)
### ------------------------------------------------------------------

MANIFEST_FILENAME = "_manifest.json"


def _to_iso(value) -> Optional[str]:
    """Converts a datetime-like value to an ISO string (None passes through)."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _read_manifest_file(data_foldpath) -> dict:
    """Reads a stock's manifest. Returns an empty dict if missing or corrupt."""
    path = Path(data_foldpath) / MANIFEST_FILENAME
    try:
        with open(path, "r") as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return {}


def _write_manifest_file(data_foldpath, manifest: dict) -> None:
    """Writes a manifest atomically (temp file + os.replace) so readers never see a partial file."""
    data_foldpath = Path(data_foldpath)
    data_foldpath.mkdir(parents=True, exist_ok=True)
    path = data_foldpath / MANIFEST_FILENAME
    fd, tmp = _tempfile.mkstemp(dir=str(data_foldpath), suffix=".json.tmp")
    try:
        with _os.fdopen(fd, "w") as f:
            _json.dump(manifest, f, indent=2, default=str)
        _os.replace(tmp, path)
    except BaseException:
        try:
            _os.remove(tmp)
        except OSError:
            pass
        raise
    return


def _ensure_manifest_skeleton(manifest: dict, stock: "Stock") -> dict:
    """Fills in the top-level manifest fields in place."""
    manifest.setdefault("symbol", stock.symbol)
    manifest.setdefault("exchange", stock.exchange)
    manifest.setdefault("exchange_type", stock.exchange_type)
    manifest.setdefault("manifest_version", 1)
    manifest.setdefault("intervals", {})
    return manifest


def _intervals_on_disk(data_foldpath) -> list:
    """Returns the interval values (e.g. '1d') for which parquet files exist on disk."""
    intervals = set()
    for f in Path(data_foldpath).glob("*.parquet"):
        parts = f.stem.split("_")
        if len(parts) >= 2:
            intervals.add(parts[-1])
    return sorted(intervals)


def _scan_coverage(data_foldpath, interval_value: str) -> Optional[dict]:
    """Computes start/end/rows for an interval directly from its parquet files (DuckDB)."""
    data_foldpath = Path(data_foldpath)
    if not list(data_foldpath.glob(f"*_{interval_value}.parquet")):
        return None
    query = f"""
    SELECT min(Datetime) AS start_dt, max(Datetime) AS end_dt, count(*) AS n
    FROM read_parquet('{data_foldpath}/*_{interval_value}.parquet')
    """
    with duckdb.connect() as con:
        start_dt, end_dt, n = con.execute(query).fetchone()
    if not n or start_dt is None:
        return None
    return {"start": _to_iso(start_dt), "end": _to_iso(end_dt), "rows": int(n)}


def _last_weekday(d: _dtm.date) -> _dtm.date:
    """Returns the most recent weekday on or before ``d``."""
    while d.weekday() >= 5:
        d -= _dtm.timedelta(days=1)
    return d


def _is_stale(last_checked_iso: Optional[str], today_ref: _dtm.date) -> bool:
    """Stale = not checked since the most recent trading weekday (uses last_checked, not data age)."""
    if not last_checked_iso:
        return True
    try:
        lc = _dtm.datetime.fromisoformat(last_checked_iso).date()
    except (ValueError, TypeError):
        return True
    return lc < today_ref


def _parse_date(value) -> _dtm.datetime:
    """Coerces a 'YYYY-MM-DD' string or datetime to a datetime."""
    if isinstance(value, _dtm.datetime):
        return value
    return _dtm.datetime.strptime(value, "%Y-%m-%d")


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
        Path(data_foldpath).mkdir(parents=True, exist_ok=True)

        ### writing the data (copy first - never mutate the caller's DataFrame)
        data = data.copy()
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
        Path(data_foldpath).mkdir(parents=True, exist_ok=True)

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

    # ------------------------------------------------------------------
    # manifest / coverage / incremental update
    # ------------------------------------------------------------------

    def read_manifest(self, local_data_foldpath: str) -> dict:
        """Returns this stock's manifest dict (empty dict if none exists).

        Parameters
        ----------
        local_data_foldpath : str
            Parent data folder (same value passed to save/load).
        """
        data_foldpath = Path(local_data_foldpath) / self.foldname
        return _read_manifest_file(data_foldpath)

    def refresh_manifest(self, local_data_foldpath: str, interval: Optional[INTERVAL] = None) -> dict:
        """Rebuilds coverage (start/end/rows) in the manifest from the parquet files on disk.

        ``last_downloaded`` / ``last_checked`` are preserved from the existing manifest
        when present, otherwise initialised to now. This makes the manifest a cache that
        self-heals if it is deleted or goes out of sync with the data.

        Parameters
        ----------
        local_data_foldpath : str
            Parent data folder.
        interval : INTERVAL, optional
            Refresh only this interval. If None, every interval found on disk is refreshed.

        Returns
        -------
        dict
            The updated manifest.
        """
        data_foldpath = Path(local_data_foldpath) / self.foldname
        manifest = _read_manifest_file(data_foldpath)
        _ensure_manifest_skeleton(manifest, self)

        now_iso = _dtm.datetime.now().isoformat(timespec="seconds")
        iv_values = [interval.value] if interval is not None else _intervals_on_disk(data_foldpath)

        for iv in iv_values:
            cov = _scan_coverage(data_foldpath, iv)
            if cov is None:
                manifest["intervals"].pop(iv, None)
                continue
            prev = manifest["intervals"].get(iv, {})
            manifest["intervals"][iv] = {
                "start": cov["start"],
                "end": cov["end"],
                "rows": cov["rows"],
                "last_downloaded": prev.get("last_downloaded", now_iso),
                "last_checked": prev.get("last_checked", now_iso),
            }

        _write_manifest_file(data_foldpath, manifest)
        return manifest

    def coverage(self, local_data_foldpath: str, interval: Optional[INTERVAL] = None) -> list:
        """Returns coverage records for this stock - one dict per interval.

        Reads the manifest (rebuilding it from disk if it is missing but data exists).
        Each record holds symbol/exchange/exchange_type/interval/start/end/rows/
        last_downloaded/last_checked/is_stale.

        Parameters
        ----------
        local_data_foldpath : str
            Parent data folder.
        interval : INTERVAL, optional
            Restrict to a single interval.
        """
        data_foldpath = Path(local_data_foldpath) / self.foldname
        manifest = _read_manifest_file(data_foldpath)
        intervals = manifest.get("intervals")
        if not intervals and _intervals_on_disk(data_foldpath):
            manifest = self.refresh_manifest(local_data_foldpath, interval=interval)
            intervals = manifest.get("intervals", {})
        intervals = intervals or {}

        today_ref = _last_weekday(_dtm.date.today())
        records = []
        for iv, info in intervals.items():
            if interval is not None and iv != interval.value:
                continue
            records.append({
                "symbol": self.symbol,
                "exchange": self.exchange,
                "exchange_type": self.exchange_type,
                "interval": iv,
                "start": info.get("start"),
                "end": info.get("end"),
                "rows": info.get("rows"),
                "last_downloaded": info.get("last_downloaded"),
                "last_checked": info.get("last_checked"),
                "is_stale": _is_stale(info.get("last_checked"), today_ref),
            })
        return records

    def update_hist_data(
        self,
        client,
        local_data_foldpath: str,
        interval: INTERVAL = INTERVAL.one_day,
        end: Union[str, _dtm.datetime, None] = None,
        default_start: str = "2017-01-01",
        overwrite: bool = False,
        start: Union[str, _dtm.datetime, None] = None,
    ) -> Optional[_pd.DataFrame]:
        """Brings stored historical data up to ``end`` by downloading only the missing tail.

        Resumes from the manifest's recorded ``end`` for this interval (or ``default_start``
        when nothing is stored yet), downloads the gap, appends it, and updates the manifest
        (coverage plus ``last_downloaded`` / ``last_checked``). Safe to call repeatedly:
        re-running with the same ``end`` downloads nothing new and only bumps ``last_checked``.

        Parameters
        ----------
        client
            Any object exposing ``download_historical_data(stock, interval, start, end)``
            (e.g. ``finmiti.clients.client_5paisa.Client5paisa``). Passed in rather than
            imported so ``Stock`` stays broker-agnostic and import-cycle free.
        local_data_foldpath : str
            Parent data folder (same value passed to save/load).
        interval : INTERVAL
            Data interval. Defaults to one day.
        end : str | datetime, optional
            Update up to this date (inclusive). Defaults to **yesterday** (today - 1 day),
            so today's still-incomplete bar is never stored during live market hours.
            Pass an explicit date to override.
        default_start : str
            Start date used when no data exists yet. Default "2017-01-01".
        overwrite : bool
            Fresh download. Ignores the stored coverage, **wipes this interval's existing
            files** for the stock, and re-downloads ``[start or default_start, end]``.
        start : str | datetime, optional
            Start date for the download. Used as the fresh-download start when ``overwrite``
            is set, or as the first-download start (instead of ``default_start``) when no
            data exists yet. Ignored for a normal incremental resume.

        Returns
        -------
        pd.DataFrame | None
            The newly downloaded data, or None if there was nothing to download.
        """
        data_foldpath = Path(local_data_foldpath) / self.foldname
        data_foldpath.mkdir(parents=True, exist_ok=True)

        now_iso = _dtm.datetime.now().isoformat(timespec="seconds")
        if end is None:
            ### default to yesterday: today's bar is incomplete during live market hours,
            ### so storing it would be a wrong representation of the day.
            end_dt = _dtm.datetime.combine(_dtm.date.today() - _dtm.timedelta(days=1), _dtm.time())
        else:
            end_dt = _parse_date(end)

        manifest = _read_manifest_file(data_foldpath)
        iv = interval.value
        # self-heal: rebuild from parquet if data exists but the manifest is missing this interval
        if not manifest.get("intervals", {}).get(iv) and list(data_foldpath.glob(f"*_{iv}.parquet")):
            manifest = self.refresh_manifest(local_data_foldpath, interval=interval)

        iv_info = manifest.get("intervals", {}).get(iv, {})
        prev_end = iv_info.get("end")
        prev_rows = iv_info.get("rows")

        ### decide where to resume the download from
        if overwrite:
            resume_dt = _parse_date(start if start is not None else default_start)
        elif iv_info.get("end"):
            resume_dt = _dtm.datetime.fromisoformat(iv_info["end"])
        else:
            resume_dt = _parse_date(start if start is not None else default_start)

        ### already up to date - just record that we checked (overwrite always forces a download)
        if not overwrite and resume_dt.date() >= end_dt.date():
            self._touch_manifest(data_foldpath, iv, now_iso)
            return None

        df = client.download_historical_data(self, interval=interval, start=resume_dt, end=end_dt)
        if df is None or len(df) == 0:
            self._touch_manifest(data_foldpath, iv, now_iso)
            return df

        ### fresh download: only clear old files AFTER a successful, non-empty download
        if overwrite:
            for f in data_foldpath.glob(f"*_{iv}.parquet"):
                f.unlink()
        self.save_historical_data(df, interval, local_data_foldpath, overwrite=overwrite)

        ### recompute coverage from disk (authoritative), then stamp freshness
        new_manifest = self.refresh_manifest(local_data_foldpath, interval=interval)
        new_info = new_manifest["intervals"][iv]
        data_changed = overwrite or (new_info.get("end") != prev_end) or (new_info.get("rows") != prev_rows)
        if data_changed:
            new_info["last_downloaded"] = now_iso
        new_info["last_checked"] = now_iso
        _write_manifest_file(data_foldpath, new_manifest)
        return df

    def _touch_manifest(self, data_foldpath, interval_value: str, now_iso: str) -> None:
        """Bumps ``last_checked`` for an interval without changing coverage."""
        manifest = _read_manifest_file(data_foldpath)
        _ensure_manifest_skeleton(manifest, self)
        info = manifest["intervals"].setdefault(interval_value, {})
        info["last_checked"] = now_iso
        info.setdefault("last_downloaded", None)
        _write_manifest_file(data_foldpath, manifest)
        return

    @staticmethod
    def from_folder(folder) -> Optional["Stock"]:
        """Reconstructs a Stock from a stored data folder (via its manifest, else the folder name)."""
        folder = Path(folder)
        manifest = _read_manifest_file(folder)
        symbol = manifest.get("symbol")
        exch = manifest.get("exchange")
        exch_type = manifest.get("exchange_type")
        if not (symbol and exch and exch_type):
            parts = folder.name.split("_")
            if len(parts) < 3:
                return None
            exch, exch_type, symbol = parts[0], parts[1], "_".join(parts[2:])
        try:
            return Stock(symbol, EXCHANGE(exch), EXCHANGE_TYPE(exch_type))
        except Exception:
            return None

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


