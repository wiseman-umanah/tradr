from datetime import datetime
from datetime import datetime
import yfinance as yf
import pandas as pd
from pandas import DataFrame
import requests
import csv
import json
import os
from datetime import datetime, timedelta
from platformdirs import user_config_dir

CONFIG_DIR = user_config_dir(appname='tradr', appauthor='wiseman-umanah', ensure_exists=True)
SYMBOLS_FILE = os.path.join(CONFIG_DIR, 'symbols.json')
CACHE_HOURS = 24

SP500_URL = "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"
NASDAQ_URL = "https://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt"

def get_current_price(symbol):
    pass


def get_ohlcv(
    symbol,
    period: str = "1mo",
    interval: str = "1d",
    max_candles: int | None = None,
) -> DataFrame:
    """Download the OHLCV data for a stock."""
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


def _format_timestamp(ts) -> str:
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
    """Convert an OHLCV to list for handling by Plotext."""
    return {
        "dates": [_format_timestamp(d) for d in data.index],
        "Open": data["Open"].tolist(),
        "High": data["High"].tolist(),
        "Low": data["Low"].tolist(),
        "Close": data["Close"].tolist(),
        "volume": data["Volume"].tolist(),
    }


SCREENERS = [
    "most_actives",
    "day_gainers",
    "day_losers",
    "trending_tickers",
    "undervalued_large_caps",
    "undervalued_growth_stocks",
]



def is_cache_fresh() -> bool:
    """Check if symbols cache is less than 24 hours old"""
    if not os.path.exists(SYMBOLS_FILE):
        return False
    modified = datetime.fromtimestamp(os.path.getmtime(SYMBOLS_FILE))
    return datetime.now() - modified < timedelta(hours=CACHE_HOURS)

def _fetch_sp500() -> list[str]:
    """Fetch S&P 500 symbols from DataHub CSV"""
    try:
        response = requests.get(SP500_URL, timeout=10)
        response.raise_for_status()
        reader = csv.DictReader(response.text.splitlines())
        return [row["Symbol"].strip() for row in reader if row.get("Symbol")]
    except Exception:
        return []

def _fetch_nasdaq() -> list[str]:
    """Fetch NASDAQ listed symbols"""
    try:
        response = requests.get(NASDAQ_URL, timeout=10)
        response.raise_for_status()
        symbols = []
        for line in response.text.splitlines()[1:]:  # skip header
            parts = line.split("|")
            if len(parts) > 0:
                symbol = parts[0].strip()
                # filter out test symbols and warrants
                if symbol and "$" not in symbol and len(symbol) <= 5:
                    symbols.append(symbol)
        return symbols
    except Exception:
        return []

def download_symbol_list() -> list[str]:
    """Download and cache full symbol list from multiple sources"""
    sp500 = _fetch_sp500()
    nasdaq = _fetch_nasdaq()

    # merge and deduplicate preserving sp500 first
    seen = set()
    symbols = []
    for symbol in sp500 + nasdaq:
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)

    if symbols:
        with open(SYMBOLS_FILE, "w") as f:
            json.dump({
                "symbols": symbols,
                "updated": datetime.now().isoformat()
            }, f)

    return symbols

def load_symbol_list() -> list[str]:
    """
    Load symbols from cache if fresh,
    otherwise download fresh list
    """
    if is_cache_fresh():
        try:
            with open(SYMBOLS_FILE, "r") as f:
                data = json.load(f)
                return data.get("symbols", [])
        except Exception:
            pass
    return download_symbol_list()
