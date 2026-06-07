#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import parse_float, safe_dict, safe_list
from manager_pool_merge import normalize_workflow_display_ticker


def build_postclose_observation_layer(postclose_review: dict[str, Any]) -> dict[str, Any]:
    reviewed = postclose_review.get("candidates_reviewed")
    candidates_by_ticker: dict[str, dict[str, Any]] = {}
    if not isinstance(reviewed, list):
        reviewed = []
    for item in reviewed:
        if not isinstance(item, dict) or clean_text(item.get("judgment")) != "missed_opportunity":
            continue
        ticker = normalize_workflow_display_ticker(item.get("ticker"))
        if not ticker:
            continue
        actual_return_pct = parse_float(item.get("actual_return_pct"))
        candidate = {
            "ticker": ticker,
            "name": clean_text(item.get("name")) or ticker,
            "actual_return_pct": actual_return_pct,
            "plan_action": clean_text(item.get("plan_action")),
            "intraday_structure": clean_text(item.get("intraday_structure")),
            "judgment": "missed_opportunity",
            "adjustment": clean_text(item.get("adjustment")) or "upgrade",
            "priority_delta": parse_float(item.get("priority_delta")),
        }
        existing = candidates_by_ticker.get(ticker)
        existing_return = parse_float(existing.get("actual_return_pct")) if existing else None
        if existing is None or (actual_return_pct is not None and (existing_return is None or actual_return_pct > existing_return)):
            candidates_by_ticker[ticker] = candidate

    candidates = sorted(
        candidates_by_ticker.values(),
        key=lambda row: parse_float(row.get("actual_return_pct")) if parse_float(row.get("actual_return_pct")) is not None else -999.0,
        reverse=True,
    )
    summary = safe_dict(postclose_review.get("summary"))
    return {
        "summary": {
            "loose_observation_count": len(candidates),
            "source_judgment": "missed_opportunity",
            "reviewed_count": parse_float(summary.get("total_reviewed")),
            "missed_count": parse_float(summary.get("missed")),
        },
        "usage_boundary": "postclose review observation layer only; does not override strict shortlist gates.",
        "candidates": candidates,
    }


def _postclose_review_bucket_for_pool_stock(stock: dict[str, Any]) -> str:
    plan = safe_dict(stock.get("plan_snapshot"))
    bucket = clean_text(plan.get("bucket") or stock.get("bucket")).lower()
    if bucket in {"top_picks", "directly_actionable"}:
        return "top_picks"
    if "risk" in bucket or "blocked" in bucket:
        return "diagnostic_scorecard"
    if "near" in bucket:
        return "near_miss_candidates"
    return "priority_watchlist"


def _postclose_review_action_for_pool_stock(stock: dict[str, Any]) -> str:
    plan = safe_dict(stock.get("plan_snapshot"))
    bucket = clean_text(plan.get("bucket") or stock.get("bucket")).lower()
    trade_card = safe_dict(plan.get("trade_card"))
    action_text = " ".join(
        clean_text(value).lower()
        for value in (
            trade_card.get("watch_action"),
            trade_card.get("positioning"),
            plan.get("entry_list_decision"),
            plan.get("entry_list_gate_status"),
            bucket,
        )
        if clean_text(value)
    )
    if any(token in action_text for token in ("no_add", "no add", "no_action", "no action", "no execution", "risk_watch")):
        return "no_action"
    if bucket in {"top_picks", "directly_actionable"} and "watchlist_only" not in action_text and "confirmation" not in action_text:
        return "qualified"
    return "watch"


def _postclose_review_market_snapshot_for_pool_stock(stock: dict[str, Any]) -> dict[str, Any]:
    plan = safe_dict(stock.get("plan_snapshot"))
    market = safe_dict(plan.get("market_snapshot"))
    if not market:
        market = safe_dict(stock.get("market_snapshot"))
    return market


def _postclose_review_row_from_pool_stock(stock: dict[str, Any]) -> dict[str, Any]:
    ticker = normalize_workflow_display_ticker(
        stock.get("ticker") or safe_dict(stock.get("plan_snapshot")).get("ticker")
    )
    if not ticker:
        return {}
    plan = safe_dict(stock.get("plan_snapshot"))
    market = _postclose_review_market_snapshot_for_pool_stock(stock)
    close = market.get("last")
    if close in (None, ""):
        close = market.get("last_done")
    if close in (None, ""):
        close = market.get("close")
    prev_close = market.get("prev_close")
    if prev_close in (None, ""):
        prev_close = market.get("pre_close")
    if close in (None, "") or prev_close in (None, ""):
        return {}
    trade_card = safe_dict(plan.get("trade_card"))
    row = {
        "ticker": ticker,
        "name": clean_text(stock.get("name") or plan.get("name")) or ticker,
        "midday_action": _postclose_review_action_for_pool_stock(stock),
        "close": close,
        "prev_close": prev_close,
        "price": close,
        "pre_close": prev_close,
        "high": market.get("high"),
        "low": market.get("low"),
        "source_bucket": clean_text(plan.get("bucket")) or clean_text(stock.get("bucket")),
        "trade_card": trade_card,
        "plan_snapshot": plan,
    }
    return {key: value for key, value in row.items() if value not in ("", None, [], {})}


def build_postclose_review_input_from_current_pool(
    shortlist_result: dict[str, Any],
    package: dict[str, Any],
) -> dict[str, Any]:
    """Use the final displayed pool as the postclose review target when it has fresh quotes."""
    pool = safe_dict(package.get("local_stock_pool"))
    rows_by_bucket: dict[str, list[dict[str, Any]]] = {
        "top_picks": [],
        "priority_watchlist": [],
        "near_miss_candidates": [],
        "diagnostic_scorecard": [],
    }
    for stock in safe_list(pool.get("stocks")):
        if not isinstance(stock, dict):
            continue
        row = _postclose_review_row_from_pool_stock(stock)
        if not row:
            continue
        rows_by_bucket[_postclose_review_bucket_for_pool_stock(stock)].append(row)
    if not any(rows_by_bucket.values()):
        return shortlist_result

    review_input = dict(shortlist_result)
    for bucket, rows in rows_by_bucket.items():
        review_input[bucket] = rows
    review_input.pop("entry_list_screening", None)
    review_input.pop("entry_list_earnings_overlay", None)
    review_input["postclose_review_source"] = "current_local_stock_pool"
    review_input["postclose_review_source_note"] = (
        "Postclose review targets the final displayed stock pool because the cached shortlist can be older than the current plan overlay."
    )
    if "fresh_discovery_coverage" not in review_input and isinstance(package.get("fresh_discovery_coverage"), dict):
        review_input["fresh_discovery_coverage"] = package["fresh_discovery_coverage"]
    return review_input


__all__ = [
    "build_postclose_observation_layer",
    "build_postclose_review_input_from_current_pool",
]
