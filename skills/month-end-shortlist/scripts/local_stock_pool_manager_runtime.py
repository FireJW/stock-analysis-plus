#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

from local_stock_pool_runtime import (
    clean_string_list,
    clean_text,
    load_json,
    normalize_a_share_ticker,
    normalize_local_stock_pool,
    unique_strings,
)
from direction_risk_register_status_html import render_direction_risk_register_status
from fresh_discovery_html import (
    render_fresh_discovery_sector_status,
    render_fresh_discovery_status,
)
from manager_fresh_discovery_layer import (
    build_fresh_discovery_sector_layer,
    fresh_discovery_count,
    normalize_reused_fresh_discovery_coverage,
)
from manager_artifact_links import artifact_label_for_path, render_file_link
from manager_browser_context import (
    cdp_endpoint_is_reachable as _browser_cdp_endpoint_is_reachable,
    default_codex_chrome_profile_dirs,
    default_codex_chrome_social_evidence_paths,
    detect_codex_chrome_cdp_endpoint as _detect_codex_chrome_cdp_endpoint,
)
from manager_calendar_scope import (
    CALENDAR_SCOPE_LABELS,
    calendar_scope_labels,
    render_calendar_scope_chips,
)
from manager_calendar_counts import (
    calendar_source_error_count,
    calendar_watch_count,
)
from manager_calendar_watch_status import (
    render_earnings_calendar_watch_status,
    render_event_calendar_watch_status,
)
from manager_calendar_watch_builders import (
    DEFAULT_EARNINGS_CALENDAR_HEADLINERS,
    DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS,
    EARNINGS_CALENDAR_EVENT_KEYS,
    EARNINGS_CALENDAR_WATCHLIST_KEYS,
    EVENT_CALENDAR_EVENT_KEYS,
    EVENT_CALENDAR_WATCHLIST_KEYS,
    build_earnings_calendar_watch,
    build_event_calendar_watch,
    parse_iso_date_value,
)
from manager_month_end_request import build_month_end_request
from manager_calendar_desk import (
    calendar_event_time_label as _calendar_event_time_label,
    event_beneficiary_labels as _event_beneficiary_labels,
    render_calendar_desk_list,
)
from manager_decision_overview import render_decision_overview
from manager_decision_rail import render_decision_rail
from manager_decision_summary import render_decision_summary
from manager_default_runners import (
    DirectionRiskRegisterRunner,
    InstitutionalAuditRunner,
    PostcloseReviewRunner,
    ShortlistRunner,
    TradeJournalDecisionRunner,
    TradeJournalOutcomeRunner,
    TriggerMonitorRunner,
    default_direction_risk_register_runner,
    default_institutional_signal_audit_runner,
    default_postclose_review_runner,
    default_shortlist_runner,
    default_source_capability_snapshot,
    default_source_health_probe_snapshot,
    default_trade_journal_decision_runner,
    default_trade_journal_outcome_runner,
    default_trigger_monitor_runner,
    resolve_trigger_monitor_longbridge_binary,
)
from manager_entry_list_status import build_entry_list_earnings_overlay, render_entry_list_screening_status
from manager_ui_summary import (
    PLAN_BUCKET_LABELS,
    build_ui_summary,
    bucket_counts_for_pool,
    count_noun_text,
    stock_bucket_label,
    summary_count_text,
)
from manager_json_payloads import (
    render_json_preview_text,
    safe_json_for_script,
)
from manager_market_snapshot import (
    format_signed_pct,
    market_change_pct,
    render_market_snapshot,
)
from manager_summary_directory import (
    SUMMARY_DIRECTORY_LINKS,
    render_summary_directory,
    summary_directory_target_available,
)
from manager_status_sections import (
    MAIN_STATUS_SECTION_ORDER,
    SOURCE_STATUS_SECTION_ORDER,
    render_status_sections,
)
from manager_source_status import (
    render_source_capabilities_status,
    render_source_health_probes_status,
    source_role_text,
    source_status_pill_class,
)
from manager_stock_rows import render_plan_overview, stock_table_rows
from manager_stock_row_widgets import (
    detail_row_id,
    render_edit_textarea,
    render_evidence_drawer,
    render_plan_level_chips,
    render_plan_text_block,
    render_trigger_distance_badge,
)
from manager_pool_merge import (
    is_placeholder_name,
    merge_note_text,
    merge_stock_pools,
    normalize_workflow_display_ticker,
    normalize_workflow_display_ticker_text,
)
from manager_report_markdown import (
    build_entry_list_screening_from_shortlist_result,
    markdown_table_cell,
    render_earnings_calendar_watch_markdown,
    render_entry_list_screening_markdown,
    render_event_calendar_watch_markdown,
    render_postclose_review_markdown,
    render_shortlist_report_markdown,
    replace_markdown_section,
)
from manager_plan_panels import (
    render_execution_checklist,
    render_plan_change_summary,
    render_ticker_list,
)
from manager_trigger_monitor_status import render_trigger_monitor_status, trigger_alert_status_class
from manager_ticker_quote_news_coverage import (
    ACTIONABILITY_GUARD_MARKERS,
    NEWS_RATE_LIMIT_MARKERS,
    _collect_stock_news_rows,
    _news_rate_limited,
    _news_sort_value,
    build_ticker_quote_news_coverage,
    normalize_news_publish_time,
    normalize_ticker_quote_news_coverage_row,
    render_ticker_quote_news_coverage_status,
)
from manager_stock_logic_check import (
    build_stock_logic_check,
    render_stock_logic_check_status,
)
from thesis_fact_check_runtime import (
    build_thesis_fact_check,
    render_thesis_fact_check_markdown,
    render_thesis_fact_check_status,
)
from manager_trading_plan_import import (
    attach_tickers_to_longbridge_news_details,
    build_local_stock_pool_from_trading_plan_result,
    build_local_stock_pool_from_trading_plan_text,
    build_monitor_trade_card_from_price_paths,
    build_plan_snapshot,
    build_trigger_distance,
    clean_markdown_text,
    detect_text_bucket,
    derive_monitor_price_paths_from_market_snapshot,
    discover_longbridge_artifacts,
    enrich_local_stock_pool_for_monitoring,
    enrich_plan_snapshot_for_monitoring,
    extract_labeled_text,
    extract_price_paths_from_text,
    extract_ticker_name,
    extract_trade_card_from_text,
    extract_trading_plan_rows,
    first_price_value,
    load_longbridge_market_status,
    load_longbridge_market_temperature,
    load_longbridge_news_details,
    load_longbridge_news_headlines,
    load_longbridge_plan_source_run,
    load_market_snapshots,
    load_trading_plan_result,
    merge_market_snapshots_into_local_stock_pool,
    merge_market_snapshots_into_trading_plan_result,
    normalize_market_snapshot,
    parse_number_list,
    plan_notes,
    plan_strategy_tags,
    plan_tags,
    price_path_summary,
    split_markdown_table_cells,
    text_looks_like_trading_plan,
    trading_plan_text_to_result,
)
from macro_health_overlay_html import render_macro_health_overlay_status
from manager_html_primitives import (
    display_status_text,
    parse_float,
    render_html_table,
    safe_dict,
    safe_list,
    title_case_display_text,
)
from manager_institutional_status import (
    build_institutional_actionability_gate,
    render_institutional_actionability_gate,
    render_institutional_evidence_followups_status,
    render_institutional_signal_audit_status,
)
from manager_institutional_audit import (
    audit_upgrade_priority_ids,
    build_institutional_signal_audit_payload,
    build_volume_anomaly_evidence_from_shortlist,
    render_institutional_signal_audit_markdown,
)
from manager_io import load_pool_or_template, write_json
from postclose_status_html import (
    render_postclose_observation_status,
    render_postclose_review_status,
)
from manager_postclose_layers import (
    build_postclose_observation_layer,
    build_postclose_review_input_from_current_pool,
)
from trade_journal_status_html import render_trade_journal_status


LONGBRIDGE_EXPECTATION_ARTIFACT_PACKAGE_KEYS: dict[str, str] = {
    "valuation": "longbridge_valuation",
    "institution_rating": "longbridge_institution_rating",
    "forecast_eps": "longbridge_forecast_eps",
    "consensus": "longbridge_consensus",
}

LONGBRIDGE_FUNDAMENTAL_ARTIFACT_PACKAGE_KEYS: dict[str, str] = {
    "financial_reports": "longbridge_financial_reports",
    "operating_reviews": "longbridge_operating_reviews",
    "industry_valuation": "longbridge_industry_valuation",
}


LOCAL_STOCK_POOL_UI_CONTRACT = {
    "interface_status": "data_contract_only",
    "supported_fields": [
        "ticker",
        "name",
        "groups",
        "tags",
        "notes",
        "strategy_tags",
        "strategy_rules",
        "plan_snapshot",
    ],
    "write_policy": "read_only_workflow_input",
}


def empty_local_stock_pool_template(payload: Any) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    strategy_rules = raw.get("strategy_rules") if isinstance(raw.get("strategy_rules"), list) else []
    return {
        "schema_version": "local_stock_pool/v1",
        "name": clean_text(raw.get("name")) or "local_stock_pool",
        "stocks": [],
        "groups": raw.get("groups") if isinstance(raw.get("groups"), list) else [],
        "strategy_rules": [item for item in strategy_rules if isinstance(item, dict)],
        "ui_contract": dict(LOCAL_STOCK_POOL_UI_CONTRACT),
    }


INSTITUTIONAL_EVIDENCE_FILENAME_MARKERS = (
    "x-index",
    "x_index",
    "institutional-evidence",
    "institutional_evidence",
    "social-evidence",
    "social_evidence",
    "x-following",
    "x_following",
    "x-capture",
    "x_capture",
    "x-whitelist",
    "x_whitelist",
    "reddit",
    "chrome-capture",
    "chrome_capture",
    "fundamental",
    "ownership",
    "filing",
    "tradingagents",
    "longbridge-news",
    "longbridge_news",
    "longbridge-market-status",
    "longbridge_market_status",
    "longbridge-market-temp",
    "longbridge_market_temp",
)

EARNINGS_CALENDAR_FILENAME_MARKERS = (
    "earnings-calendar",
    "earnings_calendar",
    "earnings-calendar-source",
    "earnings_calendar_source",
)

EVENT_CALENDAR_FILENAME_MARKERS = (
    "event-calendar",
    "event_calendar",
    "hard-events",
    "hard_events",
    "macro-calendar",
    "macro_calendar",
)


