#!/usr/bin/env python3
"""Live trigger monitor for the month-end shortlist trade cards.

Watches Longbridge real-time quotes and surfaces alerts when a trade card's
``trigger_price``, ``stop_loss`` or ``abandon_below`` is hit or approached.
Designed for one-shot CLI use today and for embedding into a polling loop later.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import clean_text, normalize_a_share_ticker


SCHEMA_VERSION = "trigger_monitor/v1"
APPROACH_THRESHOLD_PCT = 2.0
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 20.0


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number:  # NaN guard
            return None
        return number
    text = clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_longbridge_ticker(ticker: str) -> str:
    """Convert pool tickers to the format Longbridge CLI accepts.

    Pool stores Yahoo-style ``.SS`` for Shanghai; Longbridge uses ``.SH``.
    Other suffixes (.SZ/.BJ/.HK/.US) pass through unchanged.
    """
    text = clean_text(ticker).upper().replace(" ", "")
    if not text:
        return ""
    if text.endswith(".SS"):
        return text[:-3] + ".SH"
    return text


def _first_numeric(source: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if isinstance(value, list):
            for item in value:
                parsed = parse_float(item)
                if parsed is not None:
                    return parsed
            continue
        parsed = parse_float(value)
        if parsed is not None:
            return parsed
    return None


def _extract_card_levels(stock: dict[str, Any]) -> dict[str, float | None]:
    """Pull numeric trigger/stop/abandon levels from any of the known shapes."""
    plan_snapshot = safe_dict(stock.get("plan_snapshot"))
    trade_card = safe_dict(stock.get("trade_card") or plan_snapshot.get("trade_card"))
    levels = safe_dict(stock.get("levels") or plan_snapshot.get("levels"))
    price_paths = safe_dict(stock.get("price_paths") or plan_snapshot.get("price_paths"))

    trigger = _first_numeric(trade_card, ("trigger_price", "trigger"))
    if trigger is None:
        trigger = _first_numeric(levels, ("trigger_price", "trigger"))
    if trigger is None:
        trigger = _first_numeric(price_paths, ("resistance", "target", "bull", "trigger"))

    stop = _first_numeric(trade_card, ("stop_loss", "stop"))
    if stop is None:
        stop = _first_numeric(levels, ("stop_loss", "stop"))
    if stop is None:
        # support is a list ordered tightest-first; first value is the stop.
        stop = _first_numeric(price_paths, ("stop_loss", "support"))

    abandon = _first_numeric(trade_card, ("abandon_below", "abandon"))
    if abandon is None:
        abandon = _first_numeric(levels, ("abandon_below", "abandon"))
    if abandon is None:
        abandon = _first_numeric(price_paths, ("abandon_below", "abandon"))

    return {"trigger_price": trigger, "stop_loss": stop, "abandon_below": abandon}


def extract_active_trade_cards(package: dict[str, Any]) -> list[dict[str, Any]]:
    """Return trade cards from the pool that have at least one numeric level."""
    pool = safe_dict(safe_dict(package).get("local_stock_pool"))
    cards: list[dict[str, Any]] = []
    for stock in safe_list(pool.get("stocks")):
        if not isinstance(stock, dict):
            continue
        ticker = clean_text(stock.get("ticker"))
        if not ticker:
            continue
        levels = _extract_card_levels(stock)
        if all(value is None for value in levels.values()):
            continue
        plan_snapshot = safe_dict(stock.get("plan_snapshot"))
        trade_card = safe_dict(stock.get("trade_card") or plan_snapshot.get("trade_card"))
        cards.append(
            {
                "ticker": ticker,
                "longbridge_ticker": to_longbridge_ticker(ticker),
                "name": clean_text(stock.get("name")) or ticker,
                "trigger_price": levels["trigger_price"],
                "stop_loss": levels["stop_loss"],
                "abandon_below": levels["abandon_below"],
                "watch_action": clean_text(trade_card.get("watch_action")),
                "invalidation": clean_text(trade_card.get("invalidation")),
            }
        )
    return cards


def _normalize_quote_row(row: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    symbol = clean_text(
        row.get("symbol") or row.get("ticker") or row.get("code") or row.get("security")
    ).upper()
    if not symbol:
        return None
    quote = {
        "last_done": parse_float(
            row.get("last_done") or row.get("last") or row.get("last_price") or row.get("price")
        ),
        "prev_close": parse_float(row.get("prev_close") or row.get("previous_close")),
        "high": parse_float(row.get("high") or row.get("day_high")),
        "low": parse_float(row.get("low") or row.get("day_low")),
        "volume": parse_float(row.get("volume") or row.get("vol")),
        "timestamp": clean_text(row.get("timestamp") or row.get("time") or row.get("at")),
    }
    return symbol, quote


def _parse_quote_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict):
        rows = (
            payload.get("data")
            or payload.get("quotes")
            or payload.get("rows")
            or payload.get("payload")
            or []
        )
        if isinstance(rows, dict):
            rows = [rows]
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    quotes: dict[str, dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_quote_row(row)
        if normalized is None:
            continue
        symbol, quote = normalized
        quotes[symbol] = quote
    return quotes


def fetch_quotes(
    tickers: list[str],
    longbridge_binary: str = "longbridge",
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    runner: Any = None,
) -> dict[str, dict[str, Any]]:
    """Shell out to ``longbridge quote <symbols>`` and parse the JSON response."""
    cleaned_tickers = [clean_text(t).upper() for t in tickers if clean_text(t)]
    if not cleaned_tickers:
        return {}
    cmd = [longbridge_binary, "quote", *cleaned_tickers, "--format", "json"]
    try:
        if runner is not None:
            completed = runner(cmd, timeout=timeout)
        else:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
    except Exception:
        return {}
    if getattr(completed, "returncode", 1) != 0:
        return {}
    stdout = getattr(completed, "stdout", "") or ""
    if not stdout.strip():
        return {}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return _parse_quote_payload(payload)


def _alert(
    *,
    card: dict[str, Any],
    alert_type: str,
    level_name: str,
    level_price: float,
    last_done: float,
    timestamp: str,
) -> dict[str, Any]:
    distance_pct = ((last_done - level_price) / level_price) * 100 if level_price else 0.0
    return {
        "ticker": card["ticker"],
        "name": card.get("name") or card["ticker"],
        "alert_type": alert_type,
        "level_name": level_name,
        "level_price": round(level_price, 4),
        "last_done": round(last_done, 4),
        "distance_pct": round(distance_pct, 3),
        "timestamp": timestamp,
    }


def detect_trigger_alerts(
    trade_cards: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Walk each trade card's quote and emit hit / approaching alerts."""
    threshold = APPROACH_THRESHOLD_PCT / 100.0
    alerts: list[dict[str, Any]] = []
    for card in trade_cards:
        if not isinstance(card, dict):
            continue
        lookup_key = clean_text(card.get("longbridge_ticker") or card.get("ticker")).upper()
        quote = quotes.get(lookup_key)
        if quote is None and lookup_key.endswith(".SH"):
            quote = quotes.get(lookup_key[:-3] + ".SS")
        if quote is None and lookup_key.endswith(".SS"):
            quote = quotes.get(lookup_key[:-3] + ".SH")
        if not isinstance(quote, dict):
            continue
        last_done = parse_float(quote.get("last_done"))
        if last_done is None:
            continue
        timestamp = clean_text(quote.get("timestamp")) or datetime.now(UTC).isoformat(
            timespec="seconds"
        )

        trigger = parse_float(card.get("trigger_price"))
        stop = parse_float(card.get("stop_loss"))
        abandon = parse_float(card.get("abandon_below"))

        if abandon is not None and last_done <= abandon:
            alerts.append(
                _alert(
                    card=card,
                    alert_type="abandon_hit",
                    level_name="abandon_below",
                    level_price=abandon,
                    last_done=last_done,
                    timestamp=timestamp,
                )
            )
        if stop is not None and last_done <= stop:
            alerts.append(
                _alert(
                    card=card,
                    alert_type="stop_hit",
                    level_name="stop_loss",
                    level_price=stop,
                    last_done=last_done,
                    timestamp=timestamp,
                )
            )
        elif stop is not None and last_done > stop:
            distance = (last_done - stop) / stop if stop else 0.0
            if 0 <= distance <= threshold:
                alerts.append(
                    _alert(
                        card=card,
                        alert_type="stop_approaching",
                        level_name="stop_loss",
                        level_price=stop,
                        last_done=last_done,
                        timestamp=timestamp,
                    )
                )
        if trigger is not None and last_done >= trigger:
            alerts.append(
                _alert(
                    card=card,
                    alert_type="trigger_hit",
                    level_name="trigger_price",
                    level_price=trigger,
                    last_done=last_done,
                    timestamp=timestamp,
                )
            )
        elif trigger is not None and last_done < trigger:
            distance = (trigger - last_done) / trigger if trigger else 0.0
            if 0 <= distance <= threshold:
                alerts.append(
                    _alert(
                        card=card,
                        alert_type="trigger_approaching",
                        level_name="trigger_price",
                        level_price=trigger,
                        last_done=last_done,
                        timestamp=timestamp,
                    )
                )
    return alerts


