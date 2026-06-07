#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import parse_float, safe_dict
from manager_pool_merge import normalize_workflow_display_ticker


def build_fresh_discovery_sector_layer(shortlist_result: dict[str, Any]) -> dict[str, Any]:
    sector_views = shortlist_result.get("sector_views")
    if not isinstance(sector_views, list):
        sector_views = []
    normalized_sector_views: list[dict[str, Any]] = []
    for index, item in enumerate(sector_views):
        if not isinstance(item, dict):
            continue
        sector_name = clean_text(item.get("sector_name"))
        leader_ticker = normalize_workflow_display_ticker(item.get("leader_ticker"))
        leader_name = clean_text(item.get("leader_name")) or leader_ticker
        if not sector_name and not leader_ticker:
            continue
        normalized_sector_views.append(
            {
                "sector_name": sector_name or "Unknown sector",
                "sector_type": clean_text(item.get("sector_type")),
                "source": clean_text(item.get("source")),
                "rank": parse_float(item.get("rank")),
                "day_pct": parse_float(item.get("day_pct")),
                "net_inflow_cny": parse_float(item.get("net_inflow_cny")),
                "leader_name": leader_name,
                "leader_ticker": leader_ticker,
                "breadth_signal": clean_text(item.get("breadth_signal")),
                "_source_order": index,
            }
        )
    normalized_sector_views.sort(
        key=lambda row: (
            parse_float(row.get("rank")) if parse_float(row.get("rank")) is not None else 999.0,
            parse_float(row.get("_source_order")) if parse_float(row.get("_source_order")) is not None else 999.0,
        )
    )
    for row in normalized_sector_views:
        row.pop("_source_order", None)
    leader_count = len({row.get("leader_ticker") for row in normalized_sector_views if clean_text(row.get("leader_ticker"))})
    return {
        "summary": {
            "sector_count": len(normalized_sector_views),
            "leader_count": leader_count,
            "source": "sector_views",
        },
        "usage_boundary": "fresh market-strength sector layer only; does not override strict shortlist gates.",
        "sector_views": normalized_sector_views[:10],
    }


def fresh_discovery_count(coverage: dict[str, Any], key: str) -> int:
    value = parse_float(coverage.get(key))
    return int(value) if value is not None and value > 0 else 0


def normalize_reused_fresh_discovery_coverage(shortlist_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(shortlist_result, dict):
        return {}
    coverage = safe_dict(shortlist_result.get("fresh_discovery_coverage"))
    if not coverage:
        return shortlist_result
    status = clean_text(coverage.get("status")).lower()
    strong_sector_view_count = fresh_discovery_count(coverage, "strong_sector_view_count")
    sector_view_count = fresh_discovery_count(coverage, "sector_view_count")
    sector_ranking_count = fresh_discovery_count(coverage, "sector_ranking_count")
    fresh_candidate_count = fresh_discovery_count(coverage, "fresh_market_strength_candidate_count")
    fetch_error = clean_text(coverage.get("market_strength_fetch_error") or coverage.get("universe_fetch_error"))
    has_sector_fallback = (
        fetch_error
        and fresh_candidate_count == 0
        and sector_ranking_count > 0
        and sector_view_count > 0
        and strong_sector_view_count > 0
    )
    if status not in {"blocked", "sector_only"} or not has_sector_fallback:
        return shortlist_result
    normalized_result = dict(shortlist_result)
    normalized_coverage = dict(coverage)
    normalized_coverage["status"] = "sector_only"
    normalized_coverage["warning"] = "fresh_discovery_sector_only_no_stock_level_candidates"
    normalized_result["fresh_discovery_coverage"] = normalized_coverage
    return normalized_result


__all__ = [
    "build_fresh_discovery_sector_layer",
    "fresh_discovery_count",
    "normalize_reused_fresh_discovery_coverage",
]
