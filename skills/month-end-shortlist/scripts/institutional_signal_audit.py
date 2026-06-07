#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "institutional_signal_audit/v1"


OPEN_SOURCE_BASES: list[dict[str, Any]] = [
    {
        "name": "OpenBB Open Data Platform",
        "url": "https://docs.openbb.co/",
        "role": ["data_integration", "python_cli_research_layer", "analyst_workspace_bridge"],
        "notes": "Use as a vendor-neutral integration layer, not as a replacement for repo-native artifacts.",
    },
    {
        "name": "AKShare",
        "url": "https://github.com/akfamily/akshare",
        "role": ["china_market_data", "macro_data", "public_web_data_adapter"],
        "notes": "Good candidate for A-share/HK/CN macro enrichment; always label source freshness and risk.",
    },
    {
        "name": "SEC EDGAR APIs",
        "url": "https://www.sec.gov/edgar/sec-api-documentation",
        "role": ["us_filing_fundamentals", "companyfacts", "submissions"],
        "notes": "Official public source; useful for US single-name fundamentals and event evidence.",
    },
    {
        "name": "FRED",
        "url": "https://www.federalreserve.gov/data/data-download-fred-information.htm",
        "role": ["macro_rates_inflation_liquidity"],
        "notes": "Use for macro overlays such as yields, breakevens, liquidity, and financial conditions.",
    },
    {
        "name": "GDELT",
        "url": "https://gdeltcloud.com/",
        "role": ["global_news_events", "geopolitics", "supply_chain_alerts"],
        "notes": "Useful for machine-readable event/news monitoring before manual source confirmation.",
    },
    {
        "name": "TA-Lib",
        "url": "https://ta-lib.org/",
        "role": ["technical_indicators", "candlestick_patterns"],
        "notes": "Use behind existing trend/RS/VCP checks when standard indicator parity matters.",
    },
    {
        "name": "vectorbt",
        "url": "https://github.com/polakowo/vectorbt",
        "role": ["vectorized_backtest", "portfolio_research"],
        "notes": "Candidate for fast hypothesis testing; keep live trading separate from research backtests.",
    },
    {
        "name": "QuantStats",
        "url": "https://github.com/ranaroussi/quantstats",
        "role": ["portfolio_metrics", "drawdown_risk", "performance_reporting"],
        "notes": "Candidate for strategy/report diagnostics after signals are exported as return series.",
    },
    {
        "name": "FinGPT / FinNLP",
        "url": "https://github.com/AI4Finance-Foundation/FinGPT",
        "role": ["financial_nlp", "sentiment", "news_text_features"],
        "notes": "Use for research-only text features; do not let NLP sentiment override source-backed catalysts.",
    },
]


MONITORING_SIGNAL_ROSTER: list[dict[str, Any]] = [
    {
        "id": "rates_policy",
        "signals": ["US2Y", "US10Y", "US30Y", "2s10s", "real_yields", "breakevens", "Fed_path"],
        "method_note": "Start with rates and policy expectations; a higher discount-rate regime changes which equity duration can lead.",
    },
    {
        "id": "fx_liquidity",
        "signals": ["DXY", "USD/CNH", "USD/JPY", "global_liquidity", "financial_conditions"],
        "method_note": "Track dollar/liquidity stress before trusting broad risk-on breakouts.",
    },
    {
        "id": "credit_volatility",
        "signals": ["VIX", "VVIX", "MOVE", "HY_spreads", "HYG/LQD", "CDX_or_public_proxy"],
        "method_note": "Credit and volatility confirm whether equity weakness is ordinary rotation or risk-off de-grossing.",
    },
    {
        "id": "commodities_geopolitics",
        "signals": ["WTI", "Brent", "gold", "copper", "shipping", "geopolitical_event_risk"],
        "method_note": "Commodity shocks can dominate sector leadership and inflation/rates expectations.",
    },
    {
        "id": "equity_leadership_breadth",
        "signals": ["SPY", "QQQ", "IWM", "SMH", "NVDA", "sector_ETFs", "A_share_sector_rank", "HK/CN_ADR"],
        "method_note": "Separate index-level rebounds from leadership breadth and real sector transmission.",
    },
    {
        "id": "positioning_flows",
        "signals": ["ETF_flows", "northbound_southbound", "put_call", "options_skew", "volume_anomaly"],
        "method_note": "Use positioning as a risk amplifier, not as a standalone directional signal.",
    },
    {
        "id": "earnings_fundamentals",
        "signals": ["earnings_revisions", "margins", "capex", "SEC_filings", "guidance", "ownership_changes"],
        "method_note": "Validate whether theme beta is turning into business transmission.",
    },
    {
        "id": "news_social_claims",
        "signals": ["GDELT", "x_index", "watch_author_divergence", "official_news", "supply_chain_checks"],
        "method_note": "Treat social/news claims as leads until confirmed by price, official sources, or fundamentals.",
    },
]


LAYER_SPECS: list[dict[str, Any]] = [
    {
        "id": "data_provenance",
        "label": "Data provenance and freshness",
        "weight": 10,
        "required": True,
        "rationale": "Institutional workflows must show source health, freshness, and degradation instead of hiding data gaps.",
    },
    {
        "id": "fresh_discovery",
        "label": "Fresh discovery beyond the old watchlist",
        "weight": 12,
        "required": True,
        "rationale": "The system must keep discovering current leaders instead of recycling stale local-pool names.",
    },
    {
        "id": "macro_regime",
        "label": "Macro regime overlay",
        "weight": 10,
        "required": True,
        "rationale": "Rates, FX, liquidity, inflation, and growth regime should frame sector and single-name risk.",
    },
    {
        "id": "sector_leadership",
        "label": "Sector and industry leadership",
        "weight": 10,
        "required": True,
        "rationale": "Strong stocks should be checked against breadth, board rank, and sector transmission.",
    },
    {
        "id": "single_name_quality",
        "label": "Single-name quality and technical setup",
        "weight": 12,
        "required": True,
        "rationale": "Candidates need trend, relative strength, validation, and score evidence before entering the action list.",
    },
    {
        "id": "catalyst_news",
        "label": "Catalyst and news evidence",
        "weight": 10,
        "required": True,
        "rationale": "Price strength without a catalyst ledger is not enough for a durable watchlist.",
    },
    {
        "id": "risk_execution",
        "label": "Execution, invalidation, and sizing",
        "weight": 12,
        "required": True,
        "rationale": "Entry candidates need trigger, stop, invalidation, and sizing guidance before they are tradable.",
    },
    {
        "id": "positioning_flows",
        "label": "Positioning, flow, and options pressure",
        "weight": 6,
        "required": True,
        "rationale": "Institutional daily monitors need capital-flow, short-interest, option, or positioning evidence before calling a setup institutional-ready.",
    },
    {
        "id": "review_loop",
        "label": "Post-close review and feedback loop",
        "weight": 8,
        "required": True,
        "rationale": "A plan that cannot score missed opportunities and failed triggers will keep repeating mistakes.",
    },
    {
        "id": "social_altdata",
        "label": "Social and alternative-data evidence",
        "weight": 4,
        "required": False,
        "rationale": "X/Reddit/watch-author evidence can improve discovery, but must remain advisory and source-backed.",
    },
    {
        "id": "ownership_fundamental",
        "label": "Ownership, filing, and fundamental evidence",
        "weight": 4,
        "required": False,
        "rationale": "Useful for US/HK/large-cap names and for separating theme beta from business transmission.",
    },
    {
        "id": "validation_backtest",
        "label": "Validation and backtest evidence",
        "weight": 2,
        "required": False,
        "rationale": "Research hypotheses should be testable, but backtests must not be used as live-trade proof alone.",
    },
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def safe_dict_rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in safe_list(value) if isinstance(item, dict)]


