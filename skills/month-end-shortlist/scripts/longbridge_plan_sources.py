#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib import request as urllib_request

from local_stock_pool_runtime import clean_text, load_json, normalize_a_share_ticker, unique_strings


DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_NEWS_DETAIL_FALLBACK_LANGS = ("en", "zh-HK", "zh-CN")
PLAN_BUCKET_KEYS = (
    "top_picks",
    "directly_actionable",
    "priority_watchlist",
    "near_miss_candidates",
    "diagnostic_scorecard",
    "setup_launch_candidates",
    "market_strength_candidates",
    "ranked_candidates",
    "stocks",
)
EXPECTATION_SOURCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "kind": "valuation",
        "command": "valuation",
        "artifact": "longbridge-valuation",
        "filename": "longbridge-valuation.json",
        "evidence_key": "valuation",
        "row_keys": ("valuations", "valuation", "rows", "items", "data", "results"),
    },
    {
        "kind": "institution_rating",
        "command": "institution-rating",
        "artifact": "longbridge-institution-rating",
        "filename": "longbridge-institution-rating.json",
        "evidence_key": "institution_rating",
        "row_keys": ("ratings", "institution_ratings", "institution_rating", "rows", "items", "data", "results"),
    },
    {
        "kind": "forecast_eps",
        "command": "forecast-eps",
        "artifact": "longbridge-forecast-eps",
        "filename": "longbridge-forecast-eps.json",
        "evidence_key": "forecast_eps",
        "row_keys": ("forecast_eps", "eps_forecasts", "forecasts", "estimates", "rows", "items", "data", "results"),
    },
    {
        "kind": "consensus",
        "command": "consensus",
        "artifact": "longbridge-consensus",
        "filename": "longbridge-consensus.json",
        "evidence_key": "consensus",
        "row_keys": ("consensus", "consensus_estimates", "estimates", "rows", "items", "data", "results", "list"),
    },
)
FUNDAMENTAL_SOURCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "kind": "financial_reports",
        "command": "financial-report",
        "command_args": ("--kind", "ALL"),
        "artifact": "longbridge-financial-report",
        "filename": "longbridge-financial-report.json",
        "row_keys": (
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "statements",
            "financial_reports",
            "rows",
            "items",
            "data",
            "results",
        ),
    },
    {
        "kind": "operating_reviews",
        "command": "operating",
        "command_args": (),
        "artifact": "longbridge-operating",
        "filename": "longbridge-operating.json",
        "row_keys": ("operating", "operating_reviews", "indicators", "rows", "items", "data", "results"),
    },
)
INDUSTRY_VALUATION_SOURCE_SPEC: dict[str, Any] = {
    "kind": "industry_valuation",
    "command": "industry-valuation",
    "command_args": (),
    "artifact": "longbridge-industry-valuation",
    "filename": "longbridge-industry-valuation.json",
    "row_keys": (
        "industry_valuation",
        "industry_valuations",
        "peer_valuation",
        "peer_valuations",
        "peers",
        "rows",
        "items",
        "data",
        "results",
    ),
}
EXPECTATION_METADATA_KEYS = {
    "ticker",
    "symbol",
    "code",
    "name",
    "stock_name",
    "security_name",
    "source",
    "source_kind",
    "source_path",
    "path",
    "artifact_path",
    "schema",
    "schema_version",
    "retrieved_at",
    "current_index",
    "current_period",
    "opt_periods",
    "currency",
}

Runner = Callable[[list[str], float], Any]
RATE_LIMIT_RETRY_COUNT = 2


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")


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


def longbridge_detail_quality_counts(
    details: list[dict[str, Any]],
    *,
    reference_time: datetime | None,
    max_age_hours: int = 72,
) -> dict[str, int]:
    counts = {
        "usable": 0,
        "error": 0,
        "unattributed": 0,
        "stale": 0,
        "empty": 0,
    }
    max_age = timedelta(hours=max_age_hours)
    for row in details:
        fetch_status = clean_text(row.get("fetch_status")).lower()
        if fetch_status not in {"", "ok", "success", "fetched"}:
            counts["error"] += 1
            continue
        content = clean_text(row.get("content_markdown") or row.get("content") or row.get("body") or row.get("text"))
        if not content:
            counts["empty"] += 1
            continue
        if not clean_text(row.get("ticker") or row.get("symbol") or row.get("code")):
            counts["unattributed"] += 1
            continue
        published_at = parse_datetime_value(row.get("published_at") or row.get("publish_time") or row.get("time"))
        if reference_time is not None and published_at is not None and reference_time - published_at > max_age:
            counts["stale"] += 1
            continue
        counts["usable"] += 1
    return counts


def normalize_symbol(value: Any) -> str:
    raw = clean_text(value).upper()
    if not raw:
        return ""
    normalized = normalize_a_share_ticker(raw) or raw
    if normalized.endswith(".SS"):
        return normalized[:-3] + ".SH"
    if normalized.endswith(".XSHG"):
        return normalized[:-5] + ".SH"
    if normalized.endswith(".XSHE"):
        return normalized[:-5] + ".SZ"
    return normalized


def is_us_symbol(value: Any) -> bool:
    return normalize_symbol(value).endswith(".US")


def _append_ticker(tickers: list[str], value: Any) -> None:
    ticker = normalize_symbol(value)
    if ticker and ticker not in tickers:
        tickers.append(ticker)


def _collect_tickers_from_value(value: Any, tickers: list[str]) -> None:
    if isinstance(value, dict):
        _append_ticker(tickers, value.get("ticker") or value.get("symbol") or value.get("code"))
        pool = value.get("local_stock_pool")
        if isinstance(pool, dict):
            _collect_tickers_from_value(pool.get("stocks"), tickers)
        plan = value.get("trading_plan")
        if isinstance(plan, dict):
            _collect_tickers_from_value(plan.get("candidates"), tickers)
        for key in PLAN_BUCKET_KEYS:
            _collect_tickers_from_value(value.get(key), tickers)
    elif isinstance(value, list):
        for item in value:
            _collect_tickers_from_value(item, tickers)


def collect_plan_tickers(payloads: list[Any], *, limit: int = 24) -> list[str]:
    tickers: list[str] = []
    for payload in payloads:
        _collect_tickers_from_value(payload, tickers)
    return tickers[:limit]


def load_input_payloads(paths: list[str | Path]) -> list[Any]:
    payloads: list[Any] = []
    for path_value in paths:
        path = Path(path_value).expanduser()
        if not path.exists():
            continue
        payloads.append(load_json(path))
    return payloads


def run_longbridge_json(
    longbridge_binary: str,
    args: list[str],
    *,
    runner: Runner | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Any | None, dict[str, Any]]:
    cmd = [clean_text(longbridge_binary) or "longbridge", *args]
    previous_errors: list[str] = []
    for attempt in range(RATE_LIMIT_RETRY_COUNT + 1):
        try:
            if runner is not None:
                completed = runner(cmd, timeout)
            else:
                completed = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}: {exc}"
            if is_retryable_longbridge_text(error_text) and attempt < RATE_LIMIT_RETRY_COUNT:
                previous_errors.append(error_text[:800])
                if runner is None:
                    time.sleep(1.5 * (attempt + 1))
                continue
            return None, {
                "command": cmd,
                "status": "error",
                "error": error_text,
                **({"retry_count": len(previous_errors), "previous_errors": previous_errors} if previous_errors else {}),
            }

        stdout = clean_text(getattr(completed, "stdout", ""))
        stderr = clean_text(getattr(completed, "stderr", ""))
        returncode = int(getattr(completed, "returncode", 1) or 0)
        status = {
            "command": cmd,
            "status": "ok" if returncode == 0 else "error",
            "returncode": returncode,
        }
        if previous_errors:
            status["retry_count"] = len(previous_errors)
            status["previous_errors"] = previous_errors
        if stderr:
            status["stderr"] = stderr[:800]
        if returncode != 0:
            if stdout:
                status["stdout"] = stdout[:800]
            error_text = " ".join(part for part in (stderr, stdout) if part)
            if is_retryable_longbridge_text(error_text) and attempt < RATE_LIMIT_RETRY_COUNT:
                previous_errors.append(error_text[:800])
                if runner is None:
                    time.sleep(1.5 * (attempt + 1))
                continue
            return None, status
        if not stdout:
            status["status"] = "empty"
            return None, status
        try:
            return json.loads(stdout), status
        except json.JSONDecodeError as exc:
            if is_no_rows_text(stdout):
                status.update({"status": "empty", "empty_reason": "no_rows_text", "stdout": stdout[:800]})
                return None, status
            status.update({"status": "non_json", "error": f"json_decode_error: {exc}", "stdout": stdout[:800]})
            return stdout, status

    return None, {"command": cmd, "status": "error", "error": "unreachable_retry_state"}


