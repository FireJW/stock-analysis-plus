#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCHEMA_VERSION = "earnings_calendar_source/v1"
NASDAQ_EARNINGS_API_URL = "https://api.nasdaq.com/api/calendar/earnings"
US_MARKET_CAP_HEADLINER_THRESHOLD = 100_000_000_000
US_IMPORTANCE_REASON_BY_TICKER = {
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
DISCLOSURE_DATE_COLUMNS = (
    "实际披露时间",
    "实际披露日期",
    "实际披露",
    "三次变更日期",
    "二次变更日期",
    "一次变更日期",
    "首次预约时间",
    "预约披露时间",
    "预约披露日期",
)
NAME_COLUMNS = ("股票简称", "证券简称", "简称", "name", "company_name")
CODE_COLUMNS = ("股票代码", "证券代码", "代码", "ticker", "symbol", "code")
FOCUS_SOURCE_KEYS = (
    "earnings_calendar_watchlist",
    "earnings_calendar_focus",
    "earnings_calendar_focus_tickers",
    "key_earnings_companies",
    "industry_head_earnings_watchlist",
)
FOCUS_STOCK_BUCKETS = (
    "stocks",
    "top_picks",
    "directly_actionable",
    "priority_watchlist",
    "near_miss_candidates",
    "setup_launch_candidates",
)
Fetcher = Callable[[str], list[dict[str, Any]]]


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def parse_date_value(value: Any) -> date | None:
    text = clean_text(value)
    if not text or text.lower() in {"nat", "none", "nan", "-"}:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def normalize_ticker(value: Any) -> str:
    text = clean_text(value).upper().replace(" ", "")
    if not text:
        return ""
    if text.endswith((".SH", ".SZ", ".BJ", ".US", ".HK")):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6:
        if digits.startswith(("6", "9")):
            return f"{digits}.SH"
        if digits.startswith(("8", "4")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"
    return text


def normalize_us_ticker(value: Any) -> str:
    text = clean_text(value).upper().replace(" ", "")
    if not text:
        return ""
    if text.endswith(".US"):
        return text
    if "." in text:
        return text
    return f"{text}.US"


def parse_market_cap_value(value: Any) -> float:
    text = clean_text(value).replace(",", "")
    if not text:
        return 0.0
    multiplier = 1.0
    suffix = text[-1:].upper()
    if suffix == "T":
        multiplier = 1_000_000_000_000.0
        text = text[:-1]
    elif suffix == "B":
        multiplier = 1_000_000_000.0
        text = text[:-1]
    elif suffix == "M":
        multiplier = 1_000_000.0
        text = text[:-1]
    number_text = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    if not number_text:
        return 0.0
    try:
        return float(number_text) * multiplier
    except ValueError:
        return 0.0


def us_earnings_importance_reason(
    *,
    ticker: str,
    name: str,
    market_cap: Any,
    watch_scope: list[str],
) -> str:
    reason = US_IMPORTANCE_REASON_BY_TICKER.get(ticker)
    if reason:
        return reason
    market_cap_value = parse_market_cap_value(market_cap)
    if market_cap_value >= US_MARKET_CAP_HEADLINER_THRESHOLD:
        company = name or ticker
        return f"{company} is a mega-cap earnings event with broad sector and index read-through."
    if "industry_leader" in watch_scope:
        return "Default institutional headliner; earnings can affect sector leadership and risk appetite."
    if "market_cap_headliner" in watch_scope:
        return "Large market-cap earnings event with broad sector read-through."
    return ""


def normalize_focus_ticker(value: Any) -> str:
    text = clean_text(value).upper().replace(" ", "")
    if not text:
        return ""
    normalized = normalize_ticker(text)
    if "." not in normalized and normalized.isalpha() and 1 <= len(normalized) <= 5:
        return normalize_us_ticker(normalized)
    return normalized


def append_unique_text(values: list[str], seen: set[str], value: Any) -> None:
    text = clean_text(value)
    if not text:
        return
    key = text.casefold()
    if key in seen:
        return
    seen.add(key)
    values.append(text)


def append_focus_record(values: list[str], seen: set[str], value: Any) -> None:
    if isinstance(value, str):
        append_unique_text(values, seen, value)
        return
    if not isinstance(value, dict):
        return
    ticker = normalize_focus_ticker(
        value.get("ticker")
        or value.get("symbol")
        or value.get("code")
        or value.get("security_code")
    )
    append_unique_text(values, seen, ticker)
    append_unique_text(
        values,
        seen,
        value.get("name")
        or value.get("company_name")
        or value.get("stock_name")
        or value.get("security_name"),
    )


def append_focus_collection(values: list[str], seen: set[str], value: Any) -> None:
    if isinstance(value, list):
        for item in value:
            append_focus_record(values, seen, item)
        return
    append_focus_record(values, seen, value)


def extract_focus_values(payload: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        nested = value.get("local_stock_pool")
        if isinstance(nested, (dict, list)):
            visit(nested)

        for key in FOCUS_SOURCE_KEYS:
            if key in value:
                append_focus_collection(values, seen, value.get(key))

        for key in FOCUS_STOCK_BUCKETS:
            if key in value:
                append_focus_collection(values, seen, value.get(key))

        for nested_key in ("month_end_request", "request", "trading_plan_result"):
            nested = value.get(nested_key)
            if isinstance(nested, (dict, list)):
                visit(nested)

    visit(payload)
    return values


def load_focus_values_from_paths(paths: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        for value in extract_focus_values(payload):
            append_unique_text(values, seen, value)
    return values


def unique_focus_values(values: list[Any]) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        append_unique_text(unique_values, seen, value)
    return unique_values


def expand_focus_records(values: list[Any] | None) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        append_focus_record(expanded, seen, value)
    return expanded


def discover_focus_source_paths(output_path: str | Path) -> list[str]:
    root = Path(output_path).expanduser().parent
    candidates = (
        "local-stock-pool-manager-package.json",
        "trading-plan-result.json",
        "month-end-shortlist-result.json",
        "local_stock_pool_manager_package.json",
        "trading_plan_result.json",
        "month_end_shortlist_result.json",
    )
    discovered: list[str] = []
    for name in candidates:
        path = root / name
        if path.exists():
            discovered.append(str(path))
    return discovered


def resolve_focus_values(
    *,
    output_path: str | Path,
    focus_source_paths: list[str],
    focus_payloads: list[Any] | None = None,
    explicit_focus: list[Any],
) -> list[str]:
    source_paths = unique_focus_values([*focus_source_paths, *discover_focus_source_paths(output_path)])
    payload_focus: list[str] = []
    for payload in focus_payloads or []:
        payload_focus.extend(extract_focus_values(payload))
    return unique_focus_values([*load_focus_values_from_paths(source_paths), *payload_focus, *explicit_focus])


def period_label(period: str) -> str:
    text = clean_text(period)
    if text.endswith("0331"):
        return f"{text[:4]}Q1 report scheduled disclosure"
    if text.endswith("0630"):
        return f"{text[:4]}H1 report scheduled disclosure"
    if text.endswith("0930"):
        return f"{text[:4]}Q3 report scheduled disclosure"
    if text.endswith("1231"):
        return f"{text[:4]} annual report scheduled disclosure"
    if "一季" in text:
        return f"{text[:4]}Q1 report scheduled disclosure"
    if "半年" in text or "中报" in text:
        return f"{text[:4]}H1 report scheduled disclosure"
    if "三季" in text:
        return f"{text[:4]}Q3 report scheduled disclosure"
    if "年报" in text:
        return f"{text[:4]} annual report scheduled disclosure"
    return f"{text} report scheduled disclosure" if text else "report scheduled disclosure"


def first_field(row: dict[str, Any], columns: tuple[str, ...]) -> str:
    for column in columns:
        text = clean_text(row.get(column))
        if text:
            return text
    return ""


def latest_disclosure_date(row: dict[str, Any]) -> date | None:
    for column in DISCLOSURE_DATE_COLUMNS:
        parsed = parse_date_value(row.get(column))
        if parsed is not None:
            return parsed
    return None


def normalize_a_share_disclosure_rows(
    rows: list[dict[str, Any]],
    *,
    period: str,
    source: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_date = latest_disclosure_date(row)
        if event_date is None:
            continue
        ticker = normalize_ticker(first_field(row, CODE_COLUMNS))
        name = first_field(row, NAME_COLUMNS) or ticker
        if not ticker and not name:
            continue
        events.append(
            {
                "ticker": ticker,
                "name": name,
                "date": event_date.isoformat(),
                "time": "postclose",
                "event_type": period_label(period),
                "importance": "medium",
                "source": source,
            }
        )
    return events


def nasdaq_time_label(value: Any) -> str:
    text = clean_text(value).lower()
    if any(token in text for token in ("after", "time-after-hours", "post")):
        return "after_market"
    if any(token in text for token in ("before", "pre", "time-pre-market")):
        return "before_market"
    if "not-supplied" in text or "not supplied" in text:
        return ""
    return clean_text(value)


def nasdaq_earnings_source_url(event_date: date) -> str:
    return f"{NASDAQ_EARNINGS_API_URL}?{urlencode({'date': event_date.isoformat()})}"


def normalize_nasdaq_earnings_rows(
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = normalize_us_ticker(row.get("symbol") or row.get("ticker"))
        name = clean_text(row.get("name") or row.get("companyName") or ticker)
        event_date = (
            parse_date_value(row.get("earningsDate"))
            or parse_date_value(row.get("date"))
            or parse_date_value(row.get("reportDate"))
        )
        if event_date is None or not ticker:
            continue
        fiscal_period = clean_text(row.get("fiscalQuarterEnding") or row.get("fiscalPeriod"))
        event_type = f"earnings {fiscal_period}" if fiscal_period else "earnings"
        metadata = {
            "eps_forecast": clean_text(row.get("epsForecast")),
            "no_of_estimates": clean_text(row.get("noOfEsts") or row.get("noOfEstimates")),
            "market_cap": clean_text(row.get("marketCap")),
        }
        watch_scope: list[str] = []
        importance = "medium"
        if parse_market_cap_value(metadata["market_cap"]) >= US_MARKET_CAP_HEADLINER_THRESHOLD:
            watch_scope.append("market_cap_headliner")
            importance = "high"
        event: dict[str, Any] = {
            "ticker": ticker,
            "name": name,
            "date": event_date.isoformat(),
            "time": nasdaq_time_label(row.get("time")),
            "event_type": event_type,
            "importance": importance,
            "source": source,
            "source_url": nasdaq_earnings_source_url(event_date),
            "metadata": {key: value for key, value in metadata.items() if value},
        }
        if watch_scope:
            event["watch_scope"] = watch_scope
            reason = us_earnings_importance_reason(
                ticker=ticker,
                name=name,
                market_cap=metadata["market_cap"],
                watch_scope=watch_scope,
            )
            if reason:
                event["importance_reason"] = reason
        events.append(event)
    return events


def rows_with_default_earnings_date(rows: list[dict[str, Any]], default_date: str) -> list[dict[str, Any]]:
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        enriched = dict(row)
        if not any(clean_text(enriched.get(key)) for key in ("earningsDate", "date", "reportDate")):
            enriched["date"] = default_date
        enriched_rows.append(enriched)
    return enriched_rows


def identity_tokens(value: Any) -> set[str]:
    text = clean_text(value)
    if not text:
        return set()
    ticker = normalize_ticker(text)
    tokens = {text.casefold(), text.upper(), ticker.casefold(), ticker.upper()}
    compact = text.upper().replace(" ", "")
    if "." not in compact and compact.isalpha() and 1 <= len(compact) <= 5:
        us_ticker = normalize_us_ticker(compact)
        tokens.update({us_ticker.casefold(), us_ticker})
    return tokens


def matches_focus(event: dict[str, Any], focus_values: list[Any]) -> bool:
    if not focus_values:
        return True
    return matches_identity_values(event, focus_values)


def matches_identity_values(event: dict[str, Any], values: list[Any]) -> bool:
    event_tokens = identity_tokens(event.get("ticker")) | identity_tokens(event.get("name"))
    value_tokens: set[str] = set()
    for value in values:
        value_tokens.update(identity_tokens(value))
    return bool(event_tokens & value_tokens)


def normalize_watch_scope(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    scopes: list[str] = []
    seen: set[str] = set()
    for item in values:
        append_unique_text(scopes, seen, item)
    return scopes


def calendar_watch_scope(
    event: dict[str, Any],
    *,
    focus_values: list[Any],
    headliner_values: list[Any],
) -> list[str]:
    scope = normalize_watch_scope(event.get("watch_scope"))
    if focus_values and matches_identity_values(event, focus_values):
        append_unique_text(scope, {item.casefold() for item in scope}, "manual_focus")
    if headliner_values and matches_identity_values(event, headliner_values):
        append_unique_text(scope, {item.casefold() for item in scope}, "industry_leader")
    return scope


def earnings_importance_reason(
    event: dict[str, Any],
    *,
    ticker: str,
    name: str,
    watch_scope: list[str],
) -> str:
    explicit_reason = clean_text(event.get("importance_reason") or event.get("reason") or event.get("rationale"))
    if explicit_reason:
        return explicit_reason
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    if ticker.endswith(".US"):
        return us_earnings_importance_reason(
            ticker=ticker,
            name=name,
            market_cap=metadata.get("market_cap"),
            watch_scope=watch_scope,
        )
    if "local_stock_pool" in watch_scope:
        return "A-share in the current local stock pool has a scheduled disclosure date inside the watch window."
    if "industry_leader" in watch_scope:
        return "A-share institutional headliner has a scheduled disclosure date inside the watch window."
    if "manual_focus" in watch_scope:
        return "Manually forced A-share earnings focus item."
    return ""


def build_earnings_calendar_payload(
    events: list[dict[str, Any]],
    *,
    target_date: str,
    lookahead_days: int = 7,
    focus_values: list[Any] | None = None,
    headliner_values: list[Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    start_date = parse_date_value(target_date) or date.today()
    end_date = start_date + timedelta(days=max(0, int(lookahead_days)))
    resolved_focus_values = expand_focus_records(focus_values)
    resolved_headliner_values = expand_focus_records(headliner_values)
    has_scope_filter = bool(resolved_focus_values or resolved_headliner_values)
    filtered: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        event_date = parse_date_value(event.get("date") or event.get("event_date"))
        if event_date is None or event_date < start_date or event_date > end_date:
            continue
        watch_scope = calendar_watch_scope(
            event,
            focus_values=resolved_focus_values,
            headliner_values=resolved_headliner_values,
        )
        if has_scope_filter and not watch_scope:
            continue
        ticker = normalize_ticker(event.get("ticker") or event.get("symbol") or event.get("code"))
        name = clean_text(event.get("name") or event.get("company_name") or ticker)
        key = (ticker, name, event_date.isoformat())
        if key in seen:
            continue
        seen.add(key)
        normalized = {
            "ticker": ticker,
            "name": name,
            "date": event_date.isoformat(),
            "time": clean_text(event.get("time") or event.get("event_time")),
            "event_type": clean_text(event.get("event_type") or event.get("report_type") or "report scheduled disclosure"),
            "importance": clean_text(event.get("importance")) or "medium",
            "source": clean_text(event.get("source")),
        }
        source_url = clean_text(event.get("source_url") or event.get("url"))
        if source_url:
            normalized["source_url"] = source_url
        metadata = event.get("metadata")
        if isinstance(metadata, dict) and metadata:
            normalized["metadata"] = metadata
        if watch_scope:
            normalized["watch_scope"] = watch_scope
        importance_reason = earnings_importance_reason(
            event,
            ticker=ticker,
            name=name,
            watch_scope=watch_scope,
        )
        if importance_reason:
            normalized["importance_reason"] = importance_reason
        filtered.append(normalized)
    filtered.sort(key=lambda item: (item["date"], item["ticker"], item["name"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "target_date": start_date.isoformat(),
        "lookahead_days": max(0, int(lookahead_days)),
        "window_end_date": end_date.isoformat(),
        "earnings_calendar_events": filtered,
        "summary": {
            "event_count": len(filtered),
            "source_event_count": len(events),
            "focus_count": len(resolved_focus_values),
            "headliner_count": len(resolved_headliner_values),
        },
    }


def dataframe_to_records(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        records = value.to_dict(orient="records")
        return records if isinstance(records, list) else []
    return value if isinstance(value, list) else []


def fetch_akshare_eastmoney_rows(period: str) -> list[dict[str, Any]]:
    if importlib.util.find_spec("akshare") is None:
        raise RuntimeError("akshare package is not available")
    import akshare as ak  # type: ignore[import-not-found]

    return dataframe_to_records(ak.stock_yysj_em(date=period))


def extract_nasdaq_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            rows = data.get("rows")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return payload if isinstance(payload, list) else []


def fetch_nasdaq_earnings_rows(target_date: str) -> list[dict[str, Any]]:
    query = urlencode({"date": target_date})
    request = Request(
        f"{NASDAQ_EARNINGS_API_URL}?{query}",
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 Codex-EarningsCalendar/1.0",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/market-activity/earnings",
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return extract_nasdaq_rows(payload)


def fetch_rows_with_retries(
    fetcher: Fetcher,
    target_date: str,
    *,
    attempts: int = 3,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    for _attempt in range(max(1, int(attempts))):
        try:
            return fetcher(target_date), []
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
    return [], errors


def date_range(start_date: str, lookahead_days: int) -> list[str]:
    start = parse_date_value(start_date) or date.today()
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range(max(0, int(lookahead_days)) + 1)
    ]


def a_share_period_candidates_for_month(day: date) -> list[str]:
    year = day.year
    if day.month <= 3:
        return [f"{year - 1}1231"]
    if day.month <= 5:
        return [f"{year}0331", f"{year - 1}1231"]
    if day.month <= 7:
        return [f"{year}0630", f"{year}0331"]
    if day.month <= 9:
        return [f"{year}0630"]
    if day.month <= 11:
        return [f"{year}0930"]
    return [f"{year}1231", f"{year}0930"]


def default_a_share_periods(*, target_date: str, lookahead_days: int) -> list[str]:
    start = parse_date_value(target_date) or date.today()
    end = start + timedelta(days=max(0, int(lookahead_days)))
    periods: list[str] = []
    seen: set[str] = set()
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        for period in a_share_period_candidates_for_month(day):
            if period in seen:
                continue
            seen.add(period)
            periods.append(period)
    return periods


def resolve_a_share_periods(
    *,
    explicit_periods: list[str],
    target_date: str,
    lookahead_days: int,
) -> list[str]:
    cleaned_explicit = unique_focus_values(explicit_periods)
    if cleaned_explicit:
        return cleaned_explicit
    return default_a_share_periods(target_date=target_date, lookahead_days=lookahead_days)


def build_source_window_summary(
    events: list[dict[str, Any]],
    *,
    source: str,
    market: str,
    target_date: str,
    lookahead_days: int,
    periods: list[str] | None = None,
) -> dict[str, Any]:
    start_date = parse_date_value(target_date) or date.today()
    end_date = start_date + timedelta(days=max(0, int(lookahead_days)))
    event_dates = [
        parsed_date
        for parsed_date in (parse_date_value(event.get("date") or event.get("event_date")) for event in events)
        if parsed_date is not None
    ]
    window_dates = [event_date for event_date in event_dates if start_date <= event_date <= end_date]
    before_dates = sorted(event_date for event_date in event_dates if event_date < start_date)
    future_dates = sorted(event_date for event_date in event_dates if event_date > end_date)
    summary: dict[str, Any] = {
        "source": source,
        "market": market,
        "source_event_count": len(event_dates),
        "window_event_count": len(window_dates),
        "window_start": start_date.isoformat(),
        "window_end": end_date.isoformat(),
    }
    if periods:
        summary["periods"] = periods
    if event_dates:
        summary["min_date"] = min(event_dates).isoformat()
        summary["max_date"] = max(event_dates).isoformat()
    if before_dates:
        summary["latest_date_before_window"] = before_dates[-1].isoformat()
    if future_dates:
        summary["next_date_after_window"] = future_dates[0].isoformat()
    if market == "CN" and not window_dates:
        if event_dates:
            summary["window_note"] = (
                "No A-share scheduled disclosure dates in the next "
                f"{max(0, int(lookahead_days))} days; latest parsed date is {max(event_dates).isoformat()}."
            )
        else:
            summary["window_note"] = "No A-share scheduled disclosure rows parsed from the source."
    return summary


def collect_a_share_earnings_calendar(
    *,
    periods: list[str],
    target_date: str,
    lookahead_days: int,
    focus_values: list[str] | None = None,
    headliner_values: list[Any] | None = None,
    fetcher: Fetcher = fetch_akshare_eastmoney_rows,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    source_errors: list[dict[str, str]] = []
    for period in periods:
        try:
            rows = fetcher(period)
        except Exception as exc:  # noqa: BLE001
            source_errors.append(
                {
                    "source": "akshare.stock_yysj_em",
                    "period": period,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        events.extend(
            normalize_a_share_disclosure_rows(
                rows,
                period=period,
                source="akshare.stock_yysj_em",
            )
        )
    payload = build_earnings_calendar_payload(
        events,
        target_date=target_date,
        lookahead_days=lookahead_days,
        focus_values=focus_values or [],
        headliner_values=headliner_values or [],
    )
    payload["source_breakdown"] = [
        {
            "source": "akshare.stock_yysj_em",
            "source_event_count": int(payload["summary"].get("source_event_count", len(events)) or 0),
        }
    ]
    payload["source_window_summaries"] = [
        build_source_window_summary(
            events,
            source="akshare.stock_yysj_em",
            market="CN",
            target_date=target_date,
            lookahead_days=lookahead_days,
            periods=periods,
        )
    ]
    payload["source_errors"] = source_errors
    payload["source_health"] = "degraded" if source_errors else "ok"
    return payload


def collect_us_earnings_calendar(
    *,
    target_date: str,
    lookahead_days: int,
    focus_values: list[str] | None = None,
    headliner_values: list[Any] | None = None,
    dates: list[str] | None = None,
    fetcher: Fetcher = fetch_nasdaq_earnings_rows,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    source_errors: list[dict[str, str]] = []
    fetch_dates = dates or date_range(target_date, lookahead_days)
    for fetch_date in fetch_dates:
        rows, errors = fetch_rows_with_retries(fetcher, fetch_date)
        if errors:
            fetch_date_obj = parse_date_value(fetch_date)
            source_errors.append(
                {
                    "source": "nasdaq.calendar.earnings",
                    "source_url": nasdaq_earnings_source_url(fetch_date_obj) if fetch_date_obj else NASDAQ_EARNINGS_API_URL,
                    "date": fetch_date,
                    "error": " | ".join(errors),
                }
            )
            continue
        events.extend(
            normalize_nasdaq_earnings_rows(
                rows_with_default_earnings_date(rows, fetch_date),
                source="nasdaq.calendar.earnings",
            )
        )
    payload = build_earnings_calendar_payload(
        events,
        target_date=target_date,
        lookahead_days=lookahead_days,
        focus_values=focus_values or [],
        headliner_values=headliner_values or [],
    )
    payload["source_breakdown"] = [
        {
            "source": "nasdaq.calendar.earnings",
            "source_event_count": int(payload["summary"].get("source_event_count", len(events)) or 0),
        }
    ]
    payload["source_window_summaries"] = [
        build_source_window_summary(
            events,
            source="nasdaq.calendar.earnings",
            market="US",
            target_date=target_date,
            lookahead_days=lookahead_days,
        )
    ]
    payload["source_errors"] = source_errors
    payload["source_health"] = "degraded" if source_errors else "ok"
    return payload


def merge_calendar_payloads(payloads: list[dict[str, Any]], *, target_date: str, lookahead_days: int) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    source_errors: list[dict[str, Any]] = []
    source_health_values: list[str] = []
    source_window_summaries: list[dict[str, Any]] = []
    source_event_count = 0
    focus_count = 0
    headliner_count = 0
    source_breakdown: dict[str, int] = {}
    for payload in payloads:
        events.extend(
            row
            for row in payload.get("earnings_calendar_events", [])
            if isinstance(row, dict)
        )
        source_errors.extend(
            row
            for row in payload.get("source_errors", [])
            if isinstance(row, dict)
        )
        source_health_values.append(clean_text(payload.get("source_health")) or "ok")
        source_window_summaries.extend(
            row
            for row in payload.get("source_window_summaries", [])
            if isinstance(row, dict)
        )
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        source_event_count += int(summary.get("source_event_count", 0) or 0)
        focus_count = max(focus_count, int(summary.get("focus_count", 0) or 0))
        headliner_count = max(headliner_count, int(summary.get("headliner_count", 0) or 0))
        for row in payload.get("source_breakdown", []):
            if not isinstance(row, dict):
                continue
            source = clean_text(row.get("source"))
            if not source:
                continue
            source_breakdown[source] = source_breakdown.get(source, 0) + int(row.get("source_event_count", 0) or 0)
    merged = build_earnings_calendar_payload(
        events,
        target_date=target_date,
        lookahead_days=lookahead_days,
        focus_values=[],
    )
    merged["summary"]["source_event_count"] = source_event_count
    merged["summary"]["focus_count"] = focus_count
    merged["summary"]["headliner_count"] = headliner_count
    if source_breakdown:
        merged["source_breakdown"] = [
            {"source": source, "source_event_count": count}
            for source, count in source_breakdown.items()
        ]
    if source_window_summaries:
        merged["source_window_summaries"] = source_window_summaries
    merged["source_errors"] = source_errors
    merged["source_health"] = "degraded" if source_errors or any(value == "degraded" for value in source_health_values) else "ok"
    return merged


def build_combined_earnings_calendar_payload(
    *,
    output_path: str | Path,
    target_date: str,
    lookahead_days: int = 7,
    periods: list[str] | None = None,
    focus_source_paths: list[str] | None = None,
    focus_payloads: list[Any] | None = None,
    explicit_focus: list[Any] | None = None,
    headliner_values: list[Any] | None = None,
    include_a_share: bool = True,
    include_us: bool = False,
    nasdaq_dates: list[str] | None = None,
    a_share_fetcher: Fetcher = fetch_akshare_eastmoney_rows,
    us_fetcher: Fetcher = fetch_nasdaq_earnings_rows,
) -> dict[str, Any]:
    resolved_periods = (
        resolve_a_share_periods(
            explicit_periods=periods or [],
            target_date=target_date,
            lookahead_days=lookahead_days,
        )
        if include_a_share
        else []
    )
    focus_values = resolve_focus_values(
        output_path=output_path,
        focus_source_paths=focus_source_paths or [],
        focus_payloads=focus_payloads or [],
        explicit_focus=explicit_focus or [],
    )
    resolved_headliner_values = expand_focus_records(headliner_values)
    payloads = []
    if include_a_share:
        payloads.append(
            collect_a_share_earnings_calendar(
                periods=resolved_periods,
                target_date=target_date,
                lookahead_days=lookahead_days,
                focus_values=focus_values,
                headliner_values=resolved_headliner_values,
                fetcher=a_share_fetcher,
            )
        )
    if include_us or nasdaq_dates:
        payloads.append(
            collect_us_earnings_calendar(
                target_date=target_date,
                lookahead_days=lookahead_days,
                focus_values=focus_values,
                headliner_values=resolved_headliner_values,
                dates=nasdaq_dates or None,
                fetcher=us_fetcher,
            )
        )
    return merge_calendar_payloads(payloads, target_date=target_date, lookahead_days=lookahead_days)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build earnings-calendar JSON for local-stock-pool-manager.")
    parser.add_argument("--output", required=True, help="Output earnings-calendar JSON path.")
    parser.add_argument("--target-date", required=True, help="Calendar target date in YYYY-MM-DD.")
    parser.add_argument("--lookahead-days", type=int, default=7, help="Lookahead window in calendar days.")
    parser.add_argument("--period", action="append", default=[], help="A-share report period such as 20260331.")
    parser.add_argument("--no-a-share", action="store_true", help="Skip the A-share disclosure calendar and only use explicitly requested other sources.")
    parser.add_argument("--focus", action="append", default=[], help="Ticker or company name to keep.")
    parser.add_argument("--focus-source", action="append", default=[], help="JSON package or trading-plan result to extract earnings-calendar focus tickers/names from.")
    parser.add_argument("--headliner", action="append", default=[], help="Ticker or company name to keep as an institutional headliner without labeling it manual focus.")
    parser.add_argument("--include-us", action="store_true", help="Fetch Nasdaq U.S. earnings calendar for target-date through lookahead window.")
    parser.add_argument("--nasdaq-date", action="append", default=[], help="Fetch one explicit Nasdaq earnings-calendar date in YYYY-MM-DD.")
    return parser.parse_args(argv)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_combined_earnings_calendar_payload(
        output_path=args.output,
        target_date=args.target_date,
        lookahead_days=args.lookahead_days,
        periods=args.period,
        focus_source_paths=args.focus_source,
        explicit_focus=args.focus,
        headliner_values=args.headliner,
        include_a_share=not args.no_a_share,
        include_us=args.include_us,
        nasdaq_dates=args.nasdaq_date,
    )
    write_json(Path(args.output), payload)
    print(args.output)
    return 0


__all__ = [
    "SCHEMA_VERSION",
    "build_combined_earnings_calendar_payload",
    "build_earnings_calendar_payload",
    "collect_a_share_earnings_calendar",
    "collect_us_earnings_calendar",
    "dataframe_to_records",
    "discover_focus_source_paths",
    "extract_focus_values",
    "fetch_akshare_eastmoney_rows",
    "fetch_nasdaq_earnings_rows",
    "load_focus_values_from_paths",
    "normalize_a_share_disclosure_rows",
    "normalize_focus_ticker",
    "normalize_nasdaq_earnings_rows",
    "normalize_ticker",
    "normalize_us_ticker",
    "parse_args",
    "default_a_share_periods",
    "resolve_focus_values",
    "resolve_a_share_periods",
    "unique_focus_values",
]


if __name__ == "__main__":
    raise SystemExit(main())
