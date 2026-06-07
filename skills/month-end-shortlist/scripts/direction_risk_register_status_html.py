#!/usr/bin/env python3
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import parse_float, safe_dict, safe_list


__all__ = ["render_direction_risk_register_status"]


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


def render_direction_risk_register_status(package: dict[str, Any]) -> str:
    summary = safe_dict(package.get("direction_risk_register_summary"))
    register = safe_dict(package.get("direction_risk_register"))
    register_path = clean_text(package.get("direction_risk_register_path"))
    register_report_path = clean_text(package.get("direction_risk_register_report_path"))
    register_error = clean_text(package.get("direction_risk_register_error"))
    transitions = [t for t in safe_list(package.get("direction_risk_transitions")) if isinstance(t, dict)]
    if not summary and not register and not register_path and not register_error and not transitions:
        return ""
    counts = safe_dict(summary.get("counts"))
    total_tracked = clean_text(summary.get("total_tracked", 0)) or "0"
    normal_count = clean_text(counts.get("normal", 0)) or "0"
    elevated_count = clean_text(counts.get("elevated", 0)) or "0"
    restricted_count = clean_text(counts.get("restricted", 0)) or "0"
    most_restricted = clean_text(summary.get("most_restricted_direction")) or "-"
    days_since_all_clear = clean_text(summary.get("days_since_last_all_clear")) or "-"
    restricted_n = parse_float(restricted_count) or 0
    elevated_n = parse_float(elevated_count) or 0
    if register_error:
        status_class = "blocked"
        status_label = "error"
    elif restricted_n > 0:
        status_class = "blocked"
        status_label = f"{int(restricted_n)} restricted"
    elif elevated_n > 0:
        status_class = "pending"
        status_label = f"{int(elevated_n)} elevated"
    else:
        status_class = "covered"
        status_label = "all directions normal"
    intro = (
        "Direction risk register tracks consecutive caution/overheat/divergence signals and escalates directions to elevated or restricted."
        if not register_error
        else "Direction risk register hook failed; see error details below."
    )
    directions = safe_dict(register.get("directions"))
    flagged_rows: list[str] = []
    for direction_key, raw_entry in sorted(directions.items()):
        entry = safe_dict(raw_entry)
        current_status = clean_text(entry.get("current_status")) or "normal"
        if current_status == "normal":
            continue
        caution_days = clean_text(entry.get("consecutive_caution_days", 0)) or "0"
        good_days = clean_text(entry.get("consecutive_good_days", 0)) or "0"
        last_overheat = clean_text(entry.get("last_overheat_date")) or "-"
        last_divergence = clean_text(entry.get("last_divergence_date")) or "-"
        reason = clean_text(entry.get("restriction_reason")) or "-"
        expires = clean_text(entry.get("restriction_expires")) or "-"
        flagged_rows.append(
            '<div class="source-status-item direction-risk-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-name">{html.escape(direction_key)}</span>'
            f'<span class="metric-label">caution {html.escape(caution_days)} / good {html.escape(good_days)}</span>'
            "</div>"
            f'<span class="status-pill status-{html.escape("blocked" if current_status == "restricted" else "pending")}">{html.escape(current_status)}</span>'
            f'<span class="metric-label">overheat {html.escape(last_overheat)} / divergence {html.escape(last_divergence)}</span>'
            f'<span class="metric-label">{html.escape(reason)} (expires {html.escape(expires)})</span>'
            "</div>"
        )
    flagged_block = (
        '<div class="source-status-list">' + "".join(flagged_rows) + "</div>"
        if flagged_rows
        else '<p class="data-note">No directions are currently flagged elevated or restricted.</p>'
    )
    transition_rows: list[str] = []
    for transition in transitions:
        direction_key = clean_text(transition.get("direction_key"))
        from_status = clean_text(transition.get("from_status")) or "normal"
        to_status = clean_text(transition.get("to_status")) or "normal"
        reason = clean_text(transition.get("reason")) or "-"
        expires = clean_text(transition.get("expires")) or "-"
        if to_status == "restricted":
            pill_class = "blocked"
        elif to_status == "elevated":
            pill_class = "pending"
        elif to_status == "normal":
            pill_class = "covered"
        else:
            pill_class = "pending"
        transition_rows.append(
            '<div class="source-status-item direction-risk-transition-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-name">{html.escape(direction_key)}</span>'
            f'<span class="metric-label">{html.escape(from_status)} -&gt; {html.escape(to_status)}</span>'
            "</div>"
            f'<span class="status-pill status-{html.escape(pill_class)}">{html.escape(to_status)}</span>'
            f'<span class="metric-label">{html.escape(reason)} (expires {html.escape(expires)})</span>'
            "</div>"
        )
    transitions_block = (
        '<h3 class="subsection-heading">Today\'s transitions</h3>'
        '<div class="source-status-list direction-risk-transitions">'
        + "".join(transition_rows)
        + "</div>"
        if transition_rows
        else ""
    )
    error_block = f'<p class="data-note"><strong>error:</strong> {html.escape(register_error)}</p>' if register_error else ""
    artifact_links: list[str] = []
    if register_path:
        artifact_links.append(_render_file_link(register_path, "direction-risk-register.json"))
    if register_report_path:
        artifact_links.append(_render_file_link(register_report_path, "direction-risk-register.md"))
    artifact_link_block = f'<div class="artifact-links">{"".join(artifact_links)}</div>' if artifact_links else ""
    return (
        '<section class="direction-risk-register-status" aria-label="Direction risk register status">'
        '<div class="section-head">'
        "<h2>Direction Risk Register</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(status_label)}</span>'
        "</div>"
        '<div class="source-status-body">'
        f"<p>{html.escape(intro)}</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(total_tracked)}</span><span class="metric-label">Tracked</span></div>'
        f'<div><span class="metric-value">{html.escape(normal_count)}</span><span class="metric-label">Normal</span></div>'
        f'<div><span class="metric-value">{html.escape(elevated_count)}</span><span class="metric-label">Elevated</span></div>'
        f'<div><span class="metric-value">{html.escape(restricted_count)}</span><span class="metric-label">Restricted</span></div>'
        f'<div><span class="metric-value">{html.escape(most_restricted)}</span><span class="metric-label">Most restricted</span></div>'
        f'<div><span class="metric-value">{html.escape(days_since_all_clear)}</span><span class="metric-label">Days since all-clear</span></div>'
        "</div>"
        f"{artifact_link_block}"
        f"{error_block}"
        f"{transitions_block}"
        f"{flagged_block}"
        "</div>"
        "</section>"
    )
