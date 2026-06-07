#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_artifact_links import render_file_link
from manager_html_primitives import parse_float, safe_dict, safe_list


def trigger_alert_status_class(alert_type: str) -> str:
    text = clean_text(alert_type)
    if text.endswith("_hit") and ("stop" in text or "abandon" in text):
        return "blocked"
    if text.endswith("_hit"):
        return "covered"
    return "pending"


def render_trigger_monitor_status(package: dict[str, Any]) -> str:
    monitor = safe_dict(package.get("trigger_monitor"))
    if not monitor:
        return ""
    active_cards_count = clean_text(monitor.get("active_cards_count", 0)) or "0"
    quotes_fetched = clean_text(monitor.get("quotes_fetched", 0)) or "0"
    alerts = [row for row in safe_list(monitor.get("alerts")) if isinstance(row, dict)]
    alert_count = clean_text(len(alerts)) or "0"
    cycle_time = clean_text(monitor.get("cycle_time"))
    monitor_path = clean_text(package.get("trigger_monitor_path"))
    monitor_report_path = clean_text(package.get("trigger_monitor_report_path"))
    status_class = "covered" if parse_float(quotes_fetched) and parse_float(quotes_fetched) > 0 else "pending"
    summary = (
        "Trigger monitor ran against active trade cards and attached the latest alert snapshot."
        if parse_float(quotes_fetched) and parse_float(quotes_fetched) > 0
        else "Trigger monitor ran, but no live quotes were fetched; keep live quote availability explicit."
    )
    rows = []
    for alert in alerts[:8]:
        ticker = clean_text(alert.get("ticker")) or "unknown"
        name = clean_text(alert.get("name")) or ticker
        alert_type = clean_text(alert.get("alert_type")) or "alert"
        level_name = clean_text(alert.get("level_name"))
        level_price = parse_float(alert.get("level_price"))
        last_done = parse_float(alert.get("last_done"))
        distance_pct = parse_float(alert.get("distance_pct"))
        timestamp = clean_text(alert.get("timestamp"))
        level_text = f"{level_name} {level_price:.3f}" if level_price is not None else level_name
        last_text = f"last {last_done:.3f}" if last_done is not None else "last n/a"
        distance_text = f"{distance_pct:+.2f}%" if distance_pct is not None else ""
        rows.append(
            '<div class="source-status-item trigger-alert-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(ticker)}</span>'
            f'<span class="overview-name">{html.escape(name)}</span>'
            "</div>"
            f'<span class="status-pill status-{html.escape(trigger_alert_status_class(alert_type))}">{html.escape(alert_type)}</span>'
            f'<span class="bucket-pill">{html.escape(level_text)}</span>'
            f'<span class="metric-label">{html.escape(last_text)}</span>'
            f'<span class="metric-label">{html.escape(distance_text)} {html.escape(timestamp)}</span>'
            "</div>"
        )
    alert_block = (
        '<div class="source-status-list">' + "".join(rows) + "</div>"
        if rows
        else '<p class="data-note">No trigger, stop, or abandon alerts fired in this cycle.</p>'
    )
    artifact_links: list[str] = []
    if monitor_path:
        artifact_links.append(render_file_link(monitor_path, "trigger-monitor.json"))
    if monitor_report_path:
        artifact_links.append(render_file_link(monitor_report_path, "trigger-monitor.md"))
    artifact_link_block = f'<div class="artifact-links">{"".join(artifact_links)}</div>' if artifact_links else ""
    return (
        '<section id="trigger-monitor" class="trigger-monitor-status" aria-label="Trigger monitor status">'
        '<div class="section-head">'
        "<h2>Trigger Monitor</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(alert_count)} alerts</span>'
        "</div>"
        '<div class="source-status-body">'
        f"<p>{html.escape(summary)}</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(active_cards_count)}</span><span class="metric-label">Active cards</span></div>'
        f'<div><span class="metric-value">{html.escape(quotes_fetched)}</span><span class="metric-label">Quotes fetched</span></div>'
        f'<div><span class="metric-value">{html.escape(alert_count)}</span><span class="metric-label">Alerts</span></div>'
        f'<div><span class="metric-value">{html.escape(cycle_time or "n/a")}</span><span class="metric-label">Cycle time</span></div>'
        "</div>"
        f"{artifact_link_block}"
        f"{alert_block}"
        "</div>"
        "</section>"
    )
