#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from longbridge_action_plan_bridge import screen_result_to_gateway_actions


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
TRADINGAGENTS_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "tradingagents-decision-bridge" / "scripts"
DEFAULT_TIMEOUT_SECONDS = 30
STATEMENT_EXPORT_DIR = Path(".tmp") / "longbridge-statements"
APPLY_ALLOWED_PREFIXES = ("watchlist.", "alert.")
APPLY_ALLOWED_OPERATIONS = {"statement.export"}

CommandRunner = Callable[[list[str], dict[str, str] | None, int], Any]


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"), strict=False)
    return payload if isinstance(payload, dict) else {}


def extract_screen_result(payload: dict[str, Any]) -> dict[str, Any]:
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
    if isinstance(outputs.get("screen_result"), dict):
        return outputs["screen_result"]
    if isinstance(payload.get("screen_result"), dict):
        return payload["screen_result"]
    if isinstance(payload.get("longbridge_screen_result"), dict):
        return payload["longbridge_screen_result"]
    if isinstance(payload.get("ranked_candidates"), list):
        return payload
    return {}


def load_gateway_request(
    *,
    request_json: str | Path | None,
    screen_result_path: str | Path | None = None,
    postclose_review_path: str | Path | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    request = load_json(Path(request_json)) if request_json else {}
    if screen_result_path:
        screen_result = extract_screen_result(load_json(Path(screen_result_path)))
        if screen_result:
            request["screen_result"] = screen_result
    if postclose_review_path:
        request["postclose_review"] = postclose_review_payload(
            {"postclose_review": load_json(Path(postclose_review_path))}
        )
    if source is not None:
        request["source"] = clean_text(source)
    request.setdefault("apply", False)
    return request


def listify(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    if clean_text(value):
        return [clean_text(value)]
    return []


def preview_arg(value: Any) -> str:
    text = clean_text(value)
    if re.fullmatch(r"[A-Za-z0-9._:/\\=-]+", text):
        return text
    return json.dumps(text, ensure_ascii=False)


def command_preview(args: list[str]) -> str:
    return " ".join(["longbridge", *[preview_arg(arg) for arg in args]])


def canonical_operation(action_type: str, operation: str) -> str:
    return f"{clean_text(action_type).lower()}.{clean_text(operation).lower().replace('-', '_')}"


def plan_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def make_plan(
    *,
    operation: str,
    command_args: list[str],
    symbol: str = "",
    account_target: str = "",
    risk_level: str,
    action: dict[str, Any],
    hard_blocked: bool = False,
    can_execute: bool = True,
    read_only: bool = False,
) -> dict[str, Any]:
    payload = {
        "operation": operation,
        "command_args": command_args,
        "symbol": symbol,
        "account_target": account_target,
    }
    return {
        "plan_id": plan_hash(payload),
        "operation": operation,
        "command_preview": command_preview(command_args),
        "command_args": command_args,
        "symbol": symbol,
        "account_target": account_target,
        "risk_level": risk_level,
        "required_confirmation": True,
        "confirmation_text": "",
        "should_apply": False,
        "side_effects": "none",
        "hard_blocked": hard_blocked,
        "can_execute": can_execute,
        "read_only": read_only,
        "source_action": deepcopy(action),
    }


def reject(action: dict[str, Any], operation: str, reason: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "reason": reason,
        "should_apply": False,
        "side_effects": "none",
        "source_action": deepcopy(action),
    }


def action_target(action: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = clean_text(action.get(key))
        if value:
            return value
    return ""


def build_watchlist_plan(action: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw_operation = clean_text(action.get("operation")).lower().replace("-", "_")
    symbols = listify(action.get("symbols") or action.get("symbol"))
    group = action_target(action, "group", "group_id", "group_name", "target_bucket", "name")

    if raw_operation in {"create", "new"}:
        name = action_target(action, "name", "group", "group_name")
        if not name:
            return None, reject(action, "watchlist.create", "watchlist create requires `name` or `group`.")
        args = ["watchlist", "create", name, "--format", "json"]
        return make_plan(
            operation="watchlist.create",
            command_args=args,
            account_target=name,
            risk_level="medium",
            action=action,
        ), None

    if raw_operation in {"delete", "remove_group"}:
        target = action_target(action, "id", "group_id", "group", "group_name", "name")
        if not target:
            return None, reject(action, "watchlist.delete", "watchlist delete requires `id`, `group_id`, or `group`.")
        args = ["watchlist", "delete", target, "--format", "json"]
        return make_plan(
            operation="watchlist.delete",
            command_args=args,
            account_target=target,
            risk_level="high",
            action=action,
        ), None

    if raw_operation in {"add", "add_stock", "add_stocks", "manage", "manage_stocks", "update"}:
        if not group or not symbols:
            return None, reject(action, "watchlist.add_stocks", "watchlist add/update requires `group` and `symbols`.")
        args = ["watchlist", "update", group]
        for symbol in symbols:
            args.extend(["--add", symbol])
        args.extend(["--format", "json"])
        return make_plan(
            operation="watchlist.add_stocks",
            command_args=args,
            symbol=",".join(symbols),
            account_target=group,
            risk_level="medium",
            action=action,
        ), None

    if raw_operation in {"remove", "remove_stock", "remove_stocks"}:
        if not group or not symbols:
            return None, reject(action, "watchlist.remove_stocks", "watchlist remove requires `group` and `symbols`.")
        args = ["watchlist", "update", group]
        for symbol in symbols:
            args.extend(["--remove", symbol])
        args.extend(["--format", "json"])
        return make_plan(
            operation="watchlist.remove_stocks",
            command_args=args,
            symbol=",".join(symbols),
            account_target=group,
            risk_level="medium",
            action=action,
        ), None

    return None, reject(action, "watchlist.unknown", f"Unsupported watchlist operation `{raw_operation}`.")


def build_alert_plan(action: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw_operation = clean_text(action.get("operation")).lower().replace("-", "_")
    symbol = action_target(action, "symbol", "ticker")

    if raw_operation == "add":
        price = clean_text(action.get("price") or action.get("trigger_price"))
        direction = clean_text(action.get("direction") or action.get("trigger_direction")).lower()
        if not symbol or not price or direction not in {"rise", "fall"}:
            return None, reject(action, "alert.add", "alert add requires `symbol`, `price`, and direction `rise` or `fall`.")
        args = ["alert", "add", symbol, "--price", price, "--direction", direction, "--format", "json"]
        return make_plan(
            operation="alert.add",
            command_args=args,
            symbol=symbol,
            account_target="price_alert",
            risk_level="medium",
            action=action,
        ), None

    if raw_operation in {"delete", "enable", "disable"}:
        alert_id = action_target(action, "id", "alert_id")
        if not alert_id:
            return None, reject(action, f"alert.{raw_operation}", f"alert {raw_operation} requires `id`.")
        args = ["alert", raw_operation, alert_id, "--format", "json"]
        return make_plan(
            operation=f"alert.{raw_operation}",
            command_args=args,
            symbol=symbol,
            account_target=alert_id,
            risk_level="high" if raw_operation == "delete" else "medium",
            action=action,
        ), None

    return None, reject(action, "alert.unknown", f"Unsupported alert operation `{raw_operation}`.")


def order_filter_args(action: dict[str, Any]) -> list[str]:
    args: list[str] = []
    if action.get("history"):
        args.append("--history")
    for key, flag in (("start", "--start"), ("end", "--end"), ("symbol", "--symbol")):
        value = clean_text(action.get(key))
        if value:
            args.extend([flag, value])
    args.extend(["--format", "json"])
    return args


def build_order_plan(action: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw_operation = clean_text(action.get("operation") or "list").lower().replace("-", "_")
    symbol = action_target(action, "symbol", "ticker")

    if raw_operation in {"list", "orders"}:
        args = ["order", *order_filter_args(action)]
        return make_plan(
            operation="order.list",
            command_args=args,
            symbol=symbol,
            account_target="orders",
            risk_level="read_only",
            action=action,
            can_execute=True,
            read_only=True,
        ), None

    if raw_operation == "detail":
        order_id = action_target(action, "id", "order_id")
        if not order_id:
            return None, reject(action, "order.detail", "order detail requires `id` or `order_id`.")
        args = ["order", "detail", order_id, "--format", "json"]
        return make_plan(
            operation="order.detail",
            command_args=args,
            symbol=symbol,
            account_target=order_id,
            risk_level="read_only",
            action=action,
            can_execute=True,
            read_only=True,
        ), None

    if raw_operation == "executions":
        args = ["order", "executions", *order_filter_args(action)]
        return make_plan(
            operation="order.executions",
            command_args=args,
            symbol=symbol,
            account_target="executions",
            risk_level="read_only",
            action=action,
            can_execute=True,
            read_only=True,
        ), None

    if raw_operation in {"buy", "sell"}:
        quantity = clean_text(action.get("quantity") or action.get("qty"))
        if not symbol or not quantity:
            return None, reject(action, f"order.{raw_operation}", f"order {raw_operation} requires `symbol` and `quantity`.")
        args = ["order", raw_operation, symbol, quantity]
        price = clean_text(action.get("price"))
        if price:
            args.extend(["--price", price])
        args.extend(["--format", "json"])
        return make_plan(
            operation=f"order.{raw_operation}",
            command_args=args,
            symbol=symbol,
            account_target="trading_account",
            risk_level="critical",
            action=action,
            hard_blocked=True,
            can_execute=False,
        ), None

    if raw_operation == "cancel":
        order_id = action_target(action, "id", "order_id")
        if not order_id:
            return None, reject(action, "order.cancel", "order cancel requires `id` or `order_id`.")
        args = ["order", "cancel", order_id, "--format", "json"]
        return make_plan(
            operation="order.cancel",
            command_args=args,
            symbol=symbol,
            account_target=order_id,
            risk_level="critical",
            action=action,
            hard_blocked=True,
            can_execute=False,
        ), None

    if raw_operation == "replace":
        order_id = action_target(action, "id", "order_id")
        if not order_id:
            return None, reject(action, "order.replace", "order replace requires `id` or `order_id`.")
        args = ["order", "replace", order_id]
        quantity = clean_text(action.get("quantity") or action.get("qty"))
        price = clean_text(action.get("price"))
        if quantity:
            args.extend(["--qty", quantity])
        if price:
            args.extend(["--price", price])
        args.extend(["--format", "json"])
        return make_plan(
            operation="order.replace",
            command_args=args,
            symbol=symbol,
            account_target=order_id,
            risk_level="critical",
            action=action,
            hard_blocked=True,
            can_execute=False,
        ), None

    return None, reject(action, "order.unknown", f"Unsupported order operation `{raw_operation}`.")


def build_dca_plan(action: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw_operation = clean_text(action.get("operation") or "list").lower().replace("-", "_")
    cli_operation = raw_operation.replace("_", "-")
    symbol = action_target(action, "symbol", "ticker")
    plan_id = action_target(action, "id", "plan_id")
    args = ["dca"]

    if raw_operation == "create":
        amount = clean_text(action.get("amount"))
        frequency = clean_text(action.get("frequency"))
        if not symbol or not amount or not frequency:
            return None, reject(action, "dca.create", "dca create requires `symbol`, `amount`, and `frequency`.")
        args.extend(["create", symbol, "--amount", amount, "--frequency", frequency])
        for key, flag in (("day_of_month", "--day-of-month"), ("day_of_week", "--day-of-week")):
            value = clean_text(action.get(key))
            if value:
                args.extend([flag, value])
    elif raw_operation in {"update", "pause", "resume", "stop", "history"}:
        if not plan_id:
            return None, reject(action, f"dca.{raw_operation}", f"dca {raw_operation} requires `id` or `plan_id`.")
        args.extend([cli_operation, plan_id])
    elif raw_operation in {"list", "stats", "calc_date", "check", "set_reminder"}:
        args.append(cli_operation)
        if symbol:
            args.append(symbol)
    else:
        return None, reject(action, "dca.unknown", f"Unsupported dca operation `{raw_operation}`.")

    args.extend(["--format", "json"])
    return make_plan(
        operation=f"dca.{raw_operation}",
        command_args=args,
        symbol=symbol,
        account_target=plan_id or "recurring_investment",
        risk_level="critical",
        action=action,
        hard_blocked=True,
        can_execute=False,
    ), None


def resolve_statement_output_path(output_path: str, repo_root: Path) -> tuple[Path | None, str]:
    if not clean_text(output_path):
        return None, "statement export requires `output_path` under .tmp/longbridge-statements/."
    root = repo_root.resolve(strict=False)
    allowed_dir = (root / STATEMENT_EXPORT_DIR).resolve(strict=False)
    candidate = Path(output_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if resolved != allowed_dir and allowed_dir not in resolved.parents:
        return None, f"statement export output must stay under `{STATEMENT_EXPORT_DIR.as_posix()}/` inside the repo."
    return resolved, ""


def build_statement_plan(
    action: dict[str, Any],
    *,
    repo_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw_operation = clean_text(action.get("operation") or "list").lower().replace("-", "_")
    if raw_operation != "export":
        args = ["statement", "list", "--format", "json"]
        return make_plan(
            operation="statement.list",
            command_args=args,
            account_target="statements",
            risk_level="read_only",
            action=action,
            can_execute=True,
            read_only=True,
        ), None

    output_path, reason = resolve_statement_output_path(clean_text(action.get("output_path") or action.get("output")), repo_root)
    if output_path is None:
        return None, reject(action, "statement.export", reason)
    file_key = clean_text(action.get("file_key"))
    section = clean_text(action.get("section"))
    if not file_key or not section:
        return None, reject(action, "statement.export", "statement export requires `file_key` and `section`.")
    args = ["statement", "export", "--file-key", file_key, "--section", section, "-o", str(output_path), "--format", "json"]
    return make_plan(
        operation="statement.export",
        command_args=args,
        account_target=str(output_path),
        risk_level="high",
        action=action,
    ), None


def screen_actions(request: dict[str, Any]) -> list[dict[str, Any]]:
    screen_result = request.get("screen_result") or request.get("longbridge_screen_result")
    if not isinstance(screen_result, dict):
        return []
    return screen_result_to_gateway_actions(screen_result)


def postclose_review_payload(request: dict[str, Any]) -> dict[str, Any]:
    for key in ("postclose_review", "trading_plan_review", "longbridge_postclose_review"):
        payload = request.get(key)
        if isinstance(payload, dict):
            break
    else:
        payload = {}

    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
    nested_review = outputs.get("postclose_review")
    if isinstance(nested_review, dict):
        return nested_review

    nested_review = payload.get("postclose_review")
    if isinstance(nested_review, dict):
        return nested_review

    return payload


def postclose_review_rows(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    review = postclose_review_payload(request)
    rows = review.get("candidates_reviewed")
    if not isinstance(rows, list):
        rows = review.get("review_results")
    if not isinstance(rows, list):
        return {}
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = clean_text(row.get("symbol"))
        if symbol:
            by_symbol[symbol] = row
    return by_symbol


def postclose_review_allows_action(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    status = clean_text(row.get("review_status") or row.get("status")).lower()
    return bool(row.get("still_valid")) or status == "still_valid"


def skipped_postclose_action(symbol: str, row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "source": "postclose_review",
        "symbol": symbol,
        "review_status": clean_text((row or {}).get("review_status") or (row or {}).get("status") or "missing"),
        "reason": "postclose review status is not eligible for a new account-side action plan",
        "should_apply": False,
        "side_effects": "none",
    }


def filter_screen_actions_by_postclose_review(
    actions: list[dict[str, Any]],
    review_rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not review_rows:
        return actions, []

    filtered: list[dict[str, Any]] = []
    skipped_by_symbol: dict[str, dict[str, Any]] = {}
    for action in actions:
        symbol = clean_text(action.get("symbol"))
        if not symbol and isinstance(action.get("source_candidate"), dict):
            symbol = clean_text(action["source_candidate"].get("symbol"))
        row = review_rows.get(symbol)
        if symbol and postclose_review_allows_action(row):
            filtered.append(action)
        else:
            skipped_by_symbol.setdefault(symbol or "unknown", skipped_postclose_action(symbol or "unknown", row))
    return filtered, list(skipped_by_symbol.values())


def normalized_actions(request: dict[str, Any]) -> list[dict[str, Any]]:
    return normalized_action_bundle(request)[0]


def normalized_action_bundle(request: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actions = [item for item in request.get("actions") or [] if isinstance(item, dict)]
    screen_action_items, skipped = filter_screen_actions_by_postclose_review(
        screen_actions(request),
        postclose_review_rows(request),
    )
    actions.extend(screen_action_items)
    return actions, skipped


def build_plan_for_action(
    action: dict[str, Any],
    *,
    repo_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    action_type = clean_text(action.get("type") or action.get("capability") or "").lower().replace("-", "_")
    if "." in action_type and not clean_text(action.get("operation")):
        action_type, operation = action_type.split(".", 1)
        action = {**action, "type": action_type, "operation": operation}
    if action_type == "watchlist":
        return build_watchlist_plan(action)
    if action_type == "alert":
        return build_alert_plan(action)
    if action_type == "order":
        return build_order_plan(action)
    if action_type == "dca":
        return build_dca_plan(action)
    if action_type == "statement":
        return build_statement_plan(action, repo_root=repo_root)
    operation = canonical_operation(action_type or "unknown", action.get("operation") or "unknown")
    return None, reject(action, operation, f"Unsupported Longbridge action type `{action_type}`.")


def attach_confirmation(action_plans: list[dict[str, Any]]) -> str:
    if not action_plans:
        return ""
    if len(action_plans) == 1:
        confirmation_text = f"APPLY {action_plans[0]['operation']} {action_plans[0]['plan_id']}"
    else:
        batch_hash = plan_hash({"plan_ids": [plan["plan_id"] for plan in action_plans]})
        confirmation_text = f"APPLY {len(action_plans)} LONGBRIDGE ACTIONS {batch_hash}"
    for plan in action_plans:
        plan["confirmation_text"] = confirmation_text
        plan["required_confirmation"] = (
            "Set request.apply=true, set request.confirmation_text exactly to this "
            "action_plan.confirmation_text, and set LONGBRIDGE_ALLOW_WRITE=1."
        )
    return confirmation_text


def apply_blocked_reasons(request: dict[str, Any], action_plans: list[dict[str, Any]], env: dict[str, str] | None) -> list[str]:
    reasons: list[str] = []
    if clean_text((env or {}).get("LONGBRIDGE_ALLOW_WRITE")) != "1":
        reasons.append("LONGBRIDGE_ALLOW_WRITE")
    expected_confirmation = action_plans[0]["confirmation_text"] if action_plans else ""
    if clean_text(request.get("confirmation_text")) != expected_confirmation:
        reasons.append("confirmation_text mismatch")
    not_allowlisted = [
        plan["operation"]
        for plan in action_plans
        if plan.get("operation") not in APPLY_ALLOWED_OPERATIONS
        and not any(clean_text(plan.get("operation")).startswith(prefix) for prefix in APPLY_ALLOWED_PREFIXES)
    ]
    if not_allowlisted:
        reasons.extend(f"operation not allowlisted for apply: {operation}" for operation in not_allowlisted)
    blocked_operations = [plan["operation"] for plan in action_plans if plan.get("hard_blocked")]
    if blocked_operations:
        reasons.append("hard-blocked operations cannot be applied: " + ", ".join(blocked_operations))
    non_executable = [plan["operation"] for plan in action_plans if not plan.get("can_execute")]
    if non_executable:
        reasons.append("non-executable operations cannot be applied: " + ", ".join(non_executable))
    return reasons


def execute_read_only_plans(
    action_plans: list[dict[str, Any]],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for plan in action_plans:
        if not plan.get("read_only"):
            continue
        payload = runner(plan["command_args"], env, DEFAULT_TIMEOUT_SECONDS)
        results.append(
            {
                "plan_id": plan["plan_id"],
                "operation": plan["operation"],
                "command_preview": plan["command_preview"],
                "payload": payload,
                "side_effects": "none",
            }
        )
    return results


def execute_apply(
    action_plans: list[dict[str, Any]],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> list[dict[str, Any]]:
    executed: list[dict[str, Any]] = []
    for plan in action_plans:
        if plan["operation"] == "statement.export":
            Path(plan["account_target"]).parent.mkdir(parents=True, exist_ok=True)
        payload = runner(plan["command_args"], env, DEFAULT_TIMEOUT_SECONDS)
        executed.append(
            {
                "plan_id": plan["plan_id"],
                "operation": plan["operation"],
                "command_preview": plan["command_preview"],
                "payload": payload,
            }
        )
    return executed


def run_longbridge_action_gateway(
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    action_plans: list[dict[str, Any]] = []
    rejected_actions: list[dict[str, Any]] = []
    actions, skipped_actions = normalized_action_bundle(request)
    for action in actions:
        plan, rejection = build_plan_for_action(action, repo_root=root)
        if plan is not None:
            action_plans.append(plan)
        if rejection is not None:
            rejected_actions.append(rejection)

    confirmation_text = attach_confirmation(action_plans)
    result: dict[str, Any] = {
        "request": deepcopy(request),
        "action_plans": action_plans,
        "rejected_actions": rejected_actions,
        "skipped_actions": skipped_actions,
        "confirmation_text": confirmation_text,
        "side_effects": "none",
        "apply": {
            "requested": bool(request.get("apply")),
            "status": "dry_run",
            "blocked_reasons": [],
            "executed": [],
            "command_previews": [plan["command_preview"] for plan in action_plans],
        },
    }

    if request.get("execute_read_only"):
        result["read_only_results"] = execute_read_only_plans(action_plans, runner=runner, env=env)

    if not request.get("apply"):
        return result

    if not action_plans:
        result["apply"]["status"] = "blocked"
        result["apply"]["blocked_reasons"] = ["no valid action plans to apply"]
        return result

    reasons = apply_blocked_reasons(request, action_plans, env)
    if reasons:
        result["apply"]["status"] = "blocked"
        result["apply"]["blocked_reasons"] = reasons
        return result

    result["apply"]["executed"] = execute_apply(action_plans, runner=runner, env=env)
    result["apply"]["status"] = "executed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and gate Longbridge account-write action plans.")
    parser.add_argument("request_json", nargs="?", help="Optional base request JSON.")
    parser.add_argument("--screen-result", help="Optional Longbridge screen/adaptive result JSON.")
    parser.add_argument("--postclose-review", help="Optional post-close review/adaptive result JSON.")
    parser.add_argument("--source", help="Optional source label for the generated request.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()
    if not args.request_json and not args.screen_result and not args.postclose_review:
        parser.error("provide request_json or at least one of --screen-result/--postclose-review")

    if str(TRADINGAGENTS_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(TRADINGAGENTS_SCRIPT_DIR))
    from tradingagents_longbridge_market import run_longbridge_cli

    request = load_gateway_request(
        request_json=args.request_json,
        screen_result_path=args.screen_result,
        postclose_review_path=args.postclose_review,
        source=args.source,
    )
    result = run_longbridge_action_gateway(request, runner=run_longbridge_cli, env=dict(os.environ), repo_root=REPO_ROOT)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
