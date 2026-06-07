#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import safe_dict
from manager_market_snapshot import render_market_snapshot
from manager_stock_row_widgets import (
    detail_row_id,
    render_edit_textarea,
    render_evidence_drawer,
    render_plan_level_chips,
    render_plan_text_block,
    render_trigger_distance_badge,
)
from manager_ui_summary import PLAN_BUCKET_LABELS


def render_plan_overview(local_stock_pool: dict[str, Any]) -> str:
    rows: list[str] = []
    for stock in local_stock_pool.get("stocks", []):
        if not isinstance(stock, dict):
            continue
        ticker = clean_text(stock.get("ticker"))
        if not ticker:
            continue
        plan = safe_dict(stock.get("plan_snapshot"))
        trade_card = safe_dict(plan.get("trade_card"))
        bucket = PLAN_BUCKET_LABELS.get(clean_text(plan.get("bucket")), clean_text(plan.get("bucket")) or "Manual")
        action = clean_text(trade_card.get("watch_action")) or clean_text(stock.get("notes"))
        invalidation = clean_text(trade_card.get("invalidation"))
        market_summary = render_market_snapshot(safe_dict(plan.get("market_snapshot")), compact=True)
        price_span = f'<span class="overview-price">{html.escape(market_summary)}</span>' if market_summary else ""
        level_chips = render_plan_level_chips(safe_dict(plan.get("price_paths")))
        trigger_badge = render_trigger_distance_badge(plan)
        rows.append(
            '<div class="overview-row" role="button" tabindex="0" '
            f'data-action="focus-row" data-target="{html.escape(detail_row_id(ticker))}">'
            '<div class="overview-identity">'
            f'<span class="overview-ticker">{html.escape(ticker)}</span>'
            f'<span class="overview-name">{html.escape(clean_text(stock.get("name")) or ticker)}</span>'
            f"{price_span}"
            "</div>"
            f'<span class="bucket-pill overview-bucket">{html.escape(bucket)}</span>'
            f'<div class="overview-action">{html.escape(action or "-")}</div>'
            f'<div class="overview-risk">{html.escape(invalidation or "-")}</div>'
            f'<div class="overview-levels">{trigger_badge}{level_chips}</div>'
            "</div>"
        )
    if not rows:
        return ""
    return '<div class="plan-overview">' + "".join(rows) + "</div>"


def stock_table_rows(local_stock_pool: dict[str, Any]) -> str:
    rows: list[str] = []
    for stock in local_stock_pool.get("stocks", []):
        if not isinstance(stock, dict):
            continue
        plan = safe_dict(stock.get("plan_snapshot"))
        trade_card = safe_dict(plan.get("trade_card"))
        plan_bucket = PLAN_BUCKET_LABELS.get(clean_text(plan.get("bucket")), clean_text(plan.get("bucket")))
        plan_action = clean_text(trade_card.get("watch_action"))
        plan_invalidation = clean_text(trade_card.get("invalidation"))
        market_summary = render_market_snapshot(safe_dict(plan.get("market_snapshot")))
        plan_levels = render_plan_level_chips(safe_dict(plan.get("price_paths")))
        trigger_badge = render_trigger_distance_badge(plan)
        plan_panel = (
            '<div class="plan-panel">'
            f'<span class="bucket-pill">{html.escape(plan_bucket or "Manual")}</span>'
            f"{trigger_badge}"
            f'{render_plan_text_block("Market", market_summary)}'
            f'{render_plan_text_block("Action", plan_action)}'
            f'{render_plan_text_block("Invalidation", plan_invalidation)}'
            f'<div class="plan-block"><span class="plan-label">Plan Levels</span><div class="level-list">{plan_levels}</div></div>'
            f"{render_evidence_drawer(stock)}"
            "</div>"
        )
        rows.append(
            f'<tr class="stock-row" id="{html.escape(detail_row_id(stock.get("ticker")))}" tabindex="-1">'
            '<td class="identity-cell">'
            f'<input data-field="ticker" value="{html.escape(clean_text(stock.get("ticker")))}">'
            f'<input data-field="name" value="{html.escape(clean_text(stock.get("name")))}">'
            "</td>"
            '<td class="classification-cell">'
            f'<label class="cell-label">Groups{render_edit_textarea("groups", ", ".join(stock.get("groups") or []), css_class="short-textarea")}</label>'
            f'<label class="cell-label">Tags{render_edit_textarea("tags", ", ".join(stock.get("tags") or []), css_class="short-textarea")}</label>'
            f'<label class="cell-label">Strategy{render_edit_textarea("strategy_tags", ", ".join(stock.get("strategy_tags") or []), css_class="strategy-textarea")}</label>'
            "</td>"
            f'<td class="plan-cell">{plan_panel}</td>'
            f'<td class="notes-cell">{render_edit_textarea("notes", clean_text(stock.get("notes")), css_class="notes-textarea")}</td>'
            '<td class="row-actions"><button type="button" class="icon-button danger" data-action="remove" title="Remove">-</button></td>'
            "</tr>"
        )
    return "\n".join(rows)
