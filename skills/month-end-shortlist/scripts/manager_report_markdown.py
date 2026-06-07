#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text
from manager_calendar_desk import event_beneficiary_labels
from manager_html_primitives import safe_dict, safe_list
from manager_pool_merge import normalize_workflow_display_ticker_text


def replace_markdown_section(report: str, heading: str, replacement: str) -> str:
    replacement_text = str(replacement).strip()
    if not replacement_text:
        return str(report)
    report_text = str(report)
    pattern = re.compile(rf"(^|\n){re.escape(heading)}[^\n]*\n.*?(?=\n## |\Z)", re.DOTALL)
    match = pattern.search(report_text)
    if not match:
        return report_text.rstrip() + "\n\n" + replacement_text + "\n"
    leading_newline = match.group(1)
    return report_text[: match.start()] + leading_newline + replacement_text + report_text[match.end():]


def render_shortlist_report_markdown(
    shortlist_result: dict[str, Any],
    *,
    macro_health_overlay: dict[str, Any] | None = None,
    macro_health_live_fetch_summary: dict[str, Any] | None = None,
    macro_health_seed_summary: dict[str, Any] | None = None,
) -> str:
    report_markdown = shortlist_result.get("report_markdown")
    overlay = safe_dict(macro_health_overlay)
    if not overlay:
        overlay = safe_dict(shortlist_result.get("macro_health_overlay"))
    if not overlay:
        overlay = safe_dict(safe_dict(shortlist_result.get("request")).get("macro_health_overlay"))
    live_fetch_summary = safe_dict(macro_health_live_fetch_summary)
    if not live_fetch_summary:
        live_fetch_summary = safe_dict(shortlist_result.get("macro_health_overlay_live_fetch_summary"))
    if not live_fetch_summary:
        live_fetch_summary = safe_dict(safe_dict(shortlist_result.get("request")).get("macro_health_overlay_live_fetch_summary"))
    seed_summary = safe_dict(macro_health_seed_summary)
    if not seed_summary:
        seed_summary = safe_dict(shortlist_result.get("macro_health_overlay_seed_summary"))
    if not seed_summary:
        seed_summary = safe_dict(safe_dict(shortlist_result.get("request")).get("macro_health_overlay_seed_summary"))
    try:
        from month_end_shortlist_runtime import build_macro_health_overlay_markdown
    except ModuleNotFoundError:
        macro_markdown = []
    else:
        macro_markdown = build_macro_health_overlay_markdown(
            overlay,
            live_fetch_summary=live_fetch_summary,
            seed_summary=seed_summary,
        )
    if clean_text(report_markdown):
        report = str(report_markdown)
        screening = safe_dict(shortlist_result.get("entry_list_screening"))
        if screening:
            screening_markdown = render_entry_list_screening_markdown(screening)
            if screening_markdown:
                report = replace_markdown_section(report, "## Entry List Screening", screening_markdown)
        if "## Macro Health Overlay" not in report:
            if macro_markdown:
                report = report.rstrip() + "\n\n" + "\n".join(macro_markdown).rstrip() + "\n"
        elif macro_markdown and "### Liquidity Monitor" not in report:
            report = report.rstrip() + "\n\n" + "\n".join(macro_markdown[3:]).rstrip() + "\n"
        if "## Earnings Calendar Watch" not in report:
            earnings_markdown = render_earnings_calendar_watch_markdown(
                safe_dict(shortlist_result.get("earnings_calendar_watch")),
                overlay_rows=[
                    *safe_list(shortlist_result.get("entry_list_earnings_overlay")),
                    *safe_list(screening.get("entry_list_earnings_overlay")),
                ],
            )
            if earnings_markdown:
                report = report.rstrip() + "\n\n" + earnings_markdown
        if "## Event Calendar Watch" not in report:
            event_markdown = render_event_calendar_watch_markdown(safe_dict(shortlist_result.get("event_calendar_watch")))
            if event_markdown:
                report = report.rstrip() + "\n\n" + event_markdown
        return normalize_workflow_display_ticker_text(report)
    try:
        from month_end_shortlist_runtime import build_markdown_report
    except ModuleNotFoundError:
        report = json.dumps(shortlist_result, ensure_ascii=False, indent=2) + "\n"
    else:
        report = str(build_markdown_report(shortlist_result))
    if "## Macro Health Overlay" not in report:
        if macro_markdown:
            report = report.rstrip() + "\n\n" + "\n".join(macro_markdown).rstrip() + "\n"
    elif macro_markdown and "### Liquidity Monitor" not in report:
        report = report.rstrip() + "\n\n" + "\n".join(macro_markdown[3:]).rstrip() + "\n"
    if "## Earnings Calendar Watch" not in report:
        earnings_markdown = render_earnings_calendar_watch_markdown(
            safe_dict(shortlist_result.get("earnings_calendar_watch")),
            overlay_rows=[
                *safe_list(shortlist_result.get("entry_list_earnings_overlay")),
                *safe_list(safe_dict(shortlist_result.get("entry_list_screening")).get("entry_list_earnings_overlay")),
            ],
        )
        if earnings_markdown:
            report = report.rstrip() + "\n\n" + earnings_markdown
    if "## Event Calendar Watch" not in report:
        event_markdown = render_event_calendar_watch_markdown(safe_dict(shortlist_result.get("event_calendar_watch")))
        if event_markdown:
            report = report.rstrip() + "\n\n" + event_markdown
    return normalize_workflow_display_ticker_text(report)


