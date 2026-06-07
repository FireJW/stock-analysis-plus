#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
TRADINGAGENTS_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "tradingagents-decision-bridge" / "scripts"
if str(TRADINGAGENTS_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(TRADINGAGENTS_SCRIPT_DIR))

from tradingagents_eastmoney_market import fetch_daily_bars as fetch_eastmoney_daily_bars
from tradingagents_eastmoney_market import (
    EASTMONEY_DEFAULT_UT,
    cache_path,
    eastmoney_secid,
    format_date_yyyymmdd,
)


DEFAULT_LOOKBACK_DAYS = 420


def unique_tickers(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        ticker = " ".join(str(raw or "").split()).strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        ordered.append(ticker)
    return ordered


def parse_cli_tickers(raw: str) -> list[str]:
    return unique_tickers(part for part in str(raw or "").split(","))


def parse_tickers_file(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")
    if suffix == ".json":
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError("Ticker json file must contain an array of strings.")
        return unique_tickers(payload)
    return unique_tickers(text.splitlines())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preheat Eastmoney cache for selected tickers.")
    parser.add_argument("--tickers", default="", help="Comma-separated ticker list.")
    parser.add_argument("--tickers-file", default="", help="Path to txt/json ticker file.")
    parser.add_argument("--target-date", default="", help="Target date (YYYY-MM-DD). Defaults to today.")
    return parser


def eastmoney_cache_already_exists(ticker: str, start_date: str, end_date: str) -> bool:
    query = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "lmt": "10000",
        "ut": EASTMONEY_DEFAULT_UT,
        "secid": eastmoney_secid(ticker),
        "beg": format_date_yyyymmdd(start_date),
        "end": format_date_yyyymmdd(end_date),
    }
    cache_name = f"kline-{json.dumps(query, ensure_ascii=True, sort_keys=True)}.json"
    return cache_path(cache_name).exists()


def preheat_ticker(ticker: str, target_date: str, *, max_retries: int = 2) -> dict[str, str]:
    ticker = unique_tickers([ticker])[0]
    target_dt = date.fromisoformat(target_date[:10])
    start_date = (target_dt - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()
    if eastmoney_cache_already_exists(ticker, start_date, target_dt.isoformat()):
        return {"ticker": ticker, "status": "cache_hit", "message": ""}
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            rows = fetch_eastmoney_daily_bars(ticker, start_date, target_dt.isoformat())
            break
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
    else:
        return {"ticker": ticker, "status": "failed", "message": str(last_exc)}
    if not rows:
        return {"ticker": ticker, "status": "failed", "message": "No rows returned"}
    return {"ticker": ticker, "status": "cache_written", "message": ""}


def build_summary(results: list[dict[str, str]]) -> dict[str, int]:
    summary = {"total": len(results), "cache_hit": 0, "cache_written": 0, "failed": 0}
    for row in results:
        status = row.get("status")
        if status in summary:
            summary[status] += 1
    return summary


def print_results(results: list[dict[str, str]]) -> None:
    for row in results:
        status = row["status"]
        ticker = row["ticker"]
        message = row.get("message", "")
        if message:
            print(f"[{status}] {ticker} - {message}")
        else:
            print(f"[{status}] {ticker}")
    summary = build_summary(results)
    print("Summary:")
    print(f"- total: {summary['total']}")
    print(f"- cache_hit: {summary['cache_hit']}")
    print(f"- cache_written: {summary['cache_written']}")
    print(f"- failed: {summary['failed']}")


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    tickers = parse_cli_tickers(args.tickers)
    if args.tickers_file:
        tickers.extend(parse_tickers_file(Path(args.tickers_file)))
    tickers = unique_tickers(tickers)
    if not tickers:
        parser.error("Provide --tickers or --tickers-file.")
    target_date = args.target_date.strip() if args.target_date.strip() else datetime.now().date().isoformat()
    results = [preheat_ticker(ticker, target_date) for ticker in tickers]
    print_results(results)
    return 0 if any(row["status"] != "failed" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
