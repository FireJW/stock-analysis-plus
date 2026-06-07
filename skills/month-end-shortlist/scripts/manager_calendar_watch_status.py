#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_calendar_desk import (
    calendar_event_time_label,
    event_beneficiary_labels,
    render_calendar_desk_list,
)
from manager_calendar_scope import calendar_scope_labels
from manager_html_primitives import display_status_text, safe_dict, safe_list, title_case_display_text
from manager_ui_summary import count_noun_text


def render_earnings_calendar_watch_status(package: dict[str, Any]) -> str:
    watch = safe_dict(package.get("earnings_calendar_watch"))
    if not watch:
        return ""
    events = [
        row
        for row in (watch.get("events") if isinstance(watch.get("events"), list) else [])
        if isinstance(row, dict)
    ]
    source_errors = [row for row in safe_list(watch.get("source_errors")) if isinstance(row, dict)]
    if not events and not source_errors:
        return ""
    summary = safe_dict(watch.get("summary"))
    event_count = clean_text(summary.get("event_count")) or str(len(events))
    source_event_count = clean_text(summary.get("source_event_count")) or "0"
    source_error_count = clean_text(summary.get("source_error_count")) or str(len(source_errors))
    source_health = clean_text(watch.get("source_health")) or ("degraded" if source_errors else "ok")
    source_breakdown = [row for row in safe_list(watch.get("source_breakdown")) if isinstance(row, dict)]
    source_window_summaries = [row for row in safe_list(watch.get("source_window_summaries")) if isinstance(row, dict)]
    manual_focus_count = clean_text(summary.get("manual_focus_count")) or "0"
    local_pool_count = clean_text(summary.get("local_stock_pool_match_count")) or "0"
    industry_leader_count = clean_text(summary.get("industry_leader_count")) or "0"
    rows = []
    for row in events:
        scope = ", ".join(calendar_scope_labels(row.get("watch_scope")))
        source = html.escape(clean_text(row.get("source")))
        source_url = clean_text(row.get("source_url"))
        if source_url:
            link = f'<a href="{html.escape(source_url)}" target="_blank" rel="noreferrer">source</a>'
            source = f"{source} {link}" if source else link
        rows.append(
            "<tr>"
            f"<td>{html.escape(clean_text(row.get('event_date')))}</td>"
            f"<td>{html.escape(calendar_event_time_label(row.get('time')) or 'unscheduled')}</td>"
            f"<td>{html.escape(clean_text(row.get('name')))}</td>"
            f"<td>{html.escape(clean_text(row.get('ticker')))}</td>"
            f"<td>{html.escape(display_status_text(row.get('event_type')))}</td>"
            f"<td>{html.escape(title_case_display_text(row.get('importance'), 'Medium'))}</td>"
            f"<td>{html.escape(scope)}</td>"
            f"<td>{source}</td>"
            f"<td>{html.escape(clean_text(row.get('importance_reason')) or '-')}</td>"
            f"<td>{html.escape(clean_text(row.get('reminder')))}</td>"
            "</tr>"
        )
    error_rows = []
    for row in source_errors:
        source = html.escape(clean_text(row.get("source")) or "source")
        source_url = clean_text(row.get("source_url"))
        if source_url:
            source_link = f'<a href="{html.escape(source_url)}" target="_blank" rel="noreferrer">{source}</a>'
        else:
            source_link = source
        error_rows.append(
            "<tr>"
            f"<td>{source_link}</td>"
            f"<td>{html.escape(clean_text(row.get('error')))}</td>"
            "</tr>"
        )
    source_error_table = ""
    if error_rows:
        source_error_table = (
            f'<details class="source-limitations"><summary>Source limitations ({html.escape(str(len(error_rows)))})</summary>'
            '<div class="table-wrap calendar-table-wrap"><table class="earnings-calendar-table calendar-error-table">'
            "<thead><tr><th>Source</th><th>Error</th></tr></thead>"
            f"<tbody>{''.join(error_rows)}</tbody>"
            "</table></div>"
            "</details>"
        )
    source_mix_block = ""
    if source_breakdown:
        mix = "; ".join(
            f"{clean_text(row.get('source'))}={clean_text(row.get('source_event_count'))}"
            for row in source_breakdown
            if clean_text(row.get("source")) and clean_text(row.get("source_event_count"))
        )
        if mix:
            source_mix_block = f'<p class="data-note">Source mix: {html.escape(mix)}</p>'
    source_window_block = ""
    if source_window_summaries:
        window_rows = []
        for row in source_window_summaries:
            market = clean_text(row.get("market"))
            market_label = "A-share" if market.upper() == "CN" else market
            window = " - ".join(
                value for value in [clean_text(row.get("min_date")), clean_text(row.get("max_date"))] if value
            )
            window_rows.append(
                "<tr>"
                f"<td>{html.escape(clean_text(row.get('source')))}</td>"
                f"<td>{html.escape(market_label or '-')}</td>"
                f"<td>{html.escape(clean_text(row.get('source_event_count')) or '0')}</td>"
                f"<td>{html.escape(clean_text(row.get('window_event_count')) or '0')}</td>"
                f"<td>{html.escape(window or '-')}</td>"
                f"<td>{html.escape(clean_text(row.get('window_note')) or '-')}</td>"
                "</tr>"
            )
        source_window_block = (
            '<div class="table-wrap calendar-table-wrap"><table class="earnings-calendar-table calendar-source-table">'
            "<thead><tr><th>Source</th><th>Market</th><th>Source rows</th><th>Window rows</th><th>Source window</th><th>Note</th></tr></thead>"
            f"<tbody>{''.join(window_rows)}</tbody>"
            "</table></div>"
        )
    events_table = ""
    if rows:
        events_table = (
            '<details class="calendar-detail-table"><summary>Detailed earnings table</summary>'
            '<div class="table-wrap calendar-table-wrap"><table class="earnings-calendar-table calendar-event-table">'
            "<thead><tr><th>Date</th><th>Time</th><th>Company</th><th>Ticker</th><th>Type</th><th>Importance</th><th>Scope</th><th>Source</th><th>Reason</th><th>Reminder</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table></div></details>"
        )
    status_class = "status-covered" if source_health.lower() in {"ok", "covered"} else "status-blocked"
    status_label = (
        count_noun_text(event_count, "event")
        if source_health.lower() in {"ok", "covered"}
        else display_status_text(source_health, "degraded")
    )
    return (
        '<section id="earnings-calendar-watch" class="earnings-calendar-watch-status" aria-label="Earnings calendar watch">'
        '<div class="section-head">'
        "<h2>Earnings Calendar Watch</h2>"
        f'<span class="status-pill {html.escape(status_class)}">{html.escape(status_label)}</span>'
        "</div>"
        '<div class="earnings-calendar-body">'
        "<p>Shows the next 7 days of important earnings / report dates for the current pool, manual key names, and major industry leaders.</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(event_count)}</span><span class="metric-label">Events</span></div>'
        f'<div><span class="metric-value">{html.escape(source_event_count)}</span><span class="metric-label">Source rows</span></div>'
        f'<div><span class="metric-value">{html.escape(source_error_count)}</span><span class="metric-label">Source errors</span></div>'
        f'<div><span class="metric-value">{html.escape(manual_focus_count)}</span><span class="metric-label">Manual focus</span></div>'
        f'<div><span class="metric-value">{html.escape(local_pool_count)}</span><span class="metric-label">Local pool</span></div>'
        f'<div><span class="metric-value">{html.escape(industry_leader_count)}</span><span class="metric-label">Industry leaders</span></div>'
        "</div>"
        f"{render_calendar_desk_list(events, kind='earnings')}"
        f"{source_mix_block}"
        f"{source_window_block}"
        f"{events_table}"
        f"{source_error_table}"
        "</div>"
        "</section>"
    )


