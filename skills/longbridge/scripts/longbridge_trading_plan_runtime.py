#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


PLAN_SCHEMA_VERSION = "longbridge_trading_plan/v1"
REVIEW_SCHEMA_VERSION = "longbridge_trading_plan_review/v1"
VALID_SESSION_TYPES = {"premarket", "intraday", "postclose"}
EVIDENCE_LAYER_KEYS = (
    "account_review_plus",
    "execution_preflight",
    "derivative_event_risk",
    "hk_microstructure",
    "governance_structure",
)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"), strict=False)
    return payload if isinstance(payload, dict) else {}


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_session_type(value: str | None) -> str:
    session_type = clean_text(value).lower() or "premarket"
    return session_type if session_type in VALID_SESSION_TYPES else "premarket"


def _candidate_symbol(candidate: dict[str, Any]) -> str:
    return clean_text(candidate.get("symbol") or candidate.get("ticker") or candidate.get("code"))


def _candidate_name(candidate: dict[str, Any]) -> str:
    return clean_text(candidate.get("name") or candidate.get("company_name") or _candidate_symbol(candidate))


def _add_symbol_name_aliases(lookup: dict[str, str], symbol: str, name: str) -> None:
    normalized_symbol = clean_text(symbol)
    normalized_name = clean_text(name)
    if not normalized_symbol or not normalized_name or normalized_name == normalized_symbol:
        return
    lookup.setdefault(normalized_symbol, normalized_name)
    if normalized_symbol.endswith(".SH"):
        lookup.setdefault(normalized_symbol[:-3] + ".SS", normalized_name)
    elif normalized_symbol.endswith(".SS"):
        lookup.setdefault(normalized_symbol[:-3] + ".SH", normalized_name)
    if len(normalized_symbol) >= 6 and normalized_symbol[:6].isdigit():
        lookup.setdefault(normalized_symbol[:6], normalized_name)


def _symbol_name_lookup(value: Any) -> dict[str, str]:
    lookup: dict[str, str] = {}

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            symbol = clean_text(item.get("symbol") or item.get("ticker") or item.get("code"))
            name = clean_text(
                item.get("name")
                or item.get("company_name")
                or item.get("resolved_name")
                or item.get("stock_name")
                or item.get("symbol_name")
            )
            _add_symbol_name_aliases(lookup, symbol, name)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return lookup


def _display_symbol(symbol: str, lookup: dict[str, str]) -> str:
    normalized_symbol = clean_text(symbol)
    if not normalized_symbol:
        return "`unknown`"
    name = lookup.get(normalized_symbol) or lookup.get(normalized_symbol[:6])
    return f"`{normalized_symbol}` {name}" if name else f"`{normalized_symbol}`"


def _score_block(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "screen_score": candidate.get("screen_score"),
        "workbench_score": candidate.get("workbench_score"),
        "technical_score": candidate.get("technical_score"),
        "catalyst_score": candidate.get("catalyst_score"),
        "valuation_score": candidate.get("valuation_score"),
    }


def _level_block(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "last_close": candidate.get("last_close") or candidate.get("close"),
        "trigger_price": candidate.get("trigger_price"),
        "stop_loss": candidate.get("stop_loss"),
        "abandon_below": candidate.get("abandon_below"),
        "volume_ratio_20": candidate.get("volume_ratio_20"),
    }


def _candidate_risk_flags(candidate: dict[str, Any]) -> list[str]:
    qualitative = candidate.get("qualitative_evaluation") if isinstance(candidate.get("qualitative_evaluation"), dict) else {}
    risks = qualitative.get("key_risks") if isinstance(qualitative.get("key_risks"), list) else []
    return [clean_text(item) for item in risks if clean_text(item)]


def _position_guidance(candidate: dict[str, Any]) -> dict[str, Any]:
    signal = clean_text(candidate.get("signal")).lower()
    score = to_float(candidate.get("workbench_score")) or to_float(candidate.get("screen_score")) or 0.0
    if signal == "momentum_breakout" and score >= 50:
        sizing = "0% before trigger; 5%-10% pilot after trigger and confirmation; max 15%."
    elif score >= 30:
        sizing = "0% before trigger; 5%-10% pilot only after price, volume, and intraday confirmation."
    else:
        sizing = "0% default; watch-only unless the next session produces a fresh trigger and confirmation."
    return {
        "symbol": _candidate_symbol(candidate),
        "name": _candidate_name(candidate),
        "guidance": sizing,
        "account_write_allowed": False,
        "order_allowed": False,
    }


