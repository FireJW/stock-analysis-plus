#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_decision_overview import render_decision_overview
from manager_decision_rail import render_decision_rail
from manager_html_primitives import safe_dict
from manager_summary_directory import render_summary_directory


def render_decision_summary(
    ui_summary: dict[str, Any], *, target_date: str, analysis_time: str, package: dict[str, Any] | None = None
) -> str:
    package = safe_dict(package)
    overview = render_decision_overview(ui_summary, package)
    decision_rail = render_decision_rail(ui_summary, package)
    directory = render_summary_directory(package)
    meta = (
        '<div class="summary-meta">'
        f'<span class="summary-meta-chip">Target {html.escape(clean_text(target_date) or "Unscheduled")}</span>'
        f'<span class="summary-meta-chip">Snapshot {html.escape(clean_text(analysis_time) or "No analysis time")}</span>'
        "</div>"
    )
    return (
        '<section class="decision-summary" aria-label="Decision summary">'
        '<div class="section-head">'
        "<h2>Decision Summary</h2>"
        f'<span class="status">{html.escape(clean_text(target_date) or "Unscheduled")}</span>'
        "</div>"
        '<div class="summary-body">'
        '<div class="summary-copy">'
        "<strong>Next-session decision rail</strong>"
        f"{overview}"
        f"{decision_rail}"
        f"{meta}"
        "</div>"
        f"{directory}"
        "</div>"
        "</section>"
    )


__all__ = ["render_decision_summary"]
