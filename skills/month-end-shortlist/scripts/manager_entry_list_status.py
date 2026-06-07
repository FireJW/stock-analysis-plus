#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text
from manager_artifact_links import render_file_link
from manager_html_primitives import parse_float, safe_dict, safe_list
from manager_pool_merge import normalize_workflow_display_ticker, normalize_workflow_display_ticker_text


def _calendar_identity_tokens(value: Any) -> set[str]:
    text = clean_text(value)
    if not text:
        return set()
    return {
        text.casefold(),
        text.upper(),
        normalize_workflow_display_ticker(text).casefold(),
        normalize_workflow_display_ticker(text).upper(),
    }


def build_entry_list_earnings_overlay(package: dict[str, Any]) -> list[dict[str, Any]]:
    screening = safe_dict(package.get("entry_list_screening"))
    watch = safe_dict(package.get("earnings_calendar_watch"))
    events = [row for row in safe_list(watch.get("events")) if isinstance(row, dict)]
    if not screening or not events:
        return []

    event_index: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        event_ticker = normalize_workflow_display_ticker(event.get("ticker") or event.get("symbol") or event.get("code"))
        event_name = clean_text(event.get("name") or event.get("company") or event.get("company_name") or event_ticker)
        for identity in _calendar_identity_tokens(event_ticker) | _calendar_identity_tokens(event_name):
            event_index.setdefault(identity, []).append(event)

    overlay_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source_key, default_bucket in (("entry_candidates", "entry_candidate"), ("watchlist_candidates", "priority_watchlist")):
        for candidate in safe_list(screening.get(source_key)):
            if not isinstance(candidate, dict):
                continue
            ticker = normalize_workflow_display_ticker(candidate.get("ticker"))
            name = clean_text(candidate.get("name") or ticker)
            candidate_action = clean_text(candidate.get("action") or candidate.get("watch_action"))
            identities = _calendar_identity_tokens(ticker) | _calendar_identity_tokens(name)
            matched_event = None
            for identity in identities:
                event_matches = event_index.get(identity, [])
                if event_matches:
                    matched_event = event_matches[0]
                    break
            if matched_event is None:
                continue
            event_date = clean_text(matched_event.get("event_date") or matched_event.get("date"))
            unique_key = (ticker, name, event_date)
            if unique_key in seen:
                continue
            seen.add(unique_key)
            overlay_rows.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "source_bucket": clean_text(candidate.get("source_bucket")) or default_bucket,
                    "action": candidate_action or ("wait for confirmation" if source_key == "watchlist_candidates" else "entry allowed"),
                    "event_date": event_date,
                    "days_until": matched_event.get("days_until"),
                    "time": clean_text(matched_event.get("time")),
                    "event_type": clean_text(matched_event.get("event_type")),
                    "importance": clean_text(matched_event.get("importance")),
                    "source": clean_text(matched_event.get("source")),
                    "reminder": clean_text(matched_event.get("reminder")),
                    "watch_scope": clean_string_list(matched_event.get("watch_scope")),
                }
            )
    overlay_rows.sort(
        key=lambda row: (
            parse_float(row.get("days_until")) if parse_float(row.get("days_until")) is not None else 999.0,
            clean_text(row.get("ticker")),
            clean_text(row.get("name")),
        )
    )
    return overlay_rows


