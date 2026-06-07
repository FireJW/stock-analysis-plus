#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[[list[str], dict[str, str] | None, int], Any]
SCRIPT_DIR = Path(__file__).resolve().parent
TRADINGAGENTS_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "tradingagents-decision-bridge" / "scripts"


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"), strict=False)
    return payload if isinstance(payload, dict) else {}


def load_longbridge_cli_runner() -> CommandRunner:
    if str(TRADINGAGENTS_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(TRADINGAGENTS_SCRIPT_DIR))
    from tradingagents_longbridge_market import run_longbridge_cli

    return run_longbridge_cli


def compact_json(value: Any, *, limit: int = 20) -> Any:
    if isinstance(value, list):
        return value[:limit]
    return value


def list_payload(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        for key in ("items", "list", "data", "rows", "lines", "trading_days", "sessions", "markets"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def call_longbridge(
    args: list[str],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    unavailable: list[dict[str, str]],
    command: str,
    symbol: str = "",
    timeout_seconds: int = 20,
) -> Any:
    try:
        return runner(args, env, timeout_seconds)
    except Exception as exc:
        item = {"command": command, "reason": clean_text(exc)}
        if symbol:
            item["symbol"] = symbol
        unavailable.append(item)
        return None


def analysis_date_for_cli(analysis_date: str) -> str:
    try:
        return datetime.strptime(analysis_date[:10], "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return clean_text(analysis_date).replace("-", "")


def normalize_market(request: dict[str, Any], symbols: list[str]) -> str:
    explicit = clean_text(request.get("market")).upper()
    if explicit:
        return explicit
    for symbol in symbols:
        suffix = clean_text(symbol).rsplit(".", 1)[-1].upper()
        if suffix in {"HK", "US", "CN", "SG"}:
            return suffix
        if suffix in {"SH", "SZ"}:
            return "CN"
    return "HK"


def normalize_symbols(request: dict[str, Any]) -> list[dict[str, Any]]:
    plan_levels = request.get("plan_levels") if isinstance(request.get("plan_levels"), dict) else {}
    symbols: list[dict[str, Any]] = []
    for item in request.get("tickers") or []:
        if isinstance(item, dict):
            symbol = clean_text(item.get("symbol") or item.get("ticker"))
            levels = {key: item.get(key) for key in ("trigger_price", "stop_loss", "abandon_below") if key in item}
        else:
            symbol = clean_text(item)
            levels = {}
        if not symbol:
            continue
        configured = plan_levels.get(symbol) if isinstance(plan_levels.get(symbol), dict) else {}
        merged = {**configured, **levels}
        symbols.append({"symbol": symbol, "plan_levels": merged})
    return symbols


def market_status_allows_trading(payload: Any, market: str) -> tuple[bool, dict[str, Any]]:
    entries = list_payload(payload, "markets")
    selected = {}
    for item in entries:
        if clean_text(item.get("market")).upper() == market:
            selected = item
            break
    if not selected and entries:
        selected = entries[0]
    status_text = " ".join(
        clean_text(selected.get(key)).lower()
        for key in ("status", "trade_status", "description", "market_status")
    )
    allowed = bool(status_text) and any(token in status_text for token in ("open", "trading", "normal")) and "closed" not in status_text
    return allowed, {"market": market, "selected": selected, "trading_allowed": allowed, "raw": compact_json(payload)}


def trading_day_allows_trading(payload: Any, analysis_date: str) -> tuple[bool, dict[str, Any]]:
    day = clean_text(analysis_date)[:10]
    raw_days = []
    if isinstance(payload, dict):
        raw_days = payload.get("trading_days") or payload.get("days") or payload.get("items") or []
    elif isinstance(payload, list):
        raw_days = payload
    normalized_days: list[str] = []
    for item in raw_days:
        if isinstance(item, dict):
            normalized_days.append(clean_text(item.get("date") or item.get("day") or item.get("trading_day")))
        else:
            normalized_days.append(clean_text(item))
    allowed = day in normalized_days if day else bool(normalized_days)
    return allowed, {"analysis_date": day, "is_trading_day": allowed, "trading_days": normalized_days, "raw": compact_json(payload)}


def latest_intraday_line(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any], float | None]:
    lines = list_payload(payload, "lines", "items", "data")
    latest = lines[-1] if lines else {}
    latest_price = to_float(
        latest.get("price")
        or latest.get("last")
        or latest.get("last_price")
        or latest.get("close")
    )
    return lines, latest, latest_price


def normalize_capital_flow(payload: Any) -> dict[str, Any]:
    rows = list_payload(payload, "items", "list", "data", "rows", "flows", "lines")
    latest = rows[-1] if rows else {}
    data = payload if isinstance(payload, dict) else {}
    source = latest if latest else data
    net_inflow = to_float(source.get("net_inflow") or source.get("net_flow"))
    if net_inflow is None and source.get("inflow") is not None and source.get("outflow") is not None:
        inflow = to_float(source.get("inflow"))
        outflow = to_float(source.get("outflow"))
        if inflow is not None and outflow is not None:
            net_inflow = inflow - outflow
    large_in = to_float(source.get("large_order_inflow") or source.get("main_inflow") or source.get("big_inflow"))
    large_out = to_float(source.get("large_order_outflow") or source.get("main_outflow") or source.get("big_outflow"))
    cumulative_net = None
    if rows:
        total = 0.0
        found = False
        for row in rows:
            value = to_float(row.get("net_inflow") or row.get("net_flow"))
            if value is None and row.get("inflow") is not None and row.get("outflow") is not None:
                inflow = to_float(row.get("inflow"))
                outflow = to_float(row.get("outflow"))
                if inflow is not None and outflow is not None:
                    value = inflow - outflow
            if value is not None:
                total += value
                found = True
        cumulative_net = total if found else None
    confirms = False
    if net_inflow is not None and net_inflow > 0:
        confirms = True
    if cumulative_net is not None and cumulative_net > 0:
        confirms = True
    if large_in is not None and large_out is not None and large_in > large_out:
        confirms = True
    return {
        "net_inflow": net_inflow,
        "latest_net_inflow": net_inflow,
        "cumulative_net_inflow": cumulative_net,
        "large_order_inflow": large_in,
        "large_order_outflow": large_out,
        "flow_points": rows,
        "confirms": confirms,
        "raw": compact_json(payload),
    }


def normalize_anomalies(payload: Any) -> dict[str, Any]:
    items = list_payload(payload, "items", "list", "data")
    return {"exists": bool(items), "count": len(items), "items": items, "raw": compact_json(payload)}


def normalize_trade_stats(payload: Any) -> dict[str, Any]:
    distribution = list_payload(payload, "price_distribution", "distribution", "items", "list", "data", "rows")
    normalized: list[dict[str, Any]] = []
    total_volume = 0.0
    dominant: dict[str, Any] = {}
    dominant_volume = -1.0
    for item in distribution:
        price = to_float(item.get("price") or item.get("avg_price"))
        volume = to_float(item.get("volume") or item.get("vol") or item.get("qty") or item.get("quantity"))
        row = {
            "price": price,
            "volume": volume,
            "raw": item,
        }
        normalized.append(row)
        if volume is not None:
            total_volume += volume
            if volume > dominant_volume:
                dominant_volume = volume
                dominant = row
    return {
        "distribution": normalized,
        "row_count": len(normalized),
        "dominant_price": dominant.get("price"),
        "dominant_volume": dominant.get("volume"),
        "total_volume": total_volume if normalized else None,
        "raw": compact_json(payload),
    }


def build_plan_status(
    levels: dict[str, Any],
    latest_price: float | None,
    *,
    trading_allowed: bool,
) -> dict[str, Any]:
    trigger_price = to_float(levels.get("trigger_price"))
    stop_loss = to_float(levels.get("stop_loss"))
    abandon_below = to_float(levels.get("abandon_below"))
    triggered = latest_price is not None and trigger_price is not None and latest_price >= trigger_price
    invalidated = latest_price is not None and (
        (stop_loss is not None and latest_price <= stop_loss)
        or (abandon_below is not None and latest_price <= abandon_below)
    )
    if not trading_allowed:
        state = "blocked"
    elif invalidated:
        state = "invalidated"
    elif triggered:
        state = "triggered"
    elif latest_price is None:
        state = "blocked"
    else:
        state = "active"
    return {
        "state": state,
        "latest_price": latest_price,
        "trigger_price": trigger_price,
        "stop_loss": stop_loss,
        "abandon_below": abandon_below,
        "triggered": state == "triggered",
        "invalidated": state == "invalidated",
        "active": state == "active",
        "blocked": state == "blocked",
    }


def run_longbridge_intraday_monitor(
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    symbols = normalize_symbols(request)
    symbol_names = [item["symbol"] for item in symbols]
    analysis_date = clean_text(request.get("analysis_date"))
    market = normalize_market(request, symbol_names)
    session = clean_text(request.get("session")).lower() or "intraday"
    if session not in {"intraday", "all"}:
        session = "intraday"
    anomaly_count = max(1, min(to_int(request.get("anomaly_count"), 20), 100))
    unavailable: list[dict[str, str]] = []

    market_payload = call_longbridge(
        ["market-status", "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
        command="market-status",
    )
    market_open, market_status = market_status_allows_trading(market_payload, market)

    session_payload = call_longbridge(
        ["trading", "session", "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
        command="trading session",
    )
    trading_session = {"raw": compact_json(session_payload), "sessions": list_payload(session_payload, "sessions")}

    trading_day_args = ["trading", "days", market, "--format", "json"]
    if analysis_date:
        trading_day_args = [
            "trading",
            "days",
            market,
            "--start",
            analysis_date[:10],
            "--end",
            analysis_date[:10],
            "--format",
            "json",
        ]
    trading_days_payload = call_longbridge(
        trading_day_args,
        runner=runner,
        env=env,
        unavailable=unavailable,
        command="trading days",
    )
    is_trading_day, trading_days = trading_day_allows_trading(trading_days_payload, analysis_date)

    risk_flags: list[str] = []
    if not market_open:
        risk_flags.append("market_closed")
    if not is_trading_day:
        risk_flags.append("non_trading_day")
    trading_allowed = market_open and is_trading_day

    monitored_symbols: list[dict[str, Any]] = []
    cli_date = analysis_date_for_cli(analysis_date) if analysis_date else ""
    for item in symbols:
        symbol = item["symbol"]
        symbol_unavailable: list[dict[str, str]] = []
        intraday_args = ["intraday", symbol, "--session", session]
        if cli_date:
            intraday_args.extend(["--date", cli_date])
        intraday_args.extend(["--format", "json"])
        intraday_payload = call_longbridge(
            intraday_args,
            runner=runner,
            env=env,
            unavailable=symbol_unavailable,
            command="intraday",
            symbol=symbol,
        )
        lines, latest_line, latest_price = latest_intraday_line(intraday_payload)

        capital_payload = call_longbridge(
            ["capital", symbol, "--flow", "--format", "json"],
            runner=runner,
            env=env,
            unavailable=symbol_unavailable,
            command="capital",
            symbol=symbol,
        )
        capital_flow = normalize_capital_flow(capital_payload)

        anomaly_payload = call_longbridge(
            ["anomaly", "--market", market, "--symbol", symbol, "--count", str(anomaly_count), "--format", "json"],
            runner=runner,
            env=env,
            unavailable=symbol_unavailable,
            command="anomaly",
            symbol=symbol,
        )
        abnormal_volume = normalize_anomalies(anomaly_payload)

        trade_stats_payload = call_longbridge(
            ["trade-stats", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=symbol_unavailable,
            command="trade-stats",
            symbol=symbol,
        )

        data_coverage = {
            "intraday_available": bool(lines),
            "capital_available": capital_payload is not None,
            "anomaly_available": anomaly_payload is not None,
            "trade_stats_available": trade_stats_payload is not None,
        }
        plan_status = build_plan_status(item["plan_levels"], latest_price, trading_allowed=trading_allowed)
        monitored_symbols.append(
            {
                "symbol": symbol,
                "market": market,
                "session": session,
                "latest_price": latest_price,
                "latest_intraday_line": latest_line,
                "intraday": {"lines": lines, "raw": compact_json(intraday_payload)},
                "capital_flow": capital_flow,
                "abnormal_volume": abnormal_volume,
                "trade_stats": normalize_trade_stats(trade_stats_payload),
                "plan_levels": deepcopy(item["plan_levels"]),
                "plan_status": plan_status,
                "data_coverage": data_coverage,
                "unavailable": symbol_unavailable,
                "should_apply": False,
                "side_effects": "none",
            }
        )
        unavailable.extend(symbol_unavailable)

    result = {
        "request": deepcopy(request),
        "intraday_monitor": {
            "analysis_date": analysis_date,
            "market": market,
            "session": session,
            "trading_allowed": trading_allowed,
            "symbol_count": len(monitored_symbols),
        },
        "market_status": market_status,
        "trading_session": trading_session,
        "trading_days": trading_days,
        "monitored_symbols": monitored_symbols,
        "risk_flags": risk_flags,
        "data_coverage": {
            "market_status_available": market_payload is not None,
            "trading_session_available": session_payload is not None,
            "trading_days_available": trading_days_payload is not None,
            "intraday_symbols_available": sum(1 for item in monitored_symbols if item["data_coverage"]["intraday_available"]),
            "capital_symbols_available": sum(1 for item in monitored_symbols if item["data_coverage"]["capital_available"]),
            "anomaly_symbols_available": sum(1 for item in monitored_symbols if item["data_coverage"]["anomaly_available"]),
            "trade_stats_symbols_available": sum(1 for item in monitored_symbols if item["data_coverage"]["trade_stats_available"]),
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run a read-only Longbridge intraday monitor.")
    parser.add_argument("request_json", help="Path to request JSON.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    request = load_json(Path(args.request_json))
    run_longbridge_cli = load_longbridge_cli_runner()
    result = run_longbridge_intraday_monitor(request, runner=run_longbridge_cli)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