def render_event_calendar_watch_status(package: dict[str, Any]) -> str:
    watch = safe_dict(package.get("event_calendar_watch"))
    if not watch:
        return ""
    events = [row for row in safe_list(watch.get("events")) if isinstance(row, dict)]
    source_errors = [row for row in safe_list(watch.get("source_errors")) if isinstance(row, dict)]
    if not events and not source_errors:
        return ""
    summary = safe_dict(watch.get("summary"))
    event_count = clean_text(summary.get("event_count")) or str(len(events))
    source_event_count = clean_text(summary.get("source_event_count")) or "0"
    source_error_count = clean_text(summary.get("source_error_count")) or str(len(source_errors))
    source_health = clean_text(watch.get("source_health")) or ("degraded" if source_errors else "ok")
    source_breakdown = [row for row in safe_list(watch.get("source_breakdown")) if isinstance(row, dict)]
    local_pool_count = clean_text(summary.get("local_stock_pool_match_count")) or "0"
    beneficiary_count = clean_text(summary.get("beneficiary_stock_match_count")) or "0"
    high_importance_count = clean_text(summary.get("high_importance_count")) or "0"
    rows = []
    for row in events:
        scope = ", ".join(calendar_scope_labels(row.get("watch_scope")))
        beneficiary_labels = event_beneficiary_labels(
            [item for item in safe_list(row.get("beneficiary_stocks")) if isinstance(item, dict)]
        )
        beneficiary = (
            " ".join(f'<span class="ticker-chip">{html.escape(label)}</span>' for label in beneficiary_labels)
            if beneficiary_labels
            else '<span class="muted-text">-</span>'
        )
        source = html.escape(clean_text(row.get("source")))
        source_url = clean_text(row.get("source_url"))
        if source_url:
            link = f'<a href="{html.escape(source_url)}" target="_blank" rel="noreferrer">source</a>'
            source = f"{source} {link}" if source else link
        rows.append(
            "<tr>"
            f"<td>{html.escape(clean_text(row.get('event_date')))}</td>"
            f"<td>{html.escape(clean_text(row.get('time')) or '-')}</td>"
            f"<td>{html.escape(clean_text(row.get('title')))}</td>"
            f"<td>{html.escape(title_case_display_text(row.get('category'), 'Hard event'))}</td>"
            f"<td>{html.escape(title_case_display_text(row.get('importance'), 'Medium'))}</td>"
            f"<td>{html.escape(scope)}</td>"
            f"<td>{beneficiary}</td>"
            f"<td>{source}</td>"
            f"<td>{html.escape(clean_text(row.get('importance_reason')) or '-')}</td>"
            f"<td>{html.escape(clean_text(row.get('reminder')))}</td>"
            "</tr>"
        )
    error_rows = []
    for row in source_errors:
        source = html.escape(clean_text(row.get("source")) or "source")
        source_url = clean_text(row.get("source_url"))
        if source_url:
            source_link = f'<a href="{html.escape(source_url)}" target="_blank" rel="noreferrer">{source}</a>'
        else:
            source_link = source
        error_rows.append(
            "<tr>"
            f"<td>{source_link}</td>"
            f"<td>{html.escape(clean_text(row.get('error')))}</td>"
            "</tr>"
        )
    source_error_table = ""
    if error_rows:
        source_error_table = (
            '<div class="table-wrap calendar-table-wrap"><table class="event-calendar-table calendar-error-table">'
            "<thead><tr><th>Source</th><th>Error</th></tr></thead>"
            f"<tbody>{''.join(error_rows)}</tbody>"
            "</table></div>"
        )
    source_mix_block = ""
    if source_breakdown:
        mix = "; ".join(
            f"{clean_text(row.get('source'))}={clean_text(row.get('source_event_count'))}"
            for row in source_breakdown
            if clean_text(row.get("source")) and clean_text(row.get("source_event_count"))
        )
        if mix:
            source_mix_block = f'<p class="data-note">Source mix: {html.escape(mix)}</p>'
    events_table = ""
    if rows:
        events_table = (
            '<details class="calendar-detail-table"><summary>Detailed hard-event table</summary>'
            '<div class="table-wrap calendar-table-wrap"><table class="event-calendar-table calendar-event-table">'
            "<thead><tr><th>Date</th><th>Time</th><th>Title</th><th>Category</th><th>Importance</th><th>Scope</th><th>Beneficiaries</th><th>Source</th><th>Reason</th><th>Reminder</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table></div></details>"
        )
    status_class = "status-covered" if source_health.lower() in {"ok", "covered"} else "status-blocked"
    status_label = (
        count_noun_text(event_count, "event")
        if source_health.lower() in {"ok", "covered"}
        else display_status_text(source_health, "degraded")
    )
    return (
        '<section id="event-calendar-watch" class="event-calendar-watch-status" aria-label="Event calendar watch">'
        '<div class="section-head">'
        "<h2>Event Calendar Watch</h2>"
        f'<span class="status-pill {html.escape(status_class)}">{html.escape(status_label)}</span>'
        "</div>"
        '<div class="event-calendar-body">'
        "<p>Shows the next 7 days of high-impact macro, policy, product, and other hard events that can affect the current plan.</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(event_count)}</span><span class="metric-label">Events</span></div>'
        f'<div><span class="metric-value">{html.escape(source_event_count)}</span><span class="metric-label">Source rows</span></div>'
        f'<div><span class="metric-value">{html.escape(source_error_count)}</span><span class="metric-label">Source errors</span></div>'
        f'<div><span class="metric-value">{html.escape(high_importance_count)}</span><span class="metric-label">High impact</span></div>'
        f'<div><span class="metric-value">{html.escape(local_pool_count)}</span><span class="metric-label">Local pool</span></div>'
        f'<div><span class="metric-value">{html.escape(beneficiary_count)}</span><span class="metric-label">Beneficiaries</span></div>'
        "</div>"
        f"{render_calendar_desk_list(events, kind='event')}"
        f"{source_mix_block}"
        f"{source_error_table}"
        f"{events_table}"
        "</div>"
        "</section>"
    )


__all__ = [
    "render_earnings_calendar_watch_status",
    "render_event_calendar_watch_status",
]
