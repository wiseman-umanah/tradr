from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from pandas import DataFrame
from platformdirs import user_config_dir

from tradr import trading

try:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
except ModuleNotFoundError:
    DataFeed = None  # type: ignore[assignment]
    StockHistoricalDataClient = None  # type: ignore[assignment]
    StockBarsRequest = None  # type: ignore[assignment]
    StockSnapshotRequest = None  # type: ignore[assignment]
    TimeFrame = None  # type: ignore[assignment]
    TimeFrameUnit = None  # type: ignore[assignment]

CONFIG_DIR = Path(user_config_dir(appname="tradr", appauthor="wiseman-umanah", ensure_exists=True))
SYMBOLS_FILE = CONFIG_DIR / "symbols.json"
MARKET_CONFIG_FILE = CONFIG_DIR / "market.json"
CACHE_HOURS = 24

SP500_URL = "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"
NASDAQ_URL = "https://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt"
DEFAULT_DATA_FEED = "iex"


def _alpaca_available() -> bool:
    return all(
        dependency is not None
        for dependency in (
            StockHistoricalDataClient,
            StockBarsRequest,
            StockSnapshotRequest,
            TimeFrame,
            TimeFrameUnit,
        )
    )


def get_data_feed_name() -> str:
    """Return the Alpaca stock data feed name.

    Basic/free Alpaca accounts can use real-time IEX data. SIP requires a paid
    market-data subscription, so default to IEX unless the user opts into SIP.
    """
    env_feed = os.getenv("ALPACA_DATA_FEED")
    if env_feed:
        return _normalize_data_feed(env_feed)
    try:
        with MARKET_CONFIG_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
            return _normalize_data_feed(data.get("feed", DEFAULT_DATA_FEED))
    except Exception:
        return DEFAULT_DATA_FEED


def _normalize_data_feed(feed: str) -> str:
    normalized = feed.strip().lower().replace("-", "_")
    if normalized not in {"iex", "sip", "delayed_sip"}:
        raise ValueError("Feed must be one of: iex, sip, delayed_sip.")
    return normalized


def save_data_feed(feed: str) -> str:
    normalized = _normalize_data_feed(feed)
    os.environ["ALPACA_DATA_FEED"] = normalized
    with MARKET_CONFIG_FILE.open("w", encoding="utf-8") as file:
        json.dump({"feed": normalized, "updated": datetime.now().isoformat()}, file)
    return normalized


def _data_feed() -> Any:
    feed_name = get_data_feed_name()
    if DataFeed is None:
        return feed_name
    if feed_name == "sip":
        return DataFeed.SIP
    if feed_name == "delayed_sip":
        return getattr(DataFeed, "DELAYED_SIP", "delayed_sip")
    return DataFeed.IEX


def _get_data_client() -> Any | None:
    if not _alpaca_available():
        return None
    try:
        config = trading.get_trading_config()
    except Exception:
        config = {}
    try:
        if config.get("api_key") and config.get("secret_key"):
            return StockHistoricalDataClient(
                api_key=config["api_key"],
                secret_key=config["secret_key"],
            )
        return StockHistoricalDataClient()
    except Exception:
        return None


def _timeframe_for_interval(interval: str) -> Any:
    mapping = {
        "1m": TimeFrame(1, TimeFrameUnit.Minute),
        "2m": TimeFrame(2, TimeFrameUnit.Minute),
        "5m": TimeFrame(5, TimeFrameUnit.Minute),
        "15m": TimeFrame(15, TimeFrameUnit.Minute),
        "30m": TimeFrame(30, TimeFrameUnit.Minute),
        "60m": TimeFrame(1, TimeFrameUnit.Hour),
        "1h": TimeFrame(1, TimeFrameUnit.Hour),
        "90m": TimeFrame(90, TimeFrameUnit.Minute),
        "1d": TimeFrame.Day,
        "5d": TimeFrame(5, TimeFrameUnit.Day),
        "1wk": TimeFrame.Week,
        "1mo": TimeFrame.Month,
        "3mo": TimeFrame(3, TimeFrameUnit.Month),
    }
    if interval not in mapping:
        raise ValueError(f"Unsupported interval: {interval}")
    return mapping[interval]


