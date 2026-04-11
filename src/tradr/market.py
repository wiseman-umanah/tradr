import yfinance as yf
import pandas as pd
from pandas import DataFrame


def get_current_price(symbol):
    pass


def get_ohlcv(symbol, period="1mo") -> DataFrame:
    """Download the data of a stock"""
    data = yf.download(symbol, period=period, auto_adjust=True)
    data.columns = data.columns.get_level_values(0)
    return data

def extract_ohlcv(data: DataFrame) -> dict[str, list]:
    """Convert an OHLCV to list for handling by Plotext"""
    return {
        "dates": [d.strftime("%d/%m/%Y") for d in data.index],
        "Open": data["Open"].tolist(),
        "High": data["High"].tolist(),
        "Low": data["Low"].tolist(),
        "Close": data["Close"].tolist(),
        "volume": data["Volume"].tolist()
    }


def get_trending_symbols() -> list[str]:
    """Extract trending symbols to be used for analysis"""
    try:
        screen = yf.screen("most_actives")
        quotes = screen.get("quotes", [])
        return [q["symbol"] for q in quotes]
    except Exception:
        return []


