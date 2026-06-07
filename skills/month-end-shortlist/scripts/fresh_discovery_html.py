#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import parse_float, safe_dict


__all__ = [
    "format_cny_yi",
    "render_fresh_discovery_sector_status",
    "render_fresh_discovery_status",
]


def format_signed_pct(value: float | None) -> str:
    if value is None:
        return ""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def format_cny_yi(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value / 100000000:.2f}yi"


def render_fresh_discovery_status(package: dict[str, Any]) -> str:
    request = safe_dict(package.get("month_end_request"))
    coverage = safe_dict(package.get("fresh_discovery_coverage"))
    required = request.get("fresh_discovery_required") is True
    if not required and not coverage:
        return ""

    status = clean_text(coverage.get("status")) if coverage else "pending"
    status = status or "pending"
    fresh_count = clean_text(coverage.get("fresh_market_strength_candidate_count", "0")) if coverage else "0"
    candidate_count = clean_text(coverage.get("market_strength_candidate_count", "0")) if coverage else "0"
    universe_count = clean_text(coverage.get("market_strength_universe_count", "0")) if coverage else "0"
    sector_rank_count = clean_text(coverage.get("sector_ranking_count", "0")) if coverage else "0"
    strong_sector_count = clean_text(coverage.get("strong_sector_view_count", "0")) if coverage else "0"
    summary = (
        "Fresh discovery result is attached to this package."
        if coverage
        else "Fresh discovery is required before this review can be treated as a completed opportunity scan."
    )
    return (
        '<section id="fresh-discovery" class="fresh-discovery-status" aria-label="Fresh discovery status">'
        '<div class="section-head">'
        "<h2>Fresh Discovery</h2>"
        f'<span class="status-pill status-{html.escape(status)}">{html.escape(status)}</span>'
        "</div>"
        '<div class="fresh-discovery-body">'
        f"<p>{html.escape(summary)}</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(fresh_count)}</span><span class="metric-label">New names</span></div>'
        f'<div><span class="metric-value">{html.escape(candidate_count)}</span><span class="metric-label">Candidates</span></div>'
        f'<div><span class="metric-value">{html.escape(universe_count)}</span><span class="metric-label">Universe rows</span></div>'
        f'<div><span class="metric-value">{html.escape(sector_rank_count)}</span><span class="metric-label">Sector ranks</span></div>'
        f'<div><span class="metric-value">{html.escape(strong_sector_count)}</span><span class="metric-label">Strong sectors</span></div>'
        "</div>"
        "</div>"
        "</section>"
    )


def render_fresh_discovery_sector_status(package: dict[str, Any]) -> str:
    layer = safe_dict(package.get("fresh_discovery_sector_layer"))
    sectors = layer.get("sector_views")
    if not isinstance(sectors, list) or not sectors:
        return ""
    summary = safe_dict(layer.get("summary"))
    count = clean_text(summary.get("sector_count", len(sectors))) or clean_text(len(sectors))
    rows = []
    for sector in sectors[:8]:
        if not isinstance(sector, dict):
            continue
        sector_name = clean_text(sector.get("sector_name"))
        leader_name = clean_text(sector.get("leader_name"))
        leader_ticker = clean_text(sector.get("leader_ticker"))
        day_pct = format_signed_pct(parse_float(sector.get("day_pct"))) or "n/a"
        rank = clean_text(sector.get("rank")) or "-"
        breadth = clean_text(sector.get("breadth_signal")) or "unknown"
        net_inflow = format_cny_yi(parse_float(sector.get("net_inflow_cny"))) or "n/a"
        rows.append(
            '<div class="sector-leader-item">'
            '<div class="sector-name-cell">'
            f'<span class="overview-ticker">#{html.escape(rank)}</span>'
            f'<span class="overview-name">{html.escape(sector_name)}</span>'
            "</div>"
            '<div class="sector-leader-cell">'
            f'<span class="overview-ticker">{html.escape(leader_ticker)}</span>'
            f'<span class="overview-name">{html.escape(leader_name)}</span>'
            "</div>"
            f'<span class="trigger-distance distance-triggered">{html.escape(day_pct)}</span>'
            f'<span class="bucket-pill">{html.escape(breadth)}</span>'
            f'<span class="metric-label">flow {html.escape(net_inflow)}</span>'
            "</div>"
        )
    if not rows:
        return ""
    return (
        '<section class="fresh-discovery-sector-status new-strong-sectors" aria-label="Fresh discovery sector status">'
        '<div class="section-head">'
        "<h2>New Strong Sectors</h2>"
        f'<span class="status-pill status-covered">{html.escape(count)} sectors</span>'
        "</div>"
        '<div class="fresh-discovery-sector-body">'
        '<p>These sectors and leaders came from the fresh market-strength scan, outside the old/local pool gate.</p>'
        '<div class="sector-leader-list">'
        + "".join(rows)
        + "</div>"
        "</div>"
        "</section>"
    )
