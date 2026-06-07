#!/usr/bin/env python3
from __future__ import annotations

from importlib.machinery import SourcelessFileLoader
from importlib.util import module_from_spec, spec_from_loader
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable
from copy import deepcopy
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from earnings_momentum_discovery import (
    TRADING_PROFILE_BUCKETS,
    assign_discovery_bucket,
    build_auto_discovery_candidates,
    build_chain_path_summary,
    build_event_cards,
    build_trading_profile_judgment,
    build_trading_profile_playbook,
    build_trading_profile_usage,
    build_x_style_discovery_candidates,
    classify_trading_profile,
    classify_event_state,
    classify_market_validation,
    classify_trading_usability,
    compute_rumor_confidence_range,
    normalize_event_candidate,
)
from weekend_market_candidate_runtime import (
    build_weekend_market_candidate,
    normalize_weekend_market_candidate_input,
    resolve_direction_tickers,
)
from fresh_discovery_coverage import (
    attach_fresh_discovery_coverage,
    build_fresh_discovery_coverage,
    build_fresh_discovery_coverage_markdown,
    build_sector_views_from_rankings,
    build_sector_views_markdown,
    classify_sector_breadth_signal,
    enrich_sector_views_with_universe_breadth,
    merge_sector_view_inputs,
    normalize_sector_rank_row,
    normalize_sector_rankings,
    normalize_sector_view,
    normalize_sector_views,
    sector_name_from_market_strength_row,
    sector_view_key,
    sector_view_lookup,
)
from market_strength_candidates import (
    MARKET_STRENGTH_REVIEW_PRICE_FIELDS,
    build_market_strength_candidates_from_universe,
    build_market_strength_discovery_candidates,
    is_market_strength_excluded,
    market_strength_score,
    merge_market_strength_candidate_inputs,
    normalize_market_strength_candidate,
    normalize_market_strength_universe_ticker,
)
from local_stock_pool_runtime import (
    build_local_technical_snapshot,
    fetch_local_daily_rows,
    local_stock_pool_lookup,
    merge_local_pool_candidate_tickers,
    normalize_a_share_ticker,
    normalize_local_daily_bars_source,
    normalize_local_stock_pool_from_request,
)


PYC_PATH = (
    Path(__file__).resolve().parents[2]
    / "short-horizon-shortlist"
    / "scripts"
    / "__pycache__"
    / "month_end_shortlist_runtime.cpython-312.pyc"
)
TRADINGAGENTS_SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / "tradingagents-decision-bridge"
    / "scripts"
)
X_STYLE_SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / "x-stock-picker-style"
    / "scripts"
)
MACRO_HEALTH_SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / "macro-health-overlay"
    / "scripts"
)
DEFAULT_MACRO_HEALTH_REQUEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "macro-health-overlay"
    / "examples"
    / "macro-health-overlay-public-mix.request.template.json"
)
DEFAULT_MACRO_HEALTH_SEED_CACHE_PATH = (
    Path(__file__).resolve().parents[4]
    / ".tmp"
    / "runtime-cache"
    / "macro-health-overlay-public-mix.latest.json"
)


for _script_dir in (TRADINGAGENTS_SCRIPT_DIR, X_STYLE_SCRIPT_DIR, MACRO_HEALTH_SCRIPT_DIR):
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))


BENCHMARK_TICKERS = {"000300.SS", "000300.SH"}
MARKET_STRENGTH_UNIVERSE_LIMIT = 200
MARKET_STRENGTH_MARKET_GROUPS = "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23"
MARKET_STRENGTH_FIELDS = "f12,f13,f14,f2,f3,f5,f6,f8,f9,f10,f15,f16,f17,f18,f20,f21,f23,f24,f25,f100"
SINA_MARKET_CENTER_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
SINA_SW1_SECTOR_NODES: tuple[tuple[str, str], ...] = (
    ("美容护理", "sw1_770000"),
    ("环保", "sw1_760000"),
    ("石油石化", "sw1_750000"),
    ("煤炭", "sw1_740000"),
    ("通信", "sw1_730000"),
    ("传媒", "sw1_720000"),
    ("计算机", "sw1_710000"),
    ("国防军工", "sw1_650000"),
    ("机械设备", "sw1_640000"),
    ("电力设备", "sw1_630000"),
    ("建筑装饰", "sw1_620000"),
    ("建筑材料", "sw1_610000"),
    ("综合", "sw1_510000"),
    ("非银金融", "sw1_490000"),
    ("银行", "sw1_480000"),
    ("社会服务", "sw1_460000"),
    ("商贸零售", "sw1_450000"),
    ("房地产", "sw1_430000"),
    ("交通运输", "sw1_420000"),
    ("公用事业", "sw1_410000"),
    ("医药生物", "sw1_370000"),
    ("轻工制造", "sw1_360000"),
    ("纺织服饰", "sw1_350000"),
    ("食品饮料", "sw1_340000"),
    ("家用电器", "sw1_330000"),
    ("汽车", "sw1_280000"),
    ("电子", "sw1_270000"),
    ("有色金属", "sw1_240000"),
    ("钢铁", "sw1_230000"),
    ("基础化工", "sw1_220000"),
    ("农林牧渔", "sw1_110000"),
)
SECTOR_RANK_LIMIT = 30
SECTOR_RANK_INDUSTRY_GROUP = "m:90+t:2"
SECTOR_RANK_CONCEPT_GROUP = "m:90+t:3"
SECTOR_RANK_FIELDS = "f12,f14,f3,f62,f128,f136,f140,f207,f208,f209"
DEFAULT_STRATEGIC_BASE_WATCH_THEMES = (
    "commercial_space",
    "controlled_fusion",
    "humanoid_robotics",
    "semiconductor_equipment",
)
SETUP_LAUNCH_THEME_ALIASES: dict[str, tuple[str, ...]] = {
    "commercial_space": (
        "商业航天",
        "卫星",
        "卫星互联网",
        "卫星链",
        "航天",
        "火箭",
        "space",
        "spacex",
        "starlink",
        "satellite",
    ),
    "controlled_fusion": (
        "可控核聚变",
        "核聚变",
        "聚变",
        "托卡马克",
        "超导磁体",
        "fusion",
    ),
    "humanoid_robotics": (
        "人形机器人",
        "具身智能",
        "机器人",
        "灵巧手",
        "减速器",
        "伺服",
        "humanoid",
        "robotics",
        "robot",
    ),
    "semiconductor_equipment": (
        "半导体设备",
        "半导体",
        "刻蚀",
        "薄膜",
        "光刻",
        "清洗",
        "量测",
        "cmp",
        "equipment",
        "semiconductor",
    ),
}
SETUP_LAUNCH_MAX_NAMES = 10
SETUP_LAUNCH_THEME_WEIGHTS: dict[str, dict[str, float]] = {
    "commercial_space": {
        "structure_repair": 1.05,
        "volume_return": 1.1,
        "rs_improvement": 1.0,
        "distance_bonus": 1.0,
    },
    "controlled_fusion": {
        "structure_repair": 1.0,
        "volume_return": 1.1,
        "rs_improvement": 1.0,
        "distance_bonus": 1.0,
    },
    "humanoid_robotics": {
        "structure_repair": 1.0,
        "volume_return": 1.0,
        "rs_improvement": 1.05,
        "distance_bonus": 1.0,
    },
    "semiconductor_equipment": {
        "structure_repair": 1.1,
        "volume_return": 1.0,
        "rs_improvement": 1.05,
        "distance_bonus": 1.0,
    },
}


def load_compiled_module():
    if not PYC_PATH.exists():
        raise ModuleNotFoundError(f"Compiled month_end_shortlist_runtime artifact is missing: {PYC_PATH}")
    loader = SourcelessFileLoader(__name__ + "._compiled", str(PYC_PATH))
    spec = spec_from_loader(__name__ + "._compiled", loader)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to create an import spec for {PYC_PATH}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_compiled = load_compiled_module()
__doc__ = getattr(_compiled, "__doc__", None)

for _name in dir(_compiled):
    if _name.startswith("__") and _name not in {"__all__"}:
        continue
    globals()[_name] = getattr(_compiled, _name)

_ORIGINAL_BUILD_MARKDOWN_REPORT = globals().get("build_markdown_report")

BarsFetcher = Callable[[str, str, str], list[dict[str, Any]]]
AssessCandidate = Callable[..., dict[str, Any]]
NEAR_MISS_MAX_GAP = 20.0
MAX_REPORTED_TOP_PICKS = 10
MAX_REPORTED_NEAR_MISS = 5
MAX_REPORTED_BLOCKED = 5
MAX_REPORTED_WATCH_ITEMS = 3

# --- Screening Coverage Optimization constants ---
NEAR_MISS_FLOOR_GAP = 25.0        # used by floor policy supplementation
TIER_CAPS = {"T1": 10, "T2": 5, "T3": 8, "T4": 5}
TOTAL_RENDERED_CAP = 12            # final merged display budget across all tiers
MIN_COVERAGE_TARGET = 10
TWO_ROUND_THRESHOLD = 3            # top_picks < this triggers Round 2
CATALYST_WAIVER_SCORE_GAP = 10.0   # keep_threshold - this = waiver floor

# Hard failures that permanently exclude from all tiers
HARD_EXCLUSION_FAILURES = frozenset({
    "bars_fetch_failed",
    "price_below_floor",
    "volume_below_floor",
    "suspended",
    "st_or_risk_warning",
})
WRAPPER_FILTER_PROFILE_OVERRIDES: dict[str, dict[str, float]] = {
    # Recovered from a validated historical artifact until the compiled runtime
    # regains native support for this documented profile.
    "month_end_event_support_transition": {
        "keep_threshold": 56.0,
        "strict_top_pick_threshold": 58.0,
    },
    "broad_coverage_mode": {
        "keep_threshold": 55.0,
        "strict_top_pick_threshold": 57.0,
    },
}

# Board-specific threshold adjustments (legacy single-pool mode).
# Retained for backward compatibility; multi-track mode uses TRACK_CONFIGS.
BOARD_THRESHOLD_OVERRIDES: dict[str, dict[str, float]] = {
    "main_board": {
        "keep_threshold": 58.0,
        "strict_top_pick_threshold": 59.0,
    },
}

# Multi-track board-separated pipeline configuration.
# Each key is a track name; board_values lists the return values of
# _compiled.classify_board(ticker) that belong to this track.
# Candidates whose board is not covered by any track are dropped with
# "outside_track_scope".  To add a new track (e.g. star / 科创板),
# simply add an entry here.
TRACK_CONFIGS: dict[str, dict[str, Any]] = {
    "main_board": {
        "label": "主板",
        "board_values": ("main_board",),
        "keep_threshold": 58.0,
        "strict_top_pick_threshold": 59.0,
        "tier_caps": {"T1": 10, "T2": 5, "T3": 8, "T4": 5},
        "min_coverage_target": 10,
        "two_round_threshold": 3,
    },
    "chinext": {
        "label": "创业板",
        "board_values": ("chinext",),
        "keep_threshold": 56.0,
        "strict_top_pick_threshold": 58.0,
        "tier_caps": {"T1": 10, "T2": 5, "T3": 8, "T4": 5},
        "min_coverage_target": 10,
        "two_round_threshold": 3,
    },
}

GEOPOLITICS_REGIME_LABELS = frozenset({
    "escalation",
    "de_escalation",
    "whipsaw",
})

GEOPOLITICS_BENEFICIARY_CHAINS = frozenset({
    "oil_shipping",
    "energy",
    "gold",
    "defense",
})

GEOPOLITICS_HEADWIND_CHAINS = frozenset({
    "cost_sensitive_chemicals",
    "airlines",
    "export_chain",
    "high_beta_growth",
})

GEOPOLITICS_CANDIDATE_DIRECTIONS = frozenset({
    "escalation",
    "de_escalation",
    "whipsaw",
})

GEOPOLITICS_MARKET_SIGNAL_VALUES: dict[str, frozenset[str]] = {
    "oil": frozenset({"up", "down", "flat"}),
    "gold": frozenset({"up", "down", "flat"}),
    "shipping": frozenset({"up", "down", "flat"}),
    "risk_style": frozenset({"risk_on", "risk_off", "mixed"}),
    "usd_rates": frozenset({"tightening", "loosening", "mixed"}),
    "airlines": frozenset({"up", "down", "flat"}),
    "industrials": frozenset({"up", "down", "flat"}),
}


def wrap_bars_fetcher_with_benchmark_fallback(base_fetcher: BarsFetcher) -> BarsFetcher:
    def wrapped(ticker: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        try:
            return base_fetcher(ticker, start_date, end_date)
        except Exception:
            if str(ticker or "").strip().upper() in BENCHMARK_TICKERS:
                return []
            raise

    return wrapped


def load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: Any) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in result:
            result.append(text)
    return result


