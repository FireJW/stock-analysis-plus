#!/usr/bin/env python3
"""Direction risk register — persists per-direction caution / overheat /
divergence signals across days so that single-day signals can escalate into
restrictions when they recur.

The post-close review (``postclose_review_runtime``) emits per-direction
momentum and divergence warnings that reset every run.  This module reads
those signals each day, advances a state machine per direction, and persists
the result to disk.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import clean_text


SCHEMA_VERSION = "direction_risk_register/v1"
DEFAULT_REGISTER_FILENAME = "direction-risk-register.json"
HISTORY_LIMIT = 20
DEFAULT_RESTRICTION_DAYS = 5

_GOOD_STATUSES = {"confirmed", "strengthening"}


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _add_days(trade_date: str, n: int) -> str:
    return (date.fromisoformat(trade_date) + timedelta(days=n)).isoformat()


def empty_register() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "last_updated": _utc_now_iso(),
        "directions": {},
    }


def _new_direction_entry() -> dict[str, Any]:
    return {
        "current_status": "normal",
        "consecutive_caution_days": 0,
        "consecutive_good_days": 0,
        "last_overheat_date": "",
        "last_divergence_date": "",
        "history": [],
        "restriction_reason": "",
        "restriction_expires": "",
    }


def _extract_signals(postclose_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collapse direction_momentum + direction_divergence_warnings to a
    per-direction signal: ``{status, overheat, divergence}``."""
    signals: dict[str, dict[str, Any]] = {}
    for m in safe_list(postclose_result.get("direction_momentum")):
        if not isinstance(m, dict):
            continue
        dk = clean_text(m.get("direction_key"))
        if not dk:
            continue
        status = clean_text(m.get("momentum_status") or m.get("momentum_signal"))
        overheat = bool(m.get("overheat") or m.get("overheat_detected"))
        divergence = bool(
            m.get("divergence") or m.get("divergence_dampener") or m.get("divergence_detected")
        )
        signals[dk] = {"status": status, "overheat": overheat, "divergence": divergence}
    for w in safe_list(postclose_result.get("direction_divergence_warnings")):
        if not isinstance(w, dict):
            continue
        dk = clean_text(w.get("direction_key"))
        if not dk:
            continue
        signal = signals.setdefault(dk, {"status": "", "overheat": False, "divergence": False})
        signal["divergence"] = True
    return signals


def _apply_signal(
    entry: dict[str, Any],
    signal: dict[str, Any],
    trade_date: str,
    *,
    restriction_days: int,
) -> dict[str, Any]:
    status = clean_text(signal.get("status"))
    overheat = bool(signal.get("overheat"))
    divergence = bool(signal.get("divergence"))

    if status == "caution":
        entry["consecutive_caution_days"] = int(entry.get("consecutive_caution_days", 0)) + 1
        entry["consecutive_good_days"] = 0
    elif status in _GOOD_STATUSES:
        entry["consecutive_caution_days"] = 0
        if overheat:
            entry["consecutive_good_days"] = 0
        else:
            entry["consecutive_good_days"] = int(entry.get("consecutive_good_days", 0)) + 1
    else:
        entry["consecutive_caution_days"] = 0
        entry["consecutive_good_days"] = 0

    if overheat:
        entry["last_overheat_date"] = trade_date
    if divergence:
        entry["last_divergence_date"] = trade_date

    history = list(safe_list(entry.get("history")))
    history.append({
        "date": trade_date,
        "momentum_status": status,
        "overheat": overheat,
        "divergence": divergence,
    })
    if len(history) > HISTORY_LIMIT:
        history = history[-HISTORY_LIMIT:]
    entry["history"] = history

    current = clean_text(entry.get("current_status")) or "normal"
    caution_days = int(entry["consecutive_caution_days"])
    good_days = int(entry["consecutive_good_days"])

    # Auto-expire any active restriction first.
    if current == "restricted":
        expiry = clean_text(entry.get("restriction_expires"))
        if expiry and trade_date >= expiry:
            current = "elevated"
            entry["restriction_reason"] = ""
            entry["restriction_expires"] = ""

    # restricted → elevated after 1 day of good momentum.  The 2-day countdown
    # toward "normal" starts fresh from the next session, so reset good_days.
    if current == "restricted" and status in _GOOD_STATUSES:
        current = "elevated"
        entry["restriction_reason"] = ""
        entry["restriction_expires"] = ""
        entry["consecutive_good_days"] = 0
        good_days = 0

    # normal → elevated on first caution or any overheat.
    if current == "normal" and (caution_days >= 1 or overheat):
        current = "elevated"

    # elevated → restricted on 2 consecutive caution days OR overheat+divergence.
    if current == "elevated":
        if caution_days >= 2 or (overheat and divergence):
            reasons: list[str] = []
            if caution_days >= 2:
                reasons.append(f"{caution_days} consecutive caution days")
            if overheat and divergence:
                reasons.append("overheat + divergence on same day")
            current = "restricted"
            entry["restriction_reason"] = "; ".join(reasons) or "escalated to restricted"
            entry["restriction_expires"] = _add_days(trade_date, restriction_days)
        elif good_days >= 2:
            current = "normal"
            entry["restriction_reason"] = ""
            entry["restriction_expires"] = ""

    entry["current_status"] = current
    return entry


