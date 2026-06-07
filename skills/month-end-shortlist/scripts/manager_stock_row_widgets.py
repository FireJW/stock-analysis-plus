#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text, unique_strings
from manager_html_primitives import safe_dict
from manager_pool_merge import normalize_workflow_display_ticker


PLAN_LEVEL_LABELS = {
    "base": "Base",
    "bull": "Bull",
    "bear": "Bear",
    "support": "Support",
    "resistance": "Resistance",
    "target": "Target",
}


def render_plan_level_chips(price_paths: dict[str, Any]) -> str:
    chips: list[str] = []
    for key in ("base", "support", "resistance", "target", "bull", "bear"):
        values = price_paths.get(key)
        if isinstance(values, list) and values:
            rendered = " / ".join(clean_text(item) for item in values if clean_text(item))
        else:
            rendered = clean_text(values)
        if rendered:
            chips.append(
                '<span class="level-chip">'
                f'<span class="level-label">{html.escape(PLAN_LEVEL_LABELS.get(key, key))}</span>'
                f'<span class="level-value">{html.escape(rendered)}</span>'
                "</span>"
            )
    return "".join(chips) if chips else '<span class="muted-text">No imported plan levels</span>'


def render_plan_text_block(label: str, value: str) -> str:
    if not clean_text(value):
        return ""
    return (
        '<div class="plan-block">'
        f'<span class="plan-label">{html.escape(label)}</span>'
        f'<div class="plan-text">{html.escape(clean_text(value))}</div>'
        "</div>"
    )


def render_edit_textarea(field: str, value: Any, *, css_class: str = "") -> str:
    class_attr = f' class="{html.escape(css_class)}"' if css_class else ""
    return f'<textarea data-field="{html.escape(field)}"{class_attr}>{html.escape(clean_text(value))}</textarea>'


def detail_row_id(ticker: Any) -> str:
    normalized = normalize_workflow_display_ticker(ticker)
    if not re.fullmatch(r"(?:\d{6}\.(?:SH|SZ|BJ)|[A-Z0-9]{1,12}\.[A-Z]{2,5})", normalized):
        return "stock-row-manual"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", normalized).strip("-")
    return f"stock-row-{safe or 'manual'}"


def render_trigger_distance_badge(plan: dict[str, Any]) -> str:
    distance = safe_dict(plan.get("trigger_distance"))
    if not distance:
        return ""
    class_name = clean_text(distance.get("class_name")) or "distance-far"
    display = clean_text(distance.get("display")) or clean_text(distance.get("label"))
    pct = clean_text(distance.get("pct"))
    label = display or (f"{pct}%" if pct else "Trigger distance")
    return (
        f'<span class="trigger-distance {html.escape(class_name)}" data-metric="trigger_distance">'
        f"{html.escape(label)}</span>"
    )


def render_evidence_drawer(stock: dict[str, Any]) -> str:
    plan = safe_dict(stock.get("plan_snapshot"))
    setup_reasons = clean_string_list(plan.get("setup_reasons"))
    if not setup_reasons:
        setup_reasons = [
            item.removeprefix("setup:")
            for item in clean_string_list(stock.get("strategy_tags"))
            if item.startswith("setup:")
        ]
    evidence_items = setup_reasons + clean_string_list(plan.get("tier_tags")) + clean_string_list(plan.get("theme_tags"))
    if clean_text(plan.get("chain_name")):
        evidence_items.append(clean_text(plan.get("chain_name")))
    if not evidence_items and clean_text(stock.get("notes")):
        evidence_items.append(clean_text(stock.get("notes")))
    if not evidence_items:
        evidence_items.append("No structured evidence imported")
    rendered = "".join(f"<li>{html.escape(item)}</li>" for item in unique_strings(evidence_items))
    return (
        '<details class="evidence-drawer">'
        "<summary>Evidence</summary>"
        f"<ul>{rendered}</ul>"
        "</details>"
    )


__all__ = [
    "PLAN_LEVEL_LABELS",
    "detail_row_id",
    "render_edit_textarea",
    "render_evidence_drawer",
    "render_plan_level_chips",
    "render_plan_text_block",
    "render_trigger_distance_badge",
]
