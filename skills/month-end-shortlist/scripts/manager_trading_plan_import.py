#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import (
    clean_string_list,
    clean_text,
    load_json,
    normalize_a_share_ticker,
    normalize_local_stock_pool,
    unique_strings,
)
from manager_html_primitives import parse_float, safe_dict, safe_list
from manager_market_snapshot import render_market_snapshot
from manager_pool_merge import normalize_workflow_display_ticker
from manager_ui_summary import PLAN_BUCKET_LABELS
TICKER_PATTERN = re.compile(r"`?((?:SH|SZ|BJ)?\d{6}(?:\.(?:SH|SS|SZ|BJ))?)`?", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)")

TEXT_PLAN_SIGNAL_MARKERS = (
    "交易计划",
    "观察动作",
    "失效",
    "止损",
    "支撑",
    "压力",
    "目标",
    "top picks",
    "near miss",
    "priority watch",
    "watch_action",
    "invalidation",
)

TEXT_BUCKET_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("diagnostic_scorecard", ("diagnostic", "\u8bca\u65ad", "\u6253\u5206", "scorecard")),
    ("near_miss_candidates", ("near miss", "\u672a\u786e\u8ba4", "\u5047\u7a81\u7834", "\u4e0d\u4e70", "\u4e0d\u5f00\u65b0\u4ed3", "near_miss")),
    ("top_picks", ("top picks", "top_pick", "\u5df2\u89e6\u53d1", "\u89e6\u53d1", "\u4e3b\u653b", "\u6838\u5fc3", "\u76f4\u63a5\u6267\u884c")),
    ("priority_watchlist", ("priority watch", "watchlist", "\u91cd\u70b9\u89c2\u5bdf", "\u53ea\u89c2\u5bdf", "\u5907\u9009")),
)


def text_looks_like_trading_plan(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized or not TICKER_PATTERN.search(normalized):
        return False
    lower = normalized.lower()
    return any(marker in lower or marker in normalized for marker in TEXT_PLAN_SIGNAL_MARKERS)


def detect_text_bucket(text: str, fallback: str = "priority_watchlist") -> str:
    normalized = clean_text(text)
    lower = normalized.lower()
    for bucket, markers in TEXT_BUCKET_MARKERS:
        if any(marker in lower or marker in normalized for marker in markers):
            return bucket
    return fallback


def parse_number_list(text: str) -> list[float]:
    values: list[float] = []
    for match in NUMBER_PATTERN.finditer(clean_text(text).replace(",", "")):
        try:
            number = float(match.group(1))
        except ValueError:
            continue
        if number not in values:
            values.append(number)
    return values


def extract_labeled_text(text: str, labels: tuple[str, ...]) -> str:
    source = clean_text(text)
    if not source:
        return ""
    lower_source = source.lower()
    best: tuple[int, str] | None = None
    for label in labels:
        label_text = clean_text(label)
        if not label_text:
            continue
        index = lower_source.find(label_text.lower())
        if index < 0:
            continue
        if best is None or index < best[0]:
            best = (index, label_text)
    if best is None:
        return ""
    index, label_text = best
    remainder = source[index + len(label_text) :]
    remainder = re.sub(r"^\s*(?:[:：]|锛[;；]?|銆)?\??\s*", "", remainder)
    value = re.split(r"(?:[。；;|\n]|锛[;；]?|銆)", remainder, maxsplit=1)[0]
    return clean_text(value)


def split_markdown_table_cells(line: str) -> list[str]:
    stripped = clean_text(line)
    if not (stripped.startswith("|") and stripped.count("|") >= 2):
        return []
    cells = [clean_text(cell).strip("` ") for cell in stripped.strip("|").split("|")]
    if cells and all(cell and set(cell) <= set("-: ") for cell in cells):
        return []
    return cells


def clean_markdown_text(text: str) -> str:
    cleaned = clean_text(text)
    cleaned = re.sub(r"^[#>\-\*\s]+", "", cleaned)
    cleaned = cleaned.replace("`", "")
    return clean_text(cleaned.strip("| "))


def extract_ticker_name(line: str, ticker_match: re.Match[str]) -> str:
    ticker_text = ticker_match.group(1)
    cells = split_markdown_table_cells(line)
    if cells:
        for index, cell in enumerate(cells):
            if ticker_text in cell:
                name = clean_markdown_text(cell.replace(ticker_text, ""))
                if name:
                    return name
                if index > 0:
                    return clean_markdown_text(cells[index - 1])
                break
    before = clean_markdown_text(line[: ticker_match.start()])
    if before:
        parts = re.split(r"[|:：，,；;]", before)
        name = clean_markdown_text(parts[-1])
        if name:
            return name
    after = clean_markdown_text(line[ticker_match.end() :])
    if after:
        name = clean_markdown_text(re.split(r"[:：，,；;|]", after)[0])
        if name and not NUMBER_PATTERN.search(name):
            return name
    return normalize_a_share_ticker(ticker_text)


def extract_trade_card_from_text(line: str, *, fallback_action: str = "") -> dict[str, Any]:
    action = extract_labeled_text(
        line,
        ("观察动作", "瑙傚療鍔ㄤ綔", "watch_action", "watch action", "动作", "鍔ㄤ綔", "Action", "操作", "鎿嶄綔", "执行", "鎵ц"),
    )
    invalidation = extract_labeled_text(line, ("失效", "澶辨晥", "止损", "姝㈡崯", "invalidation", "Invalidation"))
    if not action and fallback_action:
        action = re.split(r"(?:失效|止损|invalidation|Invalidation)\s*[:：]?", fallback_action, maxsplit=1)[0]
        action = clean_markdown_text(action)
    trade_card = {}
    if action:
        trade_card["watch_action"] = action
    if invalidation:
        trade_card["invalidation"] = invalidation
    return trade_card


def extract_price_paths_from_text(line: str) -> dict[str, Any]:
    label_map: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("base", ("base", "基准", "鍩哄噯")),
        ("bull", ("bull", "上行", "涓婅")),
        ("bear", ("bear", "下行", "涓嬭")),
        ("support", ("support", "支撑", "回踩", "鏀拺", "鍥炶俯")),
        ("resistance", ("resistance", "压力", "压制", "站上", "突破", "鍘嬪姏", "鍘嬪埗", "绔欎笂", "绐佺牬")),
        ("target", ("target", "目标", "鐩爣")),
    )
    price_paths: dict[str, Any] = {}
    for key, labels in label_map:
        labeled_text = extract_labeled_text(line, labels)
        values = parse_number_list(labeled_text)
        if values:
            price_paths[key] = values
    return price_paths


