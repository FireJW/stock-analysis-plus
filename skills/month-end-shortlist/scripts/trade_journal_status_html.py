#!/usr/bin/env python3
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import parse_float, safe_dict


__all__ = ["render_trade_journal_status"]


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


def render_trade_journal_status(package: dict[str, Any]) -> str:
    journal_path = clean_text(package.get("trade_journal_path"))
    journal_report_path = clean_text(package.get("trade_journal_report_path"))
    decision_count = clean_text(package.get("trade_journal_decision_count", 0)) or "0"
    outcome_count = clean_text(package.get("trade_journal_outcome_count", 0)) or "0"
    decision_error = clean_text(package.get("trade_journal_error"))
    outcome_error = clean_text(package.get("trade_journal_outcome_error"))
    report_error = clean_text(package.get("trade_journal_report_error"))
    if not journal_path and not decision_error and not outcome_error and not report_error:
        return ""
    decisions_n = parse_float(decision_count) or 0
    outcomes_n = parse_float(outcome_count) or 0
    if decision_error or outcome_error or report_error:
        status_class = "blocked"
        status_label = "error"
    elif decisions_n + outcomes_n > 0:
        status_class = "covered"
        status_label = f"{int(decisions_n)} decisions / {int(outcomes_n)} outcomes"
    else:
        status_class = "pending"
        status_label = "no rows appended"
    summary = (
        "Trade journal appended decision and outcome rows for institutional traceability."
        if not (decision_error or outcome_error or report_error) and decisions_n + outcomes_n > 0
        else (
            "Trade journal hook ran but appended no rows; verify the active pool has trade cards or postclose results."
            if not (decision_error or outcome_error or report_error)
            else "Trade journal hook failed; see error details below."
        )
    )
    error_block = ""
    if decision_error or outcome_error or report_error:
        items: list[str] = []
        if decision_error:
            items.append(f"<li><strong>decision:</strong> {html.escape(decision_error)}</li>")
        if outcome_error:
            items.append(f"<li><strong>outcome:</strong> {html.escape(outcome_error)}</li>")
        if report_error:
            items.append(f"<li><strong>report:</strong> {html.escape(report_error)}</li>")
        error_block = '<ul class="data-note">' + "".join(items) + "</ul>"
    artifact_links: list[str] = []
    if journal_path:
        artifact_links.append(_render_file_link(journal_path, "trade-journal.jsonl"))
    if journal_report_path:
        artifact_links.append(_render_file_link(journal_report_path, "trade-journal.md"))
    artifact_link_block = f'<div class="artifact-links">{"".join(artifact_links)}</div>' if artifact_links else ""
    return (
        '<section class="trade-journal-status" aria-label="Trade journal status">'
        '<div class="section-head">'
        "<h2>Trade Journal</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(status_label)}</span>'
        "</div>"
        '<div class="source-status-body">'
        f"<p>{html.escape(summary)}</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(decision_count)}</span><span class="metric-label">Decisions appended</span></div>'
        f'<div><span class="metric-value">{html.escape(outcome_count)}</span><span class="metric-label">Outcomes appended</span></div>'
        "</div>"
        f"{artifact_link_block}"
        f"{error_block}"
        "</div>"
        "</section>"
    )
