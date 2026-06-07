#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

from local_stock_pool_runtime import clean_text, normalize_local_stock_pool, unique_strings


def normalize_workflow_display_ticker(value: Any) -> str:
    ticker = clean_text(value).upper().replace(" ", "")
    if not ticker:
        return ""
    if ticker.endswith(".SH") or ticker.endswith(".SS"):
        return ticker[:-3] + ".SH"
    if ticker.endswith(".XSHG"):
        return ticker[:-5] + ".SH"
    if ticker.endswith(".XSHE"):
        return ticker[:-5] + ".SZ"
    if ticker.endswith(".SZ") or ticker.endswith(".BJ"):
        return ticker
    digits = "".join(ch for ch in ticker if ch.isdigit())
    if len(digits) == 6:
        if digits.startswith(("6", "9")):
            return f"{digits}.SH"
        if digits.startswith(("8", "4")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"
    return ticker


def normalize_workflow_display_ticker_text(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    return re.sub(r"(?<![A-Z0-9])(\d{6})\.SS\b", r"\1.SH", text, flags=re.IGNORECASE)


def merge_note_text(*values: Any) -> str:
    notes: list[str] = []
    for value in values:
        for item in clean_text(value).split("|"):
            text = clean_text(item)
            if text and text not in notes:
                notes.append(text)
    return " | ".join(notes)


def is_placeholder_name(value: Any) -> bool:
    text = clean_text(value)
    return not text or bool(re.fullmatch(r"\?+", text))


def merge_stock_pools(base_pool: dict[str, Any], imported_pool: dict[str, Any]) -> dict[str, Any]:
    if not base_pool:
        return imported_pool
    if not imported_pool:
        return base_pool
    by_ticker: dict[str, dict[str, Any]] = {}
    for stock in base_pool.get("stocks", []):
        if not isinstance(stock, dict):
            continue
        ticker_key = normalize_workflow_display_ticker(stock.get("ticker") or stock.get("code") or stock.get("symbol"))
        if ticker_key:
            by_ticker[ticker_key] = dict(stock)
    for stock in imported_pool.get("stocks", []):
        if not isinstance(stock, dict):
            continue
        ticker_key = normalize_workflow_display_ticker(stock.get("ticker") or stock.get("code") or stock.get("symbol"))
        if not ticker_key:
            continue
        if ticker_key not in by_ticker:
            by_ticker[ticker_key] = dict(stock)
            continue
        current = by_ticker[ticker_key]
        imported_name = clean_text(stock.get("name"))
        if imported_name and is_placeholder_name(current.get("name")):
            current["name"] = imported_name
        current["groups"] = unique_strings(list(current.get("groups") or []) + list(stock.get("groups") or []))
        current["tags"] = unique_strings(list(current.get("tags") or []) + list(stock.get("tags") or []))
        current["strategy_tags"] = unique_strings(
            list(current.get("strategy_tags") or []) + list(stock.get("strategy_tags") or [])
        )
        merged_notes = merge_note_text(current.get("notes"), stock.get("notes"))
        if merged_notes:
            current["notes"] = merged_notes
        if isinstance(stock.get("plan_snapshot"), dict):
            current["plan_snapshot"] = stock["plan_snapshot"]
        current["source"] = clean_text(current.get("source")) or "local_stock_pool"
    return normalize_local_stock_pool(
        {
            "name": clean_text(base_pool.get("name")) or clean_text(imported_pool.get("name")) or "local_stock_pool",
            "stocks": list(by_ticker.values()),
            "groups": list(base_pool.get("groups") or []),
            "strategy_rules": list(base_pool.get("strategy_rules") or []),
        }
    )


__all__ = [
    "is_placeholder_name",
    "merge_note_text",
    "merge_stock_pools",
    "normalize_workflow_display_ticker",
    "normalize_workflow_display_ticker_text",
]