def trading_plan_text_to_result(text: str) -> dict[str, Any]:
    if not text_looks_like_trading_plan(text):
        return {}
    result: dict[str, Any] = {
        "top_picks": [],
        "priority_watchlist": [],
        "near_miss_candidates": [],
        "diagnostic_scorecard": [],
        "source_format": "trading_plan_text",
    }
    current_bucket = "priority_watchlist"
    for raw_line in text.splitlines():
        line = clean_text(raw_line)
        if not line:
            continue
        if line.startswith("#"):
            current_bucket = detect_text_bucket(line, current_bucket)
            continue
        ticker_matches = list(TICKER_PATTERN.finditer(line))
        if not ticker_matches:
            continue
        cells = split_markdown_table_cells(line)
        if cells and not any(TICKER_PATTERN.search(cell) for cell in cells):
            continue
        bucket = detect_text_bucket(line, current_bucket)
        fallback_action = clean_text(cells[-1]) if cells else ""
        trade_card = extract_trade_card_from_text(line, fallback_action=fallback_action)
        price_paths = extract_price_paths_from_text(line)
        for ticker_match in ticker_matches:
            ticker = clean_text(ticker_match.group(1)).upper()
            if not ticker:
                continue
            row = {
                "ticker": ticker,
                "name": extract_ticker_name(line, ticker_match),
                "trade_card": trade_card,
                "price_paths": price_paths,
                "raw_text": clean_markdown_text(line),
            }
            result[bucket].append({key: value for key, value in row.items() if value not in ("", None, [], {})})
    return result if any(result.get(bucket) for bucket in PLAN_BUCKET_LABELS) else {}


def price_path_summary(price_paths: dict[str, Any]) -> list[str]:
    summaries: list[str] = []
    for key in ("base", "bull", "bear", "support", "resistance", "target"):
        values = price_paths.get(key)
        if isinstance(values, list) and values:
            rendered = " / ".join(clean_text(item) for item in values if clean_text(item))
            if rendered:
                summaries.append(f"{key}: {rendered}")
        elif clean_text(values):
            summaries.append(f"{key}: {clean_text(values)}")
    return summaries


def normalize_market_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    ticker = normalize_a_share_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
    if not ticker:
        return {}
    snapshot = {
        "ticker": ticker,
        "source": clean_text(row.get("source")) or "longbridge",
        "last": clean_text(row.get("last")),
        "prev_close": clean_text(row.get("prev_close")),
        "high": clean_text(row.get("high")),
        "low": clean_text(row.get("low")),
        "open": clean_text(row.get("open")),
        "volume": row.get("volume"),
        "turnover": clean_text(row.get("turnover")),
        "status": clean_text(row.get("status")),
        "delay": clean_text(row.get("delay") or row.get("data_delay")),
        "quote_time": clean_text(row.get("quote_time") or row.get("timestamp") or row.get("time")),
    }
    return {key: value for key, value in snapshot.items() if value not in ("", None, [], {})}


def load_market_snapshots(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    payload = load_json(path)
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("quotes")
            or payload.get("items")
            or payload.get("data")
            or payload.get("market_snapshots")
            or []
        )
        if isinstance(rows, dict):
            rows = list(rows.values())
    else:
        rows = []
    snapshots: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        snapshot = normalize_market_snapshot(row)
        ticker = clean_text(snapshot.get("ticker"))
        if ticker:
            snapshots[ticker] = snapshot
    return snapshots


LONGBRIDGE_QUOTE_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-quotes.json",
    "longbridge_quotes.json",
    "longbridge-quote.json",
    "longbridge_quote.json",
)

LONGBRIDGE_NEWS_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-news-headlines.json",
    "longbridge_news_headlines.json",
    "longbridge-news.json",
    "longbridge_news.json",
)

LONGBRIDGE_NEWS_DETAIL_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-news-details.json",
    "longbridge_news_details.json",
    "longbridge-news-detail.json",
    "longbridge_news_detail.json",
)

LONGBRIDGE_MARKET_STATUS_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-market-status.json",
    "longbridge_market_status.json",
)

LONGBRIDGE_MARKET_TEMP_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-market-temp.json",
    "longbridge_market_temp.json",
    "longbridge-market-temperature.json",
    "longbridge_market_temperature.json",
)

LONGBRIDGE_CAPITAL_FLOW_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-capital-flow.json",
    "longbridge_capital_flow.json",
    "longbridge-capital-flows.json",
    "longbridge_capital_flows.json",
)

LONGBRIDGE_TOPIC_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-topics.json",
    "longbridge_topics.json",
    "longbridge-topic.json",
    "longbridge_topic.json",
)

LONGBRIDGE_FILING_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-filings.json",
    "longbridge_filings.json",
    "longbridge-filing.json",
    "longbridge_filing.json",
)