def render_entry_list_screening_status(package: dict[str, Any]) -> str:
    screening = safe_dict(package.get("entry_list_screening"))
    if not screening:
        return ""
    status = clean_text(screening.get("status")) or "empty"
    status_class = "covered" if status == "open" else "pending"
    decision = clean_text(screening.get("decision")) or "no_entry_candidates_to_promote"
    entry_count = clean_text(screening.get("entry_candidate_count", 0)) or "0"
    top_pick_count = clean_text(screening.get("top_pick_count", 0)) or "0"
    directly_actionable_count = clean_text(screening.get("directly_actionable_count", 0)) or "0"
    priority_watch_count = clean_text(screening.get("priority_watch_count", 0)) or "0"
    near_miss_count = clean_text(screening.get("near_miss_count", 0)) or "0"
    diagnostic_count = clean_text(screening.get("diagnostic_count", 0)) or "0"
    candidate_rows: list[str] = []

    def detail_items_for_candidate(candidate: dict[str, Any], default_detail: str) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []

        def add(label: str, value: Any) -> None:
            text = clean_text(value)
            if text:
                items.append((label, text))

        source = clean_text(candidate.get("source"))
        if source:
            add("source", source)
        if candidate.get("market_strength_supplement"):
            add("source_hint", "market_strength_supplement")
        add("readiness_status", candidate.get("readiness_status"))
        add("why_now", candidate.get("why_now"))
        event_state_label = clean_text(candidate.get("event_state_label"))
        event_state_summary = clean_text(candidate.get("event_state_summary"))
        if event_state_label or event_state_summary:
            add("event_state", " - ".join(part for part in (event_state_label, event_state_summary) if part))
        add("market_signal_summary", candidate.get("market_signal_summary"))
        add("community_reaction_summary", candidate.get("community_reaction_summary"))
        add("expectation_basis_summary", candidate.get("expectation_basis_summary"))
        add("expectation_risk_summary", candidate.get("expectation_risk_summary"))
        market_validation_label = clean_text(candidate.get("market_validation_label"))
        market_validation_summary = clean_text(candidate.get("market_validation_summary"))
        if market_validation_label or market_validation_summary:
            add(
                "market_validation_summary",
                " - ".join(part for part in (market_validation_label, market_validation_summary) if part),
            )
        trading_usability_label = clean_text(candidate.get("trading_usability_label"))
        trading_usability_summary = clean_text(candidate.get("trading_usability_summary"))
        if trading_usability_label or trading_usability_summary:
            add(
                "trading_usability",
                " - ".join(part for part in (trading_usability_label, trading_usability_summary) if part),
            )
        add("trading_profile_bucket", candidate.get("trading_profile_bucket"))
        add("trading_profile_judgment", candidate.get("trading_profile_judgment"))
        add("trading_profile_usage", candidate.get("trading_profile_usage"))
        add("trading_profile_playbook", candidate.get("trading_profile_playbook"))
        add("trade_card.watch_action", candidate.get("trade_action"))
        add("trade_card.trigger", candidate.get("trade_trigger"))
        add("trade_card.invalidation", candidate.get("trade_invalidation"))
        add("trade_card.stop", candidate.get("trade_stop"))
        add("trade_card.position_sizing_guidance", candidate.get("trade_position_sizing_guidance"))
        risk_flags = ", ".join(clean_string_list(candidate.get("trade_risk_flags")))
        add("trade_card.risk_flags", risk_flags)
        score = candidate.get("score")
        if score not in (None, ""):
            add("score", score)
        keep_threshold_gap = candidate.get("keep_threshold_gap")
        if keep_threshold_gap not in (None, ""):
            add("keep_threshold_gap", keep_threshold_gap)
        if not items:
            add("detail", default_detail)
        return items[:20]

    candidate_sources = (
        (
            screening.get("entry_candidates"),
            "entry_candidate",
            "entry candidate",
            "covered",
            "promoted from shortlist screening",
        ),
        (
            screening.get("watchlist_candidates"),
            "priority_watchlist",
            "wait for confirmation",
            "pending",
            "requires confirmation before promotion",
        ),
    )
    for candidates, default_bucket, default_action, row_status, default_detail in candidate_sources:
        for candidate in (candidates if isinstance(candidates, list) else [])[:8]:
            if not isinstance(candidate, dict):
                continue
            ticker = clean_text(candidate.get("ticker")) or "unknown"
            name = clean_text(candidate.get("name")) or ticker
            source_bucket = clean_text(candidate.get("source_bucket")) or default_bucket
            action = clean_text(candidate.get("action")) or default_action
            why_now = clean_text(candidate.get("why_now"))
            chain = clean_text(candidate.get("chain_name"))
            detail = why_now or chain or default_detail
            detail_html = "".join(
                f'<span class="metric-label"><strong>{html.escape(label)}</strong>: {html.escape(value)}</span>'
                for label, value in detail_items_for_candidate(candidate, detail)
            )
            candidate_rows.append(
                '<div class="source-status-item entry-list-screening-item">'
                '<div class="source-status-copy">'
                f'<span class="overview-ticker">{html.escape(ticker)}</span>'
                f'<span class="overview-name">{html.escape(name)}</span>'
                "</div>"
                f'<span class="bucket-pill">{html.escape(source_bucket)}</span>'
                f'<span class="status-pill status-{html.escape(row_status)}">{html.escape(action)}</span>'
                f'<div class="entry-list-screening-details">{detail_html}</div>'
                "</div>"
            )
    if status == "open":
        summary = "Entry-list screening is attached and has candidates that can flow into the promotion lane."
    elif status == "watchlist_only":
        summary = "Entry-list screening has watchlist-only candidates that require confirmation before promotion."
    else:
        summary = "Entry-list screening is attached, but no top-pick or directly-actionable candidate is available for promotion."
    artifact_links = "".join(
        link
        for link in (
            render_file_link(package.get("shortlist_result_path"), "month-end-shortlist-result.json"),
            render_file_link(package.get("shortlist_report_path"), "month-end-shortlist-report.md"),
        )
        if link
    )
    artifact_link_block = f'<div class="artifact-links">{artifact_links}</div>' if artifact_links else ""
    candidate_block = (
        '<div class="source-status-list">' + "".join(candidate_rows) + "</div>"
        if candidate_rows
        else '<p class="data-note">No entry-list candidates were promoted from the latest shortlist result.</p>'
    )
    overlay_rows = [row for row in safe_list(package.get("entry_list_earnings_overlay")) if isinstance(row, dict)]
    if not overlay_rows:
        overlay_rows = build_entry_list_earnings_overlay(package)
    overlay_block = ""
    if overlay_rows:
        overlay_items = []
        for row in overlay_rows[:8]:
            ticker = clean_text(row.get("ticker")) or "unknown"
            name = clean_text(row.get("name")) or ticker
            event_date = clean_text(row.get("event_date"))
            days_until = clean_text(row.get("days_until"))
            event_type = clean_text(row.get("event_type"))
            importance = clean_text(row.get("importance")) or "medium"
            source = clean_text(row.get("source"))
            reminder = clean_text(row.get("reminder"))
            label = " / ".join(part for part in (event_date, days_until and f"{days_until}d", event_type) if part)
            overlay_items.append(
                '<div class="source-status-item entry-list-overlay-item">'
                '<div class="source-status-copy">'
                f'<span class="overview-ticker">{html.escape(ticker)}</span>'
                f'<span class="overview-name">{html.escape(name)}</span>'
                "</div>"
                f'<span class="status-pill status-pending">{html.escape(label or "upcoming earnings")}</span>'
                f'<span class="bucket-pill">{html.escape(importance)}</span>'
                f'<span class="metric-label">{html.escape(source or "earnings calendar")}</span>'
                "</div>"
            )
            if reminder:
                overlay_items.append(
                    '<div class="source-status-copy entry-list-overlay-reminder">'
                    f'<span class="metric-label">{html.escape(reminder)}</span>'
                    "</div>"
                )
        overlay_block = (
            '<div class="overlay-block">'
            '<p class="data-note">Upcoming earnings overlay: entry candidates with a matching calendar event in the next 7 days.</p>'
            '<div class="source-status-list">' + "".join(overlay_items) + "</div>"
            "</div>"
        )
    rendered = (
        '<section id="entry-list-screening" class="entry-list-screening-status" aria-label="Entry list screening status">'
        '<div class="section-head">'
        "<h2>Entry List Screening</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(status)}</span>'
        "</div>"
        '<div class="source-status-body">'
        f"<p>{html.escape(summary)}</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(entry_count)}</span><span class="metric-label">Entry candidates</span></div>'
        f'<div><span class="metric-value">{html.escape(top_pick_count)}</span><span class="metric-label">Top picks</span></div>'
        f'<div><span class="metric-value">{html.escape(directly_actionable_count)}</span><span class="metric-label">Direct action</span></div>'
        f'<div><span class="metric-value">{html.escape(priority_watch_count)}</span><span class="metric-label">Priority watch</span></div>'
        f'<div><span class="metric-value">{html.escape(near_miss_count)}</span><span class="metric-label">Near miss</span></div>'
        f'<div><span class="metric-value">{html.escape(diagnostic_count)}</span><span class="metric-label">Diagnostic</span></div>'
        "</div>"
        f'<p class="data-note">Decision: {html.escape(decision)}</p>'
        f"{artifact_link_block}"
        f"{candidate_block}"
        f"{overlay_block}"
        "</div>"
        "</section>"
    )
    return normalize_workflow_display_ticker_text(rendered)


__all__ = [
    "build_entry_list_earnings_overlay",
    "render_entry_list_screening_status",
]
