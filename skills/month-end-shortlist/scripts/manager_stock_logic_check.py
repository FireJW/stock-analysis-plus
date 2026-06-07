#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text
from manager_html_primitives import safe_dict, safe_list
from manager_pool_merge import normalize_workflow_display_ticker
from manager_ui_summary import stock_bucket_label


LOGIC_CHECK_KEYS = (
    "stock_logic_check",
    "stock_logic_checks",
    "logic_check",
    "logic_checks",
    "logic_review",
    "logic_reviews",
)

PASS_STATUSES = {"pass", "passed", "ok", "covered", "verified", "open", "ready"}
BLOCKED_STATUSES = {"blocked", "block", "fail", "failed", "rejected", "invalid", "unverified"}
PARTIAL_STATUSES = {"partial", "pending", "review", "needs_review", "unknown", "thin"}


def normalize_logic_check_status(value: Any) -> str:
    status = clean_text(value).lower()
    if status in PASS_STATUSES:
        return "pass"
    if status in BLOCKED_STATUSES:
        return "blocked"
    if status in PARTIAL_STATUSES:
        return "partial"
    return "partial" if status else "partial"


def _as_clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = clean_text(value)
        return [text] if text else []
    return clean_string_list(value)


def _stock_lookup(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pool = safe_dict(package.get("local_stock_pool"))
    lookup: dict[str, dict[str, Any]] = {}
    for stock in safe_list(pool.get("stocks")):
        if not isinstance(stock, dict):
            continue
        ticker = normalize_workflow_display_ticker(stock.get("ticker") or stock.get("symbol") or stock.get("code"))
        if ticker:
            lookup[ticker] = stock
    return lookup


def _iter_logic_check_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("rows", "items", "checks", "stocks", "candidates"):
        rows = value.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    by_ticker = value.get("by_ticker")
    if isinstance(by_ticker, dict):
        rows: list[dict[str, Any]] = []
        for ticker, row in by_ticker.items():
            if not isinstance(row, dict):
                continue
            rows.append({"ticker": ticker, **row})
        return rows
    if any(clean_text(value.get(key)) for key in ("ticker", "symbol", "code", "name", "status", "rationale")):
        return [value]
    return []


def _collect_logic_check_rows(*payloads: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in LOGIC_CHECK_KEYS:
            rows.extend(_iter_logic_check_rows(payload.get(key)))
    return rows


def normalize_stock_logic_check(
    rows: list[dict[str, Any]],
    *,
    package: dict[str, Any],
) -> dict[str, Any]:
    stock_by_ticker = _stock_lookup(package)
    normalized_rows: list[dict[str, Any]] = []
    for raw_row in rows:
        ticker = normalize_workflow_display_ticker(raw_row.get("ticker") or raw_row.get("symbol") or raw_row.get("code"))
        stock = safe_dict(stock_by_ticker.get(ticker))
        plan_snapshot = safe_dict(stock.get("plan_snapshot"))
        name = clean_text(raw_row.get("name") or stock.get("name") or plan_snapshot.get("name"))
        status = normalize_logic_check_status(raw_row.get("status") or raw_row.get("logic_status"))
        row: dict[str, Any] = {
            "ticker": ticker,
            "name": name,
            "status": status,
            "decision": clean_text(raw_row.get("decision"))
            or ("logic_confirmed" if status == "pass" else "research_only_until_logic_check_passes"),
            "bucket": clean_text(raw_row.get("bucket")) or stock_bucket_label(stock),
            "missing": _as_clean_list(raw_row.get("missing") or raw_row.get("blockers")),
            "evidence": _as_clean_list(raw_row.get("evidence") or raw_row.get("sources")),
            "rationale": clean_text(raw_row.get("rationale") or raw_row.get("reason") or raw_row.get("note")),
            "source": clean_text(raw_row.get("source") or raw_row.get("source_path")),
        }
        normalized_rows.append({key: value for key, value in row.items() if value not in ("", None, [], {})})
    if not normalized_rows:
        return {}

    blocked_count = sum(1 for row in normalized_rows if clean_text(row.get("status")) == "blocked")
    partial_count = sum(1 for row in normalized_rows if clean_text(row.get("status")) == "partial")
    pass_count = sum(1 for row in normalized_rows if clean_text(row.get("status")) == "pass")
    status = "blocked" if blocked_count else "partial" if partial_count else "pass"
    return {
        "schema_version": "stock_logic_check/v1",
        "status": status,
        "summary": {
            "checked_count": len(normalized_rows),
            "pass_count": pass_count,
            "partial_count": partial_count,
            "blocked_count": blocked_count,
            "blocked_tickers": [
                clean_text(row.get("ticker"))
                for row in normalized_rows
                if clean_text(row.get("status")) == "blocked" and clean_text(row.get("ticker"))
            ],
        },
        "rows": normalized_rows,
    }


def build_stock_logic_check(
    package: dict[str, Any],
    *payloads: Any,
) -> dict[str, Any]:
    rows = _collect_logic_check_rows(package, *payloads)
    return normalize_stock_logic_check(rows, package=package)


def _status_class(status: str) -> str:
    if status == "pass":
        return "covered"
    if status == "blocked":
        return "blocked"
    return "pending"


def render_stock_logic_check_status(package: dict[str, Any]) -> str:
    logic_check = safe_dict(package.get("stock_logic_check"))
    if not logic_check:
        return ""
    status = clean_text(logic_check.get("status")) or "partial"
    summary = safe_dict(logic_check.get("summary"))
    rows = [row for row in safe_list(logic_check.get("rows")) if isinstance(row, dict)]
    rendered_rows: list[str] = []
    for row in rows[:8]:
        row_status = clean_text(row.get("status")) or "partial"
        identity = " ".join(
            item for item in (clean_text(row.get("ticker")), clean_text(row.get("name"))) if item
        )
        missing = "; ".join(clean_string_list(row.get("missing")))
        evidence = "; ".join(clean_string_list(row.get("evidence")))
        rationale = clean_text(row.get("rationale"))
        detail = " | ".join(part for part in (missing, evidence, rationale) if part) or "logic check attached"
        rendered_rows.append(
            '<div class="source-status-item stock-logic-check-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(clean_text(row.get("ticker")) or "logic")}</span>'
            f'<span class="overview-name">{html.escape(identity or "stock logic check")}</span>'
            "</div>"
            f'<span class="status-pill status-{html.escape(_status_class(row_status))}">{html.escape(row_status)}</span>'
            f'<span class="metric-label">{html.escape(detail)}</span>'
            "</div>"
        )
    return (
        '<section id="stock-logic-check" class="stock-logic-check-status" aria-label="Stock logic check status">'
        '<div class="section-head">'
        "<h2>Logic Check</h2>"
        f'<span class="status-pill status-{html.escape(_status_class(status))}">{html.escape(status)}</span>'
        "</div>"
        '<div class="source-status-body">'
        "<p>Single-name theses are checked before entry-list promotion; failed checks keep the name research-only.</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(clean_text(summary.get("checked_count")) or "0")}</span><span class="metric-label">Checked</span></div>'
        f'<div><span class="metric-value">{html.escape(clean_text(summary.get("blocked_count")) or "0")}</span><span class="metric-label">Blocked</span></div>'
        f'<div><span class="metric-value">{html.escape(clean_text(summary.get("partial_count")) or "0")}</span><span class="metric-label">Partial</span></div>'
        "</div>"
        '<div class="source-status-list stock-logic-check-list">'
        + "".join(rendered_rows)
        + "</div>"
        "</div>"
        "</section>"
    )


__all__ = [
    "build_stock_logic_check",
    "normalize_stock_logic_check",
    "normalize_logic_check_status",
    "render_stock_logic_check_status",
]
