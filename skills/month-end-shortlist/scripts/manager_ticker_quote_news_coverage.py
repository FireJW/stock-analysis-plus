#!/usr/bin/env python3
from __future__ import annotations

import html
from datetime import UTC, datetime, timedelta
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text
from manager_artifact_links import render_file_link
from manager_html_primitives import parse_float, safe_dict, safe_list
from manager_market_snapshot import render_market_snapshot
from manager_pool_merge import normalize_workflow_display_ticker
from manager_ui_summary import PLAN_BUCKET_LABELS


NEWS_RATE_LIMIT_MARKERS = ("rate-limited", "rate limited", "429", "news_rate_limited")
ACTIONABILITY_GUARD_MARKERS = (
    "no_chase",
    "no chase",
    "wait_for_confirmation",
    "watchlist_only",
    "risk_watchlist",
    "no_add",
    "no add",
    "trigger_not_confirmed",
    "entry_gate:open",
    "entry_list_eligible",
)
SOURCE_SIGNAL_PACKAGE_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("capital_flow", ("longbridge_capital_flows", "capital_flows", "positioning_flows")),
    ("filing", ("longbridge_filings", "filings", "announcements")),
    ("social", ("social_evidence",)),
    ("valuation", ("longbridge_valuation",)),
    ("institution_rating", ("longbridge_institution_rating", "longbridge_institution_ratings")),
    ("forecast_eps", ("longbridge_forecast_eps",)),
    ("consensus", ("longbridge_consensus",)),
    ("financial_report", ("longbridge_financial_reports",)),
    ("operating_review", ("longbridge_operating_reviews",)),
    ("industry_valuation", ("longbridge_industry_valuation",)),
    ("ownership", ("longbridge_shareholders", "longbridge_fund_holders", "longbridge_insider_trades")),
    ("positioning", ("longbridge_short_positions",)),
    ("institutional", ("institutional_signal_audit_payload",)),
)


def normalize_news_publish_time(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), UTC).isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            return text
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).isoformat(timespec="seconds")
    except ValueError:
        return text


def _parse_news_datetime_value(value: Any) -> datetime | None:
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
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
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


def _package_analysis_time(package: dict[str, Any]) -> datetime | None:
    request = safe_dict(package.get("month_end_request"))
    return _parse_news_datetime_value(
        request.get("analysis_time")
        or package.get("analysis_time")
        or request.get("target_date")
        or package.get("target_date")
    )


def _classify_news_detail_row(
    row: dict[str, Any],
    *,
    reference_time: datetime | None,
    max_age_hours: int = 72,
) -> str:
    fetch_status = clean_text(row.get("fetch_status") or row.get("status")).lower()
    if fetch_status not in {"", "ok", "success", "fetched"}:
        return "error"
    content = clean_text(row.get("content_markdown") or row.get("content") or row.get("body") or row.get("text"))
    if not content:
        return "empty"
    published_at = _parse_news_datetime_value(row.get("published_at") or row.get("publish_time") or row.get("time"))
    if reference_time is not None and published_at is not None and reference_time - published_at > timedelta(hours=max_age_hours):
        return "stale"
    return "covered"


def _news_rate_limited(row: dict[str, Any]) -> bool:
    haystack = " ".join(clean_text(row.get(key)) for key in ("id", "title", "url", "message", "error", "detail"))
    lowered = haystack.lower()
    return any(marker in lowered for marker in NEWS_RATE_LIMIT_MARKERS)


def _news_sort_value(row: dict[str, Any]) -> float:
    published_at = row.get("published_at")
    if isinstance(published_at, (int, float)) and not isinstance(published_at, bool):
        return float(published_at)
    text = clean_text(published_at) or clean_text(row.get("published_at_utc")) or clean_text(row.get("publish_time")) or clean_text(row.get("time"))
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def normalize_ticker_quote_news_coverage_row(row: dict[str, Any], *, fallback_ticker: str = "") -> dict[str, Any]:
    ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code")) or fallback_ticker
    title = clean_text(row.get("title") or row.get("headline") or row.get("name"))
    url = clean_text(row.get("url") or row.get("link"))
    news_id = clean_text(row.get("id") or row.get("news_id") or row.get("uuid"))
    published_at_raw = row.get("published_at_utc") or row.get("published_at") or row.get("publish_time") or row.get("time")
    normalized = {
        "ticker": ticker,
        "id": news_id,
        "title": title,
        "url": url,
        "published_at": normalize_news_publish_time(published_at_raw),
        "rate_limited": _news_rate_limited(row),
        "_sort_timestamp": _news_sort_value({"published_at": published_at_raw}),
    }
    return {key: value for key, value in normalized.items() if value not in ("", None, [], {}) or key in {"rate_limited", "_sort_timestamp"}}


def normalize_ticker_quote_topic_row(row: dict[str, Any], *, fallback_ticker: str = "") -> dict[str, Any]:
    ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code")) or fallback_ticker
    title = clean_text(row.get("title") or row.get("headline") or row.get("name") or row.get("text") or row.get("summary"))
    url = clean_text(row.get("url") or row.get("link"))
    topic_id = clean_text(row.get("id") or row.get("topic_id") or row.get("post_id") or row.get("uuid"))
    published_at_raw = row.get("published_at_utc") or row.get("published_at") or row.get("publish_time") or row.get("time")
    normalized = {
        "ticker": ticker,
        "id": topic_id,
        "title": title,
        "url": url,
        "published_at": normalize_news_publish_time(published_at_raw),
        "_sort_timestamp": _news_sort_value({"published_at": published_at_raw}),
    }
    return {key: value for key, value in normalized.items() if value not in ("", None, [], {}) or key == "_sort_timestamp"}


def _format_signal_number(value: Any) -> str:
    number = parse_float(value)
    if number is None:
        return clean_text(value)
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _capital_flow_signal_title(row: dict[str, Any]) -> str:
    payload = safe_dict(row.get("payload"))
    signal_parts: list[str] = []
    for key, label in (
        ("net_inflow_cny", "net inflow"),
        ("net_inflow", "net inflow"),
        ("large_order_net_inflow", "large-order net"),
        ("large_order_inflow", "large-order inflow"),
    ):
        value = row.get(key, payload.get(key))
        if value not in (None, "", [], {}):
            signal_parts.append(f"{label} {_format_signal_number(value)}")
    capital_in = safe_dict(payload.get("capital_in"))
    capital_out = safe_dict(payload.get("capital_out"))
    for bucket in ("large", "medium", "small"):
        in_value = parse_float(capital_in.get(bucket))
        out_value = parse_float(capital_out.get(bucket))
        if in_value is None or out_value is None:
            continue
        signal_parts.append(f"{bucket} net {_format_signal_number(in_value - out_value)}")
    return "Capital flow: " + "; ".join(signal_parts[:3]) if signal_parts else "Capital flow snapshot attached"