def _force_dry_run_action_plan(plan: Any) -> dict[str, Any]:
    if isinstance(plan, dict):
        cleaned = deepcopy(plan)
    else:
        cleaned = {"status": "dry_run", "actions": []}
    cleaned["should_apply"] = False
    cleaned["side_effects"] = "none"
    actions = cleaned.get("actions") if isinstance(cleaned.get("actions"), list) else []
    for action in actions:
        if isinstance(action, dict):
            action["should_apply"] = False
            action["side_effects"] = "none"
    return cleaned


def _monitor_by_symbol(intraday_monitor_result: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(intraday_monitor_result, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in intraday_monitor_result.get("monitored_symbols") or []:
        if not isinstance(item, dict):
            continue
        symbol = _candidate_symbol(item)
        if symbol:
            result[symbol] = item
    return result


def _intraday_confirmation(symbol: str, monitor: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    item = monitor.get(symbol)
    if not item:
        return None
    capital_flow = item.get("capital_flow") if isinstance(item.get("capital_flow"), dict) else {}
    abnormal_volume = item.get("abnormal_volume") if isinstance(item.get("abnormal_volume"), dict) else {}
    plan_status = item.get("plan_status") if isinstance(item.get("plan_status"), dict) else {}
    return {
        "latest_price": item.get("latest_price"),
        "plan_status": deepcopy(plan_status),
        "capital_flow_confirms": bool(capital_flow.get("confirms")),
        "abnormal_volume_exists": bool(abnormal_volume.get("exists")),
        "trade_stats": deepcopy(item.get("trade_stats") if isinstance(item.get("trade_stats"), dict) else {}),
        "upgrade_ready": bool(plan_status.get("triggered")) and bool(capital_flow.get("confirms")),
        "should_apply": False,
        "side_effects": "none",
    }


def _market_context(
    screen_result: dict[str, Any],
    *,
    market_context: dict[str, Any] | None,
    intraday_monitor_result: dict[str, Any] | None,
) -> dict[str, Any]:
    context = deepcopy(market_context) if isinstance(market_context, dict) else {}
    context.setdefault("source", "longbridge-screen")
    context.setdefault("analysis_layers", screen_result.get("analysis_layers") or [])
    context.setdefault("summary", deepcopy(screen_result.get("summary") if isinstance(screen_result.get("summary"), dict) else {}))
    if isinstance(intraday_monitor_result, dict):
        monitored = [
            _candidate_symbol(item)
            for item in intraday_monitor_result.get("monitored_symbols") or []
            if isinstance(item, dict) and _candidate_symbol(item)
        ]
        context["intraday_symbols"] = monitored
        context["intraday_risk_flags"] = deepcopy(intraday_monitor_result.get("risk_flags") or [])
        context["intraday_side_effects"] = intraday_monitor_result.get("side_effects", "none")
    return context


def _build_candidate_entry(
    candidate: dict[str, Any],
    *,
    rank: int,
    monitor: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    symbol = _candidate_symbol(candidate)
    qualitative = candidate.get("qualitative_evaluation") if isinstance(candidate.get("qualitative_evaluation"), dict) else {}
    for key in EVIDENCE_LAYER_KEYS:
        value = candidate.get(key)
        if isinstance(value, dict):
            qualitative[key] = deepcopy(value)
    entry = {
        "rank": rank,
        "symbol": symbol,
        "name": _candidate_name(candidate),
        "signal": clean_text(candidate.get("signal")),
        "scores": _score_block(candidate),
        "levels": _level_block(candidate),
        "tracking_bucket": clean_text((candidate.get("tracking_plan") or {}).get("suggested_watchlist_bucket"))
        if isinstance(candidate.get("tracking_plan"), dict)
        else "",
        "qualitative_evidence": deepcopy(qualitative),
        "risk_flags": _candidate_risk_flags(candidate),
        "should_apply": False,
        "side_effects": "none",
    }
    for key in EVIDENCE_LAYER_KEYS:
        value = candidate.get(key)
        if isinstance(value, dict):
            entry[key] = deepcopy(value)
    confirmation = _intraday_confirmation(symbol, monitor)
    if confirmation:
        entry["intraday_confirmation"] = confirmation
    return entry


def _build_trigger_plan(candidate_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = []
    for item in candidate_entries:
        levels = item.get("levels") if isinstance(item.get("levels"), dict) else {}
        plan.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "trigger_price": levels.get("trigger_price"),
                "upgrade_conditions": [
                    "price_at_or_above_trigger",
                    "volume_expansion_or_abnormal_volume",
                    "capital_flow_confirms",
                    "theme_or_sector_confirmation",
                ],
                "confirmation_sources": [
                    "longbridge intraday",
                    "longbridge capital",
                    "longbridge anomaly",
                    "longbridge trade-stats",
                ],
                "should_apply": False,
                "side_effects": "none",
            }
        )
    return plan


def _build_invalidation_plan(candidate_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = []
    for item in candidate_entries:
        levels = item.get("levels") if isinstance(item.get("levels"), dict) else {}
        plan.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "stop_loss": levels.get("stop_loss"),
                "abandon_below": levels.get("abandon_below"),
                "abandon_conditions": [
                    "price_below_abandon_below",
                    "stop_loss_hit",
                    "trigger_rejected_with_volume",
                    "missing_intraday_confirmation_after_open_window",
                ],
                "should_apply": False,
                "side_effects": "none",
            }
        )
    return plan


def build_trading_plan_report(
    screen_result: dict[str, Any],
    *,
    session_type: str = "premarket",
    plan_date: str | None = None,
    market_context: dict[str, Any] | None = None,
    intraday_monitor_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a reusable Longbridge trading-plan handoff report.

    The function is a pure transformer: it does not call Longbridge, mutate
    watchlists or alerts, submit orders, or run DCA.
    """
    normalized_session = normalize_session_type(session_type)
    request = screen_result.get("request") if isinstance(screen_result.get("request"), dict) else {}
    report_date = clean_text(plan_date) or clean_text(screen_result.get("analysis_date")) or clean_text(request.get("analysis_date"))
    monitor = _monitor_by_symbol(intraday_monitor_result)
    raw_candidates = [item for item in screen_result.get("ranked_candidates") or [] if isinstance(item, dict)]
    candidates = [
        _build_candidate_entry(candidate, rank=index + 1, monitor=monitor)
        for index, candidate in enumerate(raw_candidates)
    ]
    qualitative_evidence = [
        {
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "qualitative_evidence": deepcopy(item.get("qualitative_evidence") or {}),
        }
        for item in candidates
    ]
    missed = deepcopy(screen_result.get("missed_attention_priorities") or screen_result.get("key_omissions") or [])
    risk_flags = sorted(
        {
            clean_text(flag)
            for item in candidates
            for flag in (item.get("risk_flags") or [])
            if clean_text(flag)
        }
        | {
            clean_text(item.get("issue"))
            for item in missed
            if isinstance(item, dict) and clean_text(item.get("issue"))
        }
    )
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_date": report_date,
        "session_type": normalized_session,
        "market_context": _market_context(
            screen_result,
            market_context=market_context,
            intraday_monitor_result=intraday_monitor_result,
        ),
        "candidates": candidates,
        "trigger_plan": _build_trigger_plan(candidates),
        "invalidation_plan": _build_invalidation_plan(candidates),
        "position_sizing_guidance": {
            "base_rule": "No position before trigger and confirmation; use the listed percent ranges as plan capital, not full account exposure.",
            "per_candidate": [_position_guidance(candidate) for candidate in raw_candidates],
            "account_write_allowed": False,
            "order_allowed": False,
        },
        "qualitative_evidence": qualitative_evidence,
        "risk_flags": risk_flags,
        "missed_attention_priorities": missed,
        "dry_run_action_plan": _force_dry_run_action_plan(screen_result.get("dry_run_action_plan")),
        "review_checklist": [
            "candidate_pool_current",
            "trigger_price_confirmed",
            "stop_loss_confirmed",
            "abandon_price_confirmed",
            "capital_flow_confirms",
            "anomaly_or_volume_confirms",
            "trade_stats_confirms",
            "risk_flags_rechecked",
            "dry_run_action_plan_still_side_effect_free",
        ],
        "handoff": {
            "next_session_inputs": [
                "longbridge-screen result JSON",
                "longbridge-intraday-monitor result JSON",
                "postclose actual price JSON",
            ],
            "postclose_helper": "build_postclose_review",
        },
        "should_apply": False,
        "side_effects": "none",
    }


def _actual_prices_by_symbol(actuals: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw: Any = actuals.get("prices")
    if raw is None:
        raw = actuals.get("actual_prices") or actuals.get("candidates") or actuals.get("items")
    if raw is None and all(isinstance(value, dict) for value in actuals.values()):
        raw = actuals
    if isinstance(raw, dict):
        return {clean_text(symbol): value for symbol, value in raw.items() if clean_text(symbol) and isinstance(value, dict)}
    if isinstance(raw, list):
        result: dict[str, dict[str, Any]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            symbol = _candidate_symbol(item)
            if symbol:
                result[symbol] = item
        return result
    return {}


def _review_status(levels: dict[str, Any], actual: dict[str, Any] | None) -> dict[str, Any]:
    trigger = to_float(levels.get("trigger_price"))
    stop = to_float(levels.get("stop_loss"))
    abandon = to_float(levels.get("abandon_below"))
    if not actual:
        return {
            "review_status": "no_actual_data",
            "hit_trigger": False,
            "failed_trigger": False,
            "stopped": False,
            "still_valid": False,
            "invalidated": False,
            "misread_reason": "No actual post-close price data was supplied.",
            "next_session_adjustment": "rerun_with_postclose_actuals",
        }
    high = to_float(actual.get("high") or actual.get("day_high"))
    low = to_float(actual.get("low") or actual.get("day_low"))
    close = to_float(actual.get("close") or actual.get("last") or actual.get("last_price"))
    trigger_touched = high is not None and trigger is not None and high >= trigger
    stopped = low is not None and stop is not None and low <= stop
    abandon_hit = (
        (low is not None and abandon is not None and low <= abandon)
        or (close is not None and abandon is not None and close <= abandon)
    )
    invalidated = stopped or abandon_hit
    failed_trigger = trigger_touched and close is not None and trigger is not None and close < trigger and not stopped
    if stopped:
        status = "stopped"
        reason = "Stop loss or abandon zone was touched after the plan was active or watchlisted."
        adjustment = "downgrade_or_abandon; require a new reclaim above trigger before next escalation."
    elif abandon_hit:
        status = "invalidated"
        reason = "Price traded below the abandon boundary."
        adjustment = "abandon for next session unless price reclaims the trigger with confirmation."
    elif failed_trigger:
        status = "failed_trigger"
        reason = "Intraday high reached trigger, but close failed to hold above trigger."
        adjustment = "downgrade; next plan needs reclaim plus capital-flow confirmation."
    elif trigger_touched:
        status = "hit_trigger"
        reason = "Trigger was reached and close held above trigger."
        adjustment = "carry forward; tighten next-session stop around trigger or confirmed pullback support."
    else:
        status = "still_valid"
        reason = "No trigger and no invalidation; setup remains conditional."
        adjustment = "keep on watch; rerun intraday monitor next open session."
    return {
        "review_status": status,
        "hit_trigger": status == "hit_trigger",
        "failed_trigger": status == "failed_trigger",
        "stopped": stopped,
        "still_valid": status == "still_valid",
        "invalidated": invalidated,
        "trigger_touched": trigger_touched,
        "misread_reason": reason,
        "next_session_adjustment": adjustment,
    }


def build_postclose_review(
    plan_report: dict[str, Any],
    actuals: dict[str, Any],
    *,
    review_date: str | None = None,
) -> dict[str, Any]:
    prices = _actual_prices_by_symbol(actuals)
    actual_review_date = clean_text(review_date) or clean_text(actuals.get("review_date") or actuals.get("trade_date"))
    rows: list[dict[str, Any]] = []
    summary = {
        "total_reviewed": 0,
        "hit_trigger": 0,
        "failed_trigger": 0,
        "stopped": 0,
        "still_valid": 0,
        "invalidated": 0,
        "no_actual_data": 0,
    }
    for candidate in plan_report.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        symbol = _candidate_symbol(candidate)
        levels = candidate.get("levels") if isinstance(candidate.get("levels"), dict) else {}
        actual = prices.get(symbol)
        status = _review_status(levels, actual)
        row = {
            "symbol": symbol,
            "name": _candidate_name(candidate),
            "levels": deepcopy(levels),
            "actual": deepcopy(actual or {}),
            **status,
            "should_apply": False,
            "side_effects": "none",
        }
        rows.append(row)
        summary["total_reviewed"] += 1
        summary[row["review_status"]] = summary.get(row["review_status"], 0) + 1
        if row["invalidated"] and row["review_status"] != "invalidated":
            summary["invalidated"] += 1
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "plan_date": plan_report.get("plan_date"),
        "review_date": actual_review_date,
        "session_type": "postclose",
        "market_context": deepcopy(plan_report.get("market_context") or {}),
        "candidates_reviewed": rows,
        "summary": summary,
        "next_session_adjustment": [
            {"symbol": row["symbol"], "adjustment": row["next_session_adjustment"]}
            for row in rows
        ],
        "should_apply": False,
        "side_effects": "none",
    }


def build_trading_plan_markdown(report: dict[str, Any]) -> str:
    name_lookup = _symbol_name_lookup(report)
    lines = [
        "# Longbridge Trading Plan",
        "",
        f"- schema_version: `{clean_text(report.get('schema_version'))}`",
        f"- plan_date: `{clean_text(report.get('plan_date'))}`",
        f"- session_type: `{clean_text(report.get('session_type'))}`",
        f"- should_apply: `{str(bool(report.get('should_apply'))).lower()}`",
        f"- side_effects: `{clean_text(report.get('side_effects'))}`",
        "",
    ]
    symbol_rows = []
    seen_symbols = set()
    for item in report.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        symbol = clean_text(item.get("symbol"))
        name = clean_text(item.get("name")) or name_lookup.get(symbol) or name_lookup.get(symbol[:6])
        if symbol and name and name != symbol and symbol not in seen_symbols:
            symbol_rows.append((symbol, name))
            seen_symbols.add(symbol)
    if symbol_rows:
        lines.extend(
            [
                "## Symbol Name Map",
                "",
                "| Symbol | Name |",
                "|---|---|",
            ]
        )
        for symbol, name in symbol_rows:
            lines.append(f"| `{symbol}` | {name} |")
        lines.append("")
    lines.extend(
        [
        "## Candidates",
        "",
        "| Rank | Symbol | Name | Signal | Score | Trigger | Stop | Abandon |",
        "|---:|---|---|---|---:|---:|---:|---:|",
    ]
    )
    for item in report.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        levels = item.get("levels") if isinstance(item.get("levels"), dict) else {}
        scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        score = scores.get("workbench_score") or scores.get("screen_score")
        symbol = clean_text(item.get("symbol"))
        name = clean_text(item.get("name")) or name_lookup.get(symbol) or name_lookup.get(symbol[:6])
        lines.append(
            f"| {item.get('rank')} | `{symbol}` | {name} | {clean_text(item.get('signal'))} | "
            f"{score} | {levels.get('trigger_price')} | {levels.get('stop_loss')} | {levels.get('abandon_below')} |"
        )
    lines.extend(["", "## Trigger Plan", ""])
    for item in report.get("trigger_plan") or []:
        if isinstance(item, dict):
            lines.append(
                f"- {_display_symbol(clean_text(item.get('symbol')), name_lookup)} trigger `{item.get('trigger_price')}`; "
                f"conditions: {', '.join(item.get('upgrade_conditions') or [])}"
            )
    lines.extend(["", "## Invalidation Plan", ""])
    for item in report.get("invalidation_plan") or []:
        if isinstance(item, dict):
            lines.append(
                f"- {_display_symbol(clean_text(item.get('symbol')), name_lookup)} stop `{item.get('stop_loss')}`, "
                f"abandon `{item.get('abandon_below')}`"
            )
    lines.extend(["", "## Position Sizing", ""])
    sizing = report.get("position_sizing_guidance") if isinstance(report.get("position_sizing_guidance"), dict) else {}
    lines.append(f"- base_rule: {clean_text(sizing.get('base_rule'))}")
    for item in sizing.get("per_candidate") or []:
        if isinstance(item, dict):
            lines.append(f"- {_display_symbol(clean_text(item.get('symbol')), name_lookup)}: {clean_text(item.get('guidance'))}")
    lines.extend(["", "## Missed Attention Priorities", ""])
    for item in report.get("missed_attention_priorities") or []:
        if isinstance(item, dict):
            lines.append(f"- {clean_text(item.get('priority'))} `{clean_text(item.get('issue'))}`: {clean_text(item.get('follow_up_action'))}")
    lines.extend(["", "## Dry-run Action Plan", ""])
    dry_run = report.get("dry_run_action_plan") if isinstance(report.get("dry_run_action_plan"), dict) else {}
    lines.append(f"- should_apply: `{str(bool(dry_run.get('should_apply'))).lower()}`")
    lines.append(f"- side_effects: `{clean_text(dry_run.get('side_effects'))}`")
    for action in (dry_run.get("actions") or [])[:12]:
        if isinstance(action, dict):
            lines.append(
                f"- {clean_text(action.get('operation'))} {_display_symbol(clean_text(action.get('symbol')), name_lookup)} "
                f"should_apply=`{str(bool(action.get('should_apply'))).lower()}`"
            )
    lines.extend(["", "## Review Checklist", ""])
    for item in report.get("review_checklist") or []:
        lines.append(f"- [ ] {clean_text(item)}")
    return "\n".join(lines).rstrip() + "\n"


def build_postclose_review_markdown(review: dict[str, Any]) -> str:
    name_lookup = _symbol_name_lookup(review)
    lines = [
        "# Longbridge Post-Close Review",
        "",
        f"- schema_version: `{clean_text(review.get('schema_version'))}`",
        f"- plan_date: `{clean_text(review.get('plan_date'))}`",
        f"- review_date: `{clean_text(review.get('review_date'))}`",
        f"- should_apply: `{str(bool(review.get('should_apply'))).lower()}`",
        f"- side_effects: `{clean_text(review.get('side_effects'))}`",
        "",
        "## Review Results",
        "",
        "| Symbol | Name | Status | Trigger | Stop | Abandon | Close | Adjustment |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in review.get("candidates_reviewed") or []:
        if not isinstance(item, dict):
            continue
        levels = item.get("levels") if isinstance(item.get("levels"), dict) else {}
        actual = item.get("actual") if isinstance(item.get("actual"), dict) else {}
        close = actual.get("close") or actual.get("last") or actual.get("last_price")
        symbol = clean_text(item.get("symbol"))
        name = clean_text(item.get("name")) or name_lookup.get(symbol) or name_lookup.get(symbol[:6])
        lines.append(
            f"| `{symbol}` | {name} | {clean_text(item.get('review_status'))} | "
            f"{levels.get('trigger_price')} | {levels.get('stop_loss')} | {levels.get('abandon_below')} | "
            f"{close} | {clean_text(item.get('next_session_adjustment'))} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build standardized Longbridge trading-plan and postclose-review artifacts.")
    parser.add_argument("--screen-result", help="Path to longbridge-screen result JSON.")
    parser.add_argument("--plan-json", help="Path to an existing standardized trading-plan JSON.")
    parser.add_argument("--intraday-result", help="Optional longbridge-intraday-monitor result JSON.")
    parser.add_argument("--actuals", help="Optional postclose actual price JSON.")
    parser.add_argument("--session-type", default="premarket", choices=sorted(VALID_SESSION_TYPES))
    parser.add_argument("--plan-date", default=None)
    parser.add_argument("--output", help="Write JSON output to this path.")
    parser.add_argument("--markdown-output", help="Write Markdown output to this path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    intraday = load_json(Path(args.intraday_result)) if args.intraday_result else None
    if args.plan_json:
        plan = load_json(Path(args.plan_json))
    elif args.screen_result:
        plan = build_trading_plan_report(
            load_json(Path(args.screen_result)),
            session_type=args.session_type,
            plan_date=args.plan_date,
            intraday_monitor_result=intraday,
        )
    else:
        raise SystemExit("--screen-result or --plan-json is required")

    if args.session_type == "postclose":
        actuals = load_json(Path(args.actuals)) if args.actuals else {}
        output = build_postclose_review(plan, actuals)
        markdown = build_postclose_review_markdown(output)
    else:
        output = plan
        markdown = build_trading_plan_markdown(plan)

    payload = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    if args.markdown_output:
        Path(args.markdown_output).write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
