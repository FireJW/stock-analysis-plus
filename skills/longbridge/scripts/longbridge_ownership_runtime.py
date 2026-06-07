#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[[list[str], dict[str, str] | None, int], Any]
SCRIPT_DIR = Path(__file__).resolve().parent
TRADINGAGENTS_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "tradingagents-decision-bridge" / "scripts"


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"), strict=False)
    return payload if isinstance(payload, dict) else {}


def load_longbridge_cli_runner() -> CommandRunner:
    if str(TRADINGAGENTS_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(TRADINGAGENTS_SCRIPT_DIR))
    from tradingagents_longbridge_market import run_longbridge_cli

    return run_longbridge_cli


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def bounded_count(value: Any, *, default: int, low: int = 1, high: int = 100) -> int:
    count = to_int(value, default)
    return max(low, min(count, high))


def is_us_symbol(symbol: str) -> bool:
    return clean_text(symbol).upper().endswith(".US")


def list_payload(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys + ("items", "list", "data", "rows", "trades", "transactions", "holdings"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def first_number(*values: Any) -> float:
    for value in values:
        number = to_float(value)
        if not math.isnan(number):
            return number
    return float("nan")


def optional_longbridge_payload(
    args: list[str],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    unavailable: list[dict[str, str]],
    symbol: str = "",
    cik: str = "",
) -> Any:
    command = args[0] if args else ""
    try:
        return runner(args, env, 20)
    except Exception as exc:
        entry = {"command": command, "reason": clean_text(exc)}
        if symbol:
            entry["symbol"] = symbol
        if cik:
            entry["cik"] = cik
        unavailable.append(entry)
        return None


def normalize_insider_trades(payload: Any, symbol: str) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for item in list_payload(payload, "items", "trades", "transactions"):
        transaction_type = clean_text(
            item.get("transaction_type")
            or item.get("transaction_code")
            or item.get("code")
            or item.get("type")
        ).upper()
        shares = first_number(item.get("shares"), item.get("quantity"), item.get("amount"))
        price = first_number(item.get("price"), item.get("transaction_price"))
        trades.append(
            {
                "symbol": clean_text(item.get("symbol")) or symbol,
                "insider": clean_text(item.get("insider") or item.get("owner_name") or item.get("reporter_name") or item.get("name")),
                "transaction_type": transaction_type,
                "transaction_date": clean_text(item.get("transaction_date") or item.get("date") or item.get("filed_at")),
                "shares": shares if not math.isnan(shares) else None,
                "price": price if not math.isnan(price) else None,
            }
        )
    return trades


def normalize_short_positions(payload: Any, symbol: str) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for item in list_payload(payload, "items", "positions", "short_positions"):
        short_ratio = first_number(item.get("short_ratio"), item.get("short_interest_ratio"), item.get("short_float_pct"))
        days_to_cover = first_number(item.get("days_to_cover"), item.get("days_cover"), item.get("cover_days"))
        positions.append(
            {
                "symbol": clean_text(item.get("symbol")) or symbol,
                "settlement_date": clean_text(item.get("settlement_date") or item.get("date") or item.get("report_date")),
                "short_ratio": short_ratio if not math.isnan(short_ratio) else None,
                "days_to_cover": days_to_cover if not math.isnan(days_to_cover) else None,
                "short_interest": clean_text(item.get("short_interest") or item.get("shares_short")),
            }
        )
    return positions


def normalize_investor_ranking(payload: Any) -> list[dict[str, Any]]:
    ranking: list[dict[str, Any]] = []
    for item in list_payload(payload, "items", "investors", "managers"):
        ranking.append(
            {
                "cik": clean_text(item.get("cik") or item.get("CIK")),
                "manager": clean_text(item.get("manager") or item.get("name") or item.get("institution")),
                "aum": clean_text(item.get("aum") or item.get("assets_under_management")),
            }
        )
    return ranking


def normalize_investor_holdings(payload: Any, cik: str) -> dict[str, Any]:
    holdings: list[dict[str, Any]] = []
    for item in list_payload(payload, "holdings", "items", "positions"):
        weight = first_number(item.get("weight"), item.get("portfolio_weight"), item.get("percent"))
        holdings.append(
            {
                "symbol": clean_text(item.get("symbol") or item.get("ticker")),
                "name": clean_text(item.get("name") or item.get("issuer")),
                "value": clean_text(item.get("value") or item.get("market_value")),
                "shares": clean_text(item.get("shares") or item.get("quantity")),
                "weight": weight if not math.isnan(weight) else None,
            }
        )
    return {
        "cik": clean_text(payload.get("cik") if isinstance(payload, dict) else "") or cik,
        "holdings": holdings,
    }


def build_risk_flags(
    symbol: str,
    *,
    insider_trades: list[dict[str, Any]],
    short_positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    sell_trades = [
        item for item in insider_trades
        if clean_text(item.get("transaction_type")).upper() in {"SELL", "S"}
    ]
    if sell_trades:
        flags.append(
            {
                "symbol": symbol,
                "flag": "insider_sell_activity",
                "severity": "medium",
                "evidence_count": len(sell_trades),
                "detail": "Recent insider sell transactions were reported.",
            }
        )
    latest_short = short_positions[0] if short_positions else {}
    short_ratio = to_float(latest_short.get("short_ratio"))
    days_to_cover = to_float(latest_short.get("days_to_cover"))
    if (not math.isnan(short_ratio) and short_ratio >= 10.0) or (not math.isnan(days_to_cover) and days_to_cover >= 5.0):
        flags.append(
            {
                "symbol": symbol,
                "flag": "high_short_interest",
                "severity": "high" if short_ratio >= 20.0 or days_to_cover >= 10.0 else "medium",
                "short_ratio": short_ratio if not math.isnan(short_ratio) else None,
                "days_to_cover": days_to_cover if not math.isnan(days_to_cover) else None,
                "detail": "Short interest metrics are elevated.",
            }
        )
    return flags


def run_longbridge_ownership_analysis(
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    tickers = [clean_text(item).upper() for item in request.get("tickers") or [] if clean_text(item)]
    insider_count = bounded_count(request.get("insider_count"), default=20)
    short_count = bounded_count(request.get("short_count"), default=20)
    investor_top = bounded_count(request.get("investor_top"), default=50)
    investor_ciks = [clean_text(item) for item in request.get("investor_ciks") or [] if clean_text(item)]

    unavailable: list[dict[str, str]] = []
    insider_trades: dict[str, list[dict[str, Any]]] = {}
    short_positions: dict[str, list[dict[str, Any]]] = {}
    ownership_risk_analysis: dict[str, dict[str, Any]] = {}
    risk_flags: list[dict[str, Any]] = []
    data_coverage: dict[str, Any] = {
        "insider_trades": {},
        "short_positions": {},
        "institutional_investors": {},
    }

    for symbol in tickers:
        if not is_us_symbol(symbol):
            insider_trades[symbol] = []
            short_positions[symbol] = []
            data_coverage["insider_trades"][symbol] = False
            data_coverage["short_positions"][symbol] = False
            unavailable.append({"command": "insider-trades", "symbol": symbol, "reason": "US-only endpoint skipped for non-US symbol"})
            unavailable.append({"command": "short-positions", "symbol": symbol, "reason": "US-only endpoint skipped for non-US symbol"})
            ownership_risk_analysis[symbol] = {
                "symbol": symbol,
                "us_listed": False,
                "risk_flags": [],
                "summary": "US-only ownership risk endpoints were skipped for this non-US symbol.",
            }
            continue

        raw_trades = optional_longbridge_payload(
            ["insider-trades", symbol, "--count", str(insider_count), "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
            symbol=symbol,
        )
        trades = normalize_insider_trades(raw_trades, symbol) if raw_trades is not None else []
        insider_trades[symbol] = trades
        data_coverage["insider_trades"][symbol] = raw_trades is not None

        raw_short = optional_longbridge_payload(
            ["short-positions", symbol, "--count", str(short_count), "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
            symbol=symbol,
        )
        positions = normalize_short_positions(raw_short, symbol) if raw_short is not None else []
        short_positions[symbol] = positions
        data_coverage["short_positions"][symbol] = raw_short is not None

        symbol_flags = build_risk_flags(symbol, insider_trades=trades, short_positions=positions)
        risk_flags.extend(symbol_flags)
        sell_count = sum(1 for item in trades if clean_text(item.get("transaction_type")).upper() in {"SELL", "S"})
        latest_short = positions[0] if positions else {}
        ownership_risk_analysis[symbol] = {
            "symbol": symbol,
            "us_listed": True,
            "insider_sell_count": sell_count,
            "insider_trade_count": len(trades),
            "latest_short_ratio": latest_short.get("short_ratio"),
            "latest_days_to_cover": latest_short.get("days_to_cover"),
            "risk_flags": symbol_flags,
        }

    investor_ranking_payload = optional_longbridge_payload(
        ["investors", "--top", str(investor_top), "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )
    investor_ranking = normalize_investor_ranking(investor_ranking_payload) if investor_ranking_payload is not None else []
    data_coverage["institutional_investors"]["ranking"] = investor_ranking_payload is not None

    holdings_by_cik: dict[str, dict[str, Any]] = {}
    for cik in investor_ciks:
        payload = optional_longbridge_payload(
            ["investors", cik, "--top", str(investor_top), "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
            cik=cik,
        )
        holdings_by_cik[cik] = normalize_investor_holdings(payload, cik) if payload is not None else {"cik": cik, "holdings": []}
        data_coverage["institutional_investors"][cik] = payload is not None

    return {
        "request": deepcopy(request),
        "ownership_risk_analysis": ownership_risk_analysis,
        "insider_trades": insider_trades,
        "institutional_investors": {
            "ranking": investor_ranking,
            "holdings_by_cik": holdings_by_cik,
        },
        "short_positions": short_positions,
        "risk_flags": risk_flags,
        "data_coverage": data_coverage,
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run read-only Longbridge ownership and short-interest diagnostics.")
    parser.add_argument("request_json", help="Path to request JSON.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args(argv)

    request = load_json(Path(args.request_json))
    result = run_longbridge_ownership_analysis(
        request,
        runner=load_longbridge_cli_runner(),
        env=dict(os.environ),
    )
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