def update_register(
    register: dict[str, Any],
    postclose_result: dict[str, Any],
    trade_date: str,
    *,
    restriction_days: int = DEFAULT_RESTRICTION_DAYS,
) -> dict[str, Any]:
    """Apply today's post-close result to the register and return the updated copy."""
    if not trade_date:
        raise ValueError("trade_date is required (YYYY-MM-DD)")
    register = dict(register or {}) if isinstance(register, dict) else {}
    register.setdefault("schema_version", SCHEMA_VERSION)
    directions = dict(safe_dict(register.get("directions")))

    signals = _extract_signals(safe_dict(postclose_result))
    for dk, signal in signals.items():
        entry = dict(safe_dict(directions.get(dk)) or _new_direction_entry())
        directions[dk] = _apply_signal(entry, signal, trade_date, restriction_days=restriction_days)

    # Auto-expire any directions that were restricted but received no signal today.
    for dk, entry in directions.items():
        if dk in signals:
            continue
        if clean_text(entry.get("current_status")) == "restricted":
            expiry = clean_text(entry.get("restriction_expires"))
            if expiry and trade_date >= expiry:
                entry["current_status"] = "elevated"
                entry["restriction_reason"] = ""
                entry["restriction_expires"] = ""

    register["directions"] = directions
    register["last_updated"] = _utc_now_iso()
    return register


def restricted_directions(register: dict[str, Any]) -> list[str]:
    return [
        dk
        for dk, entry in safe_dict(safe_dict(register).get("directions")).items()
        if clean_text(safe_dict(entry).get("current_status")) == "restricted"
    ]


def elevated_directions(register: dict[str, Any]) -> list[str]:
    return [
        dk
        for dk, entry in safe_dict(safe_dict(register).get("directions")).items()
        if clean_text(safe_dict(entry).get("current_status")) == "elevated"
    ]


def direction_risk_level(register: dict[str, Any], direction_key: str) -> str:
    entry = safe_dict(safe_dict(safe_dict(register).get("directions")).get(direction_key))
    return clean_text(entry.get("current_status")) or "normal"


def risk_summary(register: dict[str, Any]) -> dict[str, Any]:
    directions = safe_dict(safe_dict(register).get("directions"))
    counts = {"normal": 0, "elevated": 0, "restricted": 0}
    most_restricted: tuple[int, str] = (-1, "")
    last_all_clear_dates: list[str] = []
    for dk, raw_entry in directions.items():
        entry = safe_dict(raw_entry)
        status = clean_text(entry.get("current_status")) or "normal"
        counts[status] = counts.get(status, 0) + 1
        if status == "restricted":
            caution = int(entry.get("consecutive_caution_days", 0))
            if caution > most_restricted[0]:
                most_restricted = (caution, dk)
        for hist in reversed(safe_list(entry.get("history"))):
            if isinstance(hist, dict) and clean_text(hist.get("momentum_status")) in _GOOD_STATUSES \
                    and not hist.get("overheat") and not hist.get("divergence"):
                last_all_clear_dates.append(clean_text(hist.get("date")))
                break
    days_since_all_clear = ""
    if last_all_clear_dates:
        most_recent = max(last_all_clear_dates)
        try:
            delta = (date.today() - date.fromisoformat(most_recent)).days
            days_since_all_clear = str(max(delta, 0))
        except ValueError:
            days_since_all_clear = ""
    return {
        "counts": counts,
        "total_tracked": sum(counts.values()),
        "most_restricted_direction": most_restricted[1],
        "days_since_last_all_clear": days_since_all_clear,
    }


def apply_direction_risk_to_package(package: dict[str, Any], register: dict[str, Any]) -> None:
    if not isinstance(package, dict) or not isinstance(register, dict):
        return
    package["direction_risk_register_summary"] = risk_summary(register)
    directions = safe_dict(register.get("directions"))
    flagged = {dk for dk, e in directions.items()
               if clean_text(safe_dict(e).get("current_status")) in {"elevated", "restricted"}}
    if not flagged:
        return

    def _warning_for(dk: str) -> dict[str, str]:
        entry = safe_dict(directions.get(dk))
        return {
            "direction_key": dk,
            "risk_level": clean_text(entry.get("current_status")),
            "reason": clean_text(entry.get("restriction_reason")),
            "expires": clean_text(entry.get("restriction_expires")),
        }

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            # Snapshot children first so any warning we attach below isn't walked.
            children = [
                v for k, v in node.items()
                if k != "direction_risk_warning"
            ]
            dk = clean_text(node.get("direction_key"))
            if not dk:
                dk = clean_text(safe_dict(node.get("direction_boost")).get("direction_key"))
            if dk and dk in flagged:
                warning = _warning_for(dk)
                trade_card = node.get("trade_card")
                if isinstance(trade_card, dict):
                    trade_card["direction_risk_warning"] = warning
                else:
                    node["direction_risk_warning"] = warning
            for value in children:
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(package)