def load_reusable_json_artifact(path: Path, artifact: str) -> tuple[Any | None, dict[str, Any] | None]:
    if not path.exists():
        return None, None
    try:
        payload = load_json(path)
    except Exception as exc:  # noqa: BLE001
        return None, {
            "artifact": artifact,
            "status": "reuse_error",
            "source_path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return payload, {
        "artifact": artifact,
        "status": "reused",
        "source_path": str(path),
        "reuse_reason": "existing_output_artifact",
    }


def is_rate_limited_text(value: Any) -> bool:
    text = clean_text(value).lower()
    return "429002" in text or "request is limited" in text or "slow down request frequency" in text


def is_transient_transport_text(value: Any) -> bool:
    text = clean_text(value).lower()
    return any(
        marker in text
        for marker in (
            "connection reset",
            "connection aborted",
            "econnreset",
            "winerror 10054",
            "os error 10054",
            "远程主机强迫关闭了一个现有的连接",
            "forcibly closed",
        )
    )


def is_retryable_longbridge_text(value: Any) -> bool:
    return is_rate_limited_text(value) or is_transient_transport_text(value)


def longbridge_status_error_text(status: dict[str, Any]) -> str:
    return clean_text(" ".join(clean_text(status.get(key)) for key in ("error", "stderr", "stdout")))


def longbridge_status_retry_exhausted(status: dict[str, Any]) -> bool:
    try:
        retry_count = int(status.get("retry_count") or 0)
    except (TypeError, ValueError):
        retry_count = 0
    return clean_text(status.get("status")) == "error" and retry_count >= RATE_LIMIT_RETRY_COUNT


def classify_longbridge_error_kind(status: dict[str, Any]) -> str:
    text = longbridge_status_error_text(status)
    if is_transient_transport_text(text):
        return "transport_retry_exhausted" if longbridge_status_retry_exhausted(status) else "transport_error"
    if is_rate_limited_text(text):
        return "rate_limit_retry_exhausted" if longbridge_status_retry_exhausted(status) else "rate_limited"
    lowered = text.lower()
    if "not authenticated" in lowered:
        return "not_authenticated"
    if "404" in lowered or "not found" in lowered:
        return "not_found"
    if text:
        return "source_error"
    return ""


def news_detail_language_candidates(primary_lang: Any) -> list[str]:
    candidates: list[str] = []
    for candidate in (clean_text(primary_lang) or "zh-CN", *DEFAULT_NEWS_DETAIL_FALLBACK_LANGS):
        lang = clean_text(candidate)
        if lang and lang not in candidates:
            candidates.append(lang)
    return candidates


def longbridge_headline_fetch_count(news_count: int, detail_limit_per_ticker: int) -> int:
    requested = max(1, int(news_count or 0))
    if detail_limit_per_ticker > 0:
        requested = max(requested, 8, detail_limit_per_ticker * 4)
    return requested


def is_no_rows_text(value: Any) -> bool:
    text = clean_text(value).lower().strip()
    return bool(re.match(r"^no .+ found(?: for .+)?\.?$", text))


def payload_rows(payload: Any, keys: tuple[str, ...] = ("data", "items", "news", "rows", "quotes")) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = []
        for key in keys:
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = candidate
                break
            if isinstance(candidate, dict):
                rows = list(candidate.values())
                break
        if not rows and any(payload.get(key) not in (None, "", [], {}) for key in ("id", "title", "symbol", "ticker")):
            rows = [payload]
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def normalize_news_headline(row: dict[str, Any], ticker: str) -> dict[str, Any]:
    normalized = {
        "ticker": ticker,
        "id": clean_text(row.get("id") or row.get("news_id") or row.get("uuid")),
        "published_at": row.get("published_at") or row.get("publish_time") or row.get("time"),
        "title": clean_text(row.get("title") or row.get("headline") or row.get("name")),
        "url": clean_text(row.get("url") or row.get("link")),
        "comments_count": row.get("comments_count"),
        "likes_count": row.get("likes_count"),
    }
    return {key: value for key, value in normalized.items() if value not in (None, "", [], {})}


def normalize_news_detail(
    payload: Any,
    headline: dict[str, Any],
    *,
    fetch_status: str,
    fetch_error: str = "",
    fetch_error_kind: str = "",
    fetch_retry_exhausted: bool = False,
    fetch_lang: str = "",
    fetch_language_fallback: bool = False,
) -> dict[str, Any]:
    row = payload if isinstance(payload, dict) else {}
    detail = {
        "ticker": clean_text(headline.get("ticker")),
        "id": clean_text(row.get("id") or headline.get("id")),
        "title": clean_text(row.get("title") or headline.get("title")),
        "url": clean_text(row.get("url") or headline.get("url")),
        "published_at": row.get("published_at") or row.get("publish_time") or row.get("time") or headline.get("published_at"),
        "source": clean_text(row.get("source") or "longbridge.news.detail"),
        "retrieved_at": now_utc_iso(),
        "fetch_status": fetch_status,
    }
    content = clean_text(row.get("content_markdown") or row.get("markdown") or row.get("content") or row.get("body") or row.get("text"))
    if content:
        detail["content_markdown"] = content
        detail["content_length"] = len(content)
    if fetch_error:
        detail["fetch_error"] = fetch_error
    if fetch_error_kind:
        detail["fetch_error_kind"] = fetch_error_kind
    if fetch_retry_exhausted:
        detail["fetch_retry_exhausted"] = True
    if fetch_lang:
        detail["fetch_lang"] = fetch_lang
    if fetch_language_fallback:
        detail["fetch_language_fallback"] = True
    return {key: value for key, value in detail.items() if value not in (None, "", [], {})}


def detail_error_kinds(details: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            clean_text(row.get("fetch_error_kind"))
            for row in details
            if clean_text(row.get("fetch_status")).lower() not in {"", "ok", "success", "fetched"}
            and clean_text(row.get("fetch_error_kind"))
        }
    )


def detail_transport_error_count(details: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in details
        if clean_text(row.get("fetch_error_kind")) in {"transport_error", "transport_retry_exhausted"}
    )


def detail_retry_exhausted_count(details: list[dict[str, Any]]) -> int:
    return sum(1 for row in details if bool(row.get("fetch_retry_exhausted")))


def parse_markdown_frontmatter_value(markdown: str, key: str) -> str:
    if not markdown.startswith("---"):
        return ""
    match = re.search(rf"(?m)^{re.escape(key)}:\s*[\"']?(.*?)[\"']?\s*$", markdown)
    return clean_text(match.group(1)) if match else ""


def markdown_news_detail_payload(markdown: str) -> dict[str, Any]:
    text = clean_text(markdown)
    if not text:
        return {}
    title = parse_markdown_frontmatter_value(markdown, "title")
    if not title:
        heading = re.search(r"(?m)^#\s+(.+?)\s*$", markdown)
        title = clean_text(heading.group(1)) if heading else ""
    payload = {
        "title": title,
        "content_markdown": text,
        "source": "longbridge.news.detail.markdown",
    }
    published_at = parse_markdown_frontmatter_value(markdown, "datetime")
    if published_at:
        payload["published_at"] = published_at
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def html_fragment_to_text(fragment: Any) -> str:
    text = clean_text(fragment)
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = re.sub(r"(?is)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?is)</\s*(p|div|tr|table|li|h[1-6]|section|article)\s*>", "\n", text)
    text = re.sub(r"(?is)<\s*(td|th)[^>]*>", "\t", text)
    text = re.sub(r"(?is)</\s*(td|th)\s*>", "\t", text)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    text = html_lib.unescape(text)
    lines = [clean_text(line) for line in re.split(r"\n+", text) if clean_text(line)]
    return "\n".join(lines)


