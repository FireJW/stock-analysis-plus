#!/usr/bin/env python3
"""Persistent trade journal for the month-end shortlist system.

Append-only JSONL store of trading decisions and their outcomes, plus query
helpers for stats, open positions, and integration with the local stock pool
and postclose review runtimes.

Each line in the journal is a single JSON object with an ``entry_kind`` of
either ``decision`` or ``outcome``.  Decisions describe what was planned (or
executed) for a given ticker on a given date; outcomes link back via
``journal_id`` and describe what happened at T+1, T+5, T+20, or on exit.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text  # noqa: F401


VALID_MARKETS = {"a_share", "us", "hk"}
VALID_ACTIONS = {"buy_trigger", "watch", "skip", "hold", "exit"}
VALID_SIZE_LABELS = {"probe", "half", "full", ""}
VALID_SOURCE_LAYERS = {
    "x_seed",
    "reddit",
    "fresh_discovery",
    "fundamental",
    "weekend_candidate",
}
VALID_OUTCOME_TYPES = {"t1", "t5", "t20", "exit"}
VALID_OUTCOME_LABELS = {
    "hit_trigger",
    "stopped_out",
    "invalidated",
    "still_holding",
    "target_reached",
}
TERMINAL_OUTCOME_LABELS = {"stopped_out", "invalidated", "target_reached"}

DEFAULT_JOURNAL_NAME = "trade-journal.jsonl"


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _ensure_iso_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    return text[:10]


def default_journal_path(output_root: str | Path) -> Path:
    return Path(output_root).expanduser() / DEFAULT_JOURNAL_NAME


def append_journal_entry(path: str | Path, entry: dict[str, Any]) -> dict[str, Any]:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return entry


def record_decision(
    path: str | Path,
    *,
    decision_date: str,
    ticker: str,
    name: str,
    market: str,
    action: str,
    source_layer: str,
    intended_size_label: str = "",
    trigger_price: Any = None,
    stop_loss: Any = None,
    abandon_below: Any = None,
    entry_price: Any = None,
    decision_context: str = "",
    journal_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Append a single decision entry to the journal."""
    entry = {
        "entry_kind": "decision",
        "journal_id": journal_id or str(uuid.uuid4()),
        "decision_date": _ensure_iso_date(decision_date),
        "ticker": clean_text(ticker),
        "name": clean_text(name) or clean_text(ticker),
        "market": clean_text(market),
        "action": clean_text(action),
        "source_layer": clean_text(source_layer),
        "intended_size_label": clean_text(intended_size_label),
        "trigger_price": _to_float_or_none(trigger_price),
        "stop_loss": _to_float_or_none(stop_loss),
        "abandon_below": _to_float_or_none(abandon_below),
        "entry_price": _to_float_or_none(entry_price),
        "decision_context": clean_text(decision_context),
        "recorded_at": recorded_at or _now_iso(),
    }
    return append_journal_entry(path, entry)


