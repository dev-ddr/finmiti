"""Module consisting of the Postgres-backed stock data handler."""

import os as _os
import datetime as _dtm
from dataclasses import dataclass, field
from typing import Optional, Union

import pandas as _pd
import psycopg

from .stock import Stock
from ..constants import EXCHANGE, EXCHANGE_TYPE, INTERVAL


def _env_int(key: str) -> Optional[int]:
    val = _os.environ.get(key)
    return int(val) if val else None


@dataclass(frozen=True, slots=True)
class PGConfig:
    """Postgres connection config, defaulting to FINMITI_PG_* env vars.

    Unset fields stay None so psycopg/libpq falls back to its own defaults
    (local peer auth via unix socket for host/user/password). Override any
    field explicitly, e.g. ``PGConfig(host="otherhost")``.
    """

    dbname: str = field(default_factory=lambda: _os.environ.get("FINMITI_PG_DBNAME", "finmiti"))
    host: Optional[str] = field(default_factory=lambda: _os.environ.get("FINMITI_PG_HOST") or None)
    port: Optional[int] = field(default_factory=lambda: _env_int("FINMITI_PG_PORT"))
    user: Optional[str] = field(default_factory=lambda: _os.environ.get("FINMITI_PG_USER") or None)
    password: Optional[str] = field(default_factory=lambda: _os.environ.get("FINMITI_PG_PASSWORD") or None)

    def conn_kwargs(self) -> dict:
        kwargs = {"dbname": self.dbname}
        for key in ("host", "port", "user", "password"):
            val = getattr(self, key)
            if val is not None:
                kwargs[key] = val
        return kwargs

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(**self.conn_kwargs())


def _connect() -> psycopg.Connection:
    return PGConfig().connect()


def _parse_date(value) -> _dtm.datetime:
    """Coerces a 'YYYY-MM-DD' string or datetime to a datetime."""
    if isinstance(value, _dtm.datetime):
        return value
    if isinstance(value, _dtm.date):
        return _dtm.datetime.combine(value, _dtm.time())
    return _dtm.datetime.strptime(value, "%Y-%m-%d")


### interval -> (table, date/timestamp column). Only what's actually stored;
### five_min/fifteen_min are derived on read from minute_bars via date_bin().
_TABLE_MAP = {
    INTERVAL.one_day: ("daily_bars", "trade_date"),
    INTERVAL.one_min: ("minute_bars", "ts"),
}


def _table_and_col(interval: INTERVAL) -> tuple:
    try:
        return _TABLE_MAP[interval]
    except KeyError:
        raise ValueError(
            f"{interval} is not stored directly; only INTERVAL.one_day and INTERVAL.one_min "
            "are persisted. five_min/fifteen_min are derived on read via load_historical_data()."
        )