def normalize_longbridge_published_at(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = clean_text(value)
    if text.isdigit():
        return int(text)
    return value


def parse_longbridge_news_detail_html(html_text: str, news_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    script_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text, re.S)
    if not script_match:
        return None, {"status": "error", "error": "next_data_missing"}
    try:
        data = json.loads(script_match.group(1))
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "error", "error": f"next_data_parse_error: {type(exc).__name__}: {exc}"}

    details = (
        data.get("props", {}).get("pageProps", {}).get("details", {})
        if isinstance(data, dict)
        else {}
    )
    detail: dict[str, Any] | None = None
    if isinstance(details, dict):
        candidate = details.get(news_id)
        if isinstance(candidate, dict):
            detail = candidate
        elif details:
            for value in details.values():
                if isinstance(value, dict):
                    detail = value
                    break
    if not isinstance(detail, dict):
        return None, {"status": "error", "error": "news_detail_missing"}

    body_html = clean_text(detail.get("body") or detail.get("articleBody") or detail.get("description_html"))
    title = clean_text(detail.get("title"))
    title_locale = detail.get("title_locale")
    if not title and isinstance(title_locale, dict):
        title = clean_text(title_locale.get("en"))
    if not title and isinstance(data, dict):
        title = clean_text(
            data.get("props", {})
            .get("pageProps", {})
            .get("details", {})
            .get(news_id, {})
            .get("title")
        )
    content = html_fragment_to_text(body_html)
    if not content:
        content = clean_text(detail.get("description_html") or detail.get("articleBody"))
    payload = {
        "title": title,
        "content_markdown": content,
        "source": "longbridge.news.detail.html",
    }
    published_at = normalize_longbridge_published_at(
        detail.get("published_at") or detail.get("datePublished") or detail.get("dateCreated") or detail.get("dateModified")
    )
    if published_at not in (None, "", [], {}):
        payload["published_at"] = published_at
    detail_url = clean_text(detail.get("detail_url") or detail.get("web_url"))
    status = {"status": "ok", "content_mode": "html"}
    if detail_url:
        status["source_url"] = detail_url
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}, status


def fetch_longbridge_news_detail_html(news_id: str, lang: str, *, timeout: float) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    candidates = []
    primary = clean_text(lang) or "zh-CN"
    for candidate in (primary, "en"):
        url = f"https://longbridge.cn/{candidate}/news/{news_id}"
        if url not in candidates:
            candidates.append(url)
    candidates.append(f"https://longbridge.cn/news/{news_id}")
    last_error = ""
    for url in candidates:
        try:
            req = urllib_request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            with urllib_request.urlopen(req, timeout=timeout) as response:
                html_text = response.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        payload, status = parse_longbridge_news_detail_html(html_text, news_id)
        status = {**status, "source_url": url}
        if payload is not None and clean_text(status.get("status")) == "ok":
            return payload, status
        last_error = clean_text(status.get("error") or last_error)
    return None, {"status": "error", "error": last_error or "html_detail_unavailable"}