LONGBRIDGE_SHAREHOLDER_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-shareholders.json",
    "longbridge_shareholders.json",
    "longbridge-shareholder.json",
    "longbridge_shareholder.json",
)

LONGBRIDGE_FUND_HOLDER_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-fund-holders.json",
    "longbridge_fund_holders.json",
    "longbridge-fund-holder.json",
    "longbridge_fund_holder.json",
)

LONGBRIDGE_INSIDER_TRADE_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-insider-trades.json",
    "longbridge_insider_trades.json",
    "longbridge-insider-trade.json",
    "longbridge_insider_trade.json",
)

LONGBRIDGE_SHORT_POSITION_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-short-positions.json",
    "longbridge_short_positions.json",
    "longbridge-short-position.json",
    "longbridge_short_position.json",
)

LONGBRIDGE_FINANCIAL_REPORT_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-financial-report.json",
    "longbridge_financial_report.json",
    "longbridge-financial-reports.json",
    "longbridge_financial_reports.json",
)

LONGBRIDGE_OPERATING_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-operating.json",
    "longbridge_operating.json",
    "longbridge-operating-reviews.json",
    "longbridge_operating_reviews.json",
)

LONGBRIDGE_INDUSTRY_VALUATION_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-industry-valuation.json",
    "longbridge_industry_valuation.json",
    "longbridge-industry-valuations.json",
    "longbridge_industry_valuations.json",
)

LONGBRIDGE_PLAN_SOURCE_RUN_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-plan-source-run.json",
    "longbridge_plan_source_run.json",
)

LONGBRIDGE_VALUATION_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-valuation.json",
    "longbridge_valuation.json",
    "longbridge-valuations.json",
    "longbridge_valuations.json",
)

LONGBRIDGE_INSTITUTION_RATING_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-institution-rating.json",
    "longbridge_institution_rating.json",
    "longbridge-institution-ratings.json",
    "longbridge_institution_ratings.json",
    "longbridge-institutional-rating.json",
    "longbridge_institutional_rating.json",
    "longbridge-institutional-ratings.json",
    "longbridge_institutional_ratings.json",
)

LONGBRIDGE_FORECAST_EPS_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-forecast-eps.json",
    "longbridge_forecast_eps.json",
    "longbridge-eps-forecast.json",
    "longbridge_eps_forecast.json",
    "longbridge-eps-forecasts.json",
    "longbridge_eps_forecasts.json",
)

LONGBRIDGE_CONSENSUS_FILENAME_CANDIDATES: tuple[str, ...] = (
    "longbridge-consensus.json",
    "longbridge_consensus.json",
    "longbridge-consensus-estimates.json",
    "longbridge_consensus_estimates.json",
)


def _normalize_longbridge_news_row(row: dict[str, Any]) -> dict[str, Any]:
    ticker = clean_text(row.get("ticker") or row.get("symbol") or row.get("code"))
    title = clean_text(row.get("title") or row.get("headline") or row.get("name"))
    url = clean_text(row.get("url") or row.get("link"))
    published_at = row.get("published_at") or row.get("publish_time") or row.get("time")
    news_id = clean_text(row.get("id") or row.get("news_id") or row.get("uuid"))
    normalized = {
        "ticker": ticker,
        "title": title,
        "url": url,
        "published_at": published_at,
    }
    if news_id:
        normalized["id"] = news_id
    return {key: value for key, value in normalized.items() if value not in (None, "")}


def load_longbridge_news_headlines(path: str | Path | None = None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        payload = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("headlines")
            or payload.get("news")
            or payload.get("items")
            or payload.get("data")
            or payload.get("longbridge_news_headlines")
            or []
        )
    else:
        rows = []
    headlines: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_longbridge_news_row(row)
        if normalized.get("title") or normalized.get("url"):
            headlines.append(normalized)
    return headlines


def _normalize_longbridge_news_detail_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_longbridge_news_row(row)
    content = clean_text(
        row.get("content_markdown")
        or row.get("markdown")
        or row.get("content")
        or row.get("body")
        or row.get("text")
        or row.get("summary")
    )
    if content:
        normalized["content_markdown"] = content
        normalized["content_length"] = len(content)
    lang = clean_text(row.get("lang") or row.get("language"))
    if lang:
        normalized["lang"] = lang
    source = clean_text(row.get("source") or row.get("provider"))
    if source:
        normalized["source"] = source
    fetch_status = clean_text(row.get("fetch_status") or row.get("status"))
    if fetch_status:
        normalized["fetch_status"] = fetch_status
    fetch_error = clean_text(row.get("fetch_error") or row.get("error"))
    if fetch_error:
        normalized["fetch_error"] = fetch_error
    return normalized


def load_longbridge_news_details(path: str | Path | None = None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        payload = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("details")
            or payload.get("news_details")
            or payload.get("items")
            or payload.get("data")
            or payload.get("longbridge_news_details")
            or []
        )
        if not rows and (payload.get("content") or payload.get("content_markdown") or payload.get("markdown")):
            rows = [payload]
    else:
        rows = []
    details: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_longbridge_news_detail_row(row)
        if normalized.get("id") or normalized.get("title") or normalized.get("content_markdown"):
            details.append(normalized)
    return details