def build_entry_list_screening_from_shortlist_result(shortlist_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(shortlist_result, dict):
        return {}
    screening = safe_dict(shortlist_result.get("entry_list_screening"))
    overlay = [row for row in safe_list(shortlist_result.get("entry_list_earnings_overlay")) if isinstance(row, dict)]
    try:
        from month_end_shortlist_runtime import build_entry_list_screening
    except ModuleNotFoundError:
        if overlay and screening:
            screening = dict(screening)
            screening["earnings_calendar_overlay_count"] = len(overlay)
            screening["entry_list_earnings_overlay"] = overlay
        return screening
    source_bucket_keys = (
        "top_picks",
        "directly_actionable",
        "priority_watchlist",
        "near_miss_candidates",
        "diagnostic_scorecard",
    )
    if not screening or any(key in shortlist_result for key in source_bucket_keys):
        rebuilt = safe_dict(build_entry_list_screening(shortlist_result))
        if overlay:
            rebuilt["earnings_calendar_overlay_count"] = len(overlay)
            rebuilt["entry_list_earnings_overlay"] = overlay
        if rebuilt:
            return rebuilt
    if overlay and screening:
        screening = dict(screening)
        screening["earnings_calendar_overlay_count"] = len(overlay)
        screening["entry_list_earnings_overlay"] = overlay
    return screening


def render_entry_list_screening_markdown(screening: dict[str, Any]) -> str:
    if not isinstance(screening, dict) or not screening:
        return ""
    try:
        from month_end_shortlist_runtime import build_entry_list_screening_markdown
    except ModuleNotFoundError:
        return ""
    lines = build_entry_list_screening_markdown(screening)
    if not lines:
        return ""
    return normalize_workflow_display_ticker_text("\n".join(str(line) for line in lines).rstrip()) + "\n"


def markdown_table_cell(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return "-"
    return text.replace("|", "/")


def render_earnings_calendar_watch_markdown(
    watch: dict[str, Any],
    *,
    overlay_rows: list[Any] | None = None,
) -> str:
    events = [row for row in safe_list(watch.get("events")) if isinstance(row, dict)]
    source_errors = [row for row in safe_list(watch.get("source_errors")) if isinstance(row, dict)]
    if not events and not source_errors:
        return ""
    summary = safe_dict(watch.get("summary"))
    source_health = clean_text(watch.get("source_health")) or ("degraded" if source_errors else "ok")
    source_breakdown = [row for row in safe_list(watch.get("source_breakdown")) if isinstance(row, dict)]
    source_window_summaries = [row for row in safe_list(watch.get("source_window_summaries")) if isinstance(row, dict)]
    lines = [
        "## Earnings Calendar Watch",
        "",
        f"- Window: `{markdown_table_cell(watch.get('start_date'))}` to `{markdown_table_cell(watch.get('end_date'))}`",
        f"- Events: `{markdown_table_cell(summary.get('event_count', len(events)))}`",
        f"- Source health: `{markdown_table_cell(source_health)}`",
    ]
    if source_breakdown:
        source_mix = "; ".join(
            f"{clean_text(row.get('source'))}={clean_text(row.get('source_event_count'))}"
            for row in source_breakdown
            if clean_text(row.get("source")) and clean_text(row.get("source_event_count"))
        )
        if source_mix:
            lines.append(f"- Source mix: `{markdown_table_cell(source_mix)}`")
    if source_window_summaries:
        lines.extend(["", "### Source Window Summaries", "", "| Source | Market | Source rows | Window rows | Source window | Note |", "| --- | --- | ---: | ---: | --- | --- |"])
        for row in source_window_summaries[:12]:
            market = clean_text(row.get("market"))
            market_label = "A-share" if market.upper() == "CN" else market
            source_window = " - ".join(
                value for value in [clean_text(row.get("min_date")), clean_text(row.get("max_date"))] if value
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_table_cell(row.get("source")),
                        markdown_table_cell(market_label),
                        markdown_table_cell(row.get("source_event_count")),
                        markdown_table_cell(row.get("window_event_count")),
                        markdown_table_cell(source_window),
                        markdown_table_cell(row.get("window_note") or row.get("note")),
                    ]
                )
                + " |"
            )
    lines.append("")
    if events:
        lines.extend(
            [
                "| Date | Days | Time | Company | Ticker | Event | Importance | Scope | Source | URL | Reminder |",
                "| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
    for event in events[:12]:
        scope = ", ".join(clean_string_list(event.get("watch_scope")))
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_table_cell(event.get("event_date") or event.get("date")),
                    markdown_table_cell(event.get("days_until")),
                    markdown_table_cell(event.get("time")),
                    markdown_table_cell(event.get("name") or event.get("company")),
                    markdown_table_cell(event.get("ticker")),
                    markdown_table_cell(event.get("event_type")),
                    markdown_table_cell(event.get("importance")),
                    markdown_table_cell(scope),
                    markdown_table_cell(event.get("source")),
                    markdown_table_cell(event.get("source_url")),
                    markdown_table_cell(event.get("reminder")),
                ]
            )
            + " |"
        )
    if source_errors:
        lines.extend(
            [
                "",
                "### Source Limitations",
                "",
                "| Source | URL | Error |",
                "| --- | --- | --- |",
            ]
        )
        for row in source_errors[:8]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_table_cell(row.get("source")),
                        markdown_table_cell(row.get("source_url")),
                        markdown_table_cell(row.get("error")),
                    ]
                )
                + " |"
            )
    overlay = [row for row in overlay_rows or [] if isinstance(row, dict)]
    if overlay:
        lines.extend(
            [
                "",
                "### Entry Candidate Earnings Overlay",
                "",
                "| Ticker | Name | Bucket | Event Date | Days | Event | Reminder |",
                "| --- | --- | --- | --- | ---: | --- | --- |",
            ]
        )
        seen_overlay: set[tuple[str, str, str]] = set()
        for row in overlay[:12]:
            unique_key = (
                clean_text(row.get("ticker")),
                clean_text(row.get("name")),
                clean_text(row.get("event_date")),
            )
            if unique_key in seen_overlay:
                continue
            seen_overlay.add(unique_key)
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_table_cell(row.get("ticker")),
                        markdown_table_cell(row.get("name")),
                        markdown_table_cell(row.get("source_bucket")),
                        markdown_table_cell(row.get("event_date")),
                        markdown_table_cell(row.get("days_until")),
                        markdown_table_cell(row.get("event_type")),
                        markdown_table_cell(row.get("reminder")),
                    ]
                )
                + " |"
            )
    return "\n".join(lines).rstrip() + "\n"


