#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import html
import json
import locale
import os
import re
import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


SCHEMA_VERSION = "event_calendar_source/v1"
BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
FED_MONETARY_POLICY_URL = "https://www.federalreserve.gov/monetarypolicy.htm"
BLS_ICS_PATH_ENV = "EVENT_CALENDAR_BLS_ICS_PATH"
FED_HTML_PATH_ENV = "EVENT_CALENDAR_FED_HTML_PATH"
EVENT_KEYS = (
    "event_calendar_events",
    "macro_calendar_events",
    "hard_event_calendar_events",
    "hard_events",
    "events",
)
HIGH_IMPORTANCE = {"critical", "systemic", "high", "important"}
TIMEZONE_LABELS = {
    "America/New_York": "ET",
    "US/Eastern": "ET",
    "EST": "ET",
    "EDT": "ET",
}
BLS_HIGH_IMPACT_PATTERNS = (
    "consumer price index",
    "cpi",
    "producer price index",
    "ppi",
    "employment situation",
    "nonfarm payroll",
    "job openings",
    "jolts",
    "employment cost index",
    "eci",
    "real earnings",
)
MONTH_NAME_TO_NUMBER = {month.lower(): index for index, month in enumerate(calendar.month_name) if month}


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def decode_subprocess_bytes(value: Any) -> str:
    if isinstance(value, str):
        return value
    data = bytes(value or b"")
    encodings = ("utf-8-sig", locale.getpreferredencoding(False), "mbcs", "gbk")
    seen: set[str] = set()
    for encoding in encodings:
        if not encoding or encoding.casefold() in seen:
            continue
        seen.add(encoding.casefold())
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8-sig", errors="replace")


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
    if "." not in text and text.isalpha() and 1 <= len(text) <= 5:
        return f"{text}.US"
    return text


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def clean_string_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = clean_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def identity_tokens(value: Any) -> set[str]:
    text = clean_text(value)
    if not text:
        return set()
    normalized = normalize_ticker(text)
    return {text.casefold(), text.upper(), normalized.casefold(), normalized.upper()}