def record_outcome(
    path: str | Path,
    *,
    journal_id: str,
    outcome_type: str,
    outcome_date: str,
    close_price: Any = None,
    return_pct: Any = None,
    outcome_label: str = "",
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Append a single outcome entry to the journal, linked by ``journal_id``."""
    entry = {
        "entry_kind": "outcome",
        "journal_id": clean_text(journal_id),
        "outcome_type": clean_text(outcome_type),
        "outcome_date": _ensure_iso_date(outcome_date),
        "close_price": _to_float_or_none(close_price),
        "return_pct": _to_float_or_none(return_pct),
        "outcome_label": clean_text(outcome_label),
        "recorded_at": recorded_at or _now_iso(),
    }
    return append_journal_entry(path, entry)


def load_journal(path: str | Path) -> list[dict[str, Any]]:
    """Read all journal entries from disk.  Returns an empty list if absent."""
    target = Path(path).expanduser()
    if not target.exists():
        return []
    entries: list[dict[str, Any]] = []
    text = target.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _entries_by_kind(journal: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in journal if e.get("entry_kind") == kind]


def _outcomes_by_journal_id(
    journal: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in _entries_by_kind(journal, "outcome"):
        jid = clean_text(entry.get("journal_id"))
        if not jid:
            continue
        grouped.setdefault(jid, []).append(entry)
    return grouped


def _is_terminal_outcome(outcome: dict[str, Any]) -> bool:
    if outcome.get("outcome_type") == "exit":
        return True
    return clean_text(outcome.get("outcome_label")) in TERMINAL_OUTCOME_LABELS


def _terminal_outcome(related: list[dict[str, Any]]) -> dict[str, Any] | None:
    for outcome in related:
        if _is_terminal_outcome(outcome):
            return outcome
    return None


def open_positions(journal: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return decisions with ``buy_trigger`` action that have an entry price
    and no terminal outcome yet."""
    outcomes = _outcomes_by_journal_id(journal)
    open_list: list[dict[str, Any]] = []
    for decision in _entries_by_kind(journal, "decision"):
        if clean_text(decision.get("action")) != "buy_trigger":
            continue
        if decision.get("entry_price") in (None, ""):
            continue
        jid = clean_text(decision.get("journal_id"))
        related = outcomes.get(jid, [])
        if any(_is_terminal_outcome(o) for o in related):
            continue
        open_list.append(decision)
    return open_list


def _within_lookback(decision_date: str, today: date, lookback_days: int) -> bool:
    if not decision_date:
        return False
    try:
        d = date.fromisoformat(decision_date[:10])
    except ValueError:
        return False
    delta = (today - d).days
    return 0 <= delta <= lookback_days


def _summarize_decisions(
    decisions: list[dict[str, Any]],
    outcomes: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    count = len(decisions)
    wins = 0
    losses = 0
    win_returns: list[float] = []
    loss_returns: list[float] = []
    all_returns: list[float] = []
    for decision in decisions:
        jid = clean_text(decision.get("journal_id"))
        related = outcomes.get(jid, [])
        terminal = _terminal_outcome(related)
        if terminal is None:
            continue
        ret = _to_float_or_none(terminal.get("return_pct"))
        if ret is None:
            continue
        all_returns.append(ret)
        if ret > 0:
            wins += 1
            win_returns.append(ret)
        elif ret < 0:
            losses += 1
            loss_returns.append(ret)
    resolved = wins + losses
    hit_rate = wins / resolved if resolved else 0.0
    avg_win = sum(win_returns) / len(win_returns) if win_returns else 0.0
    avg_loss = sum(loss_returns) / len(loss_returns) if loss_returns else 0.0
    expectancy = hit_rate * avg_win + (1 - hit_rate) * avg_loss if resolved else 0.0
    avg_return = sum(all_returns) / len(all_returns) if all_returns else 0.0
    max_dd = min(all_returns) if all_returns else 0.0
    return {
        "count": count,
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "hit_rate": round(hit_rate, 4),
        "expectancy": round(expectancy, 4),
        "avg_return": round(avg_return, 4),
        "max_drawdown_pct": round(max_dd, 4) if max_dd < 0 else 0.0,
    }


def compute_stats(
    journal: list[dict[str, Any]],
    *,
    lookback_days: int = 90,
    today: date | None = None,
) -> dict[str, Any]:
    """Return realized stats for ``buy_trigger`` decisions within the lookback
    window, including a per-source breakdown."""
    today = today or date.today()
    outcomes = _outcomes_by_journal_id(journal)
    decisions_in_window = [
        d
        for d in _entries_by_kind(journal, "decision")
        if clean_text(d.get("action")) == "buy_trigger"
        and _within_lookback(clean_text(d.get("decision_date")), today, lookback_days)
    ]
    overall = _summarize_decisions(decisions_in_window, outcomes)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for decision in decisions_in_window:
        layer = clean_text(decision.get("source_layer")) or "unknown"
        by_source.setdefault(layer, []).append(decision)
    by_source_layer = {
        layer: _summarize_decisions(items, outcomes)
        for layer, items in by_source.items()
    }
    return {
        "lookback_days": lookback_days,
        "as_of": today.isoformat(),
        **overall,
        "by_source_layer": by_source_layer,
    }


def _infer_market(ticker: str) -> str:
    t = clean_text(ticker).upper()
    if t.endswith((".SS", ".SH", ".SZ", ".BJ")):
        return "a_share"
    if t.endswith(".HK"):
        return "hk"
    return "us"


def _infer_action_from_trade_card(trade_card: dict[str, Any]) -> str:
    text = clean_text(trade_card.get("watch_action"))
    if not text:
        return "watch"
    lowered = text.lower()
    buy_markers = ("试仓", "建仓", "执行", "直接执行", "可买", "buy", "enter")
    skip_markers = ("不买", "不执行", "回避", "skip", "abandon")
    if any(marker in text or marker in lowered for marker in skip_markers):
        return "skip"
    if any(marker in text or marker in lowered for marker in buy_markers):
        return "buy_trigger"
    return "watch"


def _first_price(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, list):
            for item in value:
                parsed = _to_float_or_none(item)
                if parsed is not None:
                    return parsed
            continue
        parsed = _to_float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _last_price(value: Any) -> float | None:
    if isinstance(value, list):
        for item in reversed(value):
            parsed = _to_float_or_none(item)
            if parsed is not None:
                return parsed
        return None
    return _to_float_or_none(value)


def _normalize_source_layer(value: Any, default: str) -> str:
    text = clean_text(value)
    if text in VALID_SOURCE_LAYERS:
        return text
    return default if default in VALID_SOURCE_LAYERS else "weekend_candidate"


def record_decisions_from_package(
    package: dict[str, Any],
    journal_path: str | Path,
    *,
    decision_date: str | None = None,
    source_layer_default: str = "weekend_candidate",
) -> list[dict[str, Any]]:
    """Read the local stock pool's trade cards from a manager package and
    append decision entries.  Skips ticker+date pairs that already exist."""
    pool = safe_dict(package.get("local_stock_pool"))
    request = safe_dict(package.get("month_end_request"))
    resolved_date = _ensure_iso_date(
        decision_date or request.get("target_date") or date.today().isoformat()
    )

    existing = load_journal(journal_path)
    seen_keys = {
        (clean_text(e.get("ticker")), clean_text(e.get("decision_date")))
        for e in _entries_by_kind(existing, "decision")
    }

    appended: list[dict[str, Any]] = []
    for stock in safe_list(pool.get("stocks")):
        if not isinstance(stock, dict):
            continue
        ticker = clean_text(stock.get("ticker"))
        if not ticker:
            continue
        key = (ticker, resolved_date)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        plan_snapshot = safe_dict(stock.get("plan_snapshot"))
        trade_card = safe_dict(plan_snapshot.get("trade_card") or stock.get("trade_card"))
        price_paths = safe_dict(
            plan_snapshot.get("price_paths") or stock.get("price_paths")
        )
        levels = safe_dict(stock.get("levels") or plan_snapshot.get("levels"))

        trigger = _first_price(
            levels.get("trigger_price"),
            price_paths.get("resistance"),
            price_paths.get("target"),
        )
        stop = _first_price(levels.get("stop_loss"), price_paths.get("support"))
        abandon = _first_price(
            levels.get("abandon_below"), _last_price(price_paths.get("support"))
        )

        action = _infer_action_from_trade_card(trade_card)
        market = _infer_market(ticker)
        source_layer = _normalize_source_layer(
            stock.get("source_layer") or stock.get("source"),
            source_layer_default,
        )

        entry = record_decision(
            journal_path,
            decision_date=resolved_date,
            ticker=ticker,
            name=clean_text(stock.get("name")) or ticker,
            market=market,
            action=action,
            source_layer=source_layer,
            trigger_price=trigger,
            stop_loss=stop,
            abandon_below=abandon,
            decision_context=clean_text(trade_card.get("watch_action")),
        )
        appended.append(entry)
    return appended


def _ticker_variants(ticker: str) -> list[str]:
    t = clean_text(ticker).upper()
    out = [t]
    if t.endswith(".SS"):
        out.append(t[:-3] + ".SH")
    elif t.endswith(".SH"):
        out.append(t[:-3] + ".SS")
    return out


def _judgment_to_outcome_label(judgment: str, return_pct: Any) -> str:
    ret = _to_float_or_none(return_pct)
    judgment = clean_text(judgment)
    if judgment == "plan_too_aggressive" and ret is not None and ret <= -3.0:
        return "stopped_out"
    if judgment == "plan_correct" and ret is not None and ret >= 5.0:
        return "target_reached"
    return "still_holding"


def record_outcomes_from_postclose(
    postclose_result: dict[str, Any],
    journal_path: str | Path,
    journal: list[dict[str, Any]] | None = None,
    *,
    outcome_type: str = "t1",
) -> list[dict[str, Any]]:
    """Match postclose review candidates to open journal entries and append
    outcomes (default T+1).  Open entries are decisions with ``buy_trigger``
    action and an ``entry_price`` that have no terminal outcome yet."""
    journal = journal if journal is not None else load_journal(journal_path)
    trade_date = _ensure_iso_date(postclose_result.get("trade_date"))

    open_decisions = open_positions(journal)
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for decision in open_decisions:
        for variant in _ticker_variants(clean_text(decision.get("ticker"))):
            by_ticker.setdefault(variant, []).append(decision)

    existing_outcomes = {
        (clean_text(e.get("journal_id")), clean_text(e.get("outcome_type")))
        for e in _entries_by_kind(journal, "outcome")
    }

    appended: list[dict[str, Any]] = []
    for cand in safe_list(postclose_result.get("candidates_reviewed")):
        if not isinstance(cand, dict):
            continue
        ticker = clean_text(cand.get("ticker"))
        if not ticker:
            continue
        decisions: list[dict[str, Any]] = []
        for variant in _ticker_variants(ticker):
            decisions = by_ticker.get(variant, [])
            if decisions:
                break
        if not decisions:
            continue
        target = max(decisions, key=lambda d: clean_text(d.get("decision_date")))
        jid = clean_text(target.get("journal_id"))
        if (jid, outcome_type) in existing_outcomes:
            continue
        existing_outcomes.add((jid, outcome_type))

        ret = cand.get("actual_return_pct")
        label = _judgment_to_outcome_label(cand.get("judgment"), ret)
        entry = record_outcome(
            journal_path,
            journal_id=jid,
            outcome_type=outcome_type,
            outcome_date=trade_date,
            close_price=cand.get("close"),
            return_pct=ret,
            outcome_label=label,
        )
        appended.append(entry)
    return appended


def render_trade_journal_markdown(
    journal: list[dict[str, Any]],
    *,
    lookback_days: int = 90,
    today: date | None = None,
) -> str:
    """Render a concise markdown digest of the trade journal state."""
    today = today or date.today()
    lines: list[str] = []
    lines.append(f"# Trade Journal Digest — {today.isoformat()}")
    lines.append("")

    stats = compute_stats(journal, lookback_days=lookback_days, today=today)
    lines.append(f"## Stats (last {lookback_days} days)")
    lines.append("")
    lines.append(f"- Decisions: {stats['count']}")
    lines.append(f"- Resolved: {stats['resolved']} (wins {stats['wins']}, losses {stats['losses']})")
    lines.append(f"- Hit rate: {stats['hit_rate']:.1%}")
    lines.append(f"- Expectancy: {stats['expectancy']:+.2%}")
    lines.append(f"- Avg return: {stats['avg_return']:+.2%}")
    if stats["max_drawdown_pct"] < 0:
        lines.append(f"- Max drawdown: {stats['max_drawdown_pct']:.2%}")
    lines.append("")

    by_source = stats.get("by_source_layer", {})
    if by_source:
        lines.append("### By source layer")
        lines.append("")
        lines.append("| Source | Count | Resolved | Hit rate | Expectancy |")
        lines.append("|---|---|---|---|---|")
        for layer, layer_stats in sorted(by_source.items()):
            lines.append(
                f"| {layer} | {layer_stats['count']} | {layer_stats['resolved']} "
                f"| {layer_stats['hit_rate']:.1%} | {layer_stats['expectancy']:+.2%} |"
            )
        lines.append("")

    open_pos = open_positions(journal)
    if open_pos:
        lines.append(f"## Open Positions ({len(open_pos)})")
        lines.append("")
        lines.append("| Ticker | Name | Date | Action | Entry | Stop | Source |")
        lines.append("|---|---|---|---|---|---|---|")
        for pos in open_pos[-20:]:
            ticker = clean_text(pos.get("ticker"))
            name = clean_text(pos.get("name")) or ticker
            d = clean_text(pos.get("decision_date"))
            action = clean_text(pos.get("action"))
            entry_p = pos.get("entry_price")
            stop_p = pos.get("stop_loss")
            source = clean_text(pos.get("source_layer"))
            entry_str = f"{entry_p:.3f}" if entry_p is not None else "-"
            stop_str = f"{stop_p:.3f}" if stop_p is not None else "-"
            lines.append(f"| {ticker} | {name} | {d} | {action} | {entry_str} | {stop_str} | {source} |")
        lines.append("")

    recent_decisions = [
        d for d in _entries_by_kind(journal, "decision")
        if _within_lookback(clean_text(d.get("decision_date")), today, 7)
    ]
    if recent_decisions:
        lines.append(f"## Recent Decisions (last 7 days, {len(recent_decisions)})")
        lines.append("")
        lines.append("| Date | Ticker | Name | Action | Trigger | Context |")
        lines.append("|---|---|---|---|---|---|")
        for dec in recent_decisions[-15:]:
            d = clean_text(dec.get("decision_date"))
            ticker = clean_text(dec.get("ticker"))
            name = clean_text(dec.get("name")) or ticker
            action = clean_text(dec.get("action"))
            trigger = dec.get("trigger_price")
            trigger_str = f"{trigger:.3f}" if trigger is not None else "-"
            context = clean_text(dec.get("decision_context"))[:40]
            lines.append(f"| {d} | {ticker} | {name} | {action} | {trigger_str} | {context} |")
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "DEFAULT_JOURNAL_NAME",
    "TERMINAL_OUTCOME_LABELS",
    "VALID_ACTIONS",
    "VALID_MARKETS",
    "VALID_OUTCOME_LABELS",
    "VALID_OUTCOME_TYPES",
    "VALID_SIZE_LABELS",
    "VALID_SOURCE_LAYERS",
    "append_journal_entry",
    "compute_stats",
    "default_journal_path",
    "load_journal",
    "open_positions",
    "record_decision",
    "record_decisions_from_package",
    "record_outcome",
    "record_outcomes_from_postclose",
    "render_trade_journal_markdown",
    "safe_dict",
    "safe_list",
]