def format_alerts_markdown(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return "_No active trigger or stop alerts._"
    header = "| Ticker | Name | Alert | Level | Level Price | Last | Δ% | Time |"
    separator = "| --- | --- | --- | --- | ---: | ---: | ---: | --- |"
    lines = [header, separator]
    for alert in alerts:
        lines.append(
            "| {ticker} | {name} | {alert_type} | {level_name} | {level_price:.3f} | "
            "{last_done:.3f} | {distance_pct:+.2f}% | {timestamp} |".format(
                ticker=alert.get("ticker", ""),
                name=alert.get("name", ""),
                alert_type=alert.get("alert_type", ""),
                level_name=alert.get("level_name", ""),
                level_price=float(alert.get("level_price") or 0.0),
                last_done=float(alert.get("last_done") or 0.0),
                distance_pct=float(alert.get("distance_pct") or 0.0),
                timestamp=alert.get("timestamp", ""),
            )
        )
    return "\n".join(lines)


def render_trigger_monitor_markdown(result: dict[str, Any]) -> str:
    cycle_time = clean_text(result.get("cycle_time")) or "n/a"
    active_cards = int(result.get("active_cards_count") or 0)
    quotes_fetched = int(result.get("quotes_fetched") or 0)
    alerts = [a for a in (result.get("alerts") or []) if isinstance(a, dict)]
    by_type: dict[str, int] = {}
    for alert in alerts:
        key = clean_text(alert.get("alert_type")) or "unknown"
        by_type[key] = by_type.get(key, 0) + 1
    lines: list[str] = []
    lines.append(f"# Trigger Monitor Cycle — {cycle_time}")
    lines.append("")
    lines.append(f"- Active trade cards: {active_cards}")
    lines.append(f"- Quotes fetched: {quotes_fetched}")
    lines.append(f"- Alerts: {len(alerts)}")
    if by_type:
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
        lines.append(f"- Breakdown: {breakdown}")
    lines.append("")
    lines.append("## Alerts")
    lines.append("")
    lines.append(format_alerts_markdown(alerts))
    lines.append("")
    return "\n".join(lines)


def run_monitor_cycle(
    package_path: Path,
    longbridge_binary: str = "longbridge",
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    quote_fetcher: Any = None,
) -> dict[str, Any]:
    """Single end-to-end pass: load pool, fetch quotes, emit alerts."""
    cycle_time = datetime.now(UTC).isoformat(timespec="seconds")
    package = json.loads(Path(package_path).expanduser().read_text(encoding="utf-8-sig"))
    cards = extract_active_trade_cards(package)
    longbridge_tickers = sorted({card["longbridge_ticker"] for card in cards if card.get("longbridge_ticker")})
    if quote_fetcher is None:
        quotes = fetch_quotes(longbridge_tickers, longbridge_binary, timeout=timeout)
    else:
        quotes = quote_fetcher(longbridge_tickers)
    alerts = detect_trigger_alerts(cards, quotes)
    return {
        "schema_version": SCHEMA_VERSION,
        "cycle_time": cycle_time,
        "active_cards_count": len(cards),
        "quotes_fetched": len(quotes),
        "alerts": alerts,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a single trigger-monitor cycle against the local stock pool package."
    )
    parser.add_argument("--package-path", required=True, help="Path to local-stock-pool-manager-package.json")
    parser.add_argument("--longbridge-binary", default="longbridge")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS,
                        help="Polling interval in seconds (reserved for future loop use)")
    parser.add_argument("--output", default=None, help="Optional JSON output path for alerts")
    parser.add_argument("--quiet", action="store_true", help="Suppress markdown output to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    package_path = Path(clean_text(args.package_path)).expanduser()
    if not package_path.exists():
        print(f"package not found: {package_path}", file=sys.stderr)
        return 2
    result = run_monitor_cycle(package_path, clean_text(args.longbridge_binary) or "longbridge")
    if args.output:
        output_path = Path(clean_text(args.output)).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.quiet:
        print(format_alerts_markdown(result["alerts"]))
        print(
            f"\ncycle_time={result['cycle_time']} active_cards={result['active_cards_count']} "
            f"quotes_fetched={result['quotes_fetched']} alerts={len(result['alerts'])}"
        )
    return 0


__all__ = [
    "APPROACH_THRESHOLD_PCT",
    "DEFAULT_INTERVAL_SECONDS",
    "SCHEMA_VERSION",
    "detect_trigger_alerts",
    "extract_active_trade_cards",
    "fetch_quotes",
    "format_alerts_markdown",
    "render_trigger_monitor_markdown",
    "main",
    "run_monitor_cycle",
    "to_longbridge_ticker",
]


if __name__ == "__main__":
    raise SystemExit(main())
