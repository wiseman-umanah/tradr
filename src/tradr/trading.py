from __future__ import annotations

import os
import pickle
import re
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any

from platformdirs import user_config_dir

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest


CONFIG_DIR = Path(user_config_dir(appname="tradr", appauthor="wiseman-umanah", ensure_exists=True))
CONFIG_FILE = CONFIG_DIR / "trading.pkl"
_client: Any | None = None
_order_ref_lock = Lock()
_recent_order_refs: deque[dict[str, str]] = deque(maxlen=10)
_order_id_to_ref: dict[str, str] = {}
_next_order_ref = 1


def _error_text(exc: Exception) -> str:
    details: list[str] = []
    for attr in ("message", "detail", "response", "error"):
        value = getattr(exc, attr, None)
        if value:
            details.append(str(value))
    details.append(str(exc))
    return " ".join(part for part in details if part).strip()


def _extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    text = _error_text(exc)
    match = re.search(r"\bstatus(?:_code)?['\"=: ]+(\d{3})\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{3})\b", text)
    if match:
        return int(match.group(1))
    return None


def _is_not_found_error(exc: Exception) -> bool:
    status_code = _extract_status_code(exc)
    if status_code == 404:
        return True
    text = _error_text(exc).lower()
    return any(
        phrase in text
        for phrase in (
            "position does not exist",
            "position not found",
            "order not found",
            "does not exist",
            "not found",
            "no position",
        )
    )


def _next_ref() -> str:
    global _next_order_ref
    ref = f"#{_next_order_ref}"
    _next_order_ref += 1
    return ref


def remember_order(order: dict[str, Any]) -> str | None:
    order_id = str(order.get("id", "")).strip()
    symbol = str(order.get("symbol", "")).strip()
    if not order_id:
        return None
    with _order_ref_lock:
        existing = _order_id_to_ref.get(order_id)
        if existing:
            return existing
        ref = _next_ref()
        _order_id_to_ref[order_id] = ref
        _recent_order_refs.appendleft({"ref": ref, "order_id": order_id, "symbol": symbol})
        valid_ids = {entry["order_id"] for entry in _recent_order_refs}
        for known_id in list(_order_id_to_ref):
            if known_id not in valid_ids:
                _order_id_to_ref.pop(known_id, None)
        return ref


def recent_order_refs() -> list[dict[str, str]]:
    with _order_ref_lock:
        return list(_recent_order_refs)


def resolve_order_reference(reference: str) -> str:
    normalized = reference.strip()
    if not normalized:
        raise ValueError("Order reference is required.")
    if normalized.startswith("#"):
        with _order_ref_lock:
            for entry in _recent_order_refs:
                if entry["ref"] == normalized:
                    return entry["order_id"]
        raise ValueError(f"Order reference {normalized} was not found.")
    if normalized.isdigit():
        return resolve_order_reference(f"#{normalized}")
    return normalized


def get_last_order_reference() -> dict[str, str] | None:
    with _order_ref_lock:
        return dict(_recent_order_refs[0]) if _recent_order_refs else None


def _config_exists() -> bool:
    return CONFIG_FILE.exists()



def _normalize_trading_config(config: dict[str, Any]) -> dict[str, Any]:
    api_key = str(config.get("api_key", "")).strip()
    secret_key = str(config.get("secret_key", "")).strip()
    paper = bool(config.get("paper", True))

    if not api_key:
        raise ValueError("Trading API key cannot be empty.")
    if not secret_key:
        raise ValueError("Trading secret key cannot be empty.")

    return {
        "api_key": api_key,
        "secret_key": secret_key,
        "paper": paper,
    }


def _serialize_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: _serialize_model(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_model(item) for item in value]
    return value


def _build_client(config: dict[str, Any]) -> Any:
    normalized = _normalize_trading_config(config)
    return TradingClient(  # type: ignore[misc]
        api_key=normalized["api_key"],
        secret_key=normalized["secret_key"],
        paper=normalized["paper"],
    )


