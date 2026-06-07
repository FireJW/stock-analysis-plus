#!/usr/bin/env python3
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text, unique_strings
from manager_calendar_desk import calendar_event_time_label as _calendar_event_time_label
from manager_html_primitives import display_status_text, safe_dict, safe_list
from manager_pool_merge import normalize_workflow_display_ticker


DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS = 7

DEFAULT_EARNINGS_CALENDAR_HEADLINERS = (
    {"ticker": "NVDA.US", "name": "NVIDIA"},
    {"ticker": "TSM.US", "name": "TSMC"},
    {"ticker": "ASML.US", "name": "ASML"},
    {"ticker": "AMD.US", "name": "AMD"},
    {"ticker": "AVGO.US", "name": "Broadcom"},
    {"ticker": "MSFT.US", "name": "Microsoft"},
    {"ticker": "META.US", "name": "Meta"},
    {"ticker": "GOOGL.US", "name": "Alphabet"},
    {"ticker": "AAPL.US", "name": "Apple"},
    {"ticker": "AMZN.US", "name": "Amazon"},
    {"ticker": "WMT.US", "name": "Walmart"},
    {"ticker": "HD.US", "name": "Home Depot"},
    {"ticker": "ADI.US", "name": "Analog Devices"},
    {"ticker": "DE.US", "name": "Deere"},
    {"ticker": "PDD.US", "name": "PDD"},
    {"ticker": "LOW.US", "name": "Lowe's"},
    {"ticker": "INTU.US", "name": "Intuit"},
    {"ticker": "TGT.US", "name": "Target"},
    {"ticker": "NTES.US", "name": "NetEase"},
    {"ticker": "WDAY.US", "name": "Workday"},
    {"ticker": "ZS.US", "name": "Zscaler"},
    {"ticker": "TTWO.US", "name": "Take-Two"},
    {"ticker": "AZO.US", "name": "AutoZone"},
    {"ticker": "ROST.US", "name": "Ross Stores"},
    {"ticker": "NIO.US", "name": "NIO"},
    {"ticker": "KEYS.US", "name": "Keysight"},
    {"ticker": "688256.SH", "name": "\u5bd2\u6b66\u7eaa"},
    {"ticker": "688981.SH", "name": "\u4e2d\u82af\u56fd\u9645"},
    {"ticker": "300750.SZ", "name": "\u5b81\u5fb7\u65f6\u4ee3"},
    {"ticker": "002594.SZ", "name": "\u6bd4\u4e9a\u8fea"},
)

EARNINGS_IMPORTANCE_REASON_BY_TICKER = {
    "NVDA.US": "AI compute capex and semiconductor market leadership.",
    "WMT.US": "Mega-cap retail and consumer-staples read-through; checks US household demand and margin pressure.",
    "HD.US": "Housing, home improvement, and big-ticket consumer demand signal.",
    "ADI.US": "Analog and industrial semiconductor bellwether; read-through to autos, industrials, and the chip cycle.",
    "DE.US": "Agriculture and industrial equipment cycle bellwether.",
    "PDD.US": "China e-commerce, consumer demand, and cross-border platform read-through.",
    "LOW.US": "Home-improvement demand read-through alongside Home Depot.",
    "INTU.US": "Large-cap software, SMB, tax, and fintech demand read-through.",
    "TGT.US": "US discretionary retail, inventory, and margin signal.",
    "NTES.US": "China internet and online gaming earnings read-through.",
    "WDAY.US": "Enterprise SaaS spending and back-office software demand signal.",
    "ZS.US": "Cybersecurity and cloud software spending signal.",
    "TTWO.US": "Interactive entertainment and gaming pipeline read-through.",
    "AZO.US": "Auto aftermarket and resilient consumer-maintenance demand signal.",
    "ROST.US": "Off-price retail and value-consumer demand signal.",
    "NIO.US": "China EV demand, margin, and delivery-cadence signal.",
    "KEYS.US": "Electronic test-and-measurement read-through for semiconductors and industrial R&D.",
}

EARNINGS_CALENDAR_EVENT_KEYS = (
    "earnings_calendar_events",
    "calendar_events",
    "earnings_events",
    "events",
)

EARNINGS_CALENDAR_WATCHLIST_KEYS = (
    "earnings_calendar_watchlist",
    "earnings_calendar_focus",
    "earnings_calendar_focus_tickers",
    "key_earnings_companies",
    "industry_head_earnings_watchlist",
)

EVENT_CALENDAR_EVENT_KEYS = (
    "event_calendar_events",
    "macro_calendar_events",
    "hard_event_calendar_events",
    "hard_events",
)

