#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
from typing import Any

from local_stock_pool_runtime import normalize_a_share_ticker


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in result:
            result.append(text)
    return result


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_positive_int(value: Any) -> int:
    try:
        coerced = int(to_float(value))
    except (TypeError, ValueError):
        return 0
    return coerced if coerced > 0 else 0


def _finite_float(value: Any) -> float | None:
    number = to_float(value)
    return number if number == number else None


def sector_view_key(value: Any) -> str:
    return clean_text(value).lower()


def classify_sector_breadth_signal(row: dict[str, Any]) -> str:
    explicit = clean_text(row.get("breadth_signal")).lower()
    if explicit in {"broad", "focused", "thin", "ranking_only"}:
        return explicit
    rank = _coerce_positive_int(row.get("rank"))
    day_pct = _finite_float(row.get("day_pct"))
    top_mover_count = _coerce_positive_int(row.get("top_mover_count"))
    near_limit_count = _coerce_positive_int(row.get("near_limit_top_mover_count"))
    if near_limit_count >= 2 or top_mover_count >= 3:
        return "broad"
    if rank and rank <= 5 and day_pct is not None and day_pct >= 2.0:
        return "broad"
    if top_mover_count >= 1:
        return "focused"
    if rank and rank <= 10 and day_pct is not None and day_pct > 0:
        return "focused"
    return "thin"


def normalize_sector_rank_row(raw: dict[str, Any], *, default_sector_type: str = "") -> dict[str, Any]:
    sector_name = clean_text(
        raw.get("sector_name")
        or raw.get("name")
        or raw.get("sector")
        or raw.get("industry")
        or raw.get("f14")
    )
    if not sector_name:
        return {}
    row: dict[str, Any] = {
        "sector_name": sector_name,
        "sector_type": clean_text(raw.get("sector_type") or raw.get("type") or default_sector_type) or "industry",
        "source": clean_text(raw.get("source")) or "eastmoney_sector_rank",
    }
    sector_code = clean_text(raw.get("sector_code") or raw.get("code") or raw.get("f12"))
    if sector_code:
        row["sector_code"] = sector_code
    rank = _coerce_positive_int(raw.get("rank") or raw.get("priority_rank"))
    if rank:
        row["rank"] = rank
    day_pct = _finite_float(
        raw.get("day_pct")
        if raw.get("day_pct") not in (None, "")
        else raw.get("pct")
        if raw.get("pct") not in (None, "")
        else raw.get("f3")
    )
    if day_pct is not None:
        row["day_pct"] = day_pct
    net_inflow = _finite_float(
        raw.get("net_inflow_cny")
        if raw.get("net_inflow_cny") not in (None, "")
        else raw.get("f62")
    )
    if net_inflow is not None:
        row["net_inflow_cny"] = net_inflow
    leader_name = clean_text(raw.get("leader_name") or raw.get("leading_name") or raw.get("f128"))
    if leader_name:
        row["leader_name"] = leader_name
    leader_ticker = clean_text(raw.get("leader_ticker") or raw.get("leading_ticker") or raw.get("f140"))
    if leader_ticker:
        row["leader_ticker"] = leader_ticker
    for key in ("top_mover_count", "positive_top_mover_count", "near_limit_top_mover_count"):
        value = _coerce_positive_int(raw.get(key))
        if value:
            row[key] = value
    row["breadth_signal"] = classify_sector_breadth_signal(row | {"breadth_signal": raw.get("breadth_signal")})
    return row


def normalize_sector_rankings(raw_rows: Any, *, default_sector_type: str = "") -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows, start=1):
        if not isinstance(raw, dict):
            continue
        row = normalize_sector_rank_row(raw, default_sector_type=default_sector_type)
        if not row:
            continue
        if "rank" not in row:
            row["rank"] = index
        normalized.append(row)
    return normalized


def normalize_sector_view(raw: dict[str, Any]) -> dict[str, Any]:
    row = normalize_sector_rank_row(raw, default_sector_type=clean_text(raw.get("sector_type") or raw.get("type")) or "industry")
    if not row:
        return {}
    if not clean_text(raw.get("source")):
        row["source"] = "sector_view"
    aliases = raw.get("aliases") if isinstance(raw.get("aliases"), list) else []
    alias_values = unique_strings([row["sector_name"]] + aliases)
    if alias_values:
        row["aliases"] = alias_values
    row["breadth_signal"] = classify_sector_breadth_signal(row | {"breadth_signal": raw.get("breadth_signal")})
    return row