def _start_for_period(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    today = now.date()
    if period == "1d":
        return now - timedelta(days=1)
    if period == "5d":
        return now - timedelta(days=5)
    if period == "1mo":
        return now - timedelta(days=30)
    if period == "3mo":
        return now - timedelta(days=90)
    if period == "6mo":
        return now - timedelta(days=180)
    if period == "1y":
        return now - timedelta(days=365)
    if period == "2y":
        return now - timedelta(days=365 * 2)
    if period == "5y":
        return now - timedelta(days=365 * 5)
    if period == "10y":
        return now - timedelta(days=365 * 10)
    if period == "ytd":
        return datetime(today.year, 1, 1, tzinfo=timezone.utc)
    if period == "max":
        return now - timedelta(days=365 * 20)
    raise ValueError(f"Unsupported period: {period}")


def _bars_to_dataframe(bars: list[Any]) -> DataFrame:
    rows: list[dict[str, Any]] = []
    for bar in bars:
        rows.append(
            {
                "Date": getattr(bar, "timestamp", None),
                "Open": getattr(bar, "open", None),
                "High": getattr(bar, "high", None),
                "Low": getattr(bar, "low", None),
                "Close": getattr(bar, "close", None),
                "Volume": getattr(bar, "volume", None),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["Date"] = pd.to_datetime(frame["Date"], utc=True)
    frame = frame.set_index("Date")
    return frame.dropna()


def _get_alpaca_bars(
    symbol: str,
    period: str,
    interval: str,
    max_candles: int | None = None,
) -> DataFrame:
    client = _get_data_client()
    if client is None:
        raise RuntimeError("Alpaca market data client is unavailable.")
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=_timeframe_for_interval(interval),
        start=_start_for_period(period),
        end=datetime.now(timezone.utc),
        limit=max_candles or 1000,
        feed=_data_feed(),
    )
    response = client.get_stock_bars(request)
    bars_by_symbol = getattr(response, "data", response)
    bars = bars_by_symbol[symbol] if isinstance(bars_by_symbol, dict) else []
    data = _bars_to_dataframe(list(bars))
    if not data.empty and max_candles is not None:
        data = data.tail(max_candles)
    return data


def get_current_price(symbol: str) -> float | None:
    snapshot = get_snapshot(symbol)
    if snapshot is not None:
        return snapshot.get("price")
    try:
        fast = yf.Ticker(symbol).fast_info
        return float(fast.last_price) if fast.last_price is not None else None
    except Exception:
        return None


def get_ohlcv(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d",
    max_candles: int | None = None,
) -> DataFrame:
    """Download OHLCV data, preferring Alpaca and falling back to Yahoo."""
    try:
        data = _get_alpaca_bars(symbol, period, interval, max_candles=max_candles)
        if not data.empty:
            return data
    except Exception:
        pass

    data = yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data = data.dropna()
    if not data.empty and max_candles is not None:
        data = data.tail(max_candles)
    return data


def _extract_snapshot_fields(snapshot: Any) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    latest_trade = getattr(snapshot, "latest_trade", None)
    prev_daily_bar = getattr(snapshot, "previous_daily_bar", None)
    daily_bar = getattr(snapshot, "daily_bar", None)

    price = getattr(latest_trade, "price", None)
    previous_close = getattr(prev_daily_bar, "close", None)
    if previous_close is None:
        previous_close = getattr(daily_bar, "open", None)
    if price is None or previous_close in (None, 0):
        return None

    change = float(price) - float(previous_close)
    change_pct = (change / float(previous_close)) * 100
    return {
        "price": float(price),
        "previous_close": float(previous_close),
        "change": change,
        "change_pct": change_pct,
    }


def get_snapshot(symbol: str) -> dict[str, Any] | None:
    snapshots = get_snapshots([symbol])
    return snapshots.get(symbol)


def get_snapshots(symbols: list[str]) -> dict[str, dict[str, Any]]:
    clean_symbols = [symbol.upper().strip() for symbol in symbols if symbol and "." not in symbol]
    if not clean_symbols:
        return {}

    client = _get_data_client()
    if client is not None:
        try:
            request = StockSnapshotRequest(
                symbol_or_symbols=clean_symbols,
                feed=_data_feed(),
            )
            response = client.get_stock_snapshot(request)
            snapshot_map = getattr(response, "data", response)
            results: dict[str, dict[str, Any]] = {}
            for symbol in clean_symbols:
                parsed = _extract_snapshot_fields(snapshot_map.get(symbol))
                if parsed is not None:
                    results[symbol] = parsed
            if results:
                return results
        except Exception:
            pass

    results = {}
    for symbol in clean_symbols:
        try:
            info = yf.Ticker(symbol).fast_info
            price = info.last_price
            prev_close = info.previous_close
            if price is None or prev_close in (None, 0):
                continue
            change = float(price) - float(prev_close)
            results[symbol] = {
                "price": float(price),
                "previous_close": float(prev_close),
                "change": change,
                "change_pct": (change / float(prev_close)) * 100,
            }
        except Exception:
            continue
    return results


def _format_timestamp(ts: Any) -> str:
    """Convert a pandas timestamp to a display string."""
    local_tz = datetime.now().astimezone().tzinfo
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is not None:
            ts = ts.tz_convert(local_tz)
        ts = ts.to_pydatetime()
    elif not hasattr(ts, "strftime"):
        ts = pd.Timestamp(ts).to_pydatetime()

    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.astimezone(local_tz)

    return ts.replace(tzinfo=None).strftime("%d/%m/%Y %H:%M")


def extract_ohlcv(data: DataFrame) -> dict[str, list]:
    """Convert OHLCV data to lists for Plotext."""
    return {
        "dates": [_format_timestamp(d) for d in data.index],
        "Open": data["Open"].tolist(),
        "High": data["High"].tolist(),
        "Low": data["Low"].tolist(),
        "Close": data["Close"].tolist(),
        "volume": data["Volume"].tolist(),
    }


def is_cache_fresh() -> bool:
    """Check if symbols cache is less than 24 hours old."""
    if not SYMBOLS_FILE.exists():
        return False
    modified = datetime.fromtimestamp(SYMBOLS_FILE.stat().st_mtime)
    return datetime.now() - modified < timedelta(hours=CACHE_HOURS)


def _fetch_sp500() -> list[str]:
    """Fetch S&P 500 symbols from DataHub CSV."""
    try:
        response = requests.get(SP500_URL, timeout=10)
        response.raise_for_status()
        reader = csv.DictReader(response.text.splitlines())
        return [row["Symbol"].strip() for row in reader if row.get("Symbol")]
    except Exception:
        return []


def _fetch_nasdaq() -> list[str]:
    """Fetch NASDAQ listed symbols."""
    try:
        response = requests.get(NASDAQ_URL, timeout=10)
        response.raise_for_status()
        symbols = []
        for line in response.text.splitlines()[1:]:
            parts = line.split("|")
            if parts:
                symbol = parts[0].strip()
                if symbol and "$" not in symbol and len(symbol) <= 5:
                    symbols.append(symbol)
        return symbols
    except Exception:
        return []


def download_symbol_list() -> list[str]:
    """Download and cache a stock symbol list from public sources."""
    sp500 = _fetch_sp500()
    nasdaq = _fetch_nasdaq()

    seen = set()
    symbols = []
    for symbol in sp500 + nasdaq:
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)

    if symbols:
        with SYMBOLS_FILE.open("w", encoding="utf-8") as file:
            json.dump({"symbols": symbols, "updated": datetime.now().isoformat()}, file)

    return symbols


def load_symbol_list() -> list[str]:
    """Load symbols from cache if fresh, otherwise download them."""
    if is_cache_fresh():
        try:
            with SYMBOLS_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return data.get("symbols", [])
        except Exception:
            pass
    return download_symbol_list()
