#!/usr/bin/env python3
"""Automated postclose review runtime.

Reads a shortlist result.json, fetches intraday bars, classifies plan outcomes,
and produces structured adjustments + markdown report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TRADINGAGENTS_SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / "tradingagents-decision-bridge"
    / "scripts"
)
if str(TRADINGAGENTS_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(TRADINGAGENTS_SCRIPT_DIR))


QUALIFIED_ACTION_ALIASES = {"qualified", "execute", "entry", "entry_allowed", "buy", "actionable"}
SKIP_ACTION_ALIASES = {
    "watch",
    "observe",
    "skip",
    "blocked",
    "no_action",
    "wait_for_confirmation",
    "needs_confirmation",
    "watchlist_only",
}


def _action_key(value: Any) -> str:
    return str(value or "").strip().lower()


def classify_plan_outcome(*, plan_action: str, actual_return_pct: float) -> str:
    """Classify a single candidate's plan-vs-actual outcome.

    Args:
        plan_action: The midday action from the shortlist run.
            '可执行' = qualified, '继续观察' = watch/near_miss, '不执行' = blocked.
        actual_return_pct: The actual day return in percent (e.g. -1.46 for -1.46%).

    Returns one of: 'plan_correct', 'plan_too_aggressive', 'missed_opportunity',
    'plan_correct_negative'.
    """
    is_qualified = plan_action == "可执行"
    is_skip = plan_action in ("继续观察", "不执行")
    normalized_action = _action_key(plan_action)
    is_qualified = is_qualified or normalized_action in QUALIFIED_ACTION_ALIASES
    is_skip = is_skip or normalized_action in SKIP_ACTION_ALIASES

    if is_qualified:
        if actual_return_pct < -1.0:
            return "plan_too_aggressive"
        return "plan_correct"

    if is_skip:
        if actual_return_pct > 2.0:
            return "missed_opportunity"
        return "plan_correct_negative"

    # Fallback for unknown actions
    return "plan_correct_negative"


def generate_adjustment(judgment: str) -> dict[str, Any]:
    """Generate a priority adjustment dict from a plan outcome judgment.

    Returns dict with keys: adjustment, priority_delta, gate_next_run.
    """
    if judgment == "plan_too_aggressive":
        return {"adjustment": "downgrade", "priority_delta": -5, "gate_next_run": True}
    if judgment == "missed_opportunity":
        return {"adjustment": "upgrade", "priority_delta": 5, "gate_next_run": False}
    return {"adjustment": "hold", "priority_delta": 0, "gate_next_run": False}


def _fetch_intraday_bars_for_review(ticker: str, trade_date: str) -> list[dict[str, Any]]:
    """Fetch intraday bars for review — delegates to month_end_shortlist_runtime's cached wrapper."""
    try:
        from month_end_shortlist_runtime import eastmoney_cached_intraday_bars_for_candidate
        return eastmoney_cached_intraday_bars_for_candidate(ticker, trade_date)
    except ImportError:
        return []


def _normalize_review_candidate(candidate: dict[str, Any], *, midday_action: str | None = None) -> dict[str, Any]:
    """Normalize shortlist output into the shape expected by the review pass."""
    normalized = dict(candidate)
    action = (midday_action or normalized.get("midday_action") or "").strip()
    if not action:
        status = (normalized.get("midday_status") or "").strip().lower()
        if status == "blocked":
            action = "不执行"
        elif status == "qualified":
            action = "可执行"
        elif status:
            action = "继续观察"
    if not action:
        readiness = _action_key(normalized.get("readiness_status"))
        source_bucket = _action_key(normalized.get("source_bucket"))
        discovery_bucket = _action_key(normalized.get("discovery_bucket"))
        trade_card = normalized.get("trade_card") if isinstance(normalized.get("trade_card"), dict) else {}
        watch_action = _action_key(trade_card.get("watch_action"))
        if (
            readiness in {"needs_confirmation", "watchlist_only"}
            or source_bucket in {"priority_watchlist", "watchlist_candidates"}
            or discovery_bucket == "watch"
            or watch_action in SKIP_ACTION_ALIASES
            or normalized.get("market_strength_supplement") is True
        ):
            action = "watch"
    if action:
        normalized["midday_action"] = action

    if normalized.get("close") in (None, "") and normalized.get("price") not in (None, ""):
        normalized["close"] = normalized.get("price")
    if normalized.get("prev_close") in (None, "") and normalized.get("pre_close") not in (None, ""):
        normalized["prev_close"] = normalized.get("pre_close")
    return normalized