def render_event_calendar_watch_markdown(watch: dict[str, Any]) -> str:
    events = [row for row in safe_list(watch.get("events")) if isinstance(row, dict)]
    source_errors = [row for row in safe_list(watch.get("source_errors")) if isinstance(row, dict)]
    if not events and not source_errors:
        return ""
    summary = safe_dict(watch.get("summary"))
    source_health = clean_text(watch.get("source_health")) or ("degraded" if source_errors else "ok")
    source_breakdown = [row for row in safe_list(watch.get("source_breakdown")) if isinstance(row, dict)]
    lines = [
        "## Event Calendar Watch",
        "",
        f"- Window: `{markdown_table_cell(watch.get('start_date'))}` to `{markdown_table_cell(watch.get('end_date'))}`",
        f"- Events: `{markdown_table_cell(summary.get('event_count', len(events)))}`",
        f"- Source health: `{markdown_table_cell(source_health)}`",
    ]
    beneficiary_count = clean_text(summary.get("beneficiary_stock_match_count")) or "0"
    lines.append(f"- Beneficiaries: `{markdown_table_cell(beneficiary_count)}`")
    if source_breakdown:
        source_mix = "; ".join(
            f"{clean_text(row.get('source'))}={clean_text(row.get('source_event_count'))}"
            for row in source_breakdown
            if clean_text(row.get("source")) and clean_text(row.get("source_event_count"))
        )
        if source_mix:
            lines.append(f"- Source mix: `{markdown_table_cell(source_mix)}`")
    lines.append("")
    if source_errors:
        lines.extend(
            [
                "### Source Errors",
                "",
                "| Source | URL | Error |",
                "| --- | --- | --- |",
            ]
        )
        for row in source_errors[:8]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_table_cell(row.get("source")),
                        markdown_table_cell(row.get("source_url")),
                        markdown_table_cell(row.get("error")),
                    ]
                )
                + " |"
            )
        lines.append("")
    if events:
        lines.extend(
            [
                "| Date | Days | Time | Title | Category | Importance | Scope | Beneficiaries | Source | URL | Reason | Reminder |",
                "| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
    for event in events[:12]:
        scope = ", ".join(clean_string_list(event.get("watch_scope")))
        beneficiaries = "; ".join(event_beneficiary_labels([item for item in safe_list(event.get("beneficiary_stocks")) if isinstance(item, dict)]))
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_table_cell(event.get("event_date") or event.get("date")),
                    markdown_table_cell(event.get("days_until")),
                    markdown_table_cell(event.get("time")),
                    markdown_table_cell(event.get("title")),
                    markdown_table_cell(event.get("category")),
                    markdown_table_cell(event.get("importance")),
                    markdown_table_cell(scope),
                    markdown_table_cell(beneficiaries),
                    markdown_table_cell(event.get("source")),
                    markdown_table_cell(event.get("source_url")),
                    markdown_table_cell(event.get("importance_reason")),
                    markdown_table_cell(event.get("reminder")),
                ]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_postclose_review_markdown(postclose_review: dict[str, Any]) -> str:
    try:
        from postclose_review_runtime import build_review_markdown
    except ModuleNotFoundError:
        return json.dumps(postclose_review, ensure_ascii=False, indent=2) + "\n"
    return str(build_review_markdown(postclose_review))


__all__ = [
    "build_entry_list_screening_from_shortlist_result",
    "markdown_table_cell",
    "render_earnings_calendar_watch_markdown",
    "render_entry_list_screening_markdown",
    "render_event_calendar_watch_markdown",
    "render_postclose_review_markdown",
    "render_shortlist_report_markdown",
    "replace_markdown_section",
]