def normalize_audit_ticker(value: Any) -> str:
    text = clean_text(value).upper().strip("`")
    if not text:
        return ""
    text = text.replace(" ", "")
    if text.endswith(".SS"):
        text = text[:-3] + ".SH"
    if "." in text:
        return text
    if len(text) == 8 and text[:2] in {"SH", "SZ", "BJ"} and text[2:].isdigit():
        return f"{text[2:]}.{text[:2]}"
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6:
        if digits.startswith(("6", "9")):
            return f"{digits}.SH"
        if digits.startswith(("8", "4")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"
    return text


def candidate_ticker_set(candidates: list[dict[str, Any]]) -> set[str]:
    tickers: set[str] = set()
    for row in candidates:
        ticker = normalize_audit_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        if ticker:
            tickers.add(ticker)
    return tickers


def positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def parse_datetime_value(value: Any) -> datetime | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            dt = datetime.fromtimestamp(float(value), UTC)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        text = clean_text(value)
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def longbridge_detail_quality_counts(
    details: list[Any],
    *,
    analysis_time: Any = None,
    max_age_hours: int = 72,
) -> dict[str, int]:
    reference_time = parse_datetime_value(analysis_time)
    max_age = timedelta(hours=max_age_hours)
    counts = {
        "usable": 0,
        "error": 0,
        "unattributed": 0,
        "stale": 0,
        "empty": 0,
    }
    for item in details:
        if not isinstance(item, dict):
            continue
        fetch_status = clean_text(item.get("fetch_status")).lower()
        if fetch_status not in {"", "ok", "success", "fetched"}:
            counts["error"] += 1
            continue
        content = clean_text(item.get("content_markdown") or item.get("content") or item.get("body") or item.get("text"))
        if not content:
            counts["empty"] += 1
            continue
        if not clean_text(item.get("ticker") or item.get("symbol") or item.get("code")):
            counts["unattributed"] += 1
            continue
        published_at = parse_datetime_value(item.get("published_at") or item.get("publish_time") or item.get("time"))
        if reference_time is not None and published_at is not None and reference_time - published_at > max_age:
            counts["stale"] += 1
            continue
        counts["usable"] += 1
    return counts


def longbridge_detail_freshness_summary(
    details: list[Any],
    *,
    analysis_time: Any = None,
) -> dict[str, Any]:
    reference_time = parse_datetime_value(analysis_time)
    latest: datetime | None = None
    for item in details:
        if not isinstance(item, dict):
            continue
        fetch_status = clean_text(item.get("fetch_status")).lower()
        if fetch_status not in {"", "ok", "success", "fetched"}:
            continue
        content = clean_text(item.get("content_markdown") or item.get("content") or item.get("body") or item.get("text"))
        if not content:
            continue
        published_at = parse_datetime_value(
            item.get("published_at")
            or item.get("publish_time")
            or item.get("time")
            or item.get("datetime")
            or item.get("date")
        )
        if published_at is None:
            continue
        if latest is None or published_at > latest:
            latest = published_at
    if latest is None:
        return {}
    summary: dict[str, Any] = {"latest_news_detail_published_at": latest.isoformat()}
    if reference_time is not None:
        summary["latest_news_detail_age_days"] = round((reference_time - latest).total_seconds() / 86400, 2)
    return summary


def payload_reference_time(payload: dict[str, Any]) -> Any:
    month_end_request = safe_dict(payload.get("month_end_request"))
    return (
        payload.get("analysis_time")
        or month_end_request.get("analysis_time")
        or payload.get("target_date")
        or month_end_request.get("target_date")
    )


def has_meaningful_postclose_review(value: Any) -> bool:
    if isinstance(value, list):
        return any(has_meaningful_postclose_review(item) for item in value)
    review = safe_dict(value)
    if not review:
        return False
    if safe_dict_rows(review.get("candidates_reviewed")):
        return True
    summary = safe_dict(review.get("summary"))
    if positive_number(summary.get("total_reviewed")):
        return True
    for key in (
        "review_checklist",
        "prior_review_adjustments",
        "near_miss_evictions",
        "direction_momentum",
        "direction_divergence_warnings",
        "x_risk_alerts",
    ):
        if safe_list(review.get(key)) or safe_dict(review.get(key)):
            return True
    return False


def dict_rows_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    return [dict(item) for item in safe_list(value) if isinstance(item, dict)]


def unique_content_dict_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        marker = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(row)
    return unique


def merge_external_list_field(merged: dict[str, Any], item: dict[str, Any], key: str) -> None:
    incoming = dict_rows_from_value(item.get(key))
    if not incoming:
        return
    existing = dict_rows_from_value(merged.get(key))
    merged[key] = unique_content_dict_rows([*existing, *incoming])


def merge_external_dict_field(merged: dict[str, Any], item: dict[str, Any], key: str) -> None:
    incoming = item.get(key)
    if incoming in (None, "", [], {}):
        return
    if merged.get(key) in (None, "", [], {}):
        merged[key] = incoming
        return
    if isinstance(merged.get(key), dict) and isinstance(incoming, dict):
        merged[key] = {**merged[key], **incoming}


def external_evidence_schema(item: dict[str, Any]) -> str:
    return clean_text(item.get("schema_version") or item.get("schema") or item.get("workflow_kind")).lower()


def external_evidence_is_longbridge_plan_source(item: dict[str, Any]) -> bool:
    schema_text = external_evidence_schema(item)
    source_path = clean_text(item.get("source_path") or item.get("path") or item.get("artifact_path")).lower()
    return (
        "longbridge-institutional-evidence" in schema_text
        or "longbridge_plan_source" in schema_text
        or "longbridge-institutional-evidence" in source_path
    )


def longbridge_source_quality_is_usable(item: dict[str, Any]) -> bool:
    summary = safe_dict(item.get("summary"))
    source_health = safe_dict(item.get("source_health"))
    usable_count = summary.get("news_detail_usable_count", source_health.get("news_detail_usable_count"))
    if usable_count not in (None, "", [], {}):
        try:
            return int(usable_count) > 0
        except (TypeError, ValueError):
            return False
    quality = clean_text(summary.get("longbridge_plan_source_quality") or source_health.get("longbridge_plan_sources")).lower()
    if quality and quality != "ok":
        return False
    return bool(safe_list(item.get("news")))


def merge_external_source_health(source_health: dict[str, Any], item: dict[str, Any]) -> None:
    incoming = safe_dict(item.get("source_health"))
    if not incoming:
        return
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key not in source_health:
            source_health[key] = value
            continue
        if isinstance(source_health.get(key), (int, float)) and isinstance(value, (int, float)):
            source_health[key] = source_health[key] + value
        elif clean_text(source_health.get(key)) in {"", "ok"} and clean_text(value):
            source_health[key] = value


def merge_external_evidence(payload: dict[str, Any], evidence_payloads: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [item for item in evidence_payloads or [] if isinstance(item, dict)]
    if not rows:
        return payload
    merged = dict(payload)
    external = safe_dict_rows(merged.get("external_evidence"))
    merged["external_evidence"] = external + rows
    source_health = dict(safe_dict(merged.get("source_health")))
    source_health["external_evidence_count"] = len(merged["external_evidence"])
    stale_source_count = 0
    source_paths = [
        clean_text(item.get("source_path") or item.get("path") or item.get("artifact_path"))
        for item in merged["external_evidence"]
        if clean_text(item.get("source_path") or item.get("path") or item.get("artifact_path"))
    ]
    for item in merged["external_evidence"]:
        summary = safe_dict(item.get("summary"))
        if summary.get("stale_source_count") not in (None, "", [], {}):
            try:
                stale_source_count += int(summary.get("stale_source_count") or 0)
            except (TypeError, ValueError):
                continue
        merge_external_source_health(source_health, item)
        for key in ("macro_health_overlay", "market_regime_overlay", "global_macro_risk", "macro_regime", "market_context"):
            if key not in merged and item.get(key) not in (None, "", [], {}):
                merged[key] = item[key]
        if "information_completion_index" not in merged and isinstance(item.get("information_completion_index"), dict):
            merged["information_completion_index"] = item["information_completion_index"]
        list_keys = [
            "sector_rankings",
            "sector_views",
            "capital_flows",
            "positioning_flows",
            "announcements",
            "news",
            "longbridge_news_headlines",
            "longbridge_news_details",
            "event_cards",
            "events",
            "filings",
            "longbridge_filings",
            "longbridge_topics",
            "longbridge_capital_flows",
            "recent_validation",
            "validation",
            "validations",
            "backtest",
            "backtests",
            "actuals",
            "quant_analysis",
            "performance_metrics",
            "industry_valuation",
            "industry_valuations",
            "peer_valuation",
            "peer_valuations",
            "source_capabilities",
            "capabilities",
            "source_health_probes",
            "health_probes",
        ]
        if external_evidence_is_longbridge_plan_source(item) and not longbridge_source_quality_is_usable(item):
            list_keys = [key for key in list_keys if key not in {"news", "event_cards", "events"}]
        for key in (
            *list_keys,
        ):
            merge_external_list_field(merged, item, key)
        for key in ("fundamentals", "ownership"):
            merge_external_dict_field(merged, item, key)
    if stale_source_count:
        source_health["stale_external_evidence_count"] = stale_source_count
    if source_paths:
        source_health["external_evidence_paths"] = source_paths
    merged["source_health"] = source_health
    return merged


def unique_dict_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        row_id = id(row)
        if row_id in seen:
            continue
        unique.append(row)
        seen.add(row_id)
    return unique


def collect_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in (
        "top_picks",
        "priority_watchlist",
        "near_miss_candidates",
        "diagnostic_scorecard",
        "candidates",
        "market_strength_candidates",
        "setup_launch_candidates",
    ):
        rows.extend([item for item in safe_list(payload.get(key)) if isinstance(item, dict)])
    plan = safe_dict(payload.get("trading_plan"))
    rows.extend([item for item in safe_list(plan.get("candidates")) if isinstance(item, dict)])
    return unique_dict_rows(rows)


def find_truthy_by_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and has_nonempty_evidence_value(item):
                return True
            if find_truthy_by_key(item, keys):
                return True
    elif isinstance(value, list):
        return any(find_truthy_by_key(item, keys) for item in value)
    return False


def has_nonempty_evidence_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, dict):
        return any(has_nonempty_evidence_value(item) for item in value.values())
    if isinstance(value, list):
        return any(has_nonempty_evidence_value(item) for item in value)
    return True


def count_nested_evidence_rows(value: Any, keys: set[str]) -> int:
    if isinstance(value, dict):
        count = 0
        for key, item in value.items():
            if key in keys:
                if isinstance(item, list):
                    count += sum(1 for row in item if row not in (None, "", [], {}))
                elif item not in (None, "", [], {}):
                    count += 1
            count += count_nested_evidence_rows(item, keys)
        return count
    if isinstance(value, list):
        return sum(count_nested_evidence_rows(item, keys) for item in value)
    return 0


def candidate_has_any(candidate: dict[str, Any], keys: set[str]) -> bool:
    return any(has_nonempty_evidence_value(candidate.get(key)) for key in keys)


def candidate_has_trade_card(candidate: dict[str, Any]) -> bool:
    trade_card = safe_dict(candidate.get("trade_card"))
    if trade_card and any(clean_text(trade_card.get(key)) for key in ("watch_action", "trigger", "invalidation", "stop")):
        return True
    return any(clean_text(candidate.get(key)) for key in ("watch_action", "trigger", "invalidation", "stop", "stop_loss"))


def payload_without_raw_external_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    if "external_evidence" not in payload:
        return payload
    filtered = dict(payload)
    filtered.pop("external_evidence", None)
    return filtered


def contains_social_evidence(value: Any) -> bool:
    if isinstance(value, dict):
        schema_text = clean_text(value.get("schema_version") or value.get("schema") or value.get("kind")).lower()
        platform_text = clean_text(value.get("platform") or value.get("source_platform")).lower()
        social_schema = any(marker in schema_text for marker in ("x-index", "x_index", "reddit", "social"))
        tweet_rows = value.get("tweets")
        if isinstance(tweet_rows, list) and any(
            isinstance(row, dict)
            and clean_text(row.get("url") or row.get("post_url") or row.get("source_url"))
            and clean_text(row.get("text") or row.get("post_text") or row.get("post_text_raw"))
            and clean_text(row.get("handle") or row.get("author_handle") or row.get("author"))
            for row in tweet_rows
        ):
            if (
                social_schema
                or platform_text in {"x", "twitter", "reddit"}
                or clean_text(value.get("pageUrl") or value.get("page_url")).lower().startswith(("https://x.com/", "https://twitter.com/", "https://www.reddit.com/"))
                or has_nonempty_evidence_value(value.get("followingClick"))
                or has_nonempty_evidence_value(value.get("whitelist"))
            ):
                return True
        direct_social_keys = (
            "x_posts",
            "x_live_index_result_paths",
            "x_index_results",
            "reddit_posts",
            "browser_captures",
            "chrome_captures",
            "social_evidence",
        )
        if any(has_nonempty_evidence_value(value.get(key)) for key in direct_social_keys):
            return True
        evidence_pack = safe_dict(value.get("evidence_pack"))
        if any(has_nonempty_evidence_value(evidence_pack.get(key)) for key in ("x_posts", "reddit_posts")):
            return True
        if value.get("posts") not in (None, "", [], {}) and (
            value.get("handles") not in (None, "", [], {})
            or value.get("authors") not in (None, "", [], {})
            or value.get("source_accounts") not in (None, "", [], {})
            or platform_text in {"x", "twitter", "reddit"}
            or social_schema
            or clean_text(value.get("pageUrl") or value.get("page_url") or value.get("targetUrl") or value.get("target_url")).lower().startswith(("https://www.reddit.com/", "https://reddit.com/"))
            or "reddit" in clean_text(value.get("source")).lower()
        ):
            return True
        if platform_text in {"x", "twitter", "reddit"} and any(
            clean_text(value.get(key))
            for key in ("text", "post_text", "post_text_raw", "url", "post_url", "source_url")
        ):
            return True
        return any(
            contains_social_evidence(item)
            for key, item in value.items()
            if key not in {"background_x_posts", "background_posts"}
        )
    if isinstance(value, list):
        return any(contains_social_evidence(item) for item in value)
    return False


SOCIAL_EVIDENCE_LIST_KEYS = ("tweets", "posts", "x_posts", "reddit_posts", "social_evidence")
SOCIAL_TEXT_KEYS = ("text", "post_text", "post_text_raw", "title", "body", "selftext", "summary", "content")
SOCIAL_TIME_KEYS = ("datetime", "created_at", "published_at", "date", "time", "timestamp")


def iter_social_evidence_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            rows.extend(iter_social_evidence_rows(item))
        return rows
    if not isinstance(value, dict):
        return rows
    if any(clean_text(value.get(key)) for key in SOCIAL_TEXT_KEYS) or clean_text(
        value.get("url") or value.get("post_url") or value.get("source_url")
    ):
        rows.append(value)
    for key in SOCIAL_EVIDENCE_LIST_KEYS:
        rows.extend(safe_dict_rows(value.get(key)))
    evidence_pack = safe_dict(value.get("evidence_pack"))
    for key in SOCIAL_EVIDENCE_LIST_KEYS:
        rows.extend(safe_dict_rows(evidence_pack.get(key)))
    return rows


def social_evidence_row_is_fresh(row: dict[str, Any], reference_time: datetime | None) -> bool:
    status = clean_text(
        row.get("freshness_status") or row.get("freshness") or row.get("recency_status")
    ).lower()
    if status in {"stale", "old", "expired"}:
        return False
    if status in {"fresh", "current", "recent", "same_day"}:
        return True
    published_at = None
    for key in SOCIAL_TIME_KEYS:
        published_at = parse_datetime_value(row.get(key))
        if published_at is not None:
            break
    if reference_time is None or published_at is None:
        return False
    return reference_time - published_at <= timedelta(hours=72)


def social_evidence_row_matches_candidate(row: dict[str, Any], candidate: dict[str, Any]) -> bool:
    candidate_ticker = normalize_audit_ticker(candidate.get("ticker") or candidate.get("symbol") or candidate.get("code"))
    row_ticker = normalize_audit_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
    if candidate_ticker and row_ticker == candidate_ticker:
        return True
    text_parts = [
        clean_text(row.get(key))
        for key in (*SOCIAL_TEXT_KEYS, "url", "post_url", "source_url")
        if clean_text(row.get(key))
    ]
    haystack = " ".join(text_parts)
    haystack_upper = haystack.upper()
    if candidate_ticker:
        ticker_root = candidate_ticker.split(".", 1)[0]
        if candidate_ticker in haystack_upper or (len(ticker_root) >= 3 and ticker_root in haystack_upper):
            return True
    for key in ("name", "company", "company_name"):
        name = clean_text(candidate.get(key))
        if len(name) >= 2 and name.lower() in haystack.lower():
            return True
    return False


def external_social_catalyst_covered_tickers(
    payload: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    analysis_time: Any = None,
) -> set[str]:
    reference_time = parse_datetime_value(analysis_time)
    covered: set[str] = set()
    for source in safe_dict_rows(payload.get("external_evidence")):
        if not contains_social_evidence(source):
            continue
        for row in iter_social_evidence_rows(source):
            if not social_evidence_row_is_fresh(row, reference_time):
                continue
            for candidate in candidates:
                ticker = normalize_audit_ticker(candidate.get("ticker") or candidate.get("symbol") or candidate.get("code"))
                if ticker and social_evidence_row_matches_candidate(row, candidate):
                    covered.add(ticker)
    return covered


def layer_result(layer_id: str, status: str, evidence: list[str], missing: list[str]) -> dict[str, Any]:
    fraction = {"pass": 1.0, "partial": 0.5, "fail": 0.0}.get(status, 0.0)
    return {
        "id": layer_id,
        "status": status,
        "score_fraction": fraction,
        "evidence": evidence,
        "missing": missing,
    }


def evaluate_data_provenance(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: list[str] = []
    if safe_dict(payload.get("fresh_discovery_coverage")):
        evidence.append("fresh_discovery_coverage")
    if safe_dict(payload.get("run_completeness")):
        evidence.append("run_completeness")
    source_health = safe_dict(payload.get("source_health"))
    if source_health:
        evidence.append("source_health")
    stale_external_evidence_count = source_health.get("stale_external_evidence_count", 0)
    if stale_external_evidence_count:
        evidence.append(f"stale_external_evidence_count={stale_external_evidence_count}")
    if safe_dict(payload.get("workflow_preflight")):
        evidence.append("workflow_preflight")
    if safe_list(payload.get("source_capabilities")):
        evidence.append("source_capabilities")
    if safe_list(payload.get("source_health_probes")):
        evidence.append("source_health_probes")
    if find_truthy_by_key(payload, {"analysis_time", "target_date", "data_freshness", "source_paths"}):
        evidence.append("timestamp_or_source_paths")
    status = "pass" if len(evidence) >= 2 else "partial" if evidence else "fail"
    if stale_external_evidence_count and status == "pass":
        status = "partial"
    missing = ["source health and freshness markers"] if status == "fail" else []
    if stale_external_evidence_count:
        missing.append("refresh stale external evidence")
    return layer_result("data_provenance", status, evidence, missing)


def evaluate_fresh_discovery(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    coverage = safe_dict(payload.get("fresh_discovery_coverage"))
    status_value = clean_text(coverage.get("status"))
    sector_ranking_count = int(coverage.get("sector_ranking_count") or 0)
    sector_view_count = int(coverage.get("sector_view_count") or 0)
    strong_sector_view_count = int(coverage.get("strong_sector_view_count") or 0)
    evidence: list[str] = []
    if status_value:
        evidence.append(f"fresh_discovery_coverage.status={status_value}")
    if coverage.get("fresh_market_strength_candidate_count", 0):
        evidence.append("fresh_market_strength_candidate_count")
    if sector_ranking_count and sector_view_count and strong_sector_view_count:
        evidence.append("strong_sector_discovery")
    if any(clean_text(row.get("source")).startswith("market_strength") for row in candidates):
        evidence.append("market_strength_candidates")
    if status_value == "covered" or (
        status_value == "sector_only"
        and sector_ranking_count > 0
        and sector_view_count > 0
        and strong_sector_view_count > 0
    ):
        status = "pass"
    elif status_value in {"sector_only", "baseline_only", "no_candidates"} or evidence:
        status = "partial"
    else:
        status = "fail"
    return layer_result("fresh_discovery", status, evidence, ["fresh non-baseline candidate discovery"] if status == "fail" else [])


def evaluate_macro_regime(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    keys = {"macro_health_overlay", "market_regime_overlay", "global_macro_risk", "macro_regime", "market_context"}
    evidence = [key for key in keys if payload.get(key) not in (None, "", [], {})]
    factor_keys = {
        "real_yield",
        "dxy",
        "breakeven",
        "liquidity",
        "financial_conditions",
        "real_yield_signal",
        "real_yield_10y_change_bp_20d",
        "real_yield_10y_latest",
        "dxy_signal",
        "dxy_change_pct_20d",
        "dxy_latest",
        "breakeven_signal",
        "breakeven_10y_change_bp_20d",
        "financial_conditions_signal",
        "financial_conditions_latest",
        "liquidity_signal",
        "reserve_rrp_tga_total_bil",
        "reserve_rrp_tga_total_change_bil_20d",
        "sofr_latest",
        "iorb_latest",
        "sofr_iorb_spread_bp",
    }
    if find_truthy_by_key(payload, factor_keys):
        evidence.append("macro_factor_fields")
    if "macro_factor_fields" in evidence:
        status = "pass"
    elif evidence:
        status = "partial"
    else:
        status = "fail"
    return layer_result("macro_regime", status, evidence, ["macro_health_overlay or market_regime_overlay"] if status == "fail" else [])


def evaluate_sector_leadership(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    coverage = safe_dict(payload.get("fresh_discovery_coverage"))
    evidence: list[str] = []
    if coverage.get("sector_ranking_count", 0):
        evidence.append("fresh_discovery_coverage.sector_ranking_count")
    if coverage.get("strong_sector_view_count", 0):
        evidence.append("fresh_discovery_coverage.strong_sector_view_count")
    if safe_list(payload.get("sector_rankings")):
        evidence.append("sector_rankings")
    if safe_list(payload.get("sector_views")):
        evidence.append("sector_views")
    if find_truthy_by_key(payload, {"industry_valuation", "industry_valuations", "peer_valuation", "peer_valuations"}):
        evidence.append("industry_valuation")
    if any(candidate_has_any(row, {"sector_name", "market_strength_sector_name", "chain_name"}) for row in candidates):
        evidence.append("candidate_sector_context")
    status = "pass" if len(evidence) >= 2 else "partial" if evidence else "fail"
    return layer_result("sector_leadership", status, evidence, ["sector rankings/views plus candidate sector context"] if status == "fail" else [])


def evaluate_single_name_quality(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: list[str] = []
    if candidates:
        evidence.append(f"candidate_count={len(candidates)}")
    quality_keys = {"score_components", "market_validation", "price_snapshot", "price_paths", "trend_template", "rs90", "volume_ratio"}
    quality_count = sum(1 for row in candidates if candidate_has_any(row, quality_keys))
    if quality_count:
        evidence.append(f"quality_candidate_count={quality_count}")
    longbridge_quote_count = sum(
        1
        for row in candidates
        if candidate_has_any(row, {"longbridge_quote", "longbridge_snapshot", "longbridge_security_quote"})
    )
    if longbridge_quote_count:
        evidence.append(f"longbridge_quote_candidate_count={longbridge_quote_count}")
    status = "pass" if candidates and (quality_count or longbridge_quote_count) else "partial" if candidates else "fail"
    return layer_result("single_name_quality", status, evidence, ["candidate score, RS/trend, or market validation evidence"] if status == "fail" else [])


def evaluate_catalyst_news(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: list[str] = []
    promoted_payload = payload_without_raw_external_evidence(payload)
    keys = {
        "structured_catalyst",
        "structured_catalyst_score",
        "catalyst",
        "catalysts",
        "qualitative_evidence",
        "event_cards",
        "news",
        "sources",
        "source_urls",
        "key_evidence",
        "event_type",
        "event_types",
        "why_now",
        "source_count",
        "longbridge_news_headlines",
        "longbridge_news_details",
        "longbridge_qualitative_evidence",
    }
    candidate_count = sum(1 for row in candidates if candidate_has_any(row, keys))
    if candidate_count:
        evidence.append(f"catalyst_candidate_count={candidate_count}")
    if find_truthy_by_key(promoted_payload, {"catalyst", "catalysts", "news", "event_cards", "qualitative_evidence"}):
        evidence.append("payload_catalyst_or_news")
    news_event_count = count_nested_evidence_rows(promoted_payload, {"news", "event_cards", "events"})
    if news_event_count:
        evidence.append(f"news_event_count={news_event_count}")
    longbridge_news = safe_list(payload.get("longbridge_news_headlines"))
    if longbridge_news:
        evidence.append(f"longbridge_news_headline_count={len(longbridge_news)}")
    longbridge_news_details = safe_list(payload.get("longbridge_news_details"))
    analysis_time = payload_reference_time(payload)
    all_longbridge_detail_counts = longbridge_detail_quality_counts(
        longbridge_news_details,
        analysis_time=analysis_time,
    )
    candidate_tickers = candidate_ticker_set(candidates)
    candidate_catalyst_covered_tickers: set[str] = set()
    if candidate_tickers:
        for row in candidates:
            if not candidate_has_any(row, keys):
                continue
            ticker = normalize_audit_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
            if ticker:
                candidate_catalyst_covered_tickers.add(ticker)
        if candidate_catalyst_covered_tickers:
            evidence.append(f"candidate_catalyst_covered_count={len(candidate_catalyst_covered_tickers)}")
        candidate_catalyst_missing_count = len(candidate_tickers - candidate_catalyst_covered_tickers)
        if candidate_catalyst_missing_count:
            evidence.append(f"candidate_catalyst_missing_count={candidate_catalyst_missing_count}")
    unmatched_usable_detail_count = 0
    longbridge_detail_covered_tickers: set[str] = set()
    if candidate_tickers:
        matched_details = [
            item
            for item in longbridge_news_details
            if isinstance(item, dict)
            and normalize_audit_ticker(item.get("ticker") or item.get("symbol") or item.get("code")) in candidate_tickers
        ]
        longbridge_detail_counts = longbridge_detail_quality_counts(
            matched_details,
            analysis_time=analysis_time,
        )
        longbridge_detail_covered_tickers = {
            normalize_audit_ticker(item.get("ticker") or item.get("symbol") or item.get("code"))
            for item in matched_details
            if longbridge_detail_quality_counts([item], analysis_time=analysis_time)["usable"]
        }
        unmatched_usable_detail_count = max(
            0,
            all_longbridge_detail_counts["usable"] - longbridge_detail_counts["usable"],
        )
    else:
        longbridge_detail_counts = all_longbridge_detail_counts
    longbridge_news_detail_count = longbridge_detail_counts["usable"]
    longbridge_news_detail_error_count = all_longbridge_detail_counts["error"]
    if longbridge_news_detail_count:
        evidence.append(f"longbridge_news_detail_count={longbridge_news_detail_count}")
    if longbridge_news_detail_error_count:
        evidence.append(f"longbridge_news_detail_error_count={longbridge_news_detail_error_count}")
    if all_longbridge_detail_counts["unattributed"]:
        evidence.append(f"longbridge_news_detail_unattributed_count={all_longbridge_detail_counts['unattributed']}")
    if all_longbridge_detail_counts["stale"]:
        evidence.append(f"longbridge_news_detail_stale_count={all_longbridge_detail_counts['stale']}")
    if all_longbridge_detail_counts["empty"]:
        evidence.append(f"longbridge_news_detail_empty_count={all_longbridge_detail_counts['empty']}")
    if unmatched_usable_detail_count:
        evidence.append(f"longbridge_news_detail_unmatched_count={unmatched_usable_detail_count}")
    if candidate_tickers and longbridge_news_details:
        if longbridge_detail_covered_tickers:
            evidence.append(f"longbridge_news_detail_candidate_covered_count={len(longbridge_detail_covered_tickers)}")
        missing_count = len(candidate_tickers - longbridge_detail_covered_tickers)
        if missing_count:
            evidence.append(f"longbridge_news_detail_candidate_missing_count={missing_count}")
    ticker_news_detail_covered_count = 0
    ticker_news_covered_count = 0
    ticker_news_detail_covered_tickers: set[str] = set()
    ticker_coverage = safe_dict(payload.get("ticker_quote_news_coverage"))
    ticker_coverage_rows = safe_dict_rows(ticker_coverage.get("rows"))
    if ticker_coverage_rows:
        if candidate_tickers:
            scoped_ticker_coverage_rows = [
                row for row in ticker_coverage_rows if normalize_audit_ticker(row.get("ticker")) in candidate_tickers
            ]
        else:
            scoped_ticker_coverage_rows = ticker_coverage_rows
        ticker_news_detail_covered_count = sum(
            1
            for row in scoped_ticker_coverage_rows
            if clean_text(row.get("news_detail_status")).lower() == "covered" or positive_number(row.get("news_detail_count"))
        )
        ticker_news_covered_count = sum(
            1
            for row in scoped_ticker_coverage_rows
            if clean_text(row.get("news_status")).lower() in {"covered", "covered_with_limitations"}
        )
        ticker_news_detail_covered_tickers = {
            normalize_audit_ticker(row.get("ticker"))
            for row in scoped_ticker_coverage_rows
            if clean_text(row.get("news_detail_status")).lower() == "covered" or positive_number(row.get("news_detail_count"))
        }
        if ticker_news_covered_count:
            evidence.append(f"ticker_news_covered_count={ticker_news_covered_count}")
        if ticker_news_detail_covered_count:
            evidence.append(f"ticker_news_detail_covered_count={ticker_news_detail_covered_count}")
        if candidate_tickers:
            missing_count = len(candidate_tickers - ticker_news_detail_covered_tickers)
            if missing_count:
                evidence.append(f"ticker_news_detail_missing_count={missing_count}")
    information_completion_covered_tickers: set[str] = set()
    information_completion_index = safe_dict(payload.get("information_completion_index"))
    completion_rows = safe_dict_rows(information_completion_index.get("rows"))
    if completion_rows:
        scoped_completion_rows = [
            row
            for row in completion_rows
            if not candidate_tickers
            or normalize_audit_ticker(row.get("ticker") or row.get("symbol") or row.get("code")) in candidate_tickers
        ]
        complete_rows = [
            row
            for row in scoped_completion_rows
            if clean_text(row.get("status")).lower() == "complete"
        ]
        partial_rows = [
            row
            for row in scoped_completion_rows
            if clean_text(row.get("status")).lower() == "partial"
        ]
        information_completion_covered_tickers = {
            normalize_audit_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
            for row in complete_rows
            if normalize_audit_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        }
        if complete_rows:
            evidence.append(f"information_completion_complete_count={len(complete_rows)}")
        if partial_rows:
            evidence.append(f"information_completion_partial_count={len(partial_rows)}")
        if candidate_tickers:
            missing_count = len(candidate_tickers - information_completion_covered_tickers)
            if missing_count:
                evidence.append(f"information_completion_missing_count={missing_count}")
    source_health = safe_dict(payload.get("source_health"))
    for counter_key in (
        "news_detail_unattributed_count",
        "news_detail_stale_count",
        "news_detail_empty_count",
    ):
        value = source_health.get(counter_key)
        if not value:
            continue
        evidence_key = f"longbridge_{counter_key}"
        if not any(item.startswith(f"{evidence_key}=") for item in evidence):
            evidence.append(f"{evidence_key}={value}")
    latest_published_at = clean_text(source_health.get("latest_news_detail_published_at"))
    if latest_published_at:
        evidence.append(f"longbridge_news_detail_latest_published_at={latest_published_at}")
    latest_age_days = source_health.get("latest_news_detail_age_days")
    if latest_age_days not in (None, "", [], {}):
        evidence.append(f"longbridge_news_detail_latest_age_days={latest_age_days}")
    longbridge_temp = safe_dict(payload.get("longbridge_market_temperature"))
    if longbridge_temp:
        evidence.append("longbridge_market_temperature")
    external_social_covered_tickers = external_social_catalyst_covered_tickers(
        payload,
        candidates,
        analysis_time=analysis_time,
    )
    if external_social_covered_tickers:
        evidence.append(f"external_social_catalyst_covered_count={len(external_social_covered_tickers)}")
    candidate_specific_covered_tickers = (
        candidate_catalyst_covered_tickers | longbridge_detail_covered_tickers | ticker_news_detail_covered_tickers
    )
    information_source_covered_tickers = (
        candidate_specific_covered_tickers | information_completion_covered_tickers | external_social_covered_tickers
    )
    has_structured_catalyst_evidence = bool(
        candidate_catalyst_covered_tickers
        or longbridge_detail_covered_tickers
        or ticker_news_detail_covered_tickers
        or (
            not candidate_tickers
            and (
                candidate_count
                or news_event_count
                or longbridge_news_detail_count
                or ticker_news_detail_covered_count
            )
        )
    )
    if candidate_tickers:
        if information_source_covered_tickers:
            evidence.append(
                f"candidate_specific_catalyst_or_provider_covered_count={len(information_source_covered_tickers)}"
            )
        candidate_specific_missing_count = len(candidate_tickers - information_source_covered_tickers)
        if candidate_specific_missing_count:
            evidence.append(f"candidate_specific_catalyst_or_provider_missing_count={candidate_specific_missing_count}")
        structured_candidate_missing_count = len(candidate_tickers - candidate_specific_covered_tickers)
        if structured_candidate_missing_count:
            evidence.append(f"candidate_specific_structured_missing_count={structured_candidate_missing_count}")
    else:
        candidate_specific_missing_count = 0
        structured_candidate_missing_count = 0
    status = (
        "pass"
        if (
            bool(candidate_tickers)
            and candidate_tickers <= candidate_specific_covered_tickers
            and has_structured_catalyst_evidence
        )
        or (
            not candidate_tickers
            and (candidate_count or news_event_count or longbridge_news_detail_count or ticker_news_detail_covered_count)
        )
        else "partial" if evidence else "fail"
    )
    missing = ["structured catalysts/news evidence"] if status == "fail" else []
    if status == "partial" and candidate_specific_missing_count:
        missing.append("candidate-specific catalyst/news coverage for every selected ticker")
    if status == "partial" and (not has_structured_catalyst_evidence or structured_candidate_missing_count):
        missing.append("structured catalysts/news evidence")
    return layer_result("catalyst_news", status, evidence, missing)


def evaluate_risk_execution(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: list[str] = []
    trade_card_count = sum(1 for row in candidates if candidate_has_trade_card(row))
    if trade_card_count:
        evidence.append(f"trade_card_count={trade_card_count}")
    profile_count = sum(
        1
        for row in candidates
        if candidate_has_any(
            row,
            {
                "trading_profile_playbook",
                "trading_profile_usage",
                "trading_profile_judgment",
                "midday_action",
            },
        )
    )
    if profile_count:
        evidence.append(f"execution_profile_count={profile_count}")
    plan_controls = find_truthy_by_key(payload, {"trigger_plan", "invalidation_plan", "position_sizing_guidance", "risk_flags", "dry_run_action_plan"})
    if plan_controls:
        evidence.append("plan_execution_controls")
    decision_flow = [item for item in safe_list(payload.get("decision_flow")) if isinstance(item, dict)]
    gated_flow_count = 0
    qualified_flow_count = 0
    for item in decision_flow:
        status_value = clean_text(item.get("status")).lower()
        action_value = clean_text(item.get("action")).lower()
        if status_value == "qualified" or action_value in {"execute", "actionable", "buy"}:
            qualified_flow_count += 1
        triggers = safe_dict(item.get("triggers"))
        if (
            (clean_text(triggers.get("upgrade")) or clean_text(triggers.get("downgrade")))
            and clean_text(item.get("operation_reminder"))
        ):
            gated_flow_count += 1
    if gated_flow_count:
        evidence.append(f"decision_flow_risk_gates={gated_flow_count}")
    if trade_card_count and plan_controls:
        status = "pass"
    elif decision_flow and gated_flow_count == len(decision_flow) and qualified_flow_count == 0:
        status = "pass"
    else:
        status = "partial" if evidence else "fail"
    return layer_result("risk_execution", status, evidence, ["trade cards plus trigger/invalidation/sizing controls"] if status == "fail" else [])


def evaluate_positioning_flows(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: list[str] = []
    flow_keys = {
        "positioning_flows",
        "capital_flows",
        "fund_flows",
        "money_flows",
        "northbound_flows",
        "southbound_flows",
        "stock_connect_flows",
        "etf_flows",
        "short_sale_volume",
        "short_interest",
        "margin_financing",
        "securities_lending",
        "dragon_tiger",
        "options_flows",
        "put_call",
        "options_skew",
        "cftc_cot",
        "cot_positioning",
        "volume_anomaly",
    }
    row_count = 0
    for key in flow_keys:
        value = payload.get(key)
        if isinstance(value, list):
            row_count += sum(1 for row in value if row not in (None, "", [], {}))
        elif value not in (None, "", [], {}):
            row_count += 1
    if row_count:
        evidence.append(f"positioning_flow_row_count={row_count}")
    candidate_count = sum(1 for row in candidates if candidate_has_any(row, flow_keys))
    if candidate_count:
        evidence.append(f"candidate_positioning_count={candidate_count}")
    if find_truthy_by_key(payload, flow_keys):
        evidence.append("positioning_or_flow_fields")
    status = "pass" if row_count or candidate_count else "fail"
    return layer_result(
        "positioning_flows",
        status,
        evidence,
        ["capital-flow, stock-connect, short-sale, COT, put/call, options-skew, or positioning evidence"] if status == "fail" else [],
    )


def evaluate_review_loop(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: list[str] = []
    if has_meaningful_postclose_review(payload.get("postclose_review")):
        evidence.append("postclose_review")
    if safe_dict(payload.get("review_checklist")) or safe_list(payload.get("review_checklist")):
        evidence.append("review_checklist")
    if find_truthy_by_key(payload, {"missed_opportunity", "missed_attention_priorities", "next_session_adjustment"}):
        evidence.append("missed_or_next_session_feedback")
    if safe_dict(payload.get("fresh_discovery_coverage")):
        evidence.append("fresh_discovery_coverage")
    status = "pass" if any(item in evidence for item in ("postclose_review", "review_checklist", "missed_or_next_session_feedback")) else "partial" if evidence else "fail"
    return layer_result("review_loop", status, evidence, ["post-close review with reviewed candidates, checklist, or next-session feedback"] if status != "pass" else [])


def evaluate_social_altdata(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    keys = {"x_style_overlays", "x_style_batch_result_path", "x_discovery_context", "x_live_index_result_paths", "x_posts", "browser_captures", "chrome_captures"}
    evidence = [key for key in keys if payload.get(key) not in (None, "", [], {})]
    if find_truthy_by_key(payload, keys | {"reddit", "social_evidence", "watch_author"}):
        evidence.append("nested_social_evidence")
    if contains_social_evidence(payload):
        evidence.append("external_social_evidence")
    status = "pass" if evidence else "fail"
    return layer_result("social_altdata", status, evidence, ["x-index/social evidence artifacts"] if status == "fail" else [])


def evaluate_ownership_fundamental(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    keys = {"valuation", "fundamentals", "financial_event", "filing", "filings", "ownership", "investors", "insider", "institutional"}
    evidence: list[str] = []
    if find_truthy_by_key(payload, keys):
        evidence.append("fundamental_or_ownership_fields")
    candidate_count = sum(1 for row in candidates if candidate_has_any(row, keys))
    if candidate_count:
        evidence.append(f"candidate_fundamental_count={candidate_count}")
    status = "pass" if evidence else "fail"
    return layer_result("ownership_fundamental", status, evidence, ["filing/fundamental/ownership evidence"] if status == "fail" else [])


def evaluate_validation_backtest(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    keys = {
        "recent_validation",
        "validation",
        "validations",
        "backtest",
        "backtests",
        "actuals",
        "quant_analysis",
        "performance_metrics",
    }
    evidence = [key for key in keys if payload.get(key) not in (None, "", [], {})]
    if has_meaningful_postclose_review(payload.get("postclose_review")):
        evidence.append("postclose_review")
    if find_truthy_by_key(payload, keys):
        evidence.append("nested_validation_or_backtest_fields")
    if find_truthy_by_key(payload, {"hit_trigger", "failed_trigger", "stopped", "still_valid", "invalidated"}):
        evidence.append("trigger_outcome_fields")
    status = "pass" if evidence else "fail"
    return layer_result("validation_backtest", status, evidence, ["validation/backtest or trigger-outcome evidence"] if status == "fail" else [])


EVALUATORS = {
    "data_provenance": evaluate_data_provenance,
    "fresh_discovery": evaluate_fresh_discovery,
    "macro_regime": evaluate_macro_regime,
    "sector_leadership": evaluate_sector_leadership,
    "single_name_quality": evaluate_single_name_quality,
    "catalyst_news": evaluate_catalyst_news,
    "risk_execution": evaluate_risk_execution,
    "positioning_flows": evaluate_positioning_flows,
    "review_loop": evaluate_review_loop,
    "social_altdata": evaluate_social_altdata,
    "ownership_fundamental": evaluate_ownership_fundamental,
    "validation_backtest": evaluate_validation_backtest,
}


def audit_signal_stack(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(safe_dict(payload))
    source_health = dict(safe_dict(payload.get("source_health")))
    freshness_summary = longbridge_detail_freshness_summary(
        safe_list(payload.get("longbridge_news_details")),
        analysis_time=payload_reference_time(payload),
    )
    for key, value in freshness_summary.items():
        if source_health.get(key) in (None, "", [], {}):
            source_health[key] = value
    if source_health:
        payload["source_health"] = source_health
    candidates = collect_candidates(payload)
    layers: list[dict[str, Any]] = []
    total_score = 0.0
    max_score = 0.0
    missing_required: list[str] = []
    for spec in LAYER_SPECS:
        evaluator = EVALUATORS[spec["id"]]
        result = evaluator(payload, candidates)
        merged = {**spec, **result}
        score = float(spec["weight"]) * float(result["score_fraction"])
        merged["score"] = round(score, 2)
        layers.append(merged)
        total_score += score
        max_score += float(spec["weight"])
        if spec.get("required") and result["status"] != "pass":
            missing_required.append(spec["id"])
    coverage_ratio = total_score / max_score if max_score else 0.0
    if not missing_required and coverage_ratio >= 0.85:
        status = "institutional_ready"
    elif coverage_ratio >= 0.65:
        status = "research_grade_partial"
    else:
        status = "thin"
    source_health = safe_dict(payload.get("source_health"))
    upgrade_priorities = [
        {
            "id": layer["id"],
            "label": layer["label"],
            "status": layer["status"],
            "missing": layer["missing"],
            "evidence": layer["evidence"],
            "score": layer["score"],
            "rationale": layer["rationale"],
        }
        for layer in layers
        if layer["status"] != "pass"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "score": round(total_score, 2),
        "max_score": round(max_score, 2),
        "coverage_ratio": round(coverage_ratio, 4),
        "candidate_count": len(candidates),
        "missing_required": missing_required,
        "layers": layers,
        "upgrade_priorities": upgrade_priorities,
        "open_source_base": OPEN_SOURCE_BASES,
        "monitoring_signal_roster": MONITORING_SIGNAL_ROSTER,
        "source_health": source_health,
    }


def _source_health_count(source_health: dict[str, Any], key: str) -> float:
    try:
        return float(source_health.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def build_trading_readiness_blockers(audit: dict[str, Any]) -> dict[str, list[str]]:
    source_health = safe_dict(audit.get("source_health"))
    hard_trading_blockers = [clean_text(item) for item in safe_list(audit.get("missing_required")) if clean_text(item)]
    source_limitations: list[str] = []
    fallback_satisfied: list[str] = []
    retry_recommended: list[str] = []

    longbridge_quality = clean_text(source_health.get("longbridge_plan_sources"))
    if longbridge_quality and longbridge_quality.lower() not in {"ok", "covered", "pass"}:
        source_limitations.append(f"longbridge_plan_sources={longbridge_quality}")
    for key in (
        "source_error_count",
        "news_detail_error_count",
        "news_detail_stale_count",
        "news_detail_empty_count",
        "news_detail_unattributed_count",
    ):
        value = _source_health_count(source_health, key)
        if value:
            source_limitations.append(f"{key}={int(value) if value.is_integer() else value}")
    latest_detail_age_days = _source_health_count(source_health, "latest_news_detail_age_days")
    if latest_detail_age_days > 3:
        source_limitations.append(
            f"latest_news_detail_age_days={int(latest_detail_age_days) if latest_detail_age_days.is_integer() else latest_detail_age_days}"
        )

    for key in (
        "news_detail_html_fallback_success_count",
        "news_detail_language_fallback_success_count",
    ):
        value = _source_health_count(source_health, key)
        if value:
            fallback_satisfied.append(f"{key}={int(value) if value.is_integer() else value}")

    completion_complete = _source_health_count(source_health, "information_completion_complete_count")
    completion_total = _source_health_count(source_health, "information_completion_ticker_count")
    if completion_complete:
        if completion_total:
            fallback_satisfied.append(
                f"information_completion_complete_count={int(completion_complete)}/{int(completion_total)}"
            )
        else:
            fallback_satisfied.append(f"information_completion_complete_count={int(completion_complete)}")

    if (
        _source_health_count(source_health, "source_error_count")
        or _source_health_count(source_health, "news_detail_error_count")
        or _source_health_count(source_health, "news_detail_stale_count")
        or _source_health_count(source_health, "news_detail_empty_count")
    ):
        retry_recommended.append("refresh Longbridge news details")

    for layer in safe_list(audit.get("layers")):
        if not isinstance(layer, dict):
            continue
        layer_id = clean_text(layer.get("id"))
        if clean_text(layer.get("status")) == "pass":
            continue
        layer_evidence = " ".join(clean_text(item) for item in safe_list(layer.get("evidence")))
        layer_missing = " ".join(clean_text(item) for item in safe_list(layer.get("missing")))
        if (
            layer_id == "catalyst_news"
            and "external_social_catalyst_covered_count" in layer_evidence
            and "structured catalysts/news evidence" in layer_missing
        ):
            source_limitations.append(
                "catalyst_news: social/source coverage present but structured catalyst evidence still missing"
            )
        for item in safe_list(layer.get("missing")):
            text = clean_text(item)
            if text and layer_id:
                source_limitations.append(f"{layer_id}: {text}")

    return {
        "hard_trading_blockers": hard_trading_blockers,
        "source_limitations": source_limitations,
        "fallback_satisfied": fallback_satisfied,
        "retry_recommended": retry_recommended,
    }


def render_markdown_report(audit: dict[str, Any]) -> str:
    lines = [
        "# Institutional Signal Audit",
        "",
        f"- status: `{clean_text(audit.get('status'))}`",
        f"- score: `{audit.get('score')}/{audit.get('max_score')}`",
        f"- coverage_ratio: `{audit.get('coverage_ratio')}`",
        f"- candidate_count: `{audit.get('candidate_count')}`",
    ]
    source_health = safe_dict(audit.get("source_health"))
    if source_health:
        lines.append(f"- source_health: `{json.dumps(source_health, ensure_ascii=False)}`")
    missing = safe_list(audit.get("missing_required"))
    if missing:
        lines.append(f"- missing_required: `{', '.join(clean_text(item) for item in missing)}`")
    blocker_categories = build_trading_readiness_blockers(audit)
    lines.extend(["", "## Trading Readiness Blockers", ""])
    for key in ("hard_trading_blockers", "source_limitations", "fallback_satisfied", "retry_recommended"):
        values = [clean_text(item) for item in safe_list(blocker_categories.get(key)) if clean_text(item)]
        lines.append(f"- {key}: `{'; '.join(values) if values else 'none'}`")
    lines.extend(["", "## Layer Coverage", ""])
    for layer in safe_list(audit.get("layers")):
        if not isinstance(layer, dict):
            continue
        evidence = ", ".join(clean_text(item) for item in safe_list(layer.get("evidence"))) or "none"
        missing_text = ", ".join(clean_text(item) for item in safe_list(layer.get("missing"))) or "none"
        lines.append(
            f"- `{clean_text(layer.get('id'))}` status=`{clean_text(layer.get('status'))}` score=`{layer.get('score')}` evidence=`{evidence}` missing=`{missing_text}`"
        )
    lines.extend(["", "## Open Source Base", ""])
    for base in safe_list(audit.get("open_source_base")):
        if not isinstance(base, dict):
            continue
        roles = ", ".join(clean_text(item) for item in safe_list(base.get("role")))
        lines.append(f"- {clean_text(base.get('name'))}: {clean_text(base.get('url'))} role=`{roles}`")
    lines.extend(["", "## Monitoring Signal Roster", ""])
    for row in safe_list(audit.get("monitoring_signal_roster")):
        if not isinstance(row, dict):
            continue
        signals = ", ".join(clean_text(item) for item in safe_list(row.get("signals")))
        lines.append(
            f"- `{clean_text(row.get('id'))}` signals=`{signals}` note=`{clean_text(row.get('method_note'))}`"
        )
    return "\n".join(lines).rstrip() + "\n"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload


def load_external_evidence(paths: list[str] | None) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for path_text in paths or []:
        path = Path(path_text).expanduser()
        payload = load_json(path)
        payload.setdefault("source_path", str(path.resolve()))
        evidence.append(payload)
    return evidence


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit shortlist/trading-plan artifacts against an institutional signal stack.")
    parser.add_argument("input", help="Path to a month-end-shortlist or trading-plan result JSON.")
    parser.add_argument(
        "--evidence-json",
        action="append",
        default=[],
        help="Optional external evidence JSON to merge into the audit payload, such as x-index, filing, ownership, or fundamentals artifacts.",
    )
    parser.add_argument("--output", default="", help="Optional path for audit JSON output.")
    parser.add_argument("--markdown-output", default="", help="Optional path for audit Markdown output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = merge_external_evidence(
        load_json(Path(args.input)),
        load_external_evidence(args.evidence_json),
    )
    audit = audit_signal_stack(payload)
    if args.output:
        write_json(Path(args.output), audit)
    if args.markdown_output:
        path = Path(args.markdown_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown_report(audit), encoding="utf-8-sig")
    if not args.output and not args.markdown_output:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