def _normalize_review_ticker_identity(value: Any) -> str:
    """Return a stable identity for review de-duplication without rewriting output."""
    ticker = str(value or "").strip().upper()
    if not ticker:
        return ""
    if ticker.endswith(".SS"):
        return ticker[:-3] + ".SH"
    if ticker.endswith((".SH", ".SZ", ".BJ")):
        return ticker
    digits = "".join(ch for ch in ticker if ch.isdigit())
    if len(digits) == 6:
        if digits.startswith(("6", "9")):
            return f"{digits}.SH"
        if digits.startswith(("4", "8")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"
    return ticker


def _candidate_has_return_inputs(candidate: dict[str, Any]) -> bool:
    return (
        candidate.get("close") not in (None, "")
        and candidate.get("prev_close") not in (None, "")
    )


def _merge_duplicate_review_candidate(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if value in (None, ""):
            continue
        if merged.get(key) in (None, ""):
            merged[key] = value

    if not _candidate_has_return_inputs(merged) and _candidate_has_return_inputs(incoming):
        for key in ("close", "prev_close", "price", "pre_close"):
            value = incoming.get(key)
            if value not in (None, ""):
                merged[key] = value
    return merged


def _dedupe_review_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for candidate in candidates:
        identity = _normalize_review_ticker_identity(candidate.get("ticker") or candidate.get("symbol") or candidate.get("code"))
        if not identity:
            deduped.append(candidate)
            continue
        if identity in seen:
            index = seen[identity]
            deduped[index] = _merge_duplicate_review_candidate(deduped[index], candidate)
            continue
        seen[identity] = len(deduped)
        deduped.append(candidate)
    return deduped


def _extract_actionable_candidates(result_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract candidates that have a midday_action from the result."""
    candidates = []
    for source_key in ("top_picks", "near_miss_candidates"):
        for item in result_json.get(source_key, []) or []:
            if not isinstance(item, dict):
                continue
            action = (item.get("midday_action") or "").strip()
            if action:
                candidates.append(_normalize_review_candidate(item, midday_action=action))
    if candidates:
        return _dedupe_review_candidates(candidates)

    for item in result_json.get("diagnostic_scorecard", []) or []:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_review_candidate(item)
        if (normalized.get("midday_action") or "").strip():
            candidates.append(normalized)
    for item in result_json.get("priority_watchlist", []) or []:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_review_candidate(item)
        if (normalized.get("midday_action") or "").strip():
            candidates.append(normalized)
    entry_screening = result_json.get("entry_list_screening") if isinstance(result_json.get("entry_list_screening"), dict) else {}
    for item in entry_screening.get("watchlist_candidates", []) or []:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_review_candidate({**item, "source_bucket": item.get("source_bucket") or "watchlist_candidates"})
        if (normalized.get("midday_action") or "").strip():
            candidates.append(normalized)
    return _dedupe_review_candidates(candidates)


def _compute_return_pct(candidate: dict[str, Any]) -> float | None:
    """Compute actual day return from close and prev_close."""
    try:
        close = float(candidate["close"])
        prev_close = float(candidate["prev_close"])
        if prev_close <= 0:
            return None
        return round((close - prev_close) / prev_close * 100, 2)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def run_postclose_review(
    result_json: dict[str, Any],
    trade_date: str,
    plan_md: str | None = None,
    *,
    x_risk_alerts: list[dict[str, Any]] | None = None,
    prior_near_miss_evictions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the full postclose review pipeline.

    Args:
        result_json: Parsed shortlist result.json dict.
        trade_date: The date being reviewed (YYYY-MM-DD).
        plan_md: Optional morning plan markdown (unused in v1, reserved).
        x_risk_alerts: X watchlist risk warnings to surface in the report.
        prior_near_miss_evictions: Eviction records from the previous day's
            review.  Candidates appearing here AND declining again today get
            ``consecutive_decline_days`` incremented.

    Returns:
        Review output dict with candidates_reviewed, summary, prior_review_adjustments.
    """
    actionable = _extract_actionable_candidates(result_json)
    candidates_reviewed: list[dict[str, Any]] = []
    summary = {"total_reviewed": 0, "correct": 0, "too_aggressive": 0, "missed": 0, "correct_negative": 0}

    for cand in actionable:
        ticker = (cand.get("ticker") or "").strip()
        name = (cand.get("name") or "").strip() or ticker
        plan_action = (cand.get("midday_action") or "").strip()
        actual_return = _compute_return_pct(cand)
        if actual_return is None:
            continue

        # Intraday bars — best-effort
        intraday_structure = "unavailable"
        try:
            bars = _fetch_intraday_bars_for_review(ticker, trade_date)
            if bars:
                from tradingagents_eastmoney_market import classify_intraday_structure
                intraday_structure = classify_intraday_structure(bars)
        except Exception:
            pass

        judgment = classify_plan_outcome(plan_action=plan_action, actual_return_pct=actual_return)
        adj = generate_adjustment(judgment)

        direction_boost = cand.get("direction_boost") if isinstance(cand.get("direction_boost"), dict) else {}
        candidates_reviewed.append({
            "ticker": ticker,
            "name": name,
            "plan_action": plan_action,
            "actual_return_pct": actual_return,
            "intraday_structure": intraday_structure,
            "judgment": judgment,
            "direction_aligned": bool(direction_boost),
            "direction_key": direction_boost.get("direction_key") or None,
            "direction_role": direction_boost.get("direction_role") or None,
            **adj,
        })

        summary["total_reviewed"] += 1
        if judgment == "plan_correct":
            summary["correct"] += 1
        elif judgment == "plan_too_aggressive":
            summary["too_aggressive"] += 1
        elif judgment == "missed_opportunity":
            summary["missed"] += 1
        elif judgment == "plan_correct_negative":
            summary["correct_negative"] += 1

    prior_review_adjustments = [
        {"ticker": c["ticker"], "adjustment": c["adjustment"],
         "priority_delta": c["priority_delta"], "gate_next_run": c["gate_next_run"]}
        for c in candidates_reviewed if c["adjustment"] != "hold"
    ]

    # Near-miss auto-eviction: observation candidates that declined should be
    # flagged for removal from the watchlist.  Condition: plan_action was
    # "继续观察" AND actual return < 0 (i.e. plan_correct_negative with a loss).
    # The consuming pipeline uses this list to drop them from the next run's
    # near_miss pool so they stop occupying plan space.
    near_miss_evictions = _compute_near_miss_evictions(
        candidates_reviewed, prior_near_miss_evictions=prior_near_miss_evictions,
    )

    divergence_warnings = detect_direction_divergence(candidates_reviewed)
    direction_momentum = compute_direction_momentum(
        candidates_reviewed, divergence_warnings=divergence_warnings,
    )

    return {
        "trade_date": trade_date,
        "candidates_reviewed": candidates_reviewed,
        "summary": summary,
        "prior_review_adjustments": prior_review_adjustments,
        "near_miss_evictions": near_miss_evictions,
        "direction_momentum": direction_momentum,
        "direction_divergence_warnings": divergence_warnings,
        "x_risk_alerts": x_risk_alerts or [],
    }


def _compute_near_miss_evictions(
    candidates_reviewed: list[dict[str, Any]],
    *,
    prior_near_miss_evictions: list[dict[str, Any]] | None = None,
    eviction_threshold_days: int = 2,
) -> list[dict[str, Any]]:
    """Compute near-miss auto-eviction list.

    A near-miss candidate (plan_action == "继续观察") that declines (return < 0)
    accumulates ``consecutive_decline_days``.  Once it reaches
    ``eviction_threshold_days``, it is marked ``evicted: true`` and should be
    dropped from the next run's near-miss pool.

    First decline → consecutive_decline_days = 1, evicted = false.
    Second consecutive decline → consecutive_decline_days = 2, evicted = true.

    If the candidate rises (return >= 0), its streak resets and it is removed
    from the eviction list entirely.
    """
    prior_by_ticker: dict[str, dict[str, Any]] = {}
    for ev in (prior_near_miss_evictions or []):
        t = (ev.get("ticker") or "").strip()
        if t:
            prior_by_ticker[t] = ev

    evictions: list[dict[str, Any]] = []
    for c in candidates_reviewed:
        if c.get("plan_action") != "继续观察":
            continue
        ticker = (c.get("ticker") or "").strip()
        name = (c.get("name") or "").strip()
        ret = c.get("actual_return_pct")
        if ret is None:
            continue

        if ret < 0:
            prior = prior_by_ticker.get(ticker)
            prev_days = int(prior.get("consecutive_decline_days", 0)) if prior else 0
            days = prev_days + 1
            evicted = days >= eviction_threshold_days
            reason = (
                f"连续{days}日观察期下跌"
                + (f"（累计: {', '.join(prior.get('decline_history', []) + [f'{ret:+.2f}%'])}）" if prior else f"（{ret:+.2f}%）")
            )
            evictions.append({
                "ticker": ticker,
                "name": name,
                "consecutive_decline_days": days,
                "evicted": evicted,
                "reason": reason,
            })
        # If ret >= 0, streak resets — candidate is NOT added to evictions,
        # effectively removing it from the tracking list.

    return evictions


def detect_direction_divergence(
    candidates_reviewed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect high-beta divergence within direction-aligned candidates.

    When high_beta stocks significantly underperform leaders in the same
    direction, it signals potential topping / exhaustion.

    Returns list of divergence warning dicts.
    """
    by_key: dict[str, dict[str, list[float]]] = {}
    for c in candidates_reviewed:
        if not c.get("direction_aligned"):
            continue
        dk = (c.get("direction_key") or "").strip()
        role = (c.get("direction_role") or "").strip()
        if not dk or role not in ("leader", "high_beta"):
            continue
        if dk not in by_key:
            by_key[dk] = {"leader": [], "high_beta": []}
        ret = c.get("actual_return_pct")
        if ret is not None:
            by_key[dk][role].append(float(ret))

    warnings: list[dict[str, Any]] = []
    for dk, roles in by_key.items():
        if not roles["leader"] or not roles["high_beta"]:
            continue
        leader_avg = sum(roles["leader"]) / len(roles["leader"])
        hb_avg = sum(roles["high_beta"]) / len(roles["high_beta"])
        if hb_avg < leader_avg and hb_avg < 0.5:
            warnings.append({
                "direction_key": dk,
                "divergence_type": "high_beta_lagging",
                "leader_avg_return": round(leader_avg, 2),
                "high_beta_avg_return": round(hb_avg, 2),
                "warning": f"High-beta stocks ({hb_avg:+.2f}%) significantly lag leaders ({leader_avg:+.2f}%) — potential topping signal.",
            })
    return warnings


def compute_direction_momentum(
    candidates_reviewed: list[dict[str, Any]],
    *,
    divergence_warnings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compute direction momentum signals from reviewed candidates.

    Groups direction-aligned candidates by direction_key and produces
    a momentum_signal for each direction based on judgment distribution.

    Returns list of direction momentum entries (empty for directions with
    zero aligned candidates).
    """
    # Group by direction_key
    by_key: dict[str, dict[str, Any]] = {}
    for c in candidates_reviewed:
        if not c.get("direction_aligned"):
            continue
        dk = (c.get("direction_key") or "").strip()
        if not dk:
            continue
        if dk not in by_key:
            by_key[dk] = {
                "direction_key": dk,
                "direction_label": dk,
                "aligned_candidates_count": 0,
                "aligned_correct": 0,
                "aligned_too_aggressive": 0,
                "aligned_missed": 0,
            }
        entry = by_key[dk]
        entry["aligned_candidates_count"] += 1
        judgment = (c.get("judgment") or "").strip()
        if judgment == "plan_correct":
            entry["aligned_correct"] += 1
        elif judgment == "plan_too_aggressive":
            entry["aligned_too_aggressive"] += 1
        elif judgment == "missed_opportunity":
            entry["aligned_missed"] += 1

    result = []
    diverged_keys = {w["direction_key"] for w in (divergence_warnings or [])}
    for dk, entry in by_key.items():
        count = entry["aligned_candidates_count"]
        if count == 0:
            continue
        # Evaluation order: caution → strengthening → confirmed → fading
        if entry["aligned_too_aggressive"] > 0:
            signal = "caution"
        elif entry["aligned_missed"] > 0 and entry["aligned_too_aggressive"] == 0:
            signal = "strengthening"
        elif entry["aligned_correct"] / count >= 0.5:
            signal = "confirmed"
        else:
            signal = "fading"
        # Divergence detection: downgrade "confirmed" to "caution" if high-beta lagging
        if dk in diverged_keys and signal == "confirmed":
            signal = "caution"
            entry["divergence_detected"] = True
        # Overheat dampener: if any aligned stock surged >5% today,
        # downgrade strengthening → caution (short-term mean-reversion risk)
        if signal == "strengthening":
            aligned_returns = [
                c["actual_return_pct"]
                for c in candidates_reviewed
                if c.get("direction_key") == dk and c.get("actual_return_pct") is not None
            ]
            if any(r > 5.0 for r in aligned_returns):
                signal = "caution"
                entry["overheat_detected"] = True
        entry["momentum_signal"] = signal
        result.append(entry)
    return result


def build_review_markdown(review: dict[str, Any]) -> str:
    """Render the review output as a markdown report."""
    lines: list[str] = []
    trade_date = review.get("trade_date", "unknown")
    lines.append(f"# 盘后复盘报告 — {trade_date}")
    lines.append("")

    # Section: 操作建议摘要
    lines.append("## 操作建议摘要")
    lines.append("")
    lines.append("| 代码 | 名称 | 计划操作 | 实际涨跌% | 分时结构 | 判定 | 调整 |")
    lines.append("|---|---|---|---|---|---|---|")
    for c in review.get("candidates_reviewed", []):
        lines.append(
            f"| {c['ticker']} | {c['name']} | {c['plan_action']} | "
            f"{c['actual_return_pct']:+.2f}% | {c['intraday_structure']} | "
            f"{c['judgment']} | {c['adjustment']} |"
        )
    lines.append("")

    # Section: summary
    s = review.get("summary", {})
    lines.append("## 复盘统计")
    lines.append("")
    lines.append(f"- 总复盘: {s.get('total_reviewed', 0)}")
    lines.append(f"- 计划正确: {s.get('correct', 0)}")
    lines.append(f"- 过于激进: {s.get('too_aggressive', 0)}")
    lines.append(f"- 错过机会: {s.get('missed', 0)}")
    lines.append(f"- 正确回避: {s.get('correct_negative', 0)}")
    lines.append("")

    # Section: 次日观察点
    lines.append("## 次日观察点")
    lines.append("")
    adjustments = review.get("prior_review_adjustments", [])
    if adjustments:
        for adj in adjustments:
            action = "加分 +5" if adj["adjustment"] == "upgrade" else "减分 -5 + 强制确认"
            lines.append(f"- {adj['ticker']}: {action}")
    else:
        lines.append("- 无需调整")
    lines.append("")

    # Section: near-miss evictions
    evictions = review.get("near_miss_evictions", [])
    if evictions:
        lines.append("## 观察池清退")
        lines.append("")
        lines.append("| 代码 | 名称 | 连续下跌天数 | 状态 | 原因 |")
        lines.append("|---|---|---|---|---|")
        for ev in evictions:
            status = "🔴 **已清退**" if ev.get("evicted") else "⚠️ 预警"
            lines.append(
                f"| {ev.get('ticker', '?')} | {ev.get('name', '?')} "
                f"| {ev.get('consecutive_decline_days', 0)} "
                f"| {status} "
                f"| {ev.get('reason', '')} |"
            )
        lines.append("")

    # Direction momentum section
    direction_momentum = review.get("direction_momentum", [])
    if direction_momentum:
        lines.append("## 方向动量信号")
        lines.append("")
        lines.append("| 方向 | 对齐数 | 正确 | 过激 | 错过 | 信号 |")
        lines.append("|---|---|---|---|---|---|")
        for m in direction_momentum:
            lines.append(
                f"| {m.get('direction_label', m.get('direction_key', '?'))} "
                f"| {m.get('aligned_candidates_count', 0)} "
                f"| {m.get('aligned_correct', 0)} "
                f"| {m.get('aligned_too_aggressive', 0)} "
                f"| {m.get('aligned_missed', 0)} "
                f"| {m.get('momentum_signal', '?')} |"
            )
        lines.append("")

    divergence_warnings = review.get("direction_divergence_warnings", [])
    if divergence_warnings:
        lines.append("## 方向分化预警")
        lines.append("")
        for w in divergence_warnings:
            lines.append(
                f"- **{w.get('direction_key', '?')}**: "
                f"leader avg {w.get('leader_avg_return', 0):+.2f}% vs "
                f"high_beta avg {w.get('high_beta_avg_return', 0):+.2f}% — "
                f"{w.get('warning', '')}"
            )
        lines.append("")

    # X risk alerts — surface critical watchlist warnings with original text
    x_risk_alerts = review.get("x_risk_alerts", [])
    if x_risk_alerts:
        lines.append("## ⚠️ X 情报风险警告")
        lines.append("")
        for alert in x_risk_alerts:
            ticker = alert.get("ticker", "?")
            author = alert.get("author", "?")
            alert_text = alert.get("alert_text", "")
            alert_type = alert.get("alert_type", "risk")
            source_url = alert.get("source_url", "")
            url_suffix = f" [{source_url}]" if source_url else ""
            lines.append(f"> **{ticker}** — @{author}{url_suffix}")
            lines.append(f'> "{alert_text}"')
            lines.append(f"> 类型: {alert_type}")
            lines.append("")

    # Consistency check — warned tickers should not be top-3 priority
    warned_tickers: set[str] = set()
    for c in review.get("candidates_reviewed", []):
        if c.get("judgment") == "plan_too_aggressive":
            warned_tickers.add(c["ticker"])
    for alert in x_risk_alerts:
        t = alert.get("ticker", "").strip()
        if t:
            warned_tickers.add(t)
    for m in review.get("direction_momentum", []):
        if m.get("overheat_detected"):
            dk = m.get("direction_key", "")
            for c in review.get("candidates_reviewed", []):
                if c.get("direction_key") == dk:
                    warned_tickers.add(c["ticker"])
    if warned_tickers:
        lines.append("## ⚠️ 一致性检查")
        lines.append("")
        lines.append("以下标的有风险警告，**不应排入执行摘要前3优先**：")
        for t in sorted(warned_tickers):
            name = ""
            for c in review.get("candidates_reviewed", []):
                if c.get("ticker") == t:
                    name = c.get("name", "")
                    break
            lines.append(f"- {t}" + (f" ({name})" if name else ""))
        lines.append("")

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run postclose review on a shortlist result.")
    parser.add_argument("--result", required=True, help="Path to result.json from shortlist run.")
    parser.add_argument("--date", required=True, help="Trade date being reviewed (YYYY-MM-DD).")
    parser.add_argument("--plan", default=None, help="Optional path to morning trading plan markdown.")
    parser.add_argument("--output", default=None, help="Write review JSON to this path.")
    parser.add_argument("--markdown-output", default=None, help="Write review markdown to this path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result_path = Path(args.result).expanduser().resolve()
    result_json = json.loads(result_path.read_text(encoding="utf-8-sig"))
    plan_md = None
    if args.plan:
        plan_md = Path(args.plan).expanduser().resolve().read_text(encoding="utf-8")

    review = run_postclose_review(
        result_json,
        args.date,
        plan_md,
        x_risk_alerts=result_json.get("x_risk_alerts") or [],
    )

    if args.output:
        out = Path(args.output).expanduser().resolve()
        out.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown_output:
        md_out = Path(args.markdown_output).expanduser().resolve()
        md_out.write_text(build_review_markdown(review), encoding="utf-8")
    if not args.output:
        sys.stdout.write(json.dumps(review, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