def collect_news(
    tickers: list[str],
    *,
    longbridge_binary: str,
    runner: Runner | None,
    news_count: int,
    detail_limit_per_ticker: int,
    timeout: float,
    lang: str,
    reference_time: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    headlines: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    detail_cache: dict[str, dict[str, Any]] = {}
    primary_lang = clean_text(lang) or "zh-CN"
    detail_lang_candidates = news_detail_language_candidates(primary_lang)
    for ticker in tickers:
        payload, status = run_longbridge_json(
            longbridge_binary,
            [
                "news",
                ticker,
                "--count",
                str(longbridge_headline_fetch_count(news_count, detail_limit_per_ticker)),
                "--format",
                "json",
            ],
            runner=runner,
            timeout=timeout,
        )
        status["artifact"] = "longbridge-news-headlines"
        status["ticker"] = ticker
        statuses.append(status)
        ticker_headlines = [normalize_news_headline(row, ticker) for row in payload_rows(payload)]
        ticker_headlines = [row for row in ticker_headlines if row.get("id") or row.get("title") or row.get("url")]
        headlines.extend(ticker_headlines)
        kept_detail_count = 0
        first_detail_error: dict[str, Any] | None = None
        unusable_details: list[dict[str, Any]] = []
        unusable_detail_keys: set[str] = set()
        should_try_html_fallback = detail_limit_per_ticker > 0

        def remember_unusable_detail(detail: dict[str, Any]) -> None:
            if len(unusable_details) >= max(1, detail_limit_per_ticker):
                return
            detail_key = clean_text(detail.get("id") or detail.get("url") or detail.get("title"))
            if detail_key and detail_key in unusable_detail_keys:
                return
            if detail_key:
                unusable_detail_keys.add(detail_key)
            unusable_details.append(detail)

        for headline in ticker_headlines:
            if kept_detail_count >= max(0, detail_limit_per_ticker):
                break
            news_id = clean_text(headline.get("id"))
            if not news_id:
                continue
            for detail_lang in detail_lang_candidates:
                detail_cache_key = f"{detail_lang}:{news_id}"
                cached_detail = detail_cache.get(detail_cache_key)
                if cached_detail is not None:
                    detail_payload = cached_detail.get("payload")
                    detail_source_status = dict(cached_detail.get("status") or {})
                    detail_status = {
                        "artifact": "longbridge-news-details",
                        "status": "cache_hit",
                        "ticker": ticker,
                        "news_id": news_id,
                        "lang": detail_lang,
                        "cache_key": detail_cache_key,
                        "cached_status": clean_text(detail_source_status.get("status")),
                    }
                    cached_error_kind = classify_longbridge_error_kind(detail_source_status)
                    if cached_error_kind:
                        detail_status["cached_error_kind"] = cached_error_kind
                    statuses.append(detail_status)
                else:
                    detail_payload, detail_status = run_longbridge_json(
                        longbridge_binary,
                        ["--lang", detail_lang, "news", "detail", news_id, "--format", "json"],
                        runner=runner,
                        timeout=timeout,
                    )
                    detail_status["artifact"] = "longbridge-news-details"
                    detail_status["ticker"] = ticker
                    detail_status["news_id"] = news_id
                    detail_status["lang"] = detail_lang
                    statuses.append(detail_status)
                    if isinstance(detail_payload, str) and detail_status.get("status") == "non_json":
                        detail_payload = markdown_news_detail_payload(detail_payload)
                        if detail_payload:
                            detail_status["status"] = "ok"
                            detail_status["content_mode"] = "markdown"
                    detail_source_status = detail_status
                    detail_cache[detail_cache_key] = {
                        "payload": detail_payload,
                        "status": dict(detail_source_status),
                    }
                is_language_fallback = detail_lang != primary_lang
                if detail_payload is None or detail_source_status.get("status") != "ok":
                    detail_error_text = longbridge_status_error_text(detail_source_status)
                    first_detail_error = first_detail_error or normalize_news_detail(
                        {},
                        headline,
                        fetch_status="error",
                        fetch_error=detail_error_text,
                        fetch_error_kind=classify_longbridge_error_kind(detail_source_status),
                        fetch_retry_exhausted=longbridge_status_retry_exhausted(detail_source_status),
                        fetch_lang=detail_lang,
                        fetch_language_fallback=is_language_fallback,
                    )
                    continue
                detail = normalize_news_detail(
                    detail_payload,
                    headline,
                    fetch_status="ok",
                    fetch_lang=detail_lang,
                    fetch_language_fallback=is_language_fallback,
                )
                detail_quality = longbridge_detail_quality_counts([detail], reference_time=reference_time)
                if not detail_quality["usable"]:
                    remember_unusable_detail(detail)
                    if detail_quality["stale"]:
                        should_try_html_fallback = False
                        break
                    continue
                details.append(detail)
                kept_detail_count += 1
                break
            if should_try_html_fallback and kept_detail_count < max(1, detail_limit_per_ticker):
                html_payload, html_status = fetch_longbridge_news_detail_html(news_id, primary_lang, timeout=timeout)
                html_status["artifact"] = "longbridge-news-details"
                html_status["ticker"] = ticker
                html_status["news_id"] = news_id
                html_status["lang"] = "html"
                statuses.append(html_status)
                if html_payload is not None and html_status.get("status") == "ok":
                    detail = normalize_news_detail(
                        html_payload,
                        headline,
                        fetch_status="ok",
                        fetch_lang="html",
                        fetch_language_fallback=True,
                    )
                    detail_quality = longbridge_detail_quality_counts([detail], reference_time=reference_time)
                    if detail_quality["usable"]:
                        details.append(detail)
                        kept_detail_count += 1
                        continue
                    remember_unusable_detail(detail)
        if kept_detail_count == 0:
            if unusable_details:
                details.extend(unusable_details)
            elif first_detail_error:
                details.append(first_detail_error)
    return headlines, details, statuses


def collect_capital_flows(
    tickers: list[str],
    *,
    longbridge_binary: str,
    runner: Runner | None,
    timeout: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    flows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for ticker in tickers:
        payload, status = run_longbridge_json(
            longbridge_binary,
            ["capital", ticker, "--format", "json"],
            runner=runner,
            timeout=timeout,
        )
        status["artifact"] = "longbridge-capital-flow"
        status["ticker"] = ticker
        statuses.append(status)
        if payload is None or status.get("status") != "ok":
            continue
        row = {
            "ticker": ticker,
            "source": "longbridge.capital",
            "retrieved_at": now_utc_iso(),
            "payload": payload,
        }
        if isinstance(payload, dict):
            for key in ("net_inflow", "net_inflow_cny", "large_order_inflow", "large_order_net_inflow"):
                if payload.get(key) not in (None, "", [], {}):
                    row[key] = payload[key]
        flows.append(row)
    return flows, statuses


def normalize_topic_row(row: dict[str, Any], ticker: str) -> dict[str, Any]:
    normalized = {
        "ticker": normalize_symbol(row.get("ticker") or row.get("symbol") or row.get("code")) or ticker,
        "id": clean_text(row.get("id") or row.get("topic_id") or row.get("post_id") or row.get("uuid")),
        "title": clean_text(row.get("title") or row.get("headline") or row.get("subject")),
        "text": clean_text(row.get("text") or row.get("content") or row.get("body") or row.get("summary")),
        "author": clean_text(row.get("author") or row.get("user") or row.get("user_name") or row.get("nickname")),
        "published_at": row.get("published_at") or row.get("created_at") or row.get("publish_time") or row.get("time"),
        "url": clean_text(row.get("url") or row.get("link")),
        "source": "longbridge.topic",
        "retrieved_at": now_utc_iso(),
    }
    for key in ("likes_count", "comments_count", "replies_count", "views_count", "sentiment", "topic"):
        if row.get(key) not in (None, "", [], {}):
            normalized[key] = row[key]
    return {key: value for key, value in normalized.items() if value not in (None, "", [], {})}


def collect_topics(
    tickers: list[str],
    *,
    longbridge_binary: str,
    runner: Runner | None,
    topic_count: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    topics: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for ticker in tickers:
        payload, status = run_longbridge_json(
            longbridge_binary,
            ["topic", ticker, "--count", str(max(1, topic_count)), "--format", "json"],
            runner=runner,
            timeout=timeout,
        )
        status["artifact"] = "longbridge-topics"
        status["ticker"] = ticker
        statuses.append(status)
        if payload is None or status.get("status") != "ok":
            continue
        topics.extend(
            normalize_topic_row(row, ticker)
            for row in payload_rows(payload, keys=("topics", "posts", "items", "data", "rows", "results", "list"))
        )
    return topics, statuses


def normalize_filing_row(row: dict[str, Any], ticker: str) -> dict[str, Any]:
    normalized = {
        "ticker": normalize_symbol(row.get("ticker") or row.get("symbol") or row.get("code")) or ticker,
        "id": clean_text(row.get("id") or row.get("filing_id") or row.get("doc_id") or row.get("uuid")),
        "form": clean_text(row.get("form") or row.get("form_type") or row.get("type") or row.get("category")),
        "title": clean_text(row.get("title") or row.get("name") or row.get("headline")),
        "published_at": row.get("published_at") or row.get("filed_at") or row.get("filing_date") or row.get("date"),
        "url": clean_text(row.get("url") or row.get("link")),
        "source": "longbridge.filing",
        "retrieved_at": now_utc_iso(),
    }
    for key in ("period", "report_period", "fiscal_period", "accession_no", "source_path"):
        if row.get(key) not in (None, "", [], {}):
            normalized[key] = row[key]
    return {key: value for key, value in normalized.items() if value not in (None, "", [], {})}


def collect_filings(
    tickers: list[str],
    *,
    longbridge_binary: str,
    runner: Runner | None,
    filing_count: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filings: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for ticker in tickers:
        payload, status = run_longbridge_json(
            longbridge_binary,
            ["filing", ticker, "--count", str(max(1, filing_count)), "--format", "json"],
            runner=runner,
            timeout=timeout,
        )
        status["artifact"] = "longbridge-filings"
        status["ticker"] = ticker
        statuses.append(status)
        if payload is None or status.get("status") != "ok":
            continue
        filings.extend(normalize_filing_row(row, ticker) for row in payload_rows(payload))
    return filings, statuses


def normalize_longbridge_ownership_row(row: dict[str, Any], ticker: str, *, source_kind: str) -> dict[str, Any]:
    normalized = {key: value for key, value in row.items() if value not in (None, "", [], {})}
    normalized["ticker"] = normalize_symbol(row.get("ticker") or row.get("symbol") or row.get("code")) or ticker
    normalized["source"] = f"longbridge.{source_kind}"
    normalized["source_kind"] = source_kind
    normalized["retrieved_at"] = now_utc_iso()
    return normalized


def collect_ownership_positioning(
    tickers: list[str],
    *,
    longbridge_binary: str,
    runner: Runner | None,
    ownership_count: int,
    timeout: float,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    artifacts: dict[str, list[dict[str, Any]]] = {
        "shareholders": [],
        "fund_holders": [],
        "insider_trades": [],
        "short_positions": [],
    }
    ownership_records: list[dict[str, Any]] = []
    positioning_flows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []

    def collect_rows(
        *,
        artifact_key: str,
        artifact_name: str,
        source_kind: str,
        command: list[str],
        ticker: str,
        include_in_ownership: bool,
        include_in_positioning: bool,
    ) -> None:
        payload, status = run_longbridge_json(
            longbridge_binary,
            command,
            runner=runner,
            timeout=timeout,
        )
        status["artifact"] = artifact_name
        status["ticker"] = ticker
        status["source_kind"] = source_kind
        statuses.append(status)
        if payload is None or status.get("status") != "ok":
            return
        rows = [
            normalize_longbridge_ownership_row(row, ticker, source_kind=source_kind)
            for row in payload_rows(payload)
        ]
        artifacts[artifact_key].extend(rows)
        if include_in_ownership:
            ownership_records.extend(rows)
        if include_in_positioning:
            positioning_flows.extend(rows)

    for ticker in tickers:
        collect_rows(
            artifact_key="shareholders",
            artifact_name="longbridge-shareholders",
            source_kind="shareholder",
            command=["shareholder", ticker, "--format", "json"],
            ticker=ticker,
            include_in_ownership=True,
            include_in_positioning=False,
        )
        collect_rows(
            artifact_key="fund_holders",
            artifact_name="longbridge-fund-holders",
            source_kind="fund_holder",
            command=["fund-holder", ticker, "--count", str(ownership_count), "--format", "json"],
            ticker=ticker,
            include_in_ownership=True,
            include_in_positioning=False,
        )
        if not is_us_symbol(ticker):
            continue
        collect_rows(
            artifact_key="insider_trades",
            artifact_name="longbridge-insider-trades",
            source_kind="insider_trade",
            command=["insider-trades", ticker, "--count", str(ownership_count), "--format", "json"],
            ticker=ticker,
            include_in_ownership=True,
            include_in_positioning=False,
        )
        collect_rows(
            artifact_key="short_positions",
            artifact_name="longbridge-short-positions",
            source_kind="short_position",
            command=["short-positions", ticker, "--count", str(ownership_count), "--format", "json"],
            ticker=ticker,
            include_in_ownership=False,
            include_in_positioning=True,
        )
    return artifacts, ownership_records, positioning_flows, statuses


def attach_ticker_to_payload(payload: Any, ticker: str) -> Any:
    if isinstance(payload, list):
        return [attach_ticker_to_payload(row, ticker) for row in payload]
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    if not clean_text(normalized.get("ticker") or normalized.get("symbol") or normalized.get("code")):
        normalized["ticker"] = ticker
    for key in (
        "items",
        "ratings",
        "institution_ratings",
        "institution_rating",
        "income_statement",
        "balance_sheet",
        "cash_flow",
        "statements",
        "financial_reports",
        "operating",
        "operating_reviews",
        "indicators",
        "industry_valuation",
        "industry_valuations",
        "peer_valuation",
        "peer_valuations",
        "peers",
        "forecast_eps",
        "eps_forecasts",
        "forecasts",
        "estimates",
        "consensus",
        "consensus_estimates",
        "rows",
        "data",
        "results",
        "list",
    ):
        value = normalized.get(key)
        if isinstance(value, (list, dict)):
            normalized[key] = attach_ticker_to_payload(value, ticker)
    return normalized


def compact_expectation_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in (None, "", [], {})}


def expectation_value_is_meaningful(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) != 0.0
    if isinstance(value, str):
        return bool(clean_text(value))
    if isinstance(value, list):
        return any(expectation_value_is_meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(expectation_value_is_meaningful(item) for item in value.values())
    return True


def expectation_row_has_meaningful_payload(row: dict[str, Any]) -> bool:
    payload = {key: value for key, value in row.items() if key not in EXPECTATION_METADATA_KEYS}
    return any(expectation_value_is_meaningful(value) for value in payload.values())


def iter_expectation_rows(value: Any, row_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict) and compact_expectation_row(row)]
    if not isinstance(value, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in row_keys:
        nested = value.get(key)
        if nested is value:
            continue
        nested_rows = iter_expectation_rows(nested, row_keys)
        if nested_rows:
            rows.extend(nested_rows)
    if rows:
        return rows
    compacted = compact_expectation_row(value)
    return [compacted] if compacted else []


def expectation_payload_has_meaningful_evidence(payload: Any, row_keys: tuple[str, ...]) -> bool:
    return any(expectation_row_has_meaningful_payload(row) for row in iter_expectation_rows(payload, row_keys))


def collect_expectation_artifacts(
    tickers: list[str],
    *,
    output_root: Path,
    longbridge_binary: str,
    runner: Runner | None,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    artifacts: dict[str, Any] = {}
    output_paths: dict[str, str] = {}
    statuses: list[dict[str, Any]] = []
    for spec in EXPECTATION_SOURCE_SPECS:
        kind = clean_text(spec.get("kind"))
        command = clean_text(spec.get("command"))
        artifact_name = clean_text(spec.get("artifact"))
        filename = clean_text(spec.get("filename"))
        evidence_key = clean_text(spec.get("evidence_key"))
        row_keys = tuple(spec.get("row_keys") or ())
        payloads: list[Any] = []
        evidence_payloads: list[Any] = []
        for ticker in tickers:
            payload, status = run_longbridge_json(
                longbridge_binary,
                [command, ticker, "--format", "json"],
                runner=runner,
                timeout=timeout,
            )
            status["artifact"] = artifact_name
            status["ticker"] = ticker
            status["source_kind"] = kind
            statuses.append(status)
            if payload is not None and status.get("status") == "ok":
                attributed_payload = attach_ticker_to_payload(payload, ticker)
                payloads.append(attributed_payload)
                if expectation_payload_has_meaningful_evidence(attributed_payload, row_keys):
                    evidence_payloads.append(attributed_payload)
        if len(payloads) == 1:
            artifact_payload: Any = payloads[0]
        else:
            artifact_payload = payloads
        write_json(output_root / filename, artifact_payload)
        output_paths[kind] = str(output_root / filename)
        if evidence_payloads:
            artifacts[evidence_key] = evidence_payloads[0] if len(evidence_payloads) == 1 else evidence_payloads
    return artifacts, output_paths, statuses


def collect_fundamental_artifacts(
    tickers: list[str],
    *,
    output_root: Path,
    longbridge_binary: str,
    runner: Runner | None,
    timeout: float,
    include_fundamentals: bool,
    include_industry_valuation: bool,
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]], dict[str, int]]:
    artifacts: dict[str, Any] = {}
    output_paths: dict[str, str] = {}
    statuses: list[dict[str, Any]] = []
    counts = {
        "financial_report_count": 0,
        "operating_review_count": 0,
        "industry_valuation_count": 0,
    }

    fundamentals: dict[str, list[Any]] = {}
    specs: list[dict[str, Any]] = list(FUNDAMENTAL_SOURCE_SPECS) if include_fundamentals else []
    if include_industry_valuation:
        specs.append(INDUSTRY_VALUATION_SOURCE_SPEC)

    for spec in specs:
        kind = clean_text(spec.get("kind"))
        command = clean_text(spec.get("command"))
        command_args = [clean_text(item) for item in spec.get("command_args") or () if clean_text(item)]
        artifact_name = clean_text(spec.get("artifact"))
        filename = clean_text(spec.get("filename"))
        row_keys = tuple(spec.get("row_keys") or ())
        payloads: list[Any] = []
        evidence_payloads: list[Any] = []
        for ticker in tickers:
            payload, status = run_longbridge_json(
                longbridge_binary,
                [command, ticker, *command_args, "--format", "json"],
                runner=runner,
                timeout=timeout,
            )
            status["artifact"] = artifact_name
            status["ticker"] = ticker
            status["source_kind"] = kind
            statuses.append(status)
            if payload is None or status.get("status") != "ok":
                continue
            attributed_payload = attach_ticker_to_payload(payload, ticker)
            payloads.append(attributed_payload)
            if expectation_payload_has_meaningful_evidence(attributed_payload, row_keys):
                evidence_payloads.append(attributed_payload)
        artifact_payload: Any = payloads[0] if len(payloads) == 1 else payloads
        write_json(output_root / filename, artifact_payload)
        output_paths[kind] = str(output_root / filename)
        if not evidence_payloads:
            continue
        if kind == "industry_valuation":
            artifacts["industry_valuation"] = evidence_payloads
            counts["industry_valuation_count"] = len(evidence_payloads)
        elif kind == "financial_reports":
            fundamentals["financial_reports"] = evidence_payloads
            counts["financial_report_count"] = len(evidence_payloads)
        elif kind == "operating_reviews":
            fundamentals["operating_reviews"] = evidence_payloads
            counts["operating_review_count"] = len(evidence_payloads)

    if fundamentals:
        artifacts["fundamentals"] = fundamentals
    return artifacts, output_paths, statuses, counts


COMPLETION_ROW_KEYS = (
    "items",
    "ratings",
    "institution_ratings",
    "institution_rating",
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "statements",
    "financial_reports",
    "operating",
    "operating_reviews",
    "indicators",
    "industry_valuation",
    "industry_valuations",
    "peer_valuation",
    "peer_valuations",
    "peers",
    "forecast_eps",
    "eps_forecasts",
    "forecasts",
    "estimates",
    "consensus",
    "consensus_estimates",
    "rows",
    "data",
    "results",
    "list",
)


def row_matches_ticker(row: dict[str, Any], ticker: str) -> bool:
    return normalize_symbol(row.get("ticker") or row.get("symbol") or row.get("code")) == ticker


def rows_for_ticker(rows: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    return [row for row in rows if row_matches_ticker(row, ticker)]


def count_completion_artifact_rows(value: Any, ticker: str) -> int:
    return sum(
        1
        for row in iter_expectation_rows(value, COMPLETION_ROW_KEYS)
        if row_matches_ticker(row, ticker) and expectation_row_has_meaningful_payload(row)
    )


def latest_source_title(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    sorted_rows = sorted(
        rows,
        key=lambda row: parse_datetime_value(
            row.get("published_at")
            or row.get("publish_time")
            or row.get("filed_at")
            or row.get("filing_date")
            or row.get("date")
            or row.get("time")
            or row.get("retrieved_at")
        )
        or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return clean_text(sorted_rows[0].get("title") or sorted_rows[0].get("headline") or sorted_rows[0].get("name"))


def detail_completion_status(detail_counts: dict[str, int]) -> str:
    if detail_counts.get("usable", 0):
        return "covered"
    if detail_counts.get("error", 0):
        return "error"
    if detail_counts.get("stale", 0):
        return "stale"
    if detail_counts.get("empty", 0):
        return "empty"
    if detail_counts.get("unattributed", 0):
        return "unattributed"
    return "missing"


def build_information_completion_index(
    tickers: list[str],
    *,
    quote_rows: list[dict[str, Any]],
    headlines: list[dict[str, Any]],
    details: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    filings: list[dict[str, Any]],
    capital_flows: list[dict[str, Any]],
    expectation_artifacts: dict[str, Any],
    fundamental_artifacts: dict[str, Any],
    reference_time: datetime | None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        ticker_quotes = rows_for_ticker(quote_rows, ticker)
        ticker_headlines = rows_for_ticker(headlines, ticker)
        ticker_details = rows_for_ticker(details, ticker)
        ticker_topics = rows_for_ticker(topics, ticker)
        ticker_filings = rows_for_ticker(filings, ticker)
        ticker_capital_flows = rows_for_ticker(capital_flows, ticker)
        detail_counts = longbridge_detail_quality_counts(ticker_details, reference_time=reference_time)
        ticker_detail_error_kinds = detail_error_kinds(ticker_details)
        source_counts = {
            "quote": len(ticker_quotes),
            "news_headline": len(ticker_headlines),
            "news_detail": detail_counts["usable"],
            "topic": len(ticker_topics),
            "filing": len(ticker_filings),
            "capital_flow": len(ticker_capital_flows),
            "expectation": sum(
                count_completion_artifact_rows(value, ticker) for value in expectation_artifacts.values()
            ),
            "fundamental": sum(
                count_completion_artifact_rows(value, ticker) for value in fundamental_artifacts.values()
            ),
        }
        covered_source_types = [source for source, count in source_counts.items() if count]
        fallback_source_types = [
            source
            for source in covered_source_types
            if source not in {"quote", "news_detail"}
        ]
        supplemental_count = sum(count for source, count in source_counts.items() if source != "quote")
        status = "complete" if supplemental_count else "partial" if source_counts["quote"] else "missing"
        row = {
            "ticker": ticker,
            "status": status,
            "covered_source_types": covered_source_types,
            "fallback_source_types": fallback_source_types,
            "quote_status": "covered" if source_counts["quote"] else "missing",
            "news_headline_count": source_counts["news_headline"],
            "news_detail_status": detail_completion_status(detail_counts),
            "news_detail_usable_count": detail_counts["usable"],
            "news_detail_error_count": detail_counts["error"],
            "news_detail_error_kinds": ticker_detail_error_kinds,
            "news_detail_transport_error_count": detail_transport_error_count(ticker_details),
            "news_detail_retry_exhausted_count": detail_retry_exhausted_count(ticker_details),
            "news_detail_stale_count": detail_counts["stale"],
            "news_detail_empty_count": detail_counts["empty"],
            "topic_count": source_counts["topic"],
            "filing_count": source_counts["filing"],
            "capital_flow_count": source_counts["capital_flow"],
            "expectation_count": source_counts["expectation"],
            "fundamental_count": source_counts["fundamental"],
            "latest_news_title": latest_source_title(ticker_headlines),
            "latest_filing_title": latest_source_title(ticker_filings),
            "latest_topic_title": latest_source_title(ticker_topics),
        }
        rows.append({key: value for key, value in row.items() if value not in (None, "", [], {})})
    summary = {
        "ticker_count": len(rows),
        "complete_count": sum(1 for row in rows if row.get("status") == "complete"),
        "partial_count": sum(1 for row in rows if row.get("status") == "partial"),
        "missing_count": sum(1 for row in rows if row.get("status") == "missing"),
        "headline_fallback_count": sum(1 for row in rows if "news_headline" in safe_completion_list(row.get("fallback_source_types"))),
        "filing_fallback_count": sum(1 for row in rows if "filing" in safe_completion_list(row.get("fallback_source_types"))),
        "detail_covered_count": sum(1 for row in rows if row.get("news_detail_status") == "covered"),
        "detail_error_count": sum(1 for row in rows if row.get("news_detail_error_count")),
    }
    return {
        "schema_version": "information_completion_index/v1",
        "summary": summary,
        "rows": rows,
    }


def safe_completion_list(value: Any) -> list[str]:
    return [clean_text(item) for item in (value if isinstance(value, list) else []) if clean_text(item)]


def collect_longbridge_plan_sources(
    payloads: list[Any],
    *,
    output_dir: str | Path,
    longbridge_binary: str = "longbridge",
    runner: Runner | None = None,
    target_date: str = "",
    news_count: int = 3,
    detail_limit_per_ticker: int = 2,
    include_capital: bool = True,
    include_expectations: bool = True,
    include_filings: bool = True,
    filing_count: int = 5,
    include_ownership: bool = True,
    ownership_count: int = 20,
    include_topics: bool = True,
    topic_count: int = 5,
    include_fundamentals: bool = True,
    include_industry_valuation: bool = True,
    markets: list[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    lang: str = "zh-CN",
    reuse_existing_artifacts: bool = False,
) -> dict[str, Any]:
    started_at_monotonic = time.monotonic()
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    tickers = collect_plan_tickers(payloads)
    retrieved_at = now_utc_iso()
    reference_time = parse_datetime_value(target_date) or parse_datetime_value(retrieved_at)
    statuses: list[dict[str, Any]] = []

    quotes_payload = None
    quote_status: dict[str, Any] | None = None
    if reuse_existing_artifacts:
        quotes_payload, quote_status = load_reusable_json_artifact(
            output_root / "longbridge-quotes.json",
            "longbridge-quotes",
        )
    if quote_status is not None:
        statuses.append(quote_status)
    if quotes_payload is None:
        quotes_payload, quote_status = run_longbridge_json(
            longbridge_binary,
            ["quote", *tickers, "--format", "json"] if tickers else ["quote", "--format", "json"],
            runner=runner,
            timeout=timeout,
        )
        quote_status["artifact"] = "longbridge-quotes"
        statuses.append(quote_status)
    quote_rows = payload_rows(quotes_payload)
    write_json(output_root / "longbridge-quotes.json", quote_rows if quote_rows else (quotes_payload or []))

    headlines: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    reused_headlines = None
    reused_details = None
    headline_status: dict[str, Any] | None = None
    detail_status: dict[str, Any] | None = None
    if reuse_existing_artifacts:
        reused_headlines, headline_status = load_reusable_json_artifact(
            output_root / "longbridge-news-headlines.json",
            "longbridge-news-headlines",
        )
        reused_details, detail_status = load_reusable_json_artifact(
            output_root / "longbridge-news-details.json",
            "longbridge-news-details",
        )
        if reused_details is not None:
            reused_detail_rows = payload_rows(reused_details, keys=("data", "items", "news", "rows"))
            reused_detail_quality = longbridge_detail_quality_counts(
                reused_detail_rows,
                reference_time=reference_time,
            )
            if detail_limit_per_ticker > 0 and tickers and reused_detail_quality["usable"] == 0:
                if headline_status is not None and clean_text(headline_status.get("status")) == "reused":
                    headline_status = {
                        **headline_status,
                        "status": "reuse_skipped",
                        "reuse_reason": "paired_news_details_unusable",
                        "reuse_skip_reason": "paired_news_details_unusable",
                    }
                if detail_status is not None and clean_text(detail_status.get("status")) == "reused":
                    detail_status = {
                        **detail_status,
                        "status": "reuse_skipped",
                        "reuse_reason": "no_usable_news_detail",
                        "reuse_skip_reason": "no_usable_news_detail",
                        "detail_usable_count": reused_detail_quality["usable"],
                        "detail_error_count": reused_detail_quality["error"],
                        "detail_unattributed_count": reused_detail_quality["unattributed"],
                        "detail_stale_count": reused_detail_quality["stale"],
                        "detail_empty_count": reused_detail_quality["empty"],
                    }
                reused_headlines = None
                reused_details = None
    if headline_status is not None:
        statuses.append(headline_status)
    if detail_status is not None:
        statuses.append(detail_status)
    if reused_headlines is not None and reused_details is not None:
        headlines = payload_rows(reused_headlines, keys=("data", "items", "news", "rows"))
        details = payload_rows(reused_details, keys=("data", "items", "news", "rows"))
    else:
        headlines, details, news_statuses = collect_news(
            tickers,
            longbridge_binary=longbridge_binary,
            runner=runner,
            news_count=news_count,
            detail_limit_per_ticker=detail_limit_per_ticker,
            timeout=timeout,
            lang=lang,
            reference_time=reference_time,
        )
        statuses.extend(news_statuses)
    write_json(output_root / "longbridge-news-headlines.json", headlines)
    write_json(output_root / "longbridge-news-details.json", details)

    market_status_payload, market_status = run_longbridge_json(
        longbridge_binary,
        ["market-status", "--format", "json"],
        runner=runner,
        timeout=timeout,
    )
    market_status["artifact"] = "longbridge-market-status"
    statuses.append(market_status)
    write_json(output_root / "longbridge-market-status.json", market_status_payload or {})

    market_temp_payloads: dict[str, Any] = {}
    for market in unique_strings(markets or ["CN"]):
        payload, status = run_longbridge_json(
            longbridge_binary,
            ["market-temp", market, "--format", "json"],
            runner=runner,
            timeout=timeout,
        )
        status["artifact"] = "longbridge-market-temp"
        status["market"] = market
        statuses.append(status)
        if payload is not None:
            market_temp_payloads[market] = payload
    write_json(output_root / "longbridge-market-temp.json", market_temp_payloads)

    capital_flows: list[dict[str, Any]] = []
    if include_capital:
        capital_flows, capital_statuses = collect_capital_flows(
            tickers,
            longbridge_binary=longbridge_binary,
            runner=runner,
            timeout=timeout,
        )
        statuses.extend(capital_statuses)
        write_json(output_root / "longbridge-capital-flow.json", capital_flows)

    topics: list[dict[str, Any]] = []
    if include_topics:
        topics, topic_statuses = collect_topics(
            tickers,
            longbridge_binary=longbridge_binary,
            runner=runner,
            topic_count=topic_count,
            timeout=timeout,
        )
        statuses.extend(topic_statuses)
        write_json(output_root / "longbridge-topics.json", topics)

    filings: list[dict[str, Any]] = []
    if include_filings:
        filings, filing_statuses = collect_filings(
            tickers,
            longbridge_binary=longbridge_binary,
            runner=runner,
            filing_count=filing_count,
            timeout=timeout,
        )
        statuses.extend(filing_statuses)
        write_json(output_root / "longbridge-filings.json", filings)

    ownership_records: list[dict[str, Any]] = []
    positioning_flows: list[dict[str, Any]] = []
    ownership_output_paths: dict[str, str] = {}
    if include_ownership:
        ownership_artifacts, ownership_records, positioning_flows, ownership_statuses = collect_ownership_positioning(
            tickers,
            longbridge_binary=longbridge_binary,
            runner=runner,
            ownership_count=ownership_count,
            timeout=timeout,
        )
        statuses.extend(ownership_statuses)
        ownership_filenames = {
            "shareholders": "longbridge-shareholders.json",
            "fund_holders": "longbridge-fund-holders.json",
            "insider_trades": "longbridge-insider-trades.json",
            "short_positions": "longbridge-short-positions.json",
        }
        for key, filename in ownership_filenames.items():
            write_json(output_root / filename, ownership_artifacts.get(key, []))
            ownership_output_paths[key] = str(output_root / filename)

    expectation_artifacts: dict[str, Any] = {}
    expectation_output_paths: dict[str, str] = {}
    if include_expectations:
        expectation_artifacts, expectation_output_paths, expectation_statuses = collect_expectation_artifacts(
            tickers,
            output_root=output_root,
            longbridge_binary=longbridge_binary,
            runner=runner,
            timeout=timeout,
        )
        statuses.extend(expectation_statuses)

    fundamental_artifacts, fundamental_output_paths, fundamental_statuses, fundamental_counts = collect_fundamental_artifacts(
        tickers,
        output_root=output_root,
        longbridge_binary=longbridge_binary,
        runner=runner,
        timeout=timeout,
        include_fundamentals=include_fundamentals,
        include_industry_valuation=include_industry_valuation,
    )
    statuses.extend(fundamental_statuses)

    information_completion_index = build_information_completion_index(
        tickers,
        quote_rows=quote_rows,
        headlines=headlines,
        details=details,
        topics=topics,
        filings=filings,
        capital_flows=capital_flows,
        expectation_artifacts=expectation_artifacts,
        fundamental_artifacts=fundamental_artifacts,
        reference_time=reference_time,
    )
    write_json(output_root / "longbridge-information-completion-index.json", information_completion_index)
    completion_summary = (
        information_completion_index.get("summary")
        if isinstance(information_completion_index.get("summary"), dict)
        else {}
    )
    detail_ok_count = sum(1 for row in details if clean_text(row.get("fetch_status")).lower() == "ok")
    detail_error_count = sum(1 for row in details if clean_text(row.get("fetch_status")).lower() not in {"", "ok"})
    detail_quality_counts = longbridge_detail_quality_counts(
        details,
        reference_time=reference_time,
    )
    detail_kinds = detail_error_kinds(details)
    usable_detail_tickers = {
        clean_text(row.get("ticker"))
        for row in details
        if clean_text(row.get("ticker")) and longbridge_detail_quality_counts([row], reference_time=reference_time)["usable"]
    }
    source_error_count = 0
    recovered_source_error_count = 0
    counted_error_keys: set[tuple[str, str, str, str]] = set()
    for row in statuses:
        if clean_text(row.get("status")) in {"ok", "empty", "reused", "reuse_skipped", "cache_hit"}:
            continue
        artifact = clean_text(row.get("artifact"))
        ticker = clean_text(row.get("ticker"))
        news_id = clean_text(row.get("news_id"))
        if artifact == "longbridge-news-details" and ticker and news_id:
            error_key = (artifact, ticker, news_id, clean_text(row.get("cached_status")) or "direct")
            if error_key in counted_error_keys:
                continue
            counted_error_keys.add(error_key)
        if clean_text(row.get("artifact")) == "longbridge-news-details" and clean_text(row.get("ticker")) in usable_detail_tickers:
            recovered_source_error_count += 1
        else:
            source_error_count += 1
    source_quality = (
        "ok"
        if source_error_count == 0
        and detail_quality_counts["usable"] == detail_ok_count
        and detail_quality_counts["error"] == 0
        and detail_quality_counts["unattributed"] == 0
        and detail_quality_counts["stale"] == 0
        and detail_quality_counts["empty"] == 0
        else "partial"
    )
    runtime_seconds = round(time.monotonic() - started_at_monotonic, 3)
    summary = {
        "ticker_count": len(tickers),
        "quote_row_count": len(quote_rows),
        "news_headline_count": len(headlines),
        "news_detail_count": len(details),
        "news_detail_ok_count": detail_ok_count,
        "news_detail_error_count": detail_error_count,
        "news_detail_error_kinds": detail_kinds,
        "news_detail_transport_error_count": detail_transport_error_count(details),
        "news_detail_retry_exhausted_count": detail_retry_exhausted_count(details),
        "news_detail_cache_hit_count": sum(
            1
            for row in statuses
            if clean_text(row.get("artifact")) == "longbridge-news-details"
            and clean_text(row.get("status")) == "cache_hit"
        ),
        "news_detail_language_fallback_success_count": sum(
            1
            for row in details
            if clean_text(row.get("fetch_status")).lower() == "ok"
            and bool(row.get("fetch_language_fallback"))
        ),
        "news_detail_html_fallback_success_count": sum(
            1
            for row in details
            if clean_text(row.get("fetch_status")).lower() == "ok"
            and clean_text(row.get("source")) == "longbridge.news.detail.html"
        ),
        "news_detail_usable_count": detail_quality_counts["usable"],
        "news_detail_unattributed_count": detail_quality_counts["unattributed"],
        "news_detail_stale_count": detail_quality_counts["stale"],
        "news_detail_empty_count": detail_quality_counts["empty"],
        "capital_flow_count": len(capital_flows),
        "topic_count": len(topics),
        "filing_count": len(filings),
        "ownership_record_count": len(ownership_records),
        "short_position_count": len(positioning_flows),
        "expectation_artifact_count": len(expectation_artifacts),
        "expectation_source_kinds": sorted(expectation_artifacts),
        **fundamental_counts,
        "source_error_count": source_error_count,
        "recovered_source_error_count": recovered_source_error_count,
        "longbridge_plan_source_quality": source_quality,
        "information_completion_ticker_count": completion_summary.get("ticker_count", 0),
        "information_completion_complete_count": completion_summary.get("complete_count", 0),
        "information_completion_partial_count": completion_summary.get("partial_count", 0),
        "information_completion_missing_count": completion_summary.get("missing_count", 0),
        "artifact_reuse_count": sum(1 for row in statuses if clean_text(row.get("status")) == "reused"),
        "runtime_seconds": runtime_seconds,
    }
    evidence_path = output_root / "longbridge-institutional-evidence.json"
    evidence = {
        "schema_version": "longbridge-institutional-evidence/v1",
        "source_path": str(evidence_path),
        "target_date": clean_text(target_date),
        "retrieved_at": retrieved_at,
        "tickers": tickers,
        "market_context": {
            "schema_version": "longbridge-market-context/v1",
            "source": "longbridge",
            "retrieved_at": retrieved_at,
            "market_status": market_status_payload or {},
            "market_temperature": market_temp_payloads,
        },
        "longbridge_market_session_index": market_status_payload or {},
        "longbridge_market_temperature": market_temp_payloads,
        "news": details if details else headlines,
        "longbridge_news_headlines": headlines,
        "longbridge_news_details": details,
        "capital_flows": capital_flows,
        "social_evidence": topics,
        "filings": filings,
        "ownership": {"records": ownership_records},
        "positioning_flows": positioning_flows,
        "information_completion_index": information_completion_index,
        **expectation_artifacts,
        **fundamental_artifacts,
        "source_health": {
            "longbridge_plan_sources": source_quality,
            "source_error_count": source_error_count,
            "longbridge_filing_count": len(filings),
            "longbridge_topic_count": len(topics),
            "longbridge_ownership_record_count": len(ownership_records),
            "longbridge_short_position_count": len(positioning_flows),
            "news_detail_usable_count": detail_quality_counts["usable"],
            "news_detail_language_fallback_success_count": sum(
                1
                for row in details
                if clean_text(row.get("fetch_status")).lower() == "ok"
                and bool(row.get("fetch_language_fallback"))
            ),
            "news_detail_html_fallback_success_count": sum(
                1
                for row in details
                if clean_text(row.get("fetch_status")).lower() == "ok"
                and clean_text(row.get("source")) == "longbridge.news.detail.html"
            ),
            "news_detail_unattributed_count": detail_quality_counts["unattributed"],
            "news_detail_stale_count": detail_quality_counts["stale"],
            "news_detail_empty_count": detail_quality_counts["empty"],
            "longbridge_expectation_source_count": len(expectation_artifacts),
            "longbridge_expectation_source_kinds": sorted(expectation_artifacts),
            "longbridge_financial_report_count": fundamental_counts["financial_report_count"],
            "longbridge_operating_review_count": fundamental_counts["operating_review_count"],
            "longbridge_industry_valuation_count": fundamental_counts["industry_valuation_count"],
            "information_completion_ticker_count": completion_summary.get("ticker_count", 0),
            "information_completion_complete_count": completion_summary.get("complete_count", 0),
            "information_completion_partial_count": completion_summary.get("partial_count", 0),
            "information_completion_missing_count": completion_summary.get("missing_count", 0),
            "artifact_reuse_count": summary["artifact_reuse_count"],
            "runtime_seconds": runtime_seconds,
        },
        "summary": summary,
        "command_statuses": statuses,
    }
    write_json(evidence_path, evidence)
    result = {
        "schema_version": "longbridge-plan-source-run/v1",
        "target_date": clean_text(target_date),
        "retrieved_at": retrieved_at,
        "tickers": tickers,
        "output_dir": str(output_root),
        "summary": summary,
        "information_completion_index": information_completion_index,
        "output_paths": {
            "quotes": str(output_root / "longbridge-quotes.json"),
            "news": str(output_root / "longbridge-news-headlines.json"),
            "news_details": str(output_root / "longbridge-news-details.json"),
            "information_completion_index": str(output_root / "longbridge-information-completion-index.json"),
            "market_status": str(output_root / "longbridge-market-status.json"),
            "market_temperature": str(output_root / "longbridge-market-temp.json"),
            "capital_flows": str(output_root / "longbridge-capital-flow.json") if include_capital else "",
            "topics": str(output_root / "longbridge-topics.json") if include_topics else "",
            "filings": str(output_root / "longbridge-filings.json") if include_filings else "",
            **ownership_output_paths,
            **expectation_output_paths,
            **fundamental_output_paths,
            "institutional_evidence": str(evidence_path),
            "plan_source_run": str(output_root / "longbridge-plan-source-run.json"),
        },
        "command_statuses": statuses,
    }
    write_json(output_root / "longbridge-plan-source-run.json", result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Longbridge source artifacts for a trading-plan or stock-pool run.")
    parser.add_argument("--input", action="append", default=[], help="Trading-plan result, local stock-pool, or manager package JSON.")
    parser.add_argument("--output-dir", required=True, help="Directory to write standard Longbridge artifacts.")
    parser.add_argument("--longbridge-binary", default="longbridge", help="Longbridge CLI binary path.")
    parser.add_argument("--target-date", default="", help="Target trade date for metadata.")
    parser.add_argument("--news-count", type=int, default=3, help="Headlines to fetch per ticker.")
    parser.add_argument("--detail-limit-per-ticker", type=int, default=2, help="News detail rows to fetch per ticker.")
    parser.add_argument("--market", action="append", default=None, help="Market-temp market code; can be repeated.")
    parser.add_argument("--no-capital", action="store_true", help="Skip Longbridge capital-flow collection.")
    parser.add_argument("--topic-count", type=int, default=5, help="Community topic rows to fetch per ticker.")
    parser.add_argument("--no-topics", action="store_true", help="Skip Longbridge topic/community collection.")
    parser.add_argument("--filing-count", type=int, default=5, help="Regulatory filings to fetch per ticker.")
    parser.add_argument("--no-filings", action="store_true", help="Skip Longbridge filing collection.")
    parser.add_argument("--ownership-count", type=int, default=20, help="Fund-holder, insider-trade, and short-position rows to fetch per ticker.")
    parser.add_argument("--no-ownership", action="store_true", help="Skip Longbridge shareholder/fund/insider/short-position collection.")
    parser.add_argument("--no-expectations", action="store_true", help="Skip Longbridge valuation/rating/forecast/consensus collection.")
    parser.add_argument("--no-fundamentals", action="store_true", help="Skip Longbridge financial-report and operating collection.")
    parser.add_argument("--no-industry-valuation", action="store_true", help="Skip Longbridge industry valuation collection.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Per-command Longbridge timeout in seconds.")
    parser.add_argument("--lang", default="zh-CN", help="Longbridge content language for news detail.")
    parser.add_argument(
        "--reuse-existing-artifacts",
        action="store_true",
        help="Reuse existing quotes/news/news-detail artifacts in output-dir before making live Longbridge calls.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payloads = load_input_payloads(args.input)
    if not payloads:
        raise SystemExit("at least one --input JSON payload is required")
    result = collect_longbridge_plan_sources(
        payloads,
        output_dir=args.output_dir,
        longbridge_binary=args.longbridge_binary,
        target_date=args.target_date,
        news_count=args.news_count,
        detail_limit_per_ticker=args.detail_limit_per_ticker,
        include_capital=not args.no_capital,
        include_topics=not args.no_topics,
        topic_count=args.topic_count,
        include_filings=not args.no_filings,
        filing_count=args.filing_count,
        include_ownership=not args.no_ownership,
        ownership_count=args.ownership_count,
        include_expectations=not args.no_expectations,
        include_fundamentals=not args.no_fundamentals,
        include_industry_valuation=not args.no_industry_valuation,
        markets=args.market,
        timeout=args.timeout,
        lang=args.lang,
        reuse_existing_artifacts=args.reuse_existing_artifacts,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
