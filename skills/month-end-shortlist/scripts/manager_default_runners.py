#!/usr/bin/env python3
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from local_stock_pool_runtime import clean_text


ShortlistRunner = Callable[[dict[str, Any]], dict[str, Any]]
PostcloseReviewRunner = Callable[[dict[str, Any], str, str | None], dict[str, Any]]
InstitutionalAuditRunner = Callable[[dict[str, Any]], dict[str, Any]]
TriggerMonitorRunner = Callable[[dict[str, Any], str], dict[str, Any]]
TradeJournalDecisionRunner = Callable[[dict[str, Any], "str | Path"], list[dict[str, Any]]]
TradeJournalOutcomeRunner = Callable[[dict[str, Any], "str | Path"], list[dict[str, Any]]]
DirectionRiskRegisterRunner = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]


def default_shortlist_runner(request: dict[str, Any]) -> dict[str, Any]:
    from month_end_shortlist_runtime import run_month_end_shortlist

    return run_month_end_shortlist(request)


def default_postclose_review_runner(
    shortlist_result: dict[str, Any],
    trade_date: str,
    plan_md: str | None = None,
) -> dict[str, Any]:
    from postclose_review_runtime import run_postclose_review

    return run_postclose_review(shortlist_result, trade_date, plan_md)


def default_source_capability_snapshot(longbridge_binary_path: str = "") -> dict[str, Any]:
    try:
        from institutional_evidence_bundle import build_source_capability_snapshot
    except ModuleNotFoundError:
        return {}
    try:
        overrides = {}
        if clean_text(longbridge_binary_path):
            overrides["host.longbridge_cli"] = clean_text(longbridge_binary_path)
        snapshot = build_source_capability_snapshot(host_binary_overrides=overrides or None)
    except Exception:
        return {}
    return snapshot if isinstance(snapshot, dict) else {}


def default_source_health_probe_snapshot(
    capability_snapshot: dict[str, Any] | None = None,
    *,
    run_live_probes: bool = False,
) -> dict[str, Any]:
    try:
        from institutional_evidence_bundle import build_source_health_probe_snapshot
    except ModuleNotFoundError:
        return {}
    try:
        snapshot = build_source_health_probe_snapshot(
            capability_snapshot=capability_snapshot if isinstance(capability_snapshot, dict) else None,
            run_live_probes=run_live_probes,
        )
    except Exception:
        return {}
    return snapshot if isinstance(snapshot, dict) else {}


def default_institutional_signal_audit_runner(payload: dict[str, Any]) -> dict[str, Any]:
    from institutional_signal_audit import audit_signal_stack

    return audit_signal_stack(payload)


def resolve_trigger_monitor_longbridge_binary(package: dict[str, Any], explicit_binary: str = "") -> str:
    explicit = clean_text(explicit_binary)
    if explicit:
        return explicit
    source_capabilities = package.get("source_capabilities")
    for row in source_capabilities if isinstance(source_capabilities, list) else []:
        if not isinstance(row, dict):
            continue
        if clean_text(row.get("id")) != "host.longbridge_cli":
            continue
        binary_path = clean_text(row.get("binary_path"))
        if binary_path:
            return binary_path
    return "longbridge"


def default_trigger_monitor_runner(package: dict[str, Any], longbridge_binary: str) -> dict[str, Any]:
    from trigger_monitor_runtime import (
        SCHEMA_VERSION,
        detect_trigger_alerts,
        extract_active_trade_cards,
        fetch_quotes,
    )

    cycle_time = datetime.now(UTC).isoformat(timespec="seconds")
    trade_cards = extract_active_trade_cards(package)
    longbridge_tickers = sorted(
        {
            clean_text(card.get("longbridge_ticker")).upper()
            for card in trade_cards
            if clean_text(card.get("longbridge_ticker"))
        }
    )
    quotes = fetch_quotes(longbridge_tickers, clean_text(longbridge_binary) or "longbridge")
    alerts = detect_trigger_alerts(trade_cards, quotes)
    return {
        "schema_version": SCHEMA_VERSION,
        "cycle_time": cycle_time,
        "source": {
            "provider": "longbridge",
            "binary": clean_text(longbridge_binary) or "longbridge",
        },
        "active_cards_count": len(trade_cards),
        "quotes_fetched": len(quotes),
        "alerts": alerts,
    }


def default_trade_journal_decision_runner(
    package: dict[str, Any], journal_path: str | Path
) -> list[dict[str, Any]]:
    from trade_journal_runtime import record_decisions_from_package

    return record_decisions_from_package(package, journal_path)


def default_trade_journal_outcome_runner(
    postclose_review_result: dict[str, Any], journal_path: str | Path
) -> list[dict[str, Any]]:
    from trade_journal_runtime import record_outcomes_from_postclose

    return record_outcomes_from_postclose(postclose_review_result, journal_path)


def default_direction_risk_register_runner(
    register: dict[str, Any], postclose_review_result: dict[str, Any], trade_date: str
) -> dict[str, Any]:
    from direction_risk_register_runtime import update_register

    return update_register(register, postclose_review_result, trade_date)


__all__ = [
    "DirectionRiskRegisterRunner",
    "InstitutionalAuditRunner",
    "PostcloseReviewRunner",
    "ShortlistRunner",
    "TradeJournalDecisionRunner",
    "TradeJournalOutcomeRunner",
    "TriggerMonitorRunner",
    "default_direction_risk_register_runner",
    "default_institutional_signal_audit_runner",
    "default_postclose_review_runner",
    "default_shortlist_runner",
    "default_source_capability_snapshot",
    "default_source_health_probe_snapshot",
    "default_trade_journal_decision_runner",
    "default_trade_journal_outcome_runner",
    "default_trigger_monitor_runner",
    "resolve_trigger_monitor_longbridge_binary",
]
