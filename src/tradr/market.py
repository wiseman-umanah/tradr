import yfinance as yf
import pandas as pd
from pandas import DataFrame


def get_current_price(symbol):
    pass


def get_ohlcv(symbol, period: str = "1mo", interval: str = "1d") -> DataFrame:
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
    return data


def _format_timestamp(ts) -> str:
    """Convert a pandas timestamp to a display string."""
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    elif not hasattr(ts, "strftime"):
        ts = pd.Timestamp(ts).to_pydatetime()

    tzinfo = getattr(ts, "tzinfo", None)
    if tzinfo is not None:
        ts = ts.replace(tzinfo=None)

    return ts.strftime("%d/%m/%Y %H:%M")


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


def get_trending_symbols() -> list[str]:
    """Extract trending symbols to be used for analysis"""
    try:
        screen = yf.screen("most_actives")
        quotes = screen.get("quotes", [])
        return [q["symbol"] for q in quotes]
    except Exception:
        return []