def normalize_sector_views(raw_rows: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        row = normalize_sector_view(raw)
        key = sector_view_key(row.get("sector_name"))
        if not row or not key or key in seen:
            continue
        normalized.append(row)
        seen.add(key)
    return normalized


def merge_sector_view_inputs(
    request_views: list[dict[str, Any]] | None,
    ranking_views: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for row in normalize_sector_views(list(request_views or []) + list(ranking_views or [])):
        key = sector_view_key(row.get("sector_name"))
        if not key:
            continue
        if key not in by_key:
            by_key[key] = deepcopy(row)
            merged.append(by_key[key])
            continue
        existing = by_key[key]
        for field, value in row.items():
            if field not in existing or existing.get(field) in (None, "", []):
                existing[field] = value
    return merged


def build_sector_views_from_rankings(rankings: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows = normalize_sector_rankings(rankings or [])
    return normalize_sector_views(rows)


def sector_name_from_market_strength_row(raw: dict[str, Any]) -> str:
    return clean_text(raw.get("sector") or raw.get("industry") or raw.get("f100"))


def sector_view_lookup(sector_views: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for view in normalize_sector_views(sector_views or []):
        names = view.get("aliases") if isinstance(view.get("aliases"), list) else []
        for name in unique_strings([view.get("sector_name")] + names):
            key = sector_view_key(name)
            if key and key not in lookup:
                lookup[key] = view
    return lookup


def enrich_sector_views_with_universe_breadth(
    sector_views: list[dict[str, Any]],
    universe_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_views = normalize_sector_views(sector_views)
    if not normalized_views:
        return []
    lookup = sector_view_lookup(normalized_views)
    counters: dict[str, dict[str, int]] = {}
    for raw in universe_rows:
        if not isinstance(raw, dict):
            continue
        sector_key = sector_view_key(sector_name_from_market_strength_row(raw))
        if sector_key not in lookup:
            continue
        day_pct = _finite_float(raw.get("day_pct") if raw.get("day_pct") not in (None, "") else raw.get("f3"))
        if day_pct is None or day_pct <= 0:
            continue
        counter = counters.setdefault(sector_key, {"top_mover_count": 0, "positive_top_mover_count": 0, "near_limit_top_mover_count": 0})
        counter["top_mover_count"] += 1
        counter["positive_top_mover_count"] += 1
        if day_pct >= 8.0:
            counter["near_limit_top_mover_count"] += 1
    enriched: list[dict[str, Any]] = []
    seen_view_keys: set[str] = set()
    for view in normalized_views:
        key = sector_view_key(view.get("sector_name"))
        if not key or key in seen_view_keys:
            continue
        updated = deepcopy(view)
        for count_key, count_value in counters.get(key, {}).items():
            if count_value:
                updated[count_key] = count_value
        updated["breadth_signal"] = classify_sector_breadth_signal(updated)
        enriched.append(updated)
        seen_view_keys.add(key)
    return enriched


def is_fresh_discovery_required(request: dict[str, Any]) -> bool:
    explicit = request.get("fresh_discovery_required") is True
    baseline_only = clean_text(request.get("trading_plan_pool_role")) == "baseline_context_only"
    if not explicit and not baseline_only:
        return False
    sessions = [
        clean_text(item).lower()
        for item in request.get("fresh_discovery_required_sessions", [])
        if clean_text(item)
    ]
    session_type = clean_text(request.get("session_type")).lower()
    if session_type and sessions and session_type not in sessions:
        return False
    return True


def local_stock_pool_count(request: dict[str, Any]) -> int:
    pool = request.get("local_stock_pool") if isinstance(request.get("local_stock_pool"), dict) else {}
    stocks = pool.get("stocks") if isinstance(pool.get("stocks"), list) else []
    return len([stock for stock in stocks if isinstance(stock, dict)])


def local_stock_pool_tickers(request: dict[str, Any]) -> list[str]:
    pool = request.get("local_stock_pool") if isinstance(request.get("local_stock_pool"), dict) else {}
    stocks = pool.get("stocks") if isinstance(pool.get("stocks"), list) else []
    tickers: list[str] = []
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        ticker = normalize_a_share_ticker(stock.get("ticker") or stock.get("code") or stock.get("symbol"))
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def build_fresh_discovery_coverage(
    request: dict[str, Any],
    *,
    market_strength_universe: list[dict[str, Any]],
    request_market_strength_candidates: list[dict[str, Any]],
    generated_market_strength_candidates: list[dict[str, Any]],
    universe_fetch_error: str = "",
    market_strength_fetch_error: str = "",
    sector_rankings: list[dict[str, Any]] | None = None,
    sector_views: list[dict[str, Any]] | None = None,
    sector_rank_fetch_error: str = "",
) -> dict[str, Any]:
    required = is_fresh_discovery_required(request)
    request_count = len([row for row in request_market_strength_candidates if isinstance(row, dict)])
    generated_count = len([row for row in generated_market_strength_candidates if isinstance(row, dict)])
    universe_count = len([row for row in market_strength_universe if isinstance(row, dict)])
    normalized_sector_rankings = normalize_sector_rankings(sector_rankings or [])
    normalized_sector_views = normalize_sector_views(sector_views or [])
    strong_sector_views = [
        row
        for row in normalized_sector_views
        if clean_text(row.get("breadth_signal")).lower() in {"broad", "focused"}
        or (_coerce_positive_int(row.get("rank")) <= 10 and (_finite_float(row.get("day_pct")) or 0.0) > 0)
    ]
    baseline_tickers = set(local_stock_pool_tickers(request))
    candidate_tickers: list[str] = []
    for row in request_market_strength_candidates + generated_market_strength_candidates:
        if not isinstance(row, dict):
            continue
        ticker = normalize_a_share_ticker(row.get("ticker") or row.get("code") or row.get("symbol"))
        if ticker and ticker not in candidate_tickers:
            candidate_tickers.append(ticker)
    candidate_count = len(candidate_tickers)
    fresh_candidate_tickers = [ticker for ticker in candidate_tickers if ticker not in baseline_tickers]
    baseline_candidate_tickers = [ticker for ticker in candidate_tickers if ticker in baseline_tickers]
    fresh_candidate_count = len(fresh_candidate_tickers)
    baseline_candidate_count = len(baseline_candidate_tickers)
    if not required:
        status = "not_required"
    elif fresh_candidate_count > 0:
        status = "covered"
    elif strong_sector_views:
        status = "sector_only"
    elif universe_fetch_error or market_strength_fetch_error:
        status = "blocked"
    elif candidate_count > 0:
        status = "baseline_only"
    elif universe_count > 0:
        status = "no_candidates"
    else:
        status = "missing"
    coverage = {
        "required": required,
        "status": status,
        "session_type": clean_text(request.get("session_type")),
        "trading_plan_pool_role": clean_text(request.get("trading_plan_pool_role")),
        "local_stock_pool_count": local_stock_pool_count(request),
        "local_stock_pool_ticker_count": len(baseline_tickers),
        "market_strength_universe_count": universe_count,
        "market_strength_candidate_count": candidate_count,
        "request_market_strength_candidate_count": request_count,
        "generated_market_strength_candidate_count": generated_count,
        "fresh_market_strength_candidate_count": fresh_candidate_count,
        "baseline_market_strength_candidate_count": baseline_candidate_count,
        "sector_ranking_count": len(normalized_sector_rankings),
        "sector_view_count": len(normalized_sector_views),
        "strong_sector_view_count": len(strong_sector_views),
    }
    if universe_fetch_error:
        coverage["universe_fetch_error"] = universe_fetch_error
    if market_strength_fetch_error:
        coverage["market_strength_fetch_error"] = market_strength_fetch_error
    if sector_rank_fetch_error:
        coverage["sector_rank_fetch_error"] = sector_rank_fetch_error
    if required and status == "sector_only":
        coverage["warning"] = "fresh_discovery_sector_only_no_stock_level_candidates"
    elif required and status != "covered":
        coverage["warning"] = "fresh_discovery_required_but_not_covered"
    return coverage


def build_fresh_discovery_coverage_markdown(coverage: dict[str, Any]) -> str:
    if not isinstance(coverage, dict) or not coverage.get("required"):
        return ""
    lines = [
        "",
        "## Fresh Discovery Coverage",
        "",
        f"- status: `{clean_text(coverage.get('status')) or 'unknown'}`",
        f"- session_type: `{clean_text(coverage.get('session_type')) or 'n/a'}`",
        f"- local_stock_pool_count: `{coverage.get('local_stock_pool_count', 0)}`",
        f"- fresh_market_strength_candidate_count: `{coverage.get('fresh_market_strength_candidate_count', 0)}`",
        f"- market_strength_universe_count: `{coverage.get('market_strength_universe_count', 0)}`",
        f"- market_strength_candidate_count: `{coverage.get('market_strength_candidate_count', 0)}`",
        f"- sector_ranking_count: `{coverage.get('sector_ranking_count', 0)}`",
        f"- strong_sector_view_count: `{coverage.get('strong_sector_view_count', 0)}`",
        "- boundary: imported trading-plan stocks are baseline context only; fresh market-strength discovery must be checked for intraday and postclose reviews.",
    ]
    if clean_text(coverage.get("warning")):
        lines.append(f"- warning: `{clean_text(coverage.get('warning'))}`")
    if clean_text(coverage.get("universe_fetch_error")):
        lines.append(f"- universe_fetch_error: `{clean_text(coverage.get('universe_fetch_error'))}`")
    if clean_text(coverage.get("market_strength_fetch_error")):
        lines.append(f"- fetch_error: `{clean_text(coverage.get('market_strength_fetch_error'))}`")
    if clean_text(coverage.get("sector_rank_fetch_error")):
        lines.append(f"- sector_rank_fetch_error: `{clean_text(coverage.get('sector_rank_fetch_error'))}`")
    return "\n".join(lines).rstrip() + "\n"


def build_sector_views_markdown(sector_views: list[dict[str, Any]] | None) -> list[str]:
    rows = normalize_sector_views(sector_views or [])
    if not rows:
        return []
    lines = ["", "## Sector Rank Coverage", ""]
    for row in sorted(rows, key=lambda item: _coerce_positive_int(item.get("rank")) or 999)[:8]:
        sector_name = clean_text(row.get("sector_name")) or "unknown"
        sector_type = clean_text(row.get("sector_type")) or "sector"
        rank = _coerce_positive_int(row.get("rank")) or "n/a"
        day_pct = row.get("day_pct")
        breadth = clean_text(row.get("breadth_signal")) or "unknown"
        source = clean_text(row.get("source")) or "sector_view"
        top_movers = _coerce_positive_int(row.get("top_mover_count"))
        mover_text = f" top_movers=`{top_movers}`" if top_movers else ""
        lines.append(
            f"- `{sector_name}` type=`{sector_type}` rank=`{rank}` day_pct=`{day_pct if day_pct is not None else 'n/a'}` breadth=`{breadth}` source=`{source}`{mover_text}"
        )
    lines.append("- Boundary: sector rank is a discovery input; individual candidates still require stock-level verification.")
    return lines


def attach_fresh_discovery_coverage(result: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    result["fresh_discovery_coverage"] = coverage
    section = build_fresh_discovery_coverage_markdown(coverage)
    if section:
        report = str(result.get("report_markdown") or "")
        if "## Fresh Discovery Coverage" not in report:
            result["report_markdown"] = report.rstrip() + "\n" + section
    return result


__all__ = [
    "attach_fresh_discovery_coverage",
    "build_fresh_discovery_coverage",
    "build_fresh_discovery_coverage_markdown",
    "build_sector_views_from_rankings",
    "build_sector_views_markdown",
    "classify_sector_breadth_signal",
    "enrich_sector_views_with_universe_breadth",
    "merge_sector_view_inputs",
    "normalize_sector_rank_row",
    "normalize_sector_rankings",
    "normalize_sector_view",
    "normalize_sector_views",
    "sector_name_from_market_strength_row",
    "sector_view_key",
    "sector_view_lookup",
]