def test_trading_config(config: dict) -> tuple[bool, str]:
    try:
        client = _build_client(config)
        client.get_account()
    except Exception as exc:
        return False, str(exc)
    return True, "Trading credentials are valid."


def _load_cached_trading_config() -> dict | None:
    if not _config_exists():
        return None
    try:
        with CONFIG_FILE.open("rb") as file:
            return pickle.load(file)
    except Exception:
        return None


def save_trading_config(config: dict) -> None:
    normalized = _normalize_trading_config(config)
    valid, message = test_trading_config(normalized)
    if not valid:
        raise ValueError(message)
    with CONFIG_FILE.open("wb") as file:
        pickle.dump(normalized, file, protocol=pickle.HIGHEST_PROTOCOL)


def get_trading_config() -> dict:
    env_api_key = os.getenv("ALPACA_API_KEY")
    env_secret_key = os.getenv("ALPACA_SECRET_KEY")
    env_paper = os.getenv("ALPACA_PAPER")
    if env_api_key and env_secret_key:
        return _normalize_trading_config(
            {
                "api_key": env_api_key,
                "secret_key": env_secret_key,
                "paper": str(env_paper).lower() != "false" if env_paper is not None else True,
            }
        )
    cached = _load_cached_trading_config()
    return _normalize_trading_config(cached) if cached else {}


def init_trading_client(config: dict) -> None:
    global _client
    _client = _build_client(config or get_trading_config())


def get_trading_client() -> object:
    global _client
    if _client is None:
        config = get_trading_config()
        if not config:
            raise FileNotFoundError(
                "No trading credentials found. Set ALPACA_API_KEY/ALPACA_SECRET_KEY "
                "or run set-paper <ALPACA_API_KEY> <ALPACA_SECRET_KEY>."
            )
        init_trading_client(config)
    return _client


def place_order(order: dict) -> dict:
    symbol = str(order.get("symbol", "")).upper().strip()
    side = str(order.get("side", "")).lower().strip()
    qty = order.get("qty")
    time_in_force = str(order.get("time_in_force", "day")).lower().strip()

    if not symbol:
        raise ValueError("Order symbol is required.")
    if side not in {"buy", "sell"}:
        raise ValueError("Order side must be 'buy' or 'sell'.")
    try:
        qty = float(qty)
    except (TypeError, ValueError) as exc:
        raise ValueError("Order quantity must be numeric.") from exc
    if qty <= 0:
        raise ValueError("Order quantity must be greater than zero.")
    if time_in_force != "day":
        raise ValueError("Only day market orders are currently supported.")

    client = get_trading_client()
    order_request = MarketOrderRequest(  # type: ignore[misc]
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    submitted = client.submit_order(order_data=order_request)
    return _serialize_model(submitted)


def get_positions() -> list[dict]:
    client = get_trading_client()
    positions = client.get_all_positions()
    return [_serialize_model(position) for position in positions]


def get_account() -> dict:
    client = get_trading_client()
    account = client.get_account()
    return _serialize_model(account)


def get_orders(limit: int = 20) -> list[dict]:
    client = get_trading_client()
    orders = client.get_orders()
    serialized = [_serialize_model(order) for order in orders]
    for order in serialized:
        ref = remember_order(order)
        if ref:
            order["ref"] = ref
    return serialized[:limit] if limit > 0 else serialized


def close_position(symbol: str) -> dict:
    normalized = symbol.upper().strip()
    if not normalized:
        raise ValueError("Position symbol is required.")
    client = get_trading_client()
    try:
        result = client.close_position(normalized)
    except Exception as exc:
        if _is_not_found_error(exc):
            raise ValueError(f"The position for {normalized} does not exist.") from exc
        raise
    return _serialize_model(result)


def cancel_order(order_id: str) -> None:
    normalized = resolve_order_reference(order_id)
    client = get_trading_client()
    try:
        client.cancel_order_by_id(normalized)
    except Exception as exc:
        if _is_not_found_error(exc):
            raise ValueError("The order does not exist.") from exc
        raise
