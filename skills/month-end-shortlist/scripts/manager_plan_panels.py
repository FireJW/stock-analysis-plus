#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_string_list
from manager_html_primitives import safe_dict


def render_ticker_list(tickers: list[str]) -> str:
    if not tickers:
        return '<span class="muted-text">None</span>'
    return " ".join(f'<span class="ticker-chip">{html.escape(ticker)}</span>' for ticker in tickers)


def render_plan_change_summary(ui_summary: dict[str, Any]) -> str:
    changes = safe_dict(ui_summary.get("changes"))
    if changes.get("no_previous_baseline"):
        detail = '<span class="muted-text">No previous baseline supplied</span>'
    else:
        detail = (
            '<div class="change-groups">'
            f'<div><span class="plan-label">Added</span>{render_ticker_list(clean_string_list(changes.get("added")))}</div>'
            f'<div><span class="plan-label">Retained</span>{render_ticker_list(clean_string_list(changes.get("retained")))}</div>'
            f'<div><span class="plan-label">Removed</span>{render_ticker_list(clean_string_list(changes.get("removed")))}</div>'
            "</div>"
        )
    return (
        '<div class="plan-change-summary">'
        '<span class="plan-label">Changes vs previous plan</span>'
        f"{detail}"
        "</div>"
    )


def render_execution_checklist(ui_summary: dict[str, Any]) -> str:
    items = (
        "Confirm trigger-distance state before opening or adding.",
        "Respect invalidation levels; do not average down after failure.",
        "Check theme strength, volume, and market breadth before execution.",
        "Review evidence drawer for why each stock stayed on the list.",
        "Export request only after manual edits are intentional.",
    )
    rendered_items = "".join(f"<li>{html.escape(item)}</li>" for item in items)
    return (
        '<div class="execution-checklist">'
        '<div class="section-head"><h2>Execution Checklist</h2>'
        '<span class="status">Execution guardrails</span></div>'
        f"<ol>{rendered_items}</ol>"
        "</div>"
    )


__all__ = [
    "render_execution_checklist",
    "render_plan_change_summary",
    "render_ticker_list",
]
