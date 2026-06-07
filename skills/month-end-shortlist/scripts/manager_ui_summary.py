#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text
from manager_html_primitives import safe_dict
from manager_pool_merge import normalize_workflow_display_ticker


PLAN_BUCKET_LABELS = {
    "top_picks": "Top Picks",
    "directly_actionable": "Directly Actionable",
    "priority_watchlist": "Priority Watch",
    "near_miss_candidates": "Near Miss",
    "diagnostic_scorecard": "Diagnostic",
}


def stock_bucket_label(stock: dict[str, Any]) -> str:
    plan = safe_dict(stock.get("plan_snapshot"))
    bucket = clean_text(plan.get("bucket"))
    if bucket:
        return PLAN_BUCKET_LABELS.get(bucket, bucket)
    groups = clean_string_list(stock.get("groups"))
    for label in PLAN_BUCKET_LABELS.values():
        if label in groups:
            return label
    return "Manual"


def pool_tickers(pool: dict[str, Any]) -> list[str]:
    tickers: list[str] = []
    for stock in pool.get("stocks", []) if isinstance(pool.get("stocks"), list) else []:
        if not isinstance(stock, dict):
            continue
        ticker = normalize_workflow_display_ticker(stock.get("ticker"))
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def build_ui_summary(
    final_pool: dict[str, Any],
    previous_pool: dict[str, Any],
    imported_pool: dict[str, Any],
) -> dict[str, Any]:
    stocks = [stock for stock in final_pool.get("stocks", []) if isinstance(stock, dict)]
    bucket_counts = {label: 0 for label in PLAN_BUCKET_LABELS.values()}
    for stock in stocks:
        label = stock_bucket_label(stock)
        bucket_counts[label] = bucket_counts.get(label, 0) + 1

    previous_tickers = pool_tickers(previous_pool)
    imported_tickers = pool_tickers(imported_pool)
    has_previous_baseline = bool(previous_tickers)
    if has_previous_baseline and imported_tickers:
        added = [ticker for ticker in imported_tickers if ticker not in previous_tickers]
        retained = [ticker for ticker in imported_tickers if ticker in previous_tickers]
        removed = [ticker for ticker in previous_tickers if ticker not in imported_tickers]
    else:
        added = []
        retained = []
        removed = []

    return {
        "total_count": len(stocks),
        "bucket_counts": bucket_counts,
        "changes": {
            "added": added,
            "retained": retained,
            "removed": removed,
            "no_previous_baseline": not has_previous_baseline,
        },
    }


def bucket_counts_for_pool(local_stock_pool: dict[str, Any]) -> dict[str, int]:
    bucket_counts = {label: 0 for label in PLAN_BUCKET_LABELS.values()}
    for stock in local_stock_pool.get("stocks", []) if isinstance(local_stock_pool.get("stocks"), list) else []:
        if not isinstance(stock, dict):
            continue
        label = stock_bucket_label(stock)
        bucket_counts[label] = bucket_counts.get(label, 0) + 1
    return bucket_counts


def summary_count_text(value: Any, default: str = "0") -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else str(value)
    text = clean_text(value)
    return text if text else default


def count_noun_text(value: Any, singular: str, plural: str | None = None, default: str = "0") -> str:
    plural_text = plural or f"{singular}s"
    count_text = summary_count_text(value, default)
    try:
        count_value = float(count_text.replace(",", ""))
    except ValueError:
        count_value = 0.0 if not count_text else 2.0
    noun = singular if count_value == 1 else plural_text
    return f"{count_text} {noun}"


__all__ = [
    "PLAN_BUCKET_LABELS",
    "build_ui_summary",
    "bucket_counts_for_pool",
    "count_noun_text",
    "pool_tickers",
    "stock_bucket_label",
    "summary_count_text",
]
