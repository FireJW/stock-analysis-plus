#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from typing import Any

from local_stock_pool_runtime import clean_text, normalize_local_daily_bars_source


def build_month_end_request(
    local_stock_pool: dict[str, Any],
    *,
    tdx_vipdoc_path: str = "",
    target_date: str = "",
    analysis_time: str = "",
    fresh_discovery_required: bool = False,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "template_name": "month_end_shortlist",
        "target_date": clean_text(target_date) or date.today().isoformat(),
        "local_stock_pool": local_stock_pool,
    }
    if clean_text(analysis_time):
        request["analysis_time"] = clean_text(analysis_time)
    source = normalize_local_daily_bars_source(
        {"tdx_vipdoc_path": tdx_vipdoc_path}
        if clean_text(tdx_vipdoc_path)
        else {}
    )
    if source:
        request["local_daily_bars_source"] = source
    if fresh_discovery_required:
        request["fresh_discovery_required"] = True
        request["fresh_discovery_required_sessions"] = ["intraday", "postclose"]
        request["trading_plan_pool_role"] = "baseline_context_only"
        request["market_strength_universe_limit"] = 200
        request["sector_rank_limit"] = 30
    return request


__all__ = ["build_month_end_request"]
