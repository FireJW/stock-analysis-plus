#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from manager_html_primitives import safe_dict, safe_list


SUMMARY_DIRECTORY_LINKS: tuple[tuple[str, str, str], ...] = (
    ("macro-health-overlay", "Macro Overlay", "regime, liquidity, posture"),
    ("earnings-calendar-watch", "Earnings", "reports and date risk"),
    ("event-calendar-watch", "Event Calendar", "macro, policy, hard events"),
    ("fresh-discovery", "Fresh Discovery", "new market-strength names"),
    ("entry-list-screening", "Entry Screening", "direct entry vs watchlist"),
    ("trigger-monitor", "Trigger Monitor", "levels, alerts, quote state"),
    ("ticker-quote-news-coverage", "Quote/News", "per-ticker freshness and limits"),
    ("stock-logic-check", "Logic Check", "single-name thesis verification"),
    ("thesis-fact-check", "Logic Fact Check", "claim-level thesis evidence"),
    ("postclose-review", "Postclose Review", "feedback from prior session"),
    ("institutional-signal-audit", "Signal Audit", "evidence stack coverage"),
    ("institutional-evidence-followups", "Evidence Followups", "missing-source requests"),
    ("local-stock-pool", "Stock Pool", "editable plan rows"),
)


def summary_directory_target_available(anchor: str, package: dict[str, Any]) -> bool:
    if anchor == "local-stock-pool":
        return True
    if anchor == "macro-health-overlay":
        request = safe_dict(package.get("month_end_request"))
        return bool(safe_dict(package.get("macro_health_overlay")) or safe_dict(request.get("macro_health_overlay")))
    if anchor == "earnings-calendar-watch":
        watch = safe_dict(package.get("earnings_calendar_watch"))
        return bool(safe_list(watch.get("events")) or safe_list(watch.get("source_errors")))
    if anchor == "event-calendar-watch":
        watch = safe_dict(package.get("event_calendar_watch"))
        return bool(safe_list(watch.get("events")) or safe_list(watch.get("source_errors")))
    if anchor == "fresh-discovery":
        request = safe_dict(package.get("month_end_request"))
        return bool(safe_dict(package.get("fresh_discovery_coverage")) or request.get("fresh_discovery_required") is True)
    if anchor == "entry-list-screening":
        return bool(safe_dict(package.get("entry_list_screening")))
    if anchor == "trigger-monitor":
        return bool(safe_dict(package.get("trigger_monitor")))
    if anchor == "ticker-quote-news-coverage":
        return bool(safe_dict(package.get("ticker_quote_news_coverage")))
    if anchor == "stock-logic-check":
        return bool(safe_dict(package.get("stock_logic_check")))
    if anchor == "thesis-fact-check":
        return bool(safe_dict(package.get("thesis_fact_check")))
    if anchor == "postclose-review":
        return bool(safe_dict(package.get("postclose_review")))
    if anchor == "institutional-signal-audit":
        return bool(safe_dict(package.get("institutional_signal_audit")))
    if anchor == "institutional-evidence-followups":
        return bool([row for row in safe_list(package.get("institutional_evidence_followups")) if isinstance(row, dict)])
    return False


def render_summary_directory(package: dict[str, Any]) -> str:
    links = []
    for anchor, label, hint in SUMMARY_DIRECTORY_LINKS:
        if not summary_directory_target_available(anchor, package):
            continue
        links.append(
            f'<a class="directory-link" href="#{html.escape(anchor)}">'
            f'<span>{html.escape(label)}</span>'
            f'<small>{html.escape(hint)}</small>'
            "</a>"
        )
    return (
        '<nav class="summary-directory" aria-label="Page directory">'
        '<div class="directory-title">Page Directory</div>'
        '<div class="directory-grid">'
        + "".join(links)
        + "</div>"
        "</nav>"
    )


__all__ = [
    "SUMMARY_DIRECTORY_LINKS",
    "render_summary_directory",
    "summary_directory_target_available",
]
