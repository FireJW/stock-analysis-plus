#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from fresh_discovery_coverage import (
    normalize_sector_views,
    sector_name_from_market_strength_row,
    sector_view_key,
    sector_view_lookup,
)


MARKET_STRENGTH_REVIEW_PRICE_FIELDS = (
    "price",
    "pre_close",
    "high",
    "low",
    "day_pct",
    "day_turnover_cny",
    "turnover_rate_pct",
)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


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


def normalize_market_strength_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    theme_guess = raw.get("theme_guess") if isinstance(raw.get("theme_guess"), list) else []
    normalized = {
        "ticker": clean_text(raw.get("ticker")),
        "name": clean_text(raw.get("name")) or clean_text(raw.get("ticker")),
        "strength_reason": clean_text(raw.get("strength_reason")) or "close_near_high",
        "close_strength": clean_text(raw.get("close_strength")) or "medium",
        "volume_signal": clean_text(raw.get("volume_signal")) or "unclear",
        "board_context": clean_text(raw.get("board_context")) or "high_conviction_momentum",
        "theme_guess": [clean_text(item) for item in theme_guess if clean_text(item)],
        "source": clean_text(raw.get("source")) or "market_strength_scan",
    }
    for key in MARKET_STRENGTH_REVIEW_PRICE_FIELDS:
        if raw.get(key) not in (None, ""):
            normalized[key] = _finite_float(raw.get(key))
    sector_name = clean_text(raw.get("sector_name") or raw.get("sector") or raw.get("industry"))
    if sector_name:
        normalized["sector_name"] = sector_name
    sector_type = clean_text(raw.get("sector_type"))
    if sector_type:
        normalized["sector_type"] = sector_type
    sector_rank = _coerce_positive_int(raw.get("sector_rank") or raw.get("rank"))
    if sector_rank:
        normalized["sector_rank"] = sector_rank
    sector_day_pct = _finite_float(raw.get("sector_day_pct") if raw.get("sector_day_pct") not in (None, "") else raw.get("sector_pct"))
    if sector_day_pct is not None:
        normalized["sector_day_pct"] = sector_day_pct
    sector_breadth = clean_text(raw.get("sector_breadth_signal") or raw.get("breadth_signal"))
    if sector_breadth:
        normalized["sector_breadth_signal"] = sector_breadth
    sector_source = clean_text(raw.get("sector_source"))
    if sector_source:
        normalized["sector_source"] = sector_source
    return normalized


def build_market_strength_discovery_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = clean_text(row.get("ticker"))
        if not ticker:
            continue
        theme_guess = row.get("theme_guess") if isinstance(row.get("theme_guess"), list) else []
        chain_name = next((clean_text(item) for item in theme_guess if clean_text(item)), "unknown")
        close_strength = clean_text(row.get("close_strength"))
        volume_signal = clean_text(row.get("volume_signal"))
        converted.append(
            {
                "ticker": ticker,
                "name": clean_text(row.get("name")) or ticker,
                "event_type": "market_strength_scan",
                "event_strength": "strong" if close_strength == "high" else "medium",
                "chain_name": chain_name,
                "chain_role": "unknown",
                "benefit_type": "mapping",
                "sources": [
                    {
                        "source_type": "community_post",
                        "summary": clean_text(row.get("strength_reason")) or "market strength supplement",
                    }
                ],
                "market_validation": {
                    "volume_multiple_5d": 2.0 if volume_signal == "expanding" else 1.0,
                    "breakout": close_strength == "high",
                    "relative_strength": "strong" if close_strength == "high" else "normal",
                    "chain_resonance": False,
                },
                "market_strength_source": clean_text(row.get("source")) or "market_strength_scan",
                "market_strength_reason": clean_text(row.get("strength_reason")),
                "market_strength_board_context": clean_text(row.get("board_context")),
                "market_strength_sector_name": clean_text(row.get("sector_name")),
                "market_strength_sector_rank": row.get("sector_rank"),
                "market_strength_sector_breadth_signal": clean_text(row.get("sector_breadth_signal")),
                "market_strength_supplement": True,
                **{
                    key: row.get(key)
                    for key in MARKET_STRENGTH_REVIEW_PRICE_FIELDS
                    if row.get(key) not in (None, "")
                },
            }
        )
    return converted


def is_market_strength_excluded(row: dict[str, Any], existing_tickers: set[str]) -> bool:
    name = clean_text(row.get("name") or row.get("f14"))
    ticker = clean_text(row.get("ticker") or row.get("f12"))
    if not ticker or ticker in existing_tickers:
        return True
    if "ST" in name.upper():
        return True
    if to_float(row.get("day_turnover_cny")) < 100_000_000:
        return True
    if (
        to_float(row.get("turnover_rate_pct")) < 0.5
        and to_float(row.get("price")) == to_float(row.get("high"))
        and to_float(row.get("price")) == to_float(row.get("low"))
    ):
        return True
    return False


