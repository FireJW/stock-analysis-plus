#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
TRADINGAGENTS_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "tradingagents-decision-bridge" / "scripts"

import sys

if str(TRADINGAGENTS_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(TRADINGAGENTS_SCRIPT_DIR))

from tradingagents_longbridge_market import fetch_daily_bars, fetch_quote_snapshot, normalize_longbridge_symbol
from longbridge_ownership_runtime import run_longbridge_ownership_analysis
from longbridge_quant_runtime import run_longbridge_quant_analysis
from longbridge_trading_plan_runtime import build_trading_plan_report


CommandRunner = Callable[[list[str], dict[str, str] | None, int], Any]
DEFAULT_ANALYSIS_LAYERS = ("catalyst", "valuation")
ALL_ANALYSIS_LAYERS = (
    "catalyst",
    "valuation",
    "watchlist_alert",
    "portfolio",
    "intraday",
    "theme_chain",
    "governance_structure",
    "account_health",
    "financial_event",
    "ownership_risk",
    "quant",
)
CATALYST_COMMANDS = ("news", "topic", "filing")
VALUATION_COMMANDS = ("valuation", "institution-rating", "forecast-eps", "consensus")
ACCOUNT_COMMANDS = ("watchlist", "alert")
PORTFOLIO_COMMANDS = ("portfolio", "positions", "assets", "cash-flow", "profit-analysis")
INTRADAY_COMMANDS = ("capital", "depth", "trades", "trade-stats", "anomaly", "market-temp")
THEME_CHAIN_COMMANDS = ("company", "industry-valuation", "constituent", "shareholder", "fund-holder", "corp-action")
ACCOUNT_HEALTH_COMMANDS = ("statement", "fund-positions", "exchange-rate", "margin-ratio", "max-qty")
EVENT_DEPTH_COMMANDS = ("financial-report", "finance-calendar", "dividend", "operating", "news detail", "filing detail")
POSITIVE_TERMS = (
    "beat",
    "breakout",
    "buy",
    "growth",
    "inflow",
    "investment",
    "shortage",
    "strong",
    "surge",
    "tight supply",
)
NEGATIVE_TERMS = (
    "cut",
    "downgrade",
    "lawsuit",
    "loss",
    "miss",
    "sell",
    "shortfall",
    "warning",
    "weak",
)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"), strict=False)
    return payload if isinstance(payload, dict) else {}


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def first_number(value: Any) -> float:
    text = clean_text(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return float("nan")
    return to_float(match.group(0))


def latest_finite(values: list[float]) -> float:
    for value in reversed(values):
        if isinstance(value, (int, float)) and not math.isnan(float(value)):
            return float(value)
    return float("nan")


def average(values: list[float]) -> float:
    valid = [float(value) for value in values if isinstance(value, (int, float)) and not math.isnan(float(value))]
    if not valid:
        return float("nan")
    return sum(valid) / len(valid)


def pct_change(start_value: float, end_value: float) -> float:
    if math.isnan(start_value) or math.isnan(end_value) or start_value == 0:
        return float("nan")
    return (end_value / start_value - 1.0) * 100.0


def window_start_date(analysis_date: str, lookback_days: int = 180) -> str:
    try:
        anchor = datetime.strptime(clean_text(analysis_date)[:10], "%Y-%m-%d")
    except ValueError:
        return "2025-01-01"
    return (anchor - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def normalize_analysis_layers(request: dict[str, Any]) -> set[str]:
    if request.get("include_analysis") is False:
        return set()
    raw_layers = request.get("analysis_layers")
    if raw_layers is None:
        return set(DEFAULT_ANALYSIS_LAYERS)
    if isinstance(raw_layers, str):
        tokens = [item.strip().lower() for item in raw_layers.split(",")]
    else:
        tokens = [clean_text(item).lower() for item in raw_layers or []]
    if "none" in tokens or "technical" in tokens and len(tokens) == 1:
        return set()
    if "all" in tokens:
        return set(ALL_ANALYSIS_LAYERS)
    aliases = {
        "account": "watchlist_alert",
        "account_health": "account_health",
        "account_state": "watchlist_alert",
        "alert": "watchlist_alert",
        "alerts": "watchlist_alert",
        "catalyst": "catalyst",
        "content": "catalyst",
        "catalysts": "catalyst",
        "chain": "theme_chain",
        "company": "theme_chain",
        "control_structure": "governance_structure",
        "etf_exposure": "governance_structure",
        "executive": "governance_structure",
        "executives": "governance_structure",
        "fund_exposure": "governance_structure",
        "governance": "governance_structure",
        "governance_structure": "governance_structure",
        "invest_relation": "governance_structure",
        "invest-relation": "governance_structure",
        "management": "governance_structure",
        "news": "catalyst",
        "fundamental": "valuation",
        "fundamentals": "valuation",
        "fund_positions": "account_health",
        "fund-positions": "account_health",
        "health": "account_health",
        "intraday": "intraday",
        "calendar": "financial_event",
        "event": "financial_event",
        "event_depth": "event_depth",
        "events": "financial_event",
        "exchange_rate": "account_health",
        "exchange-rate": "account_health",
        "earnings": "financial_event",
        "finance_calendar": "financial_event",
        "finance-calendar": "financial_event",
        "financial": "financial_event",
        "financial_event": "financial_event",
        "financial_report": "financial_event",
        "financial-report": "financial_event",
        "filing_detail": "financial_event",
        "filing-detail": "financial_event",
        "margin_ratio": "account_health",
        "margin-ratio": "account_health",
        "max_qty": "account_health",
        "max-qty": "account_health",
        "news_detail": "financial_event",
        "news-detail": "financial_event",
        "operating": "financial_event",
        "ownership": "ownership_risk",
        "ownership_risk": "ownership_risk",
        "insider": "ownership_risk",
        "insider_trades": "ownership_risk",
        "insider-trades": "ownership_risk",
        "institutional": "ownership_risk",
        "investors": "ownership_risk",
        "short": "ownership_risk",
        "short_interest": "ownership_risk",
        "short-interest": "ownership_risk",
        "short_positions": "ownership_risk",
        "short-positions": "ownership_risk",
        "quant": "quant",
        "indicator": "quant",
        "indicators": "quant",
        "technical_indicator": "quant",
        "technical-indicator": "quant",
        "portfolio": "portfolio",
        "position": "portfolio",
        "positions": "portfolio",
        "rating": "valuation",
        "ratings": "valuation",
        "report": "financial_event",
        "short_term": "intraday",
        "short-term": "intraday",
        "theme": "theme_chain",
        "theme_chain": "theme_chain",
        "valuation": "valuation",
        "watchlist": "watchlist_alert",
        "watchlist_alert": "watchlist_alert",
        "statement": "account_health",
        "statements": "account_health",
        "dividend": "financial_event",
        "dividends": "financial_event",
    }
    return {aliases[item] for item in tokens if item in aliases}


def optional_longbridge_payload(
    args: list[str],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    unavailable: list[dict[str, str]],
) -> Any:
    command = " ".join(args[:2]) if len(args) >= 2 and args[1] == "detail" else (args[0] if args else "")
    try:
        return runner(args, env, 20)
    except Exception as exc:
        unavailable.append({"command": command, "reason": clean_text(exc)})
        return None


def list_payload(payload: Any, key: str = "") -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if key and isinstance(payload.get(key), list):
            return [item for item in payload[key] if isinstance(item, dict)]
        for fallback_key in ("items", "list"):
            if isinstance(payload.get(fallback_key), list):
                return [item for item in payload[fallback_key] if isinstance(item, dict)]
    return []


def compact_event_items(items: list[dict[str, Any]], timestamp_key: str) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in items[:5]:
        compacted.append(
            {
                "id": clean_text(item.get("id")),
                "title": clean_text(item.get("title") or item.get("file_name")),
                "description": clean_text(item.get("description")),
                "published_at": item.get(timestamp_key) or item.get("published_at") or item.get("publish_at"),
                "url": clean_text(item.get("url")),
                "likes_count": to_int(item.get("likes_count")),
                "comments_count": to_int(item.get("comments_count") or item.get("comments_count")),
            }
        )
    return compacted


def compact_valuation_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    overview = payload.get("overview") if isinstance(payload.get("overview"), dict) else {}
    metrics = overview.get("metrics") if isinstance(overview.get("metrics"), dict) else {}
    pe = metrics.get("pe") if isinstance(metrics.get("pe"), dict) else {}
    return {
        "pe": first_number(pe.get("metric") or pe.get("value")),
        "industry_median": first_number(pe.get("industry_median")),
        "valuation_percentile": first_number(pe.get("part")),
        "description": clean_text(pe.get("desc")),
    }


def compact_rating_payload(payload: Any, last_close: float) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    rating = payload.get("instratings") if isinstance(payload.get("instratings"), dict) else {}
    evaluate = rating.get("evaluate") if isinstance(rating.get("evaluate"), dict) else {}
    target_price = first_number(rating.get("target"))
    target_upside_pct = pct_change(last_close, target_price) if not math.isnan(target_price) else float("nan")
    return {
        "recommendation": clean_text(rating.get("recommend")),
        "target_price": target_price,
        "target_upside_pct": target_upside_pct,
        "strong_buy": to_int(evaluate.get("strong_buy")),
        "buy": to_int(evaluate.get("buy")),
        "hold": to_int(evaluate.get("hold")),
        "under": to_int(evaluate.get("under")),
        "sell": to_int(evaluate.get("sell")),
    }


def compact_forecast_payload(payload: Any) -> dict[str, Any]:
    items = list_payload(payload, "items")
    if not items:
        return {}
    latest = max(items, key=lambda item: to_int(item.get("forecast_start_date")), default={})
    return {
        "forecast_eps_mean": first_number(latest.get("forecast_eps_mean")),
        "institution_up": to_int(latest.get("institution_up")),
        "institution_down": to_int(latest.get("institution_down")),
        "institution_total": to_int(latest.get("institution_total")),
    }


def compact_consensus_payload(payload: Any) -> dict[str, Any]:
    periods = list_payload(payload, "list")
    if not periods:
        return {}
    latest = periods[0]
    details = latest.get("details") if isinstance(latest.get("details"), list) else []
    beats = 0
    misses = 0
    for detail in details:
        if not isinstance(detail, dict):
            continue
        comp = clean_text(detail.get("comp"))
        if comp == "beat_est":
            beats += 1
        elif comp == "miss_est":
            misses += 1
    return {
        "latest_period": clean_text(latest.get("period_text")),
        "beat_count": beats,
        "miss_count": misses,
    }


def compact_generic_payload(payload: Any, *, limit: int = 3) -> dict[str, Any]:
    if isinstance(payload, dict):
        compacted: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                compacted[key] = value
            elif isinstance(value, list):
                compacted[key] = value[:limit]
            elif isinstance(value, dict):
                compacted[key] = compact_generic_payload(value, limit=limit)
        return compacted
    items = list_payload(payload)
    if items:
        return {"items": items[:limit], "count": len(items)}
    if clean_text(payload):
        return {"content_preview": clean_text(payload)[:800], "content_length": len(clean_text(payload))}
    return {}


def compact_detail_payload(payload: Any, *, item_id: str, title: str = "") -> dict[str, Any]:
    data = first_payload_dict(payload)
    for nested_key in ("data", "detail", "item", "result", "payload"):
        nested = data.get(nested_key) if isinstance(data, dict) else None
        if isinstance(nested, dict):
            data = nested
            break
    if not data and clean_text(payload):
        text = clean_text(payload)
        return {
            "id": item_id,
            "title": title,
            "content_preview": text[:800],
            "content_length": len(text),
        }
    content = clean_text(
        data.get("content")
        or data.get("markdown")
        or data.get("text")
        or data.get("body")
        or data.get("html")
        or data.get("pdf_text")
        or data.get("plain_text")
        or data.get("raw_text")
        or data.get("description")
        or data.get("summary")
    )
    return {
        "id": clean_text(data.get("id")) or item_id,
        "title": clean_text(data.get("title")) or title,
        "content_preview": content[:800],
        "content_length": len(content),
        "url": clean_text(data.get("url")),
    }


def fetch_event_depth_analysis(
    symbol: str,
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    content_count: int,
    unavailable: list[dict[str, str]],
    news_items: list[dict[str, Any]] | None = None,
    filing_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    detail_count = max(1, min(content_count, 3))
    financial_report = compact_generic_payload(
        optional_longbridge_payload(
            ["financial-report", symbol, "--kind", "ALL", "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    calendar_events = list_payload(
        optional_longbridge_payload(
            ["finance-calendar", "report", "--symbol", symbol, "--count", str(content_count), "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    dividends = list_payload(
        optional_longbridge_payload(
            ["dividend", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    dividend_detail = compact_generic_payload(
        optional_longbridge_payload(
            ["dividend", "detail", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    operating = compact_generic_payload(
        optional_longbridge_payload(
            ["operating", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )

    news_list = list(news_items or [])
    if not news_list:
        news_list = list_payload(
            optional_longbridge_payload(
                ["news", symbol, "--count", str(detail_count), "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )
    filings = list(filing_items or [])
    if not filings:
        filings = list_payload(
            optional_longbridge_payload(
                ["filing", symbol, "--count", str(detail_count), "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )

    news_details: list[dict[str, Any]] = []
    for item in news_list[:detail_count]:
        news_id = clean_text(item.get("id") or item.get("news_id") or item.get("article_id"))
        if not news_id:
            continue
        detail = optional_longbridge_payload(
            ["news", "detail", news_id, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
        if detail:
            news_details.append(compact_detail_payload(detail, item_id=news_id, title=clean_text(item.get("title"))))

    filing_details: list[dict[str, Any]] = []
    for item in filings[:detail_count]:
        filing_id = clean_text(item.get("id") or item.get("filing_id") or item.get("file_id"))
        if not filing_id:
            continue
        detail = optional_longbridge_payload(
            ["filing", "detail", symbol, filing_id, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
        if detail:
            filing_details.append(compact_detail_payload(detail, item_id=filing_id, title=clean_text(item.get("title"))))

    return {
        "financial_report": financial_report,
        "finance_calendar": compact_event_items(calendar_events, "event_date"),
        "dividends": compact_event_items(dividends, "ex_date"),
        "dividend_detail": dividend_detail,
        "operating": operating,
        "news_details": news_details,
        "filing_details": filing_details,
        "data_coverage": {
            "financial_report_available": bool(financial_report),
            "finance_calendar_available": bool(calendar_events),
            "dividend_available": bool(dividends) or bool(dividend_detail),
            "operating_available": bool(operating),
            "news_detail_available": bool(news_details),
            "filing_detail_available": bool(filing_details),
        },
        "should_apply": False,
        "side_effects": "none",
    }


def fetch_financial_event_analysis(
    candidate: dict[str, Any],
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    symbol = clean_text(candidate.get("symbol"))
    content_count = max(1, min(to_int(request.get("content_count"), 3), 10))
    unavailable: list[dict[str, str]] = []
    longbridge_analysis = candidate.get("longbridge_analysis") if isinstance(candidate.get("longbridge_analysis"), dict) else {}
    catalysts = longbridge_analysis.get("catalysts") if isinstance(longbridge_analysis.get("catalysts"), dict) else {}
    news_items = catalysts.get("news") if isinstance(catalysts.get("news"), list) else []
    filing_items = catalysts.get("filings") if isinstance(catalysts.get("filings"), list) else []
    raw_event_depth = fetch_event_depth_analysis(
        symbol,
        runner=runner,
        env=env,
        content_count=content_count,
        unavailable=unavailable,
        news_items=news_items,
        filing_items=filing_items,
    )
    coverage = raw_event_depth.get("data_coverage") if isinstance(raw_event_depth.get("data_coverage"), dict) else {}
    financial_reports = raw_event_depth.get("financial_report") if isinstance(raw_event_depth.get("financial_report"), dict) else {}
    return {
        "financial_reports": enrich_financial_reports(financial_reports) if financial_reports else {},
        "finance_calendar": raw_event_depth.get("finance_calendar") if isinstance(raw_event_depth.get("finance_calendar"), list) else [],
        "dividends": {
            "history": raw_event_depth.get("dividends") if isinstance(raw_event_depth.get("dividends"), list) else [],
            "detail": raw_event_depth.get("dividend_detail") if isinstance(raw_event_depth.get("dividend_detail"), dict) else {},
        },
        "operating_metrics": raw_event_depth.get("operating") if isinstance(raw_event_depth.get("operating"), dict) else {},
        "news_details": raw_event_depth.get("news_details") if isinstance(raw_event_depth.get("news_details"), list) else [],
        "filing_details": raw_event_depth.get("filing_details") if isinstance(raw_event_depth.get("filing_details"), list) else [],
        "data_coverage": {
            "financial_reports_available": bool(coverage.get("financial_report_available")),
            "finance_calendar_available": bool(coverage.get("finance_calendar_available")),
            "dividends_available": bool(coverage.get("dividend_available")),
            "operating_metrics_available": bool(coverage.get("operating_available")),
            "news_details_available": bool(coverage.get("news_detail_available")),
            "filing_details_available": bool(coverage.get("filing_detail_available")),
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def fetch_longbridge_analysis(
    symbol: str,
    *,
    last_close: float,
    layers: set[str],
    runner: CommandRunner,
    env: dict[str, str] | None,
    content_count: int,
) -> dict[str, Any]:
    unavailable: list[dict[str, str]] = []
    analysis: dict[str, Any] = {
        "layers": sorted(layers),
        "data_coverage": {},
        "catalysts": {},
        "valuation": {},
        "unavailable": unavailable,
    }
    news: list[dict[str, Any]] = []
    filings: list[dict[str, Any]] = []
    if "catalyst" in layers:
        news = list_payload(
            optional_longbridge_payload(
                ["news", symbol, "--count", str(content_count), "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )
        topics = list_payload(
            optional_longbridge_payload(
                ["topic", symbol, "--count", str(content_count), "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )
        filings = list_payload(
            optional_longbridge_payload(
                ["filing", symbol, "--count", str(content_count), "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )
        analysis["catalysts"] = {
            "news": compact_event_items(news, "published_at"),
            "topics": compact_event_items(topics, "published_at"),
            "filings": compact_event_items(filings, "publish_at"),
        }
        analysis["data_coverage"].update(
            {
                "news_count": len(news),
                "topic_count": len(topics),
                "filing_count": len(filings),
            }
        )
    if "valuation" in layers:
        valuation = compact_valuation_payload(
            optional_longbridge_payload(
                ["valuation", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )
        rating = compact_rating_payload(
            optional_longbridge_payload(
                ["institution-rating", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            ),
            last_close,
        )
        forecast = compact_forecast_payload(
            optional_longbridge_payload(
                ["forecast-eps", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )
        consensus = compact_consensus_payload(
            optional_longbridge_payload(
                ["consensus", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )
        analysis["valuation"] = {
            "valuation": valuation,
            "rating": rating,
            "forecast_eps": forecast,
            "consensus": consensus,
        }
        analysis["data_coverage"].update(
            {
                "valuation_available": bool(valuation),
                "institution_rating_available": bool(rating),
                "forecast_eps_available": bool(forecast),
                "consensus_available": bool(consensus),
            }
        )
    if "event_depth" in layers:
        analysis["event_depth"] = fetch_event_depth_analysis(
            symbol,
            runner=runner,
            env=env,
            content_count=content_count,
            unavailable=unavailable,
            news_items=news,
            filing_items=filings,
        )
    return analysis


def keyword_tilt(text: str) -> float:
    lowered = clean_text(text).lower()
    score = 0.0
    for term in POSITIVE_TERMS:
        if term in lowered:
            score += 1.0
    for term in NEGATIVE_TERMS:
        if term in lowered:
            score -= 1.5
    return score


def score_catalysts(analysis: dict[str, Any]) -> float:
    catalysts = analysis.get("catalysts") if isinstance(analysis.get("catalysts"), dict) else {}
    news = catalysts.get("news") if isinstance(catalysts.get("news"), list) else []
    topics = catalysts.get("topics") if isinstance(catalysts.get("topics"), list) else []
    filings = catalysts.get("filings") if isinstance(catalysts.get("filings"), list) else []
    score = min(len(news), 3) * 0.8 + min(len(topics), 3) * 0.6 + min(len(filings), 3) * 0.8
    for item in [*news[:3], *topics[:3], *filings[:3]]:
        if isinstance(item, dict):
            score += keyword_tilt(clean_text(item.get("title")) + " " + clean_text(item.get("description")))
            score += min(to_int(item.get("likes_count")) + to_int(item.get("comments_count")), 10) * 0.1
    return max(min(score, 16.0), -10.0)


def score_valuation(analysis: dict[str, Any]) -> float:
    valuation_layer = analysis.get("valuation") if isinstance(analysis.get("valuation"), dict) else {}
    valuation = valuation_layer.get("valuation") if isinstance(valuation_layer.get("valuation"), dict) else {}
    rating = valuation_layer.get("rating") if isinstance(valuation_layer.get("rating"), dict) else {}
    forecast = valuation_layer.get("forecast_eps") if isinstance(valuation_layer.get("forecast_eps"), dict) else {}
    consensus = valuation_layer.get("consensus") if isinstance(valuation_layer.get("consensus"), dict) else {}

    score = 0.0
    pe = to_float(valuation.get("pe"))
    industry_median = to_float(valuation.get("industry_median"))
    percentile = to_float(valuation.get("valuation_percentile"))
    if not math.isnan(pe) and not math.isnan(industry_median) and industry_median > 0:
        if pe <= industry_median:
            score += 4.0
        elif pe <= industry_median * 1.3:
            score += 2.0
        elif pe >= industry_median * 2:
            score -= 5.0
    if not math.isnan(percentile):
        if percentile <= 0.35:
            score += 3.0
        elif percentile >= 0.85:
            score -= 3.0

    recommendation = clean_text(rating.get("recommendation")).lower()
    if recommendation in {"strong_buy", "buy"}:
        score += 6.0 if recommendation == "strong_buy" else 4.0
    elif recommendation in {"sell", "under", "underperform"}:
        score -= 5.0
    distribution_score = (
        to_int(rating.get("strong_buy")) * 2.0
        + to_int(rating.get("buy"))
        - to_int(rating.get("hold")) * 0.5
        - to_int(rating.get("under"))
        - to_int(rating.get("sell")) * 2.0
    )
    score += max(min(distribution_score, 8.0), -8.0)
    target_upside_pct = to_float(rating.get("target_upside_pct"))
    if not math.isnan(target_upside_pct):
        if target_upside_pct >= 20:
            score += 5.0
        elif target_upside_pct >= 8:
            score += 3.0
        elif target_upside_pct <= -5:
            score -= 3.0

    institution_total = to_int(forecast.get("institution_total"))
    if institution_total:
        score += max(min(to_int(forecast.get("institution_up")) - to_int(forecast.get("institution_down")), 3), -3)
    score += max(min((to_int(consensus.get("beat_count")) - to_int(consensus.get("miss_count"))) * 2.0, 5.0), -5.0)
    return max(min(score, 20.0), -14.0)


def build_tracking_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    signal = clean_text(candidate.get("signal"))
    catalyst_score = to_float(candidate.get("catalyst_score"))
    if signal == "momentum_breakout" and catalyst_score > 0:
        bucket = "breakout_with_catalyst"
    elif signal == "momentum_breakout":
        bucket = "technical_breakout_watch"
    elif signal == "watch_reclaim":
        bucket = "reclaim_watch"
    else:
        bucket = "risk_watch"
    alert_suggestions: list[dict[str, Any]] = []
    if candidate.get("trigger_price") is not None:
        alert_suggestions.append(
            {
                "type": "price_alert",
                "direction": "rise",
                "price": candidate.get("trigger_price"),
                "reason": "breakout trigger",
            }
        )
    if candidate.get("stop_loss") is not None:
        alert_suggestions.append(
            {
                "type": "price_alert",
                "direction": "fall",
                "price": candidate.get("stop_loss"),
                "reason": "risk-control stop",
            }
        )
    if candidate.get("abandon_below") is not None:
        alert_suggestions.append(
            {
                "type": "price_alert",
                "direction": "fall",
                "price": candidate.get("abandon_below"),
                "reason": "abandon watch below this level",
            }
        )
    return {
        "suggested_watchlist_bucket": bucket,
        "alert_suggestions": alert_suggestions,
        "watchlist_action_suggestions": [],
        "alert_action_suggestions": [],
        "should_apply": False,
        "side_effects": "none",
    }


def market_from_symbol(symbol: str) -> str:
    suffix = clean_text(symbol).rsplit(".", 1)[-1].upper()
    if suffix in {"SH", "SZ", "CN"}:
        return "CN"
    if suffix in {"US", "HK", "SG"}:
        return suffix
    return "HK"


def first_payload_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    items = list_payload(payload)
    return items[0] if items else {}


def sum_numeric(items: list[dict[str, Any]], key: str) -> float:
    total = 0.0
    found = False
    for item in items:
        value = to_float(item.get(key))
        if not math.isnan(value):
            total += value
            found = True
    return total if found else float("nan")


def normalize_watchlists(payload: Any) -> list[dict[str, Any]]:
    watchlists: list[dict[str, Any]] = []
    for group in list_payload(payload):
        raw_securities = group.get("securities") or group.get("symbols") or group.get("items") or []
        securities: list[dict[str, str]] = []
        if isinstance(raw_securities, list):
            for item in raw_securities:
                if isinstance(item, dict):
                    symbol = clean_text(item.get("symbol") or item.get("security_code") or item.get("ticker"))
                    if symbol:
                        securities.append({"symbol": symbol, "name": clean_text(item.get("name"))})
                elif clean_text(item):
                    securities.append({"symbol": clean_text(item), "name": ""})
        watchlists.append(
            {
                "id": clean_text(group.get("id") or group.get("group_id")),
                "name": clean_text(group.get("name") or group.get("group_name")),
                "securities": securities,
            }
        )
    return watchlists


def normalize_alerts(payload: Any) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for item in list_payload(payload):
        enabled_value = item.get("enabled")
        status = clean_text(item.get("status")).lower()
        if isinstance(enabled_value, bool):
            enabled = enabled_value
        else:
            enabled = status not in {"disabled", "disable", "off", "inactive"}
        alerts.append(
            {
                "id": clean_text(item.get("id") or item.get("alert_id")),
                "symbol": clean_text(item.get("symbol") or item.get("security_code")),
                "price": to_float(item.get("price") or item.get("trigger_price")),
                "direction": clean_text(item.get("direction") or item.get("trigger_direction")).lower(),
                "status": clean_text(item.get("status")),
                "enabled": enabled,
            }
        )
    return alerts


def _add_symbol_name_aliases(lookup: dict[str, str], symbol: str, name: str) -> None:
    normalized_symbol = clean_text(symbol)
    normalized_name = clean_text(name)
    if not normalized_symbol or not normalized_name:
        return
    try:
        normalized_symbol = normalize_longbridge_symbol(normalized_symbol)
    except Exception:
        normalized_symbol = clean_text(symbol)
    if not normalized_symbol or normalized_name == normalized_symbol:
        return
    lookup.setdefault(normalized_symbol, normalized_name)
    if normalized_symbol.endswith(".SH"):
        lookup.setdefault(normalized_symbol[:-3] + ".SS", normalized_name)
    elif normalized_symbol.endswith(".SS"):
        lookup.setdefault(normalized_symbol[:-3] + ".SH", normalized_name)
    if re.fullmatch(r"\d{6}(?:\.(?:SZ|SS|SH))?", normalized_symbol):
        lookup.setdefault(normalized_symbol[:6], normalized_name)


def normalize_static_name_lookup(payload: Any) -> dict[str, str]:
    lookup: dict[str, str] = {}
    if isinstance(payload, dict) and clean_text(payload.get("symbol")):
        items = [payload]
    else:
        items = list_payload(payload)
    for item in items:
        symbol = clean_text(item.get("symbol") or item.get("ticker") or item.get("code"))
        name = clean_text(item.get("name") or item.get("stock_name") or item.get("symbol_name"))
        _add_symbol_name_aliases(lookup, symbol, name)
    return lookup


def fetch_static_name_lookup(
    symbols: list[str],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    lang: str = "zh-CN",
    unavailable: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    normalized_symbols = []
    for symbol in symbols:
        try:
            normalized = normalize_longbridge_symbol(symbol)
        except Exception:
            normalized = clean_text(symbol)
        if normalized and normalized not in normalized_symbols:
            normalized_symbols.append(normalized)
    if not normalized_symbols:
        return {}
    local_unavailable: list[dict[str, str]] = unavailable if unavailable is not None else []
    args = ["static", *normalized_symbols, "--format", "json"]
    if clean_text(lang):
        args.extend(["--lang", clean_text(lang)])
    payload = optional_longbridge_payload(args, runner=runner, env=env, unavailable=local_unavailable)
    return normalize_static_name_lookup(payload)


def lookup_symbol_name(lookup: dict[str, str], symbol: str) -> str:
    normalized = clean_text(symbol)
    if not normalized:
        return ""
    try:
        normalized = normalize_longbridge_symbol(normalized)
    except Exception:
        pass
    return lookup.get(normalized) or lookup.get(normalized[:6]) or ""


def fetch_account_state(
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    unavailable: list[dict[str, str]] = []
    watchlists = normalize_watchlists(
        optional_longbridge_payload(
            ["watchlist", "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    alerts = normalize_alerts(
        optional_longbridge_payload(
            ["alert", "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    return {
        "watchlists": watchlists,
        "alerts": alerts,
        "data_coverage": {
            "watchlist_available": bool(watchlists),
            "alert_available": bool(alerts),
            "watchlist_group_count": len(watchlists),
            "alert_count": len(alerts),
        },
        "unavailable": unavailable,
        "sensitive_account_data": True,
        "should_apply": False,
        "side_effects": "none",
    }


def update_tracking_actions(candidate: dict[str, Any], account_state: dict[str, Any]) -> None:
    tracking_plan = candidate.get("tracking_plan") if isinstance(candidate.get("tracking_plan"), dict) else {}
    symbol = clean_text(candidate.get("symbol"))
    watchlists = account_state.get("watchlists") if isinstance(account_state.get("watchlists"), list) else []
    alerts = account_state.get("alerts") if isinstance(account_state.get("alerts"), list) else []
    watchlist_groups = [
        group
        for group in watchlists
        if any(clean_text(security.get("symbol")) == symbol for security in group.get("securities", []))
    ]
    watchlist_actions: list[dict[str, Any]] = []
    bucket = clean_text(tracking_plan.get("suggested_watchlist_bucket"))
    if not watchlist_groups and bucket in {"breakout_with_catalyst", "technical_breakout_watch", "reclaim_watch"}:
        watchlist_actions.append(
            {
                "operation": "add",
                "symbol": symbol,
                "target_bucket": bucket,
                "reason": "candidate is ranked for tracking but is not in the current Longbridge watchlist snapshot",
                "should_apply": False,
            }
        )
    if watchlist_groups and bucket == "risk_watch":
        watchlist_actions.append(
            {
                "operation": "remove",
                "symbol": symbol,
                "from_groups": [clean_text(group.get("name")) for group in watchlist_groups],
                "reason": "candidate has weakened into risk_watch",
                "should_apply": False,
            }
        )

    alert_actions: list[dict[str, Any]] = []
    symbol_alerts = [alert for alert in alerts if clean_text(alert.get("symbol")) == symbol]
    for suggestion in tracking_plan.get("alert_suggestions") or []:
        price = to_float(suggestion.get("price"))
        direction = clean_text(suggestion.get("direction")).lower()
        match = next(
            (
                alert
                for alert in symbol_alerts
                if clean_text(alert.get("direction")).lower() == direction
                and not math.isnan(price)
                and not math.isnan(to_float(alert.get("price")))
                and abs(to_float(alert.get("price")) - price) <= max(0.02, price * 0.02)
            ),
            None,
        )
        if match and not match.get("enabled"):
            alert_actions.append(
                {
                    "operation": "enable",
                    "id": clean_text(match.get("id")),
                    "symbol": symbol,
                    "reason": clean_text(suggestion.get("reason")),
                    "should_apply": False,
                }
            )
        elif not match and not math.isnan(price):
            alert_actions.append(
                {
                    "operation": "add",
                    "symbol": symbol,
                    "direction": direction,
                    "price": round(price, 4),
                    "reason": clean_text(suggestion.get("reason")),
                    "should_apply": False,
                }
            )
    suggested_prices = {
        (clean_text(item.get("direction")).lower(), round(to_float(item.get("price")), 2))
        for item in tracking_plan.get("alert_suggestions") or []
        if not math.isnan(to_float(item.get("price")))
    }
    for alert in symbol_alerts:
        alert_price = to_float(alert.get("price"))
        alert_key = (clean_text(alert.get("direction")).lower(), round(alert_price, 2) if not math.isnan(alert_price) else None)
        if alert.get("enabled") and alert_key not in suggested_prices:
            alert_actions.append(
                {
                    "operation": "disable",
                    "id": clean_text(alert.get("id")),
                    "symbol": symbol,
                    "reason": "existing alert does not match current repo-native tracking levels",
                    "should_apply": False,
                }
            )
    tracking_plan["watchlist_action_suggestions"] = watchlist_actions
    tracking_plan["alert_action_suggestions"] = alert_actions
    tracking_plan["should_apply"] = False
    tracking_plan["side_effects"] = "none"
    candidate["tracking_plan"] = tracking_plan


def normalize_positions(payload: Any) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for item in list_payload(payload):
        symbol = clean_text(item.get("symbol") or item.get("security_code"))
        if not symbol:
            continue
        positions.append(
            {
                "symbol": symbol,
                "name": clean_text(item.get("name")),
                "quantity": to_float(item.get("quantity")),
                "available_quantity": to_float(item.get("available_quantity")),
                "cost_price": to_float(item.get("cost_price")),
                "market_value": to_float(item.get("market_value")),
                "today_pl": to_float(item.get("today_pl")),
                "total_pl": to_float(item.get("total_pl")),
                "currency": clean_text(item.get("currency")),
                "market": clean_text(item.get("market")),
            }
        )
    return positions


def compact_asset_overview(payload: Any) -> dict[str, Any]:
    data = first_payload_dict(payload)
    overview = data.get("overview") if isinstance(data.get("overview"), dict) else data
    return {
        "currency": clean_text(overview.get("currency")),
        "net_assets": to_float(overview.get("net_assets") or overview.get("total_asset")),
        "market_cap": to_float(overview.get("market_cap")),
        "total_cash": to_float(overview.get("total_cash")),
        "buy_power": to_float(overview.get("buy_power")),
        "total_pl": to_float(overview.get("total_pl")),
        "total_today_pl": to_float(overview.get("total_today_pl") or overview.get("today_pl")),
        "margin_call": clean_text(overview.get("margin_call")),
        "risk_level": clean_text(overview.get("risk_level")),
    }


def compact_statement_summary(payload: Any) -> dict[str, Any]:
    statements = list_payload(payload)
    latest = statements[0] if statements else {}
    return {
        "statement_count": len(statements),
        "latest_date": clean_text(latest.get("dt") or latest.get("date")),
        "latest_file_key": clean_text(latest.get("file_key")),
        "latest_type": clean_text(latest.get("type") or latest.get("statement_type")),
    }


def normalize_fund_positions(payload: Any) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for item in list_payload(payload):
        symbol = clean_text(item.get("symbol") or item.get("fund_symbol"))
        if not symbol:
            continue
        positions.append(
            {
                "symbol": symbol,
                "name": clean_text(item.get("name")),
                "current_net_asset_value": to_float(item.get("current_net_asset_value")),
                "cost_net_asset_value": to_float(item.get("cost_net_asset_value")),
                "holding_units": to_float(item.get("holding_units")),
                "currency": clean_text(item.get("currency")),
            }
        )
    return positions


def normalize_exchange_rates(payload: Any) -> list[dict[str, Any]]:
    rates: list[dict[str, Any]] = []
    for item in list_payload(payload):
        from_currency = clean_text(item.get("from_currency") or item.get("source_currency") or item.get("from"))
        to_currency = clean_text(item.get("to_currency") or item.get("target_currency") or item.get("to"))
        rate = to_float(item.get("rate") or item.get("exchange_rate"))
        if from_currency or to_currency or not math.isnan(rate):
            rates.append(
                {
                    "from_currency": from_currency,
                    "to_currency": to_currency,
                    "rate": rate if not math.isnan(rate) else None,
                }
            )
    return rates


def compact_margin_ratio(symbol: str, payload: Any) -> dict[str, Any]:
    data = first_payload_dict(payload)
    return {
        "symbol": clean_text(data.get("symbol")) or symbol,
        "initial_margin_factor": first_number(data.get("im_factor") or data.get("initial_margin_factor")),
        "maintenance_margin_factor": first_number(data.get("mm_factor") or data.get("maintenance_margin_factor")),
        "forced_liquidation_factor": first_number(data.get("fm_factor") or data.get("forced_liquidation_factor")),
    }


def compact_max_quantity(symbol: str, side: str, payload: Any) -> dict[str, Any]:
    data = first_payload_dict(payload)
    return {
        "symbol": clean_text(data.get("symbol")) or symbol,
        "side": clean_text(data.get("side")) or side,
        "cash_max_qty": to_float(data.get("cash_max_qty")),
        "margin_max_qty": to_float(data.get("margin_max_qty")),
    }


def fetch_account_health(
    ranked: list[dict[str, Any]],
    analysis_date: str,
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    unavailable: list[dict[str, str]] = []
    statement_type = clean_text(request.get("statement_type")) or "daily"
    statement_limit = max(1, min(to_int(request.get("statement_limit"), 5), 30))
    statement_args = ["statement", "list", "--type", statement_type, "--limit", str(statement_limit)]
    if analysis_date:
        statement_args.extend(["--start-date", window_start_date(analysis_date, 30)])
    statement_args.extend(["--format", "json"])
    statements_payload = optional_longbridge_payload(statement_args, runner=runner, env=env, unavailable=unavailable)
    fund_positions_payload = optional_longbridge_payload(
        ["fund-positions", "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )
    exchange_rate_payload = optional_longbridge_payload(
        ["exchange-rate", "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )

    symbols = [clean_text(item.get("symbol")) for item in ranked if clean_text(item.get("symbol"))]
    symbol_limit = max(1, min(to_int(request.get("account_health_symbol_limit"), len(symbols) or 1), 10))
    margin_checks: list[dict[str, Any]] = []
    max_quantity_checks: list[dict[str, Any]] = []
    for candidate in ranked[:symbol_limit]:
        symbol = clean_text(candidate.get("symbol"))
        if not symbol:
            continue
        margin_payload = optional_longbridge_payload(
            ["margin-ratio", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
        if margin_payload:
            margin_checks.append(compact_margin_ratio(symbol, margin_payload))
        price = to_float(candidate.get("last_close"))
        if math.isnan(price) or price <= 0:
            continue
        for side in ("buy", "sell"):
            max_qty_payload = optional_longbridge_payload(
                ["max-qty", symbol, "--side", side, "--price", str(round(price, 4)), "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
            if max_qty_payload:
                max_quantity_checks.append(compact_max_quantity(symbol, side, max_qty_payload))

    fund_positions = normalize_fund_positions(fund_positions_payload)
    exchange_rates = normalize_exchange_rates(exchange_rate_payload)
    statement_summary = compact_statement_summary(statements_payload)
    return {
        "statement_summary": statement_summary,
        "fund_positions": fund_positions,
        "exchange_rates": exchange_rates,
        "symbol_margin_checks": margin_checks,
        "max_quantity_checks": max_quantity_checks,
        "data_coverage": {
            "statement_available": bool(statement_summary.get("statement_count")),
            "fund_positions_available": bool(fund_positions),
            "exchange_rate_available": bool(exchange_rates),
            "margin_ratio_available": bool(margin_checks),
            "max_qty_available": bool(max_quantity_checks),
        },
        "unavailable": unavailable,
        "sensitive_account_data": True,
        "should_apply": False,
        "side_effects": "none",
    }


def fetch_portfolio_inspection(
    ranked: list[dict[str, Any]],
    analysis_date: str,
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    unavailable: list[dict[str, str]] = []
    portfolio_payload = optional_longbridge_payload(
        ["portfolio", "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )
    positions_payload = optional_longbridge_payload(
        ["positions", "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )
    assets_payload = optional_longbridge_payload(
        ["assets", "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )
    cash_flow_payload = optional_longbridge_payload(
        ["cash-flow", "--start", window_start_date(analysis_date or "", 45), "--end", analysis_date or datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )
    profit_payload = optional_longbridge_payload(
        ["profit-analysis", "--start", window_start_date(analysis_date or "", 45), "--end", analysis_date or datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )

    positions = normalize_positions(positions_payload)
    if not positions and isinstance(portfolio_payload, dict):
        positions = normalize_positions(portfolio_payload.get("holdings"))
    position_symbols = {clean_text(item.get("symbol")) for item in positions}
    by_symbol = {clean_text(item.get("symbol")): item for item in ranked}
    held_weakening: list[dict[str, Any]] = []
    unheld_strong_watch: list[dict[str, Any]] = []
    for symbol in sorted(position_symbols):
        candidate = by_symbol.get(symbol)
        if candidate and (to_float(candidate.get("screen_score")) < 30 or clean_text(candidate.get("signal")) != "momentum_breakout"):
            held_weakening.append(
                {
                    "symbol": symbol,
                    "screen_score": candidate.get("screen_score"),
                    "signal": candidate.get("signal"),
                    "suggested_action": "review_reduce_or_hold_only",
                    "reason": "held position does not confirm strongly in current screen",
                }
            )
    for candidate in ranked:
        symbol = clean_text(candidate.get("symbol"))
        bucket = clean_text((candidate.get("tracking_plan") or {}).get("suggested_watchlist_bucket"))
        if symbol not in position_symbols and bucket in {"breakout_with_catalyst", "technical_breakout_watch"} and to_float(candidate.get("screen_score")) >= 30:
            unheld_strong_watch.append(
                {
                    "symbol": symbol,
                    "screen_score": candidate.get("screen_score"),
                    "bucket": bucket,
                    "suggested_action": "watch_for_entry_confirmation",
                    "reason": "strong screen candidate is not currently held",
                }
            )

    portfolio_overview = compact_asset_overview(portfolio_payload)
    assets_overview = compact_asset_overview(assets_payload)
    total_asset = to_float(portfolio_overview.get("net_assets"))
    if math.isnan(total_asset):
        total_asset = to_float(assets_overview.get("net_assets"))
    concentration: list[dict[str, Any]] = []
    for position in positions:
        market_value = to_float(position.get("market_value"))
        weight = market_value / total_asset if not math.isnan(market_value) and total_asset else float("nan")
        if not math.isnan(weight):
            concentration.append(
                {
                    "symbol": clean_text(position.get("symbol")),
                    "weight": round(weight, 4),
                    "market_value": round(market_value, 2),
                    "risk_flag": weight >= 0.25,
                }
            )
    return {
        "portfolio_overview": portfolio_overview,
        "assets_overview": assets_overview,
        "positions": positions,
        "cash_flow_recent_count": len(list_payload(cash_flow_payload)),
        "profit_analysis": first_payload_dict(profit_payload),
        "held_weakening": held_weakening,
        "unheld_strong_watch": unheld_strong_watch,
        "concentration": concentration,
        "data_coverage": {
            "portfolio_available": bool(portfolio_payload),
            "positions_available": bool(positions),
            "assets_available": bool(assets_payload),
            "cash_flow_available": bool(cash_flow_payload),
            "profit_analysis_available": bool(profit_payload),
        },
        "unavailable": unavailable,
        "sensitive_account_data": True,
        "should_apply": False,
        "side_effects": "none",
    }


def fetch_intraday_confirmation(
    candidate: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    trade_count: int,
) -> dict[str, Any]:
    symbol = clean_text(candidate.get("symbol"))
    market = market_from_symbol(symbol)
    unavailable: list[dict[str, str]] = []
    capital = first_payload_dict(
        optional_longbridge_payload(
            ["capital", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    depth = first_payload_dict(
        optional_longbridge_payload(
            ["depth", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    trades = list_payload(
        optional_longbridge_payload(
            ["trades", symbol, "--count", str(max(1, min(trade_count, 1000))), "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    trade_stats = first_payload_dict(
        optional_longbridge_payload(
            ["trade-stats", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    anomalies = list_payload(
        optional_longbridge_payload(
            ["anomaly", "--market", market, "--symbol", symbol, "--count", "10", "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    market_temp = first_payload_dict(
        optional_longbridge_payload(
            ["market-temp", market, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )

    score = 0.0
    net_inflow = to_float(capital.get("net_inflow") or capital.get("inflow"))
    if not math.isnan(net_inflow):
        score += 5.0 if net_inflow > 0 else -4.0
    large_in = to_float(capital.get("large_order_inflow"))
    large_out = to_float(capital.get("large_order_outflow"))
    if not math.isnan(large_in) and not math.isnan(large_out):
        score += max(min((large_in - large_out) / max(abs(large_in) + abs(large_out), 1) * 6.0, 6.0), -6.0)

    bids = list_payload(depth, "bids")
    asks = list_payload(depth, "asks")
    bid_volume = sum_numeric(bids[:5], "volume")
    ask_volume = sum_numeric(asks[:5], "volume")
    if not math.isnan(bid_volume) and not math.isnan(ask_volume) and ask_volume:
        depth_ratio = bid_volume / ask_volume
        if depth_ratio >= 1.2:
            score += 4.0
        elif depth_ratio <= 0.8:
            score -= 3.0
    else:
        depth_ratio = float("nan")

    up_volume = sum(to_float(item.get("volume")) for item in trades if clean_text(item.get("direction")).lower() == "up" and not math.isnan(to_float(item.get("volume"))))
    down_volume = sum(to_float(item.get("volume")) for item in trades if clean_text(item.get("direction")).lower() == "down" and not math.isnan(to_float(item.get("volume"))))
    if up_volume or down_volume:
        score += max(min((up_volume - down_volume) / max(up_volume + down_volume, 1) * 5.0, 5.0), -5.0)
    if trade_stats:
        score += 1.0
    if anomalies:
        score -= min(len(anomalies) * 2.0, 6.0)
    temperature = first_number(market_temp.get("temperature") or market_temp.get("temp"))
    if not math.isnan(temperature):
        if 45 <= temperature <= 75:
            score += 1.5
        elif temperature > 85:
            score -= 2.0
    return {
        "short_term_confirmation_score": round(max(min(score, 18.0), -14.0), 2),
        "evidence": {
            "capital": {
                "net_inflow": net_inflow if not math.isnan(net_inflow) else None,
                "large_order_inflow": large_in if not math.isnan(large_in) else None,
                "large_order_outflow": large_out if not math.isnan(large_out) else None,
            },
            "depth": {
                "bid_volume_top5": bid_volume if not math.isnan(bid_volume) else None,
                "ask_volume_top5": ask_volume if not math.isnan(ask_volume) else None,
                "bid_ask_depth_ratio": round(depth_ratio, 4) if not math.isnan(depth_ratio) else None,
            },
            "trades": {
                "sample_count": len(trades),
                "up_volume": up_volume,
                "down_volume": down_volume,
            },
            "anomaly_count": len(anomalies),
            "market_temperature": temperature if not math.isnan(temperature) else None,
        },
        "data_coverage": {
            "capital_available": bool(capital),
            "depth_available": bool(depth),
            "trades_available": bool(trades),
            "trade_stats_available": bool(trade_stats),
            "anomaly_available": bool(anomalies) or not any(item.get("command") == "anomaly" for item in unavailable),
            "market_temp_available": bool(market_temp),
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def fetch_theme_chain_analysis(
    candidate: dict[str, Any],
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    symbol = clean_text(candidate.get("symbol"))
    unavailable: list[dict[str, str]] = []
    analysis_layers = normalize_analysis_layers(request)
    include_governance = "governance_structure" in analysis_layers
    company = first_payload_dict(
        optional_longbridge_payload(
            ["company", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    industry_valuation = first_payload_dict(
        optional_longbridge_payload(
            ["industry-valuation", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )
    shareholders = list_payload(
        optional_longbridge_payload(
            ["shareholder", symbol, "--sort", "owned", "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )[:5]
    fund_holders = list_payload(
        optional_longbridge_payload(
            ["fund-holder", symbol, "--count", "10", "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )[:5]
    corp_actions = list_payload(
        optional_longbridge_payload(
            ["corp-action", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )[:5]
    executives = list_payload(
        optional_longbridge_payload(
            ["executive", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )[:5] if include_governance else []
    invest_relations = list_payload(
        optional_longbridge_payload(
            ["invest-relation", symbol, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    )[:5] if include_governance else []
    theme_indexes = [clean_text(item) for item in request.get("theme_indexes") or [] if clean_text(item)]
    memberships: list[str] = []
    constituent_samples: list[dict[str, Any]] = []
    for index_symbol in theme_indexes:
        constituents = list_payload(
            optional_longbridge_payload(
                ["constituent", index_symbol, "--limit", "100", "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        )
        for item in constituents:
            if clean_text(item.get("symbol")) == symbol:
                memberships.append(index_symbol)
                constituent_samples.append(
                    {
                        "index": index_symbol,
                        "weight": first_number(item.get("weight")),
                        "name": clean_text(item.get("name")),
                    }
                )
                break

    score = 0.0
    if company:
        score += 2.0
    percentile = first_number(industry_valuation.get("percentile") or industry_valuation.get("valuation_percentile") or industry_valuation.get("part"))
    pe = first_number(industry_valuation.get("pe"))
    industry_median = first_number(industry_valuation.get("industry_median"))
    if not math.isnan(percentile):
        if percentile <= 0.35:
            score += 4.0
        elif percentile >= 0.8:
            score -= 3.0
    elif not math.isnan(pe) and not math.isnan(industry_median) and industry_median:
        score += 3.0 if pe <= industry_median else -1.0
    score += min(len(memberships) * 3.0, 6.0)
    score += min(len(shareholders), 3) * 0.6
    score += min(len(fund_holders), 3) * 0.6
    if corp_actions:
        score -= 1.0
    if include_governance:
        score += min(len(executives), 3) * 0.8
        score += min(len(invest_relations), 3) * 0.4
        if shareholders:
            score += 0.6
        if fund_holders:
            score += 0.5
        if constituent_samples:
            score += 0.5
        if not executives:
            score -= 0.8
    top_shareholder = shareholders[0] if shareholders else {}
    top_shareholder_owned = first_number(
        top_shareholder.get("owned")
        or top_shareholder.get("ownership")
        or top_shareholder.get("weight")
        or top_shareholder.get("percent")
        or top_shareholder.get("percentage")
    )
    governance_flags: list[str] = []
    if shareholders:
        governance_flags.append(
            f"top_shareholder={clean_text(top_shareholder.get('name') or top_shareholder.get('holder') or top_shareholder.get('symbol'))}"
        )
    if not math.isnan(top_shareholder_owned) and top_shareholder_owned >= 20:
        governance_flags.append(f"concentrated_ownership={round(top_shareholder_owned, 2)}")
    if executives:
        governance_flags.append(f"executive_count={len(executives)}")
    if invest_relations:
        governance_flags.append(f"invest_relation_count={len(invest_relations)}")
    if fund_holders:
        governance_flags.append(f"fund_holder_count={len(fund_holders)}")
    if constituent_samples:
        governance_flags.append(f"index_membership_count={len(constituent_samples)}")
    governance_summary_parts = [
        clean_text(company.get("name")) or symbol,
        f"industry={clean_text(company.get('industry')) or 'unavailable'}",
    ]
    if shareholders:
        governance_summary_parts.append(f"top_holder={clean_text(top_shareholder.get('name') or top_shareholder.get('holder') or top_shareholder.get('symbol')) or 'unavailable'}")
    if executives:
        governance_summary_parts.append(f"executives={len(executives)}")
    if invest_relations:
        governance_summary_parts.append(f"invest_relations={len(invest_relations)}")
    if constituent_samples:
        governance_summary_parts.append(f"index_memberships={len(constituent_samples)}")
    governance_structure = {
        "summary": "; ".join(part for part in governance_summary_parts if part),
        "executive_summary": [
            {
                "name": clean_text(item.get("name") or item.get("person_name")),
                "title": clean_text(item.get("title") or item.get("role")),
            }
            for item in executives[:3]
            if clean_text(item.get("name") or item.get("person_name"))
        ],
        "invest_relation_summary": [
            {
                "title": clean_text(item.get("title") or item.get("name")),
                "published_at": clean_text(item.get("published_at") or item.get("publish_at")),
                "url": clean_text(item.get("url")),
            }
            for item in invest_relations[:3]
            if clean_text(item.get("title") or item.get("name"))
        ],
        "holder_summary": {
            "top_shareholder": clean_text(top_shareholder.get("name") or top_shareholder.get("holder") or top_shareholder.get("symbol")),
            "top_shareholder_owned": top_shareholder_owned if not math.isnan(top_shareholder_owned) else None,
            "fund_holder_count": len(fund_holders),
        },
        "constituent_summary": {
            "index_memberships": memberships,
            "sample_count": len(constituent_samples),
        },
        "key_flags": governance_flags,
        "governance_structure_score": round(max(min(score, 16.0), -8.0), 2),
        "data_coverage": {
            "executive_available": bool(executives) or not include_governance,
            "invest_relation_available": bool(invest_relations) or not include_governance,
            "company_available": bool(company),
            "shareholder_available": bool(shareholders),
            "fund_holder_available": bool(fund_holders),
            "constituent_available": bool(constituent_samples),
        },
        "unavailable": [item for item in unavailable if item.get("command") in {"executive", "invest-relation"}] if include_governance else [],
        "should_apply": False,
        "side_effects": "none",
    }
    return {
        "company": {
            "symbol": clean_text(company.get("symbol")) or symbol,
            "name": clean_text(company.get("name")),
            "industry": clean_text(company.get("industry")),
            "employees": clean_text(company.get("employees")),
            "ipo_date": clean_text(company.get("ipo_date") or company.get("listing_date")),
        },
        "industry_valuation": {
            "industry": clean_text(industry_valuation.get("industry")),
            "pe": pe if not math.isnan(pe) else None,
            "industry_median": industry_median if not math.isnan(industry_median) else None,
            "percentile": percentile if not math.isnan(percentile) else None,
        },
        "index_memberships": memberships,
        "constituent_evidence": constituent_samples,
        "shareholder_clues": shareholders,
        "fund_holder_clues": fund_holders,
        "corp_action_risks": corp_actions,
        "theme_chain_score": round(max(min(score, 14.0), -8.0), 2),
        "theme_rank_explanation": "Ranks higher when company basics are available, industry valuation is not stretched, and index/fund/shareholder or governance links confirm the theme.",
        "governance_structure": governance_structure,
        "data_coverage": {
            "company_available": bool(company),
            "industry_valuation_available": bool(industry_valuation),
            "constituent_available": bool(constituent_samples),
            "shareholder_available": bool(shareholders),
            "fund_holder_available": bool(fund_holders),
            "corp_action_available": bool(corp_actions) or not any(item.get("command") == "corp-action" for item in unavailable),
            "executive_available": bool(executives) or not include_governance,
            "invest_relation_available": bool(invest_relations) or not include_governance,
            "governance_structure_available": include_governance,
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def compute_atr14(rows: list[dict[str, Any]]) -> float:
    if len(rows) < 2:
        return float("nan")
    true_ranges: list[float] = []
    previous_close = to_float(rows[0].get("close"))
    for row in rows[1:]:
        high = to_float(row.get("high"))
        low = to_float(row.get("low"))
        close = to_float(row.get("close"))
        tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(tr)
        previous_close = close
    return average(true_ranges[-14:])


def score_candidate(
    quote: dict[str, Any],
    rows: list[dict[str, Any]],
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    closes = [to_float(row.get("close")) for row in rows]
    highs = [to_float(row.get("high")) for row in rows]
    lows = [to_float(row.get("low")) for row in rows]
    volumes = [to_float(row.get("vol")) for row in rows]

    last_close = to_float(quote.get("last_price"))
    prev_close = to_float(quote.get("prev_close"))
    day_pct = pct_change(prev_close, last_close)
    sma5 = average(closes[-5:])
    sma10 = average(closes[-10:])
    sma20 = average(closes[-20:])
    sma60 = average(closes[-60:])
    ret5 = pct_change(closes[-6], closes[-1]) if len(closes) >= 6 else float("nan")
    ret20 = pct_change(closes[-21], closes[-1]) if len(closes) >= 21 else float("nan")
    volume_ratio_20 = volumes[-1] / average(volumes[-20:]) if len(volumes) >= 20 and average(volumes[-20:]) else float("nan")
    atr14 = compute_atr14(rows)
    prior_20_high = max(highs[-21:-1]) if len(highs) >= 21 else max(highs[:-1], default=float("nan"))
    recent_10_low = min(lows[-10:]) if len(lows) >= 10 else min(lows, default=float("nan"))
    breakout = not math.isnan(prior_20_high) and last_close >= prior_20_high

    score = 0.0
    if not math.isnan(day_pct):
        score += max(min(day_pct, 8.0), -8.0) * 1.5
    if not math.isnan(ret5):
        score += max(min(ret5, 15.0), -15.0)
    if not math.isnan(ret20):
        score += max(min(ret20, 20.0), -20.0) * 0.6
    if not math.isnan(volume_ratio_20):
        score += min(max(volume_ratio_20 - 1.0, -1.0), 2.5) * 12.0
    if not math.isnan(sma20) and last_close > sma20:
        score += 8.0
    if not math.isnan(sma60) and last_close > sma60:
        score += 8.0
    if not math.isnan(sma20) and not math.isnan(sma60) and sma20 > sma60:
        score += 6.0
    if breakout:
        score += 12.0

    signal = "momentum_breakout"
    if not breakout and not math.isnan(volume_ratio_20) and volume_ratio_20 < 1.1:
        signal = "watch_reclaim"
    if not math.isnan(sma60) and last_close < sma60:
        signal = "rebound_only"

    technical_score = round(score, 2)
    longbridge_analysis = analysis if isinstance(analysis, dict) else {
        "layers": [],
        "data_coverage": {},
        "catalysts": {},
        "valuation": {},
        "unavailable": [],
    }
    catalyst_score = round(score_catalysts(longbridge_analysis), 2)
    valuation_score = round(score_valuation(longbridge_analysis), 2)
    total_score = round(technical_score + catalyst_score + valuation_score, 2)
    candidate = {
        "symbol": clean_text(quote.get("symbol")),
        "name": clean_text(quote.get("name")) or clean_text(quote.get("symbol")),
        "last_close": round(last_close, 2),
        "day_pct": round(day_pct, 2) if not math.isnan(day_pct) else None,
        "ret5": round(ret5, 2) if not math.isnan(ret5) else None,
        "ret20": round(ret20, 2) if not math.isnan(ret20) else None,
        "sma5": round(sma5, 2) if not math.isnan(sma5) else None,
        "sma10": round(sma10, 2) if not math.isnan(sma10) else None,
        "sma20": round(sma20, 2) if not math.isnan(sma20) else None,
        "sma60": round(sma60, 2) if not math.isnan(sma60) else None,
        "volume_ratio_20": round(volume_ratio_20, 2) if not math.isnan(volume_ratio_20) else None,
        "atr14": round(atr14, 2) if not math.isnan(atr14) else None,
        "recent_high_20": round(prior_20_high, 2) if not math.isnan(prior_20_high) else None,
        "recent_low_10": round(recent_10_low, 2) if not math.isnan(recent_10_low) else None,
        "breakout": breakout,
        "signal": signal,
        "technical_score": technical_score,
        "catalyst_score": catalyst_score,
        "valuation_score": valuation_score,
        "screen_score": total_score,
        "longbridge_analysis": longbridge_analysis,
        "trigger_price": round(prior_20_high + 0.01, 2) if not math.isnan(prior_20_high) else None,
        "stop_loss": round(max(recent_10_low, last_close - (atr14 * 1.1)), 2) if not math.isnan(atr14) and not math.isnan(recent_10_low) else None,
        "abandon_below": round(recent_10_low - 0.01, 2) if not math.isnan(recent_10_low) else None,
    }
    candidate["tracking_plan"] = build_tracking_plan(candidate)
    return candidate


def summarize_winner(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    if not ranked:
        return {"winner": "", "runner_up": "", "summary": "No candidates were ranked."}
    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else {}
    summary = (
        f"{winner['symbol']} ranks first with score {winner['screen_score']}."
        f" Signal={winner['signal']}, technical={winner.get('technical_score')},"
        f" catalyst={winner.get('catalyst_score')}, valuation={winner.get('valuation_score')}."
        f" Trigger={winner.get('trigger_price')}, stop={winner.get('stop_loss')}."
    )
    return {
        "winner": winner["symbol"],
        "runner_up": clean_text(runner_up.get("symbol")),
        "summary": summary,
    }


def attach_ownership_risk(
    result: dict[str, Any],
    ranked: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> None:
    symbols = [clean_text(item.get("symbol")) for item in ranked if clean_text(item.get("symbol"))]
    ownership = run_longbridge_ownership_analysis(
        {
            **deepcopy(request),
            "tickers": symbols,
        },
        runner=runner,
        env=env,
    )
    result["ownership_risk"] = ownership
    symbol_flags: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    for flag in ownership.get("risk_flags") or []:
        if isinstance(flag, dict):
            symbol_flags.setdefault(clean_text(flag.get("symbol")), []).append(flag)
    coverage = ownership.get("data_coverage") if isinstance(ownership.get("data_coverage"), dict) else {}
    for candidate in ranked:
        symbol = clean_text(candidate.get("symbol"))
        unavailable = [
            item for item in ownership.get("unavailable") or []
            if isinstance(item, dict) and clean_text(item.get("symbol")) in {"", symbol}
        ]
        candidate["ownership_risk_analysis"] = {
            **((ownership.get("ownership_risk_analysis") or {}).get(symbol) or {}),
            "insider_trades": (ownership.get("insider_trades") or {}).get(symbol, []),
            "short_positions": (ownership.get("short_positions") or {}).get(symbol, []),
            "risk_flags": symbol_flags.get(symbol, []),
            "data_coverage": {
                "insider_trades": ((coverage.get("insider_trades") or {}).get(symbol)),
                "short_positions": ((coverage.get("short_positions") or {}).get(symbol)),
                "institutional_investors": coverage.get("institutional_investors") or {},
            },
            "unavailable": unavailable,
            "should_apply": False,
            "side_effects": "none",
        }


def attach_quant_analysis(
    result: dict[str, Any],
    ranked: list[dict[str, Any]],
    request: dict[str, Any],
    analysis_date: str,
    start_date: str,
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> None:
    symbols = [clean_text(item.get("symbol")) for item in ranked if clean_text(item.get("symbol"))]
    quant_request = {
        **deepcopy(request),
        "tickers": symbols,
        "start": clean_text(request.get("quant_start") or request.get("start") or start_date),
        "end": clean_text(request.get("quant_end") or request.get("end") or analysis_date),
        "period": clean_text(request.get("quant_period") or request.get("period") or "day"),
    }
    quant = run_longbridge_quant_analysis(quant_request, runner=runner, env=env)
    result["quant_analysis"] = quant
    by_symbol = (quant.get("signal_alignment") or {}).get("by_symbol") or {}
    for candidate in ranked:
        symbol = clean_text(candidate.get("symbol"))
        unavailable = [
            item for item in quant.get("unavailable") or []
            if isinstance(item, dict) and clean_text(item.get("symbol")) == symbol
        ]
        candidate["quant_analysis"] = {
            "analysis": (quant.get("quant_analysis") or {}).get(symbol, {}),
            "indicators": (quant.get("indicators") or {}).get(symbol, {}),
            "signal_alignment": by_symbol.get(symbol, {"overall": "neutral", "score": 0, "counts": {}}),
            "data_coverage": quant.get("data_coverage") or {},
            "unavailable": unavailable,
            "should_apply": False,
            "side_effects": "none",
        }


def summarize_text_items(items: list[dict[str, Any]], *, fallback: str, limit: int = 2) -> str:
    fragments: list[str] = []
    for item in items[:limit]:
        title = clean_text(item.get("title"))
        description = clean_text(item.get("description") or item.get("content_preview"))
        if title and description:
            fragments.append(f"{title}: {description}")
        elif title:
            fragments.append(title)
        elif description:
            fragments.append(description)
    return "; ".join(fragments) if fragments else fallback


def markdown_summary(value: Any, *, limit: int = 320) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return clipped.rstrip(" ,;:") + "..."


def candidate_catalyst_items(candidate: dict[str, Any], key: str) -> list[dict[str, Any]]:
    analysis = candidate.get("longbridge_analysis") if isinstance(candidate.get("longbridge_analysis"), dict) else {}
    catalysts = analysis.get("catalysts") if isinstance(analysis.get("catalysts"), dict) else {}
    value = catalysts.get(key)
    return value if isinstance(value, list) else []


def candidate_financial_event(candidate: dict[str, Any]) -> dict[str, Any]:
    event = candidate.get("financial_event_analysis")
    return event if isinstance(event, dict) else {}


def candidate_valuation_layer(candidate: dict[str, Any]) -> dict[str, Any]:
    analysis = candidate.get("longbridge_analysis") if isinstance(candidate.get("longbridge_analysis"), dict) else {}
    valuation = analysis.get("valuation") if isinstance(analysis.get("valuation"), dict) else {}
    return valuation


def first_report(candidate: dict[str, Any]) -> dict[str, Any]:
    reports = candidate_financial_event(candidate).get("financial_reports")
    if not isinstance(reports, dict):
        return {}
    rows = list_payload(reports, "reports")
    return rows[0] if rows else reports


def comparable_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_text(value).lower())


def numeric_field(payload: dict[str, Any], *keys: str) -> float:
    comparable_payload = {
        comparable_key(key): value
        for key, value in payload.items()
        if isinstance(key, str)
    }
    for key in keys:
        value = payload.get(key)
        if value is None:
            value = comparable_payload.get(comparable_key(key))
        if value is not None:
            value = first_number(value)
            if not math.isnan(value):
                return value
    return float("nan")


def normalized_financial_metrics(report: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "revenue": ("revenue", "total_revenue", "operating_revenue", "totalRevenue", "operatingRevenue"),
        "net_income": ("net_income", "profit", "net_profit", "netProfit"),
        "net_income_yoy": ("net_income_yoy", "profit_yoy", "net_profit_yoy", "netProfitYoy"),
        "operating_cash_flow": (
            "operating_cash_flow",
            "net_operating_cash_flow",
            "cash_flow_from_operations",
            "operating_net_cash_flow",
            "net_cash_flow_from_operating_activities",
            "netCashFlowFromOperatingActivities",
        ),
        "eps": ("eps", "basic_eps", "diluted_eps", "basicEPS", "dilutedEPS"),
    }
    metrics: dict[str, Any] = {}
    for metric_name, metric_aliases in aliases.items():
        value = numeric_field(report, *metric_aliases)
        metrics[metric_name] = None if math.isnan(value) else value
    return metrics


def enrich_financial_reports(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(payload)
    rows = list_payload(enriched, "reports")
    source = rows[0] if rows else enriched
    enriched["normalized_metrics"] = normalized_financial_metrics(source)
    return enriched


def has_profit_cashflow_divergence(candidate: dict[str, Any]) -> bool:
    report = first_report(candidate)
    net_income = numeric_field(report, "net_income", "profit", "net_profit", "netProfit")
    net_income_yoy = numeric_field(report, "net_income_yoy", "profit_yoy", "net_profit_yoy")
    operating_cash_flow = numeric_field(
        report,
        "operating_cash_flow",
        "net_operating_cash_flow",
        "cash_flow_from_operations",
        "operating_net_cash_flow",
        "net_cash_flow_from_operating_activities",
    )
    profit_positive = (not math.isnan(net_income) and net_income > 0) or (not math.isnan(net_income_yoy) and net_income_yoy > 0)
    return profit_positive and not math.isnan(operating_cash_flow) and operating_cash_flow <= 0


def needs_profit_cashflow_followup(candidate: dict[str, Any]) -> bool:
    if has_profit_cashflow_divergence(candidate):
        return True
    report = first_report(candidate)
    operating_cash_flow = numeric_field(
        report,
        "operating_cash_flow",
        "net_operating_cash_flow",
        "cash_flow_from_operations",
        "operating_net_cash_flow",
        "net_cash_flow_from_operating_activities",
    )
    if not math.isnan(operating_cash_flow):
        return False
    text_parts: list[str] = []
    for key in ("news", "topics", "filings"):
        for item in candidate_catalyst_items(candidate, key):
            text_parts.append(clean_text(item.get("title")))
            text_parts.append(clean_text(item.get("description")))
    event = candidate_financial_event(candidate)
    for key in ("news_details", "filing_details"):
        value = event.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text_parts.append(clean_text(item.get("title")))
                    text_parts.append(clean_text(item.get("content_preview")))
    lowered = " ".join(text_parts).lower()
    profit_terms = ("net profit", "profit", "eps", "earnings", "growth", "increase", "yoy")
    return bool(report or event) and any(term in lowered for term in profit_terms)


def has_valuation_target_conflict(candidate: dict[str, Any]) -> bool:
    valuation_layer = candidate_valuation_layer(candidate)
    valuation = valuation_layer.get("valuation") if isinstance(valuation_layer.get("valuation"), dict) else {}
    rating = valuation_layer.get("rating") if isinstance(valuation_layer.get("rating"), dict) else {}
    pe = to_float(valuation.get("pe"))
    industry_median = to_float(valuation.get("industry_median"))
    percentile = to_float(valuation.get("valuation_percentile"))
    upside = to_float(rating.get("target_upside_pct"))
    expensive = (
        (not math.isnan(pe) and not math.isnan(industry_median) and industry_median > 0 and pe >= industry_median * 1.3)
        or (not math.isnan(percentile) and percentile >= 0.8)
    )
    negative_target = not math.isnan(upside) and upside <= 0
    optimistic_target = not math.isnan(upside) and upside >= 20
    return negative_target or (expensive and optimistic_target)


def has_topic_clarification_risk(candidate: dict[str, Any]) -> bool:
    risky_terms = (
        "abnormal volatility",
        "clarification",
        "h share",
        "h-share",
        "bulk trade",
        "investor relations",
        "application",
        "topic clarification",
        "\u6f84\u6e05",
        "\u5f02\u5e38\u6ce2\u52a8",
        "H\u80a1",
        "H \u80a1",
        "\u5927\u5b97\u4ea4\u6613",
        "\u6295\u8d44\u8005\u5173\u7cfb",
    )
    text_parts: list[str] = []
    for key in ("news", "topics", "filings"):
        for item in candidate_catalyst_items(candidate, key):
            text_parts.append(clean_text(item.get("title")))
            text_parts.append(clean_text(item.get("description")))
    event = candidate_financial_event(candidate)
    for key in ("news_details", "filing_details", "finance_calendar"):
        value = event.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text_parts.append(clean_text(item.get("title")))
                    text_parts.append(clean_text(item.get("content_preview")))
                    text_parts.append(clean_text(item.get("description")))
    lowered = " ".join(text_parts).lower()
    return any(term.lower() in lowered for term in risky_terms)


def details_are_incomplete(candidate: dict[str, Any]) -> bool:
    event = candidate_financial_event(candidate)
    if not event:
        return False
    coverage = event.get("data_coverage") if isinstance(event.get("data_coverage"), dict) else {}
    if coverage.get("news_details_available") is False or coverage.get("filing_details_available") is False:
        return True
    unavailable = event.get("unavailable") if isinstance(event.get("unavailable"), list) else []
    return any(
        isinstance(item, dict) and clean_text(item.get("command")) in {"news detail", "filing detail"}
        for item in unavailable
    )


def build_qualitative_evaluation(candidate: dict[str, Any]) -> dict[str, Any]:
    news = candidate_catalyst_items(candidate, "news")
    topics = candidate_catalyst_items(candidate, "topics")
    filings = candidate_catalyst_items(candidate, "filings")
    event = candidate_financial_event(candidate)
    report = first_report(candidate)
    valuation_layer = candidate_valuation_layer(candidate)
    valuation = valuation_layer.get("valuation") if isinstance(valuation_layer.get("valuation"), dict) else {}
    rating = valuation_layer.get("rating") if isinstance(valuation_layer.get("rating"), dict) else {}
    forecast = valuation_layer.get("forecast_eps") if isinstance(valuation_layer.get("forecast_eps"), dict) else {}
    consensus = valuation_layer.get("consensus") if isinstance(valuation_layer.get("consensus"), dict) else {}
    theme_chain = candidate.get("theme_chain_analysis") if isinstance(candidate.get("theme_chain_analysis"), dict) else {}
    governance = theme_chain.get("governance_structure") if isinstance(theme_chain.get("governance_structure"), dict) else {}

    net_income = numeric_field(report, "net_income", "profit", "net_profit", "netProfit")
    operating_cash_flow = numeric_field(
        report,
        "operating_cash_flow",
        "net_operating_cash_flow",
        "cash_flow_from_operations",
        "operating_net_cash_flow",
        "net_cash_flow_from_operating_activities",
    )
    eps = numeric_field(report, "eps", "basic_eps", "diluted_eps", "basicEPS", "dilutedEPS")
    revenue = numeric_field(report, "revenue", "total_revenue", "operating_revenue", "totalRevenue", "operatingRevenue")
    pe = to_float(valuation.get("pe"))
    industry_median = to_float(valuation.get("industry_median"))
    target_price = to_float(rating.get("target_price"))
    target_upside = to_float(rating.get("target_upside_pct"))
    recommendation = clean_text(rating.get("recommendation"))

    catalyst_summary = summarize_text_items(
        [*news, *topics],
        fallback="No strong Longbridge news or community catalyst was parsed for this candidate.",
    )
    if report:
        financial_report_summary = (
            f"Report snapshot includes revenue={None if math.isnan(revenue) else round(revenue, 2)}, "
            f"net_income={None if math.isnan(net_income) else round(net_income, 2)}, "
            f"eps={None if math.isnan(eps) else round(eps, 4)}."
        )
    else:
        financial_report_summary = "Financial report detail was not parsed; keep fundamentals as an open follow-up."

    if has_profit_cashflow_divergence(candidate):
        cashflow_quality = "Profit growth is not cash-flow confirmed: operating cash-flow is negative or weak while profit metrics are positive."
    elif not math.isnan(operating_cash_flow):
        cashflow_quality = f"Operating cash-flow is parsed at {round(operating_cash_flow, 2)}; no profit/cash-flow divergence was flagged."
    else:
        cashflow_quality = "Operating cash-flow data is not fully parsed; cash-flow quality remains unverified."

    if not math.isnan(pe) and not math.isnan(industry_median):
        valuation_assessment = f"PE={round(pe, 2)} versus industry median={round(industry_median, 2)}."
    elif not math.isnan(pe):
        valuation_assessment = f"PE={round(pe, 2)} is available, but the industry comparison is missing."
    else:
        valuation_assessment = "Valuation evidence is incomplete."

    if not math.isnan(target_price):
        rating_target_price_assessment = (
            f"Broker stance={recommendation or 'unavailable'}, target_price={round(target_price, 2)}, "
            f"target_upside_pct={None if math.isnan(target_upside) else round(target_upside, 2)}."
        )
    else:
        rating_target_price_assessment = f"Broker stance={recommendation or 'unavailable'}; target price was not parsed."

    filing_event_summary = summarize_text_items(
        [*filings, *(event.get("filing_details") if isinstance(event.get("filing_details"), list) else [])],
        fallback="No filing detail was parsed for this candidate.",
    )
    research_or_topic_quality = summarize_text_items(
        [*topics, *(event.get("news_details") if isinstance(event.get("news_details"), list) else [])],
        fallback="Research, topic, or detailed news support is thin or unavailable.",
    )
    if forecast or consensus:
        research_or_topic_quality += (
            f" Forecast EPS={forecast.get('forecast_eps_mean') if forecast else None}, "
            f"latest consensus period={consensus.get('latest_period') if consensus else ''}."
        )
    governance_structure_summary = clean_text(governance.get("summary")) or "Governance and company-structure evidence was not requested or parsed."
    governance_structure_flags = [
        clean_text(item)
        for item in (governance.get("key_flags") if isinstance(governance.get("key_flags"), list) else [])
        if clean_text(item)
    ][:5]

    key_risks: list[str] = []
    if has_profit_cashflow_divergence(candidate):
        key_risks.append("profit/cash-flow divergence")
    if has_valuation_target_conflict(candidate):
        key_risks.append("valuation/target-price conflict")
    if has_topic_clarification_risk(candidate):
        key_risks.append("topic clarification or filing-event risk")
    if details_are_incomplete(candidate):
        key_risks.append("news or filing detail not fully parsed")
    if any(flag.startswith("concentrated_ownership") for flag in governance_structure_flags):
        key_risks.append("governance concentration risk")
    if not key_risks:
        key_risks.append("no major qualitative risk parsed from available Longbridge evidence")

    verdict_prefix = "constructive" if to_float(candidate.get("screen_score")) >= 30 else "watch-only"
    if key_risks and key_risks[0] != "no major qualitative risk parsed from available Longbridge evidence":
        qualitative_verdict = f"{verdict_prefix}: score is usable, but {', '.join(key_risks[:3])} needs follow-up before escalation."
    else:
        qualitative_verdict = f"{verdict_prefix}: score and parsed qualitative evidence are broadly aligned."

    return {
        "catalyst_summary": catalyst_summary,
        "financial_report_summary": financial_report_summary,
        "cashflow_quality": cashflow_quality,
        "valuation_assessment": valuation_assessment,
        "rating_target_price_assessment": rating_target_price_assessment,
        "filing_event_summary": filing_event_summary,
        "research_or_topic_quality": research_or_topic_quality,
        "governance_structure_summary": governance_structure_summary,
        "governance_structure_flags": governance_structure_flags,
        "key_risks": key_risks,
        "qualitative_verdict": qualitative_verdict,
    }


def is_weekend_date(value: str) -> bool:
    try:
        return datetime.strptime(clean_text(value)[:10], "%Y-%m-%d").weekday() >= 5
    except ValueError:
        return False


def build_missed_attention_priorities(
    ranked: list[dict[str, Any]],
    *,
    analysis_date: str,
) -> list[dict[str, Any]]:
    priorities: list[dict[str, Any]] = []

    def symbols_where(predicate: Callable[[dict[str, Any]], bool]) -> list[str]:
        return [clean_text(item.get("symbol")) for item in ranked if predicate(item)]

    cashflow_symbols = symbols_where(needs_profit_cashflow_followup)
    if cashflow_symbols:
        priorities.append(
            {
                "priority": "P0",
                "issue": "profit_cashflow_divergence",
                "affected_symbols": cashflow_symbols,
                "why_it_matters": "Reported profit strength without parsed operating cash-flow support can make a momentum setup fragile.",
                "follow_up_action": "Re-read the latest financial report and operating cash-flow table before upgrading the watchlist bucket.",
            }
        )

    valuation_symbols = symbols_where(has_valuation_target_conflict)
    if valuation_symbols:
        priorities.append(
            {
                "priority": "P1",
                "issue": "valuation_target_price_conflict",
                "affected_symbols": valuation_symbols,
                "why_it_matters": "Expensive valuation or target price below spot can conflict with a high screen score.",
                "follow_up_action": "Check valuation percentile, broker target price, EPS forecast, and recent price move together.",
            }
        )

    clarification_symbols = symbols_where(has_topic_clarification_risk)
    if clarification_symbols:
        priorities.append(
            {
                "priority": "P1",
                "issue": "topic_clarification_or_filing_event_risk",
                "affected_symbols": clarification_symbols,
                "why_it_matters": "Clarification, abnormal-volatility, H-share, block-trade, or investor-relations events can reverse theme interpretation.",
                "follow_up_action": "Open the filing detail and investor-relations record before treating the theme as confirmed.",
            }
        )

    if is_weekend_date(analysis_date):
        priorities.append(
            {
                "priority": "P1",
                "issue": "p1_intraday_non_trading_day_followup",
                "affected_symbols": [clean_text(item.get("symbol")) for item in ranked],
                "why_it_matters": "P1 intraday confirmation, capital flow, anomaly, and trade-stat layers are stale or unavailable on non-trading days.",
                "follow_up_action": "Re-run the intraday monitor on the next open session before enabling any watchlist or alert writes.",
            }
        )

    detail_symbols = symbols_where(details_are_incomplete)
    if detail_symbols:
        priorities.append(
            {
                "priority": "P2",
                "issue": "unparsed_news_or_filing_detail",
                "affected_symbols": detail_symbols,
                "why_it_matters": "PDF or non-JSON detail output may hide the exact announcement language behind the score.",
                "follow_up_action": "Fetch news detail and filing detail again with a parser that preserves text previews.",
            }
        )

    if not priorities:
        priorities.append(
            {
                "priority": "P3",
                "issue": "no_material_omission_detected",
                "affected_symbols": [clean_text(item.get("symbol")) for item in ranked[:3]],
                "why_it_matters": "No priority omission was detected from available parsed evidence.",
                "follow_up_action": "Keep the normal open-session P1 refresh before any real account write.",
            }
        )
    return priorities


def build_dry_run_action_plan(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for candidate in ranked[:3]:
        symbol = clean_text(candidate.get("symbol"))
        tracking = candidate.get("tracking_plan") if isinstance(candidate.get("tracking_plan"), dict) else {}
        bucket = clean_text(tracking.get("suggested_watchlist_bucket"))
        if bucket:
            actions.append(
                {
                    "operation": "watchlist.add_stocks",
                    "symbol": symbol,
                    "account_target": bucket,
                    "source": "longbridge-screen",
                    "rationale": clean_text((candidate.get("qualitative_evaluation") or {}).get("qualitative_verdict")),
                    "should_apply": False,
                    "side_effects": "none",
                }
            )
        for alert in tracking.get("alert_suggestions") or []:
            if not isinstance(alert, dict):
                continue
            actions.append(
                {
                    "operation": "alert.add",
                    "symbol": symbol,
                    "account_target": "price_alert",
                    "direction": clean_text(alert.get("direction")),
                    "price": alert.get("price"),
                    "reason": clean_text(alert.get("reason")),
                    "source": "longbridge-screen",
                    "should_apply": False,
                    "side_effects": "none",
                }
            )
    return {
        "status": "dry_run",
        "source": "longbridge-screen",
        "gateway": "longbridge-action-gateway",
        "should_apply": False,
        "side_effects": "none",
        "actions": actions,
        "follow_up": "Pass the screen result to longbridge-action-gateway for audited dry-run conversion before any real account write.",
    }


def run_longbridge_screen(
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    tickers = [clean_text(item) for item in request.get("tickers") or [] if clean_text(item)]
    analysis_date = clean_text(request.get("analysis_date"))
    ranked: list[dict[str, Any]] = []
    start_date = window_start_date(analysis_date or "")
    analysis_layers = normalize_analysis_layers(request)
    content_count = max(1, min(to_int(request.get("content_count"), 3), 10))
    static_unavailable: list[dict[str, str]] = []
    static_name_lookup = fetch_static_name_lookup(
        tickers,
        runner=runner,
        env=env,
        lang=clean_text(request.get("lang")) or "zh-CN",
        unavailable=static_unavailable,
    )
    for ticker in tickers:
        quote = fetch_quote_snapshot(ticker, runner=runner, env=env)
        quote_symbol = clean_text(quote.get("symbol")) or ticker
        static_name = lookup_symbol_name(static_name_lookup, quote_symbol) or lookup_symbol_name(static_name_lookup, ticker)
        quote_name = clean_text(quote.get("name"))
        if static_name and (not quote_name or quote_name in {quote_symbol, ticker}):
            quote["name"] = static_name
        rows = fetch_daily_bars(ticker, start_date, analysis_date or "2099-12-31", runner=runner, env=env)
        analysis = fetch_longbridge_analysis(
            clean_text(quote.get("symbol")) or ticker,
            last_close=to_float(quote.get("last_price")),
            layers=analysis_layers,
            runner=runner,
            env=env,
            content_count=content_count,
        )
        ranked.append(score_candidate(quote, rows, analysis))
    ranked.sort(key=lambda item: item.get("screen_score") or float("-inf"), reverse=True)

    result: dict[str, Any] = {
        "request": deepcopy(request),
        "analysis_date": analysis_date,
        "analysis_layers": sorted(analysis_layers),
        "static_reference": {
            "data_coverage": {
                "requested_symbols": len(tickers),
                "resolved_names": len({name for name in static_name_lookup.values() if name}),
                "name_lookup_available": bool(static_name_lookup),
            },
            "unavailable": static_unavailable,
        },
        "ranked_candidates": ranked,
    }

    if "watchlist_alert" in analysis_layers:
        account_state = fetch_account_state(runner=runner, env=env)
        result["account_state"] = account_state
        for candidate in ranked:
            update_tracking_actions(candidate, account_state)

    if "account_health" in analysis_layers:
        result["account_health"] = fetch_account_health(
            ranked,
            analysis_date,
            request,
            runner=runner,
            env=env,
        )

    if "intraday" in analysis_layers:
        trade_count = max(1, min(to_int(request.get("trade_count"), 50), 1000))
        for candidate in ranked:
            confirmation = fetch_intraday_confirmation(candidate, runner=runner, env=env, trade_count=trade_count)
            candidate["intraday_confirmation"] = confirmation
            score = to_float(candidate.get("workbench_score"))
            if math.isnan(score):
                score = to_float(candidate.get("screen_score"))
            contribution = to_float(confirmation.get("short_term_confirmation_score"))
            candidate["workbench_score"] = round(score + (0.0 if math.isnan(contribution) else contribution), 2)

    if "theme_chain" in analysis_layers or "governance_structure" in analysis_layers:
        for candidate in ranked:
            chain = fetch_theme_chain_analysis(candidate, request, runner=runner, env=env)
            candidate["theme_chain_analysis"] = chain
            score = to_float(candidate.get("workbench_score"))
            if math.isnan(score):
                score = to_float(candidate.get("screen_score"))
            contribution = to_float(chain.get("theme_chain_score"))
            candidate["workbench_score"] = round(score + (0.0 if math.isnan(contribution) else contribution), 2)

    if "financial_event" in analysis_layers:
        for candidate in ranked:
            candidate["financial_event_analysis"] = fetch_financial_event_analysis(
                candidate,
                request,
                runner=runner,
                env=env,
            )

    if "portfolio" in analysis_layers:
        result["portfolio_inspection"] = fetch_portfolio_inspection(
            ranked,
            analysis_date,
            runner=runner,
            env=env,
        )

    if "ownership_risk" in analysis_layers:
        attach_ownership_risk(result, ranked, request, runner=runner, env=env)

    if "quant" in analysis_layers:
        attach_quant_analysis(
            result,
            ranked,
            request,
            analysis_date,
            start_date,
            runner=runner,
            env=env,
        )

    for candidate in ranked:
        candidate["qualitative_evaluation"] = build_qualitative_evaluation(candidate)
    result["missed_attention_priorities"] = build_missed_attention_priorities(
        ranked,
        analysis_date=analysis_date,
    )
    result["key_omissions"] = deepcopy(result["missed_attention_priorities"])
    result["dry_run_action_plan"] = build_dry_run_action_plan(ranked)
    result["summary"] = summarize_winner(ranked)
    result["trading_plan_report"] = build_trading_plan_report(result, session_type="premarket")
    return result


def build_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Longbridge Screen",
        "",
        f"- analysis_date: `{clean_text(result.get('analysis_date'))}`",
        f"- winner: `{clean_text((result.get('summary') or {}).get('winner'))}`",
        "",
    ]
    for item in result.get("ranked_candidates") or []:
        qualitative = item.get("qualitative_evaluation") if isinstance(item.get("qualitative_evaluation"), dict) else {}
        lines.extend(
            [
                f"## {item['symbol']}",
                f"- score: `{item['screen_score']}`",
                f"- technical_score: `{item.get('technical_score')}`",
                f"- catalyst_score: `{item.get('catalyst_score')}`",
                f"- valuation_score: `{item.get('valuation_score')}`",
                f"- signal: `{item['signal']}`",
                f"- last_close: `{item['last_close']}`",
                f"- trigger: `{item.get('trigger_price')}`",
                f"- stop: `{item.get('stop_loss')}`",
                f"- abandon_below: `{item.get('abandon_below')}`",
                f"- ret5 / ret20: `{item.get('ret5')}` / `{item.get('ret20')}`",
                f"- volume_ratio_20: `{item.get('volume_ratio_20')}`",
                f"- watchlist_bucket: `{clean_text((item.get('tracking_plan') or {}).get('suggested_watchlist_bucket'))}`",
                f"- longbridge_coverage: `{json.dumps((item.get('longbridge_analysis') or {}).get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                "### Qualitative Evaluation",
                f"- verdict: {markdown_summary(qualitative.get('qualitative_verdict'))}",
                f"- catalyst: {markdown_summary(qualitative.get('catalyst_summary'))}",
                f"- financial_report: {markdown_summary(qualitative.get('financial_report_summary'))}",
                f"- cashflow_quality: {markdown_summary(qualitative.get('cashflow_quality'))}",
                f"- valuation: {markdown_summary(qualitative.get('valuation_assessment'))}",
                f"- rating_target_price: {markdown_summary(qualitative.get('rating_target_price_assessment'))}",
                f"- filing_event: {markdown_summary(qualitative.get('filing_event_summary'))}",
                f"- research_or_topic: {markdown_summary(qualitative.get('research_or_topic_quality'))}",
                f"- key_risks: `{json.dumps(qualitative.get('key_risks') or [], ensure_ascii=False)}`",
                "",
            ]
        )
    priorities = result.get("missed_attention_priorities") if isinstance(result.get("missed_attention_priorities"), list) else []
    if priorities:
        lines.extend(["## Missed Attention Priorities", ""])
        for item in priorities:
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"- {clean_text(item.get('priority'))} `{clean_text(item.get('issue'))}`: {clean_text(item.get('why_it_matters'))}",
                    f"  - affected_symbols: `{json.dumps(item.get('affected_symbols') or [], ensure_ascii=False)}`",
                    f"  - follow_up_action: {clean_text(item.get('follow_up_action'))}",
                ]
            )
        lines.append("")
    plan = result.get("dry_run_action_plan") if isinstance(result.get("dry_run_action_plan"), dict) else {}
    if plan:
        lines.extend(
            [
                "## Dry-run Action Plan",
                "",
                f"- status: `{clean_text(plan.get('status'))}`",
                f"- should_apply: `{str(bool(plan.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(plan.get('side_effects'))}`",
            ]
        )
        for action in (plan.get("actions") or [])[:10]:
            if not isinstance(action, dict):
                continue
            lines.append(
                f"- {clean_text(action.get('operation'))} `{clean_text(action.get('symbol'))}` "
                f"target=`{clean_text(action.get('account_target'))}` should_apply=`{str(bool(action.get('should_apply'))).lower()}`"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run a Longbridge watchlist screen against a supplied ticker list.")
    parser.add_argument("request_json", help="Path to request JSON containing a `tickers` array.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--markdown-output", help="Optional markdown output path.")
    args = parser.parse_args()

    request = load_json(Path(args.request_json))
    result = run_longbridge_screen(request, runner=lambda a, e=None, t=20: __import__("tradingagents_longbridge_market").run_longbridge_cli(a, e, t))
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        Path(args.markdown_output).write_text(build_markdown_report(result), encoding="utf-8")
    if not args.output and not args.markdown_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