def _source_signal_payload(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        payload = safe_dict(row.get(key))
        if payload:
            return payload
    return safe_dict(row)


def _source_signal_title(row: dict[str, Any], source_signal_type: str) -> str:
    payload = _source_signal_payload(
        row,
        source_signal_type,
        "valuation",
        "institutional",
        "fundamentals",
        "industry_valuation",
        "ownership",
        "positioning",
        "raw",
        "payload",
    )
    if source_signal_type == "valuation":
        parts: list[str] = []
        for key, label in (("pe_ttm", "PE"), ("pb", "PB"), ("ps", "PS"), ("peg", "PEG")):
            value = payload.get(key) or row.get(key)
            if value in (None, "", [], {}):
                continue
            formatted = _format_signal_number(value)
            if formatted:
                parts.append(f"{label} {formatted}")
        if parts:
            return "Valuation: " + ", ".join(parts)
        return "Valuation artifact attached"
    if source_signal_type == "institution_rating":
        rating = clean_text(payload.get("rating") or payload.get("recommend") or row.get("rating") or row.get("recommend"))
        target = _format_signal_number(
            payload.get("target_price") or payload.get("target") or row.get("target_price") or row.get("target")
        )
        parts: list[str] = []
        if rating:
            parts.append(rating)
        if target:
            parts.append(f"target {target}")
        if parts:
            return "Institution rating: " + ", ".join(parts)
        return "Institution rating artifact attached"
    if source_signal_type == "forecast_eps":
        period = clean_text(payload.get("period") or payload.get("current_period") or row.get("period") or row.get("current_period"))
        eps = _format_signal_number(payload.get("eps") or row.get("eps"))
        parts: list[str] = []
        if period:
            parts.append(period)
        if eps:
            parts.append(f"EPS {eps}")
        if parts:
            return "Forecast EPS: " + " ".join(parts)
        return "Forecast EPS artifact attached"
    if source_signal_type == "consensus":
        metric = clean_text(payload.get("metric") or row.get("metric") or "EPS")
        period = clean_text(payload.get("period") or payload.get("current_period") or row.get("period") or row.get("current_period"))
        mean = _format_signal_number(payload.get("mean") or row.get("mean"))
        median = _format_signal_number(payload.get("median") or row.get("median"))
        parts: list[str] = []
        if metric:
            parts.append(metric.upper() if metric.lower() == "eps" else metric)
        if period:
            parts.append(period)
        if mean:
            parts.append(f"mean {mean}")
        elif median:
            parts.append(f"median {median}")
        if len(parts) > 1 or mean or median:
            return "Consensus: " + " ".join(parts)
        return "Consensus artifact attached"
    if source_signal_type == "financial_report":
        period = clean_text(payload.get("period") or row.get("period"))
        revenue = _format_signal_number(payload.get("revenue") or row.get("revenue"))
        net_income = _format_signal_number(payload.get("net_income") or row.get("net_income"))
        parts: list[str] = []
        if period:
            parts.append(period)
        if revenue:
            parts.append(f"revenue {revenue}")
        if net_income:
            parts.append(f"net income {net_income}")
        if parts:
            return "Financial report: " + " ".join(parts)
        return "Financial report attached"
    if source_signal_type == "operating_review":
        period = clean_text(payload.get("period") or row.get("period"))
        gross_margin = _format_signal_number(payload.get("gross_margin") or row.get("gross_margin"))
        operating_margin = _format_signal_number(payload.get("operating_margin") or row.get("operating_margin"))
        parts: list[str] = []
        if period:
            parts.append(period)
        if gross_margin:
            parts.append(f"gross margin {gross_margin}")
        if operating_margin:
            parts.append(f"operating margin {operating_margin}")
        if parts:
            return "Operating review: " + " ".join(parts)
        return "Operating review attached"
    if source_signal_type == "industry_valuation":
        industry = clean_text(payload.get("industry") or row.get("industry"))
        percentile = _format_signal_number(payload.get("pe_percentile") or row.get("pe_percentile"))
        parts: list[str] = []
        if industry:
            parts.append(industry)
        if percentile:
            parts.append(f"PE percentile {percentile}")
        if parts:
            return "Industry valuation: " + " ".join(parts)
        return "Industry valuation attached"
    if source_signal_type == "ownership":
        holder = clean_text(
            payload.get("holder_name") or payload.get("name") or row.get("holder_name") or row.get("name")
        )
        shares = _format_signal_number(payload.get("shares") or row.get("shares"))
        change = _format_signal_number(payload.get("change") or row.get("change"))
        parts: list[str] = []
        if holder:
            parts.append(holder)
        if shares:
            parts.append(f"shares {shares}")
        if change:
            parts.append(f"change {change}")
        if parts:
            return "Ownership: " + " ".join(parts)
        return "Ownership artifact attached"
    if source_signal_type == "positioning":
        short_ratio = _format_signal_number(payload.get("short_ratio") or row.get("short_ratio"))
        shares_short = _format_signal_number(payload.get("shares_short") or row.get("shares_short"))
        parts: list[str] = []
        if short_ratio:
            parts.append(f"short ratio {short_ratio}")
        if shares_short:
            parts.append(f"shares short {shares_short}")
        if parts:
            return "Positioning: " + " ".join(parts)
        return "Positioning artifact attached"
    return ""


def _source_signal_type(source_type: str, source: Any, fallback: str) -> str:
    text = clean_text(source_type or source or fallback).lower()
    if "institution_rating" in text or "institutional_rating" in text:
        return "institution_rating"
    if "forecast" in text and "eps" in text:
        return "forecast_eps"
    if "consensus" in text:
        return "consensus"
    if "industry" in text and "valuation" in text:
        return "industry_valuation"
    if "financial" in text and "report" in text:
        return "financial_report"
    if "operating" in text and "review" in text:
        return "operating_review"
    if "valuation" in text:
        return "valuation"
    if "insider" in text and "trade" in text:
        return "ownership"
    if "shareholder" in text or "fund holder" in text or "fund_holder" in text or "ownership" in text:
        return "ownership"
    if text in {"positioning", "short_position", "short_positions"} or ("short" in text and "position" in text):
        return "positioning"
    if "capital" in text or "flow" in text:
        return "capital_flow"
    if "filing" in text or "announcement" in text or "notice" in text:
        return "filing"
    if "topic" in text or "social" in text or "x-index" in text or "x_index" in text or "tweet" in text:
        return "social"
    if "rating" in text:
        return "institution_rating"
    if "fundamental" in text:
        return "financial_report"
    return text.replace(".", "_").replace("-", "_") or fallback or "source_signal"


def normalize_ticker_quote_source_signal_row(
    row: dict[str, Any],
    *,
    fallback_ticker: str = "",
    source_type: str = "source_signal",
) -> dict[str, Any]:
    payload = safe_dict(row.get("payload"))
    ticker = (
        normalize_workflow_display_ticker(
            row.get("ticker")
            or row.get("symbol")
            or row.get("code")
            or row.get("stock_code")
            or payload.get("symbol")
            or payload.get("ticker")
            or payload.get("code")
        )
        or fallback_ticker
    )
    source = clean_text(row.get("source") or payload.get("source") or source_type)
    normalized_source_type = _source_signal_type(
        clean_text(row.get("source_kind") or source_type),
        source,
        source_type,
    )
    title = clean_text(
        row.get("title")
        or row.get("headline")
        or row.get("name")
        or row.get("subject")
        or row.get("summary")
        or row.get("text")
        or row.get("post_text_raw")
        or row.get("raw_text")
        or row.get("content")
        or row.get("description")
        or row.get("form")
    )
    if not title and normalized_source_type == "capital_flow":
        title = _capital_flow_signal_title(row)
    elif not title:
        title = _source_signal_title(row, normalized_source_type)
    url = clean_text(row.get("url") or row.get("link") or row.get("source_url") or row.get("post_url"))
    signal_id = clean_text(row.get("id") or row.get("event_id") or row.get("doc_id") or row.get("uuid"))
    published_at_raw = (
        row.get("published_at_utc")
        or row.get("published_at")
        or row.get("publish_time")
        or row.get("created_at")
        or row.get("posted_at")
        or row.get("datetime")
        or row.get("filed_at")
        or row.get("filing_date")
        or row.get("date")
        or row.get("time")
        or payload.get("timestamp")
        or row.get("retrieved_at")
    )
    normalized = {
        "ticker": ticker,
        "id": signal_id,
        "title": title,
        "url": url,
        "published_at": normalize_news_publish_time(published_at_raw),
        "source": source,
        "source_type": normalized_source_type,
        "_sort_timestamp": _news_sort_value({"published_at": published_at_raw}),
    }
    return {
        key: value
        for key, value in normalized.items()
        if value not in ("", None, [], {}) or key == "_sort_timestamp"
    }


def _iter_source_signal_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for item in value:
            rows.extend(_iter_source_signal_dicts(item))
        return rows
    if not isinstance(value, dict):
        return []
    rows = []
    has_row_shape = any(
        value.get(key) not in (None, "", [], {})
        for key in (
            "ticker",
            "symbol",
            "code",
            "stock_code",
            "title",
            "headline",
            "text",
            "post_text_raw",
            "raw_text",
            "summary",
            "payload",
            "form",
        )
    )
    if has_row_shape:
        rows.append(value)
    for key in (
        "rows",
        "items",
        "data",
        "results",
        "list",
        "posts",
        "tweets",
        "x_posts",
        "background_x_posts",
        "ranked_posts",
        "social_evidence",
        "filings",
        "announcements",
        "external_evidence",
    ):
        nested = value.get(key)
        if nested is value:
            continue
        rows.extend(_iter_source_signal_dicts(nested))
    return rows


def _collect_package_source_signal_rows(package: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    seen_keys: set[str] = set()
    for source_type, package_keys in SOURCE_SIGNAL_PACKAGE_KEYS:
        for package_key in package_keys:
            for row in _iter_source_signal_dicts(package.get(package_key)):
                normalized = normalize_ticker_quote_source_signal_row(row, source_type=source_type)
                ticker = clean_text(normalized.get("ticker"))
                if not ticker and clean_text(normalized.get("source_type")) != "social":
                    continue
                unique_key = "|".join(
                    clean_text(part)
                    for part in (
                        normalized.get("source_type"),
                        ticker,
                        normalized.get("id"),
                        normalized.get("url"),
                        normalized.get("title"),
                        normalized.get("published_at"),
                    )
                )
                if unique_key in seen_keys:
                    continue
                seen_keys.add(unique_key)
                by_ticker.setdefault(ticker or "", []).append(normalized)
    for rows in by_ticker.values():
        rows.sort(key=lambda row: parse_float(row.get("_sort_timestamp")) or 0.0, reverse=True)
        for row in rows:
            row.pop("_sort_timestamp", None)
    return by_ticker


def _source_signal_matches_stock(row: dict[str, Any], *, ticker: str, name: str) -> bool:
    haystack = clean_text(row.get("title"))
    if not haystack:
        return False
    haystack_lower = haystack.lower()
    ticker_text = clean_text(ticker)
    ticker_aliases = [ticker_text]
    if "." in ticker_text:
        ticker_aliases.append(ticker_text.split(".", 1)[0])
    if any(alias and alias.lower() in haystack_lower for alias in ticker_aliases):
        return True
    name_text = clean_text(name)
    return bool(name_text and name_text.lower() in haystack_lower)


def _collect_stock_news_rows(stock: dict[str, Any], package_news_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    plan = safe_dict(stock.get("plan_snapshot"))
    intraday_review = safe_dict(plan.get("intraday_review"))
    ticker = normalize_workflow_display_ticker(stock.get("ticker"))
    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def add_rows(rows: Any, *, fallback_ticker: str = "") -> None:
        for row in safe_list(rows):
            if not isinstance(row, dict):
                continue
            normalized = normalize_ticker_quote_news_coverage_row(row, fallback_ticker=fallback_ticker or ticker)
            news_ticker = clean_text(normalized.get("ticker")) or ticker
            if news_ticker and news_ticker != ticker:
                continue
            key = clean_text(normalized.get("id")) or clean_text(normalized.get("url")) or clean_text(normalized.get("title"))
            if not key:
                key = f"{news_ticker}:{len(candidates)}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            candidates.append(normalized)

    add_rows(plan.get("news_headlines"))
    add_rows(plan.get("company_news_headlines"))
    add_rows(plan.get("news"))
    add_rows(intraday_review.get("news"), fallback_ticker=ticker)
    add_rows(intraday_review.get("news_headlines"), fallback_ticker=ticker)
    add_rows(package_news_rows.get(ticker, []))
    candidates.sort(key=lambda row: parse_float(row.get("_sort_timestamp")) or 0.0, reverse=True)
    for row in candidates:
        row.pop("_sort_timestamp", None)
    return candidates


def build_ticker_quote_news_coverage(package: dict[str, Any]) -> dict[str, Any]:
    pool = safe_dict(package.get("local_stock_pool"))
    stocks = [row for row in safe_list(pool.get("stocks")) if isinstance(row, dict)]
    package_news_rows = [row for row in safe_list(package.get("longbridge_news_headlines")) if isinstance(row, dict)]
    package_news_details = [row for row in safe_list(package.get("longbridge_news_details")) if isinstance(row, dict)]
    package_topic_rows = [row for row in safe_list(package.get("longbridge_topics")) if isinstance(row, dict)]
    information_completion_index = safe_dict(
        package.get("information_completion_index")
        or safe_dict(package.get("longbridge_plan_source_run")).get("information_completion_index")
    )
    reference_time = _package_analysis_time(package)
    news_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in package_news_rows:
        normalized = normalize_ticker_quote_news_coverage_row(row)
        ticker = clean_text(normalized.get("ticker"))
        if not ticker:
            continue
        news_by_ticker.setdefault(ticker, []).append(normalized)
    topic_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in package_topic_rows:
        normalized = normalize_ticker_quote_topic_row(row)
        ticker = clean_text(normalized.get("ticker"))
        if not ticker:
            continue
        topic_by_ticker.setdefault(ticker, []).append(normalized)
    for rows in topic_by_ticker.values():
        rows.sort(key=lambda row: parse_float(row.get("_sort_timestamp")) or 0.0, reverse=True)
        for row in rows:
            row.pop("_sort_timestamp", None)
    details_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in package_news_details:
        ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        if not ticker:
            continue
        details_by_ticker.setdefault(ticker, []).append(row)
    information_completion_by_ticker: dict[str, dict[str, Any]] = {}
    for row in [item for item in safe_list(information_completion_index.get("rows")) if isinstance(item, dict)]:
        ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        if not ticker:
            continue
        information_completion_by_ticker[ticker] = row
    source_signal_by_ticker = _collect_package_source_signal_rows(package)

    rows: list[dict[str, Any]] = []
    quote_covered_count = 0
    quote_missing_count = 0
    news_covered_count = 0
    news_missing_count = 0
    message_covered_count = 0
    message_missing_count = 0
    topic_covered_count = 0
    topic_missing_count = 0
    news_detail_covered_count = 0
    news_detail_error_count = 0
    news_detail_stale_count = 0
    news_detail_empty_count = 0
    news_limited_count = 0
    source_signal_covered_count = 0
    source_signal_missing_count = 0
    message_source_type_counts: dict[str, int] = {}
    guarded_count = 0
    information_completion_complete_count = 0
    information_completion_partial_count = 0
    information_completion_missing_count = 0

    for stock in stocks:
        ticker = normalize_workflow_display_ticker(stock.get("ticker"))
        if not ticker:
            continue
        name = clean_text(stock.get("name")) or ticker
        plan = safe_dict(stock.get("plan_snapshot"))
        snapshot = safe_dict(plan.get("market_snapshot") or stock.get("market_snapshot") or stock.get("quote_snapshot"))
        quote_last = clean_text(snapshot.get("last"))
        quote_time = clean_text(snapshot.get("quote_time"))
        quote_status = "covered" if quote_last else "missing"
        if quote_status == "covered":
            quote_covered_count += 1
        else:
            quote_missing_count += 1

        news_rows = _collect_stock_news_rows(stock, news_by_ticker)
        limited_rows = [row for row in news_rows if bool(row.get("rate_limited"))]
        real_news_rows = [row for row in news_rows if not bool(row.get("rate_limited"))]
        topic_rows = [row for row in safe_list(topic_by_ticker.get(ticker)) if isinstance(row, dict)]
        latest_topic = topic_rows[0] if topic_rows else {}
        source_signal_rows = [row for row in safe_list(source_signal_by_ticker.get(ticker)) if isinstance(row, dict)]
        for row in safe_list(source_signal_by_ticker.get("")):
            if not isinstance(row, dict):
                continue
            if _source_signal_matches_stock(row, ticker=ticker, name=name):
                source_signal_rows.append(row)
        source_signal_rows.sort(key=lambda row: _news_sort_value(row), reverse=True)
        latest_source_signal = source_signal_rows[0] if source_signal_rows else {}
        detail_classifications = [
            _classify_news_detail_row(row, reference_time=reference_time)
            for row in details_by_ticker.get(ticker, [])
        ]
        detail_rows = [
            row
            for row, status_value in zip(details_by_ticker.get(ticker, []), detail_classifications)
            if status_value == "covered"
        ]
        ticker_detail_error_count = detail_classifications.count("error")
        ticker_detail_stale_count = detail_classifications.count("stale")
        ticker_detail_empty_count = detail_classifications.count("empty")
        if real_news_rows:
            news_covered_count += 1
        if not real_news_rows and not limited_rows:
            news_missing_count += 1
        if topic_rows:
            topic_covered_count += 1
        else:
            topic_missing_count += 1
        if source_signal_rows:
            source_signal_covered_count += 1
        else:
            source_signal_missing_count += 1
        if detail_rows:
            news_detail_covered_count += 1
        if ticker_detail_error_count:
            news_detail_error_count += 1
        if ticker_detail_stale_count:
            news_detail_stale_count += 1
        if ticker_detail_empty_count:
            news_detail_empty_count += 1
        if limited_rows:
            news_limited_count += 1

        if real_news_rows and source_signal_rows:
            message_status = "covered_with_source_signals"
        elif real_news_rows and topic_rows:
            message_status = "covered_with_topics"
        elif real_news_rows:
            message_status = "covered"
        elif source_signal_rows:
            message_status = "covered_with_source_signals"
        elif topic_rows:
            message_status = "covered"
        elif limited_rows:
            message_status = "limited"
        else:
            message_status = "missing"
        if message_status == "missing":
            message_missing_count += 1
        else:
            message_covered_count += 1

        if real_news_rows and limited_rows:
            news_status = "covered_with_limitations"
        elif real_news_rows:
            news_status = "covered"
        elif limited_rows:
            news_status = "limited"
        else:
            news_status = "missing"

        strategy_tags = clean_string_list(stock.get("strategy_tags"))
        actionability_tags = [
            tag for tag in strategy_tags if any(marker.lower() in tag.lower() for marker in ACTIONABILITY_GUARD_MARKERS)
        ]
        if actionability_tags:
            guarded_count += 1

        bucket = PLAN_BUCKET_LABELS.get(clean_text(plan.get("bucket")), clean_text(plan.get("bucket")) or "Manual")
        quote_summary = render_market_snapshot(snapshot, compact=True)
        latest_news = news_rows[0] if news_rows else {}
        latest_news_title = clean_text(latest_news.get("title"))
        latest_news_url = clean_text(latest_news.get("url"))
        latest_news_time = clean_text(latest_news.get("published_at"))
        latest_topic_title = clean_text(latest_topic.get("title"))
        latest_topic_url = clean_text(latest_topic.get("url"))
        latest_topic_time = clean_text(latest_topic.get("published_at"))
        latest_source_signal_title = clean_text(latest_source_signal.get("title"))
        latest_source_signal_url = clean_text(latest_source_signal.get("url"))
        latest_source_signal_time = clean_text(latest_source_signal.get("published_at"))
        latest_source_signal_type = clean_text(latest_source_signal.get("source_type"))
        message_source_types = []
        if real_news_rows:
            message_source_types.append("news")
        if topic_rows:
            message_source_types.append("topic")
        for signal_row in source_signal_rows:
            source_type = clean_text(signal_row.get("source_type")) or "source_signal"
            if source_type not in message_source_types:
                message_source_types.append(source_type)
            message_source_type_counts[source_type] = message_source_type_counts.get(source_type, 0) + 1
        limitations: list[str] = []
        if quote_status == "missing":
            limitations.append("quote_missing")
        if limited_rows:
            limitations.append("longbridge_news_rate_limited")
        if not real_news_rows and not limited_rows:
            limitations.append("news_missing")
        if real_news_rows and not detail_rows:
            limitations.append("news_detail_missing")
        if ticker_detail_error_count:
            limitations.append("news_detail_error")
        if ticker_detail_stale_count:
            limitations.append("news_detail_stale")
        if ticker_detail_empty_count:
            limitations.append("news_detail_empty")
        if detail_rows:
            news_detail_status = "covered"
        elif ticker_detail_error_count:
            news_detail_status = "error"
        elif ticker_detail_stale_count:
            news_detail_status = "stale"
        elif ticker_detail_empty_count:
            news_detail_status = "empty"
        else:
            news_detail_status = "missing"
        completion_row = safe_dict(information_completion_by_ticker.get(ticker))
        information_completion_status = clean_text(completion_row.get("status")) or "missing"
        information_completion_sources = clean_string_list(completion_row.get("covered_source_types"))
        information_completion_fallback_sources = clean_string_list(completion_row.get("fallback_source_types"))
        information_completion_news_detail_status = (
            clean_text(completion_row.get("news_detail_status")) or "missing"
        )
        information_completion_source_statuses = _information_completion_source_statuses(completion_row)
        if information_completion_status == "complete":
            information_completion_complete_count += 1
        elif information_completion_status == "partial":
            information_completion_partial_count += 1
        else:
            information_completion_missing_count += 1
        if information_completion_news_detail_status in {"error", "stale", "empty"}:
            limitations.append(f"information_completion_detail_{information_completion_news_detail_status}")
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "bucket": bucket,
                "quote_status": quote_status,
                "quote_summary": quote_summary,
                "quote_time": quote_time,
                "news_status": news_status,
                "news_count": len(real_news_rows),
                "news_limited_count": len(limited_rows),
                "message_status": message_status,
                "message_count": len(real_news_rows) + len(topic_rows) + len(source_signal_rows),
                "message_source_types": message_source_types,
                "topic_status": "covered" if topic_rows else "missing",
                "topic_count": len(topic_rows),
                "source_signal_status": "covered" if source_signal_rows else "missing",
                "source_signal_count": len(source_signal_rows),
                "news_detail_status": news_detail_status,
                "news_detail_count": len(detail_rows),
                "news_detail_error_count": ticker_detail_error_count,
                "news_detail_stale_count": ticker_detail_stale_count,
                "news_detail_empty_count": ticker_detail_empty_count,
                "latest_news_title": latest_news_title,
                "latest_news_url": latest_news_url,
                "latest_news_time": latest_news_time,
                "latest_topic_title": latest_topic_title,
                "latest_topic_url": latest_topic_url,
                "latest_topic_time": latest_topic_time,
                "latest_source_signal_title": latest_source_signal_title,
                "latest_source_signal_url": latest_source_signal_url,
                "latest_source_signal_time": latest_source_signal_time,
                "latest_source_signal_type": latest_source_signal_type,
                "actionability_tags": actionability_tags,
                "limitations": limitations,
                "information_completion_status": information_completion_status,
                "information_completion_sources": information_completion_sources,
                "information_completion_fallback_sources": information_completion_fallback_sources,
                "information_completion_news_detail_status": information_completion_news_detail_status,
                "information_completion_source_statuses": information_completion_source_statuses,
                "information_completion_latest_news_title": clean_text(completion_row.get("latest_news_title")),
                "information_completion_latest_filing_title": clean_text(completion_row.get("latest_filing_title")),
            }
        )

    summary = {
        "stock_count": len(rows),
        "quote_covered_count": quote_covered_count,
        "quote_missing_count": quote_missing_count,
        "news_covered_count": news_covered_count,
        "news_missing_count": news_missing_count,
        "message_covered_count": message_covered_count,
        "message_missing_count": message_missing_count,
        "topic_covered_count": topic_covered_count,
        "topic_missing_count": topic_missing_count,
        "news_detail_covered_count": news_detail_covered_count,
        "news_detail_error_count": news_detail_error_count,
        "news_detail_stale_count": news_detail_stale_count,
        "news_detail_empty_count": news_detail_empty_count,
        "news_limited_count": news_limited_count,
        "source_signal_covered_count": source_signal_covered_count,
        "source_signal_missing_count": source_signal_missing_count,
        "message_source_type_counts": message_source_type_counts,
        "guarded_count": guarded_count,
        "information_completion_complete_count": information_completion_complete_count,
        "information_completion_partial_count": information_completion_partial_count,
        "information_completion_missing_count": information_completion_missing_count,
    }
    return {
        "schema_version": "ticker_quote_news_coverage/v1",
        "summary": summary,
        "rows": rows,
    }


def _latest_coverage_highlight(
    rows: list[dict[str, Any]],
    *,
    title_key: str,
    time_key: str,
) -> dict[str, str]:
    best_row: dict[str, Any] | None = None
    best_time: datetime | None = None
    for row in rows:
        title = clean_text(row.get(title_key))
        if not title:
            continue
        candidate_time = _parse_news_datetime_value(row.get(time_key))
        if best_row is None:
            best_row = row
            best_time = candidate_time
            continue
        if candidate_time is not None and (best_time is None or candidate_time > best_time):
            best_row = row
            best_time = candidate_time
    if not best_row:
        return {}
    highlight: dict[str, str] = {}
    for key in ("ticker", "name", "url", "source_type"):
        value = clean_text(best_row.get(key))
        if value:
            highlight[key] = value
    title = clean_text(best_row.get(title_key))
    if title:
        highlight["title"] = title
    time_text = clean_text(best_row.get(time_key))
    if time_text:
        highlight["time"] = time_text
    return highlight


def _information_completion_source_statuses(row: dict[str, Any]) -> dict[str, str]:
    sources = set(clean_string_list(row.get("covered_source_types")))

    def count_status(count_key: str, source_key: str) -> str:
        if count_key in row:
            return "covered" if parse_float(row.get(count_key)) else "missing"
        return "covered" if source_key in sources else "missing"

    return {
        "quote": clean_text(row.get("quote_status")) or ("covered" if "quote" in sources else "missing"),
        "headline": count_status("news_headline_count", "news_headline"),
        "detail": clean_text(row.get("news_detail_status")) or "missing",
        "filing": count_status("filing_count", "filing"),
        "topic": count_status("topic_count", "topic"),
        "capital": count_status("capital_flow_count", "capital_flow"),
        "expectation": count_status("expectation_count", "expectation"),
        "fundamental": count_status("fundamental_count", "fundamental"),
    }


def _render_information_completion_source_statuses(statuses: dict[str, Any]) -> str:
    ordered_keys = ("quote", "headline", "detail", "filing", "topic", "capital", "expectation", "fundamental")
    return "; ".join(
        f"{key} {clean_text(statuses.get(key)) or 'missing'}"
        for key in ordered_keys
    )


def build_ticker_quote_news_coverage_lead(package: dict[str, Any]) -> str:
    coverage = safe_dict(package.get("ticker_quote_news_coverage"))
    rows = [row for row in safe_list(coverage.get("rows")) if isinstance(row, dict)]
    if not rows:
        return ""
    latest_news = _latest_coverage_highlight(rows, title_key="latest_news_title", time_key="latest_news_time")
    latest_topic = _latest_coverage_highlight(rows, title_key="latest_topic_title", time_key="latest_topic_time")
    latest_source_signal = _latest_coverage_highlight(
        rows,
        title_key="latest_source_signal_title",
        time_key="latest_source_signal_time",
    )
    lead_bits: list[str] = []
    if latest_news:
        news_parts = [
            part
            for part in (
                clean_text(latest_news.get("ticker")),
                clean_text(latest_news.get("title")),
            )
            if part
        ]
        if news_parts:
            news_text = " ".join(news_parts)
            if clean_text(latest_news.get("time")):
                news_text += f" @ {clean_text(latest_news.get('time'))}"
            lead_bits.append(f"Freshest attached news: {news_text}")
    if latest_topic:
        topic_parts = [
            part
            for part in (
                clean_text(latest_topic.get("ticker")),
                clean_text(latest_topic.get("title")),
            )
            if part
        ]
        if topic_parts:
            topic_text = " ".join(topic_parts)
            if clean_text(latest_topic.get("time")):
                topic_text += f" @ {clean_text(latest_topic.get('time'))}"
            lead_bits.append(f"Freshest attached topic: {topic_text}")
    if latest_source_signal:
        source_signal_parts = [
            part
            for part in (
                clean_text(latest_source_signal.get("ticker")),
                clean_text(latest_source_signal.get("source_type")),
                clean_text(latest_source_signal.get("title")),
            )
            if part
        ]
        if source_signal_parts:
            source_signal_text = " ".join(source_signal_parts)
            if clean_text(latest_source_signal.get("time")):
                source_signal_text += f" @ {clean_text(latest_source_signal.get('time'))}"
            lead_bits.append(f"Freshest attached source signal: {source_signal_text}")
    return "; ".join(lead_bits)


def render_ticker_quote_news_coverage_status(package: dict[str, Any]) -> str:
    coverage = safe_dict(package.get("ticker_quote_news_coverage"))
    if not coverage:
        return ""
    summary = safe_dict(coverage.get("summary"))
    rows = [row for row in safe_list(coverage.get("rows")) if isinstance(row, dict)]
    if not rows:
        return ""
    stock_count = clean_text(summary.get("stock_count")) or "0"
    quote_covered_count = clean_text(summary.get("quote_covered_count")) or "0"
    news_covered_count = clean_text(summary.get("news_covered_count")) or "0"
    news_missing_count = clean_text(summary.get("news_missing_count")) or "0"
    message_covered_count = clean_text(summary.get("message_covered_count")) or "0"
    message_missing_count = clean_text(summary.get("message_missing_count")) or "0"
    topic_covered_count = clean_text(summary.get("topic_covered_count")) or "0"
    topic_missing_count = clean_text(summary.get("topic_missing_count")) or "0"
    news_detail_covered_count = clean_text(summary.get("news_detail_covered_count")) or "0"
    news_detail_error_count = clean_text(summary.get("news_detail_error_count")) or "0"
    news_detail_stale_count = clean_text(summary.get("news_detail_stale_count")) or "0"
    news_detail_empty_count = clean_text(summary.get("news_detail_empty_count")) or "0"
    news_limited_count = clean_text(summary.get("news_limited_count")) or "0"
    source_signal_covered_count = clean_text(summary.get("source_signal_covered_count")) or "0"
    guarded_count = clean_text(summary.get("guarded_count")) or "0"
    information_completion_complete_count = clean_text(summary.get("information_completion_complete_count")) or "0"
    information_completion_partial_count = clean_text(summary.get("information_completion_partial_count")) or "0"
    information_completion_missing_count = clean_text(summary.get("information_completion_missing_count")) or "0"
    status_class = (
        "covered"
        if parse_float(summary.get("quote_missing_count")) == 0
        and parse_float(summary.get("news_missing_count")) == 0
        and parse_float(summary.get("news_limited_count")) == 0
        and parse_float(summary.get("news_detail_error_count")) == 0
        and parse_float(summary.get("news_detail_stale_count")) == 0
        and parse_float(summary.get("news_detail_empty_count")) == 0
        else "pending"
    )
    longbridge_source_summary = safe_dict(package.get("longbridge_plan_source_summary"))
    source_quality = clean_text(longbridge_source_summary.get("longbridge_plan_source_quality"))
    usable_detail_count = clean_text(longbridge_source_summary.get("news_detail_usable_count"))
    stale_detail_count = clean_text(longbridge_source_summary.get("news_detail_stale_count"))
    source_error_count = clean_text(longbridge_source_summary.get("source_error_count"))
    completion_ticker_count = clean_text(longbridge_source_summary.get("information_completion_ticker_count"))
    completion_complete_count = clean_text(longbridge_source_summary.get("information_completion_complete_count"))
    source_quality_block = ""
    if longbridge_source_summary:
        source_quality_class = "covered" if source_quality.lower() in {"", "ok", "covered"} else "pending"
        source_quality_bits = [
            f"quality {source_quality or 'unknown'}",
            f"usable details {usable_detail_count or '0'}",
            f"stale details {stale_detail_count or '0'}",
            f"source errors {source_error_count or '0'}",
        ]
        if completion_ticker_count or completion_complete_count:
            source_quality_bits.append(f"completion {completion_complete_count or '0'}/{completion_ticker_count or '0'}")
        source_quality_block = (
            '<div class="source-status-item ticker-coverage-quality">'
            '<div class="source-status-copy">'
            "<span>Longbridge source quality</span>"
            f'<span class="metric-label">{html.escape("; ".join(source_quality_bits))}</span>'
            "</div>"
            f'<span class="status-pill status-{html.escape(source_quality_class)}">{html.escape(source_quality or "unknown")}</span>'
            "</div>"
    )
    lead_text = build_ticker_quote_news_coverage_lead(package)
    lead_block = ""
    if lead_text:
        lead_block = (
            '<div class="source-status-item ticker-coverage-lead">'
            '<div class="source-status-copy">'
            "<span>Latest attached message</span>"
            f'<span class="metric-label">{html.escape(lead_text)}</span>'
            "</div>"
            "</div>"
        )
    source_links: list[str] = []
    quote_source = safe_dict(package.get("longbridge_artifact_sources")).get("quotes")
    if quote_source:
        source_links.append(render_file_link(quote_source, "longbridge-quotes.json"))
    news_source = safe_dict(package.get("longbridge_artifact_sources")).get("news")
    if news_source:
        source_links.append(render_file_link(news_source, "longbridge-news-headlines.json"))
    news_detail_source = safe_dict(package.get("longbridge_artifact_sources")).get("news_details")
    if news_detail_source:
        source_links.append(render_file_link(news_detail_source, "longbridge-news-details.json"))
    topic_source = safe_dict(package.get("longbridge_artifact_sources")).get("topics")
    if topic_source:
        source_links.append(render_file_link(topic_source, "longbridge-topics.json"))
    capital_flow_source = safe_dict(package.get("longbridge_artifact_sources")).get("capital_flows")
    if capital_flow_source:
        source_links.append(render_file_link(capital_flow_source, "longbridge-capital-flow.json"))
    filing_source = safe_dict(package.get("longbridge_artifact_sources")).get("filings")
    if filing_source:
        source_links.append(render_file_link(filing_source, "longbridge-filings.json"))
    completion_source = safe_dict(package.get("longbridge_artifact_sources")).get("information_completion_index")
    if completion_source:
        source_links.append(render_file_link(completion_source, "longbridge-information-completion-index.json"))
    if package.get("longbridge_news_headlines"):
        source_links.append(
            '<span class="muted-text">Attached Longbridge headlines are already embedded in the package.</span>'
        )
    artifact_block = f'<div class="artifact-links">{"".join(source_links)}</div>' if source_links else ""
    rendered_rows: list[str] = []
    for row in rows:
        ticker = clean_text(row.get("ticker")) or "unknown"
        name = clean_text(row.get("name")) or ticker
        bucket = clean_text(row.get("bucket")) or "Manual"
        quote_status = clean_text(row.get("quote_status")) or "missing"
        news_status = clean_text(row.get("news_status")) or "missing"
        news_detail_status = clean_text(row.get("news_detail_status")) or "missing"
        news_detail_count = clean_text(row.get("news_detail_count")) or "0"
        quote_summary = clean_text(row.get("quote_summary")) or "missing"
        quote_time = clean_text(row.get("quote_time"))
        latest_news_title = clean_text(row.get("latest_news_title"))
        latest_news_url = clean_text(row.get("latest_news_url"))
        latest_news_time = clean_text(row.get("latest_news_time"))
        topic_count = clean_text(row.get("topic_count")) or "0"
        topic_status = clean_text(row.get("topic_status")) or "missing"
        message_status = clean_text(row.get("message_status")) or "missing"
        message_count = clean_text(row.get("message_count")) or "0"
        latest_topic_title = clean_text(row.get("latest_topic_title"))
        latest_topic_url = clean_text(row.get("latest_topic_url"))
        latest_topic_time = clean_text(row.get("latest_topic_time"))
        latest_source_signal_title = clean_text(row.get("latest_source_signal_title"))
        latest_source_signal_url = clean_text(row.get("latest_source_signal_url"))
        latest_source_signal_time = clean_text(row.get("latest_source_signal_time"))
        latest_source_signal_type = clean_text(row.get("latest_source_signal_type"))
        source_signal_count = clean_text(row.get("source_signal_count")) or "0"
        actionability_tags = clean_string_list(row.get("actionability_tags"))
        limitations = clean_string_list(row.get("limitations"))
        message_source_types = clean_string_list(row.get("message_source_types"))
        information_completion_status = clean_text(row.get("information_completion_status")) or "missing"
        information_completion_sources = clean_string_list(row.get("information_completion_sources"))
        information_completion_fallback_sources = clean_string_list(
            row.get("information_completion_fallback_sources")
        )
        information_completion_news_detail_status = (
            clean_text(row.get("information_completion_news_detail_status")) or "missing"
        )
        information_completion_source_statuses = safe_dict(row.get("information_completion_source_statuses"))
        information_completion_latest_news_title = clean_text(row.get("information_completion_latest_news_title"))
        information_completion_latest_filing_title = clean_text(row.get("information_completion_latest_filing_title"))
        quote_detail = f"Quote: {html.escape(quote_summary)}"
        if quote_time:
            quote_detail += f" @ {html.escape(quote_time)}"
        if latest_news_url:
            latest_news_detail = (
                'Latest news: <a class="artifact-link" href="'
                f'{html.escape(latest_news_url)}" target="_blank" rel="noreferrer">'
                f"{html.escape(latest_news_title or 'news')}</a>"
            )
        elif latest_news_title:
            latest_news_detail = f"Latest news: {html.escape(latest_news_title)}"
        elif news_status == "limited":
            latest_news_detail = "Latest news: Longbridge news request was rate-limited during this run"
        else:
            latest_news_detail = "Latest news: none attached"
        if latest_news_time:
            latest_news_detail += f" @ {html.escape(latest_news_time)}"
        if latest_topic_url:
            latest_topic_detail = (
                'Latest topic: <a class="artifact-link" href="'
                f'{html.escape(latest_topic_url)}" target="_blank" rel="noreferrer">'
                f"{html.escape(latest_topic_title or 'topic')}</a>"
            )
        elif latest_topic_title:
            latest_topic_detail = f"Latest topic: {html.escape(latest_topic_title)}"
        else:
            latest_topic_detail = "Latest topic: none attached"
        if latest_topic_time:
            latest_topic_detail += f" @ {html.escape(latest_topic_time)}"
        if latest_source_signal_url:
            latest_source_signal_detail = (
                'Latest source signal: <a class="artifact-link" href="'
                f'{html.escape(latest_source_signal_url)}" target="_blank" rel="noreferrer">'
                f"{html.escape(latest_source_signal_title or 'source signal')}</a>"
            )
        elif latest_source_signal_title:
            latest_source_signal_detail = f"Latest source signal: {html.escape(latest_source_signal_title)}"
        else:
            latest_source_signal_detail = "Latest source signal: none attached"
        if latest_source_signal_type:
            latest_source_signal_detail += f" ({html.escape(latest_source_signal_type)})"
        if latest_source_signal_time:
            latest_source_signal_detail += f" @ {html.escape(latest_source_signal_time)}"
        news_detail = f"News detail: {html.escape(news_detail_status)} ({html.escape(news_detail_count)})"
        message_detail = f"Message: {html.escape(message_status)} ({html.escape(message_count)})"
        message_source_detail = f"Message sources: {html.escape(', '.join(message_source_types) or 'none')}"
        topic_detail = f"Topic: {html.escape(topic_status)} ({html.escape(topic_count)})"
        source_signal_detail = f"Source signals: {html.escape(source_signal_count)}"
        information_completion_detail = f"Information completion: {html.escape(information_completion_status)}"
        information_completion_source_detail = (
            "Completion sources: "
            f"{html.escape(', '.join(information_completion_sources) or 'none')}"
        )
        information_completion_fallback_detail = (
            "Fallback sources: "
            f"{html.escape(', '.join(information_completion_fallback_sources) or 'none')}"
        )
        information_completion_source_status_detail = (
            "Completion status: "
            f"{html.escape(_render_information_completion_source_statuses(information_completion_source_statuses))}"
        )
        information_completion_news_detail = (
            "Completion detail: "
            f"{html.escape(information_completion_news_detail_status)}"
        )
        if information_completion_latest_news_title:
            information_completion_news_detail += (
                f"; latest news {html.escape(information_completion_latest_news_title)}"
            )
        if information_completion_latest_filing_title:
            information_completion_news_detail += (
                f"; latest filing {html.escape(information_completion_latest_filing_title)}"
            )
        actionability_detail = f"Actionability: {html.escape(', '.join(actionability_tags) or 'none')}"
        limitation_detail = f"Limitations: {html.escape('; '.join(limitations) or 'none')}"
        information_completion_class = "covered" if information_completion_status == "complete" else "pending"
        rendered_rows.append(
            '<div class="source-status-item ticker-coverage-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(ticker)}</span>'
            f'<span class="overview-name">{html.escape(name)}</span>'
            f'<span class="metric-label">{html.escape(bucket)}</span>'
            "</div>"
            f'<span class="status-pill status-{"covered" if quote_status == "covered" else "blocked"}">quote {html.escape(quote_status)}</span>'
            f'<span class="status-pill status-{"covered" if news_status == "covered" else "pending" if news_status == "covered_with_limitations" else "blocked"}">news {html.escape(news_status)}</span>'
            f'<span class="status-pill status-{"covered" if message_status != "missing" else "blocked"}">message {html.escape(message_status)}</span>'
            f'<span class="status-pill status-{html.escape(information_completion_class)}">completion {html.escape(information_completion_status)}</span>'
            '<div class="ticker-coverage-detail">'
            f'<div class="metric-label">{quote_detail}</div>'
            f'<div class="metric-label">{latest_news_detail}</div>'
            f'<div class="metric-label">{latest_topic_detail}</div>'
            f'<div class="metric-label">{latest_source_signal_detail}</div>'
            f'<div class="metric-label">{message_detail}</div>'
            f'<div class="metric-label">{message_source_detail}</div>'
            f'<div class="metric-label">{topic_detail}</div>'
            f'<div class="metric-label">{source_signal_detail}</div>'
            f'<div class="metric-label">{news_detail}</div>'
            f'<div class="metric-label">{information_completion_detail}</div>'
            f'<div class="metric-label">{information_completion_source_detail}</div>'
            f'<div class="metric-label">{information_completion_fallback_detail}</div>'
            f'<div class="metric-label">{information_completion_source_status_detail}</div>'
            f'<div class="metric-label">{information_completion_news_detail}</div>'
            f'<div class="metric-label">{actionability_detail}</div>'
            f'<div class="metric-label">{limitation_detail}</div>'
            "</div>"
            "</div>"
        )
    return (
        '<section id="ticker-quote-news-coverage" class="ticker-quote-news-coverage-status" aria-label="Ticker quote and news coverage">'
        '<div class="section-head">'
        "<h2>Quote / News Coverage</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(stock_count)} names</span>'
        "</div>"
        '<div class="source-status-body">'
        "<p>Per-ticker quote freshness, attached news, and no-chase guardrails for the current pool.</p>"
        f"{lead_block}"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(quote_covered_count)}</span><span class="metric-label">Quotes covered</span></div>'
        f'<div><span class="metric-value">{html.escape(news_covered_count)}</span><span class="metric-label">News covered</span></div>'
        f'<div><span class="metric-value">{html.escape(news_missing_count)}</span><span class="metric-label">News missing</span></div>'
        f'<div><span class="metric-value">{html.escape(message_covered_count)}</span><span class="metric-label">Messages covered</span></div>'
        f'<div><span class="metric-value">{html.escape(message_missing_count)}</span><span class="metric-label">Messages missing</span></div>'
        f'<div><span class="metric-value">{html.escape(topic_covered_count)}</span><span class="metric-label">Topics covered</span></div>'
        f'<div><span class="metric-value">{html.escape(topic_missing_count)}</span><span class="metric-label">Topics missing</span></div>'
        f'<div><span class="metric-value">{html.escape(source_signal_covered_count)}</span><span class="metric-label">Source signals</span></div>'
        f'<div><span class="metric-value">{html.escape(news_detail_covered_count)}</span><span class="metric-label">News details</span></div>'
        f'<div><span class="metric-value">{html.escape(news_limited_count)}</span><span class="metric-label">News limited</span></div>'
        f'<div><span class="metric-value">{html.escape(news_detail_error_count)}</span><span class="metric-label">Detail errors</span></div>'
        f'<div><span class="metric-value">{html.escape(news_detail_stale_count)}</span><span class="metric-label">Detail stale</span></div>'
        f'<div><span class="metric-value">{html.escape(news_detail_empty_count)}</span><span class="metric-label">Detail empty</span></div>'
        f'<div><span class="metric-value">{html.escape(information_completion_complete_count)}</span><span class="metric-label">Completion complete</span></div>'
        f'<div><span class="metric-value">{html.escape(information_completion_partial_count)}</span><span class="metric-label">Completion partial</span></div>'
        f'<div><span class="metric-value">{html.escape(information_completion_missing_count)}</span><span class="metric-label">Completion missing</span></div>'
        f'<div><span class="metric-value">{html.escape(guarded_count)}</span><span class="metric-label">Guarded names</span></div>'
        "</div>"
        f"{artifact_block}"
        '<div class="source-status-list">'
        + source_quality_block
        + "".join(rendered_rows)
        + "</div>"
        "</div>"
        "</section>"
    )
