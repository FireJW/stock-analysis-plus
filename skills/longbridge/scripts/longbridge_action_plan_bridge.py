#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
from typing import Any


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def candidate_context(candidate: dict[str, Any], target_bucket: str) -> dict[str, Any]:
    return {
        "symbol": clean_text(candidate.get("symbol")),
        "screen_score": candidate.get("screen_score"),
        "signal": clean_text(candidate.get("signal")),
        "suggested_watchlist_bucket": target_bucket,
    }


def watchlist_actions_from_tracking_plan(
    candidate: dict[str, Any],
    tracking_plan: dict[str, Any],
    *,
    source: str,
) -> list[dict[str, Any]]:
    symbol = clean_text(candidate.get("symbol"))
    target_bucket = clean_text(tracking_plan.get("suggested_watchlist_bucket"))
    context = candidate_context(candidate, target_bucket)
    actions: list[dict[str, Any]] = []
    for suggestion in tracking_plan.get("watchlist_action_suggestions") or []:
        if not isinstance(suggestion, dict):
            continue
        operation = clean_text(suggestion.get("operation")).lower()
        if operation == "add":
            actions.append(
                {
                    "type": "watchlist",
                    "operation": "add_stocks",
                    "group": clean_text(suggestion.get("target_bucket")) or target_bucket,
                    "symbols": [symbol],
                    "source": source,
                    "source_candidate": context,
                    "source_suggestion": deepcopy(suggestion),
                }
            )
        elif operation == "remove":
            groups = suggestion.get("from_groups") if isinstance(suggestion.get("from_groups"), list) else []
            actions.append(
                {
                    "type": "watchlist",
                    "operation": "remove_stocks",
                    "group": clean_text(groups[0]) if groups else "current_groups",
                    "symbols": [symbol],
                    "source": source,
                    "source_candidate": context,
                    "source_suggestion": deepcopy(suggestion),
                }
            )
    return actions


def alert_actions_from_tracking_plan(
    candidate: dict[str, Any],
    tracking_plan: dict[str, Any],
    *,
    source: str,
) -> list[dict[str, Any]]:
    symbol = clean_text(candidate.get("symbol"))
    target_bucket = clean_text(tracking_plan.get("suggested_watchlist_bucket"))
    context = candidate_context(candidate, target_bucket)
    actions: list[dict[str, Any]] = []
    for suggestion in tracking_plan.get("alert_action_suggestions") or []:
        if not isinstance(suggestion, dict):
            continue
        operation = clean_text(suggestion.get("operation")).lower()
        if operation == "add":
            actions.append(
                {
                    "type": "alert",
                    "operation": "add",
                    "symbol": symbol,
                    "price": suggestion.get("price"),
                    "direction": suggestion.get("direction"),
                    "source": source,
                    "source_candidate": context,
                    "source_suggestion": deepcopy(suggestion),
                }
            )
        elif operation in {"delete", "enable", "disable"}:
            actions.append(
                {
                    "type": "alert",
                    "operation": operation,
                    "id": suggestion.get("id"),
                    "symbol": symbol,
                    "source": source,
                    "source_candidate": context,
                    "source_suggestion": deepcopy(suggestion),
                }
            )
    return actions


def screen_result_to_gateway_actions(
    screen_result: dict[str, Any],
    *,
    source: str = "longbridge-screen",
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for candidate in screen_result.get("ranked_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        tracking_plan = candidate.get("tracking_plan") if isinstance(candidate.get("tracking_plan"), dict) else {}
        actions.extend(watchlist_actions_from_tracking_plan(candidate, tracking_plan, source=source))
        actions.extend(alert_actions_from_tracking_plan(candidate, tracking_plan, source=source))
    return actions