def load_register(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser()
    if not p.exists():
        return empty_register()
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return empty_register()
    if not isinstance(data, dict):
        return empty_register()
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("directions", {})
    return data


def save_register(register: dict[str, Any], path: str | Path) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(register, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compute_direction_transitions(
    prev_register: dict[str, Any],
    new_register: dict[str, Any],
    trade_date: str,
) -> list[dict[str, str]]:
    """Diff per-direction current_status between prev and new registers.

    Returns one row per direction whose status changed today. New directions
    that did not exist in prev_register are reported with from_status="new"."""
    prev_dirs = safe_dict(safe_dict(prev_register).get("directions"))
    new_dirs = safe_dict(safe_dict(new_register).get("directions"))
    transitions: list[dict[str, str]] = []
    for dk in sorted(new_dirs.keys()):
        new_entry = safe_dict(new_dirs.get(dk))
        new_status = clean_text(new_entry.get("current_status")) or "normal"
        if dk in prev_dirs:
            prev_status = clean_text(safe_dict(prev_dirs.get(dk)).get("current_status")) or "normal"
            if prev_status == new_status:
                continue
            from_status = prev_status
        else:
            if new_status == "normal":
                continue
            from_status = "new"
        transitions.append({
            "direction_key": dk,
            "from_status": from_status,
            "to_status": new_status,
            "reason": clean_text(new_entry.get("restriction_reason")),
            "expires": clean_text(new_entry.get("restriction_expires")),
            "trade_date": clean_text(trade_date),
        })
    return transitions


def render_risk_register_markdown(
    register: dict[str, Any],
    transitions: list[dict[str, str]] | None = None,
) -> str:
    lines: list[str] = []
    last_updated = clean_text(safe_dict(register).get("last_updated"))
    lines.append(f"# 方向风险登记表 — last_updated {last_updated or 'n/a'}")
    lines.append("")
    summary = risk_summary(register)
    counts = safe_dict(summary.get("counts"))
    lines.append(
        f"- 总跟踪方向: {summary.get('total_tracked', 0)} "
        f"(normal={counts.get('normal', 0)}, "
        f"elevated={counts.get('elevated', 0)}, "
        f"restricted={counts.get('restricted', 0)})"
    )
    if summary.get("most_restricted_direction"):
        lines.append(f"- 最受限方向: {summary['most_restricted_direction']}")
    lines.append("")
    if transitions:
        lines.append(f"## 今日状态变化 ({len(transitions)})")
        lines.append("")
        lines.append("| 方向 | 变化 | 原因 | 限制到期 |")
        lines.append("|---|---|---|---|")
        for t in transitions:
            arrow = f"{t.get('from_status', '')} → {t.get('to_status', '')}"
            lines.append(
                f"| {t.get('direction_key', '')} | {arrow} "
                f"| {t.get('reason') or '-'} "
                f"| {t.get('expires') or '-'} |"
            )
        lines.append("")
    lines.append("| 方向 | 状态 | 连续caution天 | 连续good天 | 上次overheat | 上次divergence | 限制原因 | 限制到期 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    directions = safe_dict(safe_dict(register).get("directions"))
    for dk in sorted(directions.keys()):
        e = safe_dict(directions[dk])
        lines.append(
            f"| {dk} | {clean_text(e.get('current_status')) or 'normal'} "
            f"| {int(e.get('consecutive_caution_days', 0))} "
            f"| {int(e.get('consecutive_good_days', 0))} "
            f"| {clean_text(e.get('last_overheat_date')) or '-'} "
            f"| {clean_text(e.get('last_divergence_date')) or '-'} "
            f"| {clean_text(e.get('restriction_reason')) or '-'} "
            f"| {clean_text(e.get('restriction_expires')) or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_REGISTER_FILENAME",
    "DEFAULT_RESTRICTION_DAYS",
    "HISTORY_LIMIT",
    "empty_register",
    "update_register",
    "restricted_directions",
    "elevated_directions",
    "direction_risk_level",
    "risk_summary",
    "apply_direction_risk_to_package",
    "load_register",
    "save_register",
    "compute_direction_transitions",
    "render_risk_register_markdown",
]
