#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text
from manager_calendar_scope import render_calendar_scope_chips
from manager_html_primitives import display_status_text, safe_list, title_case_display_text


def calendar_event_time_label(value: Any) -> str:
    text = clean_text(value).lower()
    if not text:
        return ""
    if "鐩樺悗" in text:
        return "盘后"
    if "鐩樺墠" in text:
        return "盘前"
    if "鐩樹腑" in text:
        return "盘中"
    if any(token in text for token in ("after_market", "after close", "after_close", "postclose", "afterhours", "after hours")):
        return "盘后"
    if any(token in text for token in ("before_market", "pre-market", "premarket", "preopen", "pre-open")):
        return "盘前"
    if any(token in text for token in ("intraday", "during_market", "market hours")):
        return "盘中"
    return clean_text(value)


def event_beneficiary_labels(stocks: list[Any]) -> list[str]:
    labels: list[str] = []
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        ticker = clean_text(stock.get("ticker"))
        name = clean_text(stock.get("name"))
        label = ticker
        if name and name != ticker:
            label = f"{ticker} {name}" if ticker else name
        elif not label:
            label = name
        if not label:
            continue
        match_fields = ", ".join(clean_string_list(stock.get("match_fields")))
        matched_terms = ", ".join(clean_string_list(stock.get("matched_terms")))
        detail_parts = [part for part in [match_fields, matched_terms] if part]
        if detail_parts:
            label = f"{label} ({' | '.join(detail_parts)})"
        labels.append(label)
    return labels


def render_calendar_desk_list(events: list[dict[str, Any]], *, kind: str) -> str:
    if not events:
        return ""
    rows: list[str] = []
    for row in events[:8]:
        event_date = clean_text(row.get("event_date"))
        time_label = calendar_event_time_label(row.get("time")) or "unscheduled"
        importance = title_case_display_text(row.get("importance"), "Medium")
        importance_label = f"{importance} importance"
        source = clean_text(row.get("source")) or "source pending"
        if kind == "earnings":
            title = clean_text(row.get("name")) or clean_text(row.get("ticker")) or "Earnings event"
            kicker = " / ".join(
                part
                for part in [
                    clean_text(row.get("ticker")),
                    display_status_text(row.get("event_type"), "scheduled report"),
                ]
                if part
            )
            reason = clean_text(row.get("importance_reason")) or "Calendar-linked disclosure event."
        else:
            title = clean_text(row.get("title")) or "Hard event"
            kicker = title_case_display_text(row.get("category"), "Hard event")
            beneficiary_labels = event_beneficiary_labels(
                [item for item in safe_list(row.get("beneficiary_stocks")) if isinstance(item, dict)]
            )
            beneficiary_text = f" Beneficiaries: {', '.join(beneficiary_labels)}" if beneficiary_labels else ""
            reason = (clean_text(row.get("importance_reason")) or "Hard event inside the watch window.") + beneficiary_text
        reminder = clean_text(row.get("reminder")) or "Confirm result and price reaction before acting."
        rows.append(
            '<div class="calendar-desk-row">'
            '<div class="calendar-primary-line">'
            '<div class="calendar-primary-copy">'
            f'<span class="calendar-date">{html.escape(event_date)} / {html.escape(time_label)}</span>'
            f'<strong>{html.escape(title)}</strong>'
            f'<span class="calendar-kicker">{html.escape(kicker)}</span>'
            "</div>"
            f'<span class="status-pill status-pending">{html.escape(importance_label)}</span>'
            "</div>"
            '<div class="calendar-secondary-line">'
            f'<span>{render_calendar_scope_chips(row.get("watch_scope"))}</span>'
            f'<span><strong>Source</strong> {html.escape(source)}</span>'
            f'<span><strong>Why it matters</strong> {html.escape(reason)}</span>'
            f'<span><strong>Desk action</strong> {html.escape(reminder)}</span>'
            "</div>"
            "</div>"
        )
    return '<div class="calendar-desk-list">' + "".join(rows) + "</div>"