def normalize_macro_geopolitics_overlay(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    regime_label = clean_text(raw.get("regime_label"))
    if regime_label not in GEOPOLITICS_REGIME_LABELS:
        return None

    overlay: dict[str, Any] = {"regime_label": regime_label}
    confidence = clean_text(raw.get("confidence"))
    if confidence:
        overlay["confidence"] = confidence
    headline_risk = clean_text(raw.get("headline_risk"))
    if headline_risk:
        overlay["headline_risk"] = headline_risk

    beneficiary_chains = [
        item for item in unique_strings(raw.get("beneficiary_chains") or [])
        if item in GEOPOLITICS_BENEFICIARY_CHAINS
    ]
    if beneficiary_chains:
        overlay["beneficiary_chains"] = beneficiary_chains

    headwind_chains = [
        item for item in unique_strings(raw.get("headwind_chains") or [])
        if item in GEOPOLITICS_HEADWIND_CHAINS
    ]
    if headwind_chains:
        overlay["headwind_chains"] = headwind_chains

    notes = clean_text(raw.get("notes"))
    if notes:
        overlay["notes"] = notes
    return overlay


def normalize_candidate_signal_row(raw: Any, source_type: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    row: dict[str, Any] = {}
    if source_type == "news":
        source = clean_text(raw.get("source"))
        headline = clean_text(raw.get("headline"))
        if source:
            row["source"] = source
        if headline:
            row["headline"] = headline
    elif source_type == "x":
        account = clean_text(raw.get("account"))
        url = clean_text(raw.get("url"))
        if account:
            row["account"] = account
        if url:
            row["url"] = url

    summary = clean_text(raw.get("summary"))
    if summary:
        row["summary"] = summary

    direction_hint = clean_text(raw.get("direction_hint"))
    if direction_hint in GEOPOLITICS_CANDIDATE_DIRECTIONS:
        row["direction_hint"] = direction_hint

    timestamp = clean_text(raw.get("timestamp"))
    if timestamp:
        row["timestamp"] = timestamp

    return row or None


def normalize_macro_geopolitics_candidate_input(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    normalized: dict[str, Any] = {}

    news_rows = [
        item
        for item in (
            normalize_candidate_signal_row(candidate, "news")
            for candidate in (raw.get("news_signals") or [])
        )
        if item
    ]
    if news_rows:
        normalized["news_signals"] = news_rows

    x_rows = [
        item
        for item in (
            normalize_candidate_signal_row(candidate, "x")
            for candidate in (raw.get("x_signals") or [])
        )
        if item
    ]
    if x_rows:
        normalized["x_signals"] = x_rows

    market_raw = raw.get("market_signals")
    if isinstance(market_raw, dict):
        market_signals: dict[str, str] = {}
        for key, allowed_values in GEOPOLITICS_MARKET_SIGNAL_VALUES.items():
            value = clean_text(market_raw.get(key))
            if value in allowed_values:
                market_signals[key] = value
        if market_signals:
            normalized["market_signals"] = market_signals

    return normalized or None


def synthesize_geopolitics_evidence_block(candidate_input: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(candidate_input, dict):
        return {"news_evidence": [], "x_evidence": [], "market_evidence": []}

    def make_row(
        source_type: str,
        signal_family: str,
        direction: str,
        strength: str,
        summary: str,
    ) -> dict[str, Any]:
        return {
            "source_type": source_type,
            "signal_family": signal_family,
            "direction": direction,
            "strength": strength,
            "summary": summary,
        }

    news_rows: list[dict[str, Any]] = []
    for row in candidate_input.get("news_signals", []):
        if not isinstance(row, dict):
            continue
        direction = clean_text(row.get("direction_hint"))
        if direction in GEOPOLITICS_CANDIDATE_DIRECTIONS:
            news_rows.append(
                make_row(
                    "news",
                    "headline_flow",
                    direction,
                    "medium",
                    clean_text(row.get("summary") or row.get("headline") or "news signal"),
                )
            )

    x_rows: list[dict[str, Any]] = []
    for row in candidate_input.get("x_signals", []):
        if not isinstance(row, dict):
            continue
        direction = clean_text(row.get("direction_hint"))
        if direction in GEOPOLITICS_CANDIDATE_DIRECTIONS:
            x_rows.append(
                make_row(
                    "x",
                    "x_discussion",
                    direction,
                    "medium",
                    clean_text(row.get("summary") or "x signal"),
                )
            )

    market_rows: list[dict[str, Any]] = []
    market = candidate_input.get("market_signals")
    if isinstance(market, dict):
        if market.get("oil") == "up":
            market_rows.append(make_row("market", "oil", "escalation", "medium", "Oil is confirming upside risk."))
        if market.get("oil") == "down":
            market_rows.append(make_row("market", "oil", "de_escalation", "medium", "Oil is unwinding risk premium."))
        if market.get("gold") == "up":
            market_rows.append(make_row("market", "gold", "escalation", "medium", "Gold is confirming safety demand."))
        if market.get("gold") == "down":
            market_rows.append(make_row("market", "gold", "de_escalation", "low", "Gold is easing with lower safety demand."))
        if market.get("shipping") == "up":
            market_rows.append(make_row("market", "shipping", "escalation", "medium", "Shipping tape is repricing disruption risk."))
        if market.get("shipping") == "down":
            market_rows.append(make_row("market", "shipping", "de_escalation", "low", "Shipping tape is easing disruption risk."))
        if market.get("risk_style") == "risk_off":
            market_rows.append(make_row("market", "risk_style", "escalation", "medium", "Risk style is defensive."))
        if market.get("risk_style") == "risk_on":
            market_rows.append(make_row("market", "risk_style", "de_escalation", "medium", "Risk style is improving."))
        if market.get("risk_style") == "mixed":
            market_rows.append(make_row("market", "risk_style", "whipsaw", "low", "Risk style is mixed."))        
        if market.get("usd_rates") == "tightening":
            market_rows.append(make_row("market", "usd_rates", "escalation", "low", "USD/rates backdrop is tighter."))
        if market.get("usd_rates") == "loosening":
            market_rows.append(make_row("market", "usd_rates", "de_escalation", "low", "USD/rates backdrop is easing."))
        if market.get("airlines") == "down":
            market_rows.append(make_row("market", "airlines", "escalation", "medium", "Airlines are lagging."))
        if market.get("airlines") == "up":
            market_rows.append(make_row("market", "airlines", "de_escalation", "low", "Airlines are recovering."))
        if market.get("industrials") == "down":
            market_rows.append(make_row("market", "industrials", "escalation", "low", "Industrials are under pressure."))
        if market.get("industrials") == "up":
            market_rows.append(make_row("market", "industrials", "de_escalation", "low", "Industrials are stabilizing."))

    return {
        "news_evidence": news_rows,
        "x_evidence": x_rows,
        "market_evidence": market_rows,
    }


def build_macro_geopolitics_candidate(candidate_input: dict[str, Any] | None) -> dict[str, Any]:
    evidence = synthesize_geopolitics_evidence_block(candidate_input)
    all_rows = evidence["news_evidence"] + evidence["x_evidence"] + evidence["market_evidence"]
    if not all_rows:
        return {
            "candidate_regime": "insufficient_signal",
            "confidence": "low",
            "signal_alignment": "none",
            "status": "insufficient_signal",
            "evidence_summary": ["No usable geopolitical candidate signals were provided."],
            "evidence_block": evidence,
        }

    score = {"escalation": 0, "de_escalation": 0, "whipsaw": 0}
    source_directions: dict[str, dict[str, int]] = {}
    weights = {"low": 1, "medium": 2, "high": 3}
    for row in all_rows:
        direction = row.get("direction")
        if direction not in score:
            continue
        weight = weights.get(clean_text(row.get("strength")), 1)
        score[direction] += weight
        source_type = clean_text(row.get("source_type"))
        source_directions.setdefault(source_type, {})
        source_directions[source_type][direction] = source_directions[source_type].get(direction, 0) + weight

    top_by_source: dict[str, str] = {}
    for source_type, direction_scores in source_directions.items():
        if not direction_scores:
            continue
        top_direction = max(direction_scores.items(), key=lambda kv: kv[1])[0]
        top_by_source[source_type] = top_direction

    aligned_pairs = []
    for pair in ("news+x", "news+market", "x+market"):
        left, right = pair.split("+")
        if left in top_by_source and right in top_by_source and top_by_source[left] == top_by_source[right]:
            aligned_pairs.append(pair)

    ordered_scores = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
    top_regime, top_score = ordered_scores[0]
    second_score = ordered_scores[1][1] if len(ordered_scores) > 1 else 0
    has_full_alignment = {"news", "x", "market"}.issubset(top_by_source) and len({top_by_source["news"], top_by_source["x"], top_by_source["market"]}) == 1

    if not aligned_pairs or top_score - second_score < 2:
        return {
            "candidate_regime": "insufficient_signal",
            "confidence": "low",
            "signal_alignment": "mixed",
            "status": "insufficient_signal",
            "evidence_summary": [clean_text(row.get("summary")) for row in all_rows[:3] if clean_text(row.get("summary"))],
            "evidence_block": evidence,
        }

    candidate_regime = top_regime
    confidence = "high" if top_score >= 6 else "medium"
    signal_alignment = "news+x+market" if has_full_alignment else aligned_pairs[0]
    return {
        "candidate_regime": candidate_regime,
        "confidence": confidence,
        "signal_alignment": signal_alignment,
        "status": "candidate_only",
        "evidence_summary": [clean_text(row.get("summary")) for row in all_rows[:3] if clean_text(row.get("summary"))],
        "beneficiary_bias": (
            ["oil_shipping", "energy", "gold", "defense"]
            if candidate_regime == "escalation"
            else ["airlines", "export_chain", "high_beta_growth"]
            if candidate_regime == "de_escalation"
            else []
        ),
        "headwind_bias": (
            ["airlines", "cost_sensitive_chemicals", "export_chain", "high_beta_growth"]
            if candidate_regime == "escalation"
            else ["oil_shipping", "energy", "gold", "defense"]
            if candidate_regime == "de_escalation"
            else []
        ),
        "evidence_block": evidence,
    }


def extract_x_style_overlays_from_result(
    batch_payload: dict[str, Any],
    selected_handles: list[str] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    desired = unique_strings([clean_text(item).lstrip("@") for item in (selected_handles or [])])
    handles: list[str] = []
    overlays: list[dict[str, Any]] = []
    stale_warning = _compute_x_style_stale_warning(batch_payload)
    for item in batch_payload.get("subject_runs", []):
        if not isinstance(item, dict):
            continue
        subject = item.get("subject", {})
        overlay_pack = item.get("overlay_pack", {})
        if not isinstance(subject, dict) or not isinstance(overlay_pack, dict):
            continue
        handle = clean_text(subject.get("handle")).lstrip("@")
        if not handle:
            continue
        if desired and handle not in desired:
            continue
        if handle in handles:
            continue
        handles.append(handle)
        overlay = deepcopy(overlay_pack)
        overlay["handle"] = handle
        if stale_warning:
            overlay["stale_result_warning"] = stale_warning
        overlays.append(overlay)
    return handles, overlays


def extract_x_risk_alerts_from_result(
    batch_payload: dict[str, Any],
    selected_handles: list[str] | None = None,
) -> list[dict[str, Any]]:
    desired = unique_strings([clean_text(item).lstrip("@") for item in (selected_handles or [])])
    alerts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in batch_payload.get("subject_runs", []):
        if not isinstance(item, dict):
            continue
        subject = item.get("subject", {})
        if not isinstance(subject, dict):
            continue
        handle = clean_text(subject.get("handle")).lstrip("@")
        if not handle:
            continue
        if desired and handle not in desired:
            continue
        for raw_alert in item.get("risk_alerts", []) or []:
            if not isinstance(raw_alert, dict):
                continue
            key = (
                clean_text(raw_alert.get("name")),
                clean_text(raw_alert.get("source_url")),
                clean_text(raw_alert.get("author")),
            )
            if key in seen:
                continue
            seen.add(key)
            alerts.append(deepcopy(raw_alert))
    return alerts


def _compute_x_style_stale_warning(batch_payload: dict[str, Any]) -> str:
    analysis_time = clean_text(batch_payload.get("analysis_time"))
    if not analysis_time:
        return ""
    try:
        from datetime import datetime
        analyzed_at = datetime.fromisoformat(analysis_time.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if analyzed_at.tzinfo is None:
        return ""
    age = now_utc() - analyzed_at
    if age.total_seconds() > 48 * 3600:
        hours = int(age.total_seconds() // 3600)
        return f"x_style batch result is older than 48h (age={hours}h)"
    return ""


def apply_wrapper_filter_profile_override(raw_payload: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    requested_profile = clean_text(raw_payload.get("filter_profile"))
    if not requested_profile:
        return normalized
    override = WRAPPER_FILTER_PROFILE_OVERRIDES.get(requested_profile)
    if not override:
        return normalized

    normalized["filter_profile"] = requested_profile
    profile_settings = dict(normalized.get("profile_settings") or {})
    for key, value in override.items():
        normalized[key] = value
        profile_settings[key] = value
    normalized["profile_settings"] = profile_settings

    # In multi-track mode, per-track payloads carry track-specific thresholds
    # that must override the profile-level defaults applied above.
    track_name = raw_payload.get("_track_name")
    if track_name:
        track_cfg = raw_payload.get("_track_config") or TRACK_CONFIGS.get(track_name, {})
        for key in ("keep_threshold", "strict_top_pick_threshold"):
            if key in track_cfg:
                normalized[key] = track_cfg[key]
                profile_settings[key] = track_cfg[key]
        normalized["profile_settings"] = profile_settings

    return normalized


def build_x_discovery_context(raw_request: dict[str, Any]) -> dict[str, Any]:
    subject_registry = raw_request.get("subject_registry") if isinstance(raw_request.get("subject_registry"), dict) else {}
    subjects = subject_registry.get("subjects") if isinstance(subject_registry.get("subjects"), list) else []
    chain_map_by_name: dict[str, dict[str, Any]] = {}
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        for rule in subject.get("logic_basket_rules", []) if isinstance(subject.get("logic_basket_rules"), list) else []:
            if not isinstance(rule, dict):
                continue
            chain_name = clean_text(rule.get("sector_or_chain") or rule.get("basket_name"))
            if not chain_name:
                continue
            leaders = unique_strings(rule.get("core_candidate_names") or rule.get("candidate_names") or [])
            tier_1 = unique_strings(rule.get("core_candidate_names") or rule.get("candidate_names") or [])
            all_candidates = unique_strings(rule.get("candidate_names") or [])
            tier_2 = [item for item in all_candidates if item not in tier_1]
            existing = chain_map_by_name.setdefault(
                chain_name,
                {"chain_name": chain_name, "leaders": [], "tier_1": [], "tier_2": [], "all_candidates": []},
            )
            existing["leaders"] = unique_strings(existing["leaders"] + leaders)
            existing["tier_1"] = unique_strings(existing["tier_1"] + tier_1)
            existing["tier_2"] = unique_strings(existing["tier_2"] + tier_2)
            existing["all_candidates"] = unique_strings(existing["all_candidates"] + all_candidates)
    return {"chain_map": list(chain_map_by_name.values())}


def normalize_setup_launch_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    theme_guess = raw.get("theme_guess") if isinstance(raw.get("theme_guess"), list) else []
    setup_reasons = raw.get("setup_reasons") if isinstance(raw.get("setup_reasons"), list) else []
    return {
        "ticker": clean_text(raw.get("ticker")),
        "name": clean_text(raw.get("name")) or clean_text(raw.get("ticker")),
        "theme_guess": [clean_text(item) for item in theme_guess if clean_text(item)],
        "setup_reasons": [clean_text(item) for item in setup_reasons if clean_text(item)],
        "structure_repair": clean_text(raw.get("structure_repair")) or "low",
        "volume_return": clean_text(raw.get("volume_return")) or "low",
        "rs_improvement": clean_text(raw.get("rs_improvement")) or "low",
        "distance_from_bottom_state": clean_text(raw.get("distance_from_bottom_state")) or "unknown",
        "source": clean_text(raw.get("source")) or "setup_launch_scan",
    }


def resolve_setup_launch_theme_pool(
    request_obj: dict[str, Any],
    weekend_market_candidate: dict[str, Any] | None,
) -> list[str]:
    ordered: list[str] = []
    candidate_topics = (
        weekend_market_candidate.get("candidate_topics", [])
        if isinstance(weekend_market_candidate, dict)
        else []
    )
    for item in candidate_topics:
        if not isinstance(item, dict):
            continue
        topic_name = clean_text(item.get("topic_name"))
        if topic_name and topic_name not in ordered:
            ordered.append(topic_name)
    configured = request_obj.get("strategic_base_watch_themes")
    if isinstance(configured, list):
        configured_rows = [clean_text(item) for item in configured if clean_text(item)]
    else:
        configured_rows = list(DEFAULT_STRATEGIC_BASE_WATCH_THEMES)
    for item in configured_rows:
        if item and item not in ordered:
            ordered.append(item)
    return ordered


def _setup_theme_intersections(raw: dict[str, Any], active_themes: list[str]) -> list[str]:
    explicit = raw.get("theme_guess") if isinstance(raw.get("theme_guess"), list) else []
    explicit_clean = [clean_text(item) for item in explicit if clean_text(item)]
    matches: list[str] = [item for item in explicit_clean if item in active_themes]
    if matches:
        return list(dict.fromkeys(matches))
    text_parts = [
        clean_text(raw.get("name") or raw.get("f14")),
        clean_text(raw.get("sector") or raw.get("industry") or raw.get("f100")),
        clean_text(raw.get("chain_name")),
        clean_text(raw.get("board_context")),
    ]
    text_blob = " ".join(item for item in text_parts if item).lower()
    for theme_name in active_themes:
        aliases = SETUP_LAUNCH_THEME_ALIASES.get(theme_name, ())
        for alias in aliases:
            normalized_alias = clean_text(alias).lower()
            if normalized_alias and normalized_alias in text_blob:
                matches.append(theme_name)
                break
    return list(dict.fromkeys(matches))


def _setup_signal_score(value: str) -> float:
    normalized = clean_text(value).lower()
    if normalized == "high":
        return 2.0
    if normalized == "medium":
        return 1.0
    return 0.0


def _average_window(values: Any) -> float:
    if not isinstance(values, list):
        return to_float(values)
    cleaned = [to_float(item) for item in values if to_float(item) > 0]
    if not cleaned:
        return 0.0
    return sum(cleaned) / len(cleaned)


def _rising_recent_lows(snapshot: dict[str, Any]) -> bool:
    recent_low_trend = clean_text(snapshot.get("recent_low_trend")).lower()
    if recent_low_trend in {"higher_lows", "rising", "up"}:
        return True
    recent_lows = snapshot.get("recent_lows") if isinstance(snapshot.get("recent_lows"), list) else []
    cleaned = [to_float(item) for item in recent_lows if to_float(item) > 0]
    if len(cleaned) < 3:
        return False
    return cleaned[-1] >= cleaned[-2] >= cleaned[-3]


def _theme_weight(theme_guess: list[str], key: str) -> float:
    for theme_name in theme_guess:
        weights = SETUP_LAUNCH_THEME_WEIGHTS.get(clean_text(theme_name), {})
        if key in weights:
            return float(weights[key])
    return 1.0


def classify_structure_repair(row: dict[str, Any]) -> str:
    snapshot = row.get("price_snapshot") if isinstance(row.get("price_snapshot"), dict) else {}
    close = to_float(snapshot.get("close") if snapshot else row.get("price"))
    ma20 = to_float(snapshot.get("ma20"))
    ma50 = to_float(snapshot.get("ma50"))
    ma20_prev_5 = to_float(
        snapshot.get("ma20_prev_5")
        if snapshot.get("ma20_prev_5") not in (None, "")
        else snapshot.get("ma20_prev")
    )
    pct_from_60d = to_float(row.get("pct_from_60d"))
    day_pct = to_float(row.get("day_pct"))
    reclaimed_ma20 = bool(close and ma20 and close > ma20)
    reclaimed_ma50 = bool(close and ma50 and close > ma50)
    ma20_turning_up = bool(ma20 and ma20_prev_5 and ma20 > ma20_prev_5)
    higher_recent_lows = _rising_recent_lows(snapshot)
    if reclaimed_ma20 and reclaimed_ma50 and ma20_turning_up and higher_recent_lows:
        return "high"
    if reclaimed_ma20 and (reclaimed_ma50 or ma20_turning_up or higher_recent_lows):
        return "medium"
    if pct_from_60d >= 8.0 and day_pct > 0:
        return "medium"
    return "low"


def classify_volume_return(row: dict[str, Any]) -> str:
    snapshot = row.get("price_snapshot") if isinstance(row.get("price_snapshot"), dict) else {}
    volume_ratio = to_float(row.get("volume_ratio") if row.get("volume_ratio") not in (None, "") else snapshot.get("volume_ratio"))
    turnover_rate = to_float(row.get("turnover_rate_pct") if row.get("turnover_rate_pct") not in (None, "") else row.get("f8"))
    turnover = to_float(row.get("day_turnover_cny") if row.get("day_turnover_cny") not in (None, "") else row.get("f6"))
    recent_window = _average_window(
        snapshot.get("recent_turnover_window")
        if snapshot.get("recent_turnover_window") not in (None, "")
        else snapshot.get("recent_turnover_avg")
    )
    base_window = _average_window(
        snapshot.get("base_turnover_window")
        if snapshot.get("base_turnover_window") not in (None, "")
        else snapshot.get("base_turnover_avg")
    )
    if recent_window and base_window:
        acceleration = recent_window / base_window if base_window else 0.0
        if acceleration >= 1.8:
            return "high"
        if acceleration >= 1.25:
            return "medium"
    if volume_ratio >= 1.5:
        return "high"
    if turnover_rate >= 3.0 or turnover >= 500_000_000:
        return "medium"
    if volume_ratio >= 1.1 or turnover_rate >= 1.0 or turnover >= 150_000_000:
        return "medium"
    return "low"


def classify_rs_improvement(row: dict[str, Any]) -> str:
    snapshot = row.get("price_snapshot") if isinstance(row.get("price_snapshot"), dict) else {}
    rs90 = to_float(snapshot.get("rs90") if snapshot else row.get("rs90"))
    rs90_prev_5 = to_float(
        snapshot.get("rs90_prev_5")
        if snapshot.get("rs90_prev_5") not in (None, "")
        else snapshot.get("rs90_prev")
    )
    pct_from_ytd = to_float(row.get("pct_from_ytd"))
    day_pct = to_float(row.get("day_pct"))
    if rs90 and rs90_prev_5:
        delta = rs90 - rs90_prev_5
        if rs90 >= 85.0 or delta >= 18.0:
            return "high"
        if delta >= 8.0 or (rs90 >= 65.0 and delta > 0):
            return "medium"
        return "low"
    if rs90 >= 90.0 or pct_from_ytd >= 20.0:
        return "high"
    if rs90 >= 70.0 and pct_from_ytd >= 12.0:
        return "medium"
    if pct_from_ytd >= 12.0 and day_pct > 0:
        return "medium"
    return "low"


def classify_distance_from_bottom_state(row: dict[str, Any]) -> str:
    pct_from_60d = to_float(row.get("pct_from_60d"))
    if pct_from_60d <= 3.0:
        return "still_bottoming"
    if pct_from_60d <= 35.0:
        return "off_bottom_not_extended"
    if pct_from_60d <= 55.0:
        return "early_extension"
    return "too_extended"


def is_setup_launch_excluded(row: dict[str, Any], existing_tickers: set[str], active_themes: list[str]) -> bool:
    ticker = clean_text(row.get("ticker"))
    name = clean_text(row.get("name"))
    if not ticker or ticker in existing_tickers:
        return True
    if "ST" in name.upper():
        return True
    if to_float(row.get("day_turnover_cny")) < 100_000_000:
        return True
    if not _setup_theme_intersections(row, active_themes):
        return True
    if classify_distance_from_bottom_state(row) == "too_extended":
        return True
    return False


def setup_launch_score(row: dict[str, Any], theme_name: str | None = None) -> float:
    if theme_name:
        theme_guess = [clean_text(theme_name)] if clean_text(theme_name) else []
    else:
        theme_guess = _setup_theme_intersections(
            row,
            row.get("theme_guess") if isinstance(row.get("theme_guess"), list) else [],
        )
    structure_repair = classify_structure_repair(row)
    volume_return = classify_volume_return(row)
    rs_improvement = classify_rs_improvement(row)
    bottom_state = classify_distance_from_bottom_state(row)
    score = (
        _setup_signal_score(structure_repair) * 2.0 * _theme_weight(theme_guess, "structure_repair")
        + _setup_signal_score(volume_return) * 1.5 * _theme_weight(theme_guess, "volume_return")
        + _setup_signal_score(rs_improvement) * 1.5 * _theme_weight(theme_guess, "rs_improvement")
    )
    if bottom_state == "off_bottom_not_extended":
        score += 2.0 * _theme_weight(theme_guess, "distance_bonus")
    elif bottom_state == "early_extension":
        score += 0.5 * _theme_weight(theme_guess, "distance_bonus")
    elif bottom_state == "still_bottoming":
        score -= 2.0
    else:
        score -= 1.0
    day_pct = to_float(row.get("day_pct"))
    if 1.0 <= day_pct <= 6.0:
        score += 1.0
    return round(score, 4)


def build_setup_launch_candidates_from_universe(
    universe_rows: list[dict[str, Any]],
    *,
    active_themes: list[str],
    existing_tickers: set[str],
    max_names: int = SETUP_LAUNCH_MAX_NAMES,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for raw in universe_rows:
        if not isinstance(raw, dict):
            continue
        row = {
            "ticker": normalize_market_strength_universe_ticker(raw),
            "name": clean_text(raw.get("name") or raw.get("f14")),
            "sector": clean_text(raw.get("sector") or raw.get("industry") or raw.get("f100")),
            "price": to_float(raw.get("price") if raw.get("price") not in (None, "") else raw.get("f2")),
            "high": to_float(raw.get("high") if raw.get("high") not in (None, "") else raw.get("f15")),
            "low": to_float(raw.get("low") if raw.get("low") not in (None, "") else raw.get("f16")),
            "pre_close": to_float(raw.get("pre_close") if raw.get("pre_close") not in (None, "") else raw.get("f18")),
            "day_pct": to_float(raw.get("day_pct") if raw.get("day_pct") not in (None, "") else raw.get("f3")),
            "day_turnover_cny": to_float(raw.get("day_turnover_cny") if raw.get("day_turnover_cny") not in (None, "") else raw.get("f6")),
            "turnover_rate_pct": to_float(raw.get("turnover_rate_pct") if raw.get("turnover_rate_pct") not in (None, "") else raw.get("f8")),
            "pct_from_60d": to_float(raw.get("pct_from_60d")),
            "pct_from_ytd": to_float(raw.get("pct_from_ytd")),
            "volume_ratio": to_float(raw.get("volume_ratio")),
            "price_snapshot": deepcopy(raw.get("price_snapshot")) if isinstance(raw.get("price_snapshot"), dict) else {},
            "theme_guess": raw.get("theme_guess") if isinstance(raw.get("theme_guess"), list) else [],
        }
        if is_setup_launch_excluded(row, existing_tickers, active_themes):
            continue
        score = setup_launch_score(row)
        if score < 4.0:
            continue
        ranked.append((score, row))

    ranked.sort(key=lambda item: item[0], reverse=True)
    generated: list[dict[str, Any]] = []
    for _, row in ranked[:max_names]:
        theme_guess = _setup_theme_intersections(row, active_themes)
        structure_repair = classify_structure_repair(row)
        volume_return = classify_volume_return(row)
        rs_improvement = classify_rs_improvement(row)
        distance_state = classify_distance_from_bottom_state(row)
        snapshot = row.get("price_snapshot") if isinstance(row.get("price_snapshot"), dict) else {}
        setup_reasons: list[str] = []
        close = to_float(snapshot.get("close") if snapshot else row.get("price"))
        ma20 = to_float(snapshot.get("ma20"))
        ma50 = to_float(snapshot.get("ma50"))
        ma20_prev_5 = to_float(snapshot.get("ma20_prev_5"))
        rs90 = to_float(snapshot.get("rs90"))
        rs90_prev_5 = to_float(snapshot.get("rs90_prev_5"))
        recent_window = _average_window(snapshot.get("recent_turnover_window"))
        base_window = _average_window(snapshot.get("base_turnover_window"))
        if close and ma20 and ma50 and close > ma20 and close > ma50:
            setup_reasons.append("reclaimed_ma20_ma50")
        elif close and ma20 and close > ma20:
            setup_reasons.append("reclaimed_ma20")
        if ma20 and ma20_prev_5 and ma20 > ma20_prev_5:
            setup_reasons.append("ma20_turning_up")
        if _rising_recent_lows(snapshot):
            setup_reasons.append("higher_recent_lows")
        if volume_return in {"medium", "high"}:
            if recent_window and base_window and recent_window > base_window:
                setup_reasons.append("volume_reacceleration")
            else:
                setup_reasons.append("volume_return_visible")
        if rs_improvement in {"medium", "high"}:
            if rs90 and rs90_prev_5 and rs90 > rs90_prev_5:
                setup_reasons.append("rs_trend_repair")
            else:
                setup_reasons.append("rs_trend_improving")
        if distance_state == "off_bottom_not_extended":
            setup_reasons.append("off_bottom_not_extended")
        elif distance_state == "early_extension":
            setup_reasons.append("early_extension")
        generated.append(
            normalize_setup_launch_candidate(
                {
                    "ticker": row["ticker"],
                    "name": row["name"],
                    "theme_guess": theme_guess,
                    "setup_reasons": setup_reasons,
                    "structure_repair": structure_repair,
                    "volume_return": volume_return,
                    "rs_improvement": rs_improvement,
                    "distance_from_bottom_state": distance_state,
                    "source": "setup_launch_scan",
                }
            )
        )
    return generated


def merge_setup_launch_candidate_inputs(
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


EMERGENT_THEME_PROMOTION_THRESHOLD = 6.0


def _coerce_positive_int(value: Any) -> int:
    try:
        coerced = int(to_float(value))
    except (TypeError, ValueError):
        return 0
    return coerced if coerced > 0 else 0


def _finite_float(value: Any) -> float | None:
    number = to_float(value)
    return number if number == number else None


def _best_emergent_signal_strength(current: Any, new: Any) -> str:
    order = {
        "strong": 3,
        "high": 3,
        "medium": 2,
        "moderate": 2,
        "low": 1,
        "weak": 1,
    }
    current_text = clean_text(current)
    new_text = clean_text(new)
    if order.get(new_text.lower(), 0) > order.get(current_text.lower(), 0):
        return new_text or current_text
    return current_text or new_text


def _normalize_emergent_supporting_signals(raw: dict[str, Any]) -> list[dict[str, Any]]:
    supporting_rows = raw.get("supporting_signals")
    if not isinstance(supporting_rows, list):
        supporting_rows = raw.get("sources")
    if not isinstance(supporting_rows, list):
        supporting_rows = raw.get("key_sources")
    if not isinstance(supporting_rows, list):
        supporting_rows = []

    normalized: list[dict[str, Any]] = []
    for item in supporting_rows:
        if isinstance(item, dict):
            row: dict[str, Any] = {}
            source_kind = clean_text(item.get("source_kind") or item.get("source_type") or item.get("kind"))
            if source_kind:
                row["source_kind"] = source_kind
            source_name = clean_text(item.get("source_name") or item.get("account") or item.get("name"))
            if source_name:
                row["source_name"] = source_name
            summary = clean_text(item.get("summary") or item.get("why_it_matters") or item.get("ranking_reason"))
            if summary:
                row["summary"] = summary
            url = clean_text(item.get("url") or item.get("post_url"))
            if url:
                row["url"] = url
            signal_strength = clean_text(item.get("signal_strength") or item.get("strength"))
            if signal_strength:
                row["signal_strength"] = signal_strength
            priority_rank = _coerce_positive_int(item.get("priority_rank") or item.get("rank"))
            if priority_rank:
                row["priority_rank"] = priority_rank
            if row:
                normalized.append(row)
        else:
            text = clean_text(item)
            if text:
                normalized.append({"summary": text})
    return normalized


def _normalize_emergent_supporting_names(raw: dict[str, Any]) -> list[str]:
    values = raw.get("supporting_names")
    if not isinstance(values, list):
        values = raw.get("supporting_tickers")
    if not isinstance(values, list):
        values = raw.get("candidate_names")
    return unique_strings(values if isinstance(values, list) else [])


def classify_emergent_signal_strength(candidate: dict[str, Any]) -> str:
    signal_strength = clean_text(candidate.get("signal_strength")).lower()
    if signal_strength in {"high", "strong"}:
        return "strong"
    if signal_strength in {"medium", "moderate"}:
        return "moderate"
    return "weak"


def classify_emergent_signal_breadth(candidate: dict[str, Any]) -> str:
    source_count = _coerce_positive_int(candidate.get("source_count"))
    if not source_count and isinstance(candidate.get("supporting_signals"), list):
        source_count = len(candidate.get("supporting_signals", []))
    if source_count >= 3:
        return "broad"
    if source_count >= 2:
        return "focused"
    return "thin"


def classify_emergent_signal_consensus(candidate: dict[str, Any]) -> str:
    supporting_signals = candidate.get("supporting_signals") if isinstance(candidate.get("supporting_signals"), list) else []
    source_kinds = unique_strings([
        clean_text(item.get("source_kind"))
        for item in supporting_signals
        if isinstance(item, dict) and clean_text(item.get("source_kind"))
    ])
    source_count = _coerce_positive_int(candidate.get("source_count"))
    if len(source_kinds) >= 2 and source_count >= 3:
        return "aligned"
    if source_count >= 2:
        return "mixed"
    return "thin"


def normalize_emergent_theme_candidate(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    theme_name = clean_text(raw.get("theme_name") or raw.get("topic_name") or raw.get("chain_name") or raw.get("theme"))
    if not theme_name:
        return None

    theme_label = clean_text(raw.get("theme_label") or raw.get("topic_label") or raw.get("name") or theme_name)
    signal_strength = clean_text(raw.get("signal_strength") or raw.get("strength") or raw.get("signal_level")) or "medium"
    source_kind = clean_text(raw.get("source_kind") or raw.get("source_type") or raw.get("source") or "runtime_input")
    priority_rank = _coerce_positive_int(raw.get("priority_rank") or raw.get("rank") or raw.get("priority"))
    supporting_signals = _normalize_emergent_supporting_signals(raw)
    source_count = _coerce_positive_int(raw.get("source_count") or raw.get("support_count") or raw.get("evidence_count"))
    if not source_count:
        source_count = len(supporting_signals)
    if not source_count and source_kind:
        source_count = 1

    normalized: dict[str, Any] = {
        "theme_name": theme_name,
        "theme_label": theme_label,
        "source_kind": source_kind,
        "signal_strength": signal_strength,
        "coarse_signal_strength": classify_emergent_signal_strength(
            {
                "signal_strength": signal_strength,
                "source_count": source_count,
                "supporting_signals": supporting_signals,
            }
        ),
        "coarse_signal_breadth": classify_emergent_signal_breadth(
            {
                "source_count": source_count,
                "supporting_signals": supporting_signals,
            }
        ),
        "coarse_signal_consensus": classify_emergent_signal_consensus(
            {
                "source_count": source_count,
                "supporting_signals": supporting_signals,
            }
        ),
    }
    if priority_rank:
        normalized["priority_rank"] = priority_rank
    if source_count:
        normalized["source_count"] = source_count
    if supporting_signals:
        normalized["supporting_signals"] = supporting_signals
    supporting_names = _normalize_emergent_supporting_names(raw)
    if supporting_names:
        normalized["supporting_names"] = supporting_names

    for field in ("why_it_matters", "notes", "ranking_reason"):
        value = clean_text(raw.get(field))
        if value:
            normalized[field] = value
    return normalized


def emergent_theme_promotion_score(candidate: dict[str, Any]) -> float:
    strength_scores = {"strong": 4.0, "moderate": 2.0, "weak": 0.0}
    breadth_scores = {"broad": 2.0, "focused": 1.0, "thin": 0.0}
    consensus_scores = {"aligned": 1.5, "mixed": 1.0, "thin": 0.0}

    score = strength_scores.get(classify_emergent_signal_strength(candidate), 0.0)
    score += breadth_scores.get(classify_emergent_signal_breadth(candidate), 0.0)
    score += consensus_scores.get(classify_emergent_signal_consensus(candidate), 0.0)

    priority_rank = _coerce_positive_int(candidate.get("priority_rank"))
    if priority_rank == 1:
        score += 1.25
    elif priority_rank == 2:
        score += 0.75
    elif priority_rank == 3:
        score += 0.25

    source_count = _coerce_positive_int(candidate.get("source_count"))
    if source_count >= 4:
        score += 1.0
    elif source_count >= 2:
        score += 0.5

    if clean_text(candidate.get("source_kind")) in {"weekend_market_candidate", "macro_geopolitics_candidate"}:
        score += 0.5
    return round(score, 2)


def should_promote_emergent_theme(candidate: dict[str, Any]) -> bool:
    theme_name = clean_text(candidate.get("theme_name") or candidate.get("topic_name"))
    if not theme_name:
        return False
    return emergent_theme_promotion_score(candidate) >= EMERGENT_THEME_PROMOTION_THRESHOLD


def build_emergent_theme_candidates_from_runtime_inputs(
    request_obj: dict[str, Any],
    *,
    weekend_market_candidate: dict[str, Any] | None = None,
    market_strength_candidates: list[dict[str, Any]] | None = None,
    setup_launch_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    source_rows: list[dict[str, Any]] = []

    explicit_rows = request_obj.get("emergent_theme_candidates")
    if isinstance(explicit_rows, list):
        for raw in explicit_rows:
            if not isinstance(raw, dict):
                continue
            normalized = normalize_emergent_theme_candidate(
                {
                    **raw,
                    "source_kind": clean_text(raw.get("source_kind")) or "explicit_request",
                }
            )
            if normalized:
                source_rows.append(normalized)

    if isinstance(weekend_market_candidate, dict):
        for topic in weekend_market_candidate.get("candidate_topics", []):
            if not isinstance(topic, dict):
                continue
            supporting_signals: list[dict[str, Any]] = []
            for source in topic.get("key_sources", []):
                if not isinstance(source, dict):
                    continue
                support_row: dict[str, Any] = {}
                source_kind = clean_text(source.get("source_kind") or "weekend_market_candidate")
                if source_kind:
                    support_row["source_kind"] = source_kind
                source_name = clean_text(source.get("source_name") or source.get("account"))
                if source_name:
                    support_row["source_name"] = source_name
                summary = clean_text(source.get("summary") or topic.get("ranking_reason") or topic.get("why_it_matters"))
                if summary:
                    support_row["summary"] = summary
                url = clean_text(source.get("url"))
                if url:
                    support_row["url"] = url
                if support_row:
                    supporting_signals.append(support_row)
            normalized = normalize_emergent_theme_candidate(
                {
                    "theme_name": topic.get("topic_name"),
                    "theme_label": topic.get("topic_label"),
                    "source_kind": "weekend_market_candidate",
                    "signal_strength": topic.get("signal_strength"),
                    "priority_rank": topic.get("priority_rank"),
                    "source_count": len(supporting_signals) or 1,
                    "supporting_signals": supporting_signals or [
                        {
                            "source_kind": "weekend_market_candidate",
                            "summary": clean_text(topic.get("ranking_reason")) or clean_text(topic.get("why_it_matters")),
                        }
                    ],
                    "why_it_matters": clean_text(topic.get("why_it_matters")),
                    "notes": clean_text(topic.get("monday_watch")),
                    "ranking_reason": clean_text(topic.get("ranking_reason")),
                }
            )
            if normalized:
                source_rows.append(normalized)

    for row in market_strength_candidates or []:
        if not isinstance(row, dict):
            continue
        theme_guess = unique_strings(row.get("theme_guess") if isinstance(row.get("theme_guess"), list) else [])
        if not theme_guess:
            continue
        signal_strength = "high" if clean_text(row.get("close_strength")) == "high" else "medium"
        for theme_name in theme_guess:
            normalized = normalize_emergent_theme_candidate(
                {
                    "theme_name": theme_name,
                    "theme_label": theme_name,
                    "source_kind": "market_strength_candidate",
                    "signal_strength": signal_strength,
                    "source_count": 1,
                    "supporting_names": [clean_text(row.get("ticker")) or clean_text(row.get("name")) or theme_name],
                    "supporting_signals": [
                        {
                            "source_kind": "market_strength_candidate",
                            "summary": clean_text(row.get("strength_reason")) or clean_text(row.get("board_context")) or theme_name,
                            "signal_strength": signal_strength,
                        }
                    ],
                }
            )
            if normalized:
                source_rows.append(normalized)

    for row in setup_launch_candidates or []:
        if not isinstance(row, dict):
            continue
        theme_guess = unique_strings(row.get("theme_guess") if isinstance(row.get("theme_guess"), list) else [])
        if not theme_guess:
            continue
        setup_score = setup_launch_score(row)
        signal_strength = "high" if setup_score >= 6.0 else "medium" if setup_score >= 4.0 else "low"
        setup_reasons = row.get("setup_reasons") if isinstance(row.get("setup_reasons"), list) else []
        for theme_name in theme_guess:
            normalized = normalize_emergent_theme_candidate(
                {
                    "theme_name": theme_name,
                    "theme_label": theme_name,
                    "source_kind": "setup_launch_candidate",
                    "signal_strength": signal_strength,
                    "source_count": 1,
                    "supporting_names": [clean_text(row.get("ticker")) or clean_text(row.get("name")) or theme_name],
                    "supporting_signals": [
                        {
                            "source_kind": "setup_launch_candidate",
                            "summary": clean_text(" ".join(clean_text(item) for item in setup_reasons if clean_text(item))) or clean_text(row.get("source")) or theme_name,
                            "signal_strength": signal_strength,
                        }
                    ],
                }
            )
            if normalized:
                source_rows.append(normalized)

    merged: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        theme_name = clean_text(row.get("theme_name"))
        if not theme_name:
            continue
        item = deepcopy(row)
        supporting_signals = [dict(signal) for signal in item.get("supporting_signals", []) if isinstance(signal, dict)]
        if not supporting_signals:
            supporting_signals = [
                {
                    "source_kind": clean_text(item.get("source_kind")) or "runtime_input",
                    "summary": clean_text(item.get("why_it_matters") or item.get("notes") or theme_name),
                }
            ]
        item["supporting_signals"] = supporting_signals
        item["source_kinds"] = unique_strings(
            [clean_text(item.get("source_kind"))]
            + [clean_text(signal.get("source_kind")) for signal in supporting_signals if clean_text(signal.get("source_kind"))]
        )
        item["supporting_names"] = unique_strings(item.get("supporting_names", []))
        item["source_count"] = max(
            _coerce_positive_int(item.get("source_count")),
            len(supporting_signals),
            1,
        )
        item["coarse_signal_strength"] = classify_emergent_signal_strength(item)
        item["coarse_signal_breadth"] = classify_emergent_signal_breadth(item)
        item["coarse_signal_consensus"] = classify_emergent_signal_consensus(item)
        item["promotion_score"] = emergent_theme_promotion_score(item)
        item["promoted"] = should_promote_emergent_theme(item)
        existing = merged.get(theme_name)
        if existing is None:
            merged[theme_name] = item
            continue
        existing["theme_label"] = existing.get("theme_label") or item.get("theme_label") or theme_name
        existing["signal_strength"] = _best_emergent_signal_strength(existing.get("signal_strength"), item.get("signal_strength"))
        existing_supporting_signals = [dict(signal) for signal in existing.get("supporting_signals", []) if isinstance(signal, dict)]
        existing_supporting_signals.extend(supporting_signals)
        deduped_supporting_signals: list[dict[str, Any]] = []
        seen_signals: set[tuple[str, str, str, str]] = set()
        for signal in existing_supporting_signals:
            key = (
                clean_text(signal.get("source_kind")),
                clean_text(signal.get("source_name")),
                clean_text(signal.get("summary")),
                clean_text(signal.get("url")),
            )
            if key in seen_signals:
                continue
            seen_signals.add(key)
            deduped_supporting_signals.append(signal)
        existing["supporting_signals"] = deduped_supporting_signals
        existing["source_kinds"] = unique_strings(existing.get("source_kinds", []) + item.get("source_kinds", []))
        existing["supporting_names"] = unique_strings(existing.get("supporting_names", []) + item.get("supporting_names", []))
        existing["source_count"] = max(
            _coerce_positive_int(existing.get("source_count")),
            _coerce_positive_int(item.get("source_count")),
            len(deduped_supporting_signals),
        )
        existing_priority = _coerce_positive_int(existing.get("priority_rank"))
        item_priority = _coerce_positive_int(item.get("priority_rank"))
        if existing_priority and item_priority:
            existing["priority_rank"] = min(existing_priority, item_priority)
        elif item_priority:
            existing["priority_rank"] = item_priority
        existing["coarse_signal_strength"] = classify_emergent_signal_strength(existing)
        existing["coarse_signal_breadth"] = classify_emergent_signal_breadth(existing)
        existing["coarse_signal_consensus"] = classify_emergent_signal_consensus(existing)
        existing["promotion_score"] = emergent_theme_promotion_score(existing)
        existing["promoted"] = should_promote_emergent_theme(existing)

    ordered_candidates = sorted(
        merged.values(),
        key=lambda item: (
            -float(item.get("promotion_score") or 0.0),
            -float(item.get("source_count") or 0.0),
            _coerce_positive_int(item.get("priority_rank")) or 999,
            clean_text(item.get("theme_name")),
        ),
    )
    return ordered_candidates


def merge_promoted_emergent_themes_into_active_pool(
    active_themes: list[str],
    emergent_theme_candidates: list[dict[str, Any]] | None,
) -> list[str]:
    merged: list[str] = []
    for theme_name in active_themes or []:
        text = clean_text(theme_name)
        if text and text not in merged:
            merged.append(text)
    for candidate in emergent_theme_candidates or []:
        if not isinstance(candidate, dict) or not should_promote_emergent_theme(candidate):
            continue
        theme_name = clean_text(candidate.get("theme_name") or candidate.get("topic_name"))
        if theme_name and theme_name not in merged:
            merged.append(theme_name)
    return merged


def build_emergent_theme_result_surfaces(
    request_obj: dict[str, Any],
    *,
    weekend_market_candidate: dict[str, Any] | None = None,
    market_strength_candidates: list[dict[str, Any]] | None = None,
    setup_launch_candidates: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    base_active_themes = resolve_setup_launch_theme_pool(request_obj, weekend_market_candidate)
    emergent_theme_candidates = build_emergent_theme_candidates_from_runtime_inputs(
        request_obj,
        weekend_market_candidate=weekend_market_candidate,
        market_strength_candidates=market_strength_candidates,
        setup_launch_candidates=setup_launch_candidates,
    )
    promoted_active_themes = merge_promoted_emergent_themes_into_active_pool(
        base_active_themes,
        emergent_theme_candidates,
    )
    return emergent_theme_candidates, promoted_active_themes


def build_data_blocked_theme_confirmed_candidates(
    dropped: list[dict[str, Any]],
    emergent_theme_candidates: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    theme_by_ticker: dict[str, dict[str, Any]] = {}
    for row in emergent_theme_candidates or []:
        if not isinstance(row, dict) or not should_promote_emergent_theme(row):
            continue
        for ticker in unique_strings(row.get("supporting_names", [])):
            theme_by_ticker[ticker] = row

    blocked_rows: list[dict[str, Any]] = []
    for row in dropped:
        if not isinstance(row, dict):
            continue
        ticker = clean_text(row.get("ticker"))
        if not ticker:
            continue
        theme_row = theme_by_ticker.get(ticker)
        if theme_row is None:
            continue
        if "bars_fetch_failed" not in split_drop_reasons(row.get("drop_reason")):
            continue
        blocked_rows.append(
            {
                "ticker": ticker,
                "name": clean_text(row.get("name")) or ticker,
                "theme_name": clean_text(theme_row.get("theme_name")),
                "theme_label": clean_text(theme_row.get("theme_label")) or clean_text(theme_row.get("theme_name")),
                "status": "data_blocked_theme_confirmed",
                "drop_reason": clean_text(row.get("drop_reason")) or "bars_fetch_failed",
                "bars_fetch_error": clean_text(row.get("bars_fetch_error")),
            }
        )
    return blocked_rows


def build_emergent_theme_markdown(rows: list[dict[str, Any]] | None) -> list[str]:
    items = [item for item in (rows or []) if isinstance(item, dict) and should_promote_emergent_theme(item)]
    if not items:
        return []
    lines = ["", "## 新兴共振主题", ""]
    for item in items:
        label = clean_text(item.get("theme_label")) or clean_text(item.get("theme_name"))
        lines.append(f"- `{label}`")
        lines.append(f"  - promotion_score: `{item.get('promotion_score')}`")
        signals = [
            clean_text(item.get("coarse_signal_strength")),
            clean_text(item.get("coarse_signal_breadth")),
            clean_text(item.get("coarse_signal_consensus")),
        ]
        lines.append(f"  - signals: `{', '.join(part for part in signals if part)}`")
        supporting_names = unique_strings(item.get("supporting_names", []))
        lines.append(f"  - supporting_names: `{', '.join(supporting_names) or 'none'}`")
        supporting_signals = item.get("supporting_signals") if isinstance(item.get("supporting_signals"), list) else []
        if supporting_signals:
            first_signal = supporting_signals[0] if isinstance(supporting_signals[0], dict) else {}
            summary = clean_text(first_signal.get("summary"))
            if summary:
                lines.append(f"  - why_now: {summary}")
    return lines


def build_data_blocked_theme_confirmed_markdown(rows: list[dict[str, Any]] | None) -> list[str]:
    items = [item for item in (rows or []) if isinstance(item, dict)]
    if not items:
        return []
    lines = ["", "## 数据受阻但主题已确认", ""]
    for item in items:
        ticker = clean_text(item.get("ticker")) or "unknown"
        name = clean_text(item.get("name")) or ticker
        theme_label = clean_text(item.get("theme_label")) or clean_text(item.get("theme_name")) or "unknown"
        lines.append(f"- `{ticker}` {name}")
        lines.append(f"  - theme: `{theme_label}`")
        lines.append(f"  - status: `{clean_text(item.get('status')) or 'data_blocked_theme_confirmed'}`")
        lines.append(f"  - drop_reason: `{clean_text(item.get('drop_reason')) or 'bars_fetch_failed'}`")
        bars_fetch_error = clean_text(item.get("bars_fetch_error"))
        if bars_fetch_error:
            lines.append(f"  - bars_fetch_error: `{bars_fetch_error}`")
    return lines


def _count_x_posts_in_result_payload(payload: Any) -> int:
    if not isinstance(payload, dict) or not isinstance(payload.get("x_posts"), list):
        return 0
    return len([item for item in payload.get("x_posts", []) if isinstance(item, dict)])


def _resolve_x_index_result_path(raw_path: str) -> Path | None:
    cleaned = clean_text(raw_path)
    if not cleaned:
        return None
    path = Path(cleaned).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.append(Path.cwd() / path)
        candidates.append(Path(__file__).resolve().parents[4] / path)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _count_x_posts_from_result_path(raw_path: str) -> int:
    resolved = _resolve_x_index_result_path(raw_path)
    if resolved is None:
        return 0
    try:
        return _count_x_posts_in_result_payload(load_json(resolved))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0


def _collect_x_index_result_paths(request_obj: dict[str, Any], weekend_input: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    raw_paths = weekend_input.get("x_live_index_result_paths")
    if isinstance(raw_paths, list):
        paths.extend(clean_text(path) for path in raw_paths if clean_text(path))
    raw_results = weekend_input.get("x_live_index_results")
    if isinstance(raw_results, list):
        for payload in raw_results:
            if isinstance(payload, dict) and clean_text(payload.get("source_result_path")):
                paths.append(clean_text(payload.get("source_result_path")))
    x_discovery_context = request_obj.get("x_discovery_context")
    if isinstance(x_discovery_context, dict) and clean_text(x_discovery_context.get("source_result_path")):
        paths.append(clean_text(x_discovery_context.get("source_result_path")))
    return list(dict.fromkeys(paths))


def build_run_completeness_summary(
    request_obj: dict[str, Any],
    *,
    weekend_market_candidate: dict[str, Any] | None = None,
    filter_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weekend_input = (
        request_obj.get("weekend_market_candidate_input")
        if isinstance(request_obj.get("weekend_market_candidate_input"), dict)
        else {}
    )
    x_results = weekend_input.get("x_live_index_results") if isinstance(weekend_input.get("x_live_index_results"), list) else []
    x_paths = _collect_x_index_result_paths(request_obj, weekend_input)
    x_posts_count = 0
    for payload in x_results:
        x_posts_count += _count_x_posts_in_result_payload(payload)
    for raw_path in x_paths:
        x_posts_count += _count_x_posts_from_result_path(raw_path)

    if x_posts_count > 0:
        x_index_status = "complete"
    elif x_results or x_paths:
        x_index_status = "partial"
    else:
        x_index_status = "missing"

    candidate_topics = (
        weekend_market_candidate.get("candidate_topics", [])
        if isinstance(weekend_market_candidate, dict) and isinstance(weekend_market_candidate.get("candidate_topics"), list)
        else []
    )
    weekend_status_raw = clean_text((weekend_market_candidate or {}).get("status"))
    if candidate_topics and weekend_status_raw == "candidate_only":
        weekend_status = "complete"
    elif candidate_topics or weekend_status_raw not in {"", "insufficient_signal"}:
        weekend_status = "partial"
    else:
        weekend_status = "missing"

    fs = filter_summary if isinstance(filter_summary, dict) else {}
    blocked_count = int(fs.get("blocked_candidate_count") or 0)
    live_supplement_status = clean_text(fs.get("live_supplement_status"))
    cache_baseline_only = bool(fs.get("cache_baseline_only"))
    if not cache_baseline_only and live_supplement_status in {"updated", "complete"} and blocked_count == 0:
        shortlist_status = "complete"
    else:
        shortlist_status = "degraded"

    reasons: list[str] = []
    if x_index_status == "missing":
        reasons.append("missing_x_index_results")
    elif x_index_status == "partial":
        reasons.append("partial_x_index_results")
    if weekend_status == "missing":
        reasons.append("missing_weekend_candidate")
    elif weekend_status == "partial":
        reasons.append("partial_weekend_candidate")
    if cache_baseline_only:
        reasons.append("cache_baseline_only")
    if live_supplement_status and live_supplement_status != "updated":
        reasons.append(f"live_supplement_{live_supplement_status}")
    if blocked_count > 0:
        reasons.append("blocked_candidates_present")

    status = "full" if x_index_status == "complete" and weekend_status == "complete" and shortlist_status == "complete" else "degraded"
    return {
        "status": status,
        "x_index_status": x_index_status,
        "weekend_status": weekend_status,
        "shortlist_status": shortlist_status,
        "reasons": reasons,
    }


def build_run_completeness_report_lines(summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(summary, dict):
        return []
    lines = [f"- Run completeness: `{clean_text(summary.get('status')) or 'degraded'}`"]
    detail = (
        f"x_index=`{clean_text(summary.get('x_index_status')) or 'missing'}` | "
        f"weekend=`{clean_text(summary.get('weekend_status')) or 'missing'}` | "
        f"shortlist=`{clean_text(summary.get('shortlist_status')) or 'degraded'}`"
    )
    lines.append(f"- Completeness detail: {detail}")
    reasons = summary.get("reasons") if isinstance(summary.get("reasons"), list) else []
    if clean_text(summary.get("status")) == "degraded":
        lines.append("- This is a degraded repo-native run. Do not treat it as a full formal plan.")
        if reasons:
            lines.append(f"- Degraded reasons: `{', '.join(clean_text(item) for item in reasons if clean_text(item))}`")
    return lines


def normalize_request_with_compiled(raw_payload: dict[str, Any], compiled_normalize_request: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    normalized = apply_wrapper_filter_profile_override(
        raw_payload,
        compiled_normalize_request(raw_payload),
    )
    geopolitics_overlay = normalize_macro_geopolitics_overlay(raw_payload.get("macro_geopolitics_overlay"))
    if geopolitics_overlay:
        normalized["macro_geopolitics_overlay"] = geopolitics_overlay
    else:
        normalized.pop("macro_geopolitics_overlay", None)
    geopolitics_candidate_input = normalize_macro_geopolitics_candidate_input(
        raw_payload.get("macro_geopolitics_candidate_input")
    )
    if geopolitics_candidate_input:
        normalized["macro_geopolitics_candidate_input"] = geopolitics_candidate_input
    else:
        normalized.pop("macro_geopolitics_candidate_input", None)
    weekend_market_candidate_input = normalize_weekend_market_candidate_input(
        raw_payload.get("weekend_market_candidate_input")
    )
    if weekend_market_candidate_input:
        normalized["weekend_market_candidate_input"] = weekend_market_candidate_input
    else:
        normalized.pop("weekend_market_candidate_input", None)
    emergent_theme_rows = raw_payload.get("emergent_theme_candidates")
    if isinstance(emergent_theme_rows, list):
        normalized["emergent_theme_candidates"] = [
            candidate
            for candidate in (
                normalize_emergent_theme_candidate(item)
                for item in emergent_theme_rows
                if isinstance(item, dict) and clean_text(item.get("theme_name") or item.get("topic_name") or item.get("chain_name") or item.get("theme"))
            )
            if candidate
        ]
    else:
        normalized.pop("emergent_theme_candidates", None)
    market_strength_rows = raw_payload.get("market_strength_candidates")
    if isinstance(market_strength_rows, list):
        normalized["market_strength_candidates"] = [
            normalize_market_strength_candidate(item)
            for item in market_strength_rows
            if isinstance(item, dict) and clean_text(item.get("ticker"))
        ]
    else:
        normalized.pop("market_strength_candidates", None)
    sector_rankings = raw_payload.get("sector_rankings")
    if isinstance(sector_rankings, list):
        normalized["sector_rankings"] = normalize_sector_rankings(sector_rankings)
    else:
        normalized.pop("sector_rankings", None)
    sector_views = raw_payload.get("sector_views")
    if isinstance(sector_views, list):
        normalized["sector_views"] = normalize_sector_views(sector_views)
    else:
        normalized.pop("sector_views", None)
    try:
        sector_rank_limit = int(raw_payload.get("sector_rank_limit") or 0)
    except (TypeError, ValueError):
        sector_rank_limit = 0
    if sector_rank_limit > 0:
        normalized["sector_rank_limit"] = sector_rank_limit
    else:
        normalized.pop("sector_rank_limit", None)
    setup_launch_rows = raw_payload.get("setup_launch_candidates")
    if isinstance(setup_launch_rows, list):
        normalized["setup_launch_candidates"] = [
            normalize_setup_launch_candidate(item)
            for item in setup_launch_rows
            if isinstance(item, dict) and clean_text(item.get("ticker"))
        ]
    else:
        normalized.pop("setup_launch_candidates", None)
    strategic_themes = raw_payload.get("strategic_base_watch_themes")
    if isinstance(strategic_themes, list):
        normalized["strategic_base_watch_themes"] = list(
            dict.fromkeys(clean_text(item) for item in strategic_themes if clean_text(item))
        )
    else:
        normalized.pop("strategic_base_watch_themes", None)
    local_stock_pool = normalize_local_stock_pool_from_request(raw_payload)
    if local_stock_pool:
        normalized["local_stock_pool"] = local_stock_pool
        normalized["candidate_tickers"] = merge_local_pool_candidate_tickers(
            normalized.get("candidate_tickers", []),
            local_stock_pool,
        )
    else:
        normalized.pop("local_stock_pool", None)
    local_daily_bars_source = normalize_local_daily_bars_source(raw_payload)
    if local_daily_bars_source:
        normalized["local_daily_bars_source"] = local_daily_bars_source
    else:
        normalized.pop("local_daily_bars_source", None)
    if raw_payload.get("fresh_discovery_required") is True:
        normalized["fresh_discovery_required"] = True
    else:
        normalized.pop("fresh_discovery_required", None)
    fresh_sessions = raw_payload.get("fresh_discovery_required_sessions")
    if isinstance(fresh_sessions, list):
        normalized["fresh_discovery_required_sessions"] = list(
            dict.fromkeys(clean_text(item).lower() for item in fresh_sessions if clean_text(item))
        )
    else:
        normalized.pop("fresh_discovery_required_sessions", None)
    session_type = clean_text(raw_payload.get("session_type")).lower()
    if session_type:
        normalized["session_type"] = session_type
    else:
        normalized.pop("session_type", None)
    trading_plan_pool_role = clean_text(raw_payload.get("trading_plan_pool_role"))
    if trading_plan_pool_role:
        normalized["trading_plan_pool_role"] = trading_plan_pool_role
    else:
        normalized.pop("trading_plan_pool_role", None)
    try:
        market_strength_universe_limit = int(raw_payload.get("market_strength_universe_limit") or 0)
    except (TypeError, ValueError):
        market_strength_universe_limit = 0
    if market_strength_universe_limit > 0:
        normalized["market_strength_universe_limit"] = market_strength_universe_limit
    else:
        normalized.pop("market_strength_universe_limit", None)
    batch_path = clean_text(normalized.get("x_style_batch_result_path"))
    if batch_path:
        path = Path(batch_path).expanduser().resolve()
        if path.exists():
            try:
                batch_payload = load_json(path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                batch_payload = {}
            if batch_payload:
                handles, overlays = extract_x_style_overlays_from_result(
                    batch_payload,
                    selected_handles=normalized.get("x_style_selected_handles", []),
                )
                if handles:
                    normalized["x_style_selected_handles"] = handles
                if overlays:
                    normalized["x_style_overlays"] = overlays
                risk_alerts = extract_x_risk_alerts_from_result(
                    batch_payload,
                    selected_handles=normalized.get("x_style_selected_handles", []),
                )
                if risk_alerts:
                    normalized["x_risk_alerts"] = risk_alerts
                x_discovery_candidates = build_x_style_discovery_candidates(
                    batch_payload,
                    selected_handles=normalized.get("x_style_selected_handles", []),
                )
                if x_discovery_candidates:
                    existing = normalized.get("event_discovery_candidates")
                    existing_rows = existing if isinstance(existing, list) else []
                    normalized["event_discovery_candidates"] = existing_rows + x_discovery_candidates

    x_discovery_request = raw_payload.get("x_discovery_request")
    x_discovery_request_path = raw_payload.get("x_discovery_request_path")
    if not isinstance(x_discovery_request, dict) and clean_text(x_discovery_request_path):
        try:
            x_discovery_request = load_json(clean_text(x_discovery_request_path))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            x_discovery_request = None
    if isinstance(x_discovery_request, dict):
        try:
            from x_stock_picker_style_runtime import run_x_stock_picker_style, run_x_stock_picker_style_batch
        except ModuleNotFoundError:
            x_result = {}
        else:
            is_batch_request = bool(
                isinstance(x_discovery_request.get("subject_registry"), dict)
                or clean_text(x_discovery_request.get("subject_registry_path"))
                or isinstance(x_discovery_request.get("subject_overrides_by_handle"), dict)
                or isinstance(x_discovery_request.get("shared_request"), dict)
                or isinstance(x_discovery_request.get("selected_handles"), list)
            )
            if is_batch_request:
                x_result = run_x_stock_picker_style_batch(deepcopy(x_discovery_request))
                x_discovery_context = build_x_discovery_context(x_discovery_request)
                if x_discovery_context.get("chain_map"):
                    normalized["x_discovery_context"] = x_discovery_context
            else:
                x_result = run_x_stock_picker_style(deepcopy(x_discovery_request))
        x_request_candidates = build_x_style_discovery_candidates(x_result)
        if x_request_candidates:
            existing = normalized.get("event_discovery_candidates")
            existing_rows = existing if isinstance(existing, list) else []
            normalized["event_discovery_candidates"] = existing_rows + x_request_candidates
    return normalized


def normalize_request(raw_payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_request_with_compiled(raw_payload, _compiled.normalize_request)


def infer_execution_state(candidate: dict[str, Any]) -> str:
    tier_tags = set(candidate.get("tier_tags", []) or [])
    failures = set(candidate.get("hard_filter_failures", []) or [])
    if candidate.get("fallback_cache_only") or "fallback_cache_only" in tier_tags:
        return "stale_cache"
    if clean_text(candidate.get("bars_source")) == "eastmoney_cache":
        return "fresh_cache"
    if candidate.get("fallback_snapshot_only") or "bars_fetch_failed" in failures:
        return "blocked"
    return "live"


def build_bars_fetch_failed_candidate(candidate: dict[str, Any], error: Exception | str) -> dict[str, Any]:
    ticker = str(candidate.get("ticker", "")).strip()
    name = str(candidate.get("name", "")).strip()
    return {
        "ticker": ticker,
        "name": name,
        "code": str(candidate.get("code", "")).strip(),
        "sector": str(candidate.get("sector", "")).strip(),
        "board": str(candidate.get("board", "")).strip(),
        "price": candidate.get("price"),
        "open": candidate.get("open"),
        "high": candidate.get("high"),
        "low": candidate.get("low"),
        "pre_close": candidate.get("pre_close"),
        "day_pct": candidate.get("day_pct"),
        "pct_from_60d": candidate.get("pct_from_60d"),
        "pct_from_ytd": candidate.get("pct_from_ytd"),
        "pe_ttm": candidate.get("pe_ttm"),
        "pb": candidate.get("pb"),
        "free_float_market_cap": candidate.get("free_float_market_cap"),
        "total_market_cap": candidate.get("total_market_cap"),
        "turnover_rate_pct": candidate.get("turnover_rate_pct"),
        "day_turnover_cny": candidate.get("day_turnover_cny"),
        "day_volume_shares": candidate.get("day_volume_shares"),
        "keep": False,
        "top_pick_eligible": False,
        "hard_filter_failures": ["bars_fetch_failed"],
        "scores": {},
        "score_components": {
            "trend_template_score": 0.0,
            "rs_and_leadership_score": 0.0,
            "fundamental_acceleration_score": 0.0,
            "structured_catalyst_score": 0.0,
            "vcp_or_contraction_score": 0.0,
            "liquidity_and_participation_score": 0.0,
            "cap_multiplier": 1.0,
            "raw_total_score": 0.0,
            "adjusted_total_score": 0.0,
        },
        "price_snapshot": {},
        "trend_template": {},
        "structured_catalyst_snapshot": {},
        "fundamental_snapshot": {},
        "vcp_snapshot": {},
        "cap_snapshot": {},
        "price_paths": {},
        "backtest_summary": {},
        "trade_card": {},
        "bars_fetch_error": str(error or "").strip(),
        "execution_state": "blocked",
    }


def last_bar_date_from_rows(rows: list[dict[str, Any]]) -> str:
    for row in reversed(rows or []):
        if not isinstance(row, dict):
            continue
        for key in ("date", "trade_date"):
            value = clean_text(row.get(key))
            if value:
                return value[:10]
    return ""


def last_cached_trade_date_from_row_sets(row_sets: list[list[dict[str, Any]]]) -> str:
    latest = ""
    for rows in row_sets:
        current = last_bar_date_from_rows(rows or [])
        if current and (not latest or current > latest):
            latest = current
    return latest


def resolve_cache_baseline_metadata(
    target_trade_date: str,
    row_sets: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    target = clean_text(target_trade_date)[:10]
    baseline = last_cached_trade_date_from_row_sets(row_sets)
    if not target or not baseline:
        return {
            "baseline_trade_date": "",
            "cache_baseline_only": False,
            "live_supplement_status": "",
        }
    if baseline >= target:
        return {
            "baseline_trade_date": "",
            "cache_baseline_only": False,
            "live_supplement_status": "",
        }
    return {
        "baseline_trade_date": baseline,
        "cache_baseline_only": True,
        "live_supplement_status": "unavailable",
    }


def classify_eastmoney_cache_freshness(
    rows: list[dict[str, Any]] | None,
    target_trade_date: str,
) -> dict[str, str]:
    normalized_target = clean_text(target_trade_date)[:10]
    last_bar_date = last_bar_date_from_rows(rows or [])
    if not normalized_target or not last_bar_date:
        return {"mode": "missing_cache", "last_bar_date": last_bar_date}
    if last_bar_date == normalized_target:
        return {"mode": "fresh_cache", "last_bar_date": last_bar_date}
    target_dt = parse_date(normalized_target)
    last_dt = parse_date(last_bar_date)
    if not target_dt or not last_dt:
        return {"mode": "missing_cache", "last_bar_date": last_bar_date}
    effective_target_dt = target_dt
    if effective_target_dt.weekday() >= 5:
        effective_target_dt += timedelta(days=7 - effective_target_dt.weekday())
    gap_days = 0
    cursor = last_dt
    # Count weekday steps against the next trading session boundary.
    while cursor < effective_target_dt:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            gap_days += 1
    if gap_days == 1:
        return {"mode": "stale_one_day", "last_bar_date": last_bar_date}
    return {"mode": "stale_too_old", "last_bar_date": last_bar_date}


def choose_eastmoney_cache_recovery_mode(
    rows: list[dict[str, Any]] | None,
    target_trade_date: str,
) -> dict[str, Any]:
    freshness = classify_eastmoney_cache_freshness(rows or [], target_trade_date)
    mode = freshness["mode"]
    if mode == "fresh_cache":
        return {
            "mode": "fresh_cache",
            "bars_source": "eastmoney_cache",
            "rows": list(rows or []),
            "last_bar_date": freshness.get("last_bar_date", ""),
        }
    return {
        "mode": mode,
        "bars_source": "",
        "rows": [],
        "last_bar_date": freshness.get("last_bar_date", ""),
    }


def build_bars_cache_rescue_candidate(
    candidate: dict[str, Any],
    cached_rows: list[dict[str, Any]] | None,
    target_trade_date: str,
) -> dict[str, Any] | None:
    cache_mode = classify_eastmoney_cache_freshness(cached_rows or [], target_trade_date)
    if cache_mode.get("mode") != "stale_one_day":
        return None
    snapshot_rows = list(cached_rows or [])
    if not snapshot_rows:
        return None
    latest = snapshot_rows[-1]
    snapshot = {
        "close": latest.get("close"),
        "pct_chg": latest.get("pct_chg"),
        "sma20": latest.get("boll"),
        "sma50": latest.get("close_50_sma"),
        "rsi14": latest.get("rsi"),
        "volume_ratio": latest.get("volume_ratio"),
    }
    rescued = build_bars_fallback_rescue_candidate(candidate, snapshot)
    if not rescued:
        return None
    rescued["bars_source"] = "eastmoney_cache"
    rescued["fallback_cache_only"] = True
    rescued["execution_state"] = "stale_cache"
    rescued["tier_tags"] = unique_strings(
        list(rescued.get("tier_tags", [])) + ["fallback_cache_only"]
    )
    return rescued


def eastmoney_cached_bars_for_candidate(
    ticker: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    from tradingagents_eastmoney_market import (
        EASTMONEY_DEFAULT_UT,
        cache_path,
        eastmoney_secid,
        format_date_yyyymmdd,
        parse_daily_items,
    )

    normalized_ticker = clean_text(ticker)
    normalized_start = clean_text(start_date)[:10]
    normalized_end = clean_text(end_date)[:10]
    if not normalized_ticker or not normalized_start or not normalized_end:
        return []
    query = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "lmt": "10000",
        "ut": EASTMONEY_DEFAULT_UT,
        "secid": eastmoney_secid(normalized_ticker),
        "beg": format_date_yyyymmdd(normalized_start),
        "end": format_date_yyyymmdd(normalized_end),
    }
    cache_name = f"kline-{json.dumps(query, ensure_ascii=True, sort_keys=True)}.json"
    path = cache_path(cache_name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = parse_daily_items(payload)
    return rows if isinstance(rows, list) else []


def eastmoney_cached_intraday_bars_for_candidate(
    ticker: str,
    trade_date: str,
    klt: int = 104,
) -> list[dict[str, Any]]:
    """Cache-first intraday bars fetch, mirroring eastmoney_cached_bars_for_candidate."""
    from tradingagents_eastmoney_market import (
        EASTMONEY_DEFAULT_UT,
        _parse_intraday_items,
        cache_path,
        eastmoney_secid,
        format_date_yyyymmdd,
    )

    normalized_ticker = clean_text(ticker)
    normalized_date = clean_text(trade_date)[:10]
    if not normalized_ticker or not normalized_date:
        return []
    query = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": str(klt),
        "fqt": "0",
        "lmt": "10000",
        "ut": EASTMONEY_DEFAULT_UT,
        "secid": eastmoney_secid(normalized_ticker),
        "beg": format_date_yyyymmdd(normalized_date),
        "end": format_date_yyyymmdd(normalized_date),
    }
    cache_name = f"kline-{json.dumps(query, ensure_ascii=True, sort_keys=True)}.json"
    path = cache_path(cache_name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = _parse_intraday_items(payload)
    if not isinstance(rows, list):
        return []
    date_prefix = normalized_date[:10]
    return [r for r in rows if str(r.get("timestamp", "")).startswith(date_prefix)]


def attach_cache_baseline_metadata(
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    enriched = deepcopy(result)
    request_obj = dict(enriched.get("request") or {})
    target_trade_date = clean_text(request_obj.get("analysis_time") or request_obj.get("target_date"))[:10]
    if not target_trade_date or not candidates:
        return enriched

    target_dt = parse_date(target_trade_date)
    if not target_dt:
        return enriched

    start_date = (target_dt - timedelta(days=420)).isoformat()
    row_sets: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        ticker = clean_text(candidate.get("ticker"))
        if not ticker:
            continue
        row_sets.append(eastmoney_cached_bars_for_candidate(ticker, start_date, target_trade_date))

    metadata = resolve_cache_baseline_metadata(target_trade_date, row_sets)
    filter_summary = dict(enriched.get("filter_summary") or {})
    filter_summary["cache_baseline_trade_date"] = metadata["baseline_trade_date"]
    filter_summary["cache_baseline_only"] = bool(metadata["cache_baseline_only"])
    filter_summary["live_supplement_status"] = metadata["live_supplement_status"]
    enriched["filter_summary"] = filter_summary
    enriched["report_markdown"] = prepend_report_metadata_lines(
        enriched.get("report_markdown") or "",
        build_cache_baseline_report_lines(enriched),
    )
    return enriched


def build_bars_source_summary(result: dict[str, Any]) -> dict[str, int]:
    decision_factors = result.get("decision_factors")
    if not isinstance(decision_factors, dict):
        decision_factors = build_decision_factors_from_result(result)

    summary = {
        "live_count": 0,
        "fresh_cache_count": 0,
        "stale_cache_count": 0,
        "blocked_count": 0,
    }
    seen: set[str] = set()
    for section in ("qualified", "near_miss", "blocked"):
        for item in decision_factors.get(section, []):
            if not isinstance(item, dict):
                continue
            ticker = clean_text(item.get("ticker"))
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            state = clean_text(item.get("execution_state")) or infer_execution_state(item)
            if state == "fresh_cache":
                summary["fresh_cache_count"] += 1
            elif state == "stale_cache":
                summary["stale_cache_count"] += 1
            elif state == "blocked":
                summary["blocked_count"] += 1
            else:
                summary["live_count"] += 1
    return summary


def build_cache_baseline_report_lines(result: dict[str, Any]) -> list[str]:
    summary = dict(result.get("filter_summary") or {})
    baseline_trade_date = clean_text(summary.get("cache_baseline_trade_date"))
    lines: list[str] = []
    if baseline_trade_date:
        lines.append(f"- 数据基线：最近交易日盘后缓存（{baseline_trade_date}）")
    status = clean_text(summary.get("live_supplement_status"))
    if status == "unavailable":
        lines.append("- 实时补充：不可用，沿用缓存基线")
    elif status == "updated":
        lines.append("- 实时补充：已更新部分数据")

    bars_source_summary = summary.get("bars_source_summary") if isinstance(summary.get("bars_source_summary"), dict) else {}
    if bars_source_summary:
        lines.append(
            "- 执行闭环：live={live_count}，fresh_cache={fresh_cache_count}，stale_cache={stale_cache_count}，blocked={blocked_count}".format(
                live_count=int(bars_source_summary.get("live_count") or 0),
                fresh_cache_count=int(bars_source_summary.get("fresh_cache_count") or 0),
                stale_cache_count=int(bars_source_summary.get("stale_cache_count") or 0),
                blocked_count=int(bars_source_summary.get("blocked_count") or 0),
            )
        )
        if int(bars_source_summary.get("blocked_count") or 0) > 0:
            lines.append("- 缓存覆盖偏薄：可先运行 `preheat_eastmoney_cache.py` 预热后再重试 shortlist。")
    if not lines:
        return []
    return lines


def prepend_report_metadata_lines(report_markdown: str, metadata_lines: list[str]) -> str:
    body = str(report_markdown or "").rstrip()
    if not metadata_lines:
        return body + ("\n" if body else "")
    if not body:
        return "\n".join(metadata_lines).strip() + "\n"

    lines = body.splitlines()
    if metadata_lines[0] in lines:
        return body + "\n"

    insert_at = 1 if lines and lines[0].startswith("# ") else 0
    merged_lines = lines[:insert_at]
    if insert_at:
        merged_lines.append("")
    merged_lines.extend(metadata_lines)
    if lines[insert_at:]:
        merged_lines.append("")
        merged_lines.extend(lines[insert_at:])
    return "\n".join(merged_lines).strip() + "\n"


def render_blocked_candidates_section(blocked_candidates: list[dict[str, Any]]) -> str:
    if not blocked_candidates:
        return ""
    lines = ["## Blocked Candidates", ""]
    for item in blocked_candidates:
        ticker = clean_text(item.get("ticker")) or "unknown"
        name = clean_text(item.get("name")) or ticker
        reason = clean_text(item.get("bars_fetch_error")) or "bars_fetch_failed"
        lines.append(f"- `{ticker}` {name}: `{reason}`")
    return "\n".join(lines).strip()


def replace_blocked_candidates_section(report_markdown: str, blocked_candidates: list[dict[str, Any]]) -> str:
    body = str(report_markdown or "").rstrip()
    marker = "\n## Blocked Candidates"
    if marker in body:
        body = body.split(marker, 1)[0].rstrip()
    section = render_blocked_candidates_section(blocked_candidates)
    if not section:
        return body + ("\n" if body else "")
    return "\n\n".join(part for part in [body, section] if part).strip() + "\n"


def prune_rescued_blocked_candidates(
    enriched: dict[str, Any],
    rescued_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rescued_tickers = {
        clean_text(item.get("ticker"))
        for item in rescued_rows
        if isinstance(item, dict) and clean_text(item.get("ticker"))
    }
    if not rescued_tickers:
        return enriched

    updated = deepcopy(enriched)
    blocked_candidates = [
        item
        for item in updated.get("blocked_candidates", [])
        if isinstance(item, dict) and clean_text(item.get("ticker")) not in rescued_tickers
    ]
    updated["blocked_candidates"] = blocked_candidates

    filter_summary = dict(updated.get("filter_summary") or {})
    filter_summary["blocked_candidate_count"] = len(blocked_candidates)
    filter_summary["bars_fetch_failed_tickers"] = [
        clean_text(item.get("ticker"))
        for item in blocked_candidates
        if clean_text(item.get("ticker"))
    ]
    updated["filter_summary"] = filter_summary
    updated["report_markdown"] = replace_blocked_candidates_section(
        updated.get("report_markdown") or "",
        blocked_candidates,
    )
    return updated


def enrich_degraded_live_result(result: dict[str, Any], failure_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not failure_candidates:
        enriched = deepcopy(result)
        metadata_lines = build_cache_baseline_report_lines(enriched)
        if metadata_lines:
            enriched["report_markdown"] = prepend_report_metadata_lines(
                enriched.get("report_markdown") or "",
                metadata_lines,
            )
        return enriched

    enriched = deepcopy(result)
    filter_summary = dict(enriched.get("filter_summary") or {})
    tickers = unique_strings([item.get("ticker") for item in failure_candidates])
    filter_summary["blocked_candidate_count"] = len(tickers)
    filter_summary["bars_fetch_failed_tickers"] = tickers
    enriched["filter_summary"] = filter_summary
    enriched["blocked_candidates"] = deepcopy(failure_candidates)

    failure_by_ticker = {clean_text(item.get("ticker")): item for item in failure_candidates if clean_text(item.get("ticker"))}
    dropped = []
    for item in enriched.get("dropped", []):
        if not isinstance(item, dict):
            dropped.append(item)
            continue
        failure = failure_by_ticker.get(clean_text(item.get("ticker")))
        if not failure:
            dropped.append(item)
            continue
        merged = dict(item)
        for key in ("sector", "board", "price", "bars_fetch_error"):
            value = failure.get(key)
            if value not in (None, "", []):
                merged[key] = value
        dropped.append(merged)
    enriched["dropped"] = dropped

    report_markdown = str(enriched.get("report_markdown") or "").rstrip()
    lines = [report_markdown] if report_markdown else []
    lines.extend(["", "## Blocked Candidates", ""])
    for item in failure_candidates:
        ticker = clean_text(item.get("ticker")) or "unknown"
        name = clean_text(item.get("name")) or ticker
        reason = clean_text(item.get("bars_fetch_error")) or "bars_fetch_failed"
        lines.append(f"- `{ticker}` {name}: `{reason}`")
    enriched["report_markdown"] = prepend_report_metadata_lines(
        "\n".join(lines).strip(),
        build_cache_baseline_report_lines(enriched),
    )
    return enriched


def split_drop_reasons(value: Any) -> list[str]:
    reasons: list[str] = []
    for chunk in str(value or "").split(","):
        text = clean_text(chunk)
        if text:
            reasons.append(text)
    return reasons


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_candidate_snapshot_from_rows(ticker: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = dict(rows[-1]) if rows else {}
    latest_close = to_float(latest.get("close"))
    first_close = to_float(rows[0].get("close")) if rows else 0.0
    trailing_60 = rows[-60] if len(rows) >= 60 else (rows[0] if rows else {})
    ref_60 = to_float(trailing_60.get("close"))
    local_technical = build_local_technical_snapshot(rows)

    pct_from_60d = ((latest_close - ref_60) / ref_60 * 100.0) if ref_60 else 0.0
    pct_from_ytd = ((latest_close - first_close) / first_close * 100.0) if first_close else 0.0
    snapshot = {
        "ticker": ticker,
        "name": ticker,
        "price": latest_close,
        "open": to_float(latest.get("open")),
        "high": to_float(latest.get("high")),
        "low": to_float(latest.get("low")),
        "pre_close": to_float(latest.get("pre_close")),
        "day_pct": to_float(latest.get("pct_chg")),
        "day_turnover_cny": to_float(latest.get("amount")),
        "day_volume_shares": to_float(latest.get("vol")),
        "pct_from_60d": round(pct_from_60d, 2),
        "pct_from_ytd": round(pct_from_ytd, 2),
    }
    if local_technical.get("price_snapshot"):
        snapshot["price_snapshot"] = local_technical["price_snapshot"]
    if local_technical.get("technical_snapshot"):
        snapshot["technical_snapshot"] = local_technical["technical_snapshot"]
        volume_meta = local_technical["technical_snapshot"].get("volume", {})
        if isinstance(volume_meta, dict):
            snapshot["volume_ratio"] = volume_meta.get("vol_ratio_5d")
    return snapshot


def hydrate_price_fields_from_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    entry = deepcopy(candidate)
    snapshot = entry.get("price_snapshot") if isinstance(entry.get("price_snapshot"), dict) else {}
    if not snapshot:
        return entry

    field_map = {
        "price": "close",
        "open": "open",
        "high": "high",
        "low": "low",
        "pre_close": "pre_close",
        "day_pct": "day_pct",
        "day_turnover_cny": "avg_turnover_20d",
    }
    for field, snapshot_key in field_map.items():
        if to_float(entry.get(field)) > 0:
            continue
        snapshot_value = to_float(snapshot.get(snapshot_key))
        if snapshot_value > 0:
            entry[field] = snapshot_value
    return entry


def remove_false_price_below_floor(candidate: dict[str, Any], min_price: float | int | None) -> dict[str, Any]:
    if min_price in (None, ""):
        return candidate
    failures = candidate.get("hard_filter_failures")
    if not isinstance(failures, list) or "price_below_floor" not in failures:
        return candidate
    effective_price = to_float(candidate.get("price"))
    if effective_price <= 0:
        snapshot = candidate.get("price_snapshot") if isinstance(candidate.get("price_snapshot"), dict) else {}
        effective_price = to_float(snapshot.get("close"))
    if effective_price < float(min_price):
        return candidate
    candidate["hard_filter_failures"] = [failure for failure in failures if failure != "price_below_floor"]
    return candidate


def build_diagnostic_scorecard_entry(
    candidate: dict[str, Any],
    keep_threshold: float | int | None = None,
    min_price: float | int | None = None,
) -> dict[str, Any]:
    entry = remove_false_price_below_floor(hydrate_price_fields_from_snapshot(candidate), min_price)
    scores = entry.get("scores") if isinstance(entry.get("scores"), dict) else {}
    score_components = entry.get("score_components") if isinstance(entry.get("score_components"), dict) else {}
    score = scores.get("adjusted_total_score")
    if score in (None, ""):
        score = score_components.get("adjusted_total_score")
    if score not in (None, ""):
        entry["score"] = float(score)
    if keep_threshold not in (None, "") and score not in (None, ""):
        entry["keep_threshold_gap"] = round(float(score) - float(keep_threshold), 2)
    entry["diagnostic_components"] = {
        "trend": score_components.get("trend_template_score"),
        "rs": score_components.get("rs_and_leadership_score"),
        "catalyst": score_components.get("structured_catalyst_score"),
        "liquidity": score_components.get("liquidity_and_participation_score"),
    }
    return entry


def apply_board_threshold_overrides(
    scorecard: list[dict[str, Any]],
    profile: str,
    base_keep_threshold: float,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Re-evaluate keep / gap per candidate using board-specific thresholds.

    The compiled runtime runs with the *lowest* keep_threshold so no candidate
    is prematurely discarded.  This function tightens the gate for boards that
    have a higher threshold (e.g. main_board 58 vs chinext 56).

    Returns (updated_scorecard, effective_thresholds_by_board).
    Only active for ``month_end_event_support_transition`` profile.
    """
    if profile != "month_end_event_support_transition" or not BOARD_THRESHOLD_OVERRIDES:
        return scorecard, {}

    effective: dict[str, float] = {}
    for entry in scorecard:
        ticker = str(entry.get("ticker") or "")
        board = _compiled.classify_board(ticker)
        override = BOARD_THRESHOLD_OVERRIDES.get(board)
        board_keep = override["keep_threshold"] if override else base_keep_threshold
        effective[board] = board_keep

        score = entry.get("score")
        if score is None:
            continue

        old_gap = entry.get("keep_threshold_gap")
        new_gap = round(float(score) - board_keep, 2)
        entry["keep_threshold_gap"] = new_gap
        entry["board"] = board
        entry["board_keep_threshold"] = board_keep

        # Demote: core said keep but score < board threshold
        if entry.get("keep") and score < board_keep:
            entry["keep"] = False
            entry["tier_tags"] = entry.get("tier_tags", []) + ["board_demoted"]

        # Promote: core said not-keep but score >= board threshold and no hard failures
        hard_failures = set(entry.get("hard_filter_failures") or [])
        if (
            not entry.get("keep")
            and score >= board_keep
            and not hard_failures - {"score_below_keep_threshold"}
        ):
            entry["keep"] = True
            entry["tier_tags"] = entry.get("tier_tags", []) + ["board_promoted"]

    return scorecard, effective


def split_universe_by_board(
    prepared_payload: dict[str, Any],
    track_configs: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Split a prepared request into per-track payloads by board classification.

    Returns ``(track_payloads, out_of_scope)`` where *track_payloads* maps
    track name to a deep-copied request whose ``universe_candidates`` and
    ``candidate_tickers`` contain only candidates belonging to that track, and
    *out_of_scope* is a list of candidate dicts that did not match any track
    (e.g. star-board tickers).

    Each track payload also has ``keep_threshold`` and
    ``strict_top_pick_threshold`` overridden from the track config.
    """
    configs = track_configs or TRACK_CONFIGS
    # Build a reverse lookup: board_value -> track_name
    board_to_track: dict[str, str] = {}
    for track_name, cfg in configs.items():
        for bv in cfg.get("board_values", ()):
            board_to_track[bv] = track_name

    universe = prepared_payload.get("universe_candidates") or []
    candidate_tickers = [clean_text(t) for t in prepared_payload.get("candidate_tickers", []) if clean_text(t)]
    history_by_ticker = prepared_payload.get("history_by_ticker") or {}

    # Classify each candidate
    track_candidates: dict[str, list[dict[str, Any]]] = {name: [] for name in configs}
    track_tickers: dict[str, list[str]] = {name: [] for name in configs}
    out_of_scope: list[dict[str, Any]] = []

    for candidate in universe:
        ticker = clean_text(candidate.get("ticker"))
        if not ticker:
            continue
        board = _compiled.classify_board(ticker)
        track_name = board_to_track.get(board)
        if track_name:
            track_candidates[track_name].append(candidate)
        else:
            out_of_scope.append({
                "ticker": ticker,
                "name": clean_text(candidate.get("name")) or ticker,
                "board": board,
                "drop_reason": "outside_track_scope",
            })

    # Also split candidate_tickers (for requests that use tickers instead of universe)
    for ticker in candidate_tickers:
        board = _compiled.classify_board(ticker)
        track_name = board_to_track.get(board)
        if track_name:
            track_tickers[track_name].append(ticker)

    # Build per-track payloads
    track_payloads: dict[str, dict[str, Any]] = {}
    for track_name, cfg in configs.items():
        payload = deepcopy(prepared_payload)
        payload["universe_candidates"] = track_candidates[track_name]
        if candidate_tickers:
            payload["candidate_tickers"] = track_tickers[track_name]
        # Filter history_by_ticker to only this track's tickers
        track_ticker_set = {clean_text(c.get("ticker")) for c in track_candidates[track_name]}
        if history_by_ticker:
            payload["history_by_ticker"] = {
                k: v for k, v in history_by_ticker.items() if k in track_ticker_set
            }
        # Apply track-specific thresholds
        payload["keep_threshold"] = cfg["keep_threshold"]
        payload["strict_top_pick_threshold"] = cfg["strict_top_pick_threshold"]
        # Tag the track
        payload["_track_name"] = track_name
        payload["_track_config"] = cfg
        track_payloads[track_name] = payload

    return track_payloads, out_of_scope


def compute_independent_source_count(candidate: dict[str, Any]) -> int:
    """Count independent information sources for T2 admission."""
    sources: set[tuple[str, str]] = set()
    for x in candidate.get("x_style_inputs", []):
        if x.get("source_account"):
            sources.add(("x", x["source_account"]))
    for ev in candidate.get("event_cards", []):
        src_type = ev.get("source_type", "")
        if src_type == "filing":
            sources.add(("filing", ev.get("source_id", "filing")))
        elif src_type == "company_event":
            sources.add(("company_event", ev.get("source_id", "company_event")))
    for d in candidate.get("discovery_candidates", []):
        sources.add(("discovery", d.get("ticker", "unknown")))
    return len(sources)


def classify_geopolitics_chain_bias(chain_name: str, overlay: dict[str, Any] | None) -> str:
    if not isinstance(overlay, dict):
        return ""
    chain = clean_text(chain_name)
    if not chain:
        return ""
    if chain in set(overlay.get("beneficiary_chains") or []):
        return "beneficiary"
    if chain in set(overlay.get("headwind_chains") or []):
        return "headwind"
    return ""


def compute_geopolitics_bias(candidate: dict[str, Any], overlay: dict[str, Any] | None) -> float:
    if not isinstance(overlay, dict):
        return 0.0
    regime = clean_text(overlay.get("regime_label"))
    if regime not in GEOPOLITICS_REGIME_LABELS:
        return 0.0
    chain_name = clean_text(candidate.get("chain_name") or candidate.get("sector_or_chain"))
    bias_kind = classify_geopolitics_chain_bias(chain_name, overlay)
    if not bias_kind:
        return 0.0
    magnitude_map = {
        "escalation": 1.5,
        "de_escalation": 1.5,
        "whipsaw": 0.5,
    }
    magnitude = magnitude_map.get(regime, 0.0)
    if regime == "escalation":
        return magnitude if bias_kind == "beneficiary" else -magnitude
    if regime == "de_escalation":
        return -magnitude if bias_kind == "beneficiary" else magnitude
    if regime == "whipsaw":
        return magnitude if bias_kind == "beneficiary" else -magnitude
    return 0.0


def sort_candidates_with_geopolitics_bias(
    candidates: list[dict[str, Any]],
    overlay: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        bias = compute_geopolitics_bias(item, overlay)
        enriched = item
        enriched["macro_geopolitics_bias"] = bias
        enriched["macro_geopolitics_bias_label"] = classify_geopolitics_chain_bias(
            clean_text(item.get("chain_name") or item.get("sector_or_chain")),
            overlay,
        )
        ordered.append(enriched)
    ordered.sort(
        key=lambda x: (x.get("adjusted_total_score", 0) + x.get("macro_geopolitics_bias", 0.0)),
        reverse=True,
    )
    return ordered


def should_promote_near_miss_to_event_driven(candidate: dict[str, Any]) -> bool:
    """Check if a near-miss candidate qualifies for T2 promotion."""
    if candidate.get("structured_catalyst_score", 0) >= 10:
        return True
    if candidate.get("discovery_bucket") == "qualified":
        return True
    if compute_independent_source_count(candidate) >= 2:
        return True
    return False


def assign_tiers(
    top_picks: list[dict[str, Any]],
    near_miss_candidates: list[dict[str, Any]],
    discovery_results: dict[str, list[dict[str, Any]]],
    all_assessed: list[dict[str, Any]],
    keep_threshold: float,
    *,
    geopolitics_overlay: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Assign candidates to T1/T2/T3/T4 tiers.

    Returns dict with keys "T1", "T2", "T3", "T4", each a list of
    candidate dicts with added "wrapper_tier" and "tier_tags" fields.
    """
    assigned_tickers: set[str] = set()
    tiers: dict[str, list[dict[str, Any]]] = {"T1": [], "T2": [], "T3": [], "T4": []}

    def is_market_strength_supplement(candidate: dict[str, Any]) -> bool:
        tier_tags = candidate.get("tier_tags") if isinstance(candidate.get("tier_tags"), list) else []
        return bool(candidate.get("market_strength_supplement")) or (
            clean_text(candidate.get("primary_event_type")) == "market_strength_scan"
        ) or (
            clean_text(candidate.get("event_type")) == "market_strength_scan"
        ) or (
            "market_strength_supplement" in tier_tags
        )

    # --- T1: top_picks from compiled core ---
    for c in sorted(
        top_picks,
        key=lambda x: x.get("adjusted_total_score", 0),
        reverse=True,
    )[:TIER_CAPS["T1"]]:
        c["wrapper_tier"] = "T1"
        c["tier_tags"] = c.get("tier_tags", [])
        tiers["T1"].append(c)
        assigned_tickers.add(c.get("ticker"))

    # --- T2 Path A: promoted near-miss ---
    ordered_near_miss = sort_candidates_with_geopolitics_bias(near_miss_candidates, geopolitics_overlay)
    qualified_rows = [
        c for c in discovery_results.get("qualified", [])
        if not is_market_strength_supplement(c)
    ]
    ordered_watch = sort_candidates_with_geopolitics_bias(
        [c for c in discovery_results.get("watch", []) if not is_market_strength_supplement(c)],
        geopolitics_overlay,
    )
    ordered_track = sort_candidates_with_geopolitics_bias(
        [c for c in discovery_results.get("track", []) if not is_market_strength_supplement(c)],
        geopolitics_overlay,
    )
    supplement_candidates = sort_candidates_with_geopolitics_bias(
        [
            c
            for c in (
                list(discovery_results.get("qualified", []))
                + list(discovery_results.get("watch", []))
                + list(discovery_results.get("track", []))
            )
            if is_market_strength_supplement(c)
        ],
        geopolitics_overlay,
    )

    for c in ordered_near_miss:
        if c.get("ticker") in assigned_tickers:
            continue
        if should_promote_near_miss_to_event_driven(c):
            c["wrapper_tier"] = "T2"
            c["tier_tags"] = c.get("tier_tags", []) + ["near_miss_promoted"]
            tiers["T2"].append(c)
            assigned_tickers.add(c.get("ticker"))
            if len(tiers["T2"]) >= TIER_CAPS["T2"]:
                break

    # --- T2 Path B: discovery qualified ---
    for c in qualified_rows:
        if c.get("ticker") in assigned_tickers:
            continue
        if len(tiers["T2"]) >= TIER_CAPS["T2"]:
            break
        c["wrapper_tier"] = "T2"
        c["tier_tags"] = c.get("tier_tags", []) + ["discovery_qualified"]
        tiers["T2"].append(c)
        assigned_tickers.add(c.get("ticker"))

    # --- T3: remaining near-miss + discovery watch ---
    for c in ordered_near_miss:
        if c.get("ticker") in assigned_tickers:
            continue
        if len(tiers["T3"]) >= TIER_CAPS["T3"]:
            break
        c["wrapper_tier"] = "T3"
        c["tier_tags"] = c.get("tier_tags", [])
        tiers["T3"].append(c)
        assigned_tickers.add(c.get("ticker"))

    for c in ordered_watch:
        if c.get("ticker") in assigned_tickers:
            continue
        if len(tiers["T3"]) >= TIER_CAPS["T3"]:
            break
        c["wrapper_tier"] = "T3"
        c["tier_tags"] = c.get("tier_tags", []) + ["discovery_watch"]
        tiers["T3"].append(c)
        assigned_tickers.add(c.get("ticker"))

    for c in supplement_candidates:
        if c.get("ticker") in assigned_tickers:
            continue
        if len(tiers["T3"]) >= TIER_CAPS["T3"]:
            break
        c["wrapper_tier"] = "T3"
        c["market_strength_supplement"] = True
        c["tier_tags"] = c.get("tier_tags", []) + ["market_strength_supplement"]
        tiers["T3"].append(c)
        assigned_tickers.add(c.get("ticker"))

    # --- T4: discovery track + chain/sympathy ---
    for c in supplement_candidates:
        if c.get("ticker") in assigned_tickers:
            continue
        if len(tiers["T4"]) >= TIER_CAPS["T4"]:
            break
        c["wrapper_tier"] = "T4"
        c["market_strength_supplement"] = True
        c["tier_tags"] = c.get("tier_tags", []) + ["market_strength_supplement"]
        tiers["T4"].append(c)
        assigned_tickers.add(c.get("ticker"))

    for c in ordered_track:
        if c.get("ticker") in assigned_tickers:
            continue
        if len(tiers["T4"]) >= TIER_CAPS["T4"]:
            break
        c["wrapper_tier"] = "T4"
        c["tier_tags"] = c.get("tier_tags", []) + ["discovery_track"]
        tiers["T4"].append(c)
        assigned_tickers.add(c.get("ticker"))

    return tiers


def apply_catalyst_waiver(
    all_assessed: list[dict[str, Any]],
    profile: str,
    keep_threshold: float,
) -> list[dict[str, Any]]:
    """
    Wrapper-only reclassification for catalyst-only failures.

    Does NOT modify the core's keep field. Instead, returns candidates
    eligible for T3 via catalyst waiver. These should be merged into
    near_miss before calling assign_tiers.
    """
    WAIVER_PROFILES = {
        "month_end_event_support_transition",
        "broad_coverage_mode",
    }
    if profile not in WAIVER_PROFILES:
        return []

    waiver_candidates: list[dict[str, Any]] = []
    score_floor = keep_threshold - CATALYST_WAIVER_SCORE_GAP

    for c in all_assessed:
        # Skip if core said keep=True (already a top_pick)
        if c.get("keep"):
            continue
        failures = c.get("hard_filter_failures", [])
        # Must have exactly one failure and it must be catalyst
        if (
            len(failures) == 1
            and failures[0] == "no_structured_catalyst_within_window"
            and c.get("adjusted_total_score", 0) >= score_floor
        ):
            # Check not in hard exclusion list (defensive)
            if not HARD_EXCLUSION_FAILURES.intersection(failures):
                c["tier_tags"] = c.get("tier_tags", []) + ["catalyst_waived"]
                waiver_candidates.append(c)

    return waiver_candidates


def local_market_snapshot_for_candidate(ticker: str, analysis_date: str) -> dict[str, Any] | None:
    from tradingagents_decision_bridge_runtime import (
        smart_free_profile_name,
        summarize_local_market_snapshot,
    )

    normalized_ticker = clean_text(ticker)
    normalized_date = clean_text(analysis_date)[:10]
    if not normalized_ticker or not normalized_date:
        return None
    profile_name = smart_free_profile_name(normalized_ticker)
    if profile_name not in {"free_eastmoney_market", "free_tushare_market", "longbridge_market"}:
        return None
    try:
        snapshot = summarize_local_market_snapshot(
            profile_name=profile_name,
            normalized_ticker=normalized_ticker,
            analysis_date=normalized_date,
            failure_message="month_end_shortlist bars fallback",
        )
    except Exception:
        return None
    if not isinstance(snapshot, dict):
        return None
    return {
        "profile_name": profile_name,
        "close": snapshot.get("latest_close"),
        "pct_chg": snapshot.get("latest_pct_chg"),
        "sma20": snapshot.get("sma20"),
        "sma50": snapshot.get("sma50"),
        "rsi14": snapshot.get("rsi14"),
        "volume_ratio": snapshot.get("volume_ratio"),
    }


def classify_fallback_support_reason(candidate: dict[str, Any]) -> str:
    structured_snapshot = candidate.get("structured_catalyst_snapshot")
    structured_snapshot = structured_snapshot if isinstance(structured_snapshot, dict) else {}
    if structured_snapshot.get("structured_company_events"):
        return "structured_catalyst"
    discovery_bucket = clean_text(candidate.get("discovery_bucket"))
    if discovery_bucket == "qualified":
        return "discovery_qualified"
    if discovery_bucket == "watch":
        return "discovery_watch"
    if clean_text(candidate.get("chain_name")) or clean_text(candidate.get("trading_profile_bucket")):
        return "chain_support"
    return ""


def snapshot_allows_fallback_observation(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    try:
        close = float(snapshot.get("close"))
        pct_chg = float(snapshot.get("pct_chg"))
        sma20 = float(snapshot.get("sma20"))
        sma50 = float(snapshot.get("sma50"))
        rsi14 = float(snapshot.get("rsi14"))
    except (TypeError, ValueError):
        return False
    if close < min(sma20, sma50):
        return False
    if rsi14 < 35.0:
        return False
    if pct_chg <= -5.0:
        return False
    return True


def build_bars_fallback_rescue_candidate(
    candidate: dict[str, Any],
    snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    support_reason = classify_fallback_support_reason(candidate)
    if not support_reason or not snapshot_allows_fallback_observation(snapshot):
        return None
    rescued = deepcopy(candidate)
    rescued["keep"] = False
    rescued["midday_status"] = "near_miss"
    rescued["wrapper_tier"] = "T3"
    rescued["fallback_support_reason"] = support_reason
    rescued["fallback_snapshot"] = deepcopy(snapshot)
    rescued["fallback_snapshot_only"] = True
    rescued["execution_state"] = "blocked"
    rescued["tier_tags"] = unique_strings(
        list(rescued.get("tier_tags", [])) + ["low_confidence_fallback", "fallback_snapshot_only"]
    )
    return rescued


def evaluate_with_coverage_fallback(
    candidates: list[dict[str, Any]],
    bars_data: dict[str, Any],
    profile: str,
    assess_fn: Callable,
) -> tuple[list[dict[str, Any]], str, str]:
    """
    Two-round evaluation. If Round 1 produces < TWO_ROUND_THRESHOLD
    top_picks and profile is not already broad_coverage_mode,
    re-evaluate all candidates with broad_coverage_mode.

    Returns: (all_assessed, profile_used, round_info)
    """
    # Round 1
    all_assessed: list[dict[str, Any]] = []
    for c in candidates:
        result = assess_fn(c, bars_data, profile)
        all_assessed.append(result)

    top_picks = [c for c in all_assessed if c.get("keep")]

    if len(top_picks) >= TWO_ROUND_THRESHOLD or profile == "broad_coverage_mode":
        return all_assessed, profile, "round_1"

    # Round 2: re-evaluate everything with broad_coverage_mode
    all_assessed_r2: list[dict[str, Any]] = []
    for c in candidates:
        result = assess_fn(c, bars_data, "broad_coverage_mode")
        all_assessed_r2.append(result)

    return all_assessed_r2, "broad_coverage_mode", "round_2"


def apply_floor_policy(
    tiers: dict[str, list[dict[str, Any]]],
    all_assessed: list[dict[str, Any]],
    discovery_results: dict[str, list[dict[str, Any]]],
    keep_threshold: float,
) -> dict[str, list[dict[str, Any]]]:
    """
    If total names < MIN_COVERAGE_TARGET, supplement from:
    1. Expanded near-miss (gap=NEAR_MISS_FLOOR_GAP)
    2. Relaxed discovery watch/track
    3. Score-sorted remaining candidates

    Never includes HARD_EXCLUSION_FAILURES candidates.
    Tags all supplemented names with [coverage_fill].
    """
    total = sum(len(v) for v in tiers.values())
    if total >= MIN_COVERAGE_TARGET:
        return tiers

    assigned_tickers: set[str] = set()
    for tier_list in tiers.values():
        for c in tier_list:
            assigned_tickers.add(c.get("ticker"))

    def is_excluded(c: dict[str, Any]) -> bool:
        failures = set(c.get("hard_filter_failures", []))
        return bool(HARD_EXCLUSION_FAILURES.intersection(failures))

    # Priority 1: expanded near-miss (gap=NEAR_MISS_FLOOR_GAP)
    for c in all_assessed:
        if total >= MIN_COVERAGE_TARGET:
            break
        if c.get("ticker") in assigned_tickers or is_excluded(c):
            continue
        score = c.get("adjusted_total_score", 0)
        gap = keep_threshold - score
        if 0 < gap <= NEAR_MISS_FLOOR_GAP:
            c["wrapper_tier"] = "T3"
            c["tier_tags"] = c.get("tier_tags", []) + ["coverage_fill"]
            tiers["T3"].append(c)
            assigned_tickers.add(c.get("ticker"))
            total += 1

    # Priority 2: relaxed discovery watch/track
    for c in discovery_results.get("watch", []) + discovery_results.get("track", []):
        if total >= MIN_COVERAGE_TARGET:
            break
        if c.get("ticker") in assigned_tickers or is_excluded(c):
            continue
        c["wrapper_tier"] = "T3"
        c["tier_tags"] = c.get("tier_tags", []) + ["coverage_fill"]
        tiers["T3"].append(c)
        assigned_tickers.add(c.get("ticker"))
        total += 1

    # Priority 3: score-sorted remaining
    remaining = [
        c for c in all_assessed
        if c.get("ticker") not in assigned_tickers and not is_excluded(c)
    ]
    remaining.sort(key=lambda x: x.get("adjusted_total_score", 0), reverse=True)
    for c in remaining:
        if total >= MIN_COVERAGE_TARGET:
            break
        c["wrapper_tier"] = "T3"
        c["tier_tags"] = c.get("tier_tags", []) + ["coverage_fill"]
        tiers["T3"].append(c)
        assigned_tickers.add(c.get("ticker"))
        total += 1

    return tiers


def build_near_miss_candidates(
    diagnostic_scorecard: list[dict[str, Any]],
    *,
    max_gap: float = NEAR_MISS_MAX_GAP,
) -> list[dict[str, Any]]:
    near_miss: list[dict[str, Any]] = []
    for item in diagnostic_scorecard:
        if not isinstance(item, dict):
            continue
        if item.get("keep"):
            continue
        if item.get("hard_filter_failures"):
            continue
        score = item.get("score")
        gap = item.get("keep_threshold_gap")
        if score in (None, "") or gap in (None, ""):
            continue
        try:
            gap_value = float(gap)
        except (TypeError, ValueError):
            continue
        if gap_value >= 0 or abs(gap_value) > float(max_gap):
            continue
        near_miss.append(deepcopy(item))
    return near_miss


def classify_midday_status(candidate: dict[str, Any], near_miss_tickers: set[str] | None = None) -> str:
    ticker = clean_text(candidate.get("ticker"))
    failures = candidate.get("hard_filter_failures")
    if isinstance(failures, list) and failures:
        return "blocked"
    if ticker and ticker in (near_miss_tickers or set()):
        return "near_miss"
    if candidate.get("keep"):
        return "qualified"
    return "watch"


def intraday_confirmation_gate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Apply confirmation gate to a marginally qualified candidate.

    If the candidate's midday_action is '可执行' but it meets any marginal
    condition, downgrade to '待确认' with midday_status 'pending_confirmation'.

    Marginal conditions (any one triggers the gate):
    - keep_threshold_gap <= 2 (marginal score)
    - structured_catalyst_score < 10 or absent (weak catalyst)
    - execution_state is 'fresh_cache' or 'stale_cache'
    - forced via 'review_force_gate' flag

    Returns a (possibly modified) copy of the candidate.
    """
    result = dict(candidate)
    action = clean_text(result.get("midday_action"))
    if action != "可执行":
        return result

    # Direction bypass: leader/high_beta + high signal → skip gate
    # Priority: review_force_gate always wins (checked first below)
    force_gate = bool(result.get("review_force_gate"))
    if not force_gate:
        tags = set(result.get("tier_tags") or [])
        direction_boost = result.get("direction_boost") if isinstance(result.get("direction_boost"), dict) else {}
        is_direction_ref = "direction_leader" in tags or "direction_high_beta" in tags
        is_high_signal = clean_text(direction_boost.get("signal_strength")) == "high"
        if is_direction_ref and is_high_signal:
            dk = clean_text(direction_boost.get("direction_key")) or ""
            result["gate_bypass_note"] = f"方向层免确认：{dk} 信号强度=high"
            return result  # bypass gate

    # Note when direction bypass is blocked by review_force_gate
    if force_gate:
        tags = set(result.get("tier_tags") or [])
        if "direction_leader" in tags or "direction_high_beta" in tags:
            result["gate_bypass_note"] = "方向层免确认：不适用（复盘强制门控优先）"

    # Check marginal conditions
    gap = result.get("keep_threshold_gap")
    try:
        gap_value = float(gap) if gap not in (None, "") else 999.0
    except (TypeError, ValueError):
        gap_value = 999.0

    catalyst_score = result.get("structured_catalyst_score")
    try:
        catalyst_value = float(catalyst_score) if catalyst_score not in (None, "") else 0.0
    except (TypeError, ValueError):
        catalyst_value = 0.0

    execution_state = clean_text(result.get("execution_state")) or infer_execution_state(result)
    # force_gate already computed above for direction bypass

    is_marginal_gap = gap_value <= 2.0
    is_weak_catalyst = catalyst_value < 10.0
    is_degraded_data = execution_state in ("fresh_cache", "stale_cache")

    if force_gate or is_marginal_gap or is_weak_catalyst or is_degraded_data:
        result["midday_action"] = "待确认"
        result["midday_status"] = "pending_confirmation"

    return result


def review_based_priority_boost(
    candidates: list[dict[str, Any]],
    prior_review_adjustments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply priority adjustments from a prior postclose review.

    For each adjustment, find the matching candidate by ticker and:
    - Apply priority_delta to score
    - Add tier tag ('review_upgraded' or 'review_downgraded')
    - Set review_force_gate if gate_next_run is True

    Returns a new list of (possibly modified) candidate copies.
    """
    if not prior_review_adjustments:
        return list(candidates)

    adj_by_ticker: dict[str, dict[str, Any]] = {}
    for adj in prior_review_adjustments:
        ticker = clean_text(adj.get("ticker"))
        if ticker:
            adj_by_ticker[ticker] = adj

    result = []
    for cand in candidates:
        c = dict(cand)
        ticker = clean_text(c.get("ticker"))
        if ticker in adj_by_ticker:
            adj = adj_by_ticker[ticker]
            try:
                delta = float(adj.get("priority_delta", 0))
            except (TypeError, ValueError):
                delta = 0.0
            current_score = c.get("score")
            try:
                c["score"] = round(float(current_score) + delta, 2) if current_score not in (None, "") else current_score
            except (TypeError, ValueError):
                pass
            tags = list(c.get("tier_tags") or [])
            adjustment_type = clean_text(adj.get("adjustment"))
            if adjustment_type == "upgrade":
                tags.append("review_upgraded")
            elif adjustment_type == "downgrade":
                tags.append("review_downgraded")
            c["tier_tags"] = tags
            if adj.get("gate_next_run"):
                c["review_force_gate"] = True
        result.append(c)
    return result


def cross_check_direction_tickers(
    direction_reference_map: list[dict[str, Any]],
    universe: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cross-check direction tickers against the fetched stock universe.

    For entries with a ticker: verify ticker exists in universe.
    For entries without a ticker: attempt match by name.
    Adds ``in_universe: bool`` to each leader/high_beta entry.
    """
    universe_tickers = {
        clean_text(row.get("ticker") or row.get("f12"))
        for row in universe
        if clean_text(row.get("ticker") or row.get("f12"))
    }
    universe_names: dict[str, str] = {}
    for row in universe:
        name = clean_text(row.get("name") or row.get("f14"))
        ticker = clean_text(row.get("ticker") or row.get("f12"))
        if name and ticker:
            universe_names[name] = ticker

    result = deepcopy(direction_reference_map)
    for entry in result:
        for group_key in ("leaders", "high_beta_names"):
            for item in entry.get(group_key, []):
                ticker = clean_text(item.get("ticker"))
                name = clean_text(item.get("name"))
                if ticker and ticker in universe_tickers:
                    item["in_universe"] = True
                elif not ticker and name and name in universe_names:
                    item["ticker"] = universe_names[name]
                    item["in_universe"] = True
                else:
                    item["in_universe"] = False
    return result


_DIRECTION_THEME_BOOST = {"high": 3, "medium": 1, "low": 0}
_DIRECTION_REFERENCE_BOOST = {"leader": 6, "high_beta": 4}
_DIRECTION_MOMENTUM_HALVED = {"theme": 1, "leader": 3, "high_beta": 2}


def direction_alignment_boost(
    candidates: list[dict[str, Any]],
    direction_reference_map: list[dict[str, Any]],
    weekend_market_candidate: dict[str, Any] | None,
    *,
    direction_momentum: list[dict[str, Any]] | None = None,
    geopolitics_overlay: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply two-tier direction alignment scoring to candidates.

    Tier 1: theme intersection boost (matched_themes ∩ direction topics).
    Tier 2: reference map match boost (ticker match in leaders/high_beta).
    Momentum modulation from prior review adjusts boost values.

    Returns a new list of (possibly modified) candidate copies.
    """
    if not weekend_market_candidate or not isinstance(weekend_market_candidate, dict):
        return [dict(c) for c in candidates]
    if weekend_market_candidate.get("status") == "insufficient_signal":
        return [dict(c) for c in candidates]
    if not direction_reference_map:
        return [dict(c) for c in candidates]

    headline_downweight = False
    if isinstance(geopolitics_overlay, dict):
        regime = clean_text(geopolitics_overlay.get("regime_label"))
        headline_risk = clean_text(geopolitics_overlay.get("headline_risk"))
        if regime in ("escalation", "whipsaw") and headline_risk == "high":
            headline_downweight = True

    signal_strength = clean_text(weekend_market_candidate.get("signal_strength")) or "low"

    # Build direction topic set from candidate_topics
    direction_topics: set[str] = set()
    for topic in weekend_market_candidate.get("candidate_topics", []):
        tn = clean_text(topic.get("topic_name"))
        if tn:
            direction_topics.add(tn)

    # Build ticker→(direction_key, role) lookup
    ticker_to_direction: dict[str, tuple[str, str, str]] = {}  # ticker → (key, label, role)
    direction_labels: dict[str, str] = {}
    for entry in direction_reference_map:
        dk = clean_text(entry.get("direction_key"))
        dl = clean_text(entry.get("direction_label")) or dk
        direction_labels[dk] = dl
        for item in entry.get("leaders", []):
            t = clean_text(item.get("ticker"))
            if t:
                ticker_to_direction[t] = (dk, dl, "leader")
        for item in entry.get("high_beta_names", []):
            t = clean_text(item.get("ticker"))
            if t and t not in ticker_to_direction:  # leader takes precedence
                ticker_to_direction[t] = (dk, dl, "high_beta")

    # Build momentum lookup: direction_key → momentum_signal
    momentum_by_key: dict[str, str] = {}
    for m in (direction_momentum or []):
        mk = clean_text(m.get("direction_key"))
        if mk:
            momentum_by_key[mk] = clean_text(m.get("momentum_signal")) or ""

    result = []
    for cand in candidates:
        c = dict(cand)
        matched_themes = set(c.get("matched_themes") or [])

        # Tier 1: theme intersection
        theme_delta = 0
        matched_direction_key = ""
        for dk in direction_topics:
            if dk in matched_themes:
                theme_delta = _DIRECTION_THEME_BOOST.get(signal_strength, 0)
                matched_direction_key = dk
                break

        # Tier 2: reference map match
        reference_delta = 0
        direction_role = ""
        ticker = clean_text(c.get("ticker"))
        if ticker in ticker_to_direction:
            dk, dl, role = ticker_to_direction[ticker]
            reference_delta = _DIRECTION_REFERENCE_BOOST.get(role, 0)
            direction_role = role
            if not matched_direction_key:
                matched_direction_key = dk

        if theme_delta == 0 and reference_delta == 0:
            result.append(c)
            continue

        # Momentum modulation
        momentum_signal = momentum_by_key.get(matched_direction_key, "")
        if momentum_signal == "fading":
            theme_delta = 0
            reference_delta = 0
        elif momentum_signal == "caution":
            theme_delta = _DIRECTION_MOMENTUM_HALVED["theme"] if theme_delta > 0 else 0
            if direction_role == "leader":
                reference_delta = _DIRECTION_MOMENTUM_HALVED["leader"] if reference_delta > 0 else 0
            elif direction_role == "high_beta":
                reference_delta = _DIRECTION_MOMENTUM_HALVED["high_beta"] if reference_delta > 0 else 0

        # Headline risk downweight (same halving as caution)
        if headline_downweight:
            if theme_delta > 0:
                theme_delta = min(theme_delta, _DIRECTION_MOMENTUM_HALVED["theme"])
            if direction_role == "leader":
                reference_delta = min(reference_delta, _DIRECTION_MOMENTUM_HALVED["leader"])
            elif direction_role == "high_beta":
                reference_delta = min(reference_delta, _DIRECTION_MOMENTUM_HALVED["high_beta"])

        total_delta = theme_delta + reference_delta
        if total_delta > 0:
            try:
                current = float(c.get("adjusted_total_score") or c.get("score") or 0)
                c["adjusted_total_score"] = round(current + total_delta, 2)
            except (TypeError, ValueError):
                pass

            tags = list(c.get("tier_tags") or [])
            if theme_delta > 0:
                tags.append("direction_theme_aligned")
            if direction_role:
                tags.append(f"direction_{direction_role}")
            c["tier_tags"] = tags

        c["direction_boost"] = {
            "theme_delta": theme_delta,
            "reference_delta": reference_delta,
            "total_delta": theme_delta + reference_delta,
            "direction_key": matched_direction_key,
            "direction_role": direction_role or None,
            "signal_strength": signal_strength,
        }
        if momentum_signal:
            c["direction_boost"]["momentum_signal"] = momentum_signal
        if headline_downweight:
            c["direction_boost"]["headline_downweight"] = True

        result.append(c)
    return result


def direction_tier_promotion(
    tiered_candidates: dict[str, list[dict[str, Any]]],
    direction_reference_map: list[dict[str, Any]],
    weekend_market_candidate: dict[str, Any] | None,
    *,
    direction_momentum: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Promote direction-aligned candidates between tiers.

    Only when signal_strength == "high":
    - T2 leader/high_beta → T1 (if T1 < 10)
    - T3 leader → T2 (if T2 < 5)
    Max 2 promotions per run.
    Momentum "caution" disables promotion for that direction.
    """
    if not weekend_market_candidate or not isinstance(weekend_market_candidate, dict):
        return dict(tiered_candidates)
    signal_strength = clean_text(weekend_market_candidate.get("signal_strength"))
    if signal_strength != "high":
        return dict(tiered_candidates)

    # Build momentum caution set
    caution_keys: set[str] = set()
    for m in (direction_momentum or []):
        if clean_text(m.get("momentum_signal")) == "caution":
            caution_keys.add(clean_text(m.get("direction_key")))

    # Build ticker→direction_key lookup
    ticker_to_key: dict[str, str] = {}
    for entry in direction_reference_map:
        dk = clean_text(entry.get("direction_key"))
        for item in entry.get("leaders", []):
            t = clean_text(item.get("ticker"))
            if t:
                ticker_to_key[t] = dk
        for item in entry.get("high_beta_names", []):
            t = clean_text(item.get("ticker"))
            if t and t not in ticker_to_key:
                ticker_to_key[t] = dk

    result = {k: list(v) for k, v in tiered_candidates.items()}
    promotions = 0
    max_promotions = 2

    # T2 → T1
    if promotions < max_promotions:
        remaining_t2 = []
        for c in result.get("T2", []):
            tags = set(c.get("tier_tags") or [])
            ticker = clean_text(c.get("ticker"))
            dk = ticker_to_key.get(ticker, "")
            is_direction = "direction_leader" in tags or "direction_high_beta" in tags
            if (
                is_direction
                and promotions < max_promotions
                and len(result.get("T1", [])) < TIER_CAPS["T1"]
                and dk not in caution_keys
            ):
                promoted = dict(c)
                promoted_tags = list(promoted.get("tier_tags") or [])
                promoted_tags.append("direction_promoted")
                promoted["tier_tags"] = promoted_tags
                promoted["wrapper_tier"] = "T1"
                result.setdefault("T1", []).append(promoted)
                promotions += 1
            else:
                remaining_t2.append(c)
        result["T2"] = remaining_t2

    # T3 → T2 (leaders only)
    if promotions < max_promotions:
        remaining_t3 = []
        for c in result.get("T3", []):
            tags = set(c.get("tier_tags") or [])
            ticker = clean_text(c.get("ticker"))
            dk = ticker_to_key.get(ticker, "")
            is_leader = "direction_leader" in tags
            if (
                is_leader
                and promotions < max_promotions
                and len(result.get("T2", [])) < TIER_CAPS["T2"]
                and dk not in caution_keys
            ):
                promoted = dict(c)
                promoted_tags = list(promoted.get("tier_tags") or [])
                promoted_tags.append("direction_promoted")
                promoted["tier_tags"] = promoted_tags
                promoted["wrapper_tier"] = "T2"
                result.setdefault("T2", []).append(promoted)
                promotions += 1
            else:
                remaining_t3.append(c)
        result["T3"] = remaining_t3

    return result


def build_discovery_lane_summary(discovery_rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"qualified_count": 0, "watch_count": 0, "track_count": 0}
    for item in discovery_rows:
        bucket = clean_text(item.get("discovery_bucket"))
        if bucket == "qualified":
            summary["qualified_count"] += 1
        elif bucket == "watch":
            summary["watch_count"] += 1
        else:
            summary["track_count"] += 1
    return summary


def build_discovery_candidates(raw_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        item = normalize_event_candidate(raw)
        item["rumor_confidence_range"] = compute_rumor_confidence_range(item)
        item["event_state"] = classify_event_state(item)
        item["market_validation_summary"] = classify_market_validation(item)
        item["trading_usability"] = classify_trading_usability(item)
        item["discovery_bucket"] = assign_discovery_bucket(item)
        rows.append(item)
    return rows


def build_setup_launch_markdown(rows: list[dict[str, Any]] | None) -> list[str]:
    items = [item for item in (rows or []) if isinstance(item, dict)]
    if not items:
        return []
    lines = ["", "## 筑底启动补充", ""]
    for item in items:
        ticker = clean_text(item.get("ticker"))
        name = clean_text(item.get("name")) or ticker
        lines.append(f"- `{ticker}` {name}")
        themes = item.get("theme_guess") if isinstance(item.get("theme_guess"), list) else []
        if themes:
            lines.append(
                f"  - 主题: `{', '.join(clean_text(theme) for theme in themes if clean_text(theme))}`"
            )
        reasons = item.get("setup_reasons") if isinstance(item.get("setup_reasons"), list) else []
        if reasons:
            lines.append(
                f"  - setup 理由: `{', '.join(clean_text(reason) for reason in reasons if clean_text(reason))}`"
            )
        lines.append(f"  - 结构修复: `{clean_text(item.get('structure_repair'))}`")
        lines.append(f"  - 量能回流: `{clean_text(item.get('volume_return'))}`")
        lines.append(f"  - RS 改善: `{clean_text(item.get('rs_improvement'))}`")
        lines.append(
            f"  - 底部状态: `{clean_text(item.get('distance_from_bottom_state'))}`"
        )
        lines.append(f"  - 来源: `{clean_text(item.get('source')) or 'setup_launch_scan'}`")
    return lines


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


def tabular_records(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if hasattr(payload, "to_dict"):
        try:
            records = payload.to_dict("records")
            if isinstance(records, list):
                return [row for row in records if isinstance(row, dict)]
        except Exception:
            return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def first_present_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def a_share_ticker_from_code(code_value: Any) -> tuple[str, str]:
    code = clean_text(code_value)
    if not re.fullmatch(r"\d{6}", code):
        return "", ""
    if code.startswith(("5", "6", "9")):
        return f"{code}.SS", "1"
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ", "0"
    return code, ""


def request_limit(request: dict[str, Any], key: str, default: int, *, max_value: int = 5000) -> int:
    try:
        value = int(request.get(key, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, max_value))


def default_akshare_market_strength_universe_fetcher(
    request: dict[str, Any],
    *,
    spot_fetcher: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    if spot_fetcher is None:
        import akshare as ak  # type: ignore[import-not-found]

        spot_fetcher = ak.stock_zh_a_spot_em
    limit = request_limit(request, "market_strength_universe_limit", MARKET_STRENGTH_UNIVERSE_LIMIT)
    rows: list[dict[str, Any]] = []
    for raw in tabular_records(spot_fetcher()):
        code = clean_text(first_present_value(raw, "代码", "code", "f12"))
        ticker, market_id = a_share_ticker_from_code(code)
        if not ticker:
            ticker = normalize_a_share_ticker(first_present_value(raw, "ticker", "symbol"))
            code = clean_text(code or ticker.split(".")[0])
            market_id = "1" if ticker.endswith(".SS") else "0" if ticker.endswith(".SZ") else ""
        if not ticker:
            continue
        day_pct = _finite_float(first_present_value(raw, "涨跌幅", "day_pct", "pct", "f3"))
        price = _finite_float(first_present_value(raw, "最新价", "price", "f2"))
        high = _finite_float(first_present_value(raw, "最高", "high", "f15"))
        low = _finite_float(first_present_value(raw, "最低", "low", "f16"))
        pre_close = _finite_float(first_present_value(raw, "昨收", "pre_close", "f18"))
        turnover = _finite_float(first_present_value(raw, "成交额", "day_turnover_cny", "f6"))
        turnover_rate = _finite_float(first_present_value(raw, "换手率", "turnover_rate_pct", "f8"))
        normalized = {
            "ticker": ticker,
            "f12": code,
            "f13": market_id,
            "f14": clean_text(first_present_value(raw, "名称", "name", "f14")) or ticker,
            "name": clean_text(first_present_value(raw, "名称", "name", "f14")) or ticker,
            "f2": price if price is not None else 0.0,
            "price": price if price is not None else 0.0,
            "f15": high if high is not None else 0.0,
            "high": high if high is not None else 0.0,
            "f16": low if low is not None else 0.0,
            "low": low if low is not None else 0.0,
            "f18": pre_close if pre_close is not None else 0.0,
            "pre_close": pre_close if pre_close is not None else 0.0,
            "f3": day_pct if day_pct is not None else 0.0,
            "day_pct": day_pct if day_pct is not None else 0.0,
            "f6": turnover if turnover is not None else 0.0,
            "day_turnover_cny": turnover if turnover is not None else 0.0,
            "f8": turnover_rate if turnover_rate is not None else 0.0,
            "turnover_rate_pct": turnover_rate if turnover_rate is not None else 0.0,
            "source": "akshare.stock_zh_a_spot_em",
        }
        industry = clean_text(first_present_value(raw, "行业", "industry", "sector", "f100"))
        if industry:
            normalized["industry"] = industry
            normalized["f100"] = industry
        rows.append(normalized)
    rows.sort(
        key=lambda row: (
            _finite_float(row.get("day_pct")) or 0.0,
            _finite_float(row.get("day_turnover_cny")) or 0.0,
        ),
        reverse=True,
    )
    return rows[:limit]


def normalize_akshare_sector_rank_rows(raw_rows: Any, *, sector_type: str, source: str, limit: int) -> list[dict[str, Any]]:
    normalized_inputs: list[dict[str, Any]] = []
    for index, raw in enumerate(tabular_records(raw_rows), start=1):
        sector_name = clean_text(first_present_value(raw, "板块名称", "sector_name", "name", "f14"))
        if not sector_name:
            continue
        normalized_inputs.append(
            {
                "sector_name": sector_name,
                "sector_type": sector_type,
                "sector_code": clean_text(first_present_value(raw, "板块代码", "sector_code", "code", "f12")),
                "source": source,
                "rank": first_present_value(raw, "排名", "rank") or index,
                "day_pct": first_present_value(raw, "涨跌幅", "day_pct", "pct", "f3"),
                "top_mover_count": first_present_value(raw, "上涨家数", "top_mover_count", "positive_top_mover_count"),
                "leader_name": clean_text(first_present_value(raw, "领涨股票", "leader_name", "leading_name", "f128")),
                "leader_ticker": clean_text(first_present_value(raw, "领涨股票代码", "leader_ticker", "leading_ticker", "f140")),
            }
        )
    rows = normalize_sector_rankings(normalized_inputs, default_sector_type=sector_type)
    for row in rows:
        row["sector_type"] = sector_type
        row["source"] = source
    rows.sort(
        key=lambda row: (
            _coerce_positive_int(row.get("rank")) or 999,
            -(_finite_float(row.get("day_pct")) or 0.0),
        )
    )
    return rows[:limit]


def default_akshare_sector_rankings_fetcher(
    request: dict[str, Any],
    *,
    industry_fetcher: Callable[[], Any] | None = None,
    concept_fetcher: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    if industry_fetcher is None or concept_fetcher is None:
        import akshare as ak  # type: ignore[import-not-found]

        if industry_fetcher is None:
            industry_fetcher = ak.stock_board_industry_name_em
        if concept_fetcher is None:
            concept_fetcher = ak.stock_board_concept_name_em
    limit = request_limit(request, "sector_rank_limit", SECTOR_RANK_LIMIT, max_value=100)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for sector_type, fetcher, source in (
        ("industry", industry_fetcher, "akshare.stock_board_industry_name_em"),
        ("concept", concept_fetcher, "akshare.stock_board_concept_name_em"),
    ):
        try:
            rows.extend(
                normalize_akshare_sector_rank_rows(
                    fetcher(),
                    sector_type=sector_type,
                    source=source,
                    limit=limit,
                )
            )
        except Exception as exc:
            errors.append(f"{sector_type}: {clean_text(exc) or exc.__class__.__name__}")
    if rows:
        return rows
    if errors:
        raise RuntimeError(f"akshare_sector_rankings_fetch_failed: {'; '.join(errors)}")
    return rows


def fetch_sina_market_center_rows(node: str, *, num: int = 80, sort: str = "changepercent", asc: int = 0) -> list[dict[str, Any]]:
    params = {
        "page": "1",
        "num": str(num),
        "sort": sort,
        "asc": str(asc),
        "node": node,
        "symbol": "",
        "_s_r_a": "page",
    }
    req = Request(
        f"{SINA_MARKET_CENTER_URL}?{urlencode(params)}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/stock/"},
        method="GET",
    )
    with urlopen(req, timeout=20) as response:
        text = response.read().decode("utf-8", errors="replace")
    payload = json.loads(text)
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def sina_ticker_from_row(row: dict[str, Any]) -> tuple[str, str, str]:
    symbol = clean_text(row.get("symbol")).lower()
    code = clean_text(row.get("code"))
    if symbol.startswith(("sh", "sz")) and len(symbol) >= 8:
        code = code or symbol[-6:]
        market_id = "1" if symbol.startswith("sh") else "0"
        suffix = "SS" if symbol.startswith("sh") else "SZ"
        return f"{code}.{suffix}", market_id, code
    ticker, market_id = a_share_ticker_from_code(code)
    return ticker, market_id, code


def normalize_sina_market_center_rows(
    raw_rows: Any,
    *,
    source: str,
    limit: int,
    sector_name: str = "",
) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for raw in tabular_records(raw_rows):
        ticker, market_id, code = sina_ticker_from_row(raw)
        if not ticker:
            continue
        day_pct = _finite_float(first_present_value(raw, "changepercent", "涨跌幅", "day_pct", "f3"))
        price = _finite_float(first_present_value(raw, "trade", "最新价", "price", "f2"))
        high = _finite_float(first_present_value(raw, "high", "最高", "f15"))
        low = _finite_float(first_present_value(raw, "low", "最低", "f16"))
        pre_close = _finite_float(first_present_value(raw, "settlement", "昨收", "pre_close", "f18"))
        turnover = _finite_float(first_present_value(raw, "amount", "成交额", "day_turnover_cny", "f6"))
        turnover_rate = _finite_float(first_present_value(raw, "turnoverratio", "换手率", "turnover_rate_pct", "f8"))
        row = {
            "ticker": ticker,
            "f12": code,
            "f13": market_id,
            "f14": clean_text(first_present_value(raw, "name", "名称", "f14")) or ticker,
            "name": clean_text(first_present_value(raw, "name", "名称", "f14")) or ticker,
            "f2": price if price is not None else 0.0,
            "price": price if price is not None else 0.0,
            "f15": high if high is not None else 0.0,
            "high": high if high is not None else 0.0,
            "f16": low if low is not None else 0.0,
            "low": low if low is not None else 0.0,
            "f18": pre_close if pre_close is not None else 0.0,
            "pre_close": pre_close if pre_close is not None else 0.0,
            "f3": day_pct if day_pct is not None else 0.0,
            "day_pct": day_pct if day_pct is not None else 0.0,
            "f6": turnover if turnover is not None else 0.0,
            "day_turnover_cny": turnover if turnover is not None else 0.0,
            "f8": turnover_rate if turnover_rate is not None else 0.0,
            "turnover_rate_pct": turnover_rate if turnover_rate is not None else 0.0,
            "source": source,
        }
        if sector_name:
            row["industry"] = sector_name
            row["f100"] = sector_name
        normalized_rows.append(row)
    normalized_rows.sort(
        key=lambda row: (
            _finite_float(row.get("day_pct")) or 0.0,
            _finite_float(row.get("day_turnover_cny")) or 0.0,
        ),
        reverse=True,
    )
    return normalized_rows[:limit]


def default_sina_market_strength_universe_fetcher(
    request: dict[str, Any],
    *,
    node_fetcher: Callable[[str, int], Any] | None = None,
) -> list[dict[str, Any]]:
    limit = request_limit(request, "market_strength_universe_limit", MARKET_STRENGTH_UNIVERSE_LIMIT)
    if node_fetcher is None:
        node_fetcher = lambda node, num: fetch_sina_market_center_rows(node, num=num)
    return normalize_sina_market_center_rows(
        node_fetcher("hs_a", limit),
        source="sina.market_center_hs_a",
        limit=limit,
    )


def default_sina_sector_rankings_fetcher(
    request: dict[str, Any],
    *,
    sector_nodes: list[tuple[str, str]] | tuple[tuple[str, str], ...] | None = None,
    node_fetcher: Callable[[str, int], Any] | None = None,
) -> list[dict[str, Any]]:
    limit = request_limit(request, "sector_rank_limit", SECTOR_RANK_LIMIT, max_value=100)
    nodes = list(sector_nodes or SINA_SW1_SECTOR_NODES)
    if node_fetcher is None:
        node_fetcher = lambda node, num: fetch_sina_market_center_rows(node, num=num)
    sector_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    sample_size = 8
    for sector_name, node in nodes:
        try:
            stock_rows = normalize_sina_market_center_rows(
                node_fetcher(node, sample_size),
                source="sina.market_center_sector_node",
                limit=sample_size,
                sector_name=sector_name,
            )
        except Exception as exc:
            errors.append(f"{node}: {clean_text(exc) or exc.__class__.__name__}")
            continue
        if not stock_rows:
            continue
        positive_rows = [row for row in stock_rows if (_finite_float(row.get("day_pct")) or 0.0) > 0]
        day_pct_rows = positive_rows[:5] if positive_rows else stock_rows[:5]
        day_pct = sum((_finite_float(row.get("day_pct")) or 0.0) for row in day_pct_rows) / max(len(day_pct_rows), 1)
        leader = stock_rows[0]
        sector_rows.append(
            {
                "sector_name": sector_name,
                "sector_type": "industry",
                "source": "sina.market_center_sector_node",
                "rank": 0,
                "day_pct": round(day_pct, 4),
                "top_mover_count": len(positive_rows),
                "leader_name": clean_text(leader.get("name")),
                "leader_ticker": clean_text(leader.get("ticker")),
            }
        )
    if not sector_rows and errors:
        raise RuntimeError(f"sina_sector_rankings_fetch_failed: {'; '.join(errors[:5])}")
    sector_rows.sort(
        key=lambda row: (
            -(_finite_float(row.get("day_pct")) or 0.0),
            -(_coerce_positive_int(row.get("top_mover_count")) or 0),
            clean_text(row.get("sector_name")),
        )
    )
    ranked_inputs: list[dict[str, Any]] = []
    for index, row in enumerate(sector_rows[:limit], start=1):
        ranked = dict(row)
        ranked["rank"] = index
        ranked_inputs.append(ranked)
    return normalize_sector_rankings(ranked_inputs, default_sector_type="industry")


def default_market_strength_universe_fetcher(request: dict[str, Any]) -> list[dict[str, Any]]:
    params = {
        "pn": "1",
        "pz": str(int(request.get("market_strength_universe_limit", MARKET_STRENGTH_UNIVERSE_LIMIT) or MARKET_STRENGTH_UNIVERSE_LIMIT)),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": MARKET_STRENGTH_MARKET_GROUPS,
        "fields": MARKET_STRENGTH_FIELDS,
    }
    request_url = f"{_compiled.EASTMONEY_CLIST_URL}?{urlencode(params)}"
    req = Request(
        request_url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        method="GET",
    )

    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = [item for item in safe_list(safe_dict(payload.get("data")).get("diff")) if isinstance(item, dict)]
            if rows:
                return rows
        except Exception as exc:
            last_error = exc
            time.sleep(1.0 * (attempt + 1))
    fallback_errors: list[str] = []
    for fallback_name, fallback_fetcher in (
        ("akshare", default_akshare_market_strength_universe_fetcher),
        ("sina", default_sina_market_strength_universe_fetcher),
    ):
        try:
            fallback_rows = fallback_fetcher(request)
            if fallback_rows:
                return fallback_rows
            fallback_errors.append(f"{fallback_name}: returned no rows")
        except Exception as fallback_exc:
            fallback_errors.append(f"{fallback_name}: {clean_text(fallback_exc) or fallback_exc.__class__.__name__}")
    fallback_note = f"; fallbacks_failed: {'; '.join(fallback_errors)}" if fallback_errors else ""
    raise RuntimeError(
        f"market_strength_universe_fetch_failed: {clean_text(last_error) or 'unknown'}{fallback_note}"
    ) from last_error


def _fetch_eastmoney_sector_rank_group(
    request: dict[str, Any],
    *,
    sector_type: str,
    fs: str,
) -> list[dict[str, Any]]:
    try:
        limit = int(request.get("sector_rank_limit", SECTOR_RANK_LIMIT) or SECTOR_RANK_LIMIT)
    except (TypeError, ValueError):
        limit = SECTOR_RANK_LIMIT
    limit = max(1, min(limit, 100))
    params = {
        "pn": "1",
        "pz": str(limit),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": fs,
        "fields": SECTOR_RANK_FIELDS,
    }
    request_url = f"{_compiled.EASTMONEY_CLIST_URL}?{urlencode(params)}"
    req = Request(
        request_url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        method="GET",
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = [item for item in safe_list(safe_dict(payload.get("data")).get("diff")) if isinstance(item, dict)]
            normalized = normalize_sector_rankings(rows, default_sector_type=sector_type)
            for row in normalized:
                row["sector_type"] = sector_type
                row["source"] = "eastmoney_sector_rank"
            return normalized
        except Exception as exc:
            last_error = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(
        f"sector_rankings_fetch_failed: {sector_type}: {clean_text(last_error) or 'unknown'}"
    ) from last_error


def default_sector_rankings_fetcher(request: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for sector_type, fs in (
        ("industry", SECTOR_RANK_INDUSTRY_GROUP),
        ("concept", SECTOR_RANK_CONCEPT_GROUP),
    ):
        try:
            rows.extend(
                _fetch_eastmoney_sector_rank_group(
                    request,
                    sector_type=sector_type,
                    fs=fs,
                )
            )
        except Exception as exc:
            errors.append(f"{sector_type}: {clean_text(exc) or exc.__class__.__name__}")
    if rows:
        return rows
    for fallback_name, fallback_fetcher in (
        ("akshare", default_akshare_sector_rankings_fetcher),
        ("sina", default_sina_sector_rankings_fetcher),
    ):
        try:
            fallback_rows = fallback_fetcher(request)
            if fallback_rows:
                return fallback_rows
            errors.append(f"{fallback_name}: returned no rows")
        except Exception as fallback_exc:
            errors.append(f"{fallback_name}: {clean_text(fallback_exc) or fallback_exc.__class__.__name__}")
    if errors:
        raise RuntimeError(f"sector_rankings_fetch_failed: {'; '.join(errors)}")
    return rows


def merge_discovery_candidate_inputs(
    manual_candidates: list[dict[str, Any]],
    auto_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [candidate for candidate in (manual_candidates + auto_candidates) if isinstance(candidate, dict)]


def midday_action_for_status(status: str) -> str:
    normalized = clean_text(status).lower()
    if normalized == "blocked":
        return "不执行"
    if normalized == "qualified":
        return "可执行"
    return "继续观察"


def build_midday_action_summary(diagnostic_scorecard: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in diagnostic_scorecard:
        if not isinstance(item, dict):
            continue
        summary.append(
            {
                "ticker": clean_text(item.get("ticker")),
                "name": clean_text(item.get("name")) or clean_text(item.get("ticker")),
                "status": clean_text(item.get("midday_status")),
                "action": midday_action_for_status(clean_text(item.get("midday_status"))),
                "score": item.get("score"),
                "keep_threshold_gap": item.get("keep_threshold_gap"),
            }
        )
    return summary


def build_midday_action_summary_from_top_picks(top_picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in top_picks[:MAX_REPORTED_TOP_PICKS]:
        if not isinstance(item, dict):
            continue
        summary.append(
            {
                "ticker": clean_text(item.get("ticker")),
                "name": clean_text(item.get("name")) or clean_text(item.get("ticker")),
                "status": "qualified",
                "action": "可执行",
                "score": item.get("score"),
                "keep_threshold_gap": None,
            }
        )
    return summary


def build_midday_action_summary_from_result(enriched: dict[str, Any]) -> list[dict[str, Any]]:
    top_picks = enriched.get("top_picks")
    if isinstance(top_picks, list) and top_picks:
        return build_midday_action_summary_from_top_picks(top_picks)
    diagnostic_scorecard = enriched.get("diagnostic_scorecard")
    if isinstance(diagnostic_scorecard, list) and diagnostic_scorecard:
        return build_midday_action_summary(diagnostic_scorecard)
    return []


def build_technical_factor_summary(candidate: dict[str, Any]) -> str:
    snapshot = candidate.get("price_snapshot") if isinstance(candidate.get("price_snapshot"), dict) else {}
    trend = candidate.get("trend_template") if isinstance(candidate.get("trend_template"), dict) else {}
    if snapshot:
        close = snapshot.get("close")
        ma20 = snapshot.get("ma20")
        ma50 = snapshot.get("ma50")
        ma150 = snapshot.get("ma150")
        ma200 = snapshot.get("ma200")
        rsi14 = snapshot.get("rsi14")
        rs90 = snapshot.get("rs90")
        structure = "均线结构偏弱"
        if all(value not in (None, "") for value in (close, ma20, ma50, ma150, ma200)):
            if close > ma20 > ma50 > ma150 > ma200:
                structure = "均线多头结构仍成立"
            elif close > ma20 and close > ma50:
                structure = "短中期均线仍偏强，但长周期确认一般"
        trend_state = "趋势未确认"
        if trend.get("trend_pass") is True:
            trend_state = f"趋势模板通过（{trend.get('passed_count', 0)}项）"
        rsi_text = f"RSI 处在 {rsi14} 附近，未见极端失真" if rsi14 not in (None, "") else "RSI 证据不足"
        rs_text = f"相对强度 RS90 仍有支撑（{rs90}）" if rs90 not in (None, "") else "相对强度证据不足"
        return f"{structure}，{trend_state}；{rsi_text}；{rs_text}。"
    return "技术形态证据不足，当前无法完整复核均线、动能与波动结构。"


def build_event_factor_summary(candidate: dict[str, Any]) -> str:
    structured = candidate.get("structured_catalyst_snapshot") if isinstance(candidate.get("structured_catalyst_snapshot"), dict) else {}
    events = structured.get("earnings_events") if isinstance(structured.get("earnings_events"), list) else []
    if events:
        first = events[0]
        return f"关键事件窗口内有催化，最近一项是 {clean_text(first.get('date'))} 的 {clean_text(first.get('event_type'))}。"
    scheduled = clean_text(candidate.get("scheduled_earnings_date"))
    if scheduled:
        return f"已知关键事件日期为 {scheduled}，需要围绕事件前后确认结构是否延续。"
    if structured.get("structured_catalyst_within_window") is False:
        return "当前没有落在窗口内的关键结构化事件，事件驱动支持偏弱。"
    return "关键事件证据不足。"


def build_likely_next_summary(candidate: dict[str, Any], action: str) -> str:
    if action == "可执行":
        return "如果量能和趋势继续共振，后续更可能走确认后延续，而不是简单冲高回落。"
    if action == "继续观察":
        return "更可能先进入确认/回踩二选一阶段，关键看趋势和事件是否能把分数推回执行区间。"
    failures = candidate.get("hard_filter_failures") if isinstance(candidate.get("hard_filter_failures"), list) else []
    if failures:
        return "在当前硬伤修复前，更可能继续维持观察或剔除状态。"
    return "后续方向仍不清晰，优先等待更多证据。"


def build_logic_factor_summary(candidate: dict[str, Any], action: str) -> str:
    failures = candidate.get("hard_filter_failures") if isinstance(candidate.get("hard_filter_failures"), list) else []
    score = candidate.get("score")
    gap = candidate.get("keep_threshold_gap")
    if action == "可执行":
        return f"当前结构、事件与分数共同支持执行，综合评分 {score} 已进入可执行区间。"
    if action == "继续观察":
        return f"当前没有硬伤，但综合评分 {score} 距 keep line 仍差 {gap}，更适合继续观察等待确认。"
    if failures:
        return f"当前不执行，核心原因是 {', '.join(failures)}。"
    return "当前不执行，复核证据不足以支持出手。"


def _format_level(value: Any) -> str:
    number = to_float(value)
    if number <= 0:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return f"{number:g}"


def build_price_level_summary(candidate: dict[str, Any]) -> str:
    snapshot = candidate.get("price_snapshot") if isinstance(candidate.get("price_snapshot"), dict) else {}
    close = to_float(snapshot.get("close") if snapshot else candidate.get("price"))
    if close <= 0:
        return ""
    ma20 = to_float(snapshot.get("ma20"))
    ma50 = to_float(snapshot.get("ma50"))
    high52 = to_float(snapshot.get("high52"))

    parts = [f"关键价位：收盘 {_format_level(close)}"]
    supports = []
    if ma20 > 0:
        supports.append(f"MA20 {_format_level(ma20)}")
    if ma50 > 0 and (not ma20 or abs(ma50 - ma20) / max(ma20, ma50) >= 0.03):
        supports.append(f"MA50 {_format_level(ma50)}")
    if supports:
        parts.append(f"支撑 {' / '.join(supports)}")
    if high52 > 0 and high52 >= close:
        parts.append(f"压力 {_format_level(high52)}")
    invalidation = ma20 if ma20 > 0 else ma50
    if invalidation > 0:
        parts.append(f"放弃线 {_format_level(invalidation)}")
    return "，".join(parts)


def build_trade_layer_summary(candidate: dict[str, Any], action: str) -> str:
    trade_card = candidate.get("trade_card") if isinstance(candidate.get("trade_card"), dict) else {}
    price_paths = candidate.get("price_paths") if isinstance(candidate.get("price_paths"), dict) else {}
    risk_reward_ratio = candidate.get("risk_reward_ratio")
    base_upside_pct = candidate.get("base_upside_pct")
    risk_pct = candidate.get("risk_pct")

    parts: list[str] = []
    price_level_summary = build_price_level_summary(candidate)
    if price_level_summary:
        parts.append(price_level_summary)
    if action in {"可执行", "继续观察"}:
        if clean_text(trade_card.get("watch_action")):
            parts.append(f"观察/执行参考：{clean_text(trade_card.get('watch_action'))}")
        if clean_text(trade_card.get("invalidation")):
            parts.append(f"失效条件：{clean_text(trade_card.get('invalidation'))}")
        if isinstance(price_paths.get("base"), list) and price_paths.get("base"):
            parts.append(f"基准路径：{price_paths.get('base')}")
        if risk_reward_ratio not in (None, ""):
            parts.append(f"风险收益比 `{risk_reward_ratio}`")
        if base_upside_pct not in (None, ""):
            parts.append(f"基础上行空间 `{base_upside_pct}%`")
        if risk_pct not in (None, ""):
            parts.append(f"预估风险 `{risk_pct}%`")
    if action == "不执行" and price_level_summary:
        parts.append("当前仍不执行，先等结构或事件硬伤修复。")
    if not parts and action == "不执行":
        return "当前不进入交易层细化，先解决结构或事件上的硬伤再谈执行。"
    return "；".join(parts) if parts else "交易层证据不足。"


def build_next_watch_items(candidate: dict[str, Any], action: str) -> list[str]:
    items: list[str] = []
    trade_card = candidate.get("trade_card") if isinstance(candidate.get("trade_card"), dict) else {}
    if action == "继续观察":
        if clean_text(trade_card.get("watch_action")):
            items.append(clean_text(trade_card.get("watch_action")))
        if clean_text(trade_card.get("invalidation")):
            items.append(f"若出现 `{clean_text(trade_card.get('invalidation'))}` 则观察逻辑失效。")
        if not items:
            items.append("等待下一次趋势确认或分数修复后再评估。")
    elif action == "可执行":
        if clean_text(trade_card.get("watch_action")):
            items.append(clean_text(trade_card.get("watch_action")))
        if clean_text(trade_card.get("invalidation")):
            items.append(f"执行后重点盯住失效条件：`{clean_text(trade_card.get('invalidation'))}`。")
    else:
        items.append("除非结构和价格条件明显改善，否则不进入执行清单。")
    return items[:MAX_REPORTED_WATCH_ITEMS]


INLINE_A_SHARE_TICKER_RE = re.compile(r"`(?P<ticker>\d{6}(?:\.(?:SZ|SS|SH))?)`")


def _looks_like_a_share_ticker(value: str) -> bool:
    return bool(re.fullmatch(r"\d{6}(?:\.(?:SZ|SS|SH))?", clean_text(value).upper()))


def _add_ticker_name_aliases(lookup: dict[str, str], ticker: str, name: str) -> None:
    normalized_ticker = clean_text(ticker).upper()
    normalized_name = clean_text(name)
    if not normalized_ticker or not normalized_name:
        return
    if normalized_name == normalized_ticker or not _looks_like_a_share_ticker(normalized_ticker):
        return
    lookup.setdefault(normalized_ticker, normalized_name)
    bare_code = normalized_ticker[:6]
    if _looks_like_a_share_ticker(bare_code):
        lookup.setdefault(bare_code, normalized_name)


def build_ticker_name_lookup(value: Any) -> dict[str, str]:
    lookup: dict[str, str] = {}

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            name = (
                clean_text(item.get("name"))
                or clean_text(item.get("resolved_name"))
                or clean_text(item.get("stock_name"))
                or clean_text(item.get("symbol_name"))
            )
            ticker = clean_text(item.get("ticker")) or clean_text(item.get("symbol"))
            if not ticker and _looks_like_a_share_ticker(clean_text(item.get("code"))):
                ticker = clean_text(item.get("code"))
            _add_ticker_name_aliases(lookup, ticker, name)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return lookup


def annotate_ticker_names_in_markdown(markdown: str, source: Any) -> str:
    lookup = build_ticker_name_lookup(source)
    if not markdown or not lookup:
        return markdown

    annotated_lines: list[str] = []
    for line in markdown.splitlines():
        def replace(match: re.Match[str]) -> str:
            ticker = clean_text(match.group("ticker")).upper()
            name = lookup.get(ticker) or lookup.get(ticker[:6])
            if not name or name in line:
                return match.group(0)
            return f"`{match.group('ticker')}` {name}"

        annotated_lines.append(INLINE_A_SHARE_TICKER_RE.sub(replace, line))
    return "\n".join(annotated_lines)


def build_decision_factor_entry(candidate: dict[str, Any], action: str) -> dict[str, Any]:
    status = clean_text(candidate.get("midday_status"))
    if not status:
        if action == "可执行":
            status = "qualified"
        elif action == "继续观察":
            status = "near_miss"
        else:
            status = "blocked"
    return {
        "ticker": clean_text(candidate.get("ticker")),
        "name": clean_text(candidate.get("name")) or clean_text(candidate.get("ticker")),
        "action": action,
        "status": status,
        "score": candidate.get("score"),
        "keep_threshold_gap": candidate.get("keep_threshold_gap"),
        "technical_summary": build_technical_factor_summary(candidate),
        "event_summary": build_event_factor_summary(candidate),
        "likely_next_summary": build_likely_next_summary(candidate, action),
        "logic_summary": build_logic_factor_summary(candidate, action),
        "trade_layer_summary": build_trade_layer_summary(candidate, action),
        "next_watch_items": build_next_watch_items(candidate, action),
        "hard_filter_failures": deepcopy(candidate.get("hard_filter_failures", [])),
        "tier_tags": deepcopy(candidate.get("tier_tags", [])),
        "fallback_support_reason": clean_text(candidate.get("fallback_support_reason")),
        "fallback_snapshot_only": bool(candidate.get("fallback_snapshot_only")),
        "fallback_cache_only": bool(candidate.get("fallback_cache_only")),
        "bars_source": clean_text(candidate.get("bars_source")),
        "execution_state": clean_text(candidate.get("execution_state")) or infer_execution_state(candidate),
    }


def build_decision_factors_from_result(enriched: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    factors = {"qualified": [], "near_miss": [], "blocked": []}
    for item in enriched.get("top_picks", []) if isinstance(enriched.get("top_picks"), list) else []:
        if isinstance(item, dict):
            factors["qualified"].append(build_decision_factor_entry(item, "可执行"))
    near_miss_candidates = (
        enriched.get("near_miss_candidates", [])
        if isinstance(enriched.get("near_miss_candidates"), list)
        else []
    )
    diagnostic_scorecard = (
        enriched.get("diagnostic_scorecard", [])
        if isinstance(enriched.get("diagnostic_scorecard"), list)
        else []
    )
    candidate_lookup: dict[str, dict[str, Any]] = {}
    for item in near_miss_candidates + diagnostic_scorecard:
        if not isinstance(item, dict):
            continue
        ticker = clean_text(item.get("ticker"))
        if ticker and ticker not in candidate_lookup:
            candidate_lookup[ticker] = deepcopy(item)

    near_miss_source: list[dict[str, Any]] = []
    seen_near_miss: set[str] = set()
    tier_output = enriched.get("tier_output", {}) if isinstance(enriched.get("tier_output"), dict) else {}
    rendered_t3 = tier_output.get("T3", []) if isinstance(tier_output.get("T3"), list) else []
    if rendered_t3:
        for row in rendered_t3:
            if not isinstance(row, dict):
                continue
            ticker = clean_text(row.get("ticker"))
            if not ticker or ticker in seen_near_miss:
                continue
            base = deepcopy(candidate_lookup.get(ticker) or row)
            base.setdefault("ticker", ticker)
            if row.get("name") not in (None, ""):
                base["name"] = row.get("name")
            if row.get("score") not in (None, "") and base.get("score") in (None, ""):
                base["score"] = row.get("score")
            if row.get("track_name") not in (None, ""):
                base["track_name"] = row.get("track_name")
            if isinstance(row.get("tier_tags"), list):
                merged_tags = list(base.get("tier_tags", []))
                for tag in row.get("tier_tags", []):
                    if tag not in merged_tags:
                        merged_tags.append(tag)
                base["tier_tags"] = merged_tags
            if clean_text(row.get("fallback_support_reason")):
                base["fallback_support_reason"] = clean_text(row.get("fallback_support_reason"))
            if row.get("fallback_snapshot_only"):
                base["fallback_snapshot_only"] = True
            if row.get("fallback_cache_only"):
                base["fallback_cache_only"] = True
            if clean_text(row.get("bars_source")):
                base["bars_source"] = clean_text(row.get("bars_source"))
            base["midday_status"] = "near_miss"
            near_miss_source.append(base)
            seen_near_miss.add(ticker)
    else:
        for item in near_miss_candidates:
            if not isinstance(item, dict):
                continue
            ticker = clean_text(item.get("ticker"))
            if ticker and ticker in seen_near_miss:
                continue
            near_miss_source.append(item)
            if ticker:
                seen_near_miss.add(ticker)

    for item in near_miss_source:
        if isinstance(item, dict):
            factors["near_miss"].append(build_decision_factor_entry(item, "继续观察"))
    for item in enriched.get("diagnostic_scorecard", []) if isinstance(enriched.get("diagnostic_scorecard"), list) else []:
        if not isinstance(item, dict):
            continue
        if clean_text(item.get("midday_status")) == "blocked":
            factors["blocked"].append(build_decision_factor_entry(item, "不执行"))
    factors["qualified"] = factors["qualified"][:MAX_REPORTED_TOP_PICKS]
    factors["near_miss"] = factors["near_miss"][:MAX_REPORTED_NEAR_MISS]
    factors["blocked"] = factors["blocked"][:MAX_REPORTED_BLOCKED]
    return factors


def build_upgrade_trigger(card: dict[str, Any], keep_threshold: float | int | None) -> str:
    action = clean_text(card.get("action"))
    score = card.get("score")
    technical_summary = clean_text(card.get("technical_summary"))
    event_summary = clean_text(card.get("event_summary"))
    driver = "技术与事件验证继续强化"
    if "均线多头结构" in technical_summary or "趋势模板通过" in technical_summary:
        driver = "趋势结构和量价验证继续保持"
    elif event_summary and "证据不足" not in event_summary:
        driver = "关键事件催化继续强化"
    if action == "继续观察" and score not in (None, "") and keep_threshold not in (None, ""):
        return f"若评分从 {score} 修复至 {keep_threshold}+，且{driver}，可升级到执行层。"
    if action == "不执行" and card.get("keep_threshold_gap") not in (None, ""):
        return "若当前硬伤消失，且分数重新回到 keep line 之上，才重新进入观察名单。"
    return "若技术、事件和资金验证继续改善，可考虑上调优先级。"


def build_downgrade_trigger(card: dict[str, Any]) -> str:
    action = clean_text(card.get("action"))
    failures = card.get("hard_filter_failures") if isinstance(card.get("hard_filter_failures"), list) else []
    if failures:
        return f"若 `{', '.join(failures)}` 继续存在或再次出现，维持当前降级结论。"
    technical_summary = clean_text(card.get("technical_summary"))
    if "均线多头结构" in technical_summary or "短中期均线仍偏强" in technical_summary:
        return "若价格重新跌回关键均线下方或趋势模板转弱，应立即降级。"
    if action == "可执行":
        return "若技术承接转弱、事件验证回落或链条共振消失，应从执行层降回观察。"
    if action == "继续观察":
        return "若技术结构转弱、事件兑现不及预期或链条共振消失，应降级为不执行。"
    return "若当前硬伤继续恶化，维持不执行。"


def build_event_risk_trigger(card: dict[str, Any]) -> str:
    key_evidence = card.get("key_evidence") if isinstance(card.get("key_evidence"), list) else []
    for item in key_evidence:
        text = clean_text(item)
        if not text:
            continue
        matches = re.findall(r"(\d{3,})\s*万元", text)
        if matches:
            return f"若实际净利润低于预告下限 {matches[0]} 万元，应警惕事件预期落空。"
    event_risk = clean_text(card.get("expectation_risk_summary"))
    if event_risk:
        return event_risk
    event_summary = clean_text(card.get("event_summary"))
    if "证据不足" in event_summary:
        return "若关键事件仍未进入窗口或验证继续缺失，不进入执行判断。"
    return ""


def build_geopolitics_bias_summary(chain_name: str, overlay: dict[str, Any] | None) -> str:
    regime = clean_text((overlay or {}).get("regime_label"))
    if regime not in GEOPOLITICS_REGIME_LABELS:
        return ""
    bias_kind = classify_geopolitics_chain_bias(chain_name, overlay)
    if not bias_kind:
        return ""
    if regime == "escalation":
        return "链条偏置：地缘升级下的受益链条" if bias_kind == "beneficiary" else "链条偏置：地缘升级下的承压链条"
    if regime == "de_escalation":
        return "链条偏置：地缘缓和下的受益链条" if bias_kind == "beneficiary" else "链条偏置：地缘缓和下的承压链条"
    return "链条偏置：whipsaw 阶段优先看确认，不看情绪先手"


def build_geopolitics_execution_constraint(action: str, overlay: dict[str, Any] | None) -> str:
    regime = clean_text((overlay or {}).get("regime_label"))
    if regime == "escalation":
        return "执行约束：轻仓，不追高，隔夜谨慎"
    if regime == "de_escalation":
        return "执行约束：优先跟随确认后的风险偏好修复，不把地缘缓和单独当成追价理由"
    if regime == "whipsaw":
        return "执行约束：headline reversal risk 高，优先等确认，不做激进隔夜博弈"
    return ""


def build_decision_flow_card(
    factor: dict[str, Any],
    *,
    keep_threshold: float | None,
    event_card: dict[str, Any] | None,
    chain_entry: dict[str, Any] | None,
    geopolitics_overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    card = deepcopy(factor)
    tier_tags = set(card.get("tier_tags", [])) if isinstance(card.get("tier_tags"), list) else set()
    bars_source = clean_text(card.get("bars_source"))
    event_context = event_card if isinstance(event_card, dict) else {}
    chain_context = chain_entry if isinstance(chain_entry, dict) else {}
    action = clean_text(card.get("action"))
    is_fallback = "low_confidence_fallback" in tier_tags
    action_label = action
    if is_fallback and action == "继续观察":
        action_label = "继续观察（low-confidence fallback）"
    ticker = clean_text(card.get("ticker")) or "unknown"
    score = card.get("score")
    gap = card.get("keep_threshold_gap")
    chain_name = clean_text(event_context.get("chain_name")) or clean_text(chain_context.get("chain_name")) or "unknown"
    chain_role = clean_text(event_context.get("chain_role")) or "unknown"
    fallback_bucket = {"可执行": "稳健核心", "继续观察": "继续观察", "不执行": "不执行"}.get(action, "继续观察")
    trading_profile_bucket = clean_text(event_context.get("trading_profile_bucket")) or fallback_bucket
    logic_summary = clean_text(card.get("logic_summary")) or clean_text(event_context.get("trading_profile_judgment")) or f"当前动作 {action}"
    conclusion = logic_summary.rstrip("。")
    if score not in (None, "") and keep_threshold not in (None, "") and gap not in (None, ""):
        conclusion = f"{conclusion}。评分 {score}，执行门槛 {keep_threshold}，差距 {gap}。"
    elif score not in (None, "") and gap not in (None, ""):
        conclusion = f"{conclusion}。评分 {score}，差距 {gap}。"
    technical_summary = clean_text(card.get("technical_summary")) or "技术形态证据不足。"
    event_summary = clean_text(card.get("event_summary")) or clean_text(event_context.get("expectation_basis_summary")) or "事件证据不足。"
    community_conviction = clean_text(event_context.get("community_conviction")) or "unknown"
    validation_label = clean_text((event_context.get("market_validation_summary") or {}).get("label")) or "unknown"
    event_bits = [event_summary, f"社区一致性: {community_conviction}", f"量价验证: {validation_label}"]
    chain_summary = "；".join(
        bit
        for bit in [
            f"链条: {chain_name}" if chain_name else "",
            f"角色: {chain_role}" if chain_role and chain_role != 'unknown' else "",
            f"交易属性: {trading_profile_bucket}" if trading_profile_bucket else "",
            clean_text(chain_context.get("chain_playbook")) or clean_text(event_context.get("chain_path_summary")) or "",
            build_geopolitics_bias_summary(chain_name, geopolitics_overlay),
        ]
        if bit
    ) or "链条共振证据不足。"
    operation_parts = [
        clean_text(event_context.get("trading_profile_usage")) or clean_text(card.get("trade_layer_summary")) or "先等更多确认。",
    ]
    execution_state = clean_text(card.get("execution_state")) or infer_execution_state(card)
    if execution_state == "stale_cache":
        operation_parts.append("数据状态：低置信度 fallback")
        operation_parts.append("数据路径：cache baseline only")
        fallback_reason = clean_text(card.get("fallback_support_reason"))
        if fallback_reason:
            operation_parts.append(f"保留原因：{fallback_reason}")
    elif execution_state == "fresh_cache":
        operation_parts.append("数据来源：Eastmoney cache")
    elif is_fallback:
        operation_parts.append("数据路径降级：local market snapshot only")
        fallback_reason = clean_text(card.get("fallback_support_reason"))
        if fallback_reason:
            operation_parts.append(f"保留原因：{fallback_reason}")
    elif bars_source == "eastmoney_cache":
        operation_parts.append("数据来源：Eastmoney cache")
    if card.get("cache_baseline_only"):
        operation_parts.append("数据状态：仍沿用缓存基线")
    elif clean_text(card.get("live_supplement_status")) == "updated":
        operation_parts.append("数据状态：已补实时更新")
    geopolitics_constraint = build_geopolitics_execution_constraint(action, geopolitics_overlay)
    if geopolitics_constraint:
        operation_parts.append(geopolitics_constraint)
    next_watch_items = card.get("next_watch_items") if isinstance(card.get("next_watch_items"), list) else []
    if next_watch_items:
        operation_parts.append(clean_text(next_watch_items[0]))
    # --- Confirmation gate labels ---
    midday_status_val = clean_text(card.get("midday_status"))
    if midday_status_val == "pending_confirmation":
        operation_parts.append("盘中确认：需等待 11:00 后分时确认")
        operation_parts.append("确认条件：分时不出现 fade_from_high 或 weak_open_no_recovery")
        operation_parts.append("确认后操作：按原计划执行")
        operation_parts.append("未确认操作：降级为观察")
    # --- Review boost/penalty labels ---
    if "review_upgraded" in tier_tags:
        operation_parts.append("复盘加分：+5（前日错过机会）")
    elif "review_downgraded" in tier_tags:
        operation_parts.append("复盘减分：-5（前日过于激进）")
        operation_parts.append("强制确认门控：是")
    flow_card = {
        "ticker": ticker,
        "name": clean_text(card.get("name")) or ticker,
        "action": action,
        "action_label": action_label,
        "status": clean_text(card.get("status")) or clean_text(card.get("midday_status")),
        "score": score,
        "keep_threshold": keep_threshold,
        "gap": gap,
        "keep_threshold_gap": gap,
        "chain_name": chain_name,
        "chain_role": chain_role,
        "trading_profile_bucket": trading_profile_bucket,
        "trigger_overrides": None,
        "conclusion": conclusion,
        "watch_points": {
            "technical": technical_summary,
            "event": "；".join(event_bits),
            "chain": chain_summary,
        },
        "triggers": {
            "upgrade": build_upgrade_trigger(card, keep_threshold),
            "downgrade": build_downgrade_trigger(card),
        },
        "operation_reminder": " ".join(part for part in operation_parts if part),
    }
    event_risk = build_event_risk_trigger({**event_context, **card})
    if event_risk:
        flow_card["triggers"]["event_risk"] = event_risk

    # Direction layer labels
    direction_boost = card.get("direction_boost") if isinstance(card.get("direction_boost"), dict) else {}
    if direction_boost:
        d_total = direction_boost.get("total_delta", 0)
        d_label = clean_text(direction_boost.get("direction_key")) or "unknown"
        d_role = clean_text(direction_boost.get("direction_role")) or ""
        d_signal = clean_text(direction_boost.get("signal_strength")) or ""
        d_momentum = clean_text(direction_boost.get("momentum_signal")) or ""

        role_label = {"leader": "龙头", "high_beta": "高弹性"}.get(d_role, d_role)
        direction_notes: list[str] = []
        if d_total > 0:
            direction_notes.append(f"方向层加分：+{d_total}（{d_label} {role_label}）")
            direction_notes.append(f"方向信号强度：{d_signal}")
            original_score = round(float(flow_card.get("score") or 0) - d_total, 1)
            direction_notes.append(f"原始得分：{original_score} → 方向调整后：{flow_card.get('score')}")
        if "direction_promoted" in tier_tags:
            original_tier = clean_text(card.get("original_tier")) or "?"
            current_tier = clean_text(card.get("wrapper_tier")) or "?"
            direction_notes.append(f"方向层晋级：{original_tier} → {current_tier}（{d_label} {role_label}，信号={d_signal}）")
        if d_momentum:
            momentum_labels = {
                "confirmed": "confirmed（前日复盘确认）",
                "strengthening": "strengthening（前日方向强化）",
                "caution": "caution（前日方向过激，加分减半）",
                "fading": "fading（前日方向衰退）",
            }
            direction_notes.append(f"方向动量：{momentum_labels.get(d_momentum, d_momentum)}")
        if direction_notes:
            existing_notes = flow_card.get("direction_notes", [])
            flow_card["direction_notes"] = existing_notes + direction_notes

    return flow_card


def build_decision_flow(enriched: dict[str, Any]) -> list[dict[str, Any]]:
    decision_factors = enriched.get("decision_factors")
    if not isinstance(decision_factors, dict):
        decision_factors = build_decision_factors_from_result(enriched)
    keep_threshold = None
    filter_summary = enriched.get("filter_summary")
    if isinstance(filter_summary, dict) and filter_summary.get("keep_threshold") not in (None, ""):
        keep_threshold = float(filter_summary.get("keep_threshold"))
    cache_baseline_only = bool(filter_summary.get("cache_baseline_only")) if isinstance(filter_summary, dict) else False
    live_supplement_status = (
        clean_text(filter_summary.get("live_supplement_status"))
        if isinstance(filter_summary, dict)
        else ""
    )

    event_card_map = {
        clean_text(item.get("ticker")): item
        for item in enriched.get("event_cards", [])
        if isinstance(item, dict) and clean_text(item.get("ticker"))
    }
    chain_entry_map = {
        clean_text(item.get("chain_name")): item
        for item in enriched.get("chain_map_entries", [])
        if isinstance(item, dict) and clean_text(item.get("chain_name"))
    }
    request_obj = enriched.get("request")
    geopolitics_overlay = (
        request_obj.get("macro_geopolitics_overlay")
        if isinstance(request_obj, dict) and isinstance(request_obj.get("macro_geopolitics_overlay"), dict)
        else None
    )
    ordered: list[dict[str, Any]] = []
    section_order = ("qualified", "near_miss", "blocked")
    for key in section_order:
        rows = decision_factors.get(key, [])
        if not isinstance(rows, list):
            continue
        sorted_rows = sorted(
            [item for item in rows if isinstance(item, dict)],
            key=lambda item: float(item.get("score") or 0.0),
            reverse=(key == "near_miss"),
        )
        for item in sorted_rows:
            item = dict(item)
            item["cache_baseline_only"] = cache_baseline_only
            item["live_supplement_status"] = live_supplement_status
            event_card = event_card_map.get(clean_text(item.get("ticker")))
            chain_entry = None
            if isinstance(event_card, dict):
                chain_entry = chain_entry_map.get(clean_text(event_card.get("chain_name")))
            ordered.append(
                build_decision_flow_card(
                    item,
                    keep_threshold=keep_threshold,
                    event_card=event_card,
                    chain_entry=chain_entry,
                    geopolitics_overlay=geopolitics_overlay,
                )
            )
    return ordered


def build_geopolitics_candidate_summary_lines(
    candidate: dict[str, Any] | None,
    overlay: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(candidate, dict):
        return []

    regime = clean_text(candidate.get("candidate_regime")) or "insufficient_signal"
    confidence = clean_text(candidate.get("confidence")) or "low"
    signal_alignment = clean_text(candidate.get("signal_alignment")) or "mixed"
    status = clean_text(candidate.get("status")) or "candidate_only"
    status_text = {
        "candidate_only": "候选判断，尚未写入正式 overlay",
        "accepted_as_overlay": "候选已被采纳为正式 overlay",
        "conflicts_with_overlay": "候选与正式 overlay 不一致",
        "insufficient_signal": "当前多源信号不足以形成稳定候选",
    }.get(status, "候选判断，尚未写入正式 overlay")

    lines = [
        f"- 地缘候选判断：`{regime}`（{confidence}）",
        f"- 信号对齐：{signal_alignment}",
        f"- 状态：{status_text}",
    ]
    overlay_regime = clean_text((overlay or {}).get("regime_label"))
    if overlay_regime:
        lines.append(f"- 正式 overlay：`{overlay_regime}`")
    return lines


def build_decision_flow_markdown(
    decision_flow: list[dict[str, Any]],
    geopolitics_overlay: dict[str, Any] | None = None,
    geopolitics_candidate: dict[str, Any] | None = None,
) -> list[str]:
    lines = ["", "## 决策流", ""]
    regime = clean_text((geopolitics_overlay or {}).get("regime_label"))
    if regime in GEOPOLITICS_REGIME_LABELS:
        lines.append(f"- 地缘 regime: `{regime}`")
        confidence = clean_text((geopolitics_overlay or {}).get("confidence"))
        headline_risk = clean_text((geopolitics_overlay or {}).get("headline_risk"))
        meta_bits: list[str] = []
        if confidence:
            meta_bits.append(f"confidence=`{confidence}`")
        if headline_risk:
            meta_bits.append(f"headline_risk=`{headline_risk}`")
        if meta_bits:
            lines.append(f"- {' | '.join(meta_bits)}")
        lines.append("")
    candidate_lines = build_geopolitics_candidate_summary_lines(
        geopolitics_candidate,
        geopolitics_overlay,
    )
    if candidate_lines:
        lines.extend(candidate_lines)
        lines.append("")
    for item in decision_flow:
        lines.append(
            f"### {item.get('ticker')} | {item.get('action_label', item.get('action'))} | {item.get('score')}分 | {item.get('trading_profile_bucket')}"
        )
        lines.append("")
        lines.append(f"- 结论：{item.get('conclusion')}")
        lines.append("- 盘中观察点：")
        watch_points = item.get("watch_points") if isinstance(item.get("watch_points"), dict) else {}
        lines.append(f"  - 技术：{watch_points.get('technical', '技术形态证据不足。')}")
        lines.append(f"  - 事件：{watch_points.get('event', '事件证据不足。')}")
        lines.append(f"  - 链条：{watch_points.get('chain', '链条共振证据不足。')}")
        lines.append("- 触发条件：")
        triggers = item.get("triggers") if isinstance(item.get("triggers"), dict) else {}
        lines.append(f"  - ↑ upgrade：{triggers.get('upgrade', '等待更多确认。')}")
        lines.append(f"  - ↓ downgrade：{triggers.get('downgrade', '若验证转弱则降级。')}")
        if clean_text(triggers.get("event_risk")):
            lines.append(f"  - ⚡ event risk：{triggers.get('event_risk')}")
        lines.append(f"- 操作提醒：{item.get('operation_reminder')}")
        lines.append("")
    return lines


def build_weekend_market_candidate_markdown(
    weekend_candidate: dict[str, Any] | None,
    direction_reference_map: list[dict[str, Any]] | None,
) -> list[str]:
    if not isinstance(weekend_candidate, dict) or weekend_candidate.get("status") == "insufficient_signal":
        return []

    logic_labels = {"high": "高", "medium": "中", "low": "低"}
    rank_labels = {1: "第一", 2: "第二", 3: "第三"}
    lines: list[str] = ["", "## 周末主线候选", ""]
    for item in weekend_candidate.get("candidate_topics", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"- `{clean_text(item.get('topic_label') or item.get('topic_name'))}` / `{clean_text(item.get('signal_strength'))}`")
        why_it_matters = clean_text(item.get("why_it_matters"))
        if why_it_matters:
            lines.append(f"  - 为什么重要: {why_it_matters}")
        monday_watch = clean_text(item.get("monday_watch"))
        if monday_watch:
            lines.append(f"  - 周一先看: {monday_watch}")

        ranking_logic = item.get("ranking_logic") if isinstance(item.get("ranking_logic"), dict) else {}
        ranking_reason = clean_text(item.get("ranking_reason"))
        key_sources = item.get("key_sources") if isinstance(item.get("key_sources"), list) else []
        priority_rank_raw = item.get("priority_rank")
        priority_rank = int(priority_rank_raw) if isinstance(priority_rank_raw, int) or (isinstance(priority_rank_raw, str) and priority_rank_raw.isdigit()) else None

        if ranking_logic:
            lines.append("")
            lines.append("### 排序逻辑")
            lines.append(f"- 种子共振：{logic_labels.get(clean_text(ranking_logic.get('seed_alignment')), clean_text(ranking_logic.get('seed_alignment')))}")
            lines.append(f"- 扩展确认：{logic_labels.get(clean_text(ranking_logic.get('expansion_confirmation')), clean_text(ranking_logic.get('expansion_confirmation')))}")
            lines.append(f"- Reddit 验证：{logic_labels.get(clean_text(ranking_logic.get('reddit_confirmation')), clean_text(ranking_logic.get('reddit_confirmation')))}")
            lines.append(f"- 分歧 / 噪音：{logic_labels.get(clean_text(ranking_logic.get('noise_or_disagreement')), clean_text(ranking_logic.get('noise_or_disagreement')))}")

        if ranking_reason:
            lines.append("")
            rank_text = rank_labels.get(priority_rank, f"第{priority_rank}" if priority_rank else "当前")
            lines.append(f"### 为什么排{rank_text}")
            lines.append(ranking_reason)

        if key_sources:
            lines.append("")
            lines.append("### 最关键 source")
            for row in key_sources[:3]:
                if not isinstance(row, dict):
                    continue
                lines.append(f"- `{clean_text(row.get('source_name'))}`")
                url = clean_text(row.get("url"))
                if url:
                    lines.append(f"  - 链接：{url}")
                summary = clean_text(row.get("summary"))
                if summary:
                    lines.append(f"  - 摘要：{summary}")

    directions = weekend_candidate.get("priority_watch_directions")
    if isinstance(directions, list) and directions:
        lines.extend(["", "## 周一优先盯的方向", ""])
        for direction in directions:
            text = clean_text(direction)
            if text:
                lines.append(f"- {text}")

    if isinstance(direction_reference_map, list) and direction_reference_map:
        lines.extend(["", "## 方向参考映射", ""])
        for item in direction_reference_map:
            if not isinstance(item, dict):
                continue
            lines.append(f"- `{clean_text(item.get('direction_label') or item.get('direction_key'))}`")
            leaders = [
                " ".join(part for part in [clean_text(row.get("name")), clean_text(row.get("ticker"))] if part)
                for row in item.get("leaders", [])
                if isinstance(row, dict)
            ]
            high_beta_names = [
                " ".join(part for part in [clean_text(row.get("name")), clean_text(row.get("ticker"))] if part)
                for row in item.get("high_beta_names", [])
                if isinstance(row, dict)
            ]
            lines.append(f"  - 龙头股: {', '.join(leaders) or 'none'}")
            lines.append(f"  - 弹性股: {', '.join(high_beta_names) or 'none'}")
            mapping_note = clean_text(item.get("mapping_note"))
            if mapping_note:
                lines.append(f"  - 说明: {mapping_note}")

    # Direction execution integration summary
    if direction_reference_map:
        lines.append("")
        lines.append("## 方向层执行整合")
        lines.append("")
        has_resolved = any(
            any(clean_text(item.get("ticker")) for item in entry.get("leaders", []))
            or any(clean_text(item.get("ticker")) for item in entry.get("high_beta_names", []))
            for entry in direction_reference_map
        )
        if has_resolved:
            lines.append("方向层已解析代码，可参与执行层评分、晋级和门控。")
        else:
            lines.append("方向层代码未解析，仅作参考。")
        lines.append("")

    return lines


def prepare_request_with_candidate_snapshots(request: dict[str, Any], *, bars_fetcher: BarsFetcher) -> dict[str, Any]:
    prepared = deepcopy(request)
    local_stock_pool = normalize_local_stock_pool_from_request(prepared)
    if local_stock_pool:
        prepared["local_stock_pool"] = local_stock_pool
        prepared["candidate_tickers"] = merge_local_pool_candidate_tickers(
            prepared.get("candidate_tickers", []),
            local_stock_pool,
        )
    local_daily_bars_source = normalize_local_daily_bars_source(prepared)
    if local_daily_bars_source:
        prepared["local_daily_bars_source"] = local_daily_bars_source
    pool_by_ticker = local_stock_pool_lookup(prepared.get("local_stock_pool", {}))
    candidate_tickers = [
        normalize_a_share_ticker(item) or clean_text(item)
        for item in prepared.get("candidate_tickers", [])
        if clean_text(item)
    ]
    prepared["candidate_tickers"] = [item for item in candidate_tickers if item]
    if not candidate_tickers or prepared.get("universe_candidates"):
        return prepared

    history_by_ticker = dict(prepared.get("history_by_ticker") or {})
    analysis_date = parse_date(prepared.get("analysis_time")) or parse_date(prepared.get("target_date")) or now_utc().date()
    start_date = (analysis_date - timedelta(days=420)).isoformat()
    end_date = analysis_date.isoformat()

    universe_candidates: list[dict[str, Any]] = []
    for raw_ticker in candidate_tickers:
        normalized_ticker = build_manual_candidate({"ticker": raw_ticker, "name": raw_ticker}).get("ticker") or clean_text(raw_ticker).upper()
        rows = history_by_ticker.get(normalized_ticker)
        rows_source = ""
        if not rows and local_daily_bars_source:
            rows = fetch_local_daily_rows(local_daily_bars_source, normalized_ticker, start_date, end_date)
            if rows:
                rows_source = clean_text(local_daily_bars_source.get("kind")) or "local_daily_bars"
        if not rows:
            try:
                rows = bars_fetcher(normalized_ticker, start_date, end_date)
            except Exception:
                rows = []
        if rows:
            history_by_ticker[normalized_ticker] = rows
            candidate_snapshot = build_candidate_snapshot_from_rows(normalized_ticker, rows)
        else:
            candidate_snapshot = {"ticker": normalized_ticker, "name": normalized_ticker}
        pool_row = pool_by_ticker.get(normalized_ticker, {})
        if pool_row:
            candidate_snapshot["name"] = clean_text(pool_row.get("name")) or candidate_snapshot.get("name") or normalized_ticker
            candidate_snapshot["stock_pool_groups"] = list(pool_row.get("groups") or [])
            candidate_snapshot["stock_pool_tags"] = list(pool_row.get("tags") or [])
            candidate_snapshot["stock_pool_strategy_tags"] = list(pool_row.get("strategy_tags") or [])
            if clean_text(pool_row.get("notes")):
                candidate_snapshot["stock_pool_notes"] = clean_text(pool_row.get("notes"))
            if isinstance(pool_row.get("plan_snapshot"), dict):
                candidate_snapshot["plan_snapshot"] = deepcopy(pool_row["plan_snapshot"])
            candidate_snapshot["candidate_source"] = "local_stock_pool"
        if rows_source:
            candidate_snapshot["bars_source"] = rows_source
            if isinstance(candidate_snapshot.get("technical_snapshot"), dict):
                candidate_snapshot["technical_snapshot"]["source"] = rows_source
        universe_candidates.append(candidate_snapshot)

    prepared["history_by_ticker"] = history_by_ticker
    prepared["universe_candidates"] = universe_candidates
    return prepared


def enrich_event_cards_with_chain_context(event_cards: list[dict[str, Any]], discovery_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(discovery_context, dict):
        return event_cards
    chain_map = discovery_context.get("chain_map") if isinstance(discovery_context.get("chain_map"), list) else []
    if not chain_map:
        return event_cards
    chain_lookup = {
        clean_text(item.get("chain_name")): item
        for item in chain_map
        if isinstance(item, dict) and clean_text(item.get("chain_name"))
    }
    membership_lookup: dict[str, str] = {}
    for item in chain_map:
        if not isinstance(item, dict):
            continue
        chain_name = clean_text(item.get("chain_name"))
        for name in unique_strings(
            list(item.get("all_candidates") or [])
            + list(item.get("leaders") or [])
            + list(item.get("tier_1") or [])
            + list(item.get("tier_2") or [])
        ):
            membership_lookup.setdefault(name, chain_name)
    enriched_cards: list[dict[str, Any]] = []
    for card in event_cards:
        if not isinstance(card, dict):
            continue
        enriched_card = deepcopy(card)
        current_chain_name = clean_text(card.get("chain_name"))
        card_name = clean_text(card.get("name")) or clean_text(card.get("ticker"))
        current_context = chain_lookup.get(current_chain_name)
        if isinstance(current_context, dict):
            current_known_names = unique_strings(
                list(current_context.get("all_candidates") or [])
                + list(current_context.get("leaders") or [])
                + list(current_context.get("tier_1") or [])
                + list(current_context.get("tier_2") or [])
            )
        else:
            current_known_names = []
        if card_name and card_name not in current_known_names:
            fallback_chain_name = membership_lookup.get(card_name)
            if fallback_chain_name:
                enriched_card["chain_name"] = fallback_chain_name
                current_chain_name = fallback_chain_name
        context = chain_lookup.get(current_chain_name)
        if isinstance(context, dict):
            enriched_card["leaders"] = unique_strings(list(enriched_card.get("leaders", [])) + list(context.get("leaders", [])))
            enriched_card["peer_tier_1"] = unique_strings(list(enriched_card.get("peer_tier_1", [])) + list(context.get("tier_1", [])))
            enriched_card["peer_tier_2"] = unique_strings(list(enriched_card.get("peer_tier_2", [])) + list(context.get("tier_2", [])))
            enriched_card["chain_path_summary"] = build_chain_path_summary(enriched_card)
            trading_profile = classify_trading_profile(enriched_card)
            enriched_card["trading_profile_bucket"] = trading_profile["bucket"]
            enriched_card["trading_profile_subtype"] = trading_profile["subtype"]
            enriched_card["trading_profile_reason"] = trading_profile["reason"]
            enriched_card["trading_profile_playbook"] = build_trading_profile_playbook(enriched_card)
            enriched_card["trading_profile_judgment"] = build_trading_profile_judgment(enriched_card)
            enriched_card["trading_profile_usage"] = build_trading_profile_usage(enriched_card)
        enriched_cards.append(enriched_card)
    return enriched_cards


def build_chain_map_entries(event_cards: list[dict[str, Any]], discovery_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = discovery_context.get("chain_map") if isinstance(discovery_context, dict) and isinstance(discovery_context.get("chain_map"), list) else []

    chain_has_strong_validation: dict[str, bool] = {}
    for card in (event_cards if isinstance(event_cards, list) else []):
        if not isinstance(card, dict):
            continue
        chain_name = clean_text(card.get("chain_name"))
        if not chain_name:
            continue
        validation_label = clean_text((card.get("market_validation_summary") or {}).get("label"))
        if validation_label == "strong":
            chain_has_strong_validation[chain_name] = True

    grouped: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        chain_name = clean_text(item.get("chain_name"))
        if not chain_name:
            continue
        leaders = unique_strings(item.get("leaders") or [])
        tier_1 = unique_strings(item.get("tier_1") or [])
        tier_2 = unique_strings(item.get("tier_2") or [])
        has_strong = chain_has_strong_validation.get(chain_name, False)
        high_beta_candidates = [name for name in tier_1 if name not in leaders]
        if has_strong:
            high_beta = high_beta_candidates
            catchup = tier_2
        else:
            high_beta = []
            catchup = unique_strings(high_beta_candidates + tier_2)
        profiles = {
            "稳健核心": leaders,
            "高弹性": high_beta,
            "补涨候选": catchup,
            "预期差最大": [],
            "兑现风险最高": [],
        }
        grouped[chain_name] = {
            "chain_name": chain_name,
            "profiles": profiles,
            "chain_playbook": build_chain_map_playbook(profiles),
            "anchors": [],
        }
    for card in event_cards:
        if not isinstance(card, dict):
            continue
        chain_name = clean_text(card.get("chain_name"))
        if not chain_name:
            continue
        row = grouped.setdefault(
            chain_name,
            {"chain_name": chain_name, "profiles": {bucket: [] for bucket in TRADING_PROFILE_BUCKETS}, "anchors": []},
        )
        anchor_name = clean_text(card.get("name")) or clean_text(card.get("ticker"))
        if anchor_name and anchor_name not in row["anchors"]:
            row["anchors"].append(anchor_name)
        bucket = clean_text(card.get("trading_profile_bucket"))
        profiles = row.setdefault("profiles", {bucket_name: [] for bucket_name in TRADING_PROFILE_BUCKETS})
        for profile_names in profiles.values():
            if anchor_name in profile_names:
                profile_names[:] = [name for name in profile_names if name != anchor_name]
        if anchor_name and bucket in profiles:
            profiles[bucket] = unique_strings(list(profiles[bucket]) + [anchor_name])
        row["chain_playbook"] = build_chain_map_playbook(profiles)
    return list(grouped.values())


def build_chain_map_playbook(profiles: dict[str, list[str]] | None) -> str:
    profile_map = profiles if isinstance(profiles, dict) else {}
    core = profile_map.get("稳健核心") if isinstance(profile_map.get("稳健核心"), list) else []
    elastic = profile_map.get("高弹性") if isinstance(profile_map.get("高弹性"), list) else []
    catchup = profile_map.get("补涨候选") if isinstance(profile_map.get("补涨候选"), list) else []
    expectation_gap = profile_map.get("预期差最大") if isinstance(profile_map.get("预期差最大"), list) else []
    realized_risk = profile_map.get("兑现风险最高") if isinstance(profile_map.get("兑现风险最高"), list) else []

    if realized_risk and core:
        return "链条打法: 核心票已经进入兑现窗口，先防 sell-the-fact，再看后排轮动。"
    if realized_risk:
        return "链条打法: 当前先防兑现风险，不适合把这条链当作新开仓主攻方向。"
    if core and elastic:
        return "链条打法: 先看核心承载，再择机做高弹性进攻。"
    if core and catchup:
        return "链条打法: 先盯核心承载，再等轮动补涨。"
    if elastic:
        return "链条打法: 当前更适合按高弹性方向进攻，重点看加速与回踩二选一。"
    if catchup:
        return "链条打法: 当前更适合按轮动补涨处理，关注主线继续扩散而不是孤立抢跑。"
    if core:
        return "链条打法: 当前以核心承载为主，优先等回踩确认而不是情绪化追高。"
    if expectation_gap:
        return "链条打法: 当前更适合先观察预期定价，等市场把预期交易得更清楚。"
    return "链条打法: 当前缺少清晰主攻方向，先观察链内强弱分化。"


def apply_rendered_caps(
    tiers: dict[str, list[dict[str, Any]]],
    tier_caps: dict[str, int] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """
    Enforce per-tier caps. Overflow candidates get [tier_cap_overflow] tag
    and are removed from rendered tiers but kept in diagnostic scorecard.

    Returns: (capped_tiers, overflow_list)
    """
    caps = tier_caps or TIER_CAPS
    overflow: list[dict[str, Any]] = []
    capped: dict[str, list[dict[str, Any]]] = {}
    for tier_name, candidates in tiers.items():
        cap = caps.get(tier_name, 10)
        sorted_candidates = sorted(
            candidates,
            key=lambda x: x.get("adjusted_total_score", 0),
            reverse=True,
        )
        capped[tier_name] = sorted_candidates[:cap]
        for c in sorted_candidates[cap:]:
            c["tier_tags"] = c.get("tier_tags", []) + ["tier_cap_overflow"]
            overflow.append(c)
    return capped, overflow


def apply_total_rendered_cap(
    tiers: dict[str, list[dict[str, Any]]],
    *,
    total_cap: int | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Apply a final merged-tier display budget across T1/T2/T3/T4.

    Preserves tier priority by consuming the budget in T1 -> T2 -> T3 -> T4
    order, while sorting candidates within each tier by score descending.
    """
    budget = TOTAL_RENDERED_CAP if total_cap is None else int(total_cap)
    remaining = max(budget, 0)
    capped: dict[str, list[dict[str, Any]]] = {}
    overflow: list[dict[str, Any]] = []
    for tier_name in ("T1", "T2", "T3", "T4"):
        candidates = sorted(
            list(tiers.get(tier_name, [])),
            key=lambda x: x.get("score", x.get("adjusted_total_score", 0)),
            reverse=True,
        )
        if remaining <= 0:
            capped[tier_name] = []
            for c in candidates:
                c["tier_tags"] = c.get("tier_tags", []) + ["total_rendered_cap_overflow"]
                overflow.append(c)
            continue
        kept = candidates[:remaining]
        capped[tier_name] = kept
        for c in candidates[remaining:]:
            c["tier_tags"] = c.get("tier_tags", []) + ["total_rendered_cap_overflow"]
            overflow.append(c)
        remaining -= len(kept)
    return capped, overflow


def enrich_live_result_reporting(
    result: dict[str, Any],
    failure_candidates: list[dict[str, Any]],
    assessed_candidates: list[dict[str, Any]] | None = None,
    discovery_candidates: list[dict[str, Any]] | None = None,
    discovery_context: dict[str, Any] | None = None,
    setup_launch_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    enriched = enrich_degraded_live_result(result, failure_candidates)
    request_obj = enriched.get("request") if isinstance(enriched.get("request"), dict) else {}
    weekend_market_candidate_input = (
        request_obj.get("weekend_market_candidate_input")
        if isinstance(request_obj.get("weekend_market_candidate_input"), dict)
        else None
    )
    weekend_market_candidate, direction_reference_map = build_weekend_market_candidate(
        weekend_market_candidate_input
    )
    enriched["weekend_market_candidate"] = weekend_market_candidate
    enriched["direction_reference_map"] = direction_reference_map
    geopolitics_candidate_input = (
        request_obj.get("macro_geopolitics_candidate_input")
        if isinstance(request_obj.get("macro_geopolitics_candidate_input"), dict)
        else None
    )
    enriched["macro_geopolitics_candidate"] = build_macro_geopolitics_candidate(
        geopolitics_candidate_input
    )
    market_strength_candidates = (
        request_obj.get("market_strength_candidates")
        if isinstance(request_obj.get("market_strength_candidates"), list)
        else []
    )
    if setup_launch_candidates is None:
        setup_launch_candidates = (
            request_obj.get("setup_launch_candidates")
            if isinstance(request_obj.get("setup_launch_candidates"), list)
            else []
        )
    enriched["setup_launch_candidates"] = [
        item for item in (setup_launch_candidates or []) if isinstance(item, dict)
    ]
    emergent_theme_candidates, promoted_active_themes = build_emergent_theme_result_surfaces(
        request_obj,
        weekend_market_candidate=weekend_market_candidate,
        market_strength_candidates=market_strength_candidates,
        setup_launch_candidates=setup_launch_candidates,
    )
    enriched["emergent_theme_candidates"] = emergent_theme_candidates
    enriched["promoted_active_themes"] = promoted_active_themes
    dropped = [item for item in enriched.get("dropped", []) if isinstance(item, dict)]
    enriched["data_blocked_theme_confirmed"] = build_data_blocked_theme_confirmed_candidates(
        dropped,
        emergent_theme_candidates,
    )

    filter_summary = dict(enriched.get("filter_summary") or {})
    if dropped:
        drop_reason_counts: dict[str, int] = {}
        for item in dropped:
            for reason in split_drop_reasons(item.get("drop_reason")):
                drop_reason_counts[reason] = drop_reason_counts.get(reason, 0) + 1
        if drop_reason_counts:
            filter_summary["drop_reason_counts"] = drop_reason_counts
            enriched["filter_summary"] = filter_summary
    run_completeness = build_run_completeness_summary(
        request_obj,
        weekend_market_candidate=weekend_market_candidate,
        filter_summary=filter_summary,
    )
    enriched["run_completeness"] = run_completeness

    profile_settings = request_obj.get("profile_settings") if isinstance(request_obj.get("profile_settings"), dict) else {}
    min_price = request_obj.get("min_price") if request_obj.get("min_price") not in (None, "") else profile_settings.get("min_price")
    diagnostic_scorecard = [
        build_diagnostic_scorecard_entry(item, filter_summary.get("keep_threshold"), min_price)
        for item in (assessed_candidates or [])
        if isinstance(item, dict)
    ]
    if diagnostic_scorecard:
        # Apply board-specific threshold overrides before near-miss / tier logic
        active_profile = clean_text(
            filter_summary.get("profile")
            or filter_summary.get("filter_profile")
            or request_obj.get("filter_profile")
        )
        geopolitics_overlay = request_obj.get("macro_geopolitics_overlay")
        base_keep = float(filter_summary.get("keep_threshold", 60.0))
        diagnostic_scorecard, board_thresholds = apply_board_threshold_overrides(
            diagnostic_scorecard, active_profile, base_keep,
        )
        if board_thresholds:
            filter_summary["board_thresholds"] = board_thresholds
            enriched["filter_summary"] = filter_summary

        near_miss_candidates = build_near_miss_candidates(diagnostic_scorecard)
        analysis_date = clean_text(request_obj.get("analysis_time") or request_obj.get("target_date"))
        rescued_fallback_rows: list[dict[str, Any]] = []
        near_miss_index_by_ticker = {
            clean_text(item.get("ticker")): idx
            for idx, item in enumerate(near_miss_candidates)
            if clean_text(item.get("ticker"))
        }
        for item in diagnostic_scorecard:
            failures = set(item.get("hard_filter_failures", []))
            if "bars_fetch_failed" not in failures:
                continue
            target_dt = parse_date(analysis_date[:10]) if clean_text(analysis_date) else None
            start_date = (target_dt - timedelta(days=420)).isoformat() if target_dt else ""
            cached_rows = eastmoney_cached_bars_for_candidate(
                clean_text(item.get("ticker")),
                start_date,
                clean_text(analysis_date)[:10],
            )
            rescued = build_bars_cache_rescue_candidate(item, cached_rows, clean_text(analysis_date)[:10])
            if not rescued:
                snapshot = local_market_snapshot_for_candidate(clean_text(item.get("ticker")), analysis_date)
                rescued = build_bars_fallback_rescue_candidate(item, snapshot)
            if not rescued:
                continue
            ticker = clean_text(rescued.get("ticker"))
            rescued_fallback_rows.append(rescued)
            if ticker in near_miss_index_by_ticker:
                near_miss_candidates[near_miss_index_by_ticker[ticker]] = rescued
            else:
                near_miss_index_by_ticker[ticker] = len(near_miss_candidates)
                near_miss_candidates.append(rescued)
        near_miss_tickers = {clean_text(item.get("ticker")) for item in near_miss_candidates}
        for item in diagnostic_scorecard:
            item["midday_status"] = classify_midday_status(item, near_miss_tickers)
        filter_summary["diagnostic_scorecard_count"] = len(diagnostic_scorecard)
        enriched["filter_summary"] = filter_summary
        enriched["diagnostic_scorecard"] = diagnostic_scorecard
        enriched["midday_action_summary"] = build_midday_action_summary(diagnostic_scorecard)
        if near_miss_candidates:
            for item in near_miss_candidates:
                item["midday_status"] = classify_midday_status(item, near_miss_tickers)
            filter_summary["near_miss_candidate_count"] = len(near_miss_candidates)
            enriched["filter_summary"] = filter_summary
            enriched["near_miss_candidates"] = near_miss_candidates

    auto_discovery_candidates = build_auto_discovery_candidates(assessed_candidates or [])
    supplement_rows = build_market_strength_discovery_candidates(market_strength_candidates)
    discovery_rows = build_discovery_candidates(
        merge_discovery_candidate_inputs(list(discovery_candidates or []) + supplement_rows, auto_discovery_candidates)
    )
    if discovery_rows:
        event_cards = enrich_event_cards_with_chain_context(build_event_cards(discovery_rows), discovery_context)
        for row in event_cards:
            if clean_text(row.get("primary_event_type")) == "market_strength_scan":
                row["market_strength_supplement"] = True
        event_cards = attach_market_strength_review_price_fields(event_cards, market_strength_candidates)
        enriched["event_cards"] = event_cards
        enriched["discovery_lane_summary"] = build_discovery_lane_summary(event_cards)
        enriched["chain_map_entries"] = build_chain_map_entries(event_cards, discovery_context)
        enriched["directly_actionable"] = [row for row in event_cards if row.get("discovery_bucket") == "qualified"][:MAX_REPORTED_TOP_PICKS]
        enriched["priority_watchlist"] = [row for row in event_cards if row.get("discovery_bucket") == "watch"][:MAX_REPORTED_NEAR_MISS]
        enriched["chain_tracking"] = [row for row in event_cards if row.get("discovery_bucket") not in {"qualified", "watch"}][:MAX_REPORTED_BLOCKED]

    midday_action_summary = build_midday_action_summary_from_result(enriched)
    if midday_action_summary:
        enriched["midday_action_summary"] = midday_action_summary
    decision_factors = build_decision_factors_from_result(enriched)
    decision_flow: list[dict[str, Any]] = []
    if any(decision_factors.values()):
        enriched["decision_factors"] = decision_factors
        decision_flow = build_decision_flow(enriched)
        enriched["decision_flow"] = decision_flow

    # --- Tier output integration ---
    if diagnostic_scorecard:
        keep_threshold = filter_summary.get("keep_threshold", 60.0)
        top_picks = [item for item in diagnostic_scorecard if item.get("keep")]
        near_miss_candidates_for_tiers = enriched.get("near_miss_candidates", [])
        discovery_results = {
            "qualified": enriched.get("directly_actionable", []),
            "watch": enriched.get("priority_watchlist", []),
            "track": enriched.get("chain_tracking", []),
        }
        tiers = assign_tiers(
            top_picks, near_miss_candidates_for_tiers,
            discovery_results, diagnostic_scorecard, keep_threshold,
            geopolitics_overlay=geopolitics_overlay if isinstance(geopolitics_overlay, dict) else None,
        )
        rescued_by_ticker = {
            clean_text(item.get("ticker")): item
            for item in rescued_fallback_rows
            if clean_text(item.get("ticker"))
        }
        if rescued_by_ticker:
            enriched["bars_fallback_rescues"] = list(rescued_by_ticker.values())
            for tier_name in ("T1", "T2", "T4"):
                tiers[tier_name] = [
                    item
                    for item in tiers.get(tier_name, [])
                    if clean_text(item.get("ticker")) not in rescued_by_ticker
                ]
            t3_rows = [
                item
                for item in tiers.get("T3", [])
                if clean_text(item.get("ticker")) not in rescued_by_ticker
            ]
            t3_rows.extend(rescued_by_ticker.values())
            tiers["T3"] = t3_rows
            enriched = prune_rescued_blocked_candidates(enriched, list(rescued_by_ticker.values()))
        capped_tiers, overflow = apply_rendered_caps(tiers)
        enriched["tier_output"] = {
            tier_name: [
                {
                    "ticker": clean_text(c.get("ticker")),
                    "name": clean_text(c.get("name")),
                    "score": c.get("score") or c.get("adjusted_total_score"),
                    "wrapper_tier": c.get("wrapper_tier"),
                    "tier_tags": c.get("tier_tags", []),
                    "fallback_support_reason": clean_text(c.get("fallback_support_reason")),
                    "fallback_snapshot_only": bool(c.get("fallback_snapshot_only")),
                    "fallback_cache_only": bool(c.get("fallback_cache_only")),
                    "bars_source": clean_text(c.get("bars_source")),
                }
                for c in candidates
            ]
            for tier_name, candidates in capped_tiers.items()
        }
        enriched["tier_metadata"] = {
            "total_rendered": sum(len(v) for v in capped_tiers.values()),
            "overflow_count": len(overflow),
            "floor_policy_applied": any(
                "coverage_fill" in c.get("tier_tags", [])
                for tier in capped_tiers.values() for c in tier
            ),
            "profile_used": str(filter_summary.get("profile", "default")),
        }

    report_markdown = str(enriched.get("report_markdown") or "").rstrip()
    if "## Dropped Candidates" in report_markdown:
        lines = [report_markdown]
    else:
        lines = [report_markdown] if report_markdown else []
        if dropped:
            lines.extend(["", "## Dropped Candidates", ""])
            for item in dropped:
                ticker = clean_text(item.get("ticker")) or "unknown"
                name = clean_text(item.get("name")) or ticker
                reason = clean_text(item.get("drop_reason")) or "dropped"
                lines.append(f"- `{ticker}` {name}: `{reason}`")
    if diagnostic_scorecard and "## Diagnostic Scorecard" not in "\n".join(lines):
        lines.extend(["", "## Diagnostic Scorecard", ""])
        for item in diagnostic_scorecard:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            score = item.get("score")
            gap = item.get("keep_threshold_gap")
            failures = ",".join(item.get("hard_filter_failures", [])) if isinstance(item.get("hard_filter_failures"), list) else clean_text(item.get("hard_filter_failures"))
            components = item.get("diagnostic_components") if isinstance(item.get("diagnostic_components"), dict) else {}
            component_summary = " / ".join(
                f"{label}=`{components[label]}`"
                for label in ("trend", "rs", "catalyst", "liquidity")
                if components.get(label) not in (None, "")
            )
            lines.append(
                f"- `{ticker}` {name}: status=`{item.get('midday_status')}` score=`{score}` gap=`{gap}`"
                + (f" {component_summary}" if component_summary else "")
                + f" failures=`{failures or 'none'}`"
            )
    near_miss_candidates = enriched.get("near_miss_candidates", [])
    if isinstance(near_miss_candidates, list) and near_miss_candidates and "## Near Miss Candidates" not in "\n".join(lines):
        lines.extend(["", "## Near Miss Candidates", ""])
        for item in near_miss_candidates:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            score = item.get("score")
            gap = item.get("keep_threshold_gap")
            lines.append(f"- `{ticker}` {name}: status=`{item.get('midday_status')}` score=`{score}` gap=`{gap}`")
    midday_action_summary = enriched.get("midday_action_summary", [])
    if isinstance(midday_action_summary, list) and midday_action_summary and "## 午盘操作建议摘要" not in "\n".join(lines):
        lines.extend(["", "## 午盘操作建议摘要", ""])
        for item in midday_action_summary:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            action = clean_text(item.get("action")) or "继续观察"
            score = item.get("score")
            gap = item.get("keep_threshold_gap")
            lines.append(f"- `{ticker}` {name}: `{action}` score=`{score}` gap=`{gap}`")
    if any(decision_factors.values()) and "## Decision Factors" not in "\n".join(lines):
        lines.extend(["", "## Decision Factors", ""])
        section_map = [("qualified", "可执行"), ("near_miss", "继续观察"), ("blocked", "不执行")]
        for key, title in section_map:
            rows = decision_factors.get(key, [])
            if not rows:
                continue
            lines.extend(["", f"### {title}", ""])
            for item in rows:
                ticker = clean_text(item.get("ticker")) or "unknown"
                name = clean_text(item.get("name")) or ticker
                lines.append(f"- `{ticker}` {name}")
                lines.append(f"  - 动作: `{item.get('action')}`")
                if item.get("score") not in (None, ""):
                    lines.append(f"  - 分数: `{item.get('score')}`")
                if item.get("keep_threshold_gap") not in (None, ""):
                    lines.append(f"  - 与 keep line 差距: `{item.get('keep_threshold_gap')}`")
                lines.append(f"  - 技术形态: {item.get('technical_summary')}")
                lines.append(f"  - 关键事件: {item.get('event_summary')}")
                lines.append(f"  - 下一步推演: {item.get('likely_next_summary')}")
                lines.append(f"  - 判断逻辑: {item.get('logic_summary')}")
                lines.append(f"  - 交易层: {item.get('trade_layer_summary')}")
                next_watch = item.get("next_watch_items") if isinstance(item.get("next_watch_items"), list) else []
                for note in next_watch[:MAX_REPORTED_WATCH_ITEMS]:
                    lines.append(f"  - 观察点: {note}")

    # --- T2 事件驱动 section ---
    tier_output = enriched.get("tier_output", {})
    t2_candidates = tier_output.get("T2", [])
    if t2_candidates and "## T2 事件驱动" not in "\n".join(lines):
        lines.extend(["", "## T2 事件驱动", ""])
        lines.append("| 标的 | 分数 | 事件信号 | 来源 |")
        lines.append("|---|---|---|---|")
        for item in t2_candidates:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            score = item.get("score", "")
            tags = ", ".join(item.get("tier_tags", []))
            lines.append(f"| `{ticker}` {name} | {score} | {tags} | T2 |")

    weekend_candidate = enriched.get("weekend_market_candidate") if isinstance(enriched.get("weekend_market_candidate"), dict) else None
    direction_reference_map = enriched.get("direction_reference_map") if isinstance(enriched.get("direction_reference_map"), list) else None
    weekend_lines = build_weekend_market_candidate_markdown(weekend_candidate, direction_reference_map)
    if weekend_lines and "## 周末主线候选" not in "\n".join(lines):
        if report_markdown and "## 决策流" in report_markdown:
            lines[0] = report_markdown.replace(
                "## 决策流",
                "\n".join(weekend_lines).strip() + "\n\n## 决策流",
                1,
            )
        else:
            lines.extend(weekend_lines)

    directly_actionable = enriched.get("directly_actionable", [])
    if isinstance(directly_actionable, list) and directly_actionable and "## 直接可执行" not in "\n".join(lines):
        lines.extend(["", "## 直接可执行", ""])
        for item in directly_actionable:
            lines.append(f"- `{item.get('ticker')}` {item.get('name')}")
            lines.append(f"  - 事件: `{item.get('event_type')}`")
            lines.append(f"  - 事件状态: `{item.get('event_state', {}).get('label')}`")
            lines.append(f"  - 链条: `{item.get('chain_name')}` / `{item.get('chain_role')}`")
            lines.append(f"  - 市场验证: {item.get('market_validation_summary', {}).get('summary')}")
            lines.append(f"  - 交易可用性: {item.get('trading_usability', {}).get('summary')}")

    priority_watchlist = enriched.get("priority_watchlist", [])
    if isinstance(priority_watchlist, list) and priority_watchlist and "## 重点观察" not in "\n".join(lines):
        lines.extend(["", "## 重点观察", ""])
        for item in priority_watchlist:
            confidence = item.get("rumor_confidence_range", {})
            lines.append(f"- `{item.get('ticker')}` {item.get('name')}")
            lines.append(f"  - 事件: `{item.get('event_type')}`")
            lines.append(f"  - 事件状态: `{item.get('event_state', {}).get('label')}`")
            lines.append(f"  - 可信度区间: `{confidence.get('label')}` `{confidence.get('range')}`")
            lines.append(f"  - 链条: `{item.get('chain_name')}` / `{item.get('chain_role')}`")
            lines.append(f"  - 交易可用性: {item.get('trading_usability', {}).get('summary')}")

    chain_tracking = enriched.get("chain_tracking", [])
    if isinstance(chain_tracking, list) and chain_tracking and "## 链条跟踪" not in "\n".join(lines):
        lines.extend(["", "## 链条跟踪", ""])
        for item in chain_tracking:
            lines.append(f"- `{item.get('ticker')}` {item.get('name')}: `{item.get('chain_name')}` / `{item.get('chain_role')}`")
            lines.append(f"  - 事件状态: `{item.get('event_state', {}).get('label')}`")
            lines.append(f"  - 交易可用性: {item.get('trading_usability', {}).get('summary')}")

    setup_launch_lines = build_setup_launch_markdown(
        enriched.get("setup_launch_candidates")
        if isinstance(enriched.get("setup_launch_candidates"), list)
        else None
    )
    if setup_launch_lines and "## 筑底启动补充" not in "\n".join(lines):
        lines.extend(setup_launch_lines)

    emergent_theme_lines = build_emergent_theme_markdown(
        enriched.get("emergent_theme_candidates")
        if isinstance(enriched.get("emergent_theme_candidates"), list)
        else None
    )
    if emergent_theme_lines and "## 新兴共振主题" not in "\n".join(lines):
        lines.extend(emergent_theme_lines)
    data_blocked_theme_lines = build_data_blocked_theme_confirmed_markdown(
        enriched.get("data_blocked_theme_confirmed")
        if isinstance(enriched.get("data_blocked_theme_confirmed"), list)
        else None
    )
    if data_blocked_theme_lines and "## 数据受阻但主题已确认" not in "\n".join(lines):
        lines.extend(data_blocked_theme_lines)

    event_cards = enriched.get("event_cards", [])
    if decision_flow and "## 决策流" not in "\n".join(lines):
        geopolitics_overlay = request_obj.get("macro_geopolitics_overlay") if isinstance(request_obj.get("macro_geopolitics_overlay"), dict) else None
        geopolitics_candidate = enriched.get("macro_geopolitics_candidate") if isinstance(enriched.get("macro_geopolitics_candidate"), dict) else None
        lines.extend(build_decision_flow_markdown(decision_flow, geopolitics_overlay, geopolitics_candidate))
    if isinstance(event_cards, list) and event_cards and "## Event Cards" not in "\n".join(lines):
        lines.extend(["", "## Event Cards", ""])
        for item in event_cards:
            lines.append(f"- `{item.get('ticker')}` {item.get('name')}")
            lines.append(f"  - 阶段: `{item.get('event_phase')}`")
            lines.append(f"  - 预期判断: `{item.get('expectation_verdict')}`")
            lines.append(f"  - {item.get('trading_profile_judgment')}")
            lines.append(f"  - {item.get('trading_profile_usage')}")
            metrics = item.get("headline_metrics") if isinstance(item.get("headline_metrics"), list) else []
            if metrics:
                lines.append(f"  - 关键数据: `{', '.join(metrics[:4])}`")
            lines.append(f"  - 社区反应: {item.get('community_reaction_summary')}")
            lines.append(f"  - 社区一致性: `{item.get('community_conviction')}`")
            lines.append(f"  - 预期驱动: {item.get('expectation_basis_summary')}")
            lines.append(f"  - 兑现风险: {item.get('expectation_risk_summary')}")
            lines.append(f"  - primary_event_type: `{item.get('primary_event_type')}`")
            lines.append(f"  - priority_score: `{item.get('priority_score')}`")
            lines.append(f"  - why_now: `{item.get('why_now')}`")
            lines.append(f"  - chain_path_summary: `{item.get('chain_path_summary')}`")
            lines.append(f"  - market_signal_summary: `{item.get('market_signal_summary')}`")
            lines.append(f"  - source_count: `{item.get('source_count')}`")
            lines.append(f"  - source_accounts: `{', '.join(item.get('source_accounts', [])) or 'none'}`")
            lines.append(f"  - source_urls: `{', '.join(item.get('source_urls', [])) or 'none'}`")
            lines.append(f"  - evidence_mix: `{json.dumps(item.get('evidence_mix', {}), ensure_ascii=False, sort_keys=True)}`")
            lines.append(f"  - event_state: `{item.get('event_state', {}).get('label')}`")
            lines.append(f"  - trading_usability: `{item.get('trading_usability', {}).get('label')}`")
            key_evidence = item.get("key_evidence") if isinstance(item.get("key_evidence"), list) else []
            if key_evidence:
                lines.append("  - key_evidence:")
                for bullet in key_evidence[:MAX_REPORTED_WATCH_ITEMS]:
                    lines.append(f"    - {bullet}")
    report_markdown = prepend_report_metadata_lines(
        "\n".join(lines).strip(),
        build_run_completeness_report_lines(run_completeness),
    )
    enriched["report_markdown"] = annotate_ticker_names_in_markdown(report_markdown, enriched)
    return enriched


# ---------------------------------------------------------------------------
# Multi-track pipeline helpers
# ---------------------------------------------------------------------------

def enrich_track_result(
    result: dict[str, Any],
    failure_candidates: list[dict[str, Any]],
    assessed_candidates: list[dict[str, Any]] | None = None,
    *,
    track_name: str = "",
    track_config: dict[str, Any] | None = None,
    direction_reference_map: list[dict[str, Any]] | None = None,
    weekend_market_candidate: dict[str, Any] | None = None,
    prior_review_adjustments: list[dict[str, Any]] | None = None,
    geopolitics_overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich a single track's compiled-runtime result.

    Similar to ``enrich_live_result_reporting`` but uses the track's own
    keep_threshold and tier_caps instead of applying board overrides.
    Discovery / event-card enrichment is intentionally omitted here; it
    is handled once in ``merge_track_results`` across all tracks.
    """
    cfg = track_config or {}
    enriched = enrich_degraded_live_result(result, failure_candidates)
    dropped = [item for item in enriched.get("dropped", []) if isinstance(item, dict)]

    filter_summary = dict(enriched.get("filter_summary") or {})
    keep_threshold = float(cfg.get("keep_threshold") or filter_summary.get("keep_threshold", 60.0))
    # Override filter_summary thresholds with track config
    filter_summary["keep_threshold"] = keep_threshold
    filter_summary["strict_top_pick_threshold"] = float(
        cfg.get("strict_top_pick_threshold") or filter_summary.get("strict_top_pick_threshold", 62.0)
    )
    if track_name:
        filter_summary["track_name"] = track_name
        filter_summary["track_label"] = cfg.get("label", track_name)

    if dropped:
        drop_reason_counts: dict[str, int] = {}
        for item in dropped:
            for reason in split_drop_reasons(item.get("drop_reason")):
                drop_reason_counts[reason] = drop_reason_counts.get(reason, 0) + 1
        if drop_reason_counts:
            filter_summary["drop_reason_counts"] = drop_reason_counts
    enriched["filter_summary"] = filter_summary

    diagnostic_scorecard = [
        build_diagnostic_scorecard_entry(item, keep_threshold)
        for item in (assessed_candidates or [])
        if isinstance(item, dict)
    ]
    if diagnostic_scorecard:
        active_profile = clean_text(
            filter_summary.get("profile")
            or filter_summary.get("filter_profile")
            or (enriched.get("request") or {}).get("filter_profile")
        )
        geopolitics_overlay = (enriched.get("request") or {}).get("macro_geopolitics_overlay")
        # No board overrides needed — each track already has the correct threshold
        near_miss_candidates = build_near_miss_candidates(diagnostic_scorecard)
        waiver_candidates = apply_catalyst_waiver(
            diagnostic_scorecard, active_profile, keep_threshold,
        )
        if waiver_candidates:
            near_miss_by_ticker = {
                clean_text(item.get("ticker")): item for item in near_miss_candidates
            }
            for item in waiver_candidates:
                ticker = clean_text(item.get("ticker"))
                if not ticker or ticker in near_miss_by_ticker:
                    continue
                near_miss_candidates.append(item)
                near_miss_by_ticker[ticker] = item
        analysis_date = clean_text(
            (result.get("request") or {}).get("analysis_time")
            or (result.get("request") or {}).get("target_date")
            or (enriched.get("request") or {}).get("analysis_time")
            or (enriched.get("request") or {}).get("target_date")
        )
        rescued_fallback_rows: list[dict[str, Any]] = []
        near_miss_index_by_ticker = {
            clean_text(item.get("ticker")): idx
            for idx, item in enumerate(near_miss_candidates)
            if clean_text(item.get("ticker"))
        }
        for item in diagnostic_scorecard:
            failures = set(item.get("hard_filter_failures", []))
            if "bars_fetch_failed" not in failures:
                continue
            target_dt = parse_date(analysis_date[:10]) if clean_text(analysis_date) else None
            start_date = (target_dt - timedelta(days=420)).isoformat() if target_dt else ""
            cached_rows = eastmoney_cached_bars_for_candidate(
                clean_text(item.get("ticker")),
                start_date,
                clean_text(analysis_date)[:10],
            )
            rescued = build_bars_cache_rescue_candidate(item, cached_rows, clean_text(analysis_date)[:10])
            if not rescued:
                snapshot = local_market_snapshot_for_candidate(clean_text(item.get("ticker")), analysis_date)
                rescued = build_bars_fallback_rescue_candidate(item, snapshot)
            if not rescued:
                continue
            ticker = clean_text(rescued.get("ticker"))
            rescued_fallback_rows.append(rescued)
            if ticker in near_miss_index_by_ticker:
                near_miss_candidates[near_miss_index_by_ticker[ticker]] = rescued
            else:
                near_miss_index_by_ticker[ticker] = len(near_miss_candidates)
                near_miss_candidates.append(rescued)
        near_miss_tickers = {clean_text(item.get("ticker")) for item in near_miss_candidates}
        for item in diagnostic_scorecard:
            item["midday_status"] = classify_midday_status(item, near_miss_tickers)
            item["track_name"] = track_name
        filter_summary["diagnostic_scorecard_count"] = len(diagnostic_scorecard)
        enriched["filter_summary"] = filter_summary
        enriched["diagnostic_scorecard"] = diagnostic_scorecard
        enriched["midday_action_summary"] = build_midday_action_summary(diagnostic_scorecard)
        if near_miss_candidates:
            for item in near_miss_candidates:
                item["midday_status"] = classify_midday_status(item, near_miss_tickers)
                item["track_name"] = track_name
            filter_summary["near_miss_candidate_count"] = len(near_miss_candidates)
            enriched["filter_summary"] = filter_summary
            enriched["near_miss_candidates"] = near_miss_candidates

        # Tier assignment with track-specific caps
        top_picks = [item for item in diagnostic_scorecard if item.get("keep")]
        enriched["top_picks"] = top_picks
        filter_summary["universe_count"] = len(diagnostic_scorecard) + len(dropped)
        filter_summary["kept_count"] = len(top_picks)
        filter_summary["top_pick_count"] = len(top_picks)
        enriched["filter_summary"] = filter_summary
        # Direction alignment boost (after review_based_priority_boost, before assign_tiers)
        if direction_reference_map and weekend_market_candidate:
            direction_momentum = None
            if prior_review_adjustments and isinstance(prior_review_adjustments, list):
                # Look for direction_momentum in the review data
                for adj in prior_review_adjustments:
                    if isinstance(adj, dict) and "direction_momentum" in adj:
                        direction_momentum = adj["direction_momentum"]
                        break
            top_picks = direction_alignment_boost(
                top_picks, direction_reference_map, weekend_market_candidate,
                direction_momentum=direction_momentum,
                geopolitics_overlay=geopolitics_overlay,
            )
            enriched["top_picks"] = top_picks
        near_miss_for_tiers = enriched.get("near_miss_candidates", [])
        # Discovery results are empty at track level — merged later
        discovery_results: dict[str, list[dict[str, Any]]] = {"qualified": [], "watch": [], "track": []}
        tiers = assign_tiers(
            top_picks, near_miss_for_tiers,
            discovery_results, diagnostic_scorecard, keep_threshold,
            geopolitics_overlay=geopolitics_overlay if isinstance(geopolitics_overlay, dict) else None,
        )
        tiers = apply_floor_policy(
            tiers,
            diagnostic_scorecard,
            discovery_results,
            keep_threshold,
        )
        # Direction tier promotion (after assign_tiers)
        if direction_reference_map and weekend_market_candidate:
            tiers = direction_tier_promotion(
                tiers, direction_reference_map, weekend_market_candidate,
                direction_momentum=direction_momentum if 'direction_momentum' in dir() else None,
            )
        rescued_by_ticker = {
            clean_text(item.get("ticker")): item
            for item in rescued_fallback_rows
            if clean_text(item.get("ticker"))
        }
        if rescued_by_ticker:
            enriched["bars_fallback_rescues"] = list(rescued_by_ticker.values())
            for tier_name in ("T1", "T2", "T4"):
                tiers[tier_name] = [
                    item
                    for item in tiers.get(tier_name, [])
                    if clean_text(item.get("ticker")) not in rescued_by_ticker
                ]
            t3_rows = [
                item
                for item in tiers.get("T3", [])
                if clean_text(item.get("ticker")) not in rescued_by_ticker
            ]
            t3_rows.extend(rescued_by_ticker.values())
            tiers["T3"] = t3_rows
            enriched = prune_rescued_blocked_candidates(enriched, list(rescued_by_ticker.values()))
        track_tier_caps = cfg.get("tier_caps", TIER_CAPS)
        capped_tiers, overflow = apply_rendered_caps(tiers, tier_caps=track_tier_caps)
        enriched["tier_output"] = {
            tier_name: [
                {
                    "ticker": clean_text(c.get("ticker")),
                    "name": clean_text(c.get("name")),
                    "score": c.get("score") or c.get("adjusted_total_score"),
                    "wrapper_tier": c.get("wrapper_tier"),
                    "tier_tags": c.get("tier_tags", []),
                    "track_name": track_name,
                    "fallback_support_reason": clean_text(c.get("fallback_support_reason")),
                    "fallback_snapshot_only": bool(c.get("fallback_snapshot_only")),
                    "fallback_cache_only": bool(c.get("fallback_cache_only")),
                    "bars_source": clean_text(c.get("bars_source")),
                }
                for c in candidates
            ]
            for tier_name, candidates in capped_tiers.items()
        }
        enriched["tier_metadata"] = {
            "total_rendered": sum(len(v) for v in capped_tiers.values()),
            "overflow_count": len(overflow),
            "floor_policy_applied": any(
                "coverage_fill" in c.get("tier_tags", [])
                for tier in capped_tiers.values() for c in tier
            ),
            "bars_fallback_rescue_count": len(rescued_fallback_rows),
            "track_name": track_name,
        }

    enriched["_track_name"] = track_name
    enriched["_track_config"] = cfg
    return enriched


def _build_track_report_section(
    track_name: str,
    track_config: dict[str, Any],
    enriched: dict[str, Any],
) -> list[str]:
    """Build markdown lines for a single track's section in the report."""
    label = track_config.get("label", track_name)
    lines: list[str] = [f"## {label} ({track_name})"]

    top_picks = enriched.get("top_picks", [])
    if isinstance(top_picks, list) and top_picks:
        lines.extend(["", "### Top Picks", ""])
        for item in top_picks:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            lines.append(f"- `{ticker}` {name}")
    else:
        lines.extend(["", "### Top Picks", "", "- None"])

    dropped = [item for item in enriched.get("dropped", []) if isinstance(item, dict)]
    if dropped:
        lines.extend(["", "### Dropped Candidates", ""])
        for item in dropped:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            reason = clean_text(item.get("drop_reason")) or "dropped"
            lines.append(f"- `{ticker}` {name}: `{reason}`")

    diagnostic_scorecard = enriched.get("diagnostic_scorecard", [])
    if diagnostic_scorecard:
        lines.extend(["", "### Diagnostic Scorecard", ""])
        for item in diagnostic_scorecard:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            score = item.get("score")
            gap = item.get("keep_threshold_gap")
            failures = ",".join(item.get("hard_filter_failures", [])) if isinstance(item.get("hard_filter_failures"), list) else clean_text(item.get("hard_filter_failures"))
            components = item.get("diagnostic_components") if isinstance(item.get("diagnostic_components"), dict) else {}
            component_summary = " / ".join(
                f"{lbl}=`{components[lbl]}`"
                for lbl in ("trend", "rs", "catalyst", "liquidity")
                if components.get(lbl) not in (None, "")
            )
            lines.append(
                f"- `{ticker}` {name}: status=`{item.get('midday_status')}` score=`{score}` gap=`{gap}`"
                + (f" {component_summary}" if component_summary else "")
                + f" failures=`{failures or 'none'}`"
            )

    near_miss_candidates = enriched.get("near_miss_candidates", [])
    if isinstance(near_miss_candidates, list) and near_miss_candidates:
        lines.extend(["", "### Near Miss Candidates", ""])
        for item in near_miss_candidates:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            score = item.get("score")
            gap = item.get("keep_threshold_gap")
            lines.append(f"- `{ticker}` {name}: status=`{item.get('midday_status')}` score=`{score}` gap=`{gap}`")

    midday_action_summary = enriched.get("midday_action_summary", [])
    if isinstance(midday_action_summary, list) and midday_action_summary:
        lines.extend(["", "### 午盘操作建议摘要", ""])
        for item in midday_action_summary:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            action = clean_text(item.get("action")) or "继续观察"
            score = item.get("score")
            gap = item.get("keep_threshold_gap")
            lines.append(f"- `{ticker}` {name}: `{action}` score=`{score}` gap=`{gap}`")

    return lines


def _entry_list_candidate_summary(row: dict[str, Any], *, source_bucket: str) -> dict[str, Any]:
    trade_card = row.get("trade_card") if isinstance(row.get("trade_card"), dict) else {}
    event_state = safe_dict(row.get("event_state"))
    market_validation = safe_dict(row.get("market_validation_summary"))
    trading_usability = safe_dict(row.get("trading_usability"))
    risk_flags = [
        clean_text(item)
        for item in (trade_card.get("risk_flags") if isinstance(trade_card.get("risk_flags"), list) else [])
        if clean_text(item)
    ]
    summary = {
        "ticker": clean_text(row.get("ticker") or row.get("code") or row.get("symbol")),
        "name": clean_text(row.get("name")),
        "source_bucket": source_bucket,
        "source": clean_text(row.get("source")),
        "readiness_status": clean_text(row.get("readiness_status")),
        "chain_name": clean_text(row.get("chain_name")),
        "event_type": clean_text(row.get("event_type") or row.get("primary_event_type")),
        "action": clean_text(trade_card.get("watch_action") or row.get("watch_action")),
        "why_now": clean_text(row.get("why_now")),
        "event_state_label": clean_text(event_state.get("label")),
        "event_state_summary": clean_text(event_state.get("summary")),
        "market_signal_summary": clean_text(row.get("market_signal_summary")),
        "community_reaction_summary": clean_text(row.get("community_reaction_summary")),
        "expectation_basis_summary": clean_text(row.get("expectation_basis_summary")),
        "expectation_risk_summary": clean_text(row.get("expectation_risk_summary")),
        "market_validation_label": clean_text(market_validation.get("label")),
        "market_validation_summary": clean_text(market_validation.get("summary")),
        "trading_usability_label": clean_text(trading_usability.get("label")),
        "trading_usability_summary": clean_text(trading_usability.get("summary")),
        "trading_profile_bucket": clean_text(row.get("trading_profile_bucket")),
        "trading_profile_subtype": clean_text(row.get("trading_profile_subtype")),
        "trading_profile_reason": clean_text(row.get("trading_profile_reason")),
        "trading_profile_judgment": clean_text(row.get("trading_profile_judgment")),
        "trading_profile_usage": clean_text(row.get("trading_profile_usage")),
        "trading_profile_playbook": clean_text(row.get("trading_profile_playbook")),
        "trade_action": clean_text(trade_card.get("watch_action")),
        "trade_trigger": clean_text(trade_card.get("trigger")),
        "trade_invalidation": clean_text(trade_card.get("invalidation")),
        "trade_stop": clean_text(trade_card.get("stop")),
        "trade_position_sizing_guidance": clean_text(trade_card.get("position_sizing_guidance")),
        "trade_risk_flags": risk_flags,
        "score": row.get("score"),
        "keep_threshold_gap": row.get("keep_threshold_gap"),
        "market_strength_supplement": bool(row.get("market_strength_supplement")),
    }
    for key in MARKET_STRENGTH_REVIEW_PRICE_FIELDS:
        if row.get(key) not in (None, ""):
            summary[key] = row.get(key)
    return {key: value for key, value in summary.items() if value not in ("", None, [], {})}


def _entry_list_candidate_detail_lines(row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    source = clean_text(row.get("source"))
    if source:
        lines.append(f"source: `{source}`")
    readiness_status = clean_text(row.get("readiness_status"))
    if readiness_status:
        lines.append(f"readiness_status: `{readiness_status}`")
    event_state_label = clean_text(row.get("event_state_label"))
    event_state_summary = clean_text(row.get("event_state_summary"))
    if event_state_label or event_state_summary:
        event_state = f"`{event_state_label}`" if event_state_label else "`unknown`"
        if event_state_summary:
            event_state = f"{event_state} - {event_state_summary}"
        lines.append(f"event_state: {event_state}")
    market_signal_summary = clean_text(row.get("market_signal_summary"))
    if market_signal_summary:
        lines.append(f"market_signal_summary: {market_signal_summary}")
    community_reaction_summary = clean_text(row.get("community_reaction_summary"))
    if community_reaction_summary:
        lines.append(f"community_reaction_summary: {community_reaction_summary}")
    expectation_basis_summary = clean_text(row.get("expectation_basis_summary"))
    if expectation_basis_summary:
        lines.append(f"expectation_basis_summary: {expectation_basis_summary}")
    expectation_risk_summary = clean_text(row.get("expectation_risk_summary"))
    if expectation_risk_summary:
        lines.append(f"expectation_risk_summary: {expectation_risk_summary}")
    market_validation_label = clean_text(row.get("market_validation_label"))
    market_validation_summary = clean_text(row.get("market_validation_summary"))
    if market_validation_label or market_validation_summary:
        market_validation = f"`{market_validation_label}`" if market_validation_label else "`unknown`"
        if market_validation_summary:
            market_validation = f"{market_validation} - {market_validation_summary}"
        lines.append(f"market_validation_summary: {market_validation}")
    trading_usability_label = clean_text(row.get("trading_usability_label"))
    trading_usability_summary = clean_text(row.get("trading_usability_summary"))
    if trading_usability_label or trading_usability_summary:
        trading_usability = f"`{trading_usability_label}`" if trading_usability_label else "`unknown`"
        if trading_usability_summary:
            trading_usability = f"{trading_usability} - {trading_usability_summary}"
        lines.append(f"trading_usability: {trading_usability}")
    trading_profile_bucket = clean_text(row.get("trading_profile_bucket"))
    trading_profile_judgment = clean_text(row.get("trading_profile_judgment"))
    trading_profile_usage = clean_text(row.get("trading_profile_usage"))
    trading_profile_playbook = clean_text(row.get("trading_profile_playbook"))
    if trading_profile_bucket:
        lines.append(f"trading_profile_bucket: `{trading_profile_bucket}`")
    if trading_profile_judgment:
        lines.append(f"trading_profile_judgment: {trading_profile_judgment}")
    if trading_profile_usage:
        lines.append(f"trading_profile_usage: {trading_profile_usage}")
    if trading_profile_playbook:
        lines.append(f"trading_profile_playbook: {trading_profile_playbook}")
    trade_action = clean_text(row.get("trade_action"))
    if trade_action:
        lines.append(f"trade_card.watch_action: `{trade_action}`")
    trade_trigger = clean_text(row.get("trade_trigger"))
    if trade_trigger:
        lines.append(f"trade_card.trigger: {trade_trigger}")
    trade_invalidation = clean_text(row.get("trade_invalidation"))
    if trade_invalidation:
        lines.append(f"trade_card.invalidation: {trade_invalidation}")
    trade_stop = clean_text(row.get("trade_stop"))
    if trade_stop:
        lines.append(f"trade_card.stop: {trade_stop}")
    trade_position_sizing_guidance = clean_text(row.get("trade_position_sizing_guidance"))
    if trade_position_sizing_guidance:
        lines.append(f"trade_card.position_sizing_guidance: {trade_position_sizing_guidance}")
    trade_risk_flags = [
        clean_text(item)
        for item in (row.get("trade_risk_flags") if isinstance(row.get("trade_risk_flags"), list) else [])
        if clean_text(item)
    ]
    if trade_risk_flags:
        lines.append(f"trade_card.risk_flags: `{', '.join(trade_risk_flags)}`")
    score = row.get("score")
    if score not in (None, ""):
        lines.append(f"score: `{score}`")
    keep_threshold_gap = row.get("keep_threshold_gap")
    if keep_threshold_gap not in (None, ""):
        lines.append(f"keep_threshold_gap: `{keep_threshold_gap}`")
    if row.get("market_strength_supplement"):
        lines.append("source_hint: `market_strength_supplement`")
    return lines


def _entry_list_ticker_identity(row: dict[str, Any]) -> str:
    return normalize_a_share_ticker(row.get("ticker") or row.get("code") or row.get("symbol"))


def _dedupe_entry_list_rows(
    rows: list[dict[str, Any]],
    *,
    assigned_identities: set[str] | None = None,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen = assigned_identities if assigned_identities is not None else set()
    for row in rows:
        identity = _entry_list_ticker_identity(row)
        if not identity:
            deduped.append(row)
            continue
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped


def build_entry_list_screening(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    assigned_identities: set[str] = set()
    top_picks = _dedupe_entry_list_rows(
        [row for row in result.get("top_picks", []) if isinstance(row, dict)],
        assigned_identities=assigned_identities,
    )
    directly_actionable = _dedupe_entry_list_rows(
        [row for row in result.get("directly_actionable", []) if isinstance(row, dict)],
        assigned_identities=assigned_identities,
    )
    priority_watchlist = _dedupe_entry_list_rows(
        [row for row in result.get("priority_watchlist", []) if isinstance(row, dict)],
        assigned_identities=assigned_identities,
    )
    near_miss = _dedupe_entry_list_rows(
        [row for row in result.get("near_miss_candidates", []) if isinstance(row, dict)],
        assigned_identities=assigned_identities,
    )
    diagnostic = _dedupe_entry_list_rows(
        [row for row in result.get("diagnostic_scorecard", []) if isinstance(row, dict)],
        assigned_identities=assigned_identities,
    )

    entry_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_bucket, rows in (("top_picks", top_picks), ("directly_actionable", directly_actionable)):
        for row in rows:
            ticker = _entry_list_ticker_identity(row)
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            entry_candidates.append(_entry_list_candidate_summary(row, source_bucket=source_bucket))

    watchlist_candidates: list[dict[str, Any]] = []
    for row in priority_watchlist:
        ticker = _entry_list_ticker_identity(row)
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        summary = _entry_list_candidate_summary(row, source_bucket="priority_watchlist")
        summary["readiness_status"] = "needs_confirmation"
        watchlist_candidates.append(summary)

    if entry_candidates:
        status = "open"
        decision = "entry_list_allowed"
    elif watchlist_candidates:
        status = "watchlist_only"
        decision = "watchlist_requires_confirmation"
    else:
        status = "empty"
        decision = "no_entry_candidates_to_promote"

    return {
        "schema_version": "entry_list_screening/v1",
        "status": status,
        "decision": decision,
        "entry_candidate_count": len(entry_candidates),
        "watchlist_candidate_count": len(watchlist_candidates),
        "top_pick_count": len(top_picks),
        "directly_actionable_count": len(directly_actionable),
        "priority_watch_count": len(priority_watchlist),
        "near_miss_count": len(near_miss),
        "diagnostic_count": len(diagnostic),
        "entry_candidates": entry_candidates[:MAX_REPORTED_TOP_PICKS],
        "watchlist_candidates": watchlist_candidates[:MAX_REPORTED_TOP_PICKS],
    }


def build_entry_list_screening_markdown(screening: dict[str, Any]) -> list[str]:
    if not isinstance(screening, dict) or not screening:
        return []
    status = clean_text(screening.get("status")) or "empty"
    decision = clean_text(screening.get("decision")) or "no_entry_candidates_to_promote"
    lines = ["", "## Entry List Screening", ""]
    lines.append(f"- Status: `{status}`")
    lines.append(f"- Decision: `{decision}`")
    lines.append(
        "- Entry candidates: "
        f"`{screening.get('entry_candidate_count', 0)}` "
        f"(top_picks=`{screening.get('top_pick_count', 0)}`, "
        f"directly_actionable=`{screening.get('directly_actionable_count', 0)}`)"
    )
    lines.append(
        "- Observation backlog: "
        f"priority_watch=`{screening.get('priority_watch_count', 0)}`, "
        f"near_miss=`{screening.get('near_miss_count', 0)}`, "
        f"diagnostic=`{screening.get('diagnostic_count', 0)}`"
    )
    candidates = [row for row in screening.get("entry_candidates", []) if isinstance(row, dict)]
    watchlist_candidates = [row for row in screening.get("watchlist_candidates", []) if isinstance(row, dict)]
    if candidates:
        lines.append("- Candidates:")
        for row in candidates:
            ticker = clean_text(row.get("ticker")) or "unknown"
            name = clean_text(row.get("name")) or ticker
            source_bucket = clean_text(row.get("source_bucket")) or "entry_candidate"
            chain = clean_text(row.get("chain_name"))
            why_now = clean_text(row.get("why_now"))
            suffix = f" / `{chain}`" if chain else ""
            lines.append(f"  - `{ticker}` {name}: `{source_bucket}`{suffix}")
            if why_now:
                lines.append(f"    - why_now: {why_now}")
            for detail_line in _entry_list_candidate_detail_lines(row):
                if detail_line.startswith("why_now:"):
                    continue
                lines.append(f"    - {detail_line}")
    if watchlist_candidates:
        lines.append("- Watchlist-only candidates:")
        for row in watchlist_candidates:
            ticker = clean_text(row.get("ticker")) or "unknown"
            name = clean_text(row.get("name")) or ticker
            action = clean_text(row.get("action")) or "wait for confirmation"
            why_now = clean_text(row.get("why_now"))
            lines.append(f"  - `{ticker}` {name}: `{action}`")
            if why_now:
                lines.append(f"    - why_now: {why_now}")
            for detail_line in _entry_list_candidate_detail_lines(row):
                if detail_line.startswith("why_now:"):
                    continue
                lines.append(f"    - {detail_line}")
    if not candidates and not watchlist_candidates:
        lines.append("- Candidates: `0`; keep the output research/watch-only until a top-pick or directly-actionable name appears.")
    return lines


def build_market_strength_watch_trade_card(row: dict[str, Any]) -> dict[str, Any]:
    ticker = clean_text(row.get("ticker")) or "candidate"
    name = clean_text(row.get("name")) or ticker
    event_state = clean_text(safe_dict(row.get("event_state")).get("label")) or "unconfirmed"
    return {
        "watch_action": "wait_for_confirmation",
        "trigger": f"confirm follow-through for {ticker} {name}: hold above signal-day close/high with expanding turnover after {event_state} evidence improves",
        "invalidation": "fail confirmation, break below signal-day low, or lose market-strength/sector breadth support",
        "stop": "no live entry stop until trigger confirms; after confirmation use signal-day low or next-session failed-breakout low as stop reference",
        "position_sizing_guidance": "watchlist only; no position before confirmation; if promoted, use starter size only and cap initial risk at a small predefined R",
        "risk_flags": [
            "market_strength_scan",
            "unconfirmed_event_state",
            "watchlist_not_entry",
        ],
    }


def attach_market_strength_review_price_fields(
    event_cards: list[dict[str, Any]],
    market_strength_candidates: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    price_source_by_ticker: dict[str, dict[str, Any]] = {}
    for row in market_strength_candidates or []:
        if not isinstance(row, dict):
            continue
        ticker = normalize_a_share_ticker(row.get("ticker") or row.get("code") or row.get("symbol"))
        if ticker:
            price_source_by_ticker.setdefault(ticker, row)

    attached: list[dict[str, Any]] = []
    for row in event_cards:
        if not isinstance(row, dict):
            continue
        ticker = normalize_a_share_ticker(row.get("ticker") or row.get("code") or row.get("symbol"))
        source = price_source_by_ticker.get(ticker)
        if not source:
            attached.append(row)
            continue
        updated = dict(row)
        for key in MARKET_STRENGTH_REVIEW_PRICE_FIELDS:
            if updated.get(key) in (None, "") and source.get(key) not in (None, ""):
                updated[key] = source.get(key)
        attached.append(updated)
    return attached


def attach_market_strength_watch_trade_cards(event_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attached: list[dict[str, Any]] = []
    for row in event_cards:
        if not isinstance(row, dict):
            continue
        if row.get("market_strength_supplement") and not safe_dict(row.get("trade_card")):
            row = dict(row)
            row["trade_card"] = build_market_strength_watch_trade_card(row)
        attached.append(row)
    return attached


def build_dry_run_action_plan(result: dict[str, Any]) -> dict[str, Any]:
    screening = safe_dict(result.get("entry_list_screening"))
    if not screening:
        return {}
    entry_count = _coerce_positive_int(screening.get("entry_candidate_count"))
    watch_count = _coerce_positive_int(screening.get("watchlist_candidate_count"))
    if not entry_count and not watch_count:
        return {}
    status = "entry_candidates_pending_review" if entry_count else "watchlist_only"
    return {
        "schema_version": "dry_run_action_plan/v1",
        "status": status,
        "entry_candidate_count": entry_count,
        "watchlist_candidate_count": watch_count,
        "trigger_plan": "Promote only after next-session confirmation: sustained follow-through, expanding turnover, and no break of the signal-day low.",
        "invalidation_plan": "Keep research-only if confirmation fails, sector breadth fades, or the candidate breaks below the signal-day low.",
        "position_sizing_guidance": "Watchlist-only names carry zero position; after confirmation, use starter size and cap initial risk at a small predefined R.",
        "risk_flags": [
            "dry_run_only",
            "confirmation_required",
            "no_position_before_trigger",
        ],
    }


def merge_track_results(
    track_results: dict[str, dict[str, Any]],
    track_configs: dict[str, dict[str, Any]],
    *,
    discovery_candidates: list[dict[str, Any]] | None = None,
    discovery_context: dict[str, Any] | None = None,
    market_strength_candidates: list[dict[str, Any]] | None = None,
    setup_launch_candidates: list[dict[str, Any]] | None = None,
    all_assessed: list[dict[str, Any]] | None = None,
    out_of_scope_dropped: list[dict[str, Any]] | None = None,
    base_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge per-track enriched results into a single output dict.

    Produces a unified result with:
    - ``track_results``: the per-track enriched dicts (keyed by track name)
    - ``filter_summary``: merged summary with per-track breakdowns
    - ``diagnostic_scorecard``: combined from all tracks
    - ``dropped``: combined from all tracks + out-of-scope
    - ``top_picks``: combined from all tracks
    - ``report_markdown``: per-track sections + shared discovery section
    - Discovery / event-card enrichment applied once across all tracks
    """
    merged: dict[str, Any] = {}
    merged["track_results"] = track_results
    merged["request"] = base_request or {}
    request_obj = merged["request"] if isinstance(merged.get("request"), dict) else {}
    weekend_market_candidate_input = (
        request_obj.get("weekend_market_candidate_input")
        if isinstance(request_obj.get("weekend_market_candidate_input"), dict)
        else None
    )
    weekend_market_candidate, direction_reference_map = build_weekend_market_candidate(
        weekend_market_candidate_input
    )
    merged["weekend_market_candidate"] = weekend_market_candidate
    merged["direction_reference_map"] = direction_reference_map
    geopolitics_candidate_input = (
        request_obj.get("macro_geopolitics_candidate_input")
        if isinstance(request_obj.get("macro_geopolitics_candidate_input"), dict)
        else None
    )
    merged["macro_geopolitics_candidate"] = build_macro_geopolitics_candidate(
        geopolitics_candidate_input
    )
    if market_strength_candidates is None and isinstance(base_request, dict):
        market_strength_candidates = (
            base_request.get("market_strength_candidates")
            if isinstance(base_request.get("market_strength_candidates"), list)
            else []
        )
    if setup_launch_candidates is None and isinstance(base_request, dict):
        setup_launch_candidates = (
            base_request.get("setup_launch_candidates")
            if isinstance(base_request.get("setup_launch_candidates"), list)
            else []
        )
    merged["setup_launch_candidates"] = [
        item for item in (setup_launch_candidates or []) if isinstance(item, dict)
    ]
    emergent_theme_candidates, promoted_active_themes = build_emergent_theme_result_surfaces(
        request_obj,
        weekend_market_candidate=weekend_market_candidate,
        market_strength_candidates=market_strength_candidates,
        setup_launch_candidates=setup_launch_candidates,
    )
    merged["emergent_theme_candidates"] = emergent_theme_candidates
    merged["promoted_active_themes"] = promoted_active_themes
    merged["sector_views"] = normalize_sector_views(
        request_obj.get("sector_views") if isinstance(request_obj.get("sector_views"), list) else []
    )
    merged["sector_rankings"] = normalize_sector_rankings(
        request_obj.get("sector_rankings") if isinstance(request_obj.get("sector_rankings"), list) else []
    )

    # Combine top_picks, dropped, diagnostic_scorecard, near_miss, midday_action
    all_top_picks: list[dict[str, Any]] = []
    all_dropped: list[dict[str, Any]] = list(out_of_scope_dropped or [])
    all_diagnostic_scorecard: list[dict[str, Any]] = []
    all_near_miss: list[dict[str, Any]] = []
    all_midday_action: list[dict[str, Any]] = []
    combined_tier_output: dict[str, list[dict[str, Any]]] = {"T1": [], "T2": [], "T3": [], "T4": []}

    per_track_summary: dict[str, dict[str, Any]] = {}
    total_universe = 0
    total_kept = 0

    for track_name, enriched in track_results.items():
        cfg = track_configs.get(track_name, {})
        fs = enriched.get("filter_summary", {})
        track_top_picks = enriched.get("top_picks", []) if isinstance(enriched.get("top_picks"), list) else []
        track_dropped = enriched.get("dropped", []) if isinstance(enriched.get("dropped"), list) else []
        track_diagnostic = enriched.get("diagnostic_scorecard", []) if isinstance(enriched.get("diagnostic_scorecard"), list) else []
        universe_count = fs.get("universe_count")
        if universe_count in (None, ""):
            universe_count = len(track_diagnostic) + len(track_dropped)
        top_pick_count = fs.get("top_pick_count")
        if top_pick_count in (None, ""):
            top_pick_count = len(track_top_picks)
        kept_count = fs.get("kept_count")
        if kept_count in (None, ""):
            kept_count = len(track_top_picks)
        per_track_summary[track_name] = {
            "label": cfg.get("label", track_name),
            "keep_threshold": fs.get("keep_threshold"),
            "strict_top_pick_threshold": fs.get("strict_top_pick_threshold"),
            "universe_count": universe_count,
            "kept_count": kept_count,
            "top_pick_count": top_pick_count,
            "diagnostic_scorecard_count": fs.get("diagnostic_scorecard_count", 0),
            "near_miss_candidate_count": fs.get("near_miss_candidate_count", 0),
        }
        total_universe += int(universe_count or 0)
        total_kept += int(kept_count or 0)

        all_top_picks.extend(track_top_picks)
        all_dropped.extend(track_dropped)
        all_diagnostic_scorecard.extend(track_diagnostic)
        all_near_miss.extend(enriched.get("near_miss_candidates", []))
        all_midday_action.extend(enriched.get("midday_action_summary", []))

        tier_output = enriched.get("tier_output", {})
        for tier_name in combined_tier_output:
            combined_tier_output[tier_name].extend(tier_output.get(tier_name, []))

    merged["top_picks"] = all_top_picks
    merged["dropped"] = all_dropped
    merged["data_blocked_theme_confirmed"] = build_data_blocked_theme_confirmed_candidates(
        all_dropped,
        emergent_theme_candidates,
    )
    merged["diagnostic_scorecard"] = all_diagnostic_scorecard
    merged["near_miss_candidates"] = all_near_miss
    merged["midday_action_summary"] = all_midday_action
    combined_tier_output, merged_overflow = apply_total_rendered_cap(combined_tier_output)
    merged["tier_output"] = combined_tier_output
    merged["filter_summary"] = {
        "universe_count": total_universe,
        "kept_count": total_kept,
        "top_pick_count": len(all_top_picks),
        "per_track": per_track_summary,
        "total_rendered_cap": TOTAL_RENDERED_CAP,
        "merged_overflow_count": len(merged_overflow),
    }
    run_completeness = build_run_completeness_summary(
        request_obj,
        weekend_market_candidate=weekend_market_candidate,
        filter_summary=merged["filter_summary"],
    )
    merged["run_completeness"] = run_completeness

    # --- Discovery / event-card enrichment (shared across tracks) ---
    all_assessed_combined = list(all_assessed or [])
    auto_discovery_candidates = build_auto_discovery_candidates(all_assessed_combined)
    supplement_rows = build_market_strength_discovery_candidates(market_strength_candidates or [])
    discovery_rows = build_discovery_candidates(
        merge_discovery_candidate_inputs(list(discovery_candidates or []) + supplement_rows, auto_discovery_candidates)
    )
    if discovery_rows:
        event_cards = enrich_event_cards_with_chain_context(build_event_cards(discovery_rows), discovery_context)
        for row in event_cards:
            if clean_text(row.get("primary_event_type")) == "market_strength_scan":
                row["market_strength_supplement"] = True
        event_cards = attach_market_strength_review_price_fields(event_cards, market_strength_candidates)
        event_cards = attach_market_strength_watch_trade_cards(event_cards)
        merged["event_cards"] = event_cards
        merged["discovery_lane_summary"] = build_discovery_lane_summary(event_cards)
        merged["chain_map_entries"] = build_chain_map_entries(event_cards, discovery_context)
        merged["directly_actionable"] = [row for row in event_cards if row.get("discovery_bucket") == "qualified"][:MAX_REPORTED_TOP_PICKS]
        merged["priority_watchlist"] = [row for row in event_cards if row.get("discovery_bucket") == "watch"][:MAX_REPORTED_NEAR_MISS]
        merged["chain_tracking"] = [row for row in event_cards if row.get("discovery_bucket") not in {"qualified", "watch"}][:MAX_REPORTED_BLOCKED]

    merged["entry_list_screening"] = build_entry_list_screening(merged)
    dry_run_action_plan = build_dry_run_action_plan(merged)
    if dry_run_action_plan:
        merged["dry_run_action_plan"] = dry_run_action_plan

    # Decision factors & flow (across all tracks)
    decision_factors = build_decision_factors_from_result(merged)
    decision_flow: list[dict[str, Any]] = []
    if any(decision_factors.values()):
        merged["decision_factors"] = decision_factors
        decision_flow = build_decision_flow(merged)
        merged["decision_flow"] = decision_flow

    # --- Report markdown ---
    request_obj = base_request or {}
    target_date = clean_text(request_obj.get("target_date") or request_obj.get("analysis_time") or "")
    profile = clean_text(request_obj.get("filter_profile") or "")
    header_lines = [
        f"# Month-End Shortlist Report: {target_date}",
        "",
        f"- Template: `{clean_text(request_obj.get('template_name') or 'month_end_shortlist')}`",
        f"- Filter profile: `{profile}`",
        f"- Total universe: `{total_universe}`",
        f"- Total kept: `{total_kept}`",
    ]
    for track_name, summary in per_track_summary.items():
        header_lines.append(f"- {summary['label']}: universe=`{summary['universe_count']}` kept=`{summary['kept_count']}` keep_threshold=`{summary['keep_threshold']}`")

    report_lines = header_lines
    report_lines.extend(build_entry_list_screening_markdown(merged.get("entry_list_screening")))

    sector_view_lines = build_sector_views_markdown(merged.get("sector_views"))
    if sector_view_lines:
        report_lines.extend(sector_view_lines)

    # Per-track sections
    for track_name in track_configs:
        enriched = track_results.get(track_name)
        if not enriched:
            continue
        cfg = track_configs[track_name]
        report_lines.append("")
        report_lines.extend(_build_track_report_section(track_name, cfg, enriched))

    # Out-of-scope dropped
    if out_of_scope_dropped:
        report_lines.extend(["", "## Out-of-Scope Dropped", ""])
        for item in out_of_scope_dropped:
            ticker = clean_text(item.get("ticker")) or "unknown"
            name = clean_text(item.get("name")) or ticker
            reason = clean_text(item.get("drop_reason")) or "outside_track_scope"
            report_lines.append(f"- `{ticker}` {name}: `{reason}`")

    # Shared discovery sections
    weekend_candidate = merged.get("weekend_market_candidate") if isinstance(merged.get("weekend_market_candidate"), dict) else None
    direction_reference_map = merged.get("direction_reference_map") if isinstance(merged.get("direction_reference_map"), list) else None
    weekend_lines = build_weekend_market_candidate_markdown(weekend_candidate, direction_reference_map)
    if weekend_lines:
        report_lines.extend(weekend_lines)

    directly_actionable = merged.get("directly_actionable", [])
    if isinstance(directly_actionable, list) and directly_actionable:
        report_lines.extend(["", "## 直接可执行", ""])
        for item in directly_actionable:
            supplement_label = " `市场强势补充`" if item.get("market_strength_supplement") else ""
            report_lines.append(f"- `{item.get('ticker')}` {item.get('name')}{supplement_label}")
            report_lines.append(f"  - 事件: `{item.get('event_type')}`")
            report_lines.append(f"  - 事件状态: `{item.get('event_state', {}).get('label')}`")
            report_lines.append(f"  - 链条: `{item.get('chain_name')}` / `{item.get('chain_role')}`")

    priority_watchlist = merged.get("priority_watchlist", [])
    if isinstance(priority_watchlist, list) and priority_watchlist:
        report_lines.extend(["", "## 重点观察", ""])
        for item in priority_watchlist:
            confidence = item.get("rumor_confidence_range", {})
            supplement_label = " `市场强势补充`" if item.get("market_strength_supplement") else ""
            report_lines.append(f"- `{item.get('ticker')}` {item.get('name')}{supplement_label}")
            report_lines.append(f"  - 事件: `{item.get('event_type')}`")
            report_lines.append(f"  - 事件状态: `{item.get('event_state', {}).get('label')}`")
            report_lines.append(f"  - 可信度区间: `{confidence.get('label')}` `{confidence.get('range')}`")

    chain_tracking = merged.get("chain_tracking", [])
    if isinstance(chain_tracking, list) and chain_tracking:
        report_lines.extend(["", "## 链条跟踪", ""])
        for item in chain_tracking:
            supplement_label = " `市场强势补充`" if item.get("market_strength_supplement") else ""
            report_lines.append(f"- `{item.get('ticker')}` {item.get('name')}{supplement_label}: `{item.get('chain_name')}` / `{item.get('chain_role')}`")

    if decision_flow:
        geopolitics_overlay = request_obj.get("macro_geopolitics_overlay") if isinstance(request_obj.get("macro_geopolitics_overlay"), dict) else None
        geopolitics_candidate = merged.get("macro_geopolitics_candidate") if isinstance(merged.get("macro_geopolitics_candidate"), dict) else None
        report_lines.extend(build_decision_flow_markdown(decision_flow, geopolitics_overlay, geopolitics_candidate))

    setup_launch_lines = build_setup_launch_markdown(
        merged.get("setup_launch_candidates")
        if isinstance(merged.get("setup_launch_candidates"), list)
        else None
    )
    if setup_launch_lines:
        report_lines.extend(setup_launch_lines)
    emergent_theme_lines = build_emergent_theme_markdown(
        merged.get("emergent_theme_candidates")
        if isinstance(merged.get("emergent_theme_candidates"), list)
        else None
    )
    if emergent_theme_lines:
        report_lines.extend(emergent_theme_lines)
    data_blocked_theme_lines = build_data_blocked_theme_confirmed_markdown(
        merged.get("data_blocked_theme_confirmed")
        if isinstance(merged.get("data_blocked_theme_confirmed"), list)
        else None
    )
    if data_blocked_theme_lines:
        report_lines.extend(data_blocked_theme_lines)

    event_cards = merged.get("event_cards", [])
    if isinstance(event_cards, list) and event_cards:
        report_lines.extend(["", "## Event Cards", ""])
        for item in event_cards:
            report_lines.append(f"- `{item.get('ticker')}` {item.get('name')}")
            report_lines.append(f"  - 阶段: `{item.get('event_phase')}`")
            report_lines.append(f"  - 预期判断: `{item.get('expectation_verdict')}`")
            report_lines.append(f"  - {item.get('trading_profile_judgment')}")
            report_lines.append(f"  - {item.get('trading_profile_usage')}")
            metrics = item.get("headline_metrics") if isinstance(item.get("headline_metrics"), list) else []
            if metrics:
                report_lines.append(f"  - 关键数据: `{', '.join(metrics[:4])}`")
            report_lines.append(f"  - primary_event_type: `{item.get('primary_event_type')}`")
            report_lines.append(f"  - event_state: `{item.get('event_state', {}).get('label')}`")
            report_lines.append(f"  - trading_usability: `{item.get('trading_usability', {}).get('label')}`")

    report_markdown = prepend_report_metadata_lines(
        "\n".join(report_lines).strip(),
        build_run_completeness_report_lines(run_completeness),
    )
    merged["report_markdown"] = annotate_ticker_names_in_markdown(report_markdown, merged)
    return merged


def wrap_assess_candidate_with_bars_failure_fallback(
    base_assess_candidate: AssessCandidate,
    failure_log: list[dict[str, Any]] | None = None,
    assessed_log: list[dict[str, Any]] | None = None,
) -> AssessCandidate:
    def wrapped(
        candidate: dict[str, Any],
        request: dict[str, Any],
        benchmark_rows: list[dict[str, Any]],
        *,
        bars_fetcher: Any,
        html_fetcher: Any,
    ) -> dict[str, Any]:
        try:
            assessed = base_assess_candidate(
                candidate,
                request,
                benchmark_rows,
                bars_fetcher=bars_fetcher,
                html_fetcher=html_fetcher,
            )
            if assessed_log is not None:
                assessed_log.append(deepcopy(assessed))
            return assessed
        except Exception as exc:
            if "bars_fetch_failed" in str(exc):
                target_date = clean_text(request.get("analysis_time") or request.get("target_date"))[:10]
                target_dt = parse_date(target_date)
                if target_dt:
                    start_date = (target_dt - timedelta(days=420)).isoformat()
                    cached_rows = eastmoney_cached_bars_for_candidate(
                        clean_text(candidate.get("ticker")),
                        start_date,
                        target_date,
                    )
                    recovery = choose_eastmoney_cache_recovery_mode(cached_rows, target_date)
                    if recovery.get("mode") == "fresh_cache":
                        def cached_bars_fetcher(ticker: str, inner_start: str, inner_end: str):
                            if clean_text(ticker) == clean_text(candidate.get("ticker")):
                                return list(recovery.get("rows") or [])
                            return bars_fetcher(ticker, inner_start, inner_end)

                        try:
                            assessed = base_assess_candidate(
                                candidate,
                                request,
                                benchmark_rows,
                                bars_fetcher=cached_bars_fetcher,
                                html_fetcher=html_fetcher,
                            )
                            assessed["bars_source"] = "eastmoney_cache"
                            assessed["execution_state"] = "fresh_cache"
                            if assessed_log is not None:
                                assessed_log.append(deepcopy(assessed))
                            return assessed
                        except Exception:
                            pass
                failed = build_bars_fetch_failed_candidate(candidate, exc)
                if failure_log is not None:
                    failure_log.append(deepcopy(failed))
                if assessed_log is not None:
                    assessed_log.append(deepcopy(failed))
                return failed
            raise

    return wrapped


default_bars_fetcher = wrap_bars_fetcher_with_benchmark_fallback(_compiled.default_bars_fetcher)


def run_month_end_shortlist(
    raw_payload: dict[str, Any],
    *,
    universe_fetcher: Any = _compiled.default_universe_fetcher,
    market_strength_universe_fetcher: Any | None = None,
    sector_rankings_fetcher: Any | None = None,
    bars_fetcher: Any = default_bars_fetcher,
    html_fetcher: Any = _compiled.fetch_html,
) -> dict[str, Any]:
    """Multi-track month-end shortlist pipeline.

    1. Normalize and prepare the request (shared).
    2. Split the universe by board into independent tracks.
    3. Run the compiled core + per-track enrichment for each track.
    4. Merge track results with shared discovery/event enrichment.
    """
    failure_log: list[dict[str, Any]] = []
    assessed_log: list[dict[str, Any]] = []
    original_assess_candidate = _compiled.assess_candidate
    original_normalize_request = _compiled.normalize_request
    _compiled.assess_candidate = wrap_assess_candidate_with_bars_failure_fallback(
        original_assess_candidate,
        failure_log,
        assessed_log,
    )
    _compiled.normalize_request = lambda payload: normalize_request_with_compiled(payload, original_normalize_request)
    try:
        safe_bars = wrap_bars_fetcher_with_benchmark_fallback(bars_fetcher)
        prepared_payload = prepare_request_with_candidate_snapshots(
            normalize_request_with_compiled(raw_payload, original_normalize_request),
            bars_fetcher=safe_bars,
        )
        discovery_candidates = deepcopy(prepared_payload.get("event_discovery_candidates") or [])
        discovery_context = deepcopy(prepared_payload.get("x_discovery_context") or {})
        request_market_strength = deepcopy(prepared_payload.get("market_strength_candidates") or [])
        request_setup_launch = deepcopy(prepared_payload.get("setup_launch_candidates") or [])
        weekend_market_candidate_input = (
            prepared_payload.get("weekend_market_candidate_input")
            if isinstance(prepared_payload.get("weekend_market_candidate_input"), dict)
            else None
        )
        prepared_weekend_market_candidate, prepared_direction_ref_map = build_weekend_market_candidate(
            weekend_market_candidate_input
        )
        base_active_setup_themes = resolve_setup_launch_theme_pool(
            prepared_payload,
            prepared_weekend_market_candidate,
        )

        # --- Fetch full universe once, then split by board ---
        universe_fetch_error = ""
        try:
            full_universe = universe_fetcher(prepared_payload)
        except Exception as exc:
            universe_fetch_error = clean_text(exc) or exc.__class__.__name__
            full_universe = []
        if prepared_direction_ref_map:
            prepared_direction_ref_map = cross_check_direction_tickers(prepared_direction_ref_map, full_universe)
        request_tickers = {clean_text(row.get("ticker")) for row in request_market_strength if clean_text(row.get("ticker"))}
        request_tickers.update(
            clean_text(row.get("ticker"))
            for row in request_setup_launch
            if clean_text(row.get("ticker"))
        )
        event_tickers = {clean_text(row.get("ticker")) for row in discovery_candidates if clean_text(row.get("ticker"))}
        existing_tickers = request_tickers | event_tickers
        effective_market_strength_fetcher = market_strength_universe_fetcher
        if effective_market_strength_fetcher is None:
            effective_market_strength_fetcher = (
                default_market_strength_universe_fetcher
                if universe_fetcher is _compiled.default_universe_fetcher
                else universe_fetcher
            )
        market_strength_fetch_error = ""
        try:
            market_strength_universe = effective_market_strength_fetcher(prepared_payload)
        except Exception as exc:
            market_strength_fetch_error = clean_text(exc) or exc.__class__.__name__
            market_strength_universe = []
        request_sector_rankings = deepcopy(prepared_payload.get("sector_rankings") or [])
        request_sector_views = deepcopy(prepared_payload.get("sector_views") or [])
        effective_sector_rankings_fetcher = sector_rankings_fetcher
        if effective_sector_rankings_fetcher is None and is_fresh_discovery_required(prepared_payload):
            effective_sector_rankings_fetcher = (
                default_sector_rankings_fetcher
                if universe_fetcher is _compiled.default_universe_fetcher
                else None
            )
        fetched_sector_rankings: list[dict[str, Any]] = []
        sector_rank_fetch_error = ""
        if effective_sector_rankings_fetcher is not None:
            try:
                fetched_sector_rankings = effective_sector_rankings_fetcher(prepared_payload)
            except Exception as exc:
                sector_rank_fetch_error = clean_text(exc) or exc.__class__.__name__
                fetched_sector_rankings = []
        sector_rankings = normalize_sector_rankings(
            [
                row
                for row in list(request_sector_rankings or []) + list(fetched_sector_rankings or [])
                if isinstance(row, dict)
            ]
        )
        ranking_sector_views = build_sector_views_from_rankings(sector_rankings)
        sector_views = merge_sector_view_inputs(
            [row for row in request_sector_views if isinstance(row, dict)],
            ranking_sector_views,
        )
        sector_views = enrich_sector_views_with_universe_breadth(sector_views, market_strength_universe)
        if sector_rankings:
            prepared_payload["sector_rankings"] = sector_rankings
        if sector_views:
            prepared_payload["sector_views"] = sector_views
        generated_market_strength = build_market_strength_candidates_from_universe(
            market_strength_universe,
            existing_tickers=existing_tickers,
            max_names=10,
            sector_views=sector_views,
        )
        market_strength_candidates = merge_market_strength_candidate_inputs(
            request_market_strength,
            generated_market_strength,
        )
        fresh_discovery_coverage = build_fresh_discovery_coverage(
            prepared_payload,
            market_strength_universe=market_strength_universe,
            request_market_strength_candidates=request_market_strength,
            generated_market_strength_candidates=generated_market_strength,
            universe_fetch_error=universe_fetch_error,
            market_strength_fetch_error=market_strength_fetch_error,
            sector_rankings=sector_rankings,
            sector_views=sector_views,
            sector_rank_fetch_error=sector_rank_fetch_error,
        )
        preliminary_emergent_theme_candidates = build_emergent_theme_candidates_from_runtime_inputs(
            prepared_payload,
            weekend_market_candidate=prepared_weekend_market_candidate,
            market_strength_candidates=market_strength_candidates,
            setup_launch_candidates=request_setup_launch,
        )
        active_setup_themes = merge_promoted_emergent_themes_into_active_pool(
            base_active_setup_themes,
            preliminary_emergent_theme_candidates,
        )
        setup_launch_candidates = merge_setup_launch_candidate_inputs(
            request_setup_launch,
            build_setup_launch_candidates_from_universe(
                full_universe,
                active_themes=active_setup_themes,
                existing_tickers=existing_tickers,
                max_names=SETUP_LAUNCH_MAX_NAMES,
            ),
        )
        board_to_track: dict[str, str] = {}
        for tn, cfg in TRACK_CONFIGS.items():
            for bv in cfg.get("board_values", ()):
                board_to_track[bv] = tn

        track_universes: dict[str, list[dict[str, Any]]] = {tn: [] for tn in TRACK_CONFIGS}
        out_of_scope: list[dict[str, Any]] = []
        for candidate in full_universe:
            ticker = str(candidate.get("ticker") or candidate.get("f12") or "").strip()
            board = _compiled.classify_board(ticker)
            tn = board_to_track.get(board)
            if tn:
                track_universes[tn].append(candidate)
            else:
                out_of_scope.append({
                    "ticker": ticker,
                    "name": str(candidate.get("name") or candidate.get("f14") or ticker),
                    "board": board,
                    "drop_reason": "outside_track_scope",
                })

        # --- Run each track independently ---
        track_results: dict[str, dict[str, Any]] = {}
        all_assessed: list[dict[str, Any]] = []
        for track_name, track_cfg in TRACK_CONFIGS.items():
            track_universe = track_universes[track_name]
            # Build a frozen universe_fetcher that returns only this track's candidates
            def make_track_fetcher(candidates: list[dict[str, Any]]):
                def fetcher(request: dict[str, Any]) -> list[dict[str, Any]]:
                    return candidates
                return fetcher

            # Build per-track payload with track-specific thresholds
            track_payload = deepcopy(prepared_payload)
            track_payload["keep_threshold"] = track_cfg["keep_threshold"]
            track_payload["strict_top_pick_threshold"] = track_cfg["strict_top_pick_threshold"]
            profile_settings = dict(track_payload.get("profile_settings") or {})
            profile_settings["keep_threshold"] = track_cfg["keep_threshold"]
            profile_settings["strict_top_pick_threshold"] = track_cfg["strict_top_pick_threshold"]
            track_payload["profile_settings"] = profile_settings
            # Tag so monkey-patched normalize_request applies track-specific thresholds
            track_payload["_track_name"] = track_name
            track_payload["_track_config"] = track_cfg

            # Each track gets its own failure/assessed logs
            track_failure_log: list[dict[str, Any]] = []
            track_assessed_log: list[dict[str, Any]] = []
            _compiled.assess_candidate = wrap_assess_candidate_with_bars_failure_fallback(
                original_assess_candidate,
                track_failure_log,
                track_assessed_log,
            )
            result = _compiled.run_month_end_shortlist(
                track_payload,
                universe_fetcher=make_track_fetcher(track_universe),
                bars_fetcher=safe_bars,
                html_fetcher=html_fetcher,
            )
            enriched = enrich_track_result(
                result,
                track_failure_log,
                track_assessed_log,
                track_name=track_name,
                track_config=track_cfg,
                direction_reference_map=prepared_direction_ref_map if prepared_direction_ref_map else None,
                weekend_market_candidate=prepared_weekend_market_candidate,
                geopolitics_overlay=prepared_payload.get("macro_geopolitics_overlay"),
            )
            track_results[track_name] = enriched
            all_assessed.extend(track_assessed_log)

        merged = merge_track_results(
            track_results,
            TRACK_CONFIGS,
            discovery_candidates=discovery_candidates,
            discovery_context=discovery_context,
            market_strength_candidates=market_strength_candidates,
            setup_launch_candidates=setup_launch_candidates,
            all_assessed=all_assessed,
            out_of_scope_dropped=out_of_scope,
            base_request=prepared_payload,
        )
        merged = attach_fresh_discovery_coverage(merged, fresh_discovery_coverage)
        merged = attach_cache_baseline_metadata(merged, all_assessed)
        if isinstance(merged.get("decision_factors"), dict) and any(merged.get("decision_factors", {}).values()):
            merged["decision_flow"] = build_decision_flow(merged)
        merged["x_risk_alerts"] = list(prepared_payload.get("x_risk_alerts") or [])
        return merged
    finally:
        _compiled.assess_candidate = original_assess_candidate
        _compiled.normalize_request = original_normalize_request


def build_market_regime_overlay_markdown(
    sentiment_overlay: dict[str, Any] | None = None,
    cross_market_overlay: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(sentiment_overlay, dict) and not isinstance(cross_market_overlay, dict):
        return []

    lines = ["", "## Market Regime Overlay", ""]
    if isinstance(sentiment_overlay, dict):
        sentiment_regime = clean_text(sentiment_overlay.get("sentiment_regime")) or "n/a"
        posture = clean_text(sentiment_overlay.get("positioning_posture")) or "n/a"
        lines.append(f"- A-share sentiment regime: `{sentiment_regime}`")
        lines.append(f"- Positioning posture: `{posture}`")
        takeaway = clean_text(sentiment_overlay.get("takeaway"))
        if takeaway:
            lines.append(f"- A-share takeaway: {takeaway}")

    if isinstance(cross_market_overlay, dict):
        regime = clean_text(cross_market_overlay.get("regime_label")) or "n/a"
        confidence = clean_text(cross_market_overlay.get("confidence"))
        lines.append(f"- US reference regime: `{regime}`" + (f" / `{confidence}`" if confidence else ""))
        focus_chains = ", ".join(unique_strings(cross_market_overlay.get("focus_chains") or []))
        mapped_themes = ", ".join(unique_strings(cross_market_overlay.get("mapped_a_share_themes") or []))
        if focus_chains:
            lines.append(f"- US focus chains: `{focus_chains}`")
        if mapped_themes:
            lines.append(f"- A-share mapped themes: `{mapped_themes}`")
        validation_note = clean_text(cross_market_overlay.get("validation_note"))
        if validation_note:
            lines.append(f"- Validation: {validation_note}")

    lines.append("- Boundary: advisory only; not a hard filter or direct buy/sell signal.")
    return lines


def default_build_macro_health_overlay_result(request: dict[str, Any]) -> dict[str, Any]:
    from macro_health_overlay_runtime import build_macro_health_overlay_result

    return build_macro_health_overlay_result(request)


def build_default_macro_health_request(raw_payload: dict[str, Any], normalized_request: dict[str, Any]) -> dict[str, Any]:
    if DEFAULT_MACRO_HEALTH_REQUEST_PATH.exists():
        request = load_json(DEFAULT_MACRO_HEALTH_REQUEST_PATH)
    else:
        request = {"live_data_provider": "public_macro_mix"}
    request = deepcopy(request)
    target_date = clean_text(raw_payload.get("target_date") or normalized_request.get("target_date") or normalized_request.get("as_of"))
    analysis_time = clean_text(raw_payload.get("analysis_time") or normalized_request.get("analysis_time"))
    if target_date:
        request["as_of"] = target_date[:10]
    if analysis_time:
        request["analysis_time"] = analysis_time
    request["integration_mode"] = "advisory_only"
    request.setdefault("seed_snapshot_path", str(DEFAULT_MACRO_HEALTH_SEED_CACHE_PATH))
    request.setdefault("seed_fill_mode", "missing_only")
    request.setdefault("write_live_seed_cache", True)
    request["evidence"] = unique_strings(
        [
            *safe_list(request.get("evidence")),
            "Auto-attached macro_health_overlay for the trading-plan macro analysis lane.",
        ]
    )
    return request


def apply_default_macro_health_overlay(
    raw_payload: dict[str, Any],
    normalized_request: dict[str, Any],
    *,
    enabled: bool = False,
    builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    request = deepcopy(normalized_request)
    existing_overlay = safe_dict(raw_payload.get("macro_health_overlay")) or safe_dict(normalized_request.get("macro_health_overlay"))
    if existing_overlay:
        request["macro_health_overlay"] = existing_overlay
        return request
    if not enabled or raw_payload.get("auto_macro_health_overlay") is False:
        request.pop("macro_health_overlay", None)
        return request
    overlay_builder = builder or default_build_macro_health_overlay_result
    try:
        overlay_result = overlay_builder(build_default_macro_health_request(raw_payload, request))
    except Exception as exc:  # pragma: no cover
        request["macro_health_overlay_error"] = clean_text(exc) or exc.__class__.__name__
        return request
    overlay = safe_dict(safe_dict(overlay_result).get("macro_health_overlay"))
    if overlay:
        request["macro_health_overlay"] = overlay
    live_fetch_summary = safe_dict(safe_dict(overlay_result).get("live_fetch_summary"))
    if live_fetch_summary:
        request["macro_health_overlay_live_fetch_summary"] = live_fetch_summary
    seed_summary = safe_dict(safe_dict(overlay_result).get("seed_summary"))
    if seed_summary:
        request["macro_health_overlay_seed_summary"] = seed_summary
    return request


def build_macro_health_overlay_markdown(
    overlay: dict[str, Any] | None = None,
    *,
    live_fetch_summary: dict[str, Any] | None = None,
    seed_summary: dict[str, Any] | None = None,
) -> list[str]:
    overlay = safe_dict(overlay)
    if not overlay:
        return []
    lines = ["", "## Macro Health Overlay", ""]
    health_label = clean_text(overlay.get("health_label"))
    risk_posture = clean_text(overlay.get("risk_posture"))
    window_state = clean_text(overlay.get("window_state"))
    if health_label:
        summary = f"- Health label: `{health_label}`"
        if risk_posture:
            summary += f" / posture `{risk_posture}`"
        if window_state:
            summary += f" / window `{window_state}`"
        lines.append(summary)
    liquidity_signal = clean_text(overlay.get("liquidity_signal"))
    if liquidity_signal:
        lines.append(f"- Liquidity signal: `{liquidity_signal}`")
    liquidity_plumbing_signal = clean_text(overlay.get("liquidity_plumbing_signal"))
    if liquidity_plumbing_signal:
        lines.append(f"- Liquidity plumbing: `{liquidity_plumbing_signal}`")
    takeaway = clean_text(overlay.get("takeaway"))
    if takeaway:
        lines.append(f"- Takeaway: {takeaway}")
    live_fetch = safe_dict(live_fetch_summary)
    provider = clean_text(live_fetch.get("provider"))
    status = clean_text(live_fetch.get("status"))
    fetched = ", ".join(clean_text(item) for item in safe_list(live_fetch.get("fetched")) if clean_text(item))
    warnings = "; ".join(clean_text(item) for item in safe_list(live_fetch.get("warnings")) if clean_text(item))
    if provider or status:
        lines.append("")
        lines.append("### Live Data")
        lines.append("")
        lines.append(f"- Provider: `{provider or 'n/a'}`")
        lines.append(f"- Status: `{status or 'n/a'}`")
    if fetched:
        lines.append(f"- Fetched layers: `{fetched}`")
    if warnings:
        lines.append(f"- Warnings: `{warnings}`")
    seed = safe_dict(seed_summary)
    seed_path = clean_text(seed.get("path"))
    if seed_path or seed.get("loaded") or seed.get("used") or seed.get("written"):
        lines.append(
            f"- Seed cache: path=`{seed_path or 'n/a'}` loaded=`{bool(seed.get('loaded'))}` used=`{bool(seed.get('used'))}` written=`{bool(seed.get('written'))}` fill_mode=`{clean_text(seed.get('fill_mode')) or 'n/a'}`"
        )
    liquidity_monitor = safe_dict(overlay.get("liquidity_monitor"))
    if liquidity_monitor:
        lines.extend(
            [
                "",
                "### Liquidity Monitor",
                "",
                "| Metric | Latest | Change |",
                "| --- | --- | --- |",
                f"| reserve_balances_bil | `{clean_text(liquidity_monitor.get('reserve_balances_latest_bil')) or 'n/a'}` | `{clean_text(liquidity_monitor.get('reserve_balances_change_bil_20d')) or 'n/a'}` |",
                f"| rrp_bil | `{clean_text(liquidity_monitor.get('rrp_latest_bil')) or 'n/a'}` | `{clean_text(liquidity_monitor.get('rrp_change_bil_20d')) or 'n/a'}` |",
                f"| tga_bil | `{clean_text(liquidity_monitor.get('tga_latest_bil')) or 'n/a'}` | `{clean_text(liquidity_monitor.get('tga_change_bil_20d')) or 'n/a'}` |",
                f"| reserve_rrp_tga_total_bil | `{clean_text(liquidity_monitor.get('reserve_rrp_tga_total_bil')) or 'n/a'}` | `{clean_text(liquidity_monitor.get('reserve_rrp_tga_total_change_bil_20d')) or 'n/a'}` |",
                f"| reserve_balances_change_bil_1d | `{clean_text(liquidity_monitor.get('reserve_balances_change_bil_1d')) or 'n/a'}` | `n/a` |",
                f"| rrp_change_bil_1d | `{clean_text(liquidity_monitor.get('rrp_change_bil_1d')) or 'n/a'}` | `n/a` |",
                f"| reserve_rrp_tga_total_change_bil_1d | `{clean_text(liquidity_monitor.get('reserve_rrp_tga_total_change_bil_1d')) or 'n/a'}` | `n/a` |",
                f"| sofr | `{clean_text(liquidity_monitor.get('sofr_latest')) or 'n/a'}` | `n/a` |",
                f"| sofr_change_bp_1d | `{clean_text(liquidity_monitor.get('sofr_change_bp_1d')) or 'n/a'}` | `n/a` |",
                f"| iorb | `{clean_text(liquidity_monitor.get('iorb_latest')) or 'n/a'}` | `{clean_text(liquidity_monitor.get('iorb_change_bp_20d')) or 'n/a'}` |",
                f"| iorb_change_bp_1d | `{clean_text(liquidity_monitor.get('iorb_change_bp_1d')) or 'n/a'}` | `n/a` |",
                f"| sofr_iorb_spread_bp | `{clean_text(liquidity_monitor.get('sofr_iorb_spread_bp')) or 'n/a'}` | `n/a` |",
                f"| sofr_iorb_ratio | `{clean_text(liquidity_monitor.get('sofr_iorb_ratio')) or 'n/a'}` | `n/a` |",
                f"| (sofr-iorb)/sofr_pct | `{clean_text(liquidity_monitor.get('sofr_minus_iorb_over_sofr_pct')) or 'n/a'}` | `n/a` |",
                f"| reserve_balances_date | `{clean_text(liquidity_monitor.get('reserve_balances_latest_date')) or 'n/a'}` | `n/a` |",
                f"| rrp_date | `{clean_text(liquidity_monitor.get('rrp_latest_date')) or 'n/a'}` | `n/a` |",
                f"| tga_date | `{clean_text(liquidity_monitor.get('tga_latest_date')) or 'n/a'}` | `n/a` |",
                f"| sofr_date | `{clean_text(liquidity_monitor.get('sofr_latest_date')) or 'n/a'}` | `n/a` |",
                f"| iorb_date | `{clean_text(liquidity_monitor.get('iorb_latest_date')) or 'n/a'}` | `n/a` |",
            ]
        )
        note = clean_text(liquidity_monitor.get("note"))
        if note:
            lines.append(f"- Note: `{note}`")
        source_rows = [
            safe_dict(row)
            for row in safe_list(liquidity_monitor.get("sources"))
            if isinstance(row, dict) and clean_text(row.get("label"))
        ]
        if source_rows:
            source_text = "; ".join(
                (
                    f"{clean_text(row.get('label'))} ({clean_text(row.get('url'))})"
                    if clean_text(row.get("url"))
                    else clean_text(row.get("label"))
                )
                for row in source_rows
            )
            lines.append(f"- Sources: `{source_text}`")
    return lines


def build_markdown_report(result: dict[str, Any]) -> str:
    if callable(_ORIGINAL_BUILD_MARKDOWN_REPORT):
        report = str(_ORIGINAL_BUILD_MARKDOWN_REPORT(result))
    else:
        report = str(result.get("report_markdown") or "")
    if not isinstance(result, dict):
        return report

    entry_list_lines = build_entry_list_screening_markdown(result.get("entry_list_screening"))
    if entry_list_lines and "## Entry List Screening" not in report:
        report = report.rstrip() + "\n" + "\n".join(entry_list_lines).rstrip() + "\n"

    request_obj = result.get("request") if isinstance(result.get("request"), dict) else {}
    sentiment_overlay = (
        result.get("sentiment_vol_overlay")
        if isinstance(result.get("sentiment_vol_overlay"), dict)
        else request_obj.get("sentiment_vol_overlay") if isinstance(request_obj.get("sentiment_vol_overlay"), dict) else None
    )
    cross_market_overlay = (
        result.get("cross_market_reference_overlay")
        if isinstance(result.get("cross_market_reference_overlay"), dict)
        else request_obj.get("cross_market_reference_overlay") if isinstance(request_obj.get("cross_market_reference_overlay"), dict) else None
    )
    overlay_lines = build_market_regime_overlay_markdown(sentiment_overlay, cross_market_overlay)
    if overlay_lines and "## Market Regime Overlay" not in report:
        report = report.rstrip() + "\n" + "\n".join(overlay_lines).rstrip() + "\n"
    macro_health_overlay = (
        result.get("macro_health_overlay")
        if isinstance(result.get("macro_health_overlay"), dict)
        else request_obj.get("macro_health_overlay") if isinstance(request_obj.get("macro_health_overlay"), dict) else None
    )
    macro_live_fetch_summary = (
        result.get("macro_health_overlay_live_fetch_summary")
        if isinstance(result.get("macro_health_overlay_live_fetch_summary"), dict)
        else request_obj.get("macro_health_overlay_live_fetch_summary") if isinstance(request_obj.get("macro_health_overlay_live_fetch_summary"), dict) else None
    )
    macro_seed_summary = (
        result.get("macro_health_overlay_seed_summary")
        if isinstance(result.get("macro_health_overlay_seed_summary"), dict)
        else request_obj.get("macro_health_overlay_seed_summary") if isinstance(request_obj.get("macro_health_overlay_seed_summary"), dict) else None
    )
    macro_lines = build_macro_health_overlay_markdown(
        macro_health_overlay,
        live_fetch_summary=macro_live_fetch_summary,
        seed_summary=macro_seed_summary,
    )
    if macro_lines and "## Macro Health Overlay" not in report:
        report = report.rstrip() + "\n" + "\n".join(macro_lines).rstrip() + "\n"
    return report


_compiled.build_markdown_report = build_markdown_report
_compiled.build_market_regime_overlay_markdown = build_market_regime_overlay_markdown

if "__all__" not in globals():
    __all__ = [name for name in dir(_compiled) if not name.startswith("_")]

for _extra in (
    "BENCHMARK_TICKERS",
    "SECTOR_RANK_LIMIT",
    "SECTOR_RANK_INDUSTRY_GROUP",
    "SECTOR_RANK_CONCEPT_GROUP",
    "SECTOR_RANK_FIELDS",
    "DEFAULT_STRATEGIC_BASE_WATCH_THEMES",
    "load_json",
    "write_json",
    "wrap_bars_fetcher_with_benchmark_fallback",
    "build_bars_fetch_failed_candidate",
    "infer_execution_state",
    "last_bar_date_from_rows",
    "classify_eastmoney_cache_freshness",
    "choose_eastmoney_cache_recovery_mode",
    "build_bars_cache_rescue_candidate",
    "eastmoney_cached_bars_for_candidate",
    "eastmoney_cached_intraday_bars_for_candidate",
    "last_cached_trade_date_from_row_sets",
    "resolve_cache_baseline_metadata",
    "attach_cache_baseline_metadata",
    "enrich_degraded_live_result",
    "render_blocked_candidates_section",
    "replace_blocked_candidates_section",
    "prune_rescued_blocked_candidates",
    "build_bars_source_summary",
    "enrich_live_result_reporting",
    "build_diagnostic_scorecard_entry",
    "apply_board_threshold_overrides",
    "BOARD_THRESHOLD_OVERRIDES",
    "build_near_miss_candidates",
    "classify_midday_status",
    "intraday_confirmation_gate",
    "review_based_priority_boost",
    "build_midday_action_summary",
    "build_midday_action_summary_from_top_picks",
    "build_midday_action_summary_from_result",
    "build_decision_factor_entry",
    "build_decision_factors_from_result",
    "build_upgrade_trigger",
    "build_downgrade_trigger",
    "build_event_risk_trigger",
    "build_decision_flow_card",
    "build_decision_flow",
    "build_decision_flow_markdown",
    "build_market_regime_overlay_markdown",
    "build_entry_list_screening",
    "build_entry_list_screening_markdown",
    "build_market_strength_watch_trade_card",
    "attach_market_strength_watch_trade_cards",
    "build_dry_run_action_plan",
    "classify_sector_breadth_signal",
    "normalize_sector_rank_row",
    "normalize_sector_rankings",
    "normalize_sector_view",
    "normalize_sector_views",
    "merge_sector_view_inputs",
    "build_sector_views_from_rankings",
    "enrich_sector_views_with_universe_breadth",
    "build_sector_views_markdown",
    "build_markdown_report",
    "build_weekend_market_candidate_markdown",
    "midday_action_for_status",
    "prepare_request_with_candidate_snapshots",
    "wrap_assess_candidate_with_bars_failure_fallback",
    "local_market_snapshot_for_candidate",
    "classify_fallback_support_reason",
    "snapshot_allows_fallback_observation",
    "build_bars_fallback_rescue_candidate",
    "TRACK_CONFIGS",
    "split_universe_by_board",
    "enrich_track_result",
    "merge_track_results",
    "normalize_market_strength_candidate",
    "normalize_setup_launch_candidate",
    "resolve_setup_launch_theme_pool",
    "classify_structure_repair",
    "classify_volume_return",
    "classify_rs_improvement",
    "classify_distance_from_bottom_state",
    "is_setup_launch_excluded",
    "setup_launch_score",
    "build_setup_launch_candidates_from_universe",
    "merge_setup_launch_candidate_inputs",
    "EMERGENT_THEME_PROMOTION_THRESHOLD",
    "normalize_emergent_theme_candidate",
    "classify_emergent_signal_strength",
    "classify_emergent_signal_breadth",
    "classify_emergent_signal_consensus",
    "emergent_theme_promotion_score",
    "should_promote_emergent_theme",
    "build_emergent_theme_candidates_from_runtime_inputs",
    "build_run_completeness_summary",
    "build_run_completeness_report_lines",
    "merge_promoted_emergent_themes_into_active_pool",
    "build_emergent_theme_result_surfaces",
    "build_setup_launch_markdown",
    "build_market_strength_discovery_candidates",
    "is_market_strength_excluded",
    "market_strength_score",
    "normalize_market_strength_universe_ticker",
    "build_market_strength_candidates_from_universe",
    "merge_market_strength_candidate_inputs",
    "is_fresh_discovery_required",
    "build_fresh_discovery_coverage",
    "build_fresh_discovery_coverage_markdown",
    "attach_fresh_discovery_coverage",
    "tabular_records",
    "first_present_value",
    "a_share_ticker_from_code",
    "request_limit",
    "default_akshare_market_strength_universe_fetcher",
    "normalize_akshare_sector_rank_rows",
    "default_akshare_sector_rankings_fetcher",
    "fetch_sina_market_center_rows",
    "sina_ticker_from_row",
    "normalize_sina_market_center_rows",
    "default_sina_market_strength_universe_fetcher",
    "default_sina_sector_rankings_fetcher",
    "default_market_strength_universe_fetcher",
    "default_sector_rankings_fetcher",
    "cross_check_direction_tickers",
    "direction_alignment_boost",
    "direction_tier_promotion",
):
    if _extra not in __all__:
        __all__.append(_extra)