class StockPG(Stock):
    """Postgres-backed Stock: OHLCV data lives in the `daily_bars`/`minute_bars`
    tables of the finmiti DB, keyed by `stock_id` (upserted into `stocks` by symbol).
    """

    def __init__(
        self,
        symbol: str,
        exchange: EXCHANGE = EXCHANGE.nse,
        exchange_type: EXCHANGE_TYPE = EXCHANGE_TYPE.cash,
    ) -> None:
        super().__init__(symbol, exchange, exchange_type)
        self._stock_id: Optional[int] = None

    @property
    def stock_id(self) -> int:
        """The DB `stock_id`, upserting a row into `stocks` on first access."""
        if self._stock_id is None:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO stocks (symbol, exchange, exchange_type)
                        VALUES (%s, %s::exchange_code, %s::exchange_type_code)
                        ON CONFLICT (symbol) DO UPDATE SET
                            exchange = EXCLUDED.exchange,
                            exchange_type = EXCLUDED.exchange_type
                        RETURNING stock_id
                        """,
                        (self.symbol, self.exchange, self.exchange_type),
                    )
                    self._stock_id = cur.fetchone()[0]
                conn.commit()
        return self._stock_id

    def save_historical_data(self, data: _pd.DataFrame, interval: INTERVAL) -> int:
        """Upserts OHLCV rows into `daily_bars` or `minute_bars`.

        Bulk-loads via COPY into a temp table, then upserts from there with
        ON CONFLICT DO UPDATE (incoming data is authoritative, matching the
        live-poll write pattern of resending overlapping ranges).

        Parameters
        ----------
        data : pd.DataFrame
            Data indexed by Datetime, with Open/High/Low/Close/Volume columns.
        interval : INTERVAL
            Only INTERVAL.one_day and INTERVAL.one_min are stored directly.

        Returns
        -------
        int
            Number of rows written.
        """
        if data is None or len(data) == 0:
            return 0
        table, date_col = _table_and_col(interval)
        is_daily = date_col == "trade_date"
        stock_id = self.stock_id

        rows = [
            (
                stock_id,
                idx.date() if is_daily else idx.to_pydatetime(),
                float(r["Open"]),
                float(r["High"]),
                float(r["Low"]),
                float(r["Close"]),
                int(r["Volume"]),
            )
            for idx, r in data.iterrows()
        ]

        stage = f"_stage_{table}"
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"CREATE TEMP TABLE {stage} (LIKE {table}) ON COMMIT DROP")
                with cur.copy(
                    f"COPY {stage} (stock_id, {date_col}, open, high, low, close, volume) FROM STDIN"
                ) as copy:
                    for row in rows:
                        copy.write_row(row)
                cur.execute(
                    f"""
                    INSERT INTO {table} (stock_id, {date_col}, open, high, low, close, volume)
                    SELECT stock_id, {date_col}, open, high, low, close, volume FROM {stage}
                    ON CONFLICT (stock_id, {date_col}) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                    """
                )
            conn.commit()
        return len(rows)

    def load_historical_data(
        self,
        start: Union[str, _dtm.datetime],
        end: Union[str, _dtm.datetime],
        interval: INTERVAL = INTERVAL.one_day,
        fill_holidays: bool = False,
        remove_weekends: bool = True,
    ) -> _pd.DataFrame:
        """Loads historical data from Postgres for the given range.

        Parameters
        ----------
        start, end : str | datetime
            Inclusive date range to load.
        interval : INTERVAL, Optional
            one_day / one_min are read straight from their tables; five_min / fifteen_min
            are aggregated on the fly from minute_bars via date_bin().
        fill_holidays : bool, Default False
            Only applies to one_day: reindexes to a full business-day range and
            forward-fills, inserting a row for missing holidays.
        remove_weekends : bool, Default True
            Drops Saturday/Sunday rows.

        Returns
        -------
        pd.DataFrame
            Data indexed by Datetime, with Open/High/Low/Close/Volume columns.
        """
        start_dt = _parse_date(start)
        end_dt = _parse_date(end)
        stock_id = self.stock_id

        if interval in (INTERVAL.five_min, INTERVAL.fifteen_min):
            minutes = 5 if interval is INTERVAL.five_min else 15
            query = f"""
                SELECT date_bin(INTERVAL '{minutes} minutes', ts, TIMESTAMP '2000-01-01') AS "Datetime",
                       (array_agg(open ORDER BY ts))[1]::float8 AS "Open",
                       max(high)::float8 AS "High",
                       min(low)::float8 AS "Low",
                       (array_agg(close ORDER BY ts DESC))[1]::float8 AS "Close",
                       sum(volume) AS "Volume"
                FROM minute_bars
                WHERE stock_id = %s AND ts BETWEEN %s AND %s
                GROUP BY 1
                ORDER BY 1
            """
            params = (stock_id, start_dt, end_dt)
        else:
            table, date_col = _table_and_col(interval)
            range_start = start_dt if date_col == "ts" else start_dt.date()
            range_end = end_dt if date_col == "ts" else end_dt.date()
            query = f"""
                SELECT {date_col} AS "Datetime",
                       open::float8 AS "Open", high::float8 AS "High",
                       low::float8 AS "Low", close::float8 AS "Close",
                       volume AS "Volume"
                FROM {table}
                WHERE stock_id = %s AND {date_col} BETWEEN %s AND %s
                ORDER BY {date_col}
            """
            params = (stock_id, range_start, range_end)

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                cols = [d.name for d in cur.description]
                rows = cur.fetchall()

        df = _pd.DataFrame(rows, columns=cols)
        df["Datetime"] = _pd.to_datetime(df["Datetime"])
        df = df.set_index("Datetime")

        if fill_holidays and interval is INTERVAL.one_day and len(df):
            full_range = _pd.date_range(start=df.index.min(), end=df.index.max(), freq="B")
            df = df.reindex(full_range).ffill()
            df.index.name = "Datetime"
        if remove_weekends and len(df):
            df = df[df.index.weekday < 5]
        return df

    def coverage(self, interval: Optional[INTERVAL] = None, include_count: bool = True) -> list:
        """Returns live coverage records (start/end, optionally rows) for this stock, one per interval.

        ``start``/``end`` are MIN/MAX on the ``(stock_id, date)`` primary key — an index
        lookup, cheap regardless of table size. ``count(*)`` is not: Postgres has no
        index-only shortcut for it (MVCC visibility means every matching row still
        has to be checked), so it scans the full per-stock row range. Pass
        ``include_count=False`` to skip it — e.g. a cross-stock coverage listing, or
        ``update_hist_data``'s internal resume-point check, where only ``end`` matters.

        Parameters
        ----------
        interval : INTERVAL, optional
            Restrict to one interval. Defaults to both stored intervals (one_day, one_min).
        include_count : bool
            Whether to also compute ``count(*)`` (``rows``). Default True for
            backward compatibility; ``rows`` is ``None`` when False.
        """
        intervals = [interval] if interval is not None else [INTERVAL.one_day, INTERVAL.one_min]
        stock_id = self.stock_id
        records = []
        with _connect() as conn:
            with conn.cursor() as cur:
                for iv in intervals:
                    table, date_col = _table_and_col(iv)
                    if include_count:
                        cur.execute(
                            f"SELECT min({date_col}), max({date_col}), count(*) FROM {table} WHERE stock_id = %s",
                            (stock_id,),
                        )
                        start, end, rows = cur.fetchone()
                    else:
                        cur.execute(
                            f"SELECT min({date_col}), max({date_col}) FROM {table} WHERE stock_id = %s",
                            (stock_id,),
                        )
                        start, end = cur.fetchone()
                        rows = None
                    records.append(
                        {
                            "symbol": self.symbol,
                            "exchange": self.exchange,
                            "exchange_type": self.exchange_type,
                            "interval": iv.value,
                            "start": start,
                            "end": end,
                            "rows": rows,
                        }
                    )
        return records

    def update_hist_data(
        self,
        client,
        interval: INTERVAL = INTERVAL.one_day,
        end: Union[str, _dtm.datetime, None] = None,
        default_start: str = "2017-01-01",
        overwrite: bool = False,
        start: Union[str, _dtm.datetime, None] = None,
    ) -> Optional[_pd.DataFrame]:
        """Brings stored historical data up to ``end`` by downloading only the missing tail.

        Resumes from this stock's stored coverage end for ``interval`` (or ``default_start``
        when nothing is stored yet), downloads the gap, and upserts it. Safe to call
        repeatedly: the upsert is authoritative-overwrite, so re-running with the same
        ``end`` just re-writes the same rows.

        If ``end`` resolves to **today**, the "nothing new to fetch" short-circuit below is
        skipped even when coverage already reaches today — today's bar can still be
        incomplete/changing, so every call re-fetches and re-upserts it. This makes the
        function safe to poll repeatedly through a live trading session to keep an
        intraday-developing bar current, not just to catch up historical gaps.

        Parameters
        ----------
        client
            Any object exposing ``download_historical_data(stock, interval, start, end)``.
        interval : INTERVAL
            Only INTERVAL.one_day and INTERVAL.one_min can be updated directly.
        end : str | datetime, optional
            Update up to this date (inclusive). Defaults to yesterday, so today's
            still-incomplete bar is never stored during live market hours.
        default_start : str
            Start date used when no data exists yet. Default "2017-01-01".
        overwrite : bool
            Ignores stored coverage and re-downloads/upserts ``[start or default_start, end]``.
        start : str | datetime, optional
            Start date for the download when ``overwrite`` is set, or the first-download
            start (instead of ``default_start``) when no data exists yet.

        Returns
        -------
        pd.DataFrame | None
            The newly downloaded data, or None if there was nothing to download.
        """
        _table_and_col(interval)  # validates interval is one_day/one_min

        if end is None:
            end_dt = _dtm.datetime.combine(_dtm.date.today() - _dtm.timedelta(days=1), _dtm.time())
        else:
            end_dt = _parse_date(end)

        if overwrite:
            resume_dt = _parse_date(start if start is not None else default_start)
        else:
            cov = self.coverage(interval=interval, include_count=False)[0]
            if cov["end"] is not None:
                resume_dt = _parse_date(cov["end"])
            else:
                resume_dt = _parse_date(start if start is not None else default_start)

        end_is_today = end_dt.date() == _dtm.date.today()
        if not overwrite and not end_is_today and resume_dt.date() >= end_dt.date():
            return None

        df = client.download_historical_data(self, interval=interval, start=resume_dt, end=end_dt)
        if df is None or len(df) == 0:
            return df

        self.save_historical_data(df, interval)
        return df

    @staticmethod
    def from_symbol(symbol: str) -> Optional["StockPG"]:
        """Reconstructs a StockPG from the `stocks` table by symbol."""
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT exchange, exchange_type FROM stocks WHERE symbol = %s", (symbol,)
                )
                row = cur.fetchone()
        if row is None:
            return None
        exch, exch_type = row
        try:
            return StockPG(symbol, EXCHANGE(exch), EXCHANGE_TYPE(exch_type))
        except Exception:
            return None