def related_identity_tokens(event: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("ticker", "symbol", "code", "related_ticker"):
        if clean_text(event.get(key)):
            values.append(event.get(key))
    for key in ("related_tickers", "tickers", "companies", "related_companies"):
        values.extend(safe_list(event.get(key)))
    tokens: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            tokens.update(identity_tokens(value.get("ticker") or value.get("symbol") or value.get("code")))
            tokens.update(identity_tokens(value.get("name") or value.get("company") or value.get("company_name")))
        else:
            tokens.update(identity_tokens(value))
    return tokens


def extract_event_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in EVENT_KEYS:
        rows.extend(item for item in safe_list(payload.get(key)) if isinstance(item, dict))
    return rows


def load_event_rows(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_path in paths:
        payload = json.loads(Path(raw_path).read_text(encoding="utf-8-sig"))
        rows.extend(extract_event_rows(payload))
    return rows


def fetch_text(url: str, timeout: int = 20) -> str:
    curl_path = shutil.which("curl.exe") or shutil.which("curl")
    if curl_path:
        result = subprocess.run(
            [
                curl_path,
                "-L",
                "--silent",
                "--show-error",
                "--fail",
                "--max-time",
                str(timeout),
                "-A",
                "stock-analysis-plus-event-calendar/1.0",
                "-H",
                "Accept: text/calendar, text/html, */*",
                url,
            ],
            capture_output=True,
        )
        stdout = decode_subprocess_bytes(result.stdout)
        stderr = decode_subprocess_bytes(result.stderr)
        if result.returncode == 0:
            return stdout.replace("\r\n", "\n").replace("\r", "\n")
        raise RuntimeError(clean_text(stderr) or f"curl failed with exit code {result.returncode}")
    request = Request(url, headers={"User-Agent": "stock-analysis-plus-event-calendar/1.0"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    return data.decode("utf-8-sig", errors="replace")


def read_text_file(path: str | Path) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8-sig")


def preferred_local_source_path(env_name: str) -> str:
    return clean_text(os.environ.get(env_name))


def unfold_ics_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw_line.startswith((" ", "\t")) and lines:
            lines[-1] = f"{lines[-1]}{raw_line[1:]}"
            continue
        if raw_line:
            lines.append(raw_line)
    return lines


def parse_ics_property(line: str) -> tuple[str, dict[str, str], str]:
    if ":" not in line:
        return "", {}, ""
    raw_key, value = line.split(":", 1)
    parts = raw_key.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, raw_value = part.split("=", 1)
            params[key.upper()] = raw_value.strip('"')
        elif part:
            params[part.upper()] = ""
    return name, params, clean_text(value)


def parse_ics_datetime(value: Any, params: dict[str, str] | None = None) -> tuple[str, str]:
    params = params or {}
    text = clean_text(value)
    if not text:
        return "", ""
    match = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?Z?$", text)
    if not match:
        return "", ""
    year, month, day, hour, minute, _second = match.groups()
    event_date = f"{year}-{month}-{day}"
    if not hour or not minute or params.get("VALUE", "").upper() == "DATE":
        return event_date, ""
    timezone_label = TIMEZONE_LABELS.get(params.get("TZID", ""), "")
    event_time = f"{hour}:{minute}"
    if timezone_label:
        event_time = f"{event_time} {timezone_label}"
    return event_date, event_time


def bls_event_importance(title: Any) -> str:
    normalized = clean_text(title).casefold()
    if any(pattern in normalized for pattern in BLS_HIGH_IMPACT_PATTERNS):
        return "high"
    return "medium"


def parse_ics_events(text: str, *, source: str, source_url: str = "") -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in unfold_ics_lines(text):
        name, params, value = parse_ics_property(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            current = {"source": source, "calendar_source_url": source_url}
            continue
        if name == "END" and value.upper() == "VEVENT":
            if current:
                title = clean_text(current.get("title"))
                event_date = clean_text(current.get("date"))
                if title and event_date:
                    current["importance"] = clean_text(current.get("importance")) or bls_event_importance(title)
                    current["category"] = clean_text(current.get("category")) or "macro_data_release"
                    events.append(current)
            current = None
            continue
        if current is None:
            continue
        if name == "SUMMARY":
            current["title"] = value
        elif name in {"DTSTART", "DTSTAMP"}:
            event_date, event_time = parse_ics_datetime(value, params)
            if event_date:
                current["date"] = event_date
            if event_time:
                current["time"] = event_time
        elif name in {"URL", "ATTACH"} and value:
            current["source_url"] = value
        elif name == "DESCRIPTION" and value:
            current["reminder"] = value
    return events


def strip_html_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def parse_fed_month_day(value: Any, target_year: int, target_month: int) -> tuple[str, str]:
    text = clean_text(value)
    match = re.match(r"^([A-Za-z]+)\s+(\d{1,2})(?:-(\d{1,2}))?$", text)
    if not match:
        return "", ""
    month_name, start_day_text, end_day_text = match.groups()
    month_number = MONTH_NAME_TO_NUMBER.get(month_name.casefold(), 0)
    if not month_number:
        return "", ""
    year = target_year if month_number >= target_month else target_year + 1
    start_day = int(start_day_text)
    start_date = date(year, month_number, start_day).isoformat()
    if end_day_text:
        end_date = date(year, month_number, int(end_day_text)).isoformat()
        return start_date, end_date
    return start_date, ""


def parse_fed_upcoming_dates(
    text: str,
    *,
    source: str,
    source_url: str = "",
    target_date: str,
) -> list[dict[str, Any]]:
    target = parse_date_value(target_date) or date.today()
    block_match = re.search(r"<h5>\s*Upcoming Dates\s*</h5>(.*?)<ul class=\"list-unstyled\">", text, re.S | re.I)
    section = block_match.group(1) if block_match else text
    events: list[dict[str, Any]] = []
    for raw_block in re.findall(r"<p><strong>(.*?)</p>", section, re.S | re.I):
        lines = [
            clean_text(line)
            for line in strip_html_tags(html.unescape(re.sub(r"<br\s*/?>", "\n", raw_block, flags=re.I))).splitlines()
            if clean_text(line)
        ]
        if not lines:
            continue
        date_match = re.match(r"^\s*([A-Za-z]+\s+\d{1,2}(?:-\d{1,2})?)\s*(.*)$", clean_text(lines[0]))
        if not date_match:
            continue
        header_text = clean_text(date_match.group(1))
        title = clean_text(date_match.group(2)) or (lines[1] if len(lines) > 1 else "")
        body_lines = lines[1:] if clean_text(date_match.group(2)) else lines[2:]
        body_lines = [line for line in body_lines if line]
        start_date, end_date = parse_fed_month_day(header_text, target.year, target.month)
        if not start_date:
            continue
        reminder = " ".join(body_lines).strip()
        if "FOMC Meeting" in title:
            event = {
                "title": "FOMC Meeting",
                "date": start_date,
                "category": "macro_policy",
                "importance": "high",
                "source": source,
                "source_url": source_url,
                "reminder": reminder,
            }
            events.append(event)
            if end_date and any("press conference" in line.casefold() for line in body_lines):
                events.append(
                    {
                        "title": "FOMC Press Conference",
                        "date": end_date,
                        "category": "macro_policy",
                        "importance": "high",
                        "source": source,
                        "source_url": source_url,
                        "reminder": "Press Conference",
                    }
                )
        else:
            events.append(
                {
                    "title": title,
                    "date": start_date,
                    "category": "macro_policy",
                    "importance": "high",
                    "source": source,
                    "source_url": source_url,
                    "reminder": reminder,
                }
            )
    return events


def event_importance(value: Any) -> str:
    text = clean_text(value).lower()
    if text in {"critical", "systemic"}:
        return "critical"
    if text in {"high", "important"}:
        return "high"
    if text in {"medium", "normal", "watch"}:
        return "medium"
    if text in {"low", "minor"}:
        return "low"
    return text or "medium"


def load_fed_rows_with_errors(
    target_date: str,
    *,
    text_fetcher=fetch_text,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    try:
        local_path = preferred_local_source_path(FED_HTML_PATH_ENV)
        if local_path:
            text = read_text_file(local_path)
        else:
            text = text_fetcher(FED_MONETARY_POLICY_URL)
        rows = parse_fed_upcoming_dates(
            text,
            source="Federal Reserve monetary policy calendar",
            source_url=FED_MONETARY_POLICY_URL,
            target_date=target_date,
        )
        return rows, []
    except Exception as error:  # noqa: BLE001 - source-health output must preserve fetch failures.
        return [], [build_source_error(FED_MONETARY_POLICY_URL, error)]


def load_fed_rows(target_date: str, *, text_fetcher=fetch_text) -> list[dict[str, Any]]:
    rows, _errors = load_fed_rows_with_errors(target_date, text_fetcher=text_fetcher)
    return rows


def build_event_calendar_payload(
    events: list[dict[str, Any]],
    *,
    target_date: str,
    lookahead_days: int = 7,
    focus_values: list[Any] | None = None,
    source: str = "",
    source_errors: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    start_date = parse_date_value(target_date) or date.today()
    end_date = start_date + timedelta(days=max(0, int(lookahead_days)))
    focus_tokens: set[str] = set()
    for value in focus_values or []:
        focus_tokens.update(identity_tokens(value))
    normalized_rows: list[dict[str, Any]] = []
    for event in events:
        event_date = (
            parse_date_value(event.get("date"))
            or parse_date_value(event.get("event_date"))
            or parse_date_value(event.get("scheduled_date"))
        )
        if event_date is None or event_date < start_date or event_date > end_date:
            continue
        title = clean_text(event.get("title") or event.get("event") or event.get("event_type") or event.get("name"))
        if not title:
            continue
        importance = event_importance(event.get("importance"))
        related_tokens = related_identity_tokens(event)
        scope: list[str] = []
        if importance in HIGH_IMPORTANCE:
            scope.append("high_importance")
        if focus_tokens and related_tokens & focus_tokens:
            scope.append("manual_focus")
        if not scope and not bool(event.get("force_include")):
            continue
        related_tickers = [
            normalize_ticker(value)
            for value in clean_string_list(event.get("related_tickers") or event.get("tickers"))
        ]
        related_companies = clean_string_list(event.get("related_companies") or event.get("companies"))
        importance_reason = clean_text(event.get("importance_reason") or event.get("reason") or event.get("rationale"))
        normalized_rows.append(
            {
                "title": title,
                "date": event_date.isoformat(),
                "time": clean_text(event.get("time") or event.get("event_time")),
                "category": clean_text(event.get("category") or event.get("event_category") or event.get("type")) or "hard_event",
                "importance": importance,
                "watch_scope": scope,
                "source": clean_text(event.get("source") or event.get("source_name")) or source,
                "source_url": clean_text(event.get("source_url") or event.get("url")),
                "reminder": clean_text(event.get("reminder") or event.get("operation_reminder")),
                "impact_scope": clean_string_list(event.get("impact_scope")),
                "related_tickers": related_tickers,
                "related_companies": related_companies,
                "importance_reason": importance_reason,
            }
        )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in normalized_rows:
        grouped.setdefault((row["title"], row["date"]), []).append(row)
    filtered: list[dict[str, Any]] = []
    for rows in grouped.values():
        sorted_rows = sorted(
            rows,
            key=lambda row: (
                clean_text(row.get("source")),
                clean_text(row.get("source_url")),
            ),
        )
        primary = dict(sorted_rows[0])
        sources = []
        seen_sources: set[str] = set()
        source_urls = []
        seen_source_urls: set[str] = set()
        scopes: list[str] = []
        impact_scope: list[str] = []
        related_tickers: list[str] = []
        related_companies: list[str] = []
        importance_reasons: list[str] = []
        for row in sorted_rows:
            source_label = clean_text(row.get("source"))
            if source_label and source_label not in seen_sources:
                seen_sources.add(source_label)
                sources.append(source_label)
            source_url = clean_text(row.get("source_url"))
            if source_url and source_url not in seen_source_urls:
                seen_source_urls.add(source_url)
                source_urls.append(source_url)
            scopes.extend(clean_string_list(row.get("watch_scope")))
            impact_scope.extend(clean_string_list(row.get("impact_scope")))
            related_tickers.extend(clean_string_list(row.get("related_tickers")))
            related_companies.extend(clean_string_list(row.get("related_companies")))
            importance_reasons.extend(clean_string_list(row.get("importance_reason")))
        primary["watch_scope"] = clean_string_list(scopes)
        primary["impact_scope"] = clean_string_list(impact_scope)
        primary["related_tickers"] = clean_string_list(related_tickers)
        primary["related_companies"] = clean_string_list(related_companies)
        if importance_reasons:
            primary["importance_reason"] = "; ".join(clean_string_list(importance_reasons))
        primary["source_count"] = len(sources) or len(sorted_rows)
        primary["sources"] = sources
        primary["source"] = ", ".join(sources) if sources else clean_text(primary.get("source"))
        primary["source_urls"] = source_urls
        if not clean_text(primary.get("source_url")) and source_urls:
            primary["source_url"] = source_urls[0]
        filtered.append(primary)
    importance_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    filtered.sort(key=lambda item: (item["date"], importance_rank.get(item["importance"], 4), item["title"]))
    errors = source_errors or []
    source_breakdown: dict[str, int] = {}
    for event in events:
        source_label = clean_text(event.get("source") or event.get("source_name")) or source
        if not source_label:
            continue
        source_breakdown[source_label] = source_breakdown.get(source_label, 0) + 1
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "target_date": start_date.isoformat(),
        "lookahead_days": max(0, int(lookahead_days)),
        "window_end_date": end_date.isoformat(),
        "event_calendar_events": filtered,
        "summary": {
            "event_count": len(filtered),
            "source_event_count": len(events),
            "focus_count": len(focus_values or []),
            "source_error_count": len(errors),
        },
        "source_health": "degraded" if errors else "ok",
    }
    if source_breakdown:
        payload["source_breakdown"] = [
            {"source": source_label, "source_event_count": count}
            for source_label, count in source_breakdown.items()
        ]
    if errors:
        payload["source_errors"] = errors
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build event-calendar JSON for local-stock-pool-manager.")
    parser.add_argument("--input", action="append", default=[], help="Input event-calendar JSON file.")
    parser.add_argument("--ics-url", action="append", default=[], help="Input iCalendar URL.")
    parser.add_argument("--bls-calendar", action="store_true", help="Include BLS official news-release iCalendar.")
    parser.add_argument("--fed-calendar", action="store_true", help="Include the Federal Reserve monetary policy calendar.")
    parser.add_argument("--output", required=True, help="Output event-calendar JSON path.")
    parser.add_argument("--target-date", required=True, help="Calendar target date in YYYY-MM-DD.")
    parser.add_argument("--lookahead-days", type=int, default=7, help="Lookahead window in calendar days.")
    parser.add_argument("--focus", action="append", default=[], help="Ticker or company name to keep medium events.")
    parser.add_argument("--source", default="manual.event_calendar", help="Default source label.")
    return parser.parse_args(argv)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")


def ics_source_label(url: str) -> str:
    return "BLS official news release calendar" if url == BLS_ICS_URL else "official.ics"


def source_error_label(url: str) -> str:
    if url == FED_MONETARY_POLICY_URL:
        return "Federal Reserve monetary policy calendar"
    return ics_source_label(url)


def build_source_error(url: str, error: Exception) -> dict[str, str]:
    return {
        "source": source_error_label(url),
        "source_url": url,
        "error": clean_text(error),
    }


def load_ics_rows_with_errors(urls: list[str], *, text_fetcher=fetch_text) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for url in urls:
        source = ics_source_label(url)
        try:
            local_path = preferred_local_source_path(BLS_ICS_PATH_ENV) if url == BLS_ICS_URL else ""
            if local_path:
                rows.extend(parse_ics_events(read_text_file(local_path), source=source, source_url=url))
            else:
                rows.extend(parse_ics_events(text_fetcher(url), source=source, source_url=url))
        except Exception as error:  # noqa: BLE001 - source-health output must preserve fetch failures.
            errors.append(build_source_error(url, error))
    return rows, errors


def load_ics_rows(urls: list[str], *, text_fetcher=fetch_text) -> list[dict[str, Any]]:
    rows, _errors = load_ics_rows_with_errors(urls, text_fetcher=text_fetcher)
    return rows


def main(argv: list[str] | None = None, *, text_fetcher=fetch_text) -> int:
    args = parse_args(argv)
    ics_urls = list(args.ics_url)
    if args.bls_calendar:
        ics_urls.append(BLS_ICS_URL)
    rows = load_event_rows(args.input)
    ics_rows, source_errors = load_ics_rows_with_errors(ics_urls, text_fetcher=text_fetcher)
    rows.extend(ics_rows)
    if args.fed_calendar:
        fed_rows, fed_errors = load_fed_rows_with_errors(args.target_date, text_fetcher=text_fetcher)
        rows.extend(fed_rows)
        source_errors.extend(fed_errors)
    payload = build_event_calendar_payload(
        rows,
        target_date=args.target_date,
        lookahead_days=args.lookahead_days,
        focus_values=args.focus,
        source=args.source,
        source_errors=source_errors,
    )
    write_json(Path(args.output), payload)
    print(args.output)
    return 0


__all__ = [
    "BLS_ICS_URL",
    "FED_MONETARY_POLICY_URL",
    "BLS_ICS_PATH_ENV",
    "FED_HTML_PATH_ENV",
    "build_event_calendar_payload",
    "extract_event_rows",
    "fetch_text",
    "load_ics_rows",
    "load_ics_rows_with_errors",
    "load_event_rows",
    "load_fed_rows",
    "load_fed_rows_with_errors",
    "preferred_local_source_path",
    "main",
    "parse_args",
    "parse_ics_datetime",
    "parse_ics_events",
    "parse_fed_upcoming_dates",
    "read_text_file",
    "write_json",
]


if __name__ == "__main__":
    raise SystemExit(main())
