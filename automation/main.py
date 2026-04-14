import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import ccxt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

load_dotenv()

APP_NAME = "amb-webhook-bot"
STATE_DIR = Path(__file__).parent / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = STATE_DIR / "events.db"

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "bybit")
SYMBOL = os.getenv("SYMBOL", "BTC/USDT:USDT")
ORDER_NOTIONAL_USDT = float(os.getenv("ORDER_NOTIONAL_USDT", "100"))
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "true").lower() == "true"


def _init_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def _init_db() -> None:
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                action TEXT NOT NULL,
                raw_payload TEXT NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _record_event_if_new(event_id: str, action: str, raw_payload: str) -> bool:
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO events(event_id, created_at, action, raw_payload) VALUES (?, ?, ?, ?)",
            (event_id, int(time.time()), action, raw_payload),
        )
        con.commit()
        return cur.rowcount == 1
    finally:
        con.close()


def _normalize_action(action: str) -> str:
    txt = action.strip().upper().replace(" ", "_")
    aliases = {
        "AMB_ENTER_LONG": "ENTER_LONG",
        "AMB_ENTER_SHORT": "ENTER_SHORT",
        "AMB_EXIT_LONG": "EXIT_LONG",
        "AMB_EXIT_SHORT": "EXIT_SHORT",
    }
    return aliases.get(txt, txt)


def _extract_payload(raw: Any) -> tuple[str, str, str, str]:
    payload: dict[str, Any]
    raw_text: str

    if isinstance(raw, dict):
        payload = raw
        raw_text = json.dumps(raw, sort_keys=True)
    else:
        raw_text = str(raw)
        try:
            parsed = json.loads(raw_text)
            payload = parsed if isinstance(parsed, dict) else {"message": raw_text}
        except Exception:
            payload = {"message": raw_text}

    secret = str(payload.get("secret", ""))
    action_raw = str(payload.get("action", payload.get("message", "")))
    action = _normalize_action(action_raw)
    ticker = str(payload.get("ticker", ""))
    bar_time = str(payload.get("bar_time", payload.get("time", "")))

    if action not in {"ENTER_LONG", "ENTER_SHORT", "EXIT_LONG", "EXIT_SHORT"}:
        text = action_raw.upper()
        if "ENTER LONG" in text:
            action = "ENTER_LONG"
        elif "ENTER SHORT" in text:
            action = "ENTER_SHORT"
        elif "EXIT LONG" in text:
            action = "EXIT_LONG"
        elif "EXIT SHORT" in text:
            action = "EXIT_SHORT"

    if action not in {"ENTER_LONG", "ENTER_SHORT", "EXIT_LONG", "EXIT_SHORT"}:
        raise HTTPException(status_code=400, detail="Unsupported action")

    event_seed = f"{action}|{ticker}|{bar_time}|{raw_text}"
    event_id = str(payload.get("event_id", hashlib.sha256(event_seed.encode("utf-8")).hexdigest()))
    return secret, action, event_id, raw_text


def _get_exchange() -> ccxt.Exchange:
    if EXCHANGE_ID != "bybit":
        raise RuntimeError("Only EXCHANGE_ID=bybit is currently supported")

    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")

    exchange = ccxt.bybit(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        }
    )
    exchange.set_sandbox_mode(BYBIT_TESTNET)
    exchange.load_markets()
    return exchange


def _position_side(exchange: ccxt.Exchange, symbol: str) -> str:
    try:
        positions = exchange.fetch_positions([symbol])
    except Exception:
        return "flat"

    for pos in positions:
        contracts = float(pos.get("contracts") or pos.get("contractSize") or pos.get("size") or 0)
        if abs(contracts) <= 0:
            continue
        side = str(pos.get("side", "")).lower()
        if side in {"long", "short"}:
            return side
    return "flat"


