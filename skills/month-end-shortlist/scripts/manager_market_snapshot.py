#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import parse_float


def format_signed_pct(value: float | None) -> str:
    if value is None:
        return ""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def market_change_pct(market_snapshot: dict[str, Any]) -> float | None:
    explicit = parse_float(market_snapshot.get("change_pct"))
    if explicit is not None:
        return explicit
    last = parse_float(market_snapshot.get("last"))
    prev_close = parse_float(market_snapshot.get("prev_close"))
    if last is None or prev_close in (None, 0):
        return None
    return (last - prev_close) / prev_close * 100


def render_market_snapshot(market_snapshot: dict[str, Any], *, compact: bool = False) -> str:
    if not market_snapshot:
        return ""
    last = clean_text(market_snapshot.get("last"))
    change_pct = format_signed_pct(market_change_pct(market_snapshot))
    high = clean_text(market_snapshot.get("high"))
    low = clean_text(market_snapshot.get("low"))
    source = clean_text(market_snapshot.get("source"))
    delay = clean_text(market_snapshot.get("delay") or market_snapshot.get("data_delay"))
    if compact:
        parts = [item for item in [last, change_pct] if item]
        return " ".join(parts)
    detail_parts = []
    if last:
        detail_parts.append(f"Last {last}")
    if change_pct:
        detail_parts.append(change_pct)
    if high or low:
        detail_parts.append(f"H/L {high or '-'} / {low or '-'}")
    if source:
        detail_parts.append(source)
    if delay:
        detail_parts.append(delay)
    return " | ".join(detail_parts)


__all__ = [
    "format_signed_pct",
    "market_change_pct",
    "render_market_snapshot",
]