def market_strength_score(row: dict[str, Any]) -> float:
    price = to_float(row.get("price"))
    high = to_float(row.get("high"))
    low = to_float(row.get("low"))
    day_pct = to_float(row.get("day_pct"))
    turnover = to_float(row.get("day_turnover_cny"))

    close_to_high = 0.0
    if high > low:
        close_to_high = (price - low) / (high - low)

    turnover_score = min(turnover / 1_000_000_000, 3.0)
    return round(day_pct * 2.0 + close_to_high * 5.0 + turnover_score, 4)


def normalize_market_strength_universe_ticker(raw: dict[str, Any]) -> str:
    ticker = clean_text(raw.get("ticker"))
    if ticker:
        return ticker
    code = clean_text(raw.get("f12"))
    market_id = clean_text(raw.get("f13"))
    if not code:
        return ""
    if market_id == "1":
        return f"{code}.SS"
    if market_id == "0":
        return f"{code}.SZ"
    return code


def build_market_strength_candidates_from_universe(
    universe_rows: list[dict[str, Any]],
    *,
    existing_tickers: set[str],
    max_names: int = 10,
    sector_views: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    normalized_sector_views = normalize_sector_views(sector_views or [])
    sector_lookup = sector_view_lookup(normalized_sector_views)
    ranked: list[dict[str, Any]] = []
    for raw in universe_rows:
        if not isinstance(raw, dict):
            continue
        sector_name = sector_name_from_market_strength_row(raw)
        sector_key = sector_view_key(sector_name)
        sector_view = sector_lookup.get(sector_key) if sector_key else None
        row = {
            "ticker": normalize_market_strength_universe_ticker(raw),
            "name": clean_text(raw.get("name") or raw.get("f14")),
            "price": to_float(raw.get("price") if raw.get("price") not in (None, "") else raw.get("f2")),
            "high": to_float(raw.get("high") if raw.get("high") not in (None, "") else raw.get("f15")),
            "low": to_float(raw.get("low") if raw.get("low") not in (None, "") else raw.get("f16")),
            "pre_close": to_float(raw.get("pre_close") if raw.get("pre_close") not in (None, "") else raw.get("f18")),
            "day_pct": to_float(raw.get("day_pct") if raw.get("day_pct") not in (None, "") else raw.get("f3")),
            "day_turnover_cny": to_float(raw.get("day_turnover_cny") if raw.get("day_turnover_cny") not in (None, "") else raw.get("f6")),
            "turnover_rate_pct": to_float(raw.get("turnover_rate_pct") if raw.get("turnover_rate_pct") not in (None, "") else raw.get("f8")),
        }
        if sector_name:
            row["sector_name"] = sector_name
        if sector_view:
            row["sector_type"] = clean_text(sector_view.get("sector_type")) or "industry"
            row["sector_rank"] = _coerce_positive_int(sector_view.get("rank")) or None
            sector_day_pct = _finite_float(sector_view.get("day_pct"))
            if sector_day_pct is not None:
                row["sector_day_pct"] = sector_day_pct
            row["sector_breadth_signal"] = clean_text(sector_view.get("breadth_signal")) or "ranking_only"
            row["sector_source"] = clean_text(sector_view.get("source")) or "eastmoney_sector_rank"
        if is_market_strength_excluded(row, existing_tickers):
            continue
        if row["day_pct"] <= 0:
            continue
        score = market_strength_score(row)
        if sector_view:
            sector_rank = _coerce_positive_int(sector_view.get("rank"))
            sector_day_pct = _finite_float(sector_view.get("day_pct"))
            breadth_signal = clean_text(sector_view.get("breadth_signal")).lower()
            top_mover_count = _coerce_positive_int(sector_view.get("top_mover_count"))
            if sector_rank:
                score += max(0.0, (10 - min(sector_rank, 10)) * 0.25)
            if sector_day_pct is not None and sector_day_pct > 0:
                score += min(sector_day_pct, 5.0) * 0.4
            if breadth_signal == "broad":
                score += 1.5
            elif breadth_signal == "focused":
                score += 0.75
            if top_mover_count >= 3:
                score += 1.0
        ranked.append({"score": score, "row": row, "sector_key": sector_key})

    ranked.sort(key=lambda item: item["score"], reverse=True)
    selected: list[dict[str, Any]] = ranked[:max_names]
    selected_tickers = {clean_text(item["row"].get("ticker")) for item in selected if clean_text(item["row"].get("ticker"))}
    selected_sector_keys = {item.get("sector_key") for item in selected if item.get("sector_key")}

    sector_priority_keys: list[str] = []
    for view in sorted(
        normalized_sector_views,
        key=lambda item: (
            _coerce_positive_int(item.get("rank")) or 999,
            -(_finite_float(item.get("day_pct")) or 0.0),
            -(_coerce_positive_int(item.get("top_mover_count")) or 0),
        ),
    ):
        key = sector_view_key(view.get("sector_name"))
        if not key or key in sector_priority_keys:
            continue
        if _coerce_positive_int(view.get("rank")) <= 10 or clean_text(view.get("breadth_signal")).lower() in {"broad", "focused"}:
            sector_priority_keys.append(key)

    for key in sector_priority_keys:
        if key in selected_sector_keys:
            continue
        sector_candidates = [item for item in ranked if item.get("sector_key") == key]
        if not sector_candidates:
            continue
        chosen = None
        for item in sector_candidates:
            ticker = clean_text(item["row"].get("ticker"))
            if ticker and ticker not in selected_tickers:
                chosen = item
                break
        if chosen is None:
            continue
        if len(selected) < max_names:
            selected.append(chosen)
        else:
            weakest_index = min(range(len(selected)), key=lambda idx: selected[idx]["score"])
            weakest_ticker = clean_text(selected[weakest_index]["row"].get("ticker"))
            if weakest_ticker in selected_tickers:
                selected_tickers.remove(weakest_ticker)
            selected[weakest_index] = chosen
        chosen_ticker = clean_text(chosen["row"].get("ticker"))
        if chosen_ticker:
            selected_tickers.add(chosen_ticker)
        selected_sector_keys.add(key)

    selected.sort(key=lambda item: item["score"], reverse=True)
    generated: list[dict[str, Any]] = []
    for item in selected:
        row = item["row"]
        high = to_float(row.get("high"))
        low = to_float(row.get("low"))
        price = to_float(row.get("price"))
        day_pct = to_float(row.get("day_pct"))
        turnover = to_float(row.get("day_turnover_cny"))
        close_to_high = 0.0
        if high > low:
            close_to_high = (price - low) / (high - low)
        theme_guess: list[str] = []
        has_sector_rank_context = bool(
            clean_text(row.get("sector_source"))
            or _coerce_positive_int(row.get("sector_rank"))
            or clean_text(row.get("sector_breadth_signal"))
        )
        if has_sector_rank_context and clean_text(row.get("sector_name")):
            theme_guess.append(clean_text(row.get("sector_name")))
        source = "market_strength_scan"
        if has_sector_rank_context:
            source = "market_strength_sector_rank_scan"
        generated.append(
            normalize_market_strength_candidate(
                {
                    "ticker": row["ticker"],
                    "name": row["name"],
                    "strength_reason": "near_limit_close" if day_pct >= 8.0 and close_to_high >= 0.8 else "close_near_high",
                    "close_strength": "high" if close_to_high >= 0.8 else "medium",
                    "volume_signal": "expanding" if turnover >= 300_000_000 else "normal",
                    "board_context": "high_conviction_momentum" if day_pct >= 8.0 else "trend_follow_through",
                    "theme_guess": theme_guess,
                    "source": source,
                    "price": row.get("price"),
                    "pre_close": row.get("pre_close"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "day_pct": row.get("day_pct"),
                    "day_turnover_cny": row.get("day_turnover_cny"),
                    "turnover_rate_pct": row.get("turnover_rate_pct"),
                    "sector_name": row.get("sector_name"),
                    "sector_type": row.get("sector_type"),
                    "sector_rank": row.get("sector_rank"),
                    "sector_day_pct": row.get("sector_day_pct"),
                    "sector_breadth_signal": row.get("sector_breadth_signal"),
                    "sector_source": row.get("sector_source"),
                }
            )
        )
    return generated


def merge_market_strength_candidate_inputs(
    request_rows: list[dict[str, Any]],
    generated_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in request_rows + generated_rows:
        ticker = clean_text(row.get("ticker"))
        if not ticker or ticker in seen:
            continue
        merged.append(row)
        seen.add(ticker)
    return merged


__all__ = [
    "MARKET_STRENGTH_REVIEW_PRICE_FIELDS",
    "build_market_strength_candidates_from_universe",
    "build_market_strength_discovery_candidates",
    "is_market_strength_excluded",
    "market_strength_score",
    "merge_market_strength_candidate_inputs",
    "normalize_market_strength_candidate",
    "normalize_market_strength_universe_ticker",
]