def _position_size(exchange: ccxt.Exchange, symbol: str, side: str) -> float:
    positions = exchange.fetch_positions([symbol])
    for pos in positions:
        pos_side = str(pos.get("side", "")).lower()
        contracts = float(pos.get("contracts") or pos.get("contractSize") or pos.get("size") or 0)
        if pos_side == side and abs(contracts) > 0:
            return abs(contracts)
    return 0.0


def _amount_for_notional(exchange: ccxt.Exchange, symbol: str, notional_usdt: float) -> float:
    ticker = exchange.fetch_ticker(symbol)
    last = float(ticker.get("last") or ticker.get("close") or 0)
    if last <= 0:
        raise RuntimeError("Cannot determine market price for amount calculation")
    raw_amount = notional_usdt / last
    amount = float(exchange.amount_to_precision(symbol, raw_amount))
    if amount <= 0:
        raise RuntimeError("Calculated order amount is zero; increase ORDER_NOTIONAL_USDT")
    return amount


def _close_side(exchange: ccxt.Exchange, symbol: str, side: str) -> dict[str, Any]:
    amount = _position_size(exchange, symbol, side)
    if amount <= 0:
        return {"closed": False, "reason": "no_open_position"}

    order_side = "sell" if side == "long" else "buy"
    return exchange.create_order(
        symbol,
        "market",
        order_side,
        amount,
        None,
        {"reduceOnly": True},
    )


def _open_target(exchange: ccxt.Exchange, symbol: str, target: str) -> dict[str, Any]:
    amount = _amount_for_notional(exchange, symbol, ORDER_NOTIONAL_USDT)
    order_side = "buy" if target == "long" else "sell"
    return exchange.create_order(symbol, "market", order_side, amount)


def _execute(action: str) -> dict[str, Any]:
    if DRY_RUN:
        return {
            "mode": "dry_run",
            "action": action,
            "symbol": SYMBOL,
            "notional_usdt": ORDER_NOTIONAL_USDT,
        }

    exchange = _get_exchange()
    side = _position_side(exchange, SYMBOL)

    result: dict[str, Any] = {"mode": "live", "action": action, "current_side": side, "symbol": SYMBOL}

    if action == "ENTER_LONG":
        if side == "short":
            result["close_short"] = _close_side(exchange, SYMBOL, "short")
            side = "flat"
        if side == "flat":
            result["open_long"] = _open_target(exchange, SYMBOL, "long")

    elif action == "ENTER_SHORT":
        if side == "long":
            result["close_long"] = _close_side(exchange, SYMBOL, "long")
            side = "flat"
        if side == "flat":
            result["open_short"] = _open_target(exchange, SYMBOL, "short")

    elif action == "EXIT_LONG":
        if side == "long":
            result["close_long"] = _close_side(exchange, SYMBOL, "long")
        else:
            result["close_long"] = {"closed": False, "reason": "position_not_long"}

    elif action == "EXIT_SHORT":
        if side == "short":
            result["close_short"] = _close_side(exchange, SYMBOL, "short")
        else:
            result["close_short"] = {"closed": False, "reason": "position_not_short"}

    return result


_init_logging()
_init_db()

app = FastAPI(title=APP_NAME)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": APP_NAME,
        "dry_run": DRY_RUN,
        "symbol": SYMBOL,
    }


@app.post("/webhook")
async def webhook(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_body: Any = await request.json()
    else:
        raw_body = await request.body()
        raw_body = raw_body.decode("utf-8", errors="ignore")

    secret, action, event_id, raw_text = _extract_payload(raw_body)

    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_SECRET is not configured")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")

    inserted = _record_event_if_new(event_id, action, raw_text)
    if not inserted:
        return {"ok": True, "status": "duplicate", "event_id": event_id, "action": action}

    try:
        execution = _execute(action)
    except Exception as exc:
        logging.exception("Execution failed")
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc

    logging.info("Processed event %s action=%s", event_id, action)
    return {"ok": True, "status": "processed", "event_id": event_id, "action": action, "execution": execution}