def payload_looks_like_institutional_evidence(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    schema_text = " ".join(
        clean_text(payload.get(key)).lower()
        for key in ("schema_version", "workflow_kind", "source_kind")
    )
    if any(marker in schema_text for marker in ("x-index", "x_index", "fundamental", "ownership", "filing")):
        return True
    if any(
        payload.get(key) not in (None, "", [], {})
        for key in (
            "x_posts",
            "reddit_posts",
            "filings",
            "filing",
            "fundamentals",
            "ownership",
            "investors",
            "insider",
            "institutional",
            "news",
            "event_cards",
            "events",
            "capital_flows",
            "positioning_flows",
            "source_health_probes",
        )
    ):
        return True
    tweets = payload.get("tweets")
    if isinstance(tweets, list) and tweets and (
        clean_text(payload.get("pageUrl") or payload.get("page_url")).lower().startswith(("https://x.com/", "https://twitter.com/", "https://www.reddit.com/"))
        or payload.get("followingClick") not in (None, "", [], {})
        or payload.get("whitelist") not in (None, "", [], {})
    ):
        return True
    posts = payload.get("posts")
    page_url = clean_text(payload.get("pageUrl") or payload.get("page_url") or payload.get("targetUrl") or payload.get("target_url")).lower()
    source_text = clean_text(payload.get("source") or payload.get("platform") or payload.get("source_platform")).lower()
    if (
        isinstance(posts, list)
        and posts
        and ("reddit" in source_text or page_url.startswith("https://www.reddit.com/") or page_url.startswith("https://reddit.com/"))
        and any(
            isinstance(post, dict)
            and clean_text(post.get("url"))
            and clean_text(post.get("title") or post.get("body") or post.get("text"))
            and clean_text(post.get("author") or post.get("subreddit"))
            for post in posts
        )
    ):
        return True
    evidence_pack = payload.get("evidence_pack")
    if isinstance(evidence_pack, dict) and any(evidence_pack.get(key) for key in ("x_posts", "claim_candidates")):
        return True
    decision_memo = safe_dict(payload.get("decision_memo"))
    state = safe_dict(decision_memo.get("state"))
    return bool(clean_text(state.get("fundamentals_report")))


def evidence_candidate_path(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() != ".json":
        return False
    if name in {"institutional-signal-audit.json", "local-stock-pool-manager-package.json"}:
        return False
    if name.endswith((".request.json", "-request.json", "_request.json")):
        return False
    return any(marker in name for marker in INSTITUTIONAL_EVIDENCE_FILENAME_MARKERS)


def payload_looks_like_earnings_calendar(payload: Any) -> bool:
    if not isinstance(payload, (dict, list)):
        return False
    if isinstance(payload, list):
        return any(isinstance(item, dict) and item.get("date") for item in payload)
    schema_text = " ".join(
        clean_text(payload.get(key)).lower()
        for key in ("schema_version", "workflow_kind", "source_kind")
    )
    if "earnings_calendar" in schema_text or "earnings-calendar" in schema_text:
        return True
    return any(payload.get(key) not in (None, "", [], {}) for key in EARNINGS_CALENDAR_EVENT_KEYS)


def earnings_calendar_candidate_path(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() != ".json":
        return False
    if name in {"local-stock-pool-manager-package.json"}:
        return False
    if any(marker in name for marker in ("-audit", "_audit", "unfiltered")):
        return False
    if name.endswith(("-check.json", "-diagnostic.json", "-probe.json")):
        return False
    if name.endswith((".request.json", "-request.json", "_request.json")):
        return False
    return any(marker in name for marker in EARNINGS_CALENDAR_FILENAME_MARKERS)


def discover_earnings_calendar_payloads(
    search_roots: list[str | Path] | None,
    *,
    limit: int = 8,
) -> tuple[list[Any], list[str]]:
    candidates: list[Path] = []
    seen_roots: set[str] = set()
    for root_value in search_roots or []:
        root = Path(root_value).expanduser()
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if str(resolved) in seen_roots:
            continue
        seen_roots.add(str(resolved))
        if resolved.is_file() and earnings_calendar_candidate_path(resolved):
            candidates.append(resolved)
        elif resolved.is_dir():
            candidates.extend(path for path in resolved.glob("*.json") if earnings_calendar_candidate_path(path))

    def sort_key(path: Path) -> tuple[float, str]:
        try:
            return (path.stat().st_mtime, path.name.lower())
        except OSError:
            return (0.0, path.name.lower())

    payloads: list[Any] = []
    sources: list[str] = []
    loaded_paths: set[str] = set()
    for path in sorted(candidates, key=sort_key, reverse=True):
        if len(payloads) >= limit:
            break
        resolved_text = str(path)
        if resolved_text in loaded_paths:
            continue
        try:
            payload = load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not payload_looks_like_earnings_calendar(payload):
            continue
        payloads.append(payload)
        sources.append(resolved_text)
        loaded_paths.add(resolved_text)
    return payloads, sources


def payload_looks_like_event_calendar(payload: Any) -> bool:
    if not isinstance(payload, (dict, list)):
        return False
    if isinstance(payload, list):
        return any(isinstance(item, dict) and item.get("date") and item.get("title") for item in payload)
    schema_text = " ".join(
        clean_text(payload.get(key)).lower()
        for key in ("schema_version", "workflow_kind", "source_kind")
    )
    if "event_calendar" in schema_text or "event-calendar" in schema_text:
        return True
    return any(payload.get(key) not in (None, "", [], {}) for key in EVENT_CALENDAR_EVENT_KEYS)


def event_calendar_candidate_path(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() != ".json":
        return False
    if name in {"local-stock-pool-manager-package.json"}:
        return False
    if name.endswith((".request.json", "-request.json", "_request.json")):
        return False
    return any(marker in name for marker in EVENT_CALENDAR_FILENAME_MARKERS)


def discover_event_calendar_payloads(
    search_roots: list[str | Path] | None,
    *,
    limit: int = 8,
) -> tuple[list[Any], list[str]]:
    candidates: list[Path] = []
    seen_roots: set[str] = set()
    for root_value in search_roots or []:
        root = Path(root_value).expanduser()
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if str(resolved) in seen_roots:
            continue
        seen_roots.add(str(resolved))
        if resolved.is_file() and event_calendar_candidate_path(resolved):
            candidates.append(resolved)
        elif resolved.is_dir():
            candidates.extend(path for path in resolved.glob("*.json") if event_calendar_candidate_path(path))

    def sort_key(path: Path) -> tuple[float, str]:
        try:
            return (path.stat().st_mtime, path.name.lower())
        except OSError:
            return (0.0, path.name.lower())

    payloads: list[Any] = []
    sources: list[str] = []
    loaded_paths: set[str] = set()
    for path in sorted(candidates, key=sort_key, reverse=True):
        if len(payloads) >= limit:
            break
        resolved_text = str(path)
        if resolved_text in loaded_paths:
            continue
        try:
            payload = load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not payload_looks_like_event_calendar(payload):
            continue
        payloads.append(payload)
        sources.append(resolved_text)
        loaded_paths.add(resolved_text)
    return payloads, sources


def discover_institutional_evidence_payloads(
    search_roots: list[str | Path] | None,
    *,
    limit: int = 12,
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for root_value in search_roots or []:
        root = Path(root_value).expanduser()
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        if resolved.is_file() and evidence_candidate_path(resolved):
            candidates.append(resolved)
        elif resolved.is_dir():
            candidates.extend(path for path in resolved.rglob("*.json") if evidence_candidate_path(path))

    def sort_key(path: Path) -> tuple[float, str]:
        try:
            return (path.stat().st_mtime, path.name.lower())
        except OSError:
            return (0.0, path.name.lower())

    payloads: list[dict[str, Any]] = []
    sources: list[str] = []
    loaded_paths: set[str] = set()
    for path in sorted(candidates, key=sort_key, reverse=True):
        if len(payloads) >= limit:
            break
        resolved_text = str(path)
        if resolved_text in loaded_paths:
            continue
        try:
            payload = load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not payload_looks_like_institutional_evidence(payload):
            continue
        payloads.append(payload)
        sources.append(resolved_text)
        loaded_paths.add(resolved_text)
    return payloads, sources


def implicit_institutional_evidence_roots(output_root: Path) -> list[Path]:
    roots = [output_root]
    if output_root.name.lower() in {"html", "output", "outputs", "artifacts"}:
        roots.append(output_root.parent)
    return roots


ENTRY_LIST_CANDIDATE_BUCKETS = {"top_picks", "directly_actionable"}
ENTRY_LIST_FALLBACK_BUCKETS = {"priority_watchlist"}
ENTRY_LIST_STATE_TAGS = {
    "entry_gate:open",
    "entry_gate:blocked",
    "entry_list_eligible",
    "monitoring_missing",
    "research_only",
    "watchlist_promoted",
}

def extract_macro_health_overlay(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    overlay = safe_dict(payload.get("macro_health_overlay"))
    if overlay:
        return overlay
    return safe_dict(safe_dict(payload.get("request")).get("macro_health_overlay"))


def extract_macro_health_overlay_live_fetch_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary = safe_dict(payload.get("macro_health_overlay_live_fetch_summary"))
    if summary:
        return summary
    return safe_dict(safe_dict(payload.get("request")).get("macro_health_overlay_live_fetch_summary"))


def extract_macro_health_overlay_seed_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary = safe_dict(payload.get("macro_health_overlay_seed_summary"))
    if summary:
        return summary
    return safe_dict(safe_dict(payload.get("request")).get("macro_health_overlay_seed_summary"))


def attach_macro_health_overlay_from_shortlist_result(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None,
) -> None:
    if not isinstance(shortlist_result, dict):
        return
    package_overlay = safe_dict(package.get("macro_health_overlay"))
    overlay = package_overlay or safe_dict(shortlist_result.get("macro_health_overlay"))
    if not overlay:
        overlay = safe_dict(safe_dict(shortlist_result.get("request")).get("macro_health_overlay"))
    live_fetch_summary = extract_macro_health_overlay_live_fetch_summary(shortlist_result)
    seed_summary = extract_macro_health_overlay_seed_summary(shortlist_result)
    if not overlay:
        return
    package["macro_health_overlay"] = overlay
    month_end_request = safe_dict(package.get("month_end_request"))
    if month_end_request:
        month_end_request["macro_health_overlay"] = overlay
        if live_fetch_summary and not safe_dict(month_end_request.get("macro_health_overlay_live_fetch_summary")):
            month_end_request["macro_health_overlay_live_fetch_summary"] = live_fetch_summary
        if seed_summary and not safe_dict(month_end_request.get("macro_health_overlay_seed_summary")):
            month_end_request["macro_health_overlay_seed_summary"] = seed_summary
        package["month_end_request"] = month_end_request
    if live_fetch_summary and not safe_dict(package.get("macro_health_overlay_live_fetch_summary")):
        package["macro_health_overlay_live_fetch_summary"] = live_fetch_summary
    if seed_summary and not safe_dict(package.get("macro_health_overlay_seed_summary")):
        package["macro_health_overlay_seed_summary"] = seed_summary


THESIS_FACT_CHECK_PACKAGE_EVIDENCE_KEYS = {
    "workflow_kind",
    "schema_version",
    "local_stock_pool",
    "longbridge_news_headlines",
    "longbridge_news_details",
    "longbridge_capital_flows",
    "capital_flows",
    "longbridge_topics",
    "longbridge_filings",
    "filings",
    "longbridge_shareholders",
    "longbridge_fund_holders",
    "longbridge_insider_trades",
    "longbridge_short_positions",
    "longbridge_valuation",
    "longbridge_institution_rating",
    "longbridge_forecast_eps",
    "longbridge_consensus",
    "longbridge_financial_reports",
    "longbridge_operating_reviews",
    "longbridge_industry_valuation",
    "longbridge_plan_source_run",
    "information_completion_index",
    "longbridge_artifact_sources",
    "longbridge_expectation_artifact_sources",
    "institutional_evidence_sources",
    "x_index_social_evidence",
    "social_evidence",
    "external_evidence",
    "event_cards",
    "events",
    "sources",
    "announcements",
    "a_share_fundamentals",
    "fundamental_metrics",
    "financial_metrics",
    "a_share_fundamental_metrics",
}


def package_without_generated_thesis_fact_check(package: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in package.items()
        if key in THESIS_FACT_CHECK_PACKAGE_EVIDENCE_KEYS
    }


def format_cny_yi(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value / 100000000:.2f}bn"


def stock_has_monitorable_levels(stock: dict[str, Any]) -> bool:
    plan_snapshot = safe_dict(stock.get("plan_snapshot"))
    trade_card = safe_dict(stock.get("trade_card") or plan_snapshot.get("trade_card"))
    levels = safe_dict(stock.get("levels") or plan_snapshot.get("levels"))
    price_paths = safe_dict(stock.get("price_paths") or plan_snapshot.get("price_paths"))
    for source in (trade_card, levels):
        for key in ("trigger_price", "trigger", "stop_loss", "stop", "abandon_below", "abandon"):
            if parse_float(source.get(key)) is not None:
                return True
    return first_price_value(
        price_paths,
        ("resistance", "target", "bull", "trigger", "support", "stop_loss", "abandon_below", "abandon"),
    ) is not None


def clean_entry_list_state_tags(tags: Any) -> list[str]:
    return [tag for tag in clean_string_list(tags) if tag not in ENTRY_LIST_STATE_TAGS]


def apply_institutional_actionability_gate_to_package(package: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    gate = safe_dict(gate)
    local_stock_pool = safe_dict(package.get("local_stock_pool"))
    stocks = [stock for stock in local_stock_pool.get("stocks", []) if isinstance(stock, dict)]
    if not gate or not stocks:
        return {}

    status = clean_text(gate.get("status")) or "blocked"
    decision = clean_text(gate.get("decision")) or "research_only_until_required_layers_pass"
    blocking_layers = clean_string_list(gate.get("blocking_required_layers"))
    top_pick_stocks = [
        stock
        for stock in stocks
        if clean_text(safe_dict(stock.get("plan_snapshot")).get("bucket")) in ENTRY_LIST_CANDIDATE_BUCKETS
    ]
    fallback_stocks = []
    if not top_pick_stocks and (
        status == "open"
        or "stock_logic_check" in blocking_layers
        or "thesis_fact_alignment" in blocking_layers
    ):
        fallback_stocks = [
            stock
            for stock in stocks
            if clean_text(safe_dict(stock.get("plan_snapshot")).get("bucket")) in ENTRY_LIST_FALLBACK_BUCKETS
        ]
    promoted_stocks = top_pick_stocks or fallback_stocks
    monitorable_stocks: list[dict[str, Any]] = []
    unmonitorable_stocks: list[dict[str, Any]] = []
    for stock in promoted_stocks:
        if stock_has_monitorable_levels(stock):
            monitorable_stocks.append(stock)
        else:
            unmonitorable_stocks.append(stock)
    unmonitorable_ids = {id(stock) for stock in unmonitorable_stocks}
    is_fallback = bool(fallback_stocks) and not bool(top_pick_stocks)
    if not promoted_stocks:
        promotion_status = "empty"
        promotion_decision = "no_entry_candidates_to_promote"
        write_policy = "research_only"
    elif is_fallback and status == "open":
        promotion_status = "open"
        promotion_decision = "watchlist_candidates_promoted"
        write_policy = "entry_list_allowed"
    else:
        promotion_status = status
        promotion_decision = decision
        write_policy = "entry_list_allowed" if status == "open" else "research_only"
    promotion = {
        "schema_version": "entry_list_promotion/v1",
        "status": promotion_status,
        "decision": promotion_decision,
        "write_policy": write_policy,
        "actionability_gate_status": status,
        "candidate_count": len(promoted_stocks),
        "eligible_count": len(monitorable_stocks) if promotion_status == "open" else 0,
        "blocked_count": len(promoted_stocks) if promotion_status == "blocked" else len(unmonitorable_stocks),
        "unmonitorable_count": len(unmonitorable_stocks),
        "unmonitorable_tickers": [
            clean_text(stock.get("ticker"))
            for stock in unmonitorable_stocks
            if clean_text(stock.get("ticker"))
        ],
        "blocking_required_layers": blocking_layers,
        "promotion_tier": "fallback_watchlist" if is_fallback else "strict",
    }

    for stock in promoted_stocks:
        plan_snapshot = dict(safe_dict(stock.get("plan_snapshot")))
        plan_snapshot.setdefault("original_bucket", clean_text(plan_snapshot.get("bucket")) or "top_picks")
        plan_snapshot["entry_list_gate_status"] = status
        plan_snapshot["entry_list_decision"] = decision
        existing_strategy_tags = clean_entry_list_state_tags(stock.get("strategy_tags"))
        if blocking_layers:
            plan_snapshot["entry_list_blockers"] = blocking_layers
        if status != "open":
            plan_snapshot["bucket"] = "priority_watchlist"
            stock["groups"] = unique_strings(
                [
                    group
                    for group in clean_string_list(stock.get("groups"))
                    if group not in {PLAN_BUCKET_LABELS["top_picks"], PLAN_BUCKET_LABELS["directly_actionable"]}
                ]
                + [PLAN_BUCKET_LABELS["priority_watchlist"]]
            )
            stock["strategy_tags"] = unique_strings(
                existing_strategy_tags + ["entry_gate:blocked", "research_only"]
            )
            note = "Entry-list promotion blocked until institutional actionability gate passes."
            stock["notes"] = " | ".join(
                item for item in [clean_text(stock.get("notes")), note] if item
            )
        else:
            is_unmonitorable = id(stock) in unmonitorable_ids
            tags = ["entry_gate:open"]
            if is_unmonitorable:
                tags.append("monitoring_missing")
                plan_snapshot["entry_list_decision"] = "monitoring_required_before_entry"
                plan_snapshot["entry_list_blockers"] = unique_strings(
                    clean_string_list(plan_snapshot.get("entry_list_blockers"))
                    + ["monitorable_levels_missing"]
                )
            else:
                tags.append("entry_list_eligible")
            if is_fallback:
                tags.append("watchlist_promoted")
            stock["strategy_tags"] = unique_strings(
                existing_strategy_tags + tags
            )
        stock["plan_snapshot"] = plan_snapshot

    package["entry_list_promotion"] = promotion
    month_end_request = safe_dict(package.get("month_end_request"))
    if month_end_request:
        month_end_request["local_stock_pool"] = local_stock_pool
        month_end_request["entry_list_promotion"] = promotion
        package["month_end_request"] = month_end_request
    ui_summary = dict(safe_dict(package.get("ui_summary")))
    ui_summary["total_count"] = len(stocks)
    ui_summary["bucket_counts"] = bucket_counts_for_pool(local_stock_pool)
    package["ui_summary"] = ui_summary
    return promotion


def render_local_stock_pool_manager_html(package: dict[str, Any]) -> str:
    pool = package["local_stock_pool"]
    month_end_request = package["month_end_request"]
    ui_summary = safe_dict(package.get("ui_summary"))
    package_json = safe_json_for_script(package)
    pool_rows = stock_table_rows(pool)
    plan_overview = render_plan_overview(pool)
    pool_name = html.escape(clean_text(pool.get("name")) or "local_stock_pool")
    tdx_path = html.escape(clean_text(month_end_request.get("local_daily_bars_source", {}).get("path")))
    target_date = html.escape(clean_text(month_end_request.get("target_date")))
    analysis_time = html.escape(clean_text(month_end_request.get("analysis_time")))
    pool_payload_text = render_json_preview_text(pool)
    request_payload_text = render_json_preview_text(month_end_request)
    shortlist_report_text = html.escape(clean_text(package.get("shortlist_report_markdown")) or "No shortlist report available.")
    has_plan_import = any(isinstance(stock, dict) and isinstance(stock.get("plan_snapshot"), dict) for stock in pool.get("stocks", []))
    plan_source_note = (
        '<div class="data-note">Imported plan levels, not latest close. '
        "Current price data is only added when a market data source is provided.</div>"
        if has_plan_import
        else ""
    )
    decision_summary = render_decision_summary(
        ui_summary,
        target_date=clean_text(month_end_request.get("target_date")),
        analysis_time=clean_text(month_end_request.get("analysis_time")),
        package=package,
    )
    status_sections = {
        "macro_health_overlay": render_macro_health_overlay_status(package),
        "earnings_calendar_watch": render_earnings_calendar_watch_status(package),
        "event_calendar_watch": render_event_calendar_watch_status(package),
        "fresh_discovery": render_fresh_discovery_status(package),
        "entry_list_screening": render_entry_list_screening_status(package),
        "trigger_monitor": render_trigger_monitor_status(package),
        "trade_journal": render_trade_journal_status(package),
        "direction_risk_register": render_direction_risk_register_status(package),
        "fresh_discovery_sector": render_fresh_discovery_sector_status(package),
        "postclose_review": render_postclose_review_status(package),
        "postclose_observation": render_postclose_observation_status(package),
        "source_capabilities": render_source_capabilities_status(package),
        "source_health_probes": render_source_health_probes_status(package),
        "ticker_quote_news_coverage": render_ticker_quote_news_coverage_status(package),
        "stock_logic_check": render_stock_logic_check_status(package),
        "thesis_fact_check": render_thesis_fact_check_status(package),
        "institutional_actionability_gate": render_institutional_actionability_gate(package),
        "institutional_audit": render_institutional_signal_audit_status(package),
        "institutional_evidence_followups": render_institutional_evidence_followups_status(package),
    }
    main_status_sections = render_status_sections(status_sections, MAIN_STATUS_SECTION_ORDER)
    source_status_sections = render_status_sections(status_sections, SOURCE_STATUS_SECTION_ORDER)
    change_summary = render_plan_change_summary(ui_summary)
    execution_checklist = render_execution_checklist(ui_summary)
    rendered = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{pool_name} - Local Stock Pool</title>
  <style>
    :root {{
      color-scheme: light;
      --font-display: "VT323", "Courier New", ui-monospace, monospace;
      --font-body: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-mono: "JetBrains Mono", Consolas, ui-monospace, monospace;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #637083;
      --line: #d7dde5;
      --accent: #0f766e;
      --accent-dark: #0b5f59;
      --danger: #b42318;
      --success: #0f8a4c;
      --warning: #b7791f;
      --focus: #2563eb;
      --manual-bg: #0a0d1a;
      --manual-surface: #11172d;
      --manual-ink: #f2efe6;
      --paper-rule: rgba(93, 124, 255, 0.13);
      --blueprint: #5d7cff;
      --blueprint-soft: rgba(93, 124, 255, 0.15);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        radial-gradient(var(--paper-rule) 1px, transparent 1px),
        linear-gradient(180deg, #f3f6fb 0%, var(--bg) 42%, #eef3f7 100%);
      background-size: 16px 16px, auto;
      color: var(--ink);
      font-family: var(--font-body);
      font-size: 14px;
      line-height: 1.45;
    }}
    main {{
      min-height: 100vh;
      padding: 20px;
    }}
    .shell {{
      max-width: 1440px;
      margin: 0 auto;
      display: grid;
      gap: 14px;
    }}
    .topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 0;
    }}
    .manual-topbar {{
      position: relative;
      overflow: hidden;
      min-height: 136px;
      padding: 18px 20px;
      color: var(--manual-ink);
      background: var(--manual-bg);
      border: 1px solid rgba(93, 124, 255, 0.28);
      border-radius: 8px;
      box-shadow: 0 16px 46px rgba(17, 24, 39, 0.16);
    }}
    .manual-topbar::before {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(rgba(93, 124, 255, 0.18) 1px, transparent 1px),
        linear-gradient(135deg, rgba(93, 124, 255, 0.18), transparent 42%);
      background-size: 18px 18px, auto;
      opacity: 0.9;
      pointer-events: none;
    }}
    .manual-title-group {{
      position: relative;
      z-index: 1;
      display: grid;
      gap: 10px;
      min-width: 0;
    }}
    .manual-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      color: var(--blueprint);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }}
    .manual-meta span {{
      overflow-wrap: anywhere;
    }}
    .manual-title {{
      display: flex;
      align-items: center;
      gap: 12px;
      max-width: 100%;
      color: var(--manual-ink);
      font-family: var(--font-display);
      font-size: clamp(30px, 4vw, 54px);
      font-weight: 800;
      line-height: 0.95;
      text-transform: uppercase;
      overflow-wrap: anywhere;
    }}
    .manual-mark {{
      width: 12px;
      height: 12px;
      flex: 0 0 auto;
      background: var(--blueprint);
      box-shadow: 0 0 0 4px rgba(93, 124, 255, 0.16);
    }}
    .manual-subtitle {{
      color: rgba(242, 239, 230, 0.76);
      font-family: var(--font-mono);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      overflow-wrap: anywhere;
    }}
    .blueprint-rule {{
      width: min(520px, 100%);
      height: 5px;
      background-image: repeating-linear-gradient(
        90deg,
        var(--blueprint) 0 18px,
        transparent 18px 28px
      );
      opacity: 0.8;
    }}
    .manual-topbar .actions {{
      position: relative;
      z-index: 1;
      align-self: flex-start;
    }}
    .manual-topbar button {{
      border-color: rgba(93, 124, 255, 0.38);
      background: rgba(93, 124, 255, 0.12);
      color: var(--manual-ink);
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .manual-topbar button.primary {{
      background: var(--blueprint);
      color: #081021;
      border-color: var(--blueprint);
    }}
    .manual-topbar button.primary:hover {{
      background: #7f95ff;
    }}
    h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 680;
      letter-spacing: 0;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    button {{
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      border-radius: 6px;
      min-height: 34px;
      padding: 0 12px;
      font: inherit;
      cursor: pointer;
    }}
    button.primary {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }}
    button.primary:hover {{ background: var(--accent-dark); }}
    button.danger {{ color: var(--danger); }}
    button:focus, input:focus, textarea:focus {{
      outline: 2px solid var(--focus);
      outline-offset: 1px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.65fr) minmax(360px, 0.85fr);
      gap: 14px;
      align-items: start;
    }}
    .decision-summary {{
      background: #0b1020;
      color: #f4f7fb;
      border-color: rgba(93, 124, 255, 0.34);
      box-shadow: 0 12px 34px rgba(17, 24, 39, 0.13);
    }}
    .decision-summary .section-head {{
      border-color: rgba(93, 124, 255, 0.38);
    }}
    .decision-summary .status,
    .decision-summary .muted-text {{
      color: rgba(244, 247, 251, 0.72);
    }}
    .summary-body {{
      display: grid;
      grid-template-columns: minmax(300px, 1.1fr) minmax(360px, 0.9fr);
      gap: 14px;
      padding: 12px;
      align-items: start;
    }}
    .summary-copy {{
      display: grid;
      gap: 8px;
    }}
    .summary-copy p {{
      margin: 0;
      max-width: 720px;
      color: rgba(244, 247, 251, 0.78);
    }}
    .summary-overview {{
      font-size: 13px;
      line-height: 1.55;
    }}
    .summary-overview strong {{
      color: #ffffff;
    }}
    .summary-plan {{
      display: grid;
      gap: 8px;
      max-width: 780px;
    }}
    .summary-risk-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px 10px;
      align-items: center;
      border: 1px solid rgba(248, 113, 113, 0.35);
      border-radius: 8px;
      background: rgba(127, 29, 29, 0.26);
      color: rgba(254, 226, 226, 0.92);
      padding: 8px 10px;
      font-size: 12px;
      line-height: 1.35;
    }}
    .summary-risk-strip strong {{
      color: #ffffff;
      font-size: 12px;
    }}
    .summary-plan-section {{
      display: grid;
      gap: 6px;
      border: 1px solid rgba(93, 124, 255, 0.22);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.045);
      padding: 9px 10px;
    }}
    .summary-plan-title {{
      color: #ffffff;
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .summary-plan-lines {{
      display: grid;
      gap: 4px;
      margin: 0;
      padding: 0;
      list-style: none;
      color: rgba(244, 247, 251, 0.8);
      font-size: 12px;
      line-height: 1.45;
    }}
    .summary-plan-lines li {{
      overflow-wrap: anywhere;
    }}
    .watchlist-priority-groups {{
      display: grid;
      gap: 7px;
    }}
    .watchlist-group {{
      display: grid;
      gap: 5px;
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 8px;
      background: rgba(15, 23, 42, 0.28);
      padding: 7px 8px;
    }}
    .watchlist-group-high {{
      border-color: rgba(45, 212, 191, 0.48);
      background: rgba(20, 184, 166, 0.13);
    }}
    .watchlist-group-label {{
      color: rgba(244, 247, 251, 0.88);
      font-family: var(--font-mono);
      font-size: 10px;
      font-weight: 850;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .watchlist-group-items {{
      display: grid;
      gap: 4px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .watchlist-group-items li {{
      display: grid;
      gap: 2px;
      color: rgba(244, 247, 251, 0.78);
      font-size: 12px;
      line-height: 1.35;
    }}
    .watchlist-group-items strong {{
      color: #ffffff;
      font-size: 12px;
    }}
    .watchlist-group-note {{
      margin: 0;
      color: rgba(244, 247, 251, 0.72);
      font-size: 12px;
      line-height: 1.4;
    }}
    .summary-plan-details {{
      border-top: 1px solid rgba(93, 124, 255, 0.18);
      padding-top: 6px;
    }}
    .summary-plan-details summary {{
      color: rgba(244, 247, 251, 0.86);
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 800;
    }}
    .summary-plan-detail-lines {{
      margin-top: 6px;
      color: rgba(244, 247, 251, 0.74);
    }}
    .summary-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
    }}
    .summary-meta-chip {{
      border: 1px solid rgba(93, 124, 255, 0.32);
      border-radius: 999px;
      color: rgba(244, 247, 251, 0.76);
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 4px 8px;
    }}
    .decision-rail {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }}
    .decision-rail-card {{
      display: grid;
      gap: 4px;
      min-width: 0;
      border: 1px solid rgba(93, 124, 255, 0.28);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.06);
      padding: 9px 10px;
    }}
    .decision-rail-card strong {{
      color: #ffffff;
      font-size: 14px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }}
    .decision-rail-label,
    .decision-rail-detail {{
      color: rgba(244, 247, 251, 0.72);
      font-size: 11px;
      font-weight: 750;
    }}
    .decision-rail-label {{
      text-transform: uppercase;
    }}
    .decision-rail-detail {{
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    .summary-directory {{
      display: grid;
      gap: 8px;
    }}
    .directory-title {{
      color: rgba(244, 247, 251, 0.72);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .directory-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .directory-link {{
      border: 1px solid rgba(93, 124, 255, 0.32);
      border-radius: 8px;
      background: rgba(93, 124, 255, 0.12);
      color: #f4f7fb;
      display: grid;
      gap: 2px;
      min-height: 52px;
      padding: 8px 10px;
      text-decoration: none;
    }}
    .directory-link:hover {{
      border-color: rgba(244, 247, 251, 0.52);
      background: rgba(93, 124, 255, 0.18);
    }}
    .directory-link span {{
      font-size: 12px;
      font-weight: 800;
    }}
    .directory-link small {{
      color: rgba(244, 247, 251, 0.75);
      font-size: 11px;
      line-height: 1.25;
    }}
    .fresh-discovery-status {{
      margin-bottom: 12px;
    }}
    .fresh-discovery-sector-status {{
      margin-bottom: 12px;
    }}
    .entry-list-screening-status {{
      margin-bottom: 12px;
    }}
    .earnings-calendar-watch-status {{
      margin-bottom: 12px;
    }}
    .event-calendar-watch-status {{
      margin-bottom: 12px;
    }}
    .trigger-monitor-status {{
      margin-bottom: 12px;
    }}
    .ticker-quote-news-coverage-status {{
      margin-bottom: 12px;
    }}
    .postclose-review-status {{
      margin-bottom: 12px;
    }}
    .postclose-observation-status {{
      margin-bottom: 12px;
    }}
    .source-capabilities-status {{
      margin-bottom: 12px;
    }}
    .source-health-probes-status {{
      margin-bottom: 12px;
    }}
    .source-diagnostic-details > summary.section-head {{
      cursor: pointer;
      justify-content: flex-start;
      list-style: none;
    }}
    .source-diagnostic-details > summary.section-head .status-pill {{
      margin-left: auto;
    }}
    .source-diagnostic-details > summary.section-head::-webkit-details-marker {{
      display: none;
    }}
    .source-diagnostic-details:not([open]) > summary.section-head {{
      border-bottom: 0;
    }}
    .source-diagnostic-toggle {{
      display: inline-grid;
      place-items: center;
      width: 20px;
      height: 20px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-family: var(--font-mono);
      font-size: 13px;
      font-weight: 800;
      line-height: 1;
      flex: 0 0 auto;
    }}
    .source-diagnostic-toggle::before {{
      content: "+";
    }}
    .source-diagnostic-details[open] .source-diagnostic-toggle::before {{
      content: "-";
    }}
    .institutional-actionability-gate {{
      margin-bottom: 12px;
    }}
    .fresh-discovery-body {{
      display: grid;
      gap: 10px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .fresh-discovery-sector-body {{
      display: grid;
      gap: 10px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .postclose-review-body {{
      display: grid;
      gap: 10px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .postclose-observation-body {{
      display: grid;
      gap: 10px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .fresh-discovery-body p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .fresh-discovery-sector-body p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .postclose-review-body p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .postclose-observation-body p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .source-status-body {{
      display: grid;
      gap: 10px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .earnings-calendar-body {{
      display: grid;
      gap: 10px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .event-calendar-body {{
      display: grid;
      gap: 10px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .institutional-gate-body {{
      display: grid;
      gap: 10px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .source-status-body p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .earnings-calendar-body p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .event-calendar-body p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .institutional-gate-body p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .observation-list {{
      display: grid;
      gap: 8px;
    }}
    .source-status-list {{
      display: grid;
      gap: 8px;
    }}
    .sector-leader-list {{
      display: grid;
      gap: 8px;
    }}
    .sector-leader-item {{
      display: grid;
      grid-template-columns: minmax(180px, 1fr) minmax(170px, 1fr) auto auto auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: #ffffff;
    }}
    .sector-name-cell,
    .sector-leader-cell {{
      display: grid;
      gap: 1px;
      min-width: 0;
    }}
    .observation-item {{
      display: grid;
      grid-template-columns: minmax(180px, 1fr) auto auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: #ffffff;
    }}
    .observation-name {{
      display: grid;
      gap: 1px;
      min-width: 0;
    }}
    .source-status-item {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto auto minmax(180px, 1fr);
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: #ffffff;
    }}
    .source-status-copy {{
      display: grid;
      gap: 1px;
      min-width: 0;
    }}
    .ticker-coverage-detail {{
      display: grid;
      gap: 3px;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .ticker-coverage-detail .metric-label {{
      line-height: 1.35;
    }}
    .entry-list-screening-details {{
      display: grid;
      gap: 3px;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .entry-list-screening-details .metric-label {{
      line-height: 1.35;
    }}
    .entry-list-screening-details strong {{
      color: var(--ink);
      font-weight: 800;
    }}
    .macro-summary-shell {{
      display: grid;
      gap: 10px;
    }}
    .macro-summary-head {{
      display: grid;
      grid-template-columns: 150px minmax(0, 1fr);
      gap: 10px;
      align-items: stretch;
    }}
    .macro-score-card {{
      display: grid;
      align-content: center;
      justify-items: center;
      gap: 4px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #ffffff;
    }}
    .macro-score-value {{
      color: var(--ink);
      font-size: 34px;
      font-weight: 850;
      font-variant-numeric: tabular-nums;
      line-height: 1;
    }}
    .macro-score-label,
    .macro-score-tier,
    .macro-summary-chip,
    .macro-kv-label {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    .macro-score-tier {{
      color: var(--accent);
    }}
    .macro-summary-copy {{
      display: grid;
      gap: 10px;
      align-content: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #ffffff;
    }}
    .macro-summary-copy p {{
      margin: 0;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.5;
    }}
    .macro-summary-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .macro-summary-chip {{
      border: 1px solid #d8e3ee;
      border-radius: 999px;
      padding: 4px 8px;
      background: #f7fafc;
    }}
    .macro-kv-value {{
      min-width: 0;
      color: var(--ink);
      overflow-wrap: anywhere;
    }}
    .macro-info-panel {{
      display: grid;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #ffffff;
    }}
    .macro-panel-title {{
      color: var(--ink);
      font-size: 12px;
      font-weight: 800;
    }}
    .macro-kv-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
      gap: 8px;
    }}
    .macro-kv-cell,
    .macro-diagnostic-row {{
      display: grid;
      gap: 2px;
      min-width: 0;
      border: 1px solid #e8edf3;
      border-radius: 6px;
      padding: 7px;
      background: #fbfcfd;
    }}
    .macro-kv-link,
    .macro-metric-link {{
      color: inherit;
      text-decoration: none;
    }}
    .macro-kv-link:hover,
    .macro-metric-link:hover {{
      border-color: var(--accent);
      background: #f0f7ff;
    }}
    .macro-diagnostic-detail {{
      padding: 0;
    }}
    .macro-diagnostic-grid {{
      display: grid;
      gap: 8px;
      padding: 0 10px 10px;
    }}
    .macro-trend-panel {{
      gap: 10px;
    }}
    .macro-chart-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 10px;
    }}
    .macro-trend-chart {{
      display: grid;
      gap: 8px;
      border: 1px solid #e8edf3;
      border-radius: 8px;
      padding: 10px;
      background: #ffffff;
      scroll-margin-top: 14px;
    }}
    .macro-chart-head {{
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 8px;
    }}
    .macro-chart-head h3 {{
      margin: 0;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.2;
    }}
    .macro-chart-head span,
    .macro-chart-unit {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }}
    .macro-chart-svg {{
      display: block;
      width: 100%;
      height: auto;
      min-height: 132px;
      overflow: visible;
    }}
    .macro-chart-axis {{
      stroke: #d7dee8;
      stroke-width: 1;
    }}
    .macro-chart-line {{
      fill: none;
      stroke: var(--accent);
      stroke-width: 2.5;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .macro-chart-last-point {{
      fill: #ffffff;
      stroke: var(--accent);
      stroke-width: 2;
    }}
    .macro-chart-label {{
      fill: var(--muted);
      font-family: var(--font-mono);
      font-size: 10px;
    }}
    .macro-chart-label-end,
    .macro-chart-latest {{
      text-anchor: end;
    }}
    .artifact-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .artifact-link {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 8px;
      background: #ffffff;
      color: var(--ink);
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
    }}
    .status-pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    .status-covered {{
      border-color: #abefc6;
      color: #067647;
      background: #ecfdf3;
    }}
    .status-pending,
    .status-baseline_only,
    .status-missing,
    .status-sector_only,
    .status-blocked {{
      border-color: #fedf89;
      color: #93370d;
      background: #fffaeb;
    }}
    .coverage-metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
      gap: 8px;
    }}
    .coverage-metrics > div,
    .coverage-metrics > a {{
      display: block;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: #ffffff;
    }}
    .metric-value {{
      display: block;
      color: var(--ink);
      font-family: var(--font-mono);
      font-weight: 800;
      font-variant-numeric: tabular-nums;
    }}
    .metric-label {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      border-top: 2px solid var(--blueprint);
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
    }}
    h2 {{
      margin: 0;
      font-size: 15px;
      font-weight: 650;
      letter-spacing: 0;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(160px, 1fr));
      gap: 10px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }}
    label {{
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    input, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 8px;
      color: var(--ink);
      background: #fff;
      font: inherit;
      line-height: 1.35;
      min-width: 0;
    }}
    textarea {{
      min-height: 36px;
      overflow: hidden;
      resize: vertical;
      field-sizing: content;
    }}
    .data-note {{
      border-bottom: 1px solid var(--line);
      padding: 7px 12px;
      color: var(--muted);
      background: #fbfcfd;
      font-size: 12px;
    }}
    .plan-change-summary {{
      display: grid;
      gap: 8px;
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      background: #f8fbff;
    }}
    .change-groups {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .ticker-chip {{
      display: inline-flex;
      align-items: center;
      margin: 3px 4px 0 0;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      padding: 2px 7px;
      color: var(--ink);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 700;
    }}
    .plan-overview {{
      display: grid;
      border-bottom: 1px solid var(--line);
      background: #f9fbff;
    }}
    .overview-row {{
      display: grid;
      grid-template-columns: 150px 112px minmax(220px, 1.2fr) minmax(115px, 0.55fr) minmax(150px, 0.8fr);
      gap: 8px;
      align-items: start;
      padding: 7px 12px;
      border-bottom: 1px solid #e8edf3;
      min-height: 44px;
      cursor: pointer;
    }}
    .overview-row:hover {{
      background: #f3f6ff;
    }}
    .overview-row:focus {{
      outline: 2px solid var(--focus);
      outline-offset: -2px;
    }}
    .overview-row:last-child {{
      border-bottom: 0;
    }}
    .overview-identity {{
      display: grid;
      gap: 1px;
    }}
    .overview-ticker {{
      font-weight: 750;
      font-variant-numeric: tabular-nums;
    }}
    .overview-name {{
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .overview-price {{
      color: var(--blueprint);
      font-size: 12px;
      font-weight: 750;
      font-variant-numeric: tabular-nums;
    }}
    .overview-bucket {{
      justify-self: start;
    }}
    .overview-action,
    .overview-risk {{
      overflow: visible;
      overflow-wrap: anywhere;
      text-overflow: clip;
      white-space: normal;
      line-height: 1.35;
    }}
    .overview-risk {{
      color: var(--danger);
      font-weight: 650;
    }}
    .overview-levels .level-chip {{
      min-height: 24px;
      padding: 2px 7px;
    }}
    .trigger-distance {{
      display: inline-flex;
      align-items: center;
      margin: 0 6px 6px 0;
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 800;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}
    .distance-triggered {{
      background: #e8f8ef;
      border: 1px solid #9bd7b4;
      color: var(--success);
    }}
    .distance-near {{
      background: #fff7e6;
      border: 1px solid #e7c37c;
      color: var(--warning);
    }}
    .distance-far {{
      background: #eef4ff;
      border: 1px solid #bfd0ff;
      color: #3655a7;
    }}
    .edit-section {{
      border-top: 1px solid var(--line);
      background: #fff;
    }}
    .edit-section > summary,
    .developer-output > summary {{
      cursor: pointer;
      padding: 10px 12px;
      color: var(--ink);
      font-weight: 750;
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    .calendar-table-wrap {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
    }}
    .calendar-desk-list {{
      display: grid;
      gap: 8px;
    }}
    .calendar-desk-row {{
      display: grid;
      gap: 7px;
      border: 1px solid #dbe4ee;
      border-radius: 8px;
      background: #ffffff;
      padding: 9px 10px;
    }}
    .calendar-primary-line {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
    }}
    .calendar-primary-copy {{
      display: grid;
      gap: 2px;
      min-width: 0;
    }}
    .calendar-primary-copy strong {{
      color: var(--ink);
      font-size: 14px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }}
    .calendar-date,
    .calendar-kicker {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }}
    .calendar-secondary-line {{
      display: grid;
      grid-template-columns: minmax(120px, 0.55fr) minmax(130px, 0.55fr) minmax(180px, 1fr) minmax(220px, 1.1fr);
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .calendar-secondary-line > span {{
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .calendar-secondary-line strong {{
      color: var(--ink);
      font-size: 11px;
      text-transform: uppercase;
    }}
    .calendar-scope-chip {{
      display: inline-flex;
      align-items: center;
      margin: 0 4px 4px 0;
      border: 1px solid #c7d7ea;
      border-radius: 999px;
      background: #f5f8fc;
      color: #29415f;
      padding: 2px 7px;
      font-size: 11px;
      font-weight: 750;
    }}
    .calendar-detail-table {{
      display: grid;
      gap: 8px;
    }}
    .calendar-detail-table > summary {{
      cursor: pointer;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      text-align: left;
      font-size: 12px;
      font-weight: 650;
      background: #fbfcfd;
    }}
    .stock-editor-table th:nth-child(1) {{ width: 180px; }}
    .stock-editor-table th:nth-child(2) {{ width: 300px; }}
    .stock-editor-table th:nth-child(3) {{ width: 430px; }}
    .stock-editor-table th:nth-child(4) {{ width: 300px; }}
    .stock-editor-table th:nth-child(5) {{ width: 54px; }}
    .macro-health-scorecard,
    .earnings-calendar-table,
    .event-calendar-table {{
      table-layout: auto;
    }}
    .macro-health-scorecard {{
      min-width: 680px;
    }}
    .calendar-source-table {{
      min-width: 760px;
    }}
    .calendar-event-table {{
      min-width: 1080px;
    }}
    .identity-cell,
    .classification-cell,
    .plan-panel {{
      display: grid;
      gap: 8px;
    }}
    .cell-label {{
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
    }}
    .short-textarea {{
      min-height: 34px;
    }}
    .strategy-textarea {{
      min-height: 54px;
    }}
    .notes-textarea {{
      min-height: 82px;
    }}
    .strategy-textarea {{
      max-height: 180px;
      overflow: auto;
    }}
    .evidence-drawer {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
    }}
    .evidence-drawer summary {{
      cursor: pointer;
      padding: 6px 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .evidence-drawer ul {{
      margin: 0;
      padding: 0 10px 10px 24px;
    }}
    .evidence-drawer li {{
      margin: 4px 0;
      overflow-wrap: anywhere;
    }}
    .bucket-pill {{
      width: fit-content;
      border: 1px solid #9dc7c2;
      border-radius: 999px;
      background: #effaf8;
      color: #0b5f59;
      padding: 3px 9px;
      font-size: 12px;
      font-weight: 700;
    }}
    .plan-block {{
      display: grid;
      gap: 3px;
    }}
    .plan-label {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .plan-text {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      padding: 6px 7px;
      min-height: 30px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    .level-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .level-chip {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      padding: 4px 8px;
      min-height: 28px;
    }}
    .level-label {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }}
    .level-value {{
      font-variant-numeric: tabular-nums;
      font-weight: 650;
    }}
    .muted-text {{
      color: var(--muted);
      font-size: 12px;
    }}
    .row-actions {{
      text-align: center;
    }}
    .row-highlight {{
      animation: rowFlash 1.6s ease-out;
      background: #f0fbf8;
    }}
    @keyframes rowFlash {{
      0% {{ background: #dff8f2; }}
      100% {{ background: transparent; }}
    }}
    .preview {{
      display: grid;
      gap: 10px;
      padding: 12px;
    }}
    pre {{
      margin: 0;
      max-height: 360px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      line-height: 1.45;
    }}
    .tabs {{
      display: flex;
      gap: 6px;
      padding: 0 12px 12px;
    }}
    .right-rail {{
      position: sticky;
      top: 12px;
      display: grid;
      gap: 14px;
    }}
    .execution-checklist ol {{
      margin: 0;
      padding: 12px 12px 12px 34px;
    }}
    .execution-checklist li {{
      margin: 8px 0;
    }}
    .developer-output {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .tab-active {{
      border-color: var(--accent);
      color: var(--accent);
    }}
    .status {{
      color: var(--muted);
      font-size: 12px;
      min-height: 18px;
    }}
    @media (max-width: 960px) {{
      main {{ padding: 12px; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      .manual-topbar {{ padding: 16px; }}
      .manual-title {{ font-size: clamp(28px, 10vw, 42px); }}
      .manual-meta {{ gap: 6px 10px; }}
      .manual-subtitle {{ line-height: 1.45; }}
      .actions {{ justify-content: flex-start; }}
      .summary-body {{ grid-template-columns: 1fr; }}
      .decision-rail {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .grid {{ grid-template-columns: 1fr; }}
      .right-rail {{ position: static; }}
      .meta-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .calendar-secondary-line {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .overview-row {{
        grid-template-columns: 132px 106px minmax(180px, 1fr);
      }}
      .overview-risk,
      .overview-levels {{
        grid-column: 3;
      }}
    }}
    @media (max-width: 760px) {{
      .stack-table-wrap {{ overflow-x: visible; }}
      .stack-table,
      .stack-table tbody,
      .stack-table tr,
      .stack-table td {{ display: block; width: 100%; }}
      .stack-table thead {{ display: none; }}
      .stock-row {{
        padding: 12px;
        border-bottom: 1px solid var(--line);
      }}
      .stack-table td {{
        border-bottom: 0;
        padding: 6px 0;
      }}
      .row-actions {{
        text-align: right;
      }}
      .notes-textarea {{
        min-height: 64px;
      }}
    }}
    @media (max-width: 520px) {{
      .meta-grid {{ grid-template-columns: 1fr; }}
      .change-groups {{ grid-template-columns: 1fr; }}
      .directory-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }}
      .directory-link {{ min-height: 44px; padding: 7px 8px; }}
      .directory-link small {{ display: none; }}
      .decision-rail {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }}
      .decision-rail-card {{ padding: 8px; }}
      .decision-rail-detail {{ display: none; }}
      .calendar-primary-line {{ grid-template-columns: 1fr; }}
      .calendar-secondary-line {{ grid-template-columns: 1fr; gap: 5px; }}
      .calendar-secondary-line > span {{ display: block; }}
      .overview-row {{
        grid-template-columns: 1fr;
        align-items: start;
      }}
      .overview-risk,
      .overview-levels {{
        grid-column: auto;
      }}
      .overview-action,
      .overview-risk {{
        white-space: normal;
        overflow: visible;
        text-overflow: clip;
      }}
      .observation-item,
      .source-status-item {{
        grid-template-columns: 1fr;
        align-items: start;
      }}
    }}
    @media (max-width: 380px) {{
      .directory-grid {{ grid-template-columns: 1fr; }}
      .decision-rail {{ grid-template-columns: 1fr; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .row-highlight {{ animation: none; }}
    }}
  </style>
</head>
<body class="blueprint-workbench">
  <main id="stock-pool-root">
    <div class="shell">
      <div class="topbar manual-topbar">
        <div class="manual-title-group">
          <div class="manual-meta">
            <span>Local Stock Pool</span>
            <span>{target_date or "Unscheduled"}</span>
            <span>{analysis_time or "No Snapshot Time"}</span>
          </div>
          <h1 class="manual-title"><span class="manual-mark" aria-hidden="true"></span><span>{pool_name}</span></h1>
          <div class="manual-subtitle">Trading Plan Cockpit / Longbridge Overlay</div>
          <div class="blueprint-rule" aria-hidden="true"></div>
        </div>
        <div class="actions">
          <button type="button" data-action="add">+</button>
          <button type="button" data-action="download-pool">Export Pool</button>
          <button type="button" class="primary" data-action="download-request">Export Request</button>
        </div>
      </div>
      {decision_summary}
      {main_status_sections}
      <div class="grid">
        <section id="local-stock-pool">
          <div class="section-head">
            <h2>股票池</h2>
            <div class="status" id="status"></div>
          </div>
          {plan_source_note}
          {change_summary}
          {plan_overview}
          <details class="edit-section">
            <summary>Edit stock pool and request fields</summary>
            <div class="meta-grid">
              <label>Pool<input id="pool-name" value="{pool_name}"></label>
              <label>TDX vipdoc<input id="tdx-path" value="{tdx_path}"></label>
              <label>Target date<input id="target-date" value="{target_date}"></label>
              <label>Analysis time<input id="analysis-time" value="{analysis_time}"></label>
            </div>
            <div class="table-wrap stack-table-wrap">
              <table class="stock-editor-table stack-table">
                <thead>
                  <tr>
                    <th>Ticker / Name</th>
                    <th>Classification</th>
                    <th>Trading Plan</th>
                    <th>Notes</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody id="stock-rows">
                  {pool_rows}
                </tbody>
              </table>
            </div>
          </details>
        </section>
        <section class="right-rail">
          <div class="section-head">
            <h2>输出</h2>
          </div>
          {execution_checklist}
          <details class="developer-output">
            <summary>Developer output</summary>
          <div class="tabs">
            <button type="button" class="tab-active" data-preview="request">Request</button>
            <button type="button" data-preview="pool">Pool</button>
            <button type="button" data-preview="report">Report</button>
          </div>
          <div class="preview">
            <pre id="request-preview">{request_payload_text}</pre>
            <pre id="pool-preview" hidden>{pool_payload_text}</pre>
            <pre id="report-preview" hidden>{shortlist_report_text}</pre>
          </div>
          </details>
        </section>
      </div>
      {source_status_sections}
    </div>
  </main>
  <script>
    window.__LOCAL_STOCK_POOL_PACKAGE__ = {package_json};
    const schemaVersion = "local_stock_pool/v1";
    const rows = document.getElementById("stock-rows");
    const statusEl = document.getElementById("status");
    const requestPreview = document.getElementById("request-preview");
    const poolPreview = document.getElementById("pool-preview");
    const reportPreview = document.getElementById("report-preview");
    const planSnapshotsByTicker = Object.fromEntries(
      (window.__LOCAL_STOCK_POOL_PACKAGE__.local_stock_pool.stocks || [])
        .filter((stock) => stock.ticker && stock.plan_snapshot)
        .map((stock) => [stock.ticker, stock.plan_snapshot])
    );

    function splitList(value) {{
      return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
    }}
    function escapeHtml(value) {{
      return String(value || "").replace(/[&<>"']/g, (char) => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }}[char]));
    }}
    function cellInput(row, field) {{
      return row.querySelector(`[data-field="${{field}}"]`);
    }}
    function normalizeTicker(value) {{
      const ticker = String(value || "").trim().toUpperCase().replace(/\\s+/g, "");
      if (!ticker) return "";
      if (ticker.endsWith(".SH")) return ticker;
      if (ticker.endsWith(".SS")) return ticker.slice(0, -3) + ".SH";
      if (ticker.endsWith(".SZ") || ticker.endsWith(".BJ")) return ticker;
      const digits = ticker.replace(/\\D/g, "");
      if (digits.length === 6) {{
        if (/^[69]/.test(digits)) return `${{digits}}.SH`;
        if (/^[84]/.test(digits)) return `${{digits}}.BJ`;
        return `${{digits}}.SZ`;
      }}
      return ticker;
    }}
    function collectPool() {{
      const stocks = Array.from(rows.querySelectorAll("tr")).map((row) => {{
        const stock = {{
          ticker: normalizeTicker(cellInput(row, "ticker")?.value),
          name: cellInput(row, "name")?.value.trim() || normalizeTicker(cellInput(row, "ticker")?.value),
          groups: splitList(cellInput(row, "groups")?.value),
          tags: splitList(cellInput(row, "tags")?.value),
          strategy_tags: splitList(cellInput(row, "strategy_tags")?.value),
          notes: cellInput(row, "notes")?.value.trim() || ""
        }};
        if (planSnapshotsByTicker[stock.ticker]) {{
          stock.plan_snapshot = planSnapshotsByTicker[stock.ticker];
        }}
        return stock;
      }}).filter((stock) => stock.ticker);
      return {{
        schema_version: schemaVersion,
        name: document.getElementById("pool-name").value.trim() || "local_stock_pool",
        stocks,
        groups: window.__LOCAL_STOCK_POOL_PACKAGE__.local_stock_pool.groups || [],
        strategy_rules: window.__LOCAL_STOCK_POOL_PACKAGE__.local_stock_pool.strategy_rules || [],
        ui_contract: window.__LOCAL_STOCK_POOL_PACKAGE__.local_stock_pool.ui_contract
      }};
    }}
    function collectRequest() {{
      const request = {{
        template_name: "month_end_shortlist",
        target_date: document.getElementById("target-date").value.trim(),
        local_stock_pool: collectPool()
      }};
      const analysisTime = document.getElementById("analysis-time").value.trim();
      const tdxPath = document.getElementById("tdx-path").value.trim();
      if (analysisTime) request.analysis_time = analysisTime;
      if (tdxPath) {{
        request.local_daily_bars_source = {{
          kind: "tdx_vipdoc",
          path: tdxPath,
          usage_boundary: "local EOD technical supplement; validate live price/news/fundamentals through provider-backed workflow before trading decisions."
        }};
      }}
      if (window.__LOCAL_STOCK_POOL_PACKAGE__.month_end_request?.macro_health_overlay) {{
        request.macro_health_overlay = window.__LOCAL_STOCK_POOL_PACKAGE__.month_end_request.macro_health_overlay;
      }}
      if (window.__LOCAL_STOCK_POOL_PACKAGE__.entry_list_promotion) {{
        request.entry_list_promotion = window.__LOCAL_STOCK_POOL_PACKAGE__.entry_list_promotion;
      }}
      return request;
    }}
    function refresh() {{
      poolPreview.textContent = JSON.stringify(collectPool(), null, 2);
      requestPreview.textContent = JSON.stringify(collectRequest(), null, 2);
      statusEl.textContent = `${{collectPool().stocks.length}} names`;
    }}
    function autosizeTextarea(textarea) {{
      if (!textarea) return;
      textarea.style.height = "auto";
      textarea.style.height = `${{textarea.scrollHeight + 2}}px`;
    }}
    function resizeAllTextareas(root = document) {{
      root.querySelectorAll("textarea").forEach(autosizeTextarea);
    }}
    function addRow(stock = {{}}) {{
      const row = document.createElement("tr");
      row.className = "stock-row";
      row.innerHTML = `
        <td class="identity-cell">
          <input data-field="ticker" value="${{escapeHtml(stock.ticker || "")}}">
          <input data-field="name" value="${{escapeHtml(stock.name || "")}}">
        </td>
        <td class="classification-cell">
          <label class="cell-label">Groups<textarea data-field="groups" class="short-textarea">${{escapeHtml((stock.groups || []).join(", "))}}</textarea></label>
          <label class="cell-label">Tags<textarea data-field="tags" class="short-textarea">${{escapeHtml((stock.tags || []).join(", "))}}</textarea></label>
          <label class="cell-label">Strategy<textarea data-field="strategy_tags" class="strategy-textarea">${{escapeHtml((stock.strategy_tags || []).join(", "))}}</textarea></label>
        </td>
        <td class="plan-cell">
          <div class="plan-panel">
            <span class="bucket-pill">Manual</span>
            <div class="plan-block"><span class="plan-label">Plan Levels</span><div class="level-list"><span class="muted-text">No imported plan levels</span></div></div>
          </div>
        </td>
        <td class="notes-cell"><textarea data-field="notes" class="notes-textarea">${{escapeHtml(stock.notes || "")}}</textarea></td>
        <td class="row-actions"><button type="button" class="icon-button danger" data-action="remove" title="Remove">-</button></td>
      `;
      rows.appendChild(row);
      resizeAllTextareas(row);
      refresh();
    }}
    function focusDetailRow(targetId) {{
      const target = document.getElementById(targetId);
      if (!target) return;
      target.scrollIntoView({{ behavior: "smooth", block: "center" }});
      target.classList.remove("row-highlight");
      void target.offsetWidth;
      target.classList.add("row-highlight");
      target.setAttribute("tabindex", "-1");
      target.focus({{ preventScroll: true }});
    }}
    function downloadJson(filename, payload) {{
      const blob = new Blob([JSON.stringify(payload, null, 2) + "\\n"], {{ type: "application/json;charset=utf-8" }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    }}
    window.downloadMonthEndRequest = () => downloadJson("month-end-shortlist-local-stock-pool.request.json", collectRequest());
    document.body.addEventListener("input", (event) => {{
      if (event.target?.matches?.("textarea")) autosizeTextarea(event.target);
      refresh();
    }});
    document.body.addEventListener("click", (event) => {{
      const actionTarget = event.target?.closest?.("[data-action]");
      const action = actionTarget?.dataset?.action;
      if (action === "add") addRow();
      if (action === "remove") {{
        actionTarget.closest("tr")?.remove();
        refresh();
      }}
      if (action === "focus-row") {{
        focusDetailRow(actionTarget?.dataset?.target);
      }}
      if (action === "download-pool") downloadJson("local-stock-pool.json", collectPool());
      if (action === "download-request") window.downloadMonthEndRequest();
      const previewTarget = event.target?.closest?.("[data-preview]");
      const preview = previewTarget?.dataset?.preview;
      if (preview) {{
        requestPreview.hidden = preview !== "request";
        poolPreview.hidden = preview !== "pool";
        reportPreview.hidden = preview !== "report";
        document.querySelectorAll("[data-preview]").forEach((button) => button.classList.toggle("tab-active", button.dataset.preview === preview));
      }}
    }});
    document.body.addEventListener("keydown", (event) => {{
      const actionTarget = event.target?.closest?.("[data-action]");
      const action = actionTarget?.dataset?.action;
      if (action === "focus-row" && (event.key === "Enter" || event.key === " ")) {{
        event.preventDefault();
        focusDetailRow(actionTarget.dataset.target);
      }}
    }});
    resizeAllTextareas();
    refresh();
  </script>
</body>
</html>
"""
    return normalize_workflow_display_ticker_text(rendered)


def build_local_stock_pool_manager_package(
    raw_pool: dict[str, Any],
    *,
    trading_plan_result: dict[str, Any] | None = None,
    tdx_vipdoc_path: str = "",
    target_date: str = "",
    analysis_time: str = "",
    institutional_ready: bool = False,
    earnings_calendar_payloads: list[Any] | None = None,
    earnings_calendar_watchlist: list[Any] | None = None,
    earnings_calendar_lookahead_days: int = DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS,
    event_calendar_payloads: list[Any] | None = None,
    event_calendar_watchlist: list[Any] | None = None,
    event_calendar_lookahead_days: int = DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS,
    thesis_check_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    previous_pool = normalize_local_stock_pool(raw_pool)
    local_stock_pool = previous_pool
    imported_pool: dict[str, Any] = {}
    if isinstance(trading_plan_result, dict) and trading_plan_result:
        imported_pool = build_local_stock_pool_from_trading_plan_result(
            trading_plan_result,
            pool_name=clean_text(raw_pool.get("name")) or "trading-plan-import",
        )
        local_stock_pool = merge_stock_pools(local_stock_pool, imported_pool)
    if not local_stock_pool:
        if institutional_ready:
            local_stock_pool = empty_local_stock_pool_template(raw_pool)
        else:
            local_stock_pool = normalize_local_stock_pool(
                {
                    "name": "local_stock_pool",
                    "stocks": [
                        {
                            "ticker": "000001.SZ",
                            "name": "sample",
                            "groups": ["watch"],
                            "tags": [],
                        }
                    ],
                }
            )
    local_stock_pool = enrich_local_stock_pool_for_monitoring(local_stock_pool)
    month_end_request = build_month_end_request(
        local_stock_pool,
        tdx_vipdoc_path=tdx_vipdoc_path,
        target_date=target_date,
        analysis_time=analysis_time,
        fresh_discovery_required=bool(institutional_ready or imported_pool.get("stocks")),
    )
    trading_plan_macro_overlay = extract_macro_health_overlay(trading_plan_result)
    trading_plan_macro_live_fetch_summary = extract_macro_health_overlay_live_fetch_summary(trading_plan_result)
    trading_plan_macro_seed_summary = extract_macro_health_overlay_seed_summary(trading_plan_result)
    if trading_plan_macro_overlay:
        month_end_request["macro_health_overlay"] = trading_plan_macro_overlay
    if trading_plan_macro_live_fetch_summary:
        month_end_request["macro_health_overlay_live_fetch_summary"] = trading_plan_macro_live_fetch_summary
    if trading_plan_macro_seed_summary:
        month_end_request["macro_health_overlay_seed_summary"] = trading_plan_macro_seed_summary
    package = {
        "workflow_kind": "local_stock_pool_manager",
        "schema_version": "local_stock_pool_manager/v1",
        "local_stock_pool": local_stock_pool,
        "month_end_request": month_end_request,
        "ui_summary": build_ui_summary(local_stock_pool, previous_pool, imported_pool),
    }
    if trading_plan_macro_overlay:
        package["macro_health_overlay"] = trading_plan_macro_overlay
    if trading_plan_macro_live_fetch_summary:
        package["macro_health_overlay_live_fetch_summary"] = trading_plan_macro_live_fetch_summary
    if trading_plan_macro_seed_summary:
        package["macro_health_overlay_seed_summary"] = trading_plan_macro_seed_summary
    stock_logic_check = build_stock_logic_check(package, raw_pool, trading_plan_result)
    if stock_logic_check:
        package["stock_logic_check"] = stock_logic_check
    if thesis_check_payloads:
        package["thesis_fact_check"] = build_thesis_fact_check(
            thesis_check_payloads,
            evidence_payloads=[
                payload
                for payload in (
                    raw_pool,
                    trading_plan_result,
                    package_without_generated_thesis_fact_check(package),
                )
                if isinstance(payload, dict)
            ],
        )
    base_calendar_payloads: list[Any] = [raw_pool]
    if isinstance(trading_plan_result, dict) and trading_plan_result:
        base_calendar_payloads.append(trading_plan_result)
    explicit_earnings_calendar_payloads = list(earnings_calendar_payloads or [])
    calendar_payloads: list[Any] = list(explicit_earnings_calendar_payloads) if explicit_earnings_calendar_payloads else list(base_calendar_payloads)
    calendar_watchlist: list[Any] = []
    for payload in [*base_calendar_payloads, *explicit_earnings_calendar_payloads]:
        if not isinstance(payload, dict):
            continue
        for key in EARNINGS_CALENDAR_WATCHLIST_KEYS:
            calendar_watchlist.extend(safe_list(payload.get(key)))
    calendar_watchlist.extend(earnings_calendar_watchlist or [])
    earnings_calendar_watch = build_earnings_calendar_watch(
        local_stock_pool,
        target_date=month_end_request["target_date"],
        lookahead_days=earnings_calendar_lookahead_days,
        payloads=calendar_payloads,
        watchlist_values=calendar_watchlist,
    )
    earnings_watch_summary = safe_dict(earnings_calendar_watch.get("summary"))
    if (
        earnings_watch_summary.get("source_event_count")
        or earnings_watch_summary.get("source_error_count")
        or earnings_calendar_watch.get("events")
    ):
        package["earnings_calendar_watch"] = earnings_calendar_watch
    event_payloads: list[Any] = [raw_pool]
    if isinstance(trading_plan_result, dict) and trading_plan_result:
        event_payloads.append(trading_plan_result)
    event_payloads.extend(event_calendar_payloads or [])
    event_watchlist: list[Any] = []
    for payload in event_payloads:
        if not isinstance(payload, dict):
            continue
        for key in EVENT_CALENDAR_WATCHLIST_KEYS:
            event_watchlist.extend(safe_list(payload.get(key)))
    event_watchlist.extend(event_calendar_watchlist or [])
    event_calendar_watch = build_event_calendar_watch(
        local_stock_pool,
        target_date=month_end_request["target_date"],
        lookahead_days=event_calendar_lookahead_days,
        payloads=event_payloads,
        watchlist_values=event_watchlist,
    )
    event_watch_summary = safe_dict(event_calendar_watch.get("summary"))
    if (
        event_watch_summary.get("source_event_count")
        or event_watch_summary.get("source_error_count")
        or event_calendar_watch.get("events")
    ):
        package["event_calendar_watch"] = event_calendar_watch
    package["ticker_quote_news_coverage"] = build_ticker_quote_news_coverage(package)
    package["html"] = render_local_stock_pool_manager_html(package)
    return package


def institutional_run_root(output_root: Path) -> Path:
    if output_root.name.lower() in {"html", "output", "outputs", "artifacts"}:
        return output_root.parent
    return output_root


_SECTOR_LEVEL_SUFFIX_RE = re.compile(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+$")


def _strip_sector_level_suffix(value: str) -> str:
    stripped = _SECTOR_LEVEL_SUFFIX_RE.sub("", value).strip()
    return stripped or value


def cdp_endpoint_is_reachable(endpoint: str) -> bool:
    return _browser_cdp_endpoint_is_reachable(endpoint)


def detect_codex_chrome_cdp_endpoint(start_path: Path) -> str:
    return _detect_codex_chrome_cdp_endpoint(start_path, probe=cdp_endpoint_is_reachable)


def _append_social_candidate(candidates: list[dict[str, str]], ticker: Any, name: Any, chain_name: Any = "") -> None:
    normalized_ticker = normalize_workflow_display_ticker(ticker)
    clean_name = clean_text(name)
    if not normalized_ticker and not clean_name:
        return
    identity = normalized_ticker or clean_name
    for candidate in candidates:
        if candidate.get("identity") == identity:
            if clean_name and not candidate.get("name"):
                candidate["name"] = clean_name
            if clean_text(chain_name) and not candidate.get("chain_name"):
                candidate["chain_name"] = clean_text(chain_name)
            return
    candidates.append(
        {
            "identity": identity,
            "ticker": normalized_ticker,
            "name": clean_name,
            "chain_name": clean_text(chain_name),
        }
    )


def _append_sector_leader_candidates(candidates: list[dict[str, str]], sector_views: Any) -> None:
    for row in sector_views if isinstance(sector_views, list) else []:
        if not isinstance(row, dict):
            continue
        _append_social_candidate(
            candidates,
            row.get("leader_ticker") or row.get("leader_symbol") or row.get("leader_code"),
            row.get("leader_name"),
            row.get("sector_name") or row.get("industry_name") or row.get("concept_name"),
        )


def collect_social_evidence_candidates(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    local_stock_pool = safe_dict(package.get("local_stock_pool"))
    for stock in local_stock_pool.get("stocks", []) if isinstance(local_stock_pool.get("stocks"), list) else []:
        if not isinstance(stock, dict):
            continue
        plan = safe_dict(stock.get("plan_snapshot"))
        _append_social_candidate(
            candidates,
            stock.get("ticker"),
            stock.get("name"),
            plan.get("chain_name") or stock.get("chain_name"),
        )
    if isinstance(shortlist_result, dict):
        for bucket in ("top_picks", "directly_actionable", "priority_watchlist", "near_miss_candidates", "diagnostic_scorecard"):
            for row in shortlist_result.get(bucket, []) if isinstance(shortlist_result.get(bucket), list) else []:
                if not isinstance(row, dict):
                    continue
                _append_social_candidate(
                    candidates,
                    row.get("ticker") or row.get("symbol") or row.get("code"),
                    row.get("name") or row.get("company_name"),
                    row.get("chain_name") or row.get("theme_name"),
                )
    sector_layer = safe_dict(package.get("fresh_discovery_sector_layer"))
    _append_sector_leader_candidates(candidates, sector_layer.get("sector_views"))
    if isinstance(shortlist_result, dict):
        _append_sector_leader_candidates(candidates, shortlist_result.get("sector_views"))
    return candidates[:12]


def collect_social_evidence_phrases(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None = None,
) -> list[str]:
    phrases: list[str] = []
    for candidate in collect_social_evidence_candidates(package, shortlist_result):
        chain = candidate.get("chain_name", "")
        if chain and chain.lower() != "unknown":
            phrases.append(_strip_sector_level_suffix(chain))
    sector_layer = safe_dict(package.get("fresh_discovery_sector_layer"))
    sector_views = sector_layer.get("sector_views")
    for row in sector_views if isinstance(sector_views, list) else []:
        if isinstance(row, dict):
            phrases.extend([clean_text(row.get("sector_name")), clean_text(row.get("leader_name"))])
    if isinstance(shortlist_result, dict):
        raw_sector_views = shortlist_result.get("sector_views")
        for row in raw_sector_views if isinstance(raw_sector_views, list) else []:
            if isinstance(row, dict):
                phrases.extend([clean_text(row.get("sector_name")), clean_text(row.get("leader_name"))])
        raw_themes = shortlist_result.get("emergent_theme_candidates")
        for row in raw_themes if isinstance(raw_themes, list) else []:
            if not isinstance(row, dict):
                continue
            phrases.append(clean_text(row.get("theme_name") or row.get("theme_label")))
            phrases.extend(clean_string_list(row.get("supporting_names")))
    return unique_strings(phrases)[:10]


def build_social_capture_focus_terms(
    candidates: list[dict[str, str]],
    phrases: list[str],
    query_overrides: list[str],
) -> list[str]:
    terms: list[str] = [
        *phrases,
        *query_overrides,
        *[candidate.get("name", "") for candidate in candidates],
        *[_strip_sector_level_suffix(candidate.get("chain_name", "")) for candidate in candidates],
    ]
    haystack = " ".join(clean_text(term).lower() for term in terms)
    if any(marker in haystack for marker in ("电子", "半导体", "芯片", "芯", "光", "通信", "计算机", "液冷", "photolithography", "ai")):
        terms.extend(["半导体", "芯", "光", "存", "存储", "英伟达", "Nvidia", "长鑫", "PCB", "算力", "液冷", "光模块"])
    if any(marker in haystack for marker in ("机械", "机器人", "设备", "工业母机")):
        terms.extend(["机械设备", "机器人", "工业母机", "设备"])
    if any(marker in haystack for marker in ("电力", "电网", "变压器", "电气")):
        terms.extend(["电力设备", "电网", "变压器", "特高压"])
    return unique_strings([term for term in terms if clean_text(term)])[:48]


def build_x_search_context_terms(
    candidates: list[dict[str, str]],
    phrases: list[str],
) -> list[str]:
    specific_names = {
        clean_text(candidate.get("name"))
        for candidate in candidates
        if clean_text(candidate.get("name"))
    }
    specific_names.update(
        clean_text(candidate.get("ticker"))
        for candidate in candidates
        if clean_text(candidate.get("ticker"))
    )
    terms: list[str] = [
        *phrases,
        *[_strip_sector_level_suffix(candidate.get("chain_name", "")) for candidate in candidates],
    ]
    haystack = " ".join(clean_text(term).lower() for term in terms)
    expanded_terms: list[str] = []
    if any(marker in haystack for marker in ("电子", "半导体", "芯片", "芯", "光", "通信", "计算机", "液冷", "photolithography", "ai")):
        expanded_terms.extend(["半导体", "芯", "光", "存", "存储", "英伟达", "Nvidia", "长鑫", "PCB", "算力", "液冷", "光模块"])
    if any(marker in haystack for marker in ("机械", "机器人", "设备", "工业母机")):
        expanded_terms.extend(["机械设备", "机器人", "工业母机", "设备"])
    if any(marker in haystack for marker in ("电力", "电网", "变压器", "电气")):
        expanded_terms.extend(["电力设备", "电网", "变压器", "特高压"])
    ordered_terms = [
        *expanded_terms,
        *[_strip_sector_level_suffix(candidate.get("chain_name", "")) for candidate in candidates],
        *phrases,
    ]
    return unique_strings(
        [
            term
            for term in ordered_terms
            if clean_text(term)
            and clean_text(term).lower() != "unknown"
            and clean_text(term) not in specific_names
            and not re.fullmatch(r"\d{6}(?:\.(?:SZ|SS|SH|BJ))?", clean_text(term), re.IGNORECASE)
        ]
    )[:24]


def default_x_social_account_allowlist(limit: int = 12) -> list[str]:
    fallback = ["ShanghaoJin"]
    script_dir = Path(__file__).resolve().parents[2] / "autoresearch-info-index" / "scripts"
    if script_dir.exists() and str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    try:
        from hot_topic_discovery_runtime import X_WATCHLIST_AUTHORS
    except Exception:
        return fallback[:limit]
    if not isinstance(X_WATCHLIST_AUTHORS, dict):
        return fallback[:limit]
    ranked: list[tuple[int, str]] = []
    for handle, profile in X_WATCHLIST_AUTHORS.items():
        clean_handle = clean_text(handle).lstrip("@")
        if not clean_handle:
            continue
        tier = parse_float(safe_dict(profile).get("tier"))
        ranked.append((int(tier) if tier is not None else 99, clean_handle))
    handles = unique_strings(
        [
            *fallback,
            *[handle for _tier, handle in sorted(ranked, key=lambda item: (item[0], item[1].lower()))],
        ]
    )
    return unique_strings(handles)[:limit]


def build_x_index_social_evidence_request(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None,
    *,
    output_root: Path,
) -> dict[str, Any]:
    month_end_request = safe_dict(package.get("month_end_request"))
    target_date = clean_text(month_end_request.get("target_date")) or date.today().isoformat()
    analysis_time = clean_text(month_end_request.get("analysis_time")) or target_date
    run_root = institutional_run_root(output_root)
    x_output_dir = run_root / "x-index-social-evidence"
    cdp_endpoint = detect_codex_chrome_cdp_endpoint(output_root)
    candidates = collect_social_evidence_candidates(package, shortlist_result)
    phrases = collect_social_evidence_phrases(package, shortlist_result)
    account_allowlist = default_x_social_account_allowlist()
    entity_clues: list[str] = []
    query_overrides: list[str] = []
    for candidate in candidates[:8]:
        ticker = clean_text(candidate.get("ticker"))
        name = clean_text(candidate.get("name"))
        chain = _strip_sector_level_suffix(clean_text(candidate.get("chain_name")))
        if chain and chain.lower() == "unknown":
            chain = ""
        entity_clues.extend([ticker, name])
        if chain and name:
            query_overrides.append(f"{chain} {name}")
        if name:
            query_overrides.append(name)
        if chain:
            query_overrides.append(chain)
    query_overrides = unique_strings(query_overrides)[:12]
    capture_paths = unique_strings(
        [
            str(x_output_dir / "x-capture-fixed-profile.json"),
            *[str(path) for path in default_codex_chrome_social_evidence_paths()],
        ]
    )[:12]
    x_search_context_terms = build_x_search_context_terms(candidates, phrases)
    return {
        "topic": f"A-share social evidence {target_date}",
        "analysis_time": analysis_time,
        "search_strategy": "watchlist_author_timeboxed_context_scans",
        "x_search_operator_profile": "web_recent_public",
        "keywords": unique_strings(["A-share", "China stocks", *phrases[:6]]),
        "phrase_clues": phrases,
        "entity_clues": unique_strings(entity_clues)[:12],
        "query_overrides": query_overrides,
        "x_search_context_terms": x_search_context_terms,
        "account_allowlist": account_allowlist,
        "browser_capture_paths": capture_paths,
        "capture_focus_terms": build_social_capture_focus_terms(candidates, phrases, query_overrides),
        "capture_ingest_mode": "allowlist_market_context",
        "max_capture_posts": 48,
        "generic_search_disabled": bool(account_allowlist),
        "market_relevance": unique_strings(["A-share watchlist", "trading plan", *phrases[:4]]),
        "lookback": "72h",
        "include_threads": True,
        "fulltext_capture_mode": "completeness_first",
        "hydrate_capture_details": True,
        "max_candidates": 16,
        "max_kept_posts": 10,
        "max_thread_posts": 36,
        "max_search_queries": 24,
        "same_author_scan_window_hours": 120,
        "same_author_scan_limit": 48,
        "output_dir": str(x_output_dir),
        "browser_session": {
            "strategy": "remote_debugging",
            "cdp_endpoint": cdp_endpoint,
            "required": False,
            "browser_name": "chrome",
            "wait_ms": 36000,
            "expand_click_limit": 36,
            "scroll_passes": 12,
            "stable_wait_ms": 4000,
            "blocked_retry_attempts": 3,
            "blocked_retry_wait_ms": 2500,
        },
    }


def classify_fundamental_evidence_market(ticker: str) -> str:
    normalized = clean_text(ticker).upper()
    if normalized.endswith((".SZ", ".SS", ".SH", ".BJ", ".XSHE", ".XSHG")):
        return "a_share"
    if normalized.endswith(".US"):
        return "us"
    if normalized.endswith(".HK"):
        return "hk"
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", normalized):
        return "us"
    return "unknown"


def safe_artifact_stem(value: Any, fallback: str = "stock") -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", clean_text(value))
    stem = stem.strip("._-")
    return stem or fallback


def collect_fundamental_evidence_candidates(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in collect_social_evidence_candidates(package, shortlist_result):
        ticker = clean_text(candidate.get("ticker")).upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        rows.append(
            {
                "ticker": ticker,
                "name": clean_text(candidate.get("name")),
                "chain_name": clean_text(candidate.get("chain_name")),
                "market": classify_fundamental_evidence_market(ticker),
            }
        )
    return rows[:12]


def build_ownership_fundamental_evidence_request(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None,
    *,
    output_root: Path,
) -> dict[str, Any]:
    month_end_request = safe_dict(package.get("month_end_request"))
    target_date = clean_text(month_end_request.get("target_date")) or date.today().isoformat()
    analysis_time = clean_text(month_end_request.get("analysis_time")) or target_date
    run_root = institutional_run_root(output_root)
    evidence_dir = run_root / "ownership-fundamental-evidence"
    result_path = evidence_dir / "institutional-evidence-bundle.json"
    report_path = evidence_dir / "institutional-evidence-bundle.md"
    candidates = collect_fundamental_evidence_candidates(package, shortlist_result)
    sec_tickers: list[str] = []
    a_share_stocks: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    for candidate in candidates:
        market = candidate.get("market", "unknown")
        ticker = clean_text(candidate.get("ticker")).upper()
        if market == "us":
            sec_tickers.append(ticker[:-3] if ticker.endswith(".US") else ticker)
        elif market == "a_share":
            a_share_stocks.append(candidate)
        else:
            unsupported.append(candidate)
    return {
        "schema_version": "ownership-fundamental-evidence-request/v1",
        "topic": f"Ownership and fundamental evidence {target_date}",
        "analysis_time": analysis_time,
        "target_date": target_date,
        "candidate_stocks": candidates,
        "sec_tickers": unique_strings(sec_tickers)[:8],
        "a_share_stocks": a_share_stocks[:12],
        "unsupported_stocks": unsupported,
        "output_path": str(result_path),
        "markdown_output_path": str(report_path),
        "recommended_adapters": [
            "SEC companyfacts for U.S. tickers via institutional_evidence_bundle --sec-ticker",
            "Eastmoney notice cache for A-share official-announcement context via --eastmoney-notice-stock",
            "AKShare/Eastmoney-style A-share JSON with fundamental_metrics, financial_metrics, a_share_fundamental_metrics, or fundamentals.reports as a positional bundle input",
            "Add explicit filing/fundamental/ownership JSON when available; request artifacts alone never satisfy the audit layer.",
        ],
        "auto_discovery_note": "Run the bundle command, then rerun local stock-pool manager; same-run-root auto-discovery will attach institutional-evidence-bundle.json only if it contains real evidence.",
    }


def write_ownership_fundamental_stock_inputs(request_payload: dict[str, Any], evidence_dir: Path) -> list[Path]:
    stock_input_dir = evidence_dir / "stock-inputs"
    stock_paths: list[Path] = []
    for index, stock in enumerate(safe_list(request_payload.get("a_share_stocks"))[:12], start=1):
        if not isinstance(stock, dict):
            continue
        ticker = clean_text(stock.get("ticker")).upper()
        if not ticker:
            continue
        path = stock_input_dir / f"{index:02d}-{safe_artifact_stem(ticker)}.json"
        write_json(
            path,
            {
                "ticker": normalize_workflow_display_ticker(ticker) or ticker,
                "name": clean_text(stock.get("name")),
                "chain_name": clean_text(stock.get("chain_name")),
                "source": "local_stock_pool_manager_ownership_followup",
            },
        )
        stock_paths.append(path)
    return stock_paths


def build_ownership_fundamental_run_command(
    request_payload: dict[str, Any],
    *,
    stock_input_paths: list[Path],
) -> str:
    result_path = Path(clean_text(request_payload.get("output_path"))).expanduser().resolve()
    report_path = Path(clean_text(request_payload.get("markdown_output_path"))).expanduser().resolve()
    target_date = clean_text(request_payload.get("target_date"))
    args = [
        "financial-analysis\\skills\\month-end-shortlist\\scripts\\run_institutional_evidence_bundle.cmd",
        f'--output "{result_path}"',
        f'--markdown-output "{report_path}"',
    ]
    if target_date:
        args.append(f'--analysis-date "{target_date}"')
    for ticker in clean_string_list(request_payload.get("sec_tickers"))[:8]:
        args.append(f'--sec-ticker "{ticker}"')
    for path in stock_input_paths:
        args.append(f'--eastmoney-notice-stock "{path.resolve()}"')
    for path in stock_input_paths:
        args.append(f'--akshare-fundamental-stock "{path.resolve()}"')
    if stock_input_paths:
        args.append("--refresh-eastmoney-notices")
    args.append("--source-capabilities")
    return " ".join(args)


XIndexRunner = Callable[[dict[str, Any]], dict[str, Any]]
EvidenceBundleRunner = Callable[[list[str]], int]


def _import_x_index_runtime() -> Any:
    autoresearch_scripts = (
        Path(__file__).resolve().parent.parent.parent
        / "autoresearch-info-index"
        / "scripts"
    )
    if str(autoresearch_scripts) not in sys.path:
        sys.path.insert(0, str(autoresearch_scripts))
    import x_index_runtime  # type: ignore[import-not-found]

    return x_index_runtime


def default_x_index_runner(payload: dict[str, Any]) -> dict[str, Any]:
    return _import_x_index_runtime().run_x_index(payload)


def default_evidence_bundle_runner(argv: list[str]) -> int:
    from institutional_evidence_bundle import main as bundle_main

    return bundle_main(argv)


def build_ownership_fundamental_argv(
    request_payload: dict[str, Any],
    *,
    stock_input_paths: list[Path],
) -> list[str]:
    output_path = Path(clean_text(request_payload.get("output_path"))).expanduser().resolve()
    report_path = Path(clean_text(request_payload.get("markdown_output_path"))).expanduser().resolve()
    target_date = clean_text(request_payload.get("target_date"))
    argv: list[str] = ["--output", str(output_path), "--markdown-output", str(report_path)]
    if target_date:
        argv.extend(["--analysis-date", target_date])
    for ticker in clean_string_list(request_payload.get("sec_tickers"))[:8]:
        argv.extend(["--sec-ticker", ticker])
    for path in stock_input_paths:
        argv.extend(["--eastmoney-notice-stock", str(path.resolve())])
    for path in stock_input_paths:
        argv.extend(["--akshare-fundamental-stock", str(path.resolve())])
    if stock_input_paths:
        argv.append("--refresh-eastmoney-notices")
    argv.append("--source-capabilities")
    return argv


def execute_x_index_followup(
    request_payload: dict[str, Any],
    *,
    runner: XIndexRunner | None = None,
) -> dict[str, Any]:
    actual_runner = runner or default_x_index_runner
    return actual_runner(request_payload)


def execute_ownership_fundamental_followup(
    request_payload: dict[str, Any],
    *,
    stock_input_paths: list[Path],
    runner: EvidenceBundleRunner | None = None,
) -> int:
    argv = build_ownership_fundamental_argv(request_payload, stock_input_paths=stock_input_paths)
    actual_runner = runner or default_evidence_bundle_runner
    return actual_runner(argv)


def ownership_request_tickers(request_payload: dict[str, Any]) -> set[str]:
    tickers: set[str] = set()
    for row in safe_list(request_payload.get("candidate_stocks")):
        if not isinstance(row, dict):
            continue
        ticker = normalize_workflow_display_ticker(row.get("ticker"))
        if ticker:
            tickers.add(ticker)
    return tickers


def ownership_result_tickers(payload: dict[str, Any]) -> set[str]:
    tickers: set[str] = set()

    def add_rows(rows: Any) -> None:
        for row in safe_list(rows):
            if not isinstance(row, dict):
                continue
            ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
            if ticker:
                tickers.add(ticker)

    for key in ("event_cards", "events", "filings", "sources", "a_share_fundamentals", "announcements"):
        add_rows(payload.get(key))
    fundamentals = payload.get("fundamentals")
    if isinstance(fundamentals, dict):
        add_rows(fundamentals.get("reports"))
        add_rows(fundamentals.get("items"))
        ticker = normalize_workflow_display_ticker(fundamentals.get("ticker"))
        if ticker:
            tickers.add(ticker)
    else:
        add_rows(fundamentals)
    ownership = payload.get("ownership")
    if isinstance(ownership, dict):
        add_rows(ownership.get("records"))
        ticker = normalize_workflow_display_ticker(ownership.get("ticker"))
        if ticker:
            tickers.add(ticker)
    else:
        add_rows(ownership)
    return tickers


def ownership_result_covers_request(payload: dict[str, Any], request_payload: dict[str, Any]) -> bool:
    requested = ownership_request_tickers(request_payload)
    if not requested:
        return False
    covered = ownership_result_tickers(payload)
    return requested.issubset(covered)


CATALYST_AUDIT_CANDIDATE_BUCKETS = (
    "top_picks",
    "priority_watchlist",
    "near_miss_candidates",
    "diagnostic_scorecard",
    "candidates",
    "market_strength_candidates",
    "setup_launch_candidates",
)


def collect_catalyst_news_followup_candidates(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None,
) -> list[dict[str, str]]:
    raw_rows: list[dict[str, Any]] = []
    audit_payload = safe_dict(package.get("institutional_signal_audit_payload"))
    for key in CATALYST_AUDIT_CANDIDATE_BUCKETS:
        raw_rows.extend([row for row in safe_list(audit_payload.get(key)) if isinstance(row, dict)])
    audit_plan = safe_dict(audit_payload.get("trading_plan"))
    raw_rows.extend([row for row in safe_list(audit_plan.get("candidates")) if isinstance(row, dict)])
    if not raw_rows and isinstance(shortlist_result, dict):
        for key in CATALYST_AUDIT_CANDIDATE_BUCKETS:
            raw_rows.extend([row for row in safe_list(shortlist_result.get(key)) if isinstance(row, dict)])
    if not raw_rows:
        return collect_social_evidence_candidates(package, shortlist_result)

    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in raw_rows:
        ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        name = clean_text(row.get("name") or row.get("company_name") or row.get("stock_name"))
        chain = clean_text(row.get("chain_name") or row.get("theme_name") or row.get("sector_name"))
        identity = ticker or name
        if not identity or identity in seen:
            continue
        seen.add(identity)
        candidates.append({"ticker": ticker, "name": name, "chain_name": chain})
        if len(candidates) >= 12:
            break
    return candidates


def build_catalyst_news_followup_request(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None,
    *,
    output_root: Path,
) -> dict[str, Any]:
    followup_dir = institutional_run_root(output_root) / "catalyst-news-evidence"
    followup_dir.mkdir(parents=True, exist_ok=True)
    package_path = clean_text(package.get("package_path"))
    request_path = followup_dir / "catalyst-news-evidence.request.json"
    result_path = followup_dir / "longbridge-institutional-evidence.json"
    target_date = clean_text(safe_dict(package.get("month_end_request")).get("target_date")) or clean_text(package.get("target_date"))
    analysis_time = clean_text(safe_dict(package.get("month_end_request")).get("analysis_time")) or clean_text(package.get("analysis_time"))
    candidates = collect_catalyst_news_followup_candidates(package, shortlist_result)
    candidate_tickers = unique_strings(
        [
            normalize_workflow_display_ticker(candidate.get("ticker"))
            for candidate in candidates
            if normalize_workflow_display_ticker(candidate.get("ticker"))
        ]
    )[:12]
    candidate_names = unique_strings(
        [
            clean_text(candidate.get("name"))
            for candidate in candidates
            if clean_text(candidate.get("name"))
        ]
    )[:12]
    request_payload = {
        "schema_version": "catalyst_news_followup_request/v1",
        "topic": f"Structured catalyst evidence {target_date or clean_text(package.get('target_date')) or date.today().isoformat()}",
        "target_date": target_date or clean_text(package.get("target_date")) or date.today().isoformat(),
        "analysis_time": analysis_time or clean_text(package.get("analysis_time")) or date.today().isoformat(),
        "package_path": package_path,
        "output_dir": str(followup_dir),
        "candidate_tickers": candidate_tickers,
        "candidate_names": candidate_names,
        "top_picks": [
            {key: value for key, value in candidate.items() if clean_text(value)}
            for candidate in candidates
            if clean_text(candidate.get("ticker"))
        ],
        "missing": ["structured catalysts/news evidence"],
        "news_count": 12,
        "detail_limit_per_ticker": 4,
        "reuse_existing_artifacts": True,
        "run_command": (
            "financial-analysis\\skills\\month-end-shortlist\\scripts\\run_longbridge_plan_sources.cmd "
            f'--input "{request_path}" --output-dir "{followup_dir}" '
            f'--target-date "{target_date or clean_text(package.get("target_date")) or date.today().isoformat()}" '
            "--news-count 12 --detail-limit-per-ticker 4 --reuse-existing-artifacts "
            "--no-capital --no-topics --no-filings --no-ownership --no-expectations --no-fundamentals --no-industry-valuation"
        ),
        "request_path": str(request_path),
        "expected_result_path": str(result_path),
        "expected_report_path": "",
    }
    write_json(request_path, request_payload)
    return request_payload


def write_institutional_evidence_followup_requests(
    package: dict[str, Any],
    shortlist_result: dict[str, Any] | None,
    *,
    output_root: Path,
    execute: bool = False,
    x_index_runner: XIndexRunner | None = None,
    evidence_bundle_runner: EvidenceBundleRunner | None = None,
) -> list[dict[str, Any]]:
    audit = safe_dict(package.get("institutional_signal_audit"))
    upgrade_ids = audit_upgrade_priority_ids(audit)
    followups: list[dict[str, Any]] = []
    if "catalyst_news" in upgrade_ids:
        request_payload = build_catalyst_news_followup_request(package, shortlist_result, output_root=output_root)
        followup = {
            "id": "catalyst_news",
            "label": "catalyst/news evidence request",
            "status": "request_ready",
            "request_path": clean_text(request_payload.get("request_path")),
            "output_dir": clean_text(request_payload.get("output_dir")),
            "expected_result_path": clean_text(request_payload.get("expected_result_path")),
            "expected_report_path": clean_text(request_payload.get("expected_report_path")),
            "run_command": clean_text(request_payload.get("run_command")),
            "auto_discovery_note": "Run the native Longbridge source collector, then rerun local stock-pool manager; same-run-root auto-discovery will attach the longbridge-institutional-evidence.json catalyst bundle.",
        }
        followups.append(followup)
    if "social_altdata" in upgrade_ids:
        request_payload = build_x_index_social_evidence_request(package, shortlist_result, output_root=output_root)
        x_output_dir = Path(request_payload["output_dir"]).expanduser().resolve()
        request_path = x_output_dir / "x-index-social-evidence.request.json"
        result_path = x_output_dir / "x-index-result.json"
        report_path = x_output_dir / "x-index-report.md"
        write_json(request_path, request_payload)
        run_command = (
            'financial-analysis\\skills\\autoresearch-info-index\\scripts\\run_x_index.cmd '
            f'"{request_path}" --output "{result_path}" --markdown-output "{report_path}" --quiet'
        )
        followup = {
            "id": "social_altdata",
            "label": "x-index social evidence request",
            "status": "request_ready",
            "request_path": str(request_path),
            "output_dir": str(x_output_dir),
            "expected_result_path": str(result_path),
            "expected_report_path": str(report_path),
            "run_command": run_command,
            "auto_discovery_note": "Run the native x-index command, then rerun local stock-pool manager; same-run-root auto-discovery will attach x-index-result.json.",
        }
        if execute:
            followup["execution_mode"] = "in_process"
            try:
                execute_x_index_followup(request_payload, runner=x_index_runner)
            except SystemExit as exc:
                followup["status"] = "execution_error"
                followup["execution_error"] = f"SystemExit: {exc.code}"
            except Exception as exc:  # noqa: BLE001
                followup["status"] = "execution_error"
                followup["execution_error"] = f"{type(exc).__name__}: {exc}"
        refresh_institutional_evidence_followup_result_state(followup)
        followups.append(followup)
    ownership_refresh_reason = (
        "audit_gap"
        if "ownership_fundamental" in upgrade_ids
        else "active_pool_maintenance"
    )
    if "ownership_fundamental" in upgrade_ids or collect_fundamental_evidence_candidates(package, shortlist_result):
        request_payload = build_ownership_fundamental_evidence_request(package, shortlist_result, output_root=output_root)
        evidence_dir = Path(clean_text(request_payload.get("output_path"))).expanduser().resolve().parent
        request_path = evidence_dir / "ownership-fundamental-evidence.request.json"
        stock_input_paths = write_ownership_fundamental_stock_inputs(request_payload, evidence_dir)
        run_command = build_ownership_fundamental_run_command(request_payload, stock_input_paths=stock_input_paths)
        request_payload["stock_input_paths"] = [str(path.resolve()) for path in stock_input_paths]
        request_payload["run_command"] = run_command
        write_json(request_path, request_payload)
        followup = {
            "id": "ownership_fundamental",
            "label": "ownership/fundamental evidence bundle request",
            "status": "request_ready",
            "request_path": str(request_path),
            "output_dir": str(evidence_dir),
            "expected_result_path": clean_text(request_payload.get("output_path")),
            "expected_report_path": clean_text(request_payload.get("markdown_output_path")),
            "run_command": run_command,
            "refresh_reason": ownership_refresh_reason,
            "auto_discovery_note": "Run the institutional evidence bundle command, then rerun local stock-pool manager; same-run-root auto-discovery will attach only real filing/fundamental/ownership evidence.",
        }
        if execute:
            followup["execution_mode"] = "in_process"
            try:
                execute_ownership_fundamental_followup(
                    request_payload,
                    stock_input_paths=stock_input_paths,
                    runner=evidence_bundle_runner,
                )
            except SystemExit as exc:
                followup["status"] = "execution_error"
                followup["execution_error"] = f"SystemExit: {exc.code}"
            except Exception as exc:  # noqa: BLE001
                followup["status"] = "execution_error"
                followup["execution_error"] = f"{type(exc).__name__}: {exc}"
        refresh_institutional_evidence_followup_result_state(followup)
        result_path = Path(clean_text(followup.get("result_path") or followup.get("expected_result_path"))).expanduser()
        try:
            if ownership_refresh_reason == "active_pool_maintenance" and result_path.exists():
                result_payload = load_json(result_path)
                if isinstance(result_payload, dict) and ownership_result_covers_request(result_payload, request_payload):
                    followup["result_request_coverage"] = "covered"
                    followup.pop("result_stale_for_request", None)
                elif result_path.stat().st_mtime < request_path.stat().st_mtime:
                    followup["status"] = "request_ready"
                    followup["result_stale_for_request"] = True
                    followup["result_request_coverage"] = "stale_or_incomplete"
                    followup["result_note"] = "existing ownership/fundamental bundle predates the refreshed active-pool request"
        except OSError:
            pass
        followups.append(followup)
    if not followups:
        return []
    package["institutional_evidence_followups"] = followups
    return followups


def load_longbridge_json_artifact(path: str | Path | None) -> Any:
    if not path:
        return None
    try:
        payload = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if payload not in (None, "", [], {}) else None


def load_longbridge_expectation_artifact(path: str | Path | None) -> Any:
    return load_longbridge_json_artifact(path)


def load_longbridge_capital_flows_artifact(path: str | Path | None) -> list[dict[str, Any]]:
    payload = load_longbridge_json_artifact(path)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("capital_flows")
            or payload.get("capital_flow")
            or payload.get("fund_flows")
            or payload.get("money_flows")
            or payload.get("rows")
            or payload.get("items")
            or payload.get("data")
            or payload.get("results")
            or []
        )
        if isinstance(rows, dict):
            rows = [rows]
    else:
        rows = []
    capital_flows: list[dict[str, Any]] = []
    for raw_row in rows if isinstance(rows, list) else []:
        if not isinstance(raw_row, dict):
            continue
        row = {key: value for key, value in raw_row.items() if value not in ("", None, [], {})}
        ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        if ticker:
            row["ticker"] = ticker
        if row:
            capital_flows.append(row)
    return capital_flows


def load_longbridge_rows_artifact(path: str | Path | None) -> list[dict[str, Any]]:
    payload = load_longbridge_json_artifact(path)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("filings")
            or payload.get("filing")
            or payload.get("topics")
            or payload.get("topic")
            or payload.get("posts")
            or payload.get("rows")
            or payload.get("items")
            or payload.get("data")
            or payload.get("results")
            or []
        )
        if isinstance(rows, dict):
            rows = [rows]
    else:
        rows = []
    filings: list[dict[str, Any]] = []
    for raw_row in rows if isinstance(rows, list) else []:
        if not isinstance(raw_row, dict):
            continue
        row = {key: value for key, value in raw_row.items() if value not in ("", None, [], {})}
        ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        if ticker:
            row["ticker"] = ticker
        if row:
            filings.append(row)
    return filings


def load_longbridge_filings_artifact(path: str | Path | None) -> list[dict[str, Any]]:
    return load_longbridge_rows_artifact(path)


def load_longbridge_structured_rows_artifact(path: str | Path | None) -> list[dict[str, Any]]:
    payload = load_longbridge_json_artifact(path)
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("rows")
            or payload.get("items")
            or payload.get("data")
            or payload.get("results")
        )
        raw_rows = rows if isinstance(rows, list) else [payload]
    else:
        raw_rows = []
    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        row = {key: value for key, value in raw_row.items() if value not in ("", None, [], {})}
        ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        if ticker:
            row["ticker"] = ticker
        if row:
            rows.append(row)
    return rows


def x_index_result_primary_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root_posts = [row for row in safe_list(payload.get("x_posts")) if isinstance(row, dict)]
    evidence_pack = safe_dict(payload.get("evidence_pack"))
    pack_posts = [row for row in safe_list(evidence_pack.get("x_posts")) if isinstance(row, dict)]
    return root_posts if len(root_posts) >= len(pack_posts) else pack_posts


def x_index_post_uses_detail_text(post: dict[str, Any]) -> bool:
    source = clean_text(post.get("post_text_source")).lower()
    return source in {"dom", "dom_target", "accessibility", "accessibility_root"}


def x_index_post_was_detail_hydrated(post: dict[str, Any]) -> bool:
    notes = " ".join(
        clean_text(item)
        for item in [
            *safe_list(post.get("crawl_notes")),
            *safe_list(post.get("session_notes")),
        ]
    ).lower()
    return "hydrated fixed-profile capture from detail page" in notes


def x_index_post_had_detail_expansion(post: dict[str, Any]) -> bool:
    notes = " ".join(
        clean_text(item)
        for item in [
            *safe_list(post.get("crawl_notes")),
            *safe_list(post.get("session_notes")),
        ]
    ).lower()
    for match in re.findall(r"expand_clicks=(\d+)", notes):
        try:
            if int(match) > 0:
                return True
        except ValueError:
            continue
    return False


def attach_x_index_fulltext_metrics(followup: dict[str, Any], payload: dict[str, Any], post_count: int) -> list[str]:
    posts = x_index_result_primary_posts(payload)
    browser_session_count = sum(1 for post in posts if clean_text(post.get("access_mode")) == "browser_session")
    detail_text_count = sum(1 for post in posts if x_index_post_uses_detail_text(post))
    hydrated_detail_count = sum(1 for post in posts if x_index_post_was_detail_hydrated(post))
    expanded_detail_count = sum(1 for post in posts if x_index_post_had_detail_expansion(post))
    thread_text_post_count = 0
    max_text_length = 0
    for post in posts:
        max_text_length = max(max_text_length, len(clean_text(post.get("post_text_raw") or post.get("text"))))
        thread_texts = [
            clean_text(item.get("post_text_raw") or item.get("text"))
            for item in safe_list(post.get("thread_posts"))
            if isinstance(item, dict) and clean_text(item.get("post_text_raw") or item.get("text"))
        ]
        if thread_texts:
            thread_text_post_count += 1
        for text in thread_texts:
            max_text_length = max(max_text_length, len(text))

    if browser_session_count:
        followup["result_browser_session_post_count"] = browser_session_count
    if detail_text_count:
        followup["result_dom_text_post_count"] = detail_text_count
    if hydrated_detail_count:
        followup["result_hydrated_detail_post_count"] = hydrated_detail_count
    if expanded_detail_count:
        followup["result_expanded_detail_post_count"] = expanded_detail_count
    if thread_text_post_count:
        followup["result_thread_text_post_count"] = thread_text_post_count
    if max_text_length:
        followup["result_max_text_length"] = max_text_length

    metric_parts: list[str] = []
    if post_count:
        if browser_session_count:
            metric_parts.append(f"browser session {browser_session_count}/{post_count}")
        if detail_text_count:
            metric_parts.append(f"dom/detail text {detail_text_count}/{post_count}")
        if hydrated_detail_count:
            metric_parts.append(f"hydrated detail {hydrated_detail_count}/{post_count}")
        if expanded_detail_count:
            metric_parts.append(f"expanded detail {expanded_detail_count}/{post_count}")
        if thread_text_post_count:
            metric_parts.append(f"thread text {thread_text_post_count}/{post_count}")
    if max_text_length:
        metric_parts.append(f"max text {max_text_length}")
    return metric_parts


def refresh_institutional_evidence_followup_result_state(followup: dict[str, Any]) -> dict[str, Any]:
    result_path_text = clean_text(followup.get("expected_result_path"))
    if not result_path_text:
        return followup
    result_path = Path(result_path_text).expanduser()
    if not result_path.exists():
        return followup
    followup["result_path"] = str(result_path.resolve())
    report_path = Path(clean_text(followup.get("expected_report_path"))).expanduser() if clean_text(followup.get("expected_report_path")) else None
    if report_path and report_path.exists():
        followup["report_path"] = str(report_path.resolve())
    try:
        payload = load_json(result_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        followup["status"] = "result_error"
        followup["result_note"] = f"followup result exists but could not be parsed: {exc}"
        return followup
    if clean_text(followup.get("id")) == "catalyst_news":
        summary = safe_dict(payload.get("source_health"))
        detail_rows = [
            row
            for row in safe_list(payload.get("longbridge_news_details"))
            if isinstance(row, dict)
        ]
        command_statuses = [
            row
            for row in safe_list(payload.get("command_statuses"))
            if isinstance(row, dict)
        ]
        detail_count = 0
        detail_error_count = 0
        source_error_count = 0
        max_text_length = 0
        if summary:
            try:
                detail_count = int(summary.get("news_detail_usable_count") or 0)
            except (TypeError, ValueError):
                detail_count = 0
            try:
                detail_error_count = int(summary.get("news_detail_error_count") or 0)
            except (TypeError, ValueError):
                detail_error_count = 0
            try:
                source_error_count = int(summary.get("source_error_count") or 0)
            except (TypeError, ValueError):
                source_error_count = 0
        if not source_error_count:
            source_error_count = sum(
                1
                for row in command_statuses
                if clean_text(row.get("status")).lower() == "error"
                or clean_text(row.get("stderr"))
                or clean_text(row.get("error"))
            )
        blocked_text = " ".join(
            clean_text(row.get("stderr") or row.get("error") or row.get("message")).lower()
            for row in command_statuses
        )
        longbridge_auth_blocked = "not authenticated" in blocked_text or "authentication failed" in blocked_text
        if not detail_count:
            detail_count = sum(
                1
                for row in detail_rows
                if clean_text(row.get("fetch_status")).lower() == "ok"
                and clean_text(row.get("content_markdown") or row.get("content") or row.get("body") or row.get("text"))
            )
        if not detail_error_count:
            detail_error_count = sum(
                1
                for row in detail_rows
                if clean_text(row.get("fetch_status")).lower() not in {"ok", "covered"}
            )
        for row in detail_rows:
            max_text_length = max(
                max_text_length,
                len(
                    clean_text(
                        row.get("content_markdown")
                        or row.get("content")
                        or row.get("body")
                        or row.get("text")
                    )
                ),
            )
        followup["result_news_detail_usable_count"] = detail_count
        followup["result_news_detail_error_count"] = detail_error_count
        if detail_count:
            followup["status"] = "result_ready"
            followup["result_note"] = (
                f"longbridge catalyst/news bundle contains {detail_count} usable news detail(s); "
                "structured catalyst/news detail is available for audit rerun."
            )
        elif longbridge_auth_blocked:
            followup["status"] = "access_blocked"
            followup["access_block_reason"] = "longbridge_not_authenticated"
            followup["result_source_error_count"] = source_error_count
            followup["result_note"] = (
                "Longbridge authentication blocked the catalyst/news refresh; "
                "keep catalyst_news unresolved until the Longbridge session is authenticated."
            )
        elif source_error_count:
            followup["status"] = "source_error"
            followup["result_source_error_count"] = source_error_count
            followup["result_note"] = (
                f"longbridge catalyst/news bundle recorded {source_error_count} source error(s) and no usable news detail; "
                "check command_statuses before treating this as a no-news result."
            )
        else:
            followup["status"] = "empty_result"
            followup["result_note"] = "longbridge catalyst/news bundle ran, but no usable news detail was found; keep catalyst_news unresolved."
        if max_text_length:
            followup["result_max_text_length"] = max_text_length
        return followup
    if clean_text(followup.get("id")) == "ownership_fundamental":
        summary = safe_dict(payload.get("summary"))
        live_fetch_source_count = 0
        source_fetch_error_count = 0
        try:
            live_fetch_source_count = int(summary.get("live_fetch_source_count") or 0)
        except (TypeError, ValueError):
            live_fetch_source_count = 0
        try:
            source_fetch_error_count = int(summary.get("source_fetch_error_count") or 0)
        except (TypeError, ValueError):
            source_fetch_error_count = 0
        if live_fetch_source_count:
            followup["live_fetch_source_count"] = live_fetch_source_count
        if source_fetch_error_count:
            followup["source_fetch_error_count"] = source_fetch_error_count
        count = 0
        for key in ("filing_count", "fundamental_report_count", "ownership_record_count"):
            try:
                count += int(summary.get(key) or 0)
            except (TypeError, ValueError):
                continue
        filings = payload.get("filings")
        if isinstance(filings, list):
            count = max(count, len(filings))
        fundamentals = payload.get("fundamentals")
        if isinstance(fundamentals, dict):
            reports = fundamentals.get("reports")
            if isinstance(reports, list):
                count = max(count, len(reports))
            elif any(value not in (None, "", [], {}) for value in fundamentals.values()):
                count = max(count, 1)
        elif isinstance(fundamentals, list):
            count = max(count, len(fundamentals))
        ownership = payload.get("ownership")
        if isinstance(ownership, list):
            count = max(count, len(ownership))
        elif isinstance(ownership, dict) and any(value not in (None, "", [], {}) for value in ownership.values()):
            count = max(count, 1)
        followup["result_evidence_count"] = count
        if count:
            followup["status"] = "result_ready"
            followup["result_note"] = f"institutional evidence bundle contains {count} filing/fundamental/ownership item(s); rerun audit should merge the evidence."
        else:
            followup["status"] = "empty_result"
            fetch_note = (
                f" {source_fetch_error_count} source fetch error(s) were recorded; check the bundle source rows before blaming the workflow."
                if source_fetch_error_count
                else ""
            )
            followup["result_note"] = (
                "institutional evidence bundle ran, but no filing/fundamental/ownership evidence was found; "
                f"keep ownership_fundamental unresolved.{fetch_note}"
            )
        return followup
    x_posts = payload.get("x_posts")
    x_post_count = len(x_posts) if isinstance(x_posts, list) else 0
    evidence_pack = safe_dict(payload.get("evidence_pack"))
    pack_posts = evidence_pack.get("x_posts")
    pack_post_count = len(pack_posts) if isinstance(pack_posts, list) else 0
    background_posts = payload.get("background_x_posts")
    background_post_count = len(background_posts) if isinstance(background_posts, list) else 0
    pack_background_posts = evidence_pack.get("background_x_posts")
    pack_background_post_count = len(pack_background_posts) if isinstance(pack_background_posts, list) else 0
    summary_background_post_count = safe_dict(payload.get("discovery_summary")).get("background_post_count")
    try:
        summary_background_post_count = int(summary_background_post_count or 0)
    except (TypeError, ValueError):
        summary_background_post_count = 0
    post_count = max(x_post_count, pack_post_count)
    background_count = max(background_post_count, pack_background_post_count, summary_background_post_count)
    followup["result_post_count"] = post_count
    if background_count:
        followup["background_post_count"] = background_count
    else:
        followup.pop("background_post_count", None)
    if post_count:
        followup["status"] = "result_ready"
        metric_parts = attach_x_index_fulltext_metrics(followup, payload, post_count)
        metric_suffix = f"; {'; '.join(metric_parts)}" if metric_parts else ""
        followup["result_note"] = f"x-index result contains {post_count} post(s){metric_suffix}; rerun audit should merge the evidence."
    else:
        discovery_summary = safe_dict(payload.get("discovery_summary"))
        search_attempts = [
            row
            for row in discovery_summary.get("search_attempts", [])
            if isinstance(row, dict)
        ]
        blocked_attempts = [
            row
            for row in search_attempts
            if clean_text(row.get("status")).lower() == "blocked" or clean_text(row.get("blocked_reason"))
        ]
        blocked_reasons = [
            clean_text(row.get("blocked_reason"))
            for row in blocked_attempts
            if clean_text(row.get("blocked_reason"))
        ]
        login_required = any("login" in reason.lower() or "sign in" in reason.lower() for reason in blocked_reasons)
        if blocked_attempts:
            followup["blocked_search_count"] = len(blocked_attempts)
        else:
            followup.pop("blocked_search_count", None)
        if login_required:
            followup["status"] = "access_blocked"
            followup["access_block_reason"] = "x_login_required"
            followup["result_note"] = (
                "x-index reached the browser session but X search requires login; "
                "keep social_altdata unresolved until the fixed Codex Chrome profile is signed in."
            )
            return followup
        followup["status"] = "empty_result"
        if background_count:
            followup["result_note"] = (
                f"x-index ran, but returned zero fresh/current posts; {background_count} background/stale post(s) "
                "were separated and should not satisfy social_altdata."
            )
        else:
            followup["result_note"] = "x-index ran, but returned zero posts; keep social_altdata unresolved."
    return followup


def write_local_stock_pool_manager_package(
    raw_pool: dict[str, Any],
    *,
    output_dir: str | Path,
    trading_plan_result: dict[str, Any] | None = None,
    tdx_vipdoc_path: str = "",
    target_date: str = "",
    analysis_time: str = "",
    institutional_ready: bool = False,
    run_shortlist: bool = False,
    shortlist_runner: ShortlistRunner | None = None,
    shortlist_input_path: str | Path | None = None,
    shortlist_output_path: str | Path | None = None,
    shortlist_markdown_output_path: str | Path | None = None,
    run_postclose_review: bool = False,
    postclose_review_runner: PostcloseReviewRunner | None = None,
    postclose_output_path: str | Path | None = None,
    postclose_markdown_output_path: str | Path | None = None,
    postclose_plan_path: str | Path | None = None,
    institutional_audit_runner: InstitutionalAuditRunner | None = None,
    institutional_audit_output_path: str | Path | None = None,
    institutional_audit_markdown_output_path: str | Path | None = None,
    institutional_evidence_payloads: list[dict[str, Any]] | None = None,
    institutional_evidence_dirs: list[str | Path] | None = None,
    auto_discover_institutional_evidence: bool = True,
    execute_institutional_evidence_followups: bool = False,
    run_live_source_probes: bool = False,
    longbridge_news_path: str | Path | None = None,
    longbridge_market_status_path: str | Path | None = None,
    longbridge_market_temp_path: str | Path | None = None,
    earnings_calendar_payloads: list[Any] | None = None,
    earnings_calendar_source_paths: list[str | Path] | None = None,
    earnings_calendar_watchlist: list[Any] | None = None,
    earnings_calendar_lookahead_days: int = DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS,
    auto_discover_earnings_calendar: bool = True,
    event_calendar_payloads: list[Any] | None = None,
    event_calendar_source_paths: list[str | Path] | None = None,
    event_calendar_watchlist: list[Any] | None = None,
    event_calendar_lookahead_days: int = DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS,
    auto_discover_event_calendar: bool = True,
    auto_macro_health_overlay: bool = False,
    run_trigger_monitor: bool = False,
    trigger_monitor_runner: TriggerMonitorRunner | None = None,
    trigger_monitor_output_path: str | Path | None = None,
    longbridge_binary_path: str = "",
    record_trade_journal: bool = False,
    trade_journal_path: str | Path | None = None,
    trade_journal_decision_runner: TradeJournalDecisionRunner | None = None,
    trade_journal_outcome_runner: TradeJournalOutcomeRunner | None = None,
    update_direction_risk_register: bool = False,
    direction_risk_register_path: str | Path | None = None,
    direction_risk_register_runner: DirectionRiskRegisterRunner | None = None,
    thesis_check_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    discovered_evidence_payloads: list[dict[str, Any]] = []
    discovered_evidence_sources: list[str] = []
    discovered_earnings_calendar_payloads: list[Any] = []
    discovered_earnings_calendar_sources: list[str] = []
    discovered_event_calendar_payloads: list[Any] = []
    discovered_event_calendar_sources: list[str] = []
    if auto_discover_institutional_evidence:
        evidence_roots: list[str | Path] = implicit_institutional_evidence_roots(output_root)
        evidence_roots.extend(institutional_evidence_dirs or [])
        if institutional_ready:
            evidence_roots.extend(default_codex_chrome_social_evidence_paths())
        discovered_evidence_payloads, discovered_evidence_sources = discover_institutional_evidence_payloads(evidence_roots)
    if auto_discover_earnings_calendar:
        calendar_roots: list[str | Path] = implicit_institutional_evidence_roots(output_root)
        calendar_roots.extend(institutional_evidence_dirs or [])
        discovered_earnings_calendar_payloads, discovered_earnings_calendar_sources = discover_earnings_calendar_payloads(calendar_roots)
    if auto_discover_event_calendar:
        event_calendar_roots: list[str | Path] = implicit_institutional_evidence_roots(output_root)
        event_calendar_roots.extend(institutional_evidence_dirs or [])
        discovered_event_calendar_payloads, discovered_event_calendar_sources = discover_event_calendar_payloads(event_calendar_roots)
    longbridge_artifact_paths: dict[str, Path] = {}
    if auto_discover_institutional_evidence:
        longbridge_search_roots = implicit_institutional_evidence_roots(output_root)
        longbridge_search_roots.extend(institutional_evidence_dirs or [])
        longbridge_artifact_paths = discover_longbridge_artifacts(longbridge_search_roots)
    if longbridge_news_path:
        longbridge_artifact_paths["news"] = Path(longbridge_news_path).expanduser().resolve()
    if longbridge_market_status_path:
        longbridge_artifact_paths["market_status"] = Path(longbridge_market_status_path).expanduser().resolve()
    if longbridge_market_temp_path:
        longbridge_artifact_paths["market_temperature"] = Path(longbridge_market_temp_path).expanduser().resolve()
    package = build_local_stock_pool_manager_package(
        raw_pool,
        trading_plan_result=trading_plan_result,
        tdx_vipdoc_path=tdx_vipdoc_path,
        target_date=target_date,
        analysis_time=analysis_time,
        institutional_ready=institutional_ready,
        earnings_calendar_payloads=[
            *(earnings_calendar_payloads or []),
            *discovered_earnings_calendar_payloads,
        ],
        earnings_calendar_watchlist=earnings_calendar_watchlist,
        earnings_calendar_lookahead_days=earnings_calendar_lookahead_days,
        event_calendar_payloads=[
            *(event_calendar_payloads or []),
            *discovered_event_calendar_payloads,
        ],
        event_calendar_watchlist=event_calendar_watchlist,
        event_calendar_lookahead_days=event_calendar_lookahead_days,
        thesis_check_payloads=thesis_check_payloads,
    )
    html_path = output_root / "local-stock-pool-manager.html"
    pool_path = output_root / "local-stock-pool.json"
    request_path = output_root / "month-end-shortlist-local-stock-pool.request.json"
    package_path = output_root / "local-stock-pool-manager-package.json"
    package.update(
        {
            "html_path": str(html_path),
            "pool_path": str(pool_path),
            "month_end_request_path": str(request_path),
            "package_path": str(package_path),
        }
    )
    source_capability_snapshot = default_source_capability_snapshot(longbridge_binary_path)
    raw_source_capabilities = source_capability_snapshot.get("source_capabilities")
    source_capabilities = [
        row
        for row in (raw_source_capabilities if isinstance(raw_source_capabilities, list) else [])
        if isinstance(row, dict)
    ]
    if source_capabilities:
        package["source_capabilities"] = source_capabilities
        if isinstance(source_capability_snapshot.get("summary"), dict):
            package["source_capability_summary"] = source_capability_snapshot["summary"]
    source_health_probe_snapshot = default_source_health_probe_snapshot(source_capability_snapshot, run_live_probes=run_live_source_probes)
    raw_source_health_probes = source_health_probe_snapshot.get("source_health_probes")
    source_health_probes = [
        row
        for row in (raw_source_health_probes if isinstance(raw_source_health_probes, list) else [])
        if isinstance(row, dict)
    ]
    if source_health_probes:
        package["source_health_probes"] = source_health_probes
        if isinstance(source_health_probe_snapshot.get("summary"), dict):
            package["source_health_probe_summary"] = source_health_probe_snapshot["summary"]
    if discovered_evidence_sources:
        package["institutional_evidence_sources"] = discovered_evidence_sources
    earnings_sources = unique_strings(
        [
            *[str(Path(path).expanduser().resolve()) for path in (earnings_calendar_source_paths or []) if clean_text(path)],
            *discovered_earnings_calendar_sources,
        ]
    )
    event_sources = unique_strings(
        [
            *[str(Path(path).expanduser().resolve()) for path in (event_calendar_source_paths or []) if clean_text(path)],
            *discovered_event_calendar_sources,
        ]
    )
    if earnings_sources:
        package["earnings_calendar_sources"] = earnings_sources
    if event_sources:
        package["event_calendar_sources"] = event_sources

    longbridge_artifact_sources: dict[str, str] = {}
    quotes_artifact_path = longbridge_artifact_paths.get("quotes")
    if quotes_artifact_path is not None:
        market_snapshots = load_market_snapshots(quotes_artifact_path)
        if market_snapshots:
            package["longbridge_quotes"] = list(market_snapshots.values())
            package["local_stock_pool"] = merge_market_snapshots_into_local_stock_pool(
                safe_dict(package.get("local_stock_pool")),
                market_snapshots,
            )
            month_end_request = safe_dict(package.get("month_end_request"))
            if month_end_request:
                month_end_request = dict(month_end_request)
                month_end_request["local_stock_pool"] = package["local_stock_pool"]
                package["month_end_request"] = month_end_request
            longbridge_artifact_sources["quotes"] = str(quotes_artifact_path)
    news_artifact_path = longbridge_artifact_paths.get("news")
    if news_artifact_path is not None:
        headlines = load_longbridge_news_headlines(news_artifact_path)
        if headlines:
            package["longbridge_news_headlines"] = headlines
            longbridge_artifact_sources["news"] = str(news_artifact_path)
    news_details_artifact_path = longbridge_artifact_paths.get("news_details")
    if news_details_artifact_path is not None:
        details = load_longbridge_news_details(news_details_artifact_path)
        if details:
            package["longbridge_news_details"] = attach_tickers_to_longbridge_news_details(
                details,
                [row for row in safe_list(package.get("longbridge_news_headlines")) if isinstance(row, dict)],
            )
            longbridge_artifact_sources["news_details"] = str(news_details_artifact_path)
    market_status_path = longbridge_artifact_paths.get("market_status")
    if market_status_path is not None:
        session_index = load_longbridge_market_status(market_status_path)
        if session_index:
            package["longbridge_market_session_index"] = session_index
            longbridge_artifact_sources["market_status"] = str(market_status_path)
    market_temp_path = longbridge_artifact_paths.get("market_temperature")
    if market_temp_path is not None:
        temperature = load_longbridge_market_temperature(market_temp_path)
        if temperature:
            package["longbridge_market_temperature"] = temperature
            longbridge_artifact_sources["market_temperature"] = str(market_temp_path)
    capital_flow_path = longbridge_artifact_paths.get("capital_flows")
    if capital_flow_path is not None:
        capital_flows = load_longbridge_capital_flows_artifact(capital_flow_path)
        if capital_flows:
            package["longbridge_capital_flows"] = capital_flows
            package["capital_flows"] = capital_flows
            longbridge_artifact_sources["capital_flows"] = str(capital_flow_path)
    topics_path = longbridge_artifact_paths.get("topics")
    if topics_path is not None:
        topics = load_longbridge_rows_artifact(topics_path)
        if topics:
            package["longbridge_topics"] = topics
            longbridge_artifact_sources["topics"] = str(topics_path)
    filings_path = longbridge_artifact_paths.get("filings")
    if filings_path is not None:
        filings = load_longbridge_filings_artifact(filings_path)
        if filings:
            package["longbridge_filings"] = filings
            package["filings"] = filings
            longbridge_artifact_sources["filings"] = str(filings_path)
    for artifact_key, package_key in (
        ("shareholders", "longbridge_shareholders"),
        ("fund_holders", "longbridge_fund_holders"),
        ("insider_trades", "longbridge_insider_trades"),
        ("short_positions", "longbridge_short_positions"),
    ):
        artifact_path = longbridge_artifact_paths.get(artifact_key)
        if artifact_path is None:
            continue
        rows = load_longbridge_rows_artifact(artifact_path)
        if not rows:
            continue
        package[package_key] = rows
        longbridge_artifact_sources[artifact_key] = str(artifact_path)
    for artifact_kind, package_key in LONGBRIDGE_FUNDAMENTAL_ARTIFACT_PACKAGE_KEYS.items():
        artifact_path = longbridge_artifact_paths.get(artifact_kind)
        if artifact_path is None:
            continue
        rows = load_longbridge_structured_rows_artifact(artifact_path)
        if not rows:
            continue
        package[package_key] = rows
        longbridge_artifact_sources[artifact_kind] = str(artifact_path)
    plan_source_run_path = longbridge_artifact_paths.get("plan_source_run")
    if plan_source_run_path is not None:
        plan_source_run = load_longbridge_plan_source_run(plan_source_run_path)
        summary = plan_source_run.get("summary") if isinstance(plan_source_run, dict) else {}
        if isinstance(summary, dict) and summary:
            package["longbridge_plan_source_run"] = plan_source_run
            package["longbridge_plan_source_summary"] = summary
            longbridge_artifact_sources["plan_source_run"] = str(plan_source_run_path)
            information_completion_index = safe_dict(plan_source_run.get("information_completion_index"))
            if information_completion_index:
                package["information_completion_index"] = information_completion_index
                completion_path = clean_text(
                    safe_dict(plan_source_run.get("output_paths")).get("information_completion_index")
                )
                if completion_path:
                    longbridge_artifact_sources["information_completion_index"] = completion_path
    longbridge_expectation_artifact_sources: dict[str, str] = {}
    for artifact_kind, package_key in LONGBRIDGE_EXPECTATION_ARTIFACT_PACKAGE_KEYS.items():
        artifact_path = longbridge_artifact_paths.get(artifact_kind)
        if artifact_path is None:
            continue
        payload = load_longbridge_expectation_artifact(artifact_path)
        if payload is None:
            continue
        path_text = str(artifact_path)
        package[package_key] = payload
        longbridge_artifact_sources[artifact_kind] = path_text
        longbridge_expectation_artifact_sources[artifact_kind] = path_text
    if longbridge_expectation_artifact_sources:
        package["longbridge_expectation_artifact_sources"] = longbridge_expectation_artifact_sources
    if longbridge_artifact_sources:
        package["longbridge_artifact_sources"] = longbridge_artifact_sources
    package["ticker_quote_news_coverage"] = build_ticker_quote_news_coverage(package)
    if thesis_check_payloads:
        thesis_fact_check = build_thesis_fact_check(
            thesis_check_payloads,
            evidence_payloads=[
                payload
                for payload in (
                    raw_pool,
                    trading_plan_result,
                    package_without_generated_thesis_fact_check(package),
                    *(institutional_evidence_payloads or []),
                    *discovered_evidence_payloads,
                )
                if isinstance(payload, dict)
            ],
        )
        thesis_fact_check_path = output_root / "thesis-fact-check.json"
        thesis_fact_check_report_path = output_root / "thesis-fact-check.md"
        write_json(thesis_fact_check_path, thesis_fact_check)
        thesis_fact_check_report_path.write_text(
            render_thesis_fact_check_markdown(thesis_fact_check),
            encoding="utf-8",
        )
        package["thesis_fact_check"] = thesis_fact_check
        package["thesis_fact_check_path"] = str(thesis_fact_check_path)
        package["thesis_fact_check_report_path"] = str(thesis_fact_check_report_path)

    should_run_postclose = bool(run_postclose_review or postclose_output_path or postclose_markdown_output_path)
    should_run_shortlist = bool(
        run_shortlist
        or shortlist_input_path
        or shortlist_output_path
        or shortlist_markdown_output_path
        or should_run_postclose
    )
    shortlist_result: dict[str, Any] | None = None
    if should_run_shortlist:
        from month_end_shortlist_runtime import apply_default_macro_health_overlay

        month_end_request = apply_default_macro_health_overlay(
            package["month_end_request"],
            package["month_end_request"],
            enabled=auto_macro_health_overlay,
        )
        package["month_end_request"] = month_end_request
        if isinstance(month_end_request.get("macro_health_overlay"), dict):
            package["macro_health_overlay"] = month_end_request["macro_health_overlay"]
        if isinstance(month_end_request.get("macro_health_overlay_live_fetch_summary"), dict):
            package["macro_health_overlay_live_fetch_summary"] = month_end_request["macro_health_overlay_live_fetch_summary"]
        if shortlist_input_path:
            loaded_shortlist = load_json(shortlist_input_path)
            shortlist_result = loaded_shortlist if isinstance(loaded_shortlist, dict) else {}
        else:
            runner = shortlist_runner or default_shortlist_runner
            shortlist_result = runner(month_end_request)
        shortlist_result = normalize_reused_fresh_discovery_coverage(shortlist_result)
        attach_macro_health_overlay_from_shortlist_result(package, shortlist_result)
        result_path = (
            Path(shortlist_output_path).expanduser().resolve()
            if shortlist_output_path
            else output_root / "month-end-shortlist-result.json"
        )
        report_path = (
            Path(shortlist_markdown_output_path).expanduser().resolve()
            if shortlist_markdown_output_path
            else output_root / "month-end-shortlist-report.md"
        )
        entry_list_screening = build_entry_list_screening_from_shortlist_result(shortlist_result)
        if entry_list_screening:
            entry_list_earnings_overlay = build_entry_list_earnings_overlay(
                {
                    "entry_list_screening": entry_list_screening,
                    "earnings_calendar_watch": package.get("earnings_calendar_watch"),
                }
            )
            if entry_list_earnings_overlay:
                entry_list_screening["earnings_calendar_overlay_count"] = len(entry_list_earnings_overlay)
                entry_list_screening["entry_list_earnings_overlay"] = entry_list_earnings_overlay
                shortlist_result["entry_list_earnings_overlay"] = entry_list_earnings_overlay
                package["entry_list_earnings_overlay"] = entry_list_earnings_overlay
            else:
                package["entry_list_earnings_overlay"] = []
            shortlist_result["entry_list_screening"] = entry_list_screening
            package["entry_list_screening"] = entry_list_screening
        if isinstance(package.get("earnings_calendar_watch"), dict):
            shortlist_result["earnings_calendar_watch"] = package["earnings_calendar_watch"]
        if isinstance(package.get("event_calendar_watch"), dict):
            shortlist_result["event_calendar_watch"] = package["event_calendar_watch"]
        shortlist_report_markdown = render_shortlist_report_markdown(
            shortlist_result,
            macro_health_overlay=safe_dict(package.get("macro_health_overlay")),
            macro_health_live_fetch_summary=safe_dict(package.get("macro_health_overlay_live_fetch_summary")),
            macro_health_seed_summary=safe_dict(package.get("macro_health_overlay_seed_summary")),
        )
        write_json(result_path, shortlist_result)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(shortlist_report_markdown, encoding="utf-8")
        package["shortlist_result_path"] = str(result_path)
        package["shortlist_report_path"] = str(report_path)
        if clean_text(shortlist_report_markdown):
            package["shortlist_report_markdown"] = shortlist_report_markdown
        if clean_text(shortlist_result.get("status")):
            package["shortlist_status"] = clean_text(shortlist_result.get("status"))
        if isinstance(shortlist_result.get("fresh_discovery_coverage"), dict):
            package["fresh_discovery_coverage"] = shortlist_result["fresh_discovery_coverage"]
        sector_layer = build_fresh_discovery_sector_layer(shortlist_result)
        if safe_dict(sector_layer.get("summary")).get("sector_count"):
            package["fresh_discovery_sector_layer"] = sector_layer

    should_record_trade_journal = bool(record_trade_journal or trade_journal_path)
    resolved_trade_journal_path: Path | None = None
    if should_record_trade_journal:
        resolved_trade_journal_path = (
            Path(trade_journal_path).expanduser().resolve()
            if trade_journal_path
            else output_root / "trade-journal.jsonl"
        )
        decision_runner = trade_journal_decision_runner or default_trade_journal_decision_runner
        try:
            recorded_decisions = decision_runner(package, resolved_trade_journal_path)
        except Exception as exc:  # noqa: BLE001
            package["trade_journal_error"] = f"{type(exc).__name__}: {exc}"
            recorded_decisions = []
        package["trade_journal_path"] = str(resolved_trade_journal_path)
        package["trade_journal_decision_count"] = len(recorded_decisions)

    if should_run_postclose:
        if shortlist_result is None:
            shortlist_result = {}
        plan_md = None
        if postclose_plan_path:
            plan_path = Path(postclose_plan_path).expanduser().resolve()
            plan_md = plan_path.read_text(encoding="utf-8")
        review_runner = postclose_review_runner or default_postclose_review_runner
        trade_date = clean_text(package["month_end_request"].get("target_date")) or clean_text(target_date)
        postclose_review_input = build_postclose_review_input_from_current_pool(shortlist_result, package)
        if postclose_review_input is not shortlist_result:
            package["postclose_review_input_source"] = clean_text(postclose_review_input.get("postclose_review_source"))
        postclose_review_result = review_runner(postclose_review_input, trade_date, plan_md)
        review_path = (
            Path(postclose_output_path).expanduser().resolve()
            if postclose_output_path
            else output_root / "postclose-review.json"
        )
        review_report_path = (
            Path(postclose_markdown_output_path).expanduser().resolve()
            if postclose_markdown_output_path
            else output_root / "postclose-review.md"
        )
        write_json(review_path, postclose_review_result)
        review_report_path.parent.mkdir(parents=True, exist_ok=True)
        review_report_path.write_text(render_postclose_review_markdown(postclose_review_result), encoding="utf-8")
        package["postclose_review"] = postclose_review_result
        package["postclose_review_path"] = str(review_path)
        package["postclose_report_path"] = str(review_report_path)
        observation_layer = build_postclose_observation_layer(postclose_review_result)
        if safe_dict(observation_layer.get("summary")).get("loose_observation_count"):
            package["postclose_observation_layer"] = observation_layer

        if should_record_trade_journal and resolved_trade_journal_path is not None:
            outcome_runner = trade_journal_outcome_runner or default_trade_journal_outcome_runner
            try:
                recorded_outcomes = outcome_runner(postclose_review_result, resolved_trade_journal_path)
            except Exception as exc:  # noqa: BLE001
                package["trade_journal_outcome_error"] = f"{type(exc).__name__}: {exc}"
                recorded_outcomes = []
            package["trade_journal_outcome_count"] = len(recorded_outcomes)
            try:
                from trade_journal_runtime import load_journal, render_trade_journal_markdown

                journal_entries = load_journal(resolved_trade_journal_path)
                report_path = resolved_trade_journal_path.with_suffix(".md")
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(
                    render_trade_journal_markdown(journal_entries),
                    encoding="utf-8",
                )
                package["trade_journal_report_path"] = str(report_path)
            except Exception as exc:  # noqa: BLE001
                package["trade_journal_report_error"] = f"{type(exc).__name__}: {exc}"

        should_update_direction_risk_register = bool(
            update_direction_risk_register or direction_risk_register_path
        )
        if should_update_direction_risk_register:
            import copy as _copy_for_register

            from direction_risk_register_runtime import (
                apply_direction_risk_to_package,
                compute_direction_transitions,
                empty_register,
                load_register,
                render_risk_register_markdown,
                risk_summary,
                save_register,
            )

            register_path = (
                Path(direction_risk_register_path).expanduser().resolve()
                if direction_risk_register_path
                else output_root / "direction-risk-register.json"
            )
            register = load_register(register_path) if register_path.exists() else empty_register()
            prev_register_snapshot = _copy_for_register.deepcopy(register)
            register_runner = direction_risk_register_runner or default_direction_risk_register_runner
            try:
                register = register_runner(register, postclose_review_result, trade_date)
            except Exception as exc:  # noqa: BLE001
                package["direction_risk_register_error"] = f"{type(exc).__name__}: {exc}"
            else:
                save_register(register, register_path)
                apply_direction_risk_to_package(package, register)
                transitions = compute_direction_transitions(
                    prev_register_snapshot, register, trade_date
                )
                register_report_path = register_path.with_suffix(".md")
                register_report_path.parent.mkdir(parents=True, exist_ok=True)
                register_report_path.write_text(
                    render_risk_register_markdown(register, transitions),
                    encoding="utf-8",
                )
                package["direction_risk_register"] = register
                package["direction_risk_register_path"] = str(register_path)
                package["direction_risk_register_report_path"] = str(register_report_path)
                package["direction_risk_transitions"] = transitions

    if shortlist_result is not None:
        audit_runner = institutional_audit_runner or default_institutional_signal_audit_runner
        audit_path = (
            Path(institutional_audit_output_path).expanduser().resolve()
            if institutional_audit_output_path
            else output_root / "institutional-signal-audit.json"
        )
        audit_report_path = (
            Path(institutional_audit_markdown_output_path).expanduser().resolve()
            if institutional_audit_markdown_output_path
            else output_root / "institutional-signal-audit.md"
        )

        def run_audit_and_persist(extra_evidence_payloads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            audit_payload = build_institutional_signal_audit_payload(
                package,
                shortlist_result=shortlist_result,
                postclose_review_result=package.get("postclose_review") if isinstance(package.get("postclose_review"), dict) else None,
                institutional_evidence_payloads=[
                    *(institutional_evidence_payloads or []),
                    *discovered_evidence_payloads,
                    *(extra_evidence_payloads or []),
                ],
            )
            package["institutional_signal_audit_payload"] = audit_payload
            if isinstance(audit_payload.get("source_health"), dict):
                package["source_health"] = dict(audit_payload["source_health"])
            audit_result = audit_runner(audit_payload)
            stock_logic_check = safe_dict(package.get("stock_logic_check"))
            if stock_logic_check:
                audit_result = dict(audit_result)
                audit_result["stock_logic_check"] = stock_logic_check
            thesis_fact_check = safe_dict(package.get("thesis_fact_check"))
            if thesis_fact_check:
                audit_result = dict(audit_result)
                audit_result["thesis_fact_check"] = thesis_fact_check
            write_json(audit_path, audit_result)
            audit_report_path.parent.mkdir(parents=True, exist_ok=True)
            audit_report_path.write_text(render_institutional_signal_audit_markdown(audit_result), encoding="utf-8")
            package["institutional_signal_audit"] = audit_result
            package["institutional_actionability_gate"] = build_institutional_actionability_gate(
                audit_result,
                stock_logic_check=stock_logic_check,
                thesis_fact_check=thesis_fact_check,
            )
            apply_institutional_actionability_gate_to_package(package, package["institutional_actionability_gate"])
            package["institutional_signal_audit_path"] = str(audit_path)
            package["institutional_signal_audit_report_path"] = str(audit_report_path)
            return audit_result

        run_audit_and_persist()
        followups = write_institutional_evidence_followup_requests(
            package,
            shortlist_result,
            output_root=output_root,
            execute=execute_institutional_evidence_followups,
        )
        if execute_institutional_evidence_followups and followups:
            new_evidence_payloads: list[dict[str, Any]] = []
            new_evidence_sources: list[str] = []
            seen_sources = {clean_text(item) for item in discovered_evidence_sources}
            for followup in followups:
                result_path_text = clean_text(followup.get("result_path") or followup.get("expected_result_path"))
                if not result_path_text:
                    continue
                resolved_text = str(Path(result_path_text).expanduser().resolve())
                if resolved_text in seen_sources:
                    continue
                result_path = Path(resolved_text)
                if not result_path.exists():
                    continue
                try:
                    payload = load_json(result_path)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not payload_looks_like_institutional_evidence(payload):
                    continue
                new_evidence_payloads.append(payload)
                new_evidence_sources.append(resolved_text)
                seen_sources.add(resolved_text)
            if new_evidence_payloads:
                discovered_evidence_payloads.extend(new_evidence_payloads)
                discovered_evidence_sources.extend(new_evidence_sources)
                package["institutional_evidence_sources"] = list(discovered_evidence_sources)
                run_audit_and_persist()
                write_institutional_evidence_followup_requests(
                    package,
                    shortlist_result,
                    output_root=output_root,
                    execute=False,
                )

    should_run_trigger_monitor = bool(run_trigger_monitor or trigger_monitor_output_path)
    if should_run_trigger_monitor:
        resolved_longbridge_binary = resolve_trigger_monitor_longbridge_binary(package, longbridge_binary_path)
        monitor_runner = trigger_monitor_runner or default_trigger_monitor_runner
        trigger_monitor = monitor_runner(package, resolved_longbridge_binary)
        if isinstance(trigger_monitor, dict):
            package["trigger_monitor"] = trigger_monitor
            monitor_path = (
                Path(trigger_monitor_output_path).expanduser().resolve()
                if trigger_monitor_output_path
                else output_root / "trigger-monitor.json"
            )
            write_json(monitor_path, trigger_monitor)
            package["trigger_monitor_path"] = str(monitor_path)
            try:
                from trigger_monitor_runtime import render_trigger_monitor_markdown

                monitor_report_path = monitor_path.with_suffix(".md")
                monitor_report_path.parent.mkdir(parents=True, exist_ok=True)
                monitor_report_path.write_text(
                    render_trigger_monitor_markdown(trigger_monitor),
                    encoding="utf-8",
                )
                package["trigger_monitor_report_path"] = str(monitor_report_path)
            except Exception as exc:  # noqa: BLE001
                package["trigger_monitor_report_error"] = f"{type(exc).__name__}: {exc}"

    package["ticker_quote_news_coverage"] = build_ticker_quote_news_coverage(package)
    package["html"] = render_local_stock_pool_manager_html(package)
    html_path.write_text(package["html"], encoding="utf-8")
    write_json(pool_path, package["local_stock_pool"])
    write_json(request_path, package["month_end_request"])
    write_json(
        package_path,
        {key: value for key, value in package.items() if key != "html"},
    )
    return package


__all__ = [
    "build_local_stock_pool_manager_package",
    "build_local_stock_pool_from_trading_plan_result",
    "build_local_stock_pool_from_trading_plan_text",
    "build_month_end_request",
    "build_fresh_discovery_sector_layer",
    "normalize_reused_fresh_discovery_coverage",
    "build_postclose_observation_layer",
    "build_earnings_calendar_watch",
    "build_event_calendar_watch",
    "build_entry_list_screening_from_shortlist_result",
    "build_institutional_signal_audit_payload",
    "build_institutional_actionability_gate",
    "apply_institutional_actionability_gate_to_package",
    "default_source_capability_snapshot",
    "default_source_health_probe_snapshot",
    "discover_earnings_calendar_payloads",
    "discover_event_calendar_payloads",
    "discover_institutional_evidence_payloads",
    "merge_market_snapshots_into_local_stock_pool",
    "load_longbridge_news_details",
    "load_longbridge_plan_source_run",
    "load_pool_or_template",
    "load_trading_plan_result",
    "payload_looks_like_institutional_evidence",
    "payload_looks_like_earnings_calendar",
    "payload_looks_like_event_calendar",
    "render_local_stock_pool_manager_html",
    "safe_json_for_script",
    "write_local_stock_pool_manager_package",
    "default_shortlist_runner",
    "default_postclose_review_runner",
    "default_institutional_signal_audit_runner",
    "default_trigger_monitor_runner",
    "default_trade_journal_decision_runner",
    "default_trade_journal_outcome_runner",
    "default_direction_risk_register_runner",
    "resolve_trigger_monitor_longbridge_binary",
    "render_entry_list_screening_status",
    "render_entry_list_screening_markdown",
    "render_trigger_monitor_status",
    "render_trade_journal_status",
    "render_direction_risk_register_status",
    "render_postclose_review_markdown",
    "render_earnings_calendar_watch_status",
    "render_event_calendar_watch_status",
    "render_event_calendar_watch_markdown",
    "build_ticker_quote_news_coverage",
    "render_ticker_quote_news_coverage_status",
    "build_stock_logic_check",
    "render_stock_logic_check_status",
    "build_thesis_fact_check",
    "render_thesis_fact_check_status",
    "render_thesis_fact_check_markdown",
    "render_institutional_actionability_gate",
    "render_institutional_evidence_followups_status",
    "render_institutional_signal_audit_markdown",
    "build_x_index_social_evidence_request",
    "build_social_capture_focus_terms",
    "build_x_search_context_terms",
    "collect_social_evidence_candidates",
    "collect_social_evidence_phrases",
    "default_x_social_account_allowlist",
    "detect_codex_chrome_cdp_endpoint",
    "institutional_run_root",
    "audit_upgrade_priority_ids",
    "refresh_institutional_evidence_followup_result_state",
    "write_institutional_evidence_followup_requests",
    "build_ownership_fundamental_argv",
    "build_ownership_fundamental_run_command",
    "default_x_index_runner",
    "default_evidence_bundle_runner",
    "execute_x_index_followup",
    "execute_ownership_fundamental_followup",
]