EVENT_CALENDAR_WATCHLIST_KEYS = (
    "event_calendar_watchlist",
    "event_calendar_focus",
    "hard_event_watchlist",
    "macro_event_watchlist",
)

HIGH_EVENT_IMPORTANCE = {"high", "critical", "systemic"}


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


def parse_iso_date_value(value: Any) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    date_text = text[:10]
    try:
        return date.fromisoformat(date_text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


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


def _calendar_identity_map(items: list[Any]) -> dict[str, set[str]]:
    identities = {"ticker": set(), "name": set()}
    for item in items:
        if isinstance(item, dict):
            ticker = clean_text(item.get("ticker") or item.get("symbol") or item.get("code"))
            name = clean_text(item.get("name") or item.get("company") or item.get("company_name"))
            if ticker:
                identities["ticker"].update(_calendar_identity_tokens(ticker))
            if name:
                identities["name"].update(_calendar_identity_tokens(name))
            continue
        identities["ticker"].update(_calendar_identity_tokens(item))
        identities["name"].update(_calendar_identity_tokens(item))
    return identities


def _calendar_event_window(start_date: date, lookahead_days: int) -> tuple[date, date]:
    lookahead = max(0, int(lookahead_days))
    return start_date, start_date + timedelta(days=lookahead)


def _calendar_event_scope(
    *,
    ticker: str,
    name: str,
    focus_identities: dict[str, set[str]],
    headliner_identities: dict[str, set[str]],
    explicit_scope: list[str],
) -> list[str]:
    scope = [clean_text(item) for item in explicit_scope if clean_text(item)]
    ticker_tokens = _calendar_identity_tokens(ticker)
    name_tokens = _calendar_identity_tokens(name)
    if ticker_tokens & headliner_identities["ticker"] or name_tokens & headliner_identities["name"]:
        scope.append("industry_leader")
    if ticker_tokens & focus_identities["ticker"] or name_tokens & focus_identities["name"]:
        scope.append("manual_focus")
    return unique_strings(scope)


def _calendar_event_importance_label(value: Any, scope: list[str]) -> str:
    text = clean_text(value).lower()
    if text in {"critical", "high", "important", "\u91cd\u70b9", "\u9ad8"}:
        return "high"
    if any(item in scope for item in ("manual_focus", "industry_leader", "local_stock_pool", "market_cap_headliner")):
        return "high"
    if text:
        return text
    return "medium" if scope else "low"


def _calendar_event_importance_reason(
    *,
    ticker: str,
    name: str,
    scope: list[str],
    raw: dict[str, Any],
) -> str:
    explicit_reason = clean_text(raw.get("importance_reason") or raw.get("reason") or raw.get("rationale"))
    if explicit_reason:
        return explicit_reason
    mapped_reason = EARNINGS_IMPORTANCE_REASON_BY_TICKER.get(ticker)
    if mapped_reason:
        return mapped_reason
    if "market_cap_headliner" in scope:
        return "Large market-cap earnings event with broad sector and index read-through."
    if "local_stock_pool" in scope:
        return "Ticker is in the current local stock pool and has a scheduled disclosure date inside the watch window."
    if "manual_focus" in scope:
        return "Ticker was manually forced into the earnings watchlist."
    if "industry_leader" in scope:
        return "Default institutional headliner; earnings can affect sector leadership and risk appetite."
    if ticker.endswith((".SH", ".SZ", ".BJ")):
        return "A-share scheduled disclosure date inside the watch window."
    return ""


def _calendar_event_operation_reminder(time_label: str, importance: str) -> str:
    if time_label == "\u76d8\u540e":
        return "After close: verify results, guidance, and management tone before deciding next-session follow-through."
    if time_label == "\u76d8\u524d":
        return "Before open: compare against expectations, then prioritize price and flow reaction after the open."
    if time_label == "\u76d8\u4e2d":
        return "Intraday: watch volatility and turnover strength; avoid chasing before the news is absorbed."
    if importance == "high":
        return "High-importance earnings nearby; wait for confirmation before adding exposure."
    return "Earnings date nearby; keep it on watch until results and price reaction confirm."


def _hard_event_operation_reminder(time_label: str, importance: str, category: str) -> str:
    category_label = display_status_text(category, "hard event")
    if importance in HIGH_EVENT_IMPORTANCE:
        return f"\u4e34\u8fd1\u9ad8\u5f71\u54cd{category_label}\uff0c\u5148\u786e\u8ba4\u7ed3\u679c\u3001\u5e02\u573a\u65b9\u5411\u548c\u53d7\u76ca/\u53d7\u635f\u94fe\u6761\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u8c03\u6574\u4ed3\u4f4d"
    if time_label:
        return f"{time_label}\u4e8b\u4ef6\u5148\u786e\u8ba4\u7ed3\u679c\u548c\u4ef7\u683c\u53cd\u5e94\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u8ddf\u8fdb"
    return "\u4e34\u8fd1\u4e8b\u4ef6\u7a97\u53e3\uff0c\u4fdd\u6301\u89c2\u5bdf\u4f4d\uff0c\u7b49\u7ed3\u679c\u548c\u5e02\u573a\u53cd\u5e94\u786e\u8ba4\u540e\u518d\u5904\u7406"


def collapse_calendar_events_by_company(events: list[dict[str, Any]], *, start_date: date) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for event in events:
        ticker = clean_text(event.get("ticker"))
        name = clean_text(event.get("name"))
        event_type = clean_text(event.get("event_type"))
        grouped.setdefault((ticker or name, name or ticker, event_type), []).append(event)

    collapsed: list[dict[str, Any]] = []
    for rows in grouped.values():
        sorted_rows = sorted(
            rows,
            key=lambda row: (
                clean_text(row.get("event_date")),
                clean_text(row.get("source")),
            ),
        )
        primary = dict(sorted_rows[0])
        dates = unique_strings([clean_text(row.get("event_date")) for row in sorted_rows])
        sources = unique_strings([clean_text(row.get("source")) for row in sorted_rows if clean_text(row.get("source"))])
        source_urls = unique_strings([clean_text(row.get("source_url")) for row in sorted_rows if clean_text(row.get("source_url"))])
        reasons = unique_strings([clean_text(row.get("importance_reason")) for row in sorted_rows if clean_text(row.get("importance_reason"))])
        scopes: list[str] = []
        for row in sorted_rows:
            scopes.extend(clean_string_list(row.get("watch_scope")))
        date_conflict = len(dates) > 1
        primary["source_count"] = len(sources) or len(sorted_rows)
        primary["sources"] = sources
        primary["source"] = ", ".join(sources) if sources else clean_text(primary.get("source"))
        primary["source_urls"] = source_urls
        if not clean_text(primary.get("source_url")) and source_urls:
            primary["source_url"] = source_urls[0]
        primary["watch_scope"] = unique_strings(scopes)
        if reasons:
            primary["importance_reason"] = "; ".join(reasons)
        primary["alternate_dates"] = dates[1:]
        primary["date_conflict"] = date_conflict
        primary["confidence"] = "conflicting" if date_conflict else "confirmed" if primary["source_count"] > 1 else "single_source"
        parsed_primary_date = parse_iso_date_value(primary.get("event_date"))
        if parsed_primary_date is not None:
            primary["days_until"] = (parsed_primary_date - start_date).days
        if date_conflict:
            conflict_note = (
                f"Date conflict: alternate source date(s) {', '.join(dates[1:])}; "
                "confirm official IR/exchange date before action."
            )
            primary["reminder"] = " ".join([conflict_note, clean_text(primary.get("reminder"))]).strip()
        collapsed.append(primary)
    return collapsed


def _calendar_extract_event_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in EARNINGS_CALENDAR_EVENT_KEYS:
            rows.extend(item for item in safe_list(payload.get(key)) if isinstance(item, dict))
        watch = safe_dict(payload.get("earnings_calendar_watch"))
        rows.extend(item for item in safe_list(watch.get("events")) if isinstance(item, dict))
        structured = safe_dict(payload.get("structured_catalyst_snapshot"))
        rows.extend(item for item in safe_list(structured.get("earnings_events")) if isinstance(item, dict))
        for bucket in ("top_picks", "directly_actionable", "priority_watchlist", "near_miss_candidates"):
            for stock in safe_list(payload.get(bucket)):
                if not isinstance(stock, dict):
                    continue
                structured = safe_dict(stock.get("structured_catalyst_snapshot"))
                for event in safe_list(structured.get("earnings_events")):
                    if isinstance(event, dict):
                        rows.append({**event, "ticker": stock.get("ticker"), "name": stock.get("name")})
                scheduled = clean_text(stock.get("scheduled_earnings_date"))
                if scheduled:
                    rows.append(
                        {
                            "ticker": stock.get("ticker"),
                            "name": stock.get("name"),
                            "date": scheduled,
                            "event_type": stock.get("report_type") or stock.get("event_type") or "\u8d22\u62a5",
                            "importance": stock.get("importance") or "high",
                            "source": stock.get("source") or "trading plan",
                        }
                    )
        return rows
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return rows


def _earnings_calendar_extract_source_event_count(payloads: list[Any] | None, fallback: int) -> int:
    total = 0
    found = False
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = []
        if payload_looks_like_earnings_calendar(payload):
            candidates.append(payload)
        watch = safe_dict(payload.get("earnings_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            summary = safe_dict(candidate.get("summary"))
            raw_count = clean_text(summary.get("source_event_count"))
            if not raw_count:
                continue
            try:
                source_event_count = int(float(raw_count.replace(",", "")))
            except ValueError:
                continue
            total += max(0, source_event_count)
            found = True
            break
    return total if found else fallback


def _earnings_calendar_extract_source_errors(payloads: list[Any] | None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = []
        if payload_looks_like_earnings_calendar(payload):
            candidates.append(payload)
        watch = safe_dict(payload.get("earnings_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            for raw_error in safe_list(candidate.get("source_errors")):
                if not isinstance(raw_error, dict):
                    continue
                row = {
                    "source": clean_text(raw_error.get("source") or raw_error.get("source_name")),
                    "source_url": clean_text(raw_error.get("source_url") or raw_error.get("url")),
                    "error": clean_text(raw_error.get("error") or raw_error.get("message")),
                }
                if not any(row.values()):
                    continue
                key = (row["source"], row["source_url"], row["error"])
                if key in seen:
                    continue
                seen.add(key)
                errors.append(row)
    return errors


def _earnings_calendar_extract_source_breakdown(payloads: list[Any] | None) -> list[dict[str, Any]]:
    breakdown: dict[str, int] = {}
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = []
        if payload_looks_like_earnings_calendar(payload):
            candidates.append(payload)
        watch = safe_dict(payload.get("earnings_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            rows = candidate.get("source_breakdown")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                source = clean_text(row.get("source"))
                if not source:
                    continue
                breakdown[source] = breakdown.get(source, 0) + int(row.get("source_event_count", 0) or 0)
    return [
        {"source": source, "source_event_count": count}
        for source, count in breakdown.items()
    ]


def _earnings_calendar_extract_source_window_summaries(payloads: list[Any] | None) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = []
        if payload_looks_like_earnings_calendar(payload):
            candidates.append(payload)
        watch = safe_dict(payload.get("earnings_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            for raw_row in safe_list(candidate.get("source_window_summaries")):
                if not isinstance(raw_row, dict):
                    continue
                row = {
                    "source": clean_text(raw_row.get("source") or raw_row.get("source_name")),
                    "market": clean_text(raw_row.get("market")),
                    "source_event_count": raw_row.get("source_event_count", 0),
                    "window_event_count": raw_row.get("window_event_count", 0),
                    "min_date": clean_text(raw_row.get("min_date")),
                    "max_date": clean_text(raw_row.get("max_date")),
                    "window_note": clean_text(raw_row.get("window_note") or raw_row.get("note")),
                }
                if not any(clean_text(value) for value in row.values()):
                    continue
                key = (
                    row["source"],
                    row["market"],
                    clean_text(row["min_date"]),
                    clean_text(row["max_date"]),
                    row["window_note"],
                )
                if key in seen:
                    continue
                seen.add(key)
                summaries.append(row)
    return summaries


def _earnings_calendar_source_health(payloads: list[Any] | None, errors: list[dict[str, str]]) -> str:
    if errors:
        return "degraded"
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = []
        if payload_looks_like_earnings_calendar(payload):
            candidates.append(payload)
        watch = safe_dict(payload.get("earnings_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            source_health = clean_text(candidate.get("source_health")).lower()
            if source_health and source_health not in {"ok", "covered"}:
                return source_health
    return "ok"


def build_earnings_calendar_watch(
    local_stock_pool: dict[str, Any],
    *,
    target_date: str,
    lookahead_days: int = DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS,
    payloads: list[Any] | None = None,
    watchlist_values: list[Any] | None = None,
) -> dict[str, Any]:
    start_date = parse_iso_date_value(target_date) or date.today()
    window_start, window_end = _calendar_event_window(start_date, lookahead_days)
    pool = safe_dict(local_stock_pool)
    pool_identities = _calendar_identity_map(pool.get("stocks") or [])
    focus_identities = _calendar_identity_map(watchlist_values or [])
    headliner_identities = _calendar_identity_map(list(DEFAULT_EARNINGS_CALENDAR_HEADLINERS))
    raw_events: list[dict[str, Any]] = []
    for payload in payloads or []:
        raw_events.extend(_calendar_extract_event_rows(payload))
    source_event_count = _earnings_calendar_extract_source_event_count(payloads, len(raw_events))
    source_errors = _earnings_calendar_extract_source_errors(payloads)
    source_breakdown = _earnings_calendar_extract_source_breakdown(payloads)
    source_window_summaries = _earnings_calendar_extract_source_window_summaries(payloads)
    source_health = _earnings_calendar_source_health(payloads, source_errors)
    normalized_events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in raw_events:
        ticker = normalize_workflow_display_ticker(raw.get("ticker") or raw.get("symbol") or raw.get("code"))
        name = clean_text(raw.get("name") or raw.get("company") or raw.get("company_name") or ticker)
        event_date = (
            parse_iso_date_value(raw.get("date"))
            or parse_iso_date_value(raw.get("event_date"))
            or parse_iso_date_value(raw.get("announce_date"))
            or parse_iso_date_value(raw.get("scheduled_date"))
            or parse_iso_date_value(raw.get("scheduled_earnings_date"))
        )
        if event_date is None or event_date < window_start or event_date > window_end:
            continue
        explicit_scope = clean_string_list(raw.get("watch_scope")) if isinstance(raw.get("watch_scope"), list) else clean_string_list([raw.get("watch_scope")])
        scope = _calendar_event_scope(
            ticker=ticker,
            name=name,
            focus_identities=focus_identities,
            headliner_identities=headliner_identities,
            explicit_scope=explicit_scope,
        )
        if ticker and (ticker.casefold() in pool_identities["ticker"] or name.casefold() in pool_identities["name"]):
            if "local_stock_pool" not in scope:
                scope.append("local_stock_pool")
        raw_importance = clean_text(raw.get("importance")).lower()
        unscoped_importance_allows_include = raw_importance in {"critical", "high", "important", "\u91cd\u70b9", "\u9ad8"}
        if not scope and not unscoped_importance_allows_include and not bool(raw.get("force_include")):
            continue
        event_type = (
            clean_text(raw.get("report_type"))
            or clean_text(raw.get("event_type"))
            or clean_text(raw.get("earnings_type"))
            or "\u8d22\u62a5"
        )
        importance = _calendar_event_importance_label(raw.get("importance"), scope)
        time_label = _calendar_event_time_label(raw.get("time") or raw.get("event_time") or raw.get("session"))
        importance_reason = _calendar_event_importance_reason(
            ticker=ticker,
            name=name,
            scope=scope,
            raw=raw,
        )
        unique_key = (ticker, name, event_date.isoformat())
        if unique_key in seen:
            continue
        seen.add(unique_key)
        normalized_events.append(
            {
                "ticker": ticker,
                "name": name,
                "event_date": event_date.isoformat(),
                "days_until": (event_date - start_date).days,
                "time": time_label,
                "event_type": event_type,
                "importance": importance,
                "watch_scope": scope,
                "source": clean_text(raw.get("source") or raw.get("source_name") or raw.get("source_url")),
                "source_url": clean_text(raw.get("source_url") or raw.get("url")),
                "importance_reason": importance_reason,
                "reminder": clean_text(raw.get("reminder") or raw.get("operation_reminder")) or _calendar_event_operation_reminder(time_label, importance),
                "related_industry": clean_text(raw.get("related_industry") or raw.get("industry") or raw.get("theme")),
            }
        )

    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        importance_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(clean_text(row.get("importance")).lower(), 4)
        scope = row.get("watch_scope") if isinstance(row.get("watch_scope"), list) else []
        scope_rank = 0 if "manual_focus" in scope else 1 if "local_stock_pool" in scope else 2 if "industry_leader" in scope else 3 if "market_cap_headliner" in scope else 4
        return (
            clean_text(row.get("event_date")),
            importance_rank,
            scope_rank,
            clean_text(row.get("ticker")),
            clean_text(row.get("name")),
        )

    normalized_events = collapse_calendar_events_by_company(normalized_events, start_date=start_date)
    normalized_events.sort(key=sort_key)
    summary = {
        "event_count": len(normalized_events),
        "source_event_count": source_event_count,
        "window_days": max(0, int(lookahead_days)),
        "local_stock_pool_match_count": sum(1 for row in normalized_events if "local_stock_pool" in (row.get("watch_scope") or [])),
        "manual_focus_count": sum(1 for row in normalized_events if "manual_focus" in (row.get("watch_scope") or [])),
        "industry_leader_count": sum(1 for row in normalized_events if "industry_leader" in (row.get("watch_scope") or [])),
        "market_cap_headliner_count": sum(1 for row in normalized_events if "market_cap_headliner" in (row.get("watch_scope") or [])),
        "date_conflict_count": sum(1 for row in normalized_events if bool(row.get("date_conflict"))),
        "multi_source_confirmed_count": sum(1 for row in normalized_events if clean_text(row.get("confidence")) == "confirmed"),
        "source_error_count": len(source_errors),
    }
    watch = {
        "schema_version": "earnings_calendar_watch/v1",
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
        "lookahead_days": max(0, int(lookahead_days)),
        "events": normalized_events,
        "summary": summary,
        "source_health": source_health,
    }
    if source_breakdown:
        watch["source_breakdown"] = source_breakdown
    if source_window_summaries:
        watch["source_window_summaries"] = source_window_summaries
    if source_errors:
        watch["source_errors"] = source_errors
    return watch


def _event_calendar_extract_event_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in EVENT_CALENDAR_EVENT_KEYS:
            rows.extend(item for item in safe_list(payload.get(key)) if isinstance(item, dict))
        watch = safe_dict(payload.get("event_calendar_watch"))
        rows.extend(item for item in safe_list(watch.get("events")) if isinstance(item, dict))
        return rows
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return rows


def _event_calendar_extract_source_errors(payloads: list[Any] | None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = [payload]
        watch = safe_dict(payload.get("event_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            if candidate is payload and not payload_looks_like_event_calendar(candidate):
                continue
            for raw_error in safe_list(candidate.get("source_errors")):
                if not isinstance(raw_error, dict):
                    continue
                row = {
                    "source": clean_text(raw_error.get("source") or raw_error.get("source_name")),
                    "source_url": clean_text(raw_error.get("source_url") or raw_error.get("url")),
                    "error": clean_text(raw_error.get("error") or raw_error.get("message")),
                }
                if not any(row.values()):
                    continue
                key = (row["source"], row["source_url"], row["error"])
                if key in seen:
                    continue
                seen.add(key)
                errors.append(row)
    return errors


def _event_calendar_extract_source_breakdown(payloads: list[Any] | None) -> list[dict[str, Any]]:
    breakdown: dict[str, int] = {}
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = [payload]
        watch = safe_dict(payload.get("event_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            if candidate is payload and not payload_looks_like_event_calendar(candidate):
                continue
            rows = candidate.get("source_breakdown")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                source = clean_text(row.get("source"))
                if not source:
                    continue
                breakdown[source] = breakdown.get(source, 0) + int(row.get("source_event_count", 0) or 0)
    return [
        {"source": source, "source_event_count": count}
        for source, count in breakdown.items()
    ]


def _event_calendar_extract_source_event_count(payloads: list[Any] | None, fallback: int) -> int:
    total = 0
    found = False
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = []
        if payload_looks_like_event_calendar(payload):
            candidates.append(payload)
        watch = safe_dict(payload.get("event_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            summary = safe_dict(candidate.get("summary"))
            raw_count = clean_text(summary.get("source_event_count"))
            if not raw_count:
                continue
            try:
                source_event_count = int(float(raw_count.replace(",", "")))
            except ValueError:
                continue
            total += max(0, source_event_count)
            found = True
            break
    return total if found else fallback


def _event_calendar_source_health(payloads: list[Any] | None, errors: list[dict[str, str]]) -> str:
    if errors:
        return "degraded"
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        candidates = [payload]
        watch = safe_dict(payload.get("event_calendar_watch"))
        if watch:
            candidates.append(watch)
        for candidate in candidates:
            if candidate is payload and not payload_looks_like_event_calendar(candidate):
                continue
            source_health = clean_text(candidate.get("source_health")).lower()
            if source_health and source_health not in {"ok", "covered"}:
                return source_health
    return "ok"


def _event_related_identity_tokens(raw: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("ticker", "symbol", "code", "related_ticker"):
        if clean_text(raw.get(key)):
            values.append(raw.get(key))
    for key in ("related_tickers", "tickers", "companies", "related_companies"):
        values.extend(safe_list(raw.get(key)))
    tokens: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            tokens.update(_calendar_identity_tokens(value.get("ticker") or value.get("symbol") or value.get("code")))
            tokens.update(_calendar_identity_tokens(value.get("name") or value.get("company") or value.get("company_name")))
        else:
            tokens.update(_calendar_identity_tokens(value))
    return tokens


def _event_related_company_terms(raw: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("related_companies", "companies", "related_company", "company", "company_name"):
        if key in {"related_companies", "companies"}:
            values.extend(safe_list(raw.get(key)))
        elif clean_text(raw.get(key)):
            values.append(raw.get(key))
    for key in ("related_tickers", "tickers"):
        values.extend(safe_list(raw.get(key)))
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            parts = [
                value.get("ticker"),
                value.get("symbol"),
                value.get("code"),
                value.get("name"),
                value.get("company"),
                value.get("company_name"),
            ]
            for part in parts:
                text = clean_text(part)
                if not text:
                    continue
                for item in re.split(r"[,\u3001;\uff1b|]+", text):
                    normalized = clean_text(item)
                    if not normalized:
                        continue
                    if len(normalized) < 2 and not re.search(r"[\u4e00-\u9fff]", normalized):
                        continue
                    key = normalized.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    terms.append(normalized)
            continue
        text = clean_text(value)
        if not text:
            continue
        for item in re.split(r"[,\u3001;\uff1b|]+", text):
            normalized = clean_text(item)
            if not normalized:
                continue
            if len(normalized) < 2 and not re.search(r"[\u4e00-\u9fff]", normalized):
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            terms.append(normalized)
    return terms


def _event_beneficiary_stocks(raw: dict[str, Any], stocks: list[Any]) -> list[dict[str, Any]]:
    terms = [term for term in _event_related_company_terms(raw) if term]
    if not terms:
        return []
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        ticker = normalize_workflow_display_ticker(stock.get("ticker"))
        name = clean_text(stock.get("name") or ticker)
        groups = clean_string_list(stock.get("groups"))
        tags = clean_string_list(stock.get("tags"))
        notes = clean_text(stock.get("notes"))
        field_texts = {
            "groups": " ".join(groups),
            "tags": " ".join(tags),
            "notes": notes,
        }
        match_fields: list[str] = []
        matched_terms: list[str] = []
        for field, field_text in field_texts.items():
            normalized_field = clean_text(field_text).casefold()
            if not normalized_field:
                continue
            for term in terms:
                normalized_term = clean_text(term).casefold()
                if not normalized_term:
                    continue
                if normalized_term in normalized_field:
                    match_fields.append(field)
                    matched_terms.append(term)
        if not match_fields:
            stock_tokens = _calendar_identity_tokens(ticker) | _calendar_identity_tokens(name)
            raw_tokens = _event_related_identity_tokens(raw)
            if stock_tokens & raw_tokens:
                match_fields.append("identity")
                matched_terms.extend(sorted(stock_tokens & raw_tokens))
        if not match_fields:
            continue
        unique_key = ticker or name
        if unique_key and unique_key in seen:
            continue
        if unique_key:
            seen.add(unique_key)
        matches.append(
            {
                "ticker": ticker,
                "name": name,
                "match_fields": unique_strings(match_fields),
                "matched_terms": unique_strings(matched_terms),
            }
        )
    return matches


def _event_importance_label(value: Any) -> str:
    text = clean_text(value).lower()
    if text in {"critical", "systemic", "high", "important"}:
        return "critical" if text in {"critical", "systemic"} else "high"
    if text in {"medium", "normal", "watch"}:
        return "medium"
    if text in {"low", "minor"}:
        return "low"
    return text or "medium"


def build_event_calendar_watch(
    local_stock_pool: dict[str, Any],
    *,
    target_date: str,
    lookahead_days: int = DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS,
    payloads: list[Any] | None = None,
    watchlist_values: list[Any] | None = None,
) -> dict[str, Any]:
    start_date = parse_iso_date_value(target_date) or date.today()
    window_start, window_end = _calendar_event_window(start_date, lookahead_days)
    pool = safe_dict(local_stock_pool)
    pool_stocks = [row for row in safe_list(pool.get("stocks")) if isinstance(row, dict)]
    pool_identities = _calendar_identity_map(pool_stocks)
    focus_identities = _calendar_identity_map(watchlist_values or [])
    raw_events: list[dict[str, Any]] = []
    for payload in payloads or []:
        raw_events.extend(_event_calendar_extract_event_rows(payload))
    source_errors = _event_calendar_extract_source_errors(payloads)
    source_health = _event_calendar_source_health(payloads, source_errors)
    source_event_count = _event_calendar_extract_source_event_count(payloads, len(raw_events))
    source_breakdown = _event_calendar_extract_source_breakdown(payloads)

    normalized_events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_events:
        event_date = (
            parse_iso_date_value(raw.get("date"))
            or parse_iso_date_value(raw.get("event_date"))
            or parse_iso_date_value(raw.get("scheduled_date"))
        )
        if event_date is None or event_date < window_start or event_date > window_end:
            continue
        title = (
            clean_text(raw.get("title"))
            or clean_text(raw.get("event"))
            or clean_text(raw.get("event_type"))
            or clean_text(raw.get("name"))
            or "scheduled event"
        )
        time_label = clean_text(raw.get("time") or raw.get("event_time"))
        category = clean_text(raw.get("category") or raw.get("event_category") or raw.get("type")) or "hard_event"
        importance = _event_importance_label(raw.get("importance"))
        related_tokens = _event_related_identity_tokens(raw)
        scope = clean_string_list(raw.get("watch_scope")) if isinstance(raw.get("watch_scope"), list) else clean_string_list([raw.get("watch_scope")])
        if importance in HIGH_EVENT_IMPORTANCE:
            scope.append("high_importance")
        beneficiary_stocks = _event_beneficiary_stocks(raw, pool_stocks)
        if related_tokens & pool_identities["ticker"] or related_tokens & pool_identities["name"] or beneficiary_stocks:
            scope.append("local_stock_pool")
        if related_tokens & focus_identities["ticker"] or related_tokens & focus_identities["name"]:
            scope.append("manual_focus")
        scope = unique_strings(scope)
        if not scope and not bool(raw.get("force_include")):
            continue
        unique_key = (title, event_date.isoformat())
        if unique_key in seen:
            continue
        seen.add(unique_key)
        related_tickers = [
            normalize_workflow_display_ticker(value)
            for value in clean_string_list(raw.get("related_tickers") or raw.get("tickers"))
            if clean_text(value)
        ]
        normalized_events.append(
            {
                "title": title,
                "event_date": event_date.isoformat(),
                "days_until": (event_date - start_date).days,
                "time": time_label,
                "category": category,
                "importance": importance,
                "watch_scope": scope,
                "source": clean_text(raw.get("source") or raw.get("source_name") or raw.get("source_url")),
                "source_url": clean_text(raw.get("source_url") or raw.get("url")),
                "reminder": clean_text(raw.get("reminder") or raw.get("operation_reminder"))
                or _hard_event_operation_reminder(time_label, importance, category),
                "impact_scope": clean_string_list(raw.get("impact_scope")),
                "related_tickers": unique_strings(related_tickers),
                "related_companies": clean_string_list(raw.get("related_companies") or raw.get("companies")),
                "importance_reason": clean_text(raw.get("importance_reason") or raw.get("reason") or raw.get("rationale")),
                "source_count": int(raw.get("source_count", 0) or 0),
                "sources": clean_string_list(raw.get("sources")),
                "source_urls": clean_string_list(raw.get("source_urls")),
                "beneficiary_stocks": beneficiary_stocks,
            }
        )

    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        importance_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(clean_text(row.get("importance")).lower(), 4)
        return (
            clean_text(row.get("event_date")),
            importance_rank,
            clean_text(row.get("title")),
        )

    normalized_events.sort(key=sort_key)
    summary = {
        "event_count": len(normalized_events),
        "source_event_count": source_event_count,
        "window_days": max(0, int(lookahead_days)),
        "local_stock_pool_match_count": sum(1 for row in normalized_events if "local_stock_pool" in (row.get("watch_scope") or [])),
        "manual_focus_count": sum(1 for row in normalized_events if "manual_focus" in (row.get("watch_scope") or [])),
        "high_importance_count": sum(1 for row in normalized_events if "high_importance" in (row.get("watch_scope") or [])),
        "beneficiary_stock_match_count": sum(len(safe_list(row.get("beneficiary_stocks"))) for row in normalized_events),
        "source_error_count": len(source_errors),
    }
    watch = {
        "schema_version": "event_calendar_watch/v1",
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
        "lookahead_days": max(0, int(lookahead_days)),
        "events": normalized_events,
        "summary": summary,
        "source_health": source_health,
    }
    if source_breakdown:
        watch["source_breakdown"] = source_breakdown
    if source_errors:
        watch["source_errors"] = source_errors
    return watch


__all__ = [
    "DEFAULT_EARNINGS_CALENDAR_HEADLINERS",
    "DEFAULT_EARNINGS_CALENDAR_LOOKAHEAD_DAYS",
    "EARNINGS_CALENDAR_EVENT_KEYS",
    "EARNINGS_CALENDAR_WATCHLIST_KEYS",
    "EVENT_CALENDAR_EVENT_KEYS",
    "EVENT_CALENDAR_WATCHLIST_KEYS",
    "HIGH_EVENT_IMPORTANCE",
    "build_earnings_calendar_watch",
    "build_event_calendar_watch",
    "collapse_calendar_events_by_company",
    "parse_iso_date_value",
    "payload_looks_like_earnings_calendar",
    "payload_looks_like_event_calendar",
]
