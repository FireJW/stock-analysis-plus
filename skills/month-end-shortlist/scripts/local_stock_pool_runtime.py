#!/usr/bin/env python3
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any


TDX_DAY_RECORD = struct.Struct("<iiiiifii")


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def clean_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    cleaned: list[str] = []
    for item in raw_items:
        text = clean_text(item)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def unique_strings(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = clean_text(item)
        if text and text not in result:
            result.append(text)
    return result


def normalize_a_share_ticker(value: Any) -> str:
    ticker = clean_text(value).upper()
    if not ticker:
        return ""
    ticker = ticker.replace(" ", "")
    if ticker.endswith(".SH"):
        return ticker[:-3] + ".SS"
    if ticker.endswith(".SS") or ticker.endswith(".SZ") or ticker.endswith(".BJ"):
        return ticker
    if ticker.endswith(".XSHE"):
        return ticker[:-5] + ".SZ"
    if ticker.endswith(".XSHG"):
        return ticker[:-5] + ".SS"
    digits = "".join(ch for ch in ticker if ch.isdigit())
    if len(digits) == 6:
        if digits.startswith(("6", "9")):
            return f"{digits}.SS"
        if digits.startswith(("8", "4")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"
    return ticker


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8-sig"))


def normalize_pool_stock(raw: dict[str, Any]) -> dict[str, Any]:
    ticker = normalize_a_share_ticker(raw.get("ticker") or raw.get("code") or raw.get("symbol"))
    if not ticker:
        return {}
    groups = clean_string_list(raw.get("groups") or raw.get("group") or raw.get("stock_pool_groups"))
    tags = clean_string_list(raw.get("tags") or raw.get("tag") or raw.get("stock_pool_tags"))
    strategy_tags = clean_string_list(raw.get("strategy_tags") or raw.get("strategy_tag"))
    normalized = {
        "ticker": ticker,
        "name": clean_text(raw.get("name") or raw.get("stock_name") or raw.get("display_name") or ticker),
        "groups": groups,
        "tags": tags,
        "strategy_tags": strategy_tags,
        "notes": clean_text(raw.get("notes") or raw.get("note")),
        "source": clean_text(raw.get("source")) or "local_stock_pool",
    }
    strategy_rules = raw.get("strategy_rules")
    if isinstance(strategy_rules, list):
        normalized["strategy_rules"] = [item for item in strategy_rules if isinstance(item, dict)]
    if isinstance(raw.get("plan_snapshot"), dict):
        normalized["plan_snapshot"] = dict(raw["plan_snapshot"])
    return normalized


def normalize_local_stock_pool(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    stocks = [
        normalized
        for normalized in (normalize_pool_stock(item) for item in payload.get("stocks", []) if isinstance(item, dict))
        if normalized
    ]
    if not stocks:
        return {}
    strategy_rules = payload.get("strategy_rules") if isinstance(payload.get("strategy_rules"), list) else []
    return {
        "schema_version": "local_stock_pool/v1",
        "name": clean_text(payload.get("name")) or "local_stock_pool",
        "stocks": stocks,
        "groups": payload.get("groups") if isinstance(payload.get("groups"), list) else [],
        "strategy_rules": [item for item in strategy_rules if isinstance(item, dict)],
        "ui_contract": {
            "interface_status": "data_contract_only",
            "supported_fields": [
                "ticker",
                "name",
                "groups",
                "tags",
                "notes",
            "strategy_tags",
            "strategy_rules",
            "plan_snapshot",
        ],
        "write_policy": "read_only_workflow_input",
    },
}


def normalize_local_stock_pool_from_request(raw_payload: dict[str, Any]) -> dict[str, Any]:
    pool_payload = raw_payload.get("local_stock_pool")
    pool_path = clean_text(raw_payload.get("local_stock_pool_path"))
    if not isinstance(pool_payload, dict) and pool_path:
        try:
            pool_payload = load_json(pool_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pool_payload = {}
    return normalize_local_stock_pool(pool_payload)


def local_stock_pool_lookup(pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        clean_text(item.get("ticker")): item
        for item in pool.get("stocks", [])
        if isinstance(item, dict) and clean_text(item.get("ticker"))
    }


def merge_local_pool_candidate_tickers(existing: Any, pool: dict[str, Any]) -> list[str]:
    tickers = [normalize_a_share_ticker(item) for item in (existing if isinstance(existing, list) else [])]
    for item in pool.get("stocks", []):
        if not isinstance(item, dict):
            continue
        tickers.append(normalize_a_share_ticker(item.get("ticker")))
    return unique_strings(tickers)


def normalize_local_daily_bars_source(raw_payload: dict[str, Any]) -> dict[str, Any]:
    source = raw_payload.get("local_daily_bars_source")
    if isinstance(source, dict):
        kind = clean_text(source.get("kind")) or "tdx_vipdoc"
        path = clean_text(source.get("path") or source.get("root") or source.get("vipdoc_path"))
    else:
        kind = "tdx_vipdoc"
        path = clean_text(raw_payload.get("tdx_vipdoc_path"))
    if not path:
        return {}
    return {
        "kind": kind,
        "path": path,
        "usage_boundary": "local EOD technical supplement; validate live price/news/fundamentals through provider-backed workflow before trading decisions.",
    }


def tdx_market_prefix(ticker: str) -> str:
    normalized = normalize_a_share_ticker(ticker)
    code = normalized.split(".")[0]
    if normalized.endswith(".SS"):
        return "sh"
    if normalized.endswith(".BJ"):
        return "bj"
    if normalized.endswith(".SZ"):
        return "sz"
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("8", "4")):
        return "bj"
    return "sz"


def tdx_day_path(root: str | Path, ticker: str) -> Path:
    normalized = normalize_a_share_ticker(ticker)
    code = normalized.split(".")[0]
    market = tdx_market_prefix(normalized)
    return Path(root).expanduser() / market / "lday" / f"{market}{code}.day"


def parse_tdx_date(value: int) -> str:
    text = str(value)
    if len(text) != 8:
        return ""
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def read_tdx_day_rows(root: str | Path, ticker: str, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
    path = tdx_day_path(root, ticker)
    if not path.exists():
        return []
    data = path.read_bytes()
    rows: list[dict[str, Any]] = []
    previous_close = 0.0
    for offset in range(0, len(data) - TDX_DAY_RECORD.size + 1, TDX_DAY_RECORD.size):
        date_int, open_raw, high_raw, low_raw, close_raw, amount, volume, _reserved = TDX_DAY_RECORD.unpack_from(data, offset)
        trade_date = parse_tdx_date(date_int)
        if not trade_date:
            continue
        if start_date and trade_date < start_date[:10]:
            previous_close = close_raw / 100.0
            continue
        if end_date and trade_date > end_date[:10]:
            break
        close = close_raw / 100.0
        pre_close = previous_close
        pct_chg = ((close - pre_close) / pre_close * 100.0) if pre_close else 0.0
        rows.append(
            {
                "trade_date": trade_date,
                "open": open_raw / 100.0,
                "high": high_raw / 100.0,
                "low": low_raw / 100.0,
                "close": close,
                "pre_close": pre_close,
                "pct_chg": round(pct_chg, 4),
                "amount": float(amount),
                "vol": float(volume),
                "source": "tdx_vipdoc",
            }
        )
        previous_close = close
    return rows


def fetch_local_daily_rows(source: dict[str, Any], ticker: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    if clean_text(source.get("kind")) != "tdx_vipdoc":
        return []
    root = clean_text(source.get("path"))
    if not root:
        return []
    return read_tdx_day_rows(root, ticker, start_date, end_date)


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def average(values: list[float]) -> float:
    cleaned = [float(item) for item in values if item not in (None, "")]
    return sum(cleaned) / len(cleaned) if cleaned else 0.0


def moving_average(rows: list[dict[str, Any]], period: int, *, end_offset: int = 0) -> float:
    end = len(rows) - end_offset
    start = end - period
    if start < 0 or end <= 0:
        return 0.0
    return average([to_float(item.get("close")) for item in rows[start:end]])


def slope_pct(current: float, previous: float) -> float:
    return round((current - previous) / previous * 100.0, 4) if previous else 0.0


def bias_pct(close: float, ma_value: float) -> float:
    return round((close - ma_value) / ma_value * 100.0, 4) if ma_value else 0.0


def build_local_technical_snapshot(rows: list[dict[str, Any]], *, source: str = "local_daily_bars") -> dict[str, Any]:
    if not rows:
        return {"price_snapshot": {}, "technical_snapshot": {}}
    latest = rows[-1]
    close = to_float(latest.get("close"))
    periods = (5, 10, 20, 50, 60, 120, 150, 200)
    ma_values = {f"ma{period}": round(moving_average(rows, period), 4) for period in periods}
    ma20_prev_5 = moving_average(rows, 20, end_offset=5)
    ma60_prev_10 = moving_average(rows, 60, end_offset=10)
    ma120_prev_20 = moving_average(rows, 120, end_offset=20)
    previous_volumes = [to_float(item.get("vol") if item.get("vol") not in (None, "") else item.get("volume")) for item in rows[-6:-1]]
    base_vol = average(previous_volumes)
    latest_vol = to_float(latest.get("vol") if latest.get("vol") not in (None, "") else latest.get("volume"))
    vol_ratio = round(latest_vol / base_vol, 4) if base_vol else 0.0
    price_snapshot = {
        "close": close,
        "ma5": ma_values["ma5"],
        "ma10": ma_values["ma10"],
        "ma20": ma_values["ma20"],
        "ma20_prev_5": round(ma20_prev_5, 4),
        "ma50": ma_values["ma50"],
        "ma60": ma_values["ma60"],
        "ma120": ma_values["ma120"],
        "ma150": ma_values["ma150"],
        "ma200": ma_values["ma200"],
        "vol_ratio_5d": vol_ratio,
        "recent_turnover_window": [to_float(item.get("amount")) for item in rows[-5:]],
        "base_turnover_window": [to_float(item.get("amount")) for item in rows[-20:-5]],
    }
    technical_snapshot = {
        "source": source,
        "trade_date": clean_text(latest.get("trade_date") or latest.get("date")),
        "moving_averages": {key: value for key, value in ma_values.items() if value},
        "slopes": {
            "ma20_slope_5d_pct": slope_pct(ma_values["ma20"], ma20_prev_5),
            "ma60_slope_10d_pct": slope_pct(ma_values["ma60"], ma60_prev_10),
            "ma120_slope_20d_pct": slope_pct(ma_values["ma120"], ma120_prev_20),
        },
        "biases": {
            "bias5_pct": bias_pct(close, ma_values["ma5"]),
            "bias10_pct": bias_pct(close, ma_values["ma10"]),
            "bias20_pct": bias_pct(close, ma_values["ma20"]),
            "bias60_pct": bias_pct(close, ma_values["ma60"]),
            "bias120_pct": bias_pct(close, ma_values["ma120"]),
        },
        "volume": {
            "latest_volume": latest_vol,
            "avg_volume_5d_ex_latest": round(base_vol, 4),
            "vol_ratio_5d": vol_ratio,
            "volume_status": "expanding" if vol_ratio >= 1.5 else "normal" if vol_ratio >= 0.8 else "contracting",
        },
    }
    return {"price_snapshot": price_snapshot, "technical_snapshot": technical_snapshot}