def attach_tickers_to_longbridge_news_details(
    details: list[dict[str, Any]],
    headlines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    headlines_by_id = {
        clean_text(row.get("id")): row
        for row in headlines
        if isinstance(row, dict) and clean_text(row.get("id"))
    }
    enriched: list[dict[str, Any]] = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        row = dict(detail)
        headline = headlines_by_id.get(clean_text(row.get("id"))) or {}
        if headline:
            row.setdefault("ticker", clean_text(headline.get("ticker")))
            row.setdefault("title", clean_text(headline.get("title")))
            row.setdefault("url", clean_text(headline.get("url")))
            row.setdefault("published_at", headline.get("published_at"))
        enriched.append({key: value for key, value in row.items() if value not in ("", None, [], {})})
    return enriched


def load_longbridge_market_status(path: str | Path | None = None) -> dict[str, str]:
    if not path:
        return {}
    try:
        payload = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    try:
        from institutional_evidence_bundle import normalize_longbridge_market_status_payload
    except ModuleNotFoundError:
        return {}
    return normalize_longbridge_market_status_payload(payload)


def load_longbridge_market_temperature(path: str | Path | None = None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"rows": payload}
    return {}


def load_longbridge_plan_source_run(path: str | Path | None = None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    schema_text = clean_text(payload.get("schema_version"))
    if schema_text and schema_text != "longbridge-plan-source-run/v1":
        return {}
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return {}
    return payload


def discover_longbridge_artifacts(search_roots: list[str | Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    seen: set[str] = set()
    for root_value in search_roots or []:
        root = Path(root_value).expanduser()
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if str(resolved) in seen or not resolved.is_dir():
            seen.add(str(resolved))
            continue
        seen.add(str(resolved))
        for kind, candidates in (
            ("quotes", LONGBRIDGE_QUOTE_FILENAME_CANDIDATES),
            ("news", LONGBRIDGE_NEWS_FILENAME_CANDIDATES),
            ("news_details", LONGBRIDGE_NEWS_DETAIL_FILENAME_CANDIDATES),
            ("market_status", LONGBRIDGE_MARKET_STATUS_FILENAME_CANDIDATES),
            ("market_temperature", LONGBRIDGE_MARKET_TEMP_FILENAME_CANDIDATES),
            ("capital_flows", LONGBRIDGE_CAPITAL_FLOW_FILENAME_CANDIDATES),
            ("topics", LONGBRIDGE_TOPIC_FILENAME_CANDIDATES),
            ("filings", LONGBRIDGE_FILING_FILENAME_CANDIDATES),
            ("shareholders", LONGBRIDGE_SHAREHOLDER_FILENAME_CANDIDATES),
            ("fund_holders", LONGBRIDGE_FUND_HOLDER_FILENAME_CANDIDATES),
            ("insider_trades", LONGBRIDGE_INSIDER_TRADE_FILENAME_CANDIDATES),
            ("short_positions", LONGBRIDGE_SHORT_POSITION_FILENAME_CANDIDATES),
            ("financial_reports", LONGBRIDGE_FINANCIAL_REPORT_FILENAME_CANDIDATES),
            ("operating_reviews", LONGBRIDGE_OPERATING_FILENAME_CANDIDATES),
            ("industry_valuation", LONGBRIDGE_INDUSTRY_VALUATION_FILENAME_CANDIDATES),
            ("plan_source_run", LONGBRIDGE_PLAN_SOURCE_RUN_FILENAME_CANDIDATES),
            ("valuation", LONGBRIDGE_VALUATION_FILENAME_CANDIDATES),
            ("institution_rating", LONGBRIDGE_INSTITUTION_RATING_FILENAME_CANDIDATES),
            ("forecast_eps", LONGBRIDGE_FORECAST_EPS_FILENAME_CANDIDATES),
            ("consensus", LONGBRIDGE_CONSENSUS_FILENAME_CANDIDATES),
        ):
            if kind in found:
                continue
            for candidate in candidates:
                path = resolved / candidate
                if path.exists():
                    found[kind] = path
                    break
    return found


def merge_market_snapshots_into_trading_plan_result(
    trading_plan_result: dict[str, Any],
    market_snapshots: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not trading_plan_result or not market_snapshots:
        return trading_plan_result
    enriched = dict(trading_plan_result)
    for bucket in ("top_picks", "directly_actionable", "priority_watchlist", "near_miss_candidates", "diagnostic_scorecard"):
        rows = trading_plan_result.get(bucket)
        if not isinstance(rows, list):
            continue
        enriched_rows = []
        for row in rows:
            if not isinstance(row, dict):
                enriched_rows.append(row)
                continue
            ticker = normalize_a_share_ticker(row.get("ticker") or row.get("code") or row.get("symbol"))
            snapshot = market_snapshots.get(ticker)
            if snapshot:
                merged_row = dict(row)
                merged_row["market_snapshot"] = snapshot
                enriched_rows.append(merged_row)
            else:
                enriched_rows.append(row)
        enriched[bucket] = enriched_rows
    return enriched


def _display_market_snapshot(snapshot: dict[str, Any], *, fallback_ticker: str = "") -> dict[str, Any]:
    if not isinstance(snapshot, dict) or not snapshot:
        return {}
    rendered = dict(snapshot)
    display_ticker = normalize_workflow_display_ticker(
        rendered.get("ticker") or rendered.get("symbol") or rendered.get("code") or fallback_ticker
    )
    if display_ticker:
        rendered["ticker"] = display_ticker
    return rendered


def merge_market_snapshots_into_local_stock_pool(
    raw_pool: dict[str, Any],
    market_snapshots: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(raw_pool, dict) or not raw_pool or not market_snapshots:
        return raw_pool
    snapshots_by_ticker: dict[str, dict[str, Any]] = {}
    for key, snapshot in market_snapshots.items():
        if not isinstance(snapshot, dict):
            continue
        display_ticker = normalize_workflow_display_ticker(
            snapshot.get("ticker") or snapshot.get("symbol") or snapshot.get("code") or key
        )
        if display_ticker:
            snapshots_by_ticker[display_ticker] = _display_market_snapshot(snapshot, fallback_ticker=display_ticker)

    if not snapshots_by_ticker:
        return raw_pool

    refreshed_pool = dict(raw_pool)
    refreshed_stocks: list[Any] = []
    for stock in safe_list(raw_pool.get("stocks")):
        if not isinstance(stock, dict):
            refreshed_stocks.append(stock)
            continue
        refreshed_stock = dict(stock)
        ticker = normalize_workflow_display_ticker(stock.get("ticker") or stock.get("code") or stock.get("symbol"))
        snapshot = snapshots_by_ticker.get(ticker)
        if snapshot:
            refreshed_stock["market_snapshot"] = snapshot
            if isinstance(stock.get("plan_snapshot"), dict):
                plan_snapshot = dict(stock["plan_snapshot"])
                plan_snapshot["market_snapshot"] = snapshot
                refreshed_stock["plan_snapshot"] = plan_snapshot
        refreshed_stocks.append(refreshed_stock)
    refreshed_pool["stocks"] = refreshed_stocks
    return refreshed_pool


def plan_notes(row: dict[str, Any]) -> str:
    parts: list[str] = []
    market_summary = render_market_snapshot(safe_dict(row.get("market_snapshot") or row.get("quote_snapshot")))
    if market_summary:
        parts.append(market_summary)
    trade_card = safe_dict(row.get("trade_card"))
    action = clean_text(trade_card.get("watch_action") or row.get("watch_action"))
    invalidation = clean_text(trade_card.get("invalidation") or row.get("invalidation"))
    if action:
        parts.append(f"Action: {action}")
    if invalidation:
        parts.append(f"Invalidation: {invalidation}")
    parts.extend(price_path_summary(safe_dict(row.get("price_paths"))))
    if clean_text(row.get("keep_threshold_gap")):
        parts.append(f"Keep gap: {clean_text(row.get('keep_threshold_gap'))}")
    if clean_text(row.get("execution_state")):
        parts.append(f"Execution: {clean_text(row.get('execution_state'))}")
    return " | ".join(parts)


def plan_strategy_tags(row: dict[str, Any]) -> list[str]:
    trade_card = safe_dict(row.get("trade_card"))
    tags = []
    action = clean_text(trade_card.get("watch_action") or row.get("watch_action"))
    invalidation = clean_text(trade_card.get("invalidation") or row.get("invalidation"))
    if action:
        tags.append(f"watch:{action}")
    if invalidation:
        tags.append(f"invalid:{invalidation}")
    tags.extend(f"setup:{item}" for item in clean_string_list(row.get("setup_reasons")))
    return unique_strings(tags)


def plan_tags(row: dict[str, Any]) -> list[str]:
    tags = []
    tags.extend(clean_string_list(row.get("tier_tags")))
    tags.extend(clean_string_list(row.get("theme_tags")))
    for key in ("chain_name", "trading_profile_bucket", "discovery_bucket", "execution_state"):
        text = clean_text(row.get(key))
        if text:
            tags.append(text)
    return unique_strings(tags)


def first_price_value(price_paths: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        values = price_paths.get(key)
        if isinstance(values, list):
            for item in values:
                parsed = parse_float(item)
                if parsed is not None:
                    return parsed
            continue
        parsed = parse_float(values)
        if parsed is not None:
            return parsed
    return None


def build_trigger_distance(price_paths: dict[str, Any]) -> dict[str, Any]:
    reference_price = first_price_value(price_paths, ("base", "close", "last_close"))
    trigger_price = first_price_value(price_paths, ("resistance", "target", "bull"))
    if reference_price is None or trigger_price is None or reference_price <= 0 or trigger_price <= 0:
        return {}
    pct = ((trigger_price - reference_price) / reference_price) * 100
    if reference_price >= trigger_price:
        label = "Triggered"
        class_name = "distance-triggered"
    elif pct <= 3:
        label = "Near trigger"
        class_name = "distance-near"
    else:
        label = "Away from trigger"
        class_name = "distance-far"
    return {
        "metric": "trigger_distance",
        "reference_price": round(reference_price, 3),
        "trigger_price": round(trigger_price, 3),
        "pct": round(pct, 2),
        "label": label,
        "class_name": class_name,
        "display": f"{label} {pct:+.2f}%",
    }


def derive_monitor_price_paths_from_market_snapshot(market_snapshot: dict[str, Any]) -> dict[str, list[float]]:
    if not isinstance(market_snapshot, dict) or not market_snapshot:
        return {}
    base = parse_float(market_snapshot.get("last") or market_snapshot.get("last_done") or market_snapshot.get("close"))
    high = parse_float(market_snapshot.get("high"))
    low = parse_float(market_snapshot.get("low"))
    price_paths: dict[str, list[float]] = {}
    if base is not None and base > 0:
        price_paths["base"] = [round(base, 3)]
    if high is not None and high > 0:
        price_paths["resistance"] = [round(high, 3)]
    if low is not None and low > 0:
        price_paths["support"] = [round(low, 3)]
    return price_paths


def build_monitor_trade_card_from_price_paths(price_paths: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(price_paths, dict) or not price_paths:
        return {}
    trade_card = {"watch_action": "wait for confirmation"}
    support = first_price_value(price_paths, ("support",))
    if support is not None:
        trade_card["invalidation"] = f"break below {support:g}"
    return trade_card


def _supplement_trading_plan_row(
    row: dict[str, Any],
    supplemental_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(row)
    supplemental_sources = [safe_dict(row.get("plan_snapshot"))]
    if isinstance(supplemental_row, dict) and supplemental_row:
        supplemental_sources.append(safe_dict(supplemental_row))
        supplemental_sources.append(safe_dict(supplemental_row.get("plan_snapshot")))
    for source in supplemental_sources:
        if not source:
            continue
        for key in ("market_snapshot", "quote_snapshot", "price_paths", "trade_card", "levels"):
            if merged.get(key) not in (None, "", [], {}):
                continue
            value = source.get(key)
            if value not in (None, "", [], {}):
                merged[key] = value
    return merged


def enrich_plan_snapshot_for_monitoring(plan_snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan_snapshot, dict) or not plan_snapshot:
        return {}
    snapshot = dict(plan_snapshot)
    price_paths = safe_dict(snapshot.get("price_paths"))
    market_snapshot = safe_dict(snapshot.get("market_snapshot") or snapshot.get("quote_snapshot"))
    if not price_paths:
        price_paths = derive_monitor_price_paths_from_market_snapshot(market_snapshot)
        if price_paths:
            snapshot["price_paths"] = price_paths
    if price_paths and not safe_dict(snapshot.get("trade_card")):
        trade_card = build_monitor_trade_card_from_price_paths(price_paths)
        if trade_card:
            snapshot["trade_card"] = trade_card
    trigger_distance = build_trigger_distance(price_paths)
    if trigger_distance:
        snapshot["trigger_distance"] = trigger_distance
    return {key: value for key, value in snapshot.items() if value not in ("", None, [], {})}


def _nested_local_stock_pool_rows_by_ticker(trading_plan_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}

    def ingest_pool(pool: dict[str, Any]) -> None:
        if not isinstance(pool, dict) or not pool:
            return
        for stock in safe_list(pool.get("stocks")):
            if not isinstance(stock, dict):
                continue
            ticker = normalize_workflow_display_ticker(stock.get("ticker") or stock.get("code") or stock.get("symbol"))
            if ticker and ticker not in lookup:
                lookup[ticker] = stock

    ingest_pool(safe_dict(trading_plan_result.get("local_stock_pool")))
    ingest_pool(safe_dict(safe_dict(trading_plan_result.get("request")).get("local_stock_pool")))
    track_results = trading_plan_result.get("track_results")
    if isinstance(track_results, dict):
        for track_result in track_results.values():
            if not isinstance(track_result, dict):
                continue
            ingest_pool(safe_dict(safe_dict(track_result.get("request")).get("local_stock_pool")))
    return lookup


def enrich_local_stock_pool_for_monitoring(local_stock_pool: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(local_stock_pool, dict) or not local_stock_pool:
        return {}
    stocks = local_stock_pool.get("stocks")
    if not isinstance(stocks, list) or not stocks:
        return local_stock_pool
    enriched_stocks: list[dict[str, Any]] = []
    changed = False
    for stock in stocks:
        if not isinstance(stock, dict):
            enriched_stocks.append(stock)
            continue
        plan_snapshot = safe_dict(stock.get("plan_snapshot"))
        if plan_snapshot:
            enriched_plan_snapshot = enrich_plan_snapshot_for_monitoring(plan_snapshot)
            if enriched_plan_snapshot != plan_snapshot:
                stock = dict(stock)
                stock["plan_snapshot"] = enriched_plan_snapshot
                changed = True
        enriched_stocks.append(stock)
    if not changed:
        return local_stock_pool
    enriched_pool = dict(local_stock_pool)
    enriched_pool["stocks"] = enriched_stocks
    return enriched_pool


def build_plan_snapshot(
    row: dict[str, Any],
    *,
    bucket: str,
    supplemental_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_row = _supplement_trading_plan_row(row, supplemental_row)
    market_snapshot = safe_dict(source_row.get("market_snapshot") or source_row.get("quote_snapshot"))
    snapshot = {
        "bucket": bucket,
        "ticker": normalize_workflow_display_ticker(source_row.get("ticker") or source_row.get("code") or source_row.get("symbol")),
        "name": clean_text(source_row.get("name")),
        "score": source_row.get("score"),
        "keep_threshold_gap": source_row.get("keep_threshold_gap"),
        "chain_name": clean_text(source_row.get("chain_name")),
        "execution_state": clean_text(source_row.get("execution_state")),
        "market_snapshot": market_snapshot,
        "tier_tags": clean_string_list(source_row.get("tier_tags")),
        "theme_tags": clean_string_list(source_row.get("theme_tags")),
        "setup_reasons": clean_string_list(source_row.get("setup_reasons")),
        "raw_text": clean_text(source_row.get("raw_text")),
    }
    for key in ("quote_snapshot", "price_paths", "trade_card", "levels"):
        value = source_row.get(key)
        if value not in (None, "", [], {}):
            snapshot[key] = safe_dict(value) if isinstance(value, dict) else value
    return enrich_plan_snapshot_for_monitoring(snapshot)


def extract_trading_plan_rows(trading_plan_result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for bucket in ("top_picks", "directly_actionable", "priority_watchlist", "near_miss_candidates", "diagnostic_scorecard"):
        for item in trading_plan_result.get(bucket, []) if isinstance(trading_plan_result.get(bucket), list) else []:
            if isinstance(item, dict) and clean_text(item.get("ticker") or item.get("code") or item.get("symbol")):
                rows.append((bucket, item))
    return rows


def build_local_stock_pool_from_trading_plan_result(
    trading_plan_result: dict[str, Any],
    *,
    pool_name: str = "trading-plan-import",
) -> dict[str, Any]:
    stocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    supplementary_rows = _nested_local_stock_pool_rows_by_ticker(trading_plan_result)
    for bucket, row in extract_trading_plan_rows(trading_plan_result):
        ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("code") or row.get("symbol"))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        bucket_label = PLAN_BUCKET_LABELS.get(bucket, bucket)
        name = clean_text(row.get("name")) or ticker
        supplemental_row = supplementary_rows.get(ticker, {})
        stocks.append(
            {
                "ticker": ticker,
                "name": name,
                "groups": unique_strings(["Trading Plan", bucket_label]),
                "tags": plan_tags(row),
                "strategy_tags": plan_strategy_tags(row),
                "notes": plan_notes(row),
                "plan_snapshot": build_plan_snapshot(row, bucket=bucket, supplemental_row=supplemental_row),
                "source": "trading_plan_import",
            }
        )
    if not stocks:
        return {}
    return {
        "schema_version": "local_stock_pool/v1",
        "name": clean_text(pool_name) or "trading-plan-import",
        "stocks": stocks,
        "groups": [],
        "strategy_rules": [],
        "ui_contract": {
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
        },
    }


def build_local_stock_pool_from_trading_plan_text(
    text: str,
    *,
    pool_name: str = "trading-plan-text-import",
) -> dict[str, Any]:
    return build_local_stock_pool_from_trading_plan_result(
        trading_plan_text_to_result(text),
        pool_name=pool_name,
    )


def _longbridge_screen_name_index(screen_result: dict[str, Any]) -> dict[str, str]:
    name_index: dict[str, str] = {}
    ranked_candidates = screen_result.get("ranked_candidates")
    if not isinstance(ranked_candidates, list):
        return name_index
    for ranked_candidate in ranked_candidates:
        if not isinstance(ranked_candidate, dict):
            continue
        symbol = normalize_workflow_display_ticker(ranked_candidate.get("symbol") or ranked_candidate.get("ticker"))
        if not symbol:
            continue
        theme_chain_analysis = safe_dict(ranked_candidate.get("theme_chain_analysis"))
        company = safe_dict(theme_chain_analysis.get("company"))
        company_name = clean_text(company.get("name"))
        if company_name and company_name != symbol:
            name_index[symbol] = company_name
    return name_index


def _longbridge_name_is_symbol_like(name: str, symbol: str) -> bool:
    cleaned = clean_text(name)
    if not cleaned:
        return False
    if cleaned == symbol:
        return True
    return normalize_workflow_display_ticker(cleaned) == symbol


def _longbridge_candidate_name(candidate: dict[str, Any], symbol: str, *, name_index: dict[str, str] | None = None) -> str:
    indexed_name = clean_text((name_index or {}).get(symbol))
    if indexed_name and indexed_name != symbol:
        return indexed_name
    name = clean_text(candidate.get("name"))
    if name and not _longbridge_name_is_symbol_like(name, symbol):
        return name
    preflight = safe_dict(candidate.get("execution_preflight"))
    static_rows = preflight.get("static")
    if isinstance(static_rows, list):
        for row in static_rows:
            if not isinstance(row, dict):
                continue
            static_name = clean_text(row.get("name"))
            if static_name and static_name != symbol:
                return static_name
    return name or symbol


def _longbridge_candidate_bucket(candidate: dict[str, Any]) -> str:
    rank = parse_float(candidate.get("rank"))
    if rank is None:
        return "priority_watchlist"
    if rank <= 3:
        return "top_picks"
    if rank <= 9:
        return "priority_watchlist"
    return "near_miss_candidates"


def _longbridge_candidate_score(candidate: dict[str, Any]) -> float | None:
    scores = safe_dict(candidate.get("scores"))
    for key in ("workbench_score", "screen_score", "technical_score"):
        value = parse_float(scores.get(key))
        if value is not None:
            return value
    return None


def _longbridge_candidate_price_paths(candidate: dict[str, Any]) -> dict[str, list[float]]:
    levels = safe_dict(candidate.get("levels"))
    price_paths: dict[str, list[float]] = {}
    base = parse_float(levels.get("last_close"))
    if base is not None:
        price_paths["base"] = [base]
    support = [value for value in (parse_float(levels.get("stop_loss")), parse_float(levels.get("abandon_below"))) if value is not None]
    if support:
        price_paths["support"] = support
    resistance = parse_float(levels.get("trigger_price"))
    if resistance is not None:
        price_paths["resistance"] = [resistance]
    return price_paths


def _longbridge_candidate_trade_card(candidate: dict[str, Any], *, bucket: str) -> dict[str, str]:
    rank = clean_text(candidate.get("rank")) or "?"
    signal = clean_text(candidate.get("signal")) or "screen_signal"
    levels = safe_dict(candidate.get("levels"))
    trigger = clean_text(levels.get("trigger_price"))
    stop = clean_text(levels.get("stop_loss"))
    abandon = clean_text(levels.get("abandon_below"))
    if bucket == "top_picks":
        action = f"标准链路排名第{rank}，信号 {signal}；只在触发价 {trigger} 以上且量能/资金/主题确认后试仓，未触发不提前买。"
    elif bucket == "priority_watchlist":
        action = f"标准链路排名第{rank}，保持重点观察；等待 {trigger} 触发并确认，当前不追。"
    else:
        action = f"标准链路排名第{rank}，当前仅保留观察；除非重新触发 {trigger} 且确认，否则不纳入主动买点。"
    invalidation_parts = []
    if stop:
        invalidation_parts.append(f"止损 {stop}")
    if abandon:
        invalidation_parts.append(f"放弃线 {abandon}")
    invalidation = " 或 ".join(invalidation_parts)
    return {
        "watch_action": action,
        "invalidation": f"跌破{invalidation}，该计划失效。" if invalidation else "",
    }


def _longbridge_candidate_setup_reasons(candidate: dict[str, Any]) -> list[str]:
    evidence = safe_dict(candidate.get("qualitative_evidence"))
    reasons = []
    for key in ("catalyst_summary", "research_or_topic_quality", "filing_event_summary"):
        text = clean_text(evidence.get(key))
        if text:
            reasons.append(text)
    return reasons[:3]


def _longbridge_plan_report_to_bucketed_result(
    report: dict[str, Any],
    *,
    name_index: dict[str, str] | None = None,
) -> dict[str, Any]:
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        return {}
    result: dict[str, Any] = {
        "source_format": "longbridge_trading_plan",
        "target_date": clean_text(report.get("plan_date")),
        "top_picks": [],
        "priority_watchlist": [],
        "near_miss_candidates": [],
    }
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        symbol = normalize_workflow_display_ticker(candidate.get("ticker") or candidate.get("symbol"))
        if not symbol:
            continue
        bucket = _longbridge_candidate_bucket(candidate)
        signal = clean_text(candidate.get("signal"))
        tracking_bucket = clean_text(candidate.get("tracking_bucket"))
        row = {
            "ticker": symbol,
            "name": _longbridge_candidate_name(candidate, symbol, name_index=name_index),
            "score": _longbridge_candidate_score(candidate),
            "chain_name": signal,
            "execution_state": signal,
            "price_paths": _longbridge_candidate_price_paths(candidate),
            "trade_card": _longbridge_candidate_trade_card(candidate, bucket=bucket),
            "tier_tags": unique_strings(["longbridge_full_runner", signal, tracking_bucket]),
            "setup_reasons": _longbridge_candidate_setup_reasons(candidate),
            "risk_flags": clean_string_list(candidate.get("risk_flags")),
        }
        result[bucket].append({key: value for key, value in row.items() if value not in ("", None, [], {})})
    return result if any(result.get(bucket) for bucket in PLAN_BUCKET_LABELS) else {}


def _longbridge_adaptive_wrapper_to_bucketed_result(payload: dict[str, Any]) -> dict[str, Any]:
    outputs = safe_dict(payload.get("outputs"))
    report = safe_dict(outputs.get("trading_plan_report"))
    if not report:
        return {}
    name_index = _longbridge_screen_name_index(safe_dict(outputs.get("screen_result")))
    extracted_plan = _longbridge_plan_report_to_bucketed_result(report, name_index=name_index)
    if extracted_plan:
        return extracted_plan
    return {}


def _extract_trading_plan_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if any(key in payload for key in ("top_picks", "directly_actionable", "priority_watchlist", "near_miss_candidates", "diagnostic_scorecard")):
        return payload
    if clean_text(payload.get("schema_version")) == "longbridge_adaptive_runner/v1":
        extracted_plan = _longbridge_adaptive_wrapper_to_bucketed_result(payload)
        if extracted_plan:
            return extracted_plan
    if clean_text(payload.get("schema_version")) == "longbridge_trading_plan/v1" or isinstance(payload.get("candidates"), list):
        extracted_plan = _longbridge_plan_report_to_bucketed_result(payload)
        if extracted_plan:
            return extracted_plan
    outputs = payload.get("outputs")
    if isinstance(outputs, dict) and "trading_plan_report" in outputs:
        extracted_plan = _longbridge_adaptive_wrapper_to_bucketed_result(payload)
        if extracted_plan:
            return extracted_plan
    for key in ("trading_plan_result", "trading_plan_report", "month_end_result", "outputs", "result", "payload"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            extracted = _extract_trading_plan_payload(nested)
            if extracted:
                return extracted
    return {}


def _load_trading_plan_result_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown", ".txt"):
        return trading_plan_text_to_result(path.read_text(encoding="utf-8-sig"))
    payload = load_json(path)
    return _extract_trading_plan_payload(payload)


def load_trading_plan_result(path: str | Path | None = None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser()
    if resolved.is_dir():
        candidates = sorted(
            (
                item
                for item in resolved.rglob("*")
                if item.is_file() and item.suffix.lower() in (".json", ".md", ".markdown", ".txt")
            ),
            key=lambda item: (item.stat().st_mtime, item.name.lower()),
            reverse=True,
        )
        for candidate in candidates:
            try:
                extracted = _load_trading_plan_result_file(candidate)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if extracted:
                return extracted
        return {}
    return _load_trading_plan_result_file(resolved)
__all__ = [
    "attach_tickers_to_longbridge_news_details",
    "build_monitor_trade_card_from_price_paths",
    "build_local_stock_pool_from_trading_plan_result",
    "build_local_stock_pool_from_trading_plan_text",
    "build_plan_snapshot",
    "build_trigger_distance",
    "clean_markdown_text",
    "detect_text_bucket",
    "derive_monitor_price_paths_from_market_snapshot",
    "discover_longbridge_artifacts",
    "enrich_local_stock_pool_for_monitoring",
    "enrich_plan_snapshot_for_monitoring",
    "extract_labeled_text",
    "extract_price_paths_from_text",
    "extract_ticker_name",
    "extract_trade_card_from_text",
    "extract_trading_plan_rows",
    "first_price_value",
    "load_longbridge_plan_source_run",
    "load_longbridge_market_status",
    "load_longbridge_market_temperature",
    "load_longbridge_news_details",
    "load_longbridge_news_headlines",
    "load_market_snapshots",
    "load_trading_plan_result",
    "merge_market_snapshots_into_local_stock_pool",
    "merge_market_snapshots_into_trading_plan_result",
    "normalize_market_snapshot",
    "parse_number_list",
    "plan_notes",
    "plan_strategy_tags",
    "plan_tags",
    "price_path_summary",
    "split_markdown_table_cells",
    "text_looks_like_trading_plan",
    "trading_plan_text_to_result",
]
