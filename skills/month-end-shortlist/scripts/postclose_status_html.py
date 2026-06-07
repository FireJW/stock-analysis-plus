#!/usr/bin/env python3
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import parse_float, safe_dict


__all__ = [
    "render_postclose_observation_status",
    "render_postclose_review_status",
]


def _format_signed_pct(value: float | None) -> str:
    if value is None:
        return ""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _render_file_link(path_text: Any, label: str) -> str:
    path = clean_text(path_text)
    if not path:
        return ""
    try:
        href = Path(path).expanduser().resolve().as_uri()
    except (OSError, ValueError):
        return ""
    return (
        '<a class="artifact-link" href="'
        f'{html.escape(href)}" target="_blank" rel="noreferrer">'
        f"{html.escape(label)}</a>"
    )


def render_postclose_review_status(package: dict[str, Any]) -> str:
    review = safe_dict(package.get("postclose_review"))
    if not review:
        return ""
    summary = safe_dict(review.get("summary"))
    total_reviewed = clean_text(summary.get("total_reviewed", "0")) or "0"
    missed = clean_text(summary.get("missed", "0")) or "0"
    too_aggressive = clean_text(summary.get("too_aggressive", "0")) or "0"
    trade_date = clean_text(review.get("trade_date")) or clean_text(safe_dict(package.get("month_end_request")).get("target_date"))
    artifact_links = "".join(
        link
        for link in (
            _render_file_link(package.get("shortlist_result_path"), "month-end-shortlist-result.json"),
            _render_file_link(package.get("shortlist_report_path"), "month-end-shortlist-report.md"),
            _render_file_link(package.get("postclose_review_path"), "postclose-review.json"),
            _render_file_link(package.get("postclose_report_path"), "postclose-review.md"),
        )
        if link
    )
    artifact_link_block = f'<div class="artifact-links">{artifact_links}</div>' if artifact_links else ""
    return (
        '<section id="postclose-review" class="postclose-review-status" aria-label="Postclose review status">'
        '<div class="section-head">'
        "<h2>Postclose Review</h2>"
        f'<span class="status-pill status-covered">{html.escape(total_reviewed)} reviewed</span>'
        "</div>"
        '<div class="postclose-review-body">'
        f'<p>Postclose artifact is attached for {html.escape(trade_date or "the target session")}.</p>'
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(total_reviewed)}</span><span class="metric-label">Reviewed</span></div>'
        f'<div><span class="metric-value">{html.escape(missed)}</span><span class="metric-label">Missed</span></div>'
        f'<div><span class="metric-value">{html.escape(too_aggressive)}</span><span class="metric-label">Too aggressive</span></div>'
        "</div>"
        f"{artifact_link_block}"
        "</div>"
        "</section>"
    )


def render_postclose_observation_status(package: dict[str, Any]) -> str:
    layer = safe_dict(package.get("postclose_observation_layer"))
    candidates = layer.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    summary = safe_dict(layer.get("summary"))
    count = clean_text(summary.get("loose_observation_count", len(candidates))) or clean_text(len(candidates))
    items = []
    for candidate in candidates[:8]:
        if not isinstance(candidate, dict):
            continue
        ticker = clean_text(candidate.get("ticker"))
        name = clean_text(candidate.get("name")) or ticker
        actual_return = parse_float(candidate.get("actual_return_pct"))
        adjustment = clean_text(candidate.get("adjustment")) or "observe"
        items.append(
            '<div class="observation-item">'
            '<div class="observation-name">'
            f'<span class="overview-ticker">{html.escape(ticker)}</span>'
            f'<span class="overview-name">{html.escape(name)}</span>'
            "</div>"
            f'<span class="trigger-distance distance-triggered">{html.escape(_format_signed_pct(actual_return) or "n/a")}</span>'
            f'<span class="bucket-pill">{html.escape(adjustment)}</span>'
            "</div>"
        )
    if not items:
        return ""
    return (
        '<section class="postclose-observation-status" aria-label="Postclose loose observation status">'
        '<div class="section-head">'
        "<h2>Loose Observation</h2>"
        f'<span class="status-pill status-covered">{html.escape(count)} names</span>'
        "</div>"
        '<div class="postclose-observation-body">'
        '<p>These names came from missed-opportunity review, not from the strict shortlist gate.</p>'
        '<div class="observation-list">'
        + "".join(items)
        + "</div>"
        "</div>"
        "</section>"
    )
