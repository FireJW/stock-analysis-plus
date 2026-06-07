#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
TRADINGAGENTS_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "tradingagents-decision-bridge" / "scripts"

if str(TRADINGAGENTS_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(TRADINGAGENTS_SCRIPT_DIR))

from longbridge_intraday_monitor_runtime import run_longbridge_intraday_monitor
from longbridge_screen_runtime import run_longbridge_screen
from longbridge_trading_plan_runtime import (
    build_postclose_review,
    build_postclose_review_markdown,
    build_trading_plan_markdown,
    build_trading_plan_report,
)


SCHEMA_VERSION = "longbridge_adaptive_runner/v1"
CommandRunner = Callable[[list[str], dict[str, str] | None, int], Any]

READ_ONLY_ACCOUNT_COMMANDS = {"portfolio", "assets", "positions"}
TASK_ALIASES = {
    "analysis": "stock_analysis",
    "stock": "stock_analysis",
    "stock_analysis": "stock_analysis",
    "market_analysis": "stock_analysis",
    "plan": "trading_plan",
    "trade_plan": "trading_plan",
    "trading_plan": "trading_plan",
    "review": "review",
    "postclose": "review",
    "post_close": "review",
    "replay": "review",
    "portfolio": "portfolio_review",
    "portfolio_review": "portfolio_review",
    "account": "portfolio_review",
    "account_review": "portfolio_review",
}
LAYER_ORDER = [
    "catalyst",
    "valuation",
    "financial_event",
    "ownership_risk",
    "intraday",
    "portfolio",
    "theme_chain",
    "governance_structure",
    "account_health",
    "account_review_plus",
    "execution_preflight",
    "derivative_event_risk",
    "hk_microstructure",
    "quant",
    "watchlist_alert",
    "subscription_sharelist",
]
PLAN_EVIDENCE_LAYER_KEYS = (
    "account_review_plus",
    "execution_preflight",
    "derivative_event_risk",
    "hk_microstructure",
    "governance_structure",
)
WRITE_RISK_ORDER_OPERATIONS = {"buy", "sell", "submit", "cancel", "replace", "modify"}
WRITE_RISK_GENERIC_OPERATIONS = {
    "add",
    "add-stock",
    "add_stocks",
    "create",
    "delete",
    "disable",
    "enable",
    "pin",
    "remove",
    "remove-stock",
    "replace",
    "set",
    "sort",
    "unpin",
    "update",
}
SOCIAL_DYNAMIC_SOURCE_TYPES = {
    "browser_capture",
    "browser_use",
    "chrome_capture",
    "codex_iab",
    "reddit",
    "reddit_bridge",
    "reddit_summary",
    "social",
    "social_media",
    "social_summary",
    "twitter",
    "twitter_x",
    "x",
    "x_index",
    "x_live_index",
    "x_twitter",
}
DYNAMIC_SOURCE_ARTIFACT_KEYS = (
    "path",
    "artifact_path",
    "result_path",
    "result_json",
    "report_path",
    "report_markdown",
    "workflow_artifact",
)
X_INDEX_DYNAMIC_SOURCE_TYPES = {"twitter", "twitter_x", "x", "x_index", "x_live_index", "x_twitter"}
REDDIT_DYNAMIC_SOURCE_TYPES = {"reddit", "reddit_bridge", "reddit_summary"}


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def normalized_key(value: Any) -> str:
    return clean_text(value).lower().replace("-", "_").replace(" ", "_")


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json_value(item) for item in value]
    return value


def _symbol_match_key(symbol: Any) -> str:
    value = clean_text(symbol).upper()
    match = re.match(r"^0*(\d+)\.(US|HK|SH|SZ|SG|HAS)$", value)
    if match:
        return f"{int(match.group(1))}.{match.group(2)}"
    return value


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"), strict=False)
    return payload if isinstance(payload, dict) else {}


def _text_has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _strip_side_effect_boundary_text(text: str) -> str:
    stripped = re.sub(r"\b(?:do not|don't|never|without|no)\b[^.!?。！？；;\n]*", " ", text, flags=re.IGNORECASE)
    stripped = re.sub(r"(?:不要|不得|禁止|不需要|请勿|請勿)[^。！？；;\n]*", " ", stripped)
    return " ".join(stripped.split())


def _is_broker_holding_context(prompt: str) -> bool:
    return _text_has_any(
        prompt,
        ("broker holding", "broker-holding", "brokers", "券商持仓", "经纪持仓"),
    )


def _listify(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    if clean_text(value):
        return [clean_text(value)]
    return []


def _extract_tickers(prompt: str) -> list[str]:
    tickers: list[str] = []
    for match in re.finditer(r"\b([A-Z]{1,6}|\d{1,6})(?:\.(US|HK|SH|SZ|SG|HAS))\b", prompt):
        symbol = match.group(0).upper()
        if symbol not in tickers:
            tickers.append(symbol)
    return tickers


def normalize_task_type(request: dict[str, Any]) -> str:
    explicit = clean_text(request.get("task_type") or request.get("mode")).lower().replace("-", "_")
    if explicit:
        return TASK_ALIASES.get(explicit, explicit)
    prompt = clean_text(request.get("prompt") or request.get("query") or request.get("task"))
    if _text_has_any(prompt, ("复盘", "review", "postclose", "post-close", "回顾")):
        return "review"
    if _text_has_any(prompt, ("交易计划", "trading plan", "trade plan", "trigger", "止损", "入场", "仓位")):
        return "trading_plan"
    if _text_has_any(prompt, ("portfolio", "assets", "positions", "组合", "资产", "持仓")) and not _is_broker_holding_context(prompt):
        return "portfolio_review"
    return "stock_analysis"


def infer_analysis_layers(request: dict[str, Any], *, task_type: str) -> list[str]:
    explicit = _listify(request.get("analysis_layers"))
    if explicit:
        if any(item.lower() == "all" for item in explicit):
            return list(LAYER_ORDER)
        normalized = {layer.lower().replace("-", "_") for layer in explicit}
        if "preflight" in normalized:
            normalized.add("execution_preflight")
        if normalized & {"derivative", "derivatives", "option", "options", "iv", "oi", "warrant", "warrants"}:
            normalized.add("derivative_event_risk")
        if normalized & {"hk", "hk_micro", "microstructure", "broker_holding", "broker-holding", "ah_premium", "ah-premium"}:
            normalized.add("hk_microstructure")
        if normalized & {"governance", "governance_structure", "executive", "executives", "management", "invest_relation", "invest-relation", "fund_exposure", "control_structure"}:
            normalized.add("governance_structure")
        if normalized & {"subscription", "subscriptions", "sharelist", "sharelists", "subscription_sharelist", "sharelist_subscription"}:
            normalized.add("subscription_sharelist")
        return [item for item in LAYER_ORDER if item in normalized]

    prompt = _strip_side_effect_boundary_text(clean_text(request.get("prompt") or request.get("query") or request.get("task")))
    layers: set[str] = {"catalyst", "valuation"}
    if _text_has_any(
        prompt,
        (
            "option",
            "options",
            "iv",
            "oi",
            "call",
            "put",
            "warrant",
            "warrants",
            "derivative",
            "derivatives",
            "期权",
            "隐波",
            "窝轮",
            "牛熊证",
        ),
    ):
        layers.add("derivative_event_risk")
    if _text_has_any(
        prompt,
        (
            "hk microstructure",
            "microstructure",
            "broker holding",
            "broker-holding",
            "brokers",
            "ah premium",
            "ah-premium",
            "participants",
            "港股",
            "券商持仓",
            "经纪持仓",
            "AH溢价",
        ),
    ):
        layers.add("hk_microstructure")
    if _text_has_any(
        prompt,
        (
            "governance",
            "governance structure",
            "executive",
            "management",
            "invest relation",
            "invest-relation",
            "board",
            "control",
            "ownership structure",
            "fund exposure",
            "model governance",
            "治理",
            "治理结构",
            "高管",
            "管理层",
            "投资者关系",
            "控股结构",
            "股权结构",
            "基金暴露",
        ),
    ):
        layers.add("governance_structure")
    if task_type == "trading_plan":
        layers.update({"financial_event", "ownership_risk"})
        if _text_has_any(
            prompt,
            (
                "execution preflight",
                "preflight",
                "overnight eligibility",
                "market status",
                "trading days",
                "trading session",
                "tradability",
                "可执行",
                "可执行性",
                "隔夜",
                "隔夜资格",
                "市场状态",
                "交易日",
                "交易时段",
            ),
        ):
            layers.add("execution_preflight")
    if _text_has_any(prompt, ("filing", "财报", "业绩", "earnings", "financial report", "dividend", "分红")):
        layers.add("financial_event")
    if _text_has_any(prompt, ("insider", "investors", "institutional", "short interest", "short-position", "空头", "内部人", "机构")):
        layers.add("ownership_risk")
    if _text_has_any(
        prompt,
        (
            "资金面",
            "capital flow",
            "intraday",
            "盘中",
            "短线",
            "market-temp",
            "市场温度",
            "order book",
            "depth",
            "bid ask",
            "bid-ask",
            "recent trades",
            "tick-by-tick",
            "trade-stats",
            "trade stats",
            "quote anomaly",
            "quote anomalies",
            "逐笔",
            "盘口",
            "买卖盘",
            "异动",
        ),
    ):
        layers.add("intraday")
    if _text_has_any(prompt, ("portfolio", "assets", "positions", "组合", "资产", "持仓")) and not _is_broker_holding_context(prompt):
        layers.add("portfolio")
    if task_type in {"review", "portfolio_review"} and _text_has_any(
        prompt,
        (
            "order history",
            "trade history",
            "executions",
            "fills",
            "cash-flow",
            "cash flow",
            "profit-analysis",
            "profit analysis",
            "statement list",
            "daily statement",
            "订单",
            "订单历史",
            "成交",
            "现金流",
            "收益分析",
            "盈亏分析",
            "日结单",
            "结单",
            "对账单",
        ),
    ):
        layers.add("account_review_plus")
    if _text_has_any(prompt, ("产业链", "theme", "sector", "constituent", "fund-holder", "shareholder", "板块")):
        layers.add("theme_chain")
    if _text_has_any(prompt, ("margin", "buying power", "max-qty", "statement list", "保证金", "购买力", "最大可买")):
        layers.add("account_health")
    if _text_has_any(prompt, ("quant", "rsi", "macd", "技术指标", "指标")):
        layers.add("quant")
    if _text_has_any(prompt, ("watchlist", "alert", "观察池", "提醒")):
        layers.add("watchlist_alert")
    if _text_has_any(
        prompt,
        (
            "subscription",
            "subscriptions",
            "websocket subscription",
            "sharelist",
            "share list",
            "popular sharelist",
            "community stock list",
            "实时订阅",
            "订阅",
            "共享列表",
            "社区股票列表",
            "热门社区",
        ),
    ):
        layers.add("subscription_sharelist")
    return [layer for layer in LAYER_ORDER if layer in layers]


def infer_adaptive_request(request: dict[str, Any]) -> dict[str, Any]:
    inferred = deepcopy(request)
    prompt = clean_text(inferred.get("prompt") or inferred.get("query") or inferred.get("task"))
    task_type = normalize_task_type(inferred)
    tickers = _listify(inferred.get("tickers") or inferred.get("symbols"))
    if not tickers and prompt:
        tickers = _extract_tickers(prompt)
    inferred["task_type"] = task_type
    inferred["tickers"] = tickers
    inferred["analysis_layers"] = infer_analysis_layers(inferred, task_type=task_type)
    inferred["content_count"] = max(1, min(_to_int(inferred.get("content_count"), 3), 10))
    inferred["session_type"] = clean_text(inferred.get("session_type") or inferred.get("session")) or "premarket"
    return inferred


def _is_a_share_symbol(symbol: str) -> bool:
    return bool(re.match(r"^\d{6}\.(SZ|SH|SS)$", clean_text(symbol), flags=re.IGNORECASE))


def _is_a_share_continuation_plan(inferred: dict[str, Any]) -> bool:
    tickers = _listify(inferred.get("tickers") or inferred.get("symbols"))
    if not any(_is_a_share_symbol(symbol) for symbol in tickers):
        return False
    prompt = clean_text(inferred.get("prompt") or inferred.get("query") or inferred.get("task")).lower()
    session_type = clean_text(inferred.get("session_type") or inferred.get("session")).lower().replace("_", "-")
    if session_type in {"weekend-premarket", "next-trading-day"}:
        return True
    if not ("a股" in prompt or "a 股" in prompt):
        return False
    continuation_hints = (
        "盘前",
        "下一交易日",
        "明天",
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周末",
        "补充",
        "沿用",
        "既有",
        "现有",
        "标准链路",
        "next-trading-day",
        "next trading day",
        "premarket",
        "weekend",
    )
    return any(hint in prompt for hint in continuation_hints)


def dynamic_source_artifact_path(source: dict[str, Any]) -> str:
    for key in DYNAMIC_SOURCE_ARTIFACT_KEYS:
        value = clean_text(source.get(key))
        if value:
            return value
    workflow_artifacts = source.get("workflow_artifacts")
    if isinstance(workflow_artifacts, dict):
        for value in workflow_artifacts.values():
            cleaned = clean_text(value)
            if cleaned:
                return cleaned
    return ""


def resolve_dynamic_source_artifact_path(path_text: str) -> Path:
    expanded = os.path.expandvars(clean_text(path_text))
    path = Path(expanded).expanduser()
    if path.is_absolute():
        return path
    return Path.cwd() / path


def load_dynamic_source_artifact(path_text: str) -> dict[str, Any]:
    path = resolve_dynamic_source_artifact_path(path_text)
    if not path.is_file():
        raise RuntimeError(f"X/Reddit dynamic_candidate_sources artifact path does not exist: {path_text}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"X/Reddit dynamic_candidate_sources artifact is not valid JSON: {path_text}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"X/Reddit dynamic_candidate_sources artifact must be a JSON object: {path_text}"
        )
    return payload


def is_x_index_artifact(payload: dict[str, Any]) -> bool:
    workflow_kind = normalized_key(payload.get("workflow_kind"))
    if workflow_kind in {"x_index", "x_live_index"}:
        return True
    if isinstance(payload.get("run_completeness"), dict) and (
        isinstance(payload.get("x_posts"), list)
        or isinstance(payload.get("session_bootstrap"), dict)
        or isinstance(payload.get("discovery_summary"), dict)
    ):
        return True
    evidence_pack = payload.get("evidence_pack")
    return isinstance(evidence_pack, dict) and isinstance(evidence_pack.get("x_posts"), list)


def is_reddit_bridge_artifact(payload: dict[str, Any]) -> bool:
    if normalized_key(payload.get("workflow_kind")) == "reddit_bridge":
        return True
    return isinstance(payload.get("import_summary"), dict) and (
        isinstance(payload.get("operator_review_queue"), list)
        or isinstance(payload.get("candidate_items"), list)
        or isinstance(payload.get("reddit_items"), list)
    )


def expected_social_artifact_kinds(source: dict[str, Any]) -> set[str]:
    values = [
        source.get("source_type"),
        source.get("workflow_kind"),
        source.get("origin"),
        source.get("provider"),
        source.get("platform"),
        source.get("channel"),
    ]
    normalized_values = {normalized_key(value) for value in values if clean_text(value)}
    expected: set[str] = set()
    if normalized_values & X_INDEX_DYNAMIC_SOURCE_TYPES:
        expected.add("x_index")
    if normalized_values & REDDIT_DYNAMIC_SOURCE_TYPES:
        expected.add("reddit_bridge")
    return expected or {"x_index", "reddit_bridge"}


def validate_social_dynamic_source_artifact(source: dict[str, Any]) -> None:
    artifact_path = dynamic_source_artifact_path(source)
    if not artifact_path:
        raise RuntimeError(
            "X/Reddit dynamic_candidate_sources must be artifact-backed "
            "x-index or reddit-bridge results; summaries alone are not a dynamic candidate refresh."
        )
    payload = load_dynamic_source_artifact(artifact_path)
    expected = expected_social_artifact_kinds(source)
    if ("x_index" in expected and is_x_index_artifact(payload)) or (
        "reddit_bridge" in expected and is_reddit_bridge_artifact(payload)
    ):
        return
    raise RuntimeError(
        "X/Reddit dynamic_candidate_sources artifact does not match the expected "
        f"x-index or reddit-bridge artifact schema: {artifact_path}"
    )


def is_social_dynamic_source(source: dict[str, Any]) -> bool:
    values = [
        source.get("source_type"),
        source.get("workflow_kind"),
        source.get("origin"),
        source.get("provider"),
        source.get("platform"),
        source.get("channel"),
    ]
    return any(normalized_key(value) in SOCIAL_DYNAMIC_SOURCE_TYPES for value in values)


def validate_trading_plan_candidate_provenance(inferred: dict[str, Any]) -> None:
    if clean_text(inferred.get("task_type")) != "trading_plan":
        return
    if not _is_a_share_continuation_plan(inferred):
        return
    plan_context = inferred.get("plan_context") if isinstance(inferred.get("plan_context"), dict) else {}
    dynamic_sources = plan_context.get("dynamic_candidate_sources")
    if isinstance(dynamic_sources, list):
        for source in dynamic_sources:
            if isinstance(source, dict) and is_social_dynamic_source(source):
                validate_social_dynamic_source_artifact(source)
    if isinstance(dynamic_sources, list) and any(
        isinstance(source, dict)
        and clean_text(source.get("source_type"))
        and (
            dynamic_source_artifact_path(source)
            or clean_text(source.get("summary"))
        )
        for source in dynamic_sources
    ):
        return
    if bool(inferred.get("allow_manual_ticker_universe")) and clean_text(inferred.get("candidate_universe_reason")):
        return
    raise RuntimeError(
        "A-share continuation trading plans require plan_context.dynamic_candidate_sources "
        "from a fresh shortlist, market-strength scan, X-index, or equivalent live refresh; "
        "use allow_manual_ticker_universe with candidate_universe_reason only for explicit manual watchlists."
    )


def build_dynamic_source_preflight_entry(source: dict[str, Any]) -> dict[str, Any]:
    artifact_path = dynamic_source_artifact_path(source)
    entry: dict[str, Any] = {
        "source_type": clean_text(source.get("source_type")) or clean_text(source.get("workflow_kind")) or "unknown",
        "is_social_source": is_social_dynamic_source(source),
        "artifact_path": artifact_path,
        "artifact_exists": False,
        "artifact_kind": "",
        "artifact_error": "",
    }
    if artifact_path:
        resolved = resolve_dynamic_source_artifact_path(artifact_path)
        entry["resolved_artifact_path"] = str(resolved)
        entry["artifact_exists"] = resolved.is_file()
    if not entry["is_social_source"] or not artifact_path or not entry["artifact_exists"]:
        return entry
    try:
        payload = load_dynamic_source_artifact(artifact_path)
    except RuntimeError as exc:
        entry["artifact_error"] = clean_text(exc)
        return entry
    if is_x_index_artifact(payload):
        entry["artifact_kind"] = "x_index"
    elif is_reddit_bridge_artifact(payload):
        entry["artifact_kind"] = "reddit_bridge"
    else:
        entry["artifact_kind"] = "unknown"
    entry["status"] = clean_text(payload.get("status"))
    if isinstance(payload.get("run_completeness"), dict):
        entry["run_completeness_status"] = clean_text(payload["run_completeness"].get("status"))
    if isinstance(payload.get("import_summary"), dict):
        entry["payload_source"] = clean_text(payload["import_summary"].get("payload_source"))
    return entry


def build_trading_plan_workflow_preflight(inferred: dict[str, Any]) -> dict[str, Any]:
    plan_context = inferred.get("plan_context") if isinstance(inferred.get("plan_context"), dict) else {}
    dynamic_sources = plan_context.get("dynamic_candidate_sources")
    dynamic_source_items = dynamic_sources if isinstance(dynamic_sources, list) else []
    source_entries = [
        build_dynamic_source_preflight_entry(source)
        for source in dynamic_source_items
        if isinstance(source, dict)
    ]
    social_entries = [entry for entry in source_entries if bool(entry.get("is_social_source"))]
    return {
        "target_trading_date": clean_text(plan_context.get("target_trading_date")),
        "analysis_date": clean_text(inferred.get("analysis_date")),
        "session_type": clean_text(inferred.get("session_type") or inferred.get("session")),
        "tickers": _listify(inferred.get("tickers") or inferred.get("symbols")),
        "source_plan": clean_text(plan_context.get("source_plan")),
        "candidate_universe_source": clean_text(plan_context.get("candidate_universe_source")),
        "candidate_universe_reason": clean_text(inferred.get("candidate_universe_reason")),
        "allow_manual_ticker_universe": bool(inferred.get("allow_manual_ticker_universe")),
        "dynamic_source_count": len(source_entries),
        "social_artifact_count": len(social_entries),
        "dynamic_sources": source_entries,
        "social_artifacts": social_entries,
        "should_apply": False,
        "side_effects": "none",
    }


def _to_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def command_preview(args: list[str]) -> str:
    return "longbridge " + " ".join(clean_text(arg) for arg in args)


def is_write_risk_command(args: list[str]) -> bool:
    if not args:
        return False
    command = clean_text(args[0]).lower()
    operation = clean_text(args[1]).lower().replace("_", "-") if len(args) > 1 else ""
    if command == "dca":
        return True
    if command == "order":
        return operation in WRITE_RISK_ORDER_OPERATIONS
    if command == "statement":
        return operation == "export" or "-o" in args or "--output" in args
    if command in {"watchlist", "alert", "sharelist"}:
        return operation in WRITE_RISK_GENERIC_OPERATIONS
    return False


def build_safe_longbridge_runner(runner: CommandRunner) -> CommandRunner:
    def safe_runner(args: list[str], env: dict[str, str] | None = None, timeout_seconds: int = 20) -> Any:
        if is_write_risk_command(args):
            raise RuntimeError(f"blocked write-risk Longbridge command: {command_preview(args)}")
        return runner(args, env, timeout_seconds)

    return safe_runner


def _screen_request(inferred: dict[str, Any]) -> dict[str, Any]:
    request = {
        "tickers": inferred.get("tickers") or [],
        "analysis_date": clean_text(inferred.get("analysis_date")),
        "analysis_layers": inferred.get("analysis_layers") or [],
        "content_count": inferred.get("content_count") or 3,
    }
    for key in (
        "investor_ciks",
        "investor_top",
        "short_count",
        "insider_count",
        "trade_count",
        "theme_indexes",
        "quant_start",
        "quant_end",
        "quant_period",
        "quant_scripts",
        "indicators",
        "statement_type",
        "statement_limit",
        "account_health_symbol_limit",
        "plan_context",
        "candidate_universe_reason",
        "allow_manual_ticker_universe",
        "lang",
    ):
        if key in inferred:
            request[key] = deepcopy(inferred[key])
    return request


def _candidate_plan_levels(screen_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    levels: dict[str, dict[str, Any]] = {}
    for candidate in screen_result.get("ranked_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        symbol = clean_text(candidate.get("symbol"))
        if not symbol:
            continue
        levels[symbol] = {
            key: candidate.get(key)
            for key in ("trigger_price", "stop_loss", "abandon_below")
            if candidate.get(key) is not None
        }
    return levels


def _fetch_account_snapshot(
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    unavailable: list[dict[str, str]] = []
    outputs: dict[str, Any] = {}
    for command in ("portfolio", "assets", "positions"):
        try:
            outputs[command] = runner([command, "--format", "json"], env, 20)
        except Exception as exc:
            unavailable.append({"command": command, "reason": clean_text(exc)})
            outputs[command] = None
    return {
        **outputs,
        "data_coverage": {
            "portfolio_available": outputs["portfolio"] is not None,
            "assets_available": outputs["assets"] is not None,
            "positions_available": outputs["positions"] is not None,
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def _symbols_from_plan(plan_report: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    for candidate in plan_report.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        symbol = clean_text(candidate.get("symbol"))
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _has_analysis_layer(inferred: dict[str, Any], layer: str) -> bool:
    normalized = {clean_text(item).lower().replace("-", "_") for item in inferred.get("analysis_layers") or []}
    return layer in normalized


def _symbol_targets_for_account_review(
    inferred: dict[str, Any],
    *,
    plan_report: dict[str, Any] | None = None,
    screen_result: dict[str, Any] | None = None,
) -> list[str]:
    symbols: list[str] = []
    for symbol in _listify(inferred.get("tickers") or inferred.get("symbols")):
        if symbol not in symbols:
            symbols.append(symbol)
    for symbol in _symbols_from_plan(plan_report or {}):
        if symbol not in symbols:
            symbols.append(symbol)
    if isinstance(screen_result, dict):
        for candidate in screen_result.get("ranked_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            symbol = clean_text(candidate.get("symbol"))
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def _date_window_for_account_review(inferred: dict[str, Any]) -> dict[str, str]:
    start = clean_text(
        inferred.get("start")
        or inferred.get("start_date")
        or inferred.get("review_start")
        or inferred.get("trade_start")
    )
    end = clean_text(
        inferred.get("end")
        or inferred.get("end_date")
        or inferred.get("review_end")
        or inferred.get("trade_end")
        or inferred.get("review_date")
        or inferred.get("analysis_date")
    )
    if start and not end:
        end = start
    if end and not start:
        start = end
    return {"start": start, "end": end}


def _with_date_window(args: list[str], window: dict[str, str]) -> list[str]:
    result = list(args)
    if clean_text(window.get("start")):
        result.extend(["--start", clean_text(window.get("start"))])
    if clean_text(window.get("end")):
        result.extend(["--end", clean_text(window.get("end"))])
    return result


def _optional_account_payload(
    args: list[str],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    unavailable: list[dict[str, str]],
) -> Any:
    try:
        return runner(args, env, 20)
    except Exception as exc:
        unavailable.append({"command": command_preview(args), "reason": clean_text(exc)})
        return None


def _extend_list_payload(target: list[Any], payload: Any) -> None:
    if isinstance(payload, list):
        target.extend(deepcopy(payload))
    elif payload is not None:
        target.append(deepcopy(payload))


def _fetch_account_review_plus(
    inferred: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    plan_report: dict[str, Any] | None = None,
    screen_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbols = _symbol_targets_for_account_review(inferred, plan_report=plan_report, screen_result=screen_result)
    window = _date_window_for_account_review(inferred)
    statement_limit = max(1, min(_to_int(inferred.get("statement_limit"), 5), 100))
    unavailable: list[dict[str, str]] = []
    order_history: list[Any] = []
    order_executions: list[Any] = []

    for symbol in symbols:
        history_args = _with_date_window(["order", "--history"], window)
        history_args.extend(["--symbol", symbol, "--format", "json"])
        _extend_list_payload(
            order_history,
            _optional_account_payload(history_args, runner=runner, env=env, unavailable=unavailable),
        )

        executions_args = _with_date_window(["order", "executions", "--history"], window)
        executions_args.extend(["--symbol", symbol, "--format", "json"])
        _extend_list_payload(
            order_executions,
            _optional_account_payload(executions_args, runner=runner, env=env, unavailable=unavailable),
        )

    cash_flow = _optional_account_payload(["cash-flow", "--format", "json"], runner=runner, env=env, unavailable=unavailable)
    profit_analysis = _optional_account_payload(["profit-analysis", "--format", "json"], runner=runner, env=env, unavailable=unavailable)
    statement_list = _optional_account_payload(
        ["statement", "list", "--type", "daily", "--limit", str(statement_limit), "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )

    return {
        "symbols": symbols,
        "date_window": window,
        "order_history": order_history,
        "order_executions": order_executions,
        "cash_flow": cash_flow,
        "profit_analysis": profit_analysis,
        "statement_list": statement_list,
        "data_coverage": {
            "order_history_available": bool(order_history),
            "order_executions_available": bool(order_executions),
            "cash_flow_available": cash_flow is not None,
            "profit_analysis_available": profit_analysis is not None,
            "statement_list_available": statement_list is not None,
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def _items_from_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "sharelists", "lists", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _sharelist_ids_from_payload(payload: Any, *, limit: int) -> list[str]:
    ids: list[str] = []
    for item in _items_from_payload(payload):
        if not isinstance(item, dict):
            continue
        sharelist_id = clean_text(item.get("id") or item.get("sharelist_id") or item.get("list_id"))
        if sharelist_id and sharelist_id not in ids:
            ids.append(sharelist_id)
        if len(ids) >= limit:
            break
    return ids


def _fetch_subscription_sharelist_state(
    inferred: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    sharelist_count = max(1, min(_to_int(inferred.get("sharelist_count"), 20), 100))
    popular_count = max(1, min(_to_int(inferred.get("sharelist_popular_count"), 10), 100))
    detail_limit = max(0, min(_to_int(inferred.get("sharelist_detail_limit"), 0), 20))
    unavailable: list[dict[str, str]] = []

    subscriptions = _optional_account_payload(["subscriptions", "--format", "json"], runner=runner, env=env, unavailable=unavailable)
    sharelists = _optional_account_payload(
        ["sharelist", "--count", str(sharelist_count), "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )
    popular_sharelists = _optional_account_payload(
        ["sharelist", "popular", "--count", str(popular_count), "--format", "json"],
        runner=runner,
        env=env,
        unavailable=unavailable,
    )
    sharelist_details: list[Any] = []
    for sharelist_id in _sharelist_ids_from_payload(sharelists, limit=detail_limit):
        detail = _optional_account_payload(
            ["sharelist", "detail", sharelist_id, "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
        _extend_list_payload(sharelist_details, detail)

    return {
        "sharelist_count": sharelist_count,
        "sharelist_popular_count": popular_count,
        "sharelist_detail_limit": detail_limit,
        "subscriptions": subscriptions,
        "sharelists": sharelists,
        "popular_sharelists": popular_sharelists,
        "sharelist_details": sharelist_details,
        "data_coverage": {
            "subscriptions_available": subscriptions is not None,
            "sharelists_available": sharelists is not None,
            "popular_sharelists_available": popular_sharelists is not None,
            "sharelist_details_available": bool(sharelist_details),
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def _append_subscription_sharelist_state(
    result: dict[str, Any],
    inferred: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> None:
    if not _has_analysis_layer(inferred, "subscription_sharelist"):
        return
    state = _fetch_subscription_sharelist_state(inferred, runner=runner, env=env)
    result["workflow_steps"].append("longbridge subscription-sharelist")
    result["outputs"]["subscription_sharelist_state"] = state
    screen_result = result["outputs"].get("screen_result")
    if isinstance(screen_result, dict):
        screen_result["subscription_sharelist_state"] = state


def _market_from_symbol(symbol: str, fallback_market: str = "") -> str:
    match = re.search(r"\.([A-Z]{2,3})$", clean_text(symbol))
    if match:
        return match.group(1).upper()
    return clean_text(fallback_market).upper()


def _market_targets_for_preflight(inferred: dict[str, Any]) -> list[str]:
    markets: list[str] = []
    fallback_market = clean_text(inferred.get("market"))
    for symbol in _listify(inferred.get("tickers") or inferred.get("symbols")):
        market = _market_from_symbol(symbol, fallback_market)
        if market and market not in markets:
            markets.append(market)
    if not markets and fallback_market:
        markets.append(fallback_market.upper())
    return markets


def _date_window_for_preflight(inferred: dict[str, Any]) -> dict[str, str]:
    start = clean_text(
        inferred.get("preflight_start")
        or inferred.get("start")
        or inferred.get("start_date")
        or inferred.get("analysis_date")
    )
    end = clean_text(
        inferred.get("preflight_end")
        or inferred.get("end")
        or inferred.get("end_date")
        or inferred.get("analysis_date")
    )
    if start and not end:
        end = start
    if end and not start:
        start = end
    return {"start": start, "end": end}


def _fetch_execution_preflight(
    inferred: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    symbols = _listify(inferred.get("tickers") or inferred.get("symbols"))
    markets = _market_targets_for_preflight(inferred)
    window = _date_window_for_preflight(inferred)
    unavailable: list[dict[str, str]] = []
    symbol_checks: list[dict[str, Any]] = []
    preflight_fields = "pe,pb,dps_rate,turnover_rate,mktcap,volume_ratio,capital_flow"

    for symbol in symbols:
        symbol_checks.append(
            {
                "symbol": symbol,
                "market": _market_from_symbol(symbol, clean_text(inferred.get("market"))),
                "static": _optional_account_payload(
                    ["static", symbol, "--format", "json"],
                    runner=runner,
                    env=env,
                    unavailable=unavailable,
                ),
                "calc_index": _optional_account_payload(
                    ["calc-index", symbol, "--fields", preflight_fields, "--format", "json"],
                    runner=runner,
                    env=env,
                    unavailable=unavailable,
                ),
            }
        )

    security_list = None
    if "US" in markets:
        security_list = _optional_account_payload(
            ["security-list", "US", "--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )
    else:
        unavailable.append({"command": "security-list US", "reason": "not applicable for non-US markets"})

    market_status = _optional_account_payload(["market-status", "--format", "json"], runner=runner, env=env, unavailable=unavailable)
    trading_session = _optional_account_payload(["trading", "session", "--format", "json"], runner=runner, env=env, unavailable=unavailable)

    trading_days: dict[str, Any] = {}
    for market in markets:
        trading_days[market] = _optional_account_payload(
            _with_date_window(["trading", "days", market], window) + ["--format", "json"],
            runner=runner,
            env=env,
            unavailable=unavailable,
        )

    result = {
        "symbols": symbols,
        "markets": markets,
        "date_window": window,
        "symbol_checks": symbol_checks,
        "security_list": security_list,
        "market_status": market_status,
        "trading_session": trading_session,
        "trading_days": trading_days,
        "data_coverage": {
            "static_available": all(check.get("static") is not None for check in symbol_checks) if symbol_checks else False,
            "calc_index_available": all(check.get("calc_index") is not None for check in symbol_checks) if symbol_checks else False,
            "security_list_available": security_list is not None,
            "market_status_available": market_status is not None,
            "trading_session_available": trading_session is not None,
            "trading_days_available": bool(trading_days),
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }
    return result


def _attach_symbol_layer_to_candidates(
    screen_result: dict[str, Any],
    *,
    layer_name: str,
    records: list[dict[str, Any]],
) -> None:
    by_symbol = {
        _symbol_match_key(record.get("symbol")): record
        for record in records
        if isinstance(record, dict) and _symbol_match_key(record.get("symbol"))
    }
    for candidate in screen_result.get("ranked_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        symbol = _symbol_match_key(candidate.get("symbol"))
        if symbol not in by_symbol:
            continue
        candidate[layer_name] = deepcopy(by_symbol[symbol])
        qualitative = deepcopy(candidate.get("qualitative_evaluation") or {})
        qualitative[layer_name] = deepcopy(by_symbol[symbol])
        candidate["qualitative_evaluation"] = qualitative


def _merge_layer_evidence_into_plan(
    plan: dict[str, Any],
    *,
    screen_result: dict[str, Any],
    outputs: dict[str, Any] | None = None,
) -> None:
    source_candidates = {
        _symbol_match_key(candidate.get("symbol")): candidate
        for candidate in screen_result.get("ranked_candidates") or []
        if isinstance(candidate, dict) and _symbol_match_key(candidate.get("symbol"))
    }
    output_sources = outputs if isinstance(outputs, dict) else {}

    def merge_from_records(target: dict[str, Any], layer_name: str, records: Any) -> None:
        if not isinstance(records, list):
            return
        by_symbol = {
            _symbol_match_key(record.get("symbol")): record
            for record in records
            if isinstance(record, dict) and _symbol_match_key(record.get("symbol"))
        }
        symbol = _symbol_match_key(target.get("symbol"))
        record = by_symbol.get(symbol)
        if not record:
            return
        qualitative = target.get("qualitative_evidence")
        if not isinstance(qualitative, dict):
            qualitative = {}
            target["qualitative_evidence"] = qualitative
        qualitative[layer_name] = deepcopy(record)

    def merge_candidate(target: dict[str, Any]) -> None:
        symbol = clean_text(target.get("symbol"))
        source = source_candidates.get(symbol)
        if not source:
            return
        qualitative = target.get("qualitative_evidence")
        if not isinstance(qualitative, dict):
            qualitative = {}
            target["qualitative_evidence"] = qualitative
        for key in PLAN_EVIDENCE_LAYER_KEYS:
            value = source.get(key)
            if isinstance(value, dict):
                qualitative[key] = deepcopy(value)
        merge_from_records(target, "derivative_event_risk", (output_sources.get("derivative_event_risk") or {}).get("symbol_risks"))
        merge_from_records(target, "hk_microstructure", (output_sources.get("hk_microstructure") or {}).get("symbol_microstructure"))
        merge_from_records(target, "execution_preflight", (output_sources.get("preflight") or {}).get("symbol_checks"))

    for candidate in plan.get("candidates") or []:
        if isinstance(candidate, dict):
            merge_candidate(candidate)

    for candidate in plan.get("qualitative_evidence") or []:
        if isinstance(candidate, dict):
            symbol = _symbol_match_key(candidate.get("symbol"))
            source = source_candidates.get(symbol)
            if not source:
                continue
            qualitative = candidate.get("qualitative_evidence")
            if not isinstance(qualitative, dict):
                qualitative = {}
                candidate["qualitative_evidence"] = qualitative
            for key in PLAN_EVIDENCE_LAYER_KEYS:
                value = source.get(key)
                if isinstance(value, dict):
                    qualitative[key] = deepcopy(value)
            merge_from_records(candidate, "derivative_event_risk", (output_sources.get("derivative_event_risk") or {}).get("symbol_risks"))
            merge_from_records(candidate, "hk_microstructure", (output_sources.get("hk_microstructure") or {}).get("symbol_microstructure"))
            merge_from_records(candidate, "execution_preflight", (output_sources.get("preflight") or {}).get("symbol_checks"))


def _inject_symbol_records_into_plan(
    plan: dict[str, Any],
    *,
    layer_name: str,
    records: Any,
) -> None:
    if not isinstance(records, list):
        return
    by_symbol = {
        _symbol_match_key(record.get("symbol")): record
        for record in records
        if isinstance(record, dict) and _symbol_match_key(record.get("symbol"))
    }

    def merge_entry(entry: dict[str, Any]) -> None:
        symbol = _symbol_match_key(entry.get("symbol"))
        record = by_symbol.get(symbol)
        if not record:
            return
        entry[layer_name] = deepcopy(record)
        qualitative = deepcopy(entry.get("qualitative_evidence") or {})
        qualitative[layer_name] = deepcopy(record)
        entry["qualitative_evidence"] = qualitative

    for candidate in plan.get("candidates") or []:
        if isinstance(candidate, dict):
            merge_entry(candidate)
    for candidate in plan.get("qualitative_evidence") or []:
        if isinstance(candidate, dict):
            merge_entry(candidate)


def _collect_governance_structure(screen_result: dict[str, Any]) -> dict[str, Any]:
    symbol_structures: list[dict[str, Any]] = []
    for candidate in screen_result.get("ranked_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        symbol = clean_text(candidate.get("symbol"))
        theme_chain = candidate.get("theme_chain_analysis") if isinstance(candidate.get("theme_chain_analysis"), dict) else {}
        governance = theme_chain.get("governance_structure") if isinstance(theme_chain.get("governance_structure"), dict) else {}
        if not governance:
            continue
        symbol_structures.append(
            {
                "symbol": symbol,
                "governance_structure": deepcopy(governance),
                "theme_chain_score": theme_chain.get("theme_chain_score"),
                "data_coverage": deepcopy(governance.get("data_coverage") if isinstance(governance.get("data_coverage"), dict) else {}),
            }
        )
    return {
        "symbols": [item["symbol"] for item in symbol_structures],
        "symbol_structures": symbol_structures,
        "data_coverage": {
            "governance_structure_available": bool(symbol_structures),
            "executive_available": any((item.get("data_coverage") or {}).get("executive_available") for item in symbol_structures),
            "invest_relation_available": any((item.get("data_coverage") or {}).get("invest_relation_available") for item in symbol_structures),
        },
        "should_apply": False,
        "side_effects": "none",
    }


def _fetch_derivative_event_risk(
    inferred: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    symbols = _listify(inferred.get("tickers") or inferred.get("symbols"))
    derivative_fields = "iv,delta,gamma,theta,vega,oi,exp,strike,premium,effective_leverage"
    unavailable: list[dict[str, str]] = []
    symbol_risks: list[dict[str, Any]] = []

    for symbol in symbols:
        market = _market_from_symbol(symbol, clean_text(inferred.get("market")))
        record: dict[str, Any] = {
            "symbol": symbol,
            "market": market,
            "option": None,
            "warrant": None,
            "calc_index": None,
            "should_apply": False,
            "side_effects": "none",
        }
        if market == "US":
            record["option"] = {
                "chain": _optional_account_payload(
                    ["option", "chain", symbol, "--format", "json"],
                    runner=runner,
                    env=env,
                    unavailable=unavailable,
                ),
                "quote": _optional_account_payload(
                    ["option", "quote", symbol, "--format", "json"],
                    runner=runner,
                    env=env,
                    unavailable=unavailable,
                ),
                "volume": _optional_account_payload(
                    ["option", "volume", symbol, "--format", "json"],
                    runner=runner,
                    env=env,
                    unavailable=unavailable,
                ),
            }
            record["calc_index"] = _optional_account_payload(
                ["calc-index", symbol, "--fields", derivative_fields, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        elif market == "HK":
            record["warrant"] = {
                "list": _optional_account_payload(
                    ["warrant", symbol, "--format", "json"],
                    runner=runner,
                    env=env,
                    unavailable=unavailable,
                ),
                "quote": _optional_account_payload(
                    ["warrant", "quote", symbol, "--format", "json"],
                    runner=runner,
                    env=env,
                    unavailable=unavailable,
                ),
                "issuers": _optional_account_payload(
                    ["warrant", "issuers", "--format", "json"],
                    runner=runner,
                    env=env,
                    unavailable=unavailable,
                ),
            }
            record["calc_index"] = _optional_account_payload(
                ["calc-index", symbol, "--fields", derivative_fields, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        else:
            unavailable.append(
                {
                    "command": "derivative_event_risk",
                    "symbol": symbol,
                    "market": market,
                    "reason": "not applicable for non-US/HK markets",
                }
            )
        symbol_risks.append(record)

    option_available = any(isinstance(record.get("option"), dict) for record in symbol_risks)
    warrant_available = any(isinstance(record.get("warrant"), dict) for record in symbol_risks)
    calc_index_available = any(record.get("calc_index") is not None for record in symbol_risks)
    return {
        "symbols": symbols,
        "symbol_risks": symbol_risks,
        "data_coverage": {
            "option_available": option_available,
            "warrant_available": warrant_available,
            "calc_index_available": calc_index_available,
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def _hk_symbol_targets(inferred: dict[str, Any]) -> list[str]:
    return [
        symbol
        for symbol in _listify(inferred.get("tickers") or inferred.get("symbols"))
        if _market_from_symbol(symbol, clean_text(inferred.get("market"))) == "HK"
    ]


def _fetch_hk_microstructure(
    inferred: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    all_symbols = _listify(inferred.get("tickers") or inferred.get("symbols"))
    hk_symbols = _hk_symbol_targets(inferred)
    broker_id = clean_text(inferred.get("broker_id") or inferred.get("broker"))
    ah_symbols = _listify(inferred.get("ah_premium_symbols") or inferred.get("ah_symbols"))
    if not ah_symbols:
        ah_symbols = list(hk_symbols)
    unavailable: list[dict[str, str]] = []
    symbol_microstructure: list[dict[str, Any]] = []

    if not hk_symbols:
        unavailable.append(
            {
                "command": "hk_microstructure",
                "reason": "not applicable because no HK symbols were supplied",
            }
        )
        return {
            "symbols": all_symbols,
            "hk_symbols": [],
            "ah_premium_symbols": [],
            "symbol_microstructure": [],
            "ah_premium": {},
            "participants": None,
            "data_coverage": {
                "brokers_available": False,
                "broker_holding_available": False,
                "broker_holding_detail_available": False,
                "broker_holding_daily_available": False,
                "ah_premium_available": False,
                "participants_available": False,
            },
            "unavailable": unavailable,
            "should_apply": False,
            "side_effects": "none",
        }

    for symbol in hk_symbols:
        record = {
            "symbol": symbol,
            "brokers": _optional_account_payload(
                ["brokers", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            ),
            "broker_holding": _optional_account_payload(
                ["broker-holding", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            ),
            "broker_holding_detail": _optional_account_payload(
                ["broker-holding", "detail", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            ),
            "broker_holding_daily": None,
            "should_apply": False,
            "side_effects": "none",
        }
        if broker_id:
            record["broker_holding_daily"] = _optional_account_payload(
                ["broker-holding", "daily", symbol, "--broker", broker_id, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            )
        symbol_microstructure.append(record)

    ah_premium: dict[str, Any] = {}
    for symbol in ah_symbols:
        if _market_from_symbol(symbol, "HK") != "HK":
            unavailable.append({"command": "ah-premium", "symbol": symbol, "reason": "not an HK symbol"})
            continue
        ah_premium[symbol] = {
            "snapshot": _optional_account_payload(
                ["ah-premium", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            ),
            "intraday": _optional_account_payload(
                ["ah-premium", "intraday", symbol, "--format", "json"],
                runner=runner,
                env=env,
                unavailable=unavailable,
            ),
        }

    participants = _optional_account_payload(["participants", "--format", "json"], runner=runner, env=env, unavailable=unavailable)
    return {
        "symbols": all_symbols,
        "hk_symbols": hk_symbols,
        "ah_premium_symbols": ah_symbols,
        "symbol_microstructure": symbol_microstructure,
        "ah_premium": ah_premium,
        "participants": participants,
        "data_coverage": {
            "brokers_available": any(record.get("brokers") is not None for record in symbol_microstructure),
            "broker_holding_available": any(record.get("broker_holding") is not None for record in symbol_microstructure),
            "broker_holding_detail_available": any(record.get("broker_holding_detail") is not None for record in symbol_microstructure),
            "broker_holding_daily_available": any(record.get("broker_holding_daily") is not None for record in symbol_microstructure),
            "ah_premium_available": bool(ah_premium),
            "participants_available": participants is not None,
        },
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def _first_quote_item(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    if isinstance(payload, dict):
        return payload
    return {}


def _fetch_quote_actuals(
    plan_report: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
    review_date: str,
) -> dict[str, Any]:
    prices: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, str]] = []
    for symbol in _symbols_from_plan(plan_report):
        try:
            payload = runner(["quote", "--format", "json", symbol], env, 20)
        except Exception as exc:
            unavailable.append({"command": "quote", "symbol": symbol, "reason": clean_text(exc)})
            continue
        item = _first_quote_item(payload)
        prices[symbol] = {
            "symbol": symbol,
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": item.get("close") or item.get("last") or item.get("last_price"),
            "last": item.get("last") or item.get("last_price"),
            "volume": item.get("volume"),
            "source": "longbridge quote",
        }
    return {
        "review_date": review_date,
        "prices": prices,
        "unavailable": unavailable,
        "data_coverage": {"quote_actuals_available": len(prices)},
    }


def _run_screen(
    inferred: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    tickers = inferred.get("tickers") or []
    if not tickers:
        raise RuntimeError("Longbridge adaptive runner requires `tickers` for stock analysis or trading-plan tasks.")
    return run_longbridge_screen(_screen_request(inferred), runner=runner, env=env)


def _promote_screen_outputs(result: dict[str, Any], screen_result: dict[str, Any]) -> None:
    for key in ("account_state", "account_health", "quant_analysis"):
        if key in screen_result:
            result["outputs"][key] = deepcopy(screen_result[key])


def _collect_intraday_confirmation_state(screen_result: dict[str, Any]) -> dict[str, Any]:
    confirmations: list[dict[str, Any]] = []
    coverage_totals: dict[str, bool] = {
        "capital_available": False,
        "depth_available": False,
        "trades_available": False,
        "trade_stats_available": False,
        "anomaly_available": False,
        "market_temp_available": False,
    }
    unavailable: list[Any] = []
    for candidate in screen_result.get("ranked_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        confirmation = candidate.get("intraday_confirmation")
        if not isinstance(confirmation, dict):
            continue
        symbol = clean_text(candidate.get("symbol"))
        confirmations.append(
            {
                "symbol": symbol,
                "short_term_confirmation_score": confirmation.get("short_term_confirmation_score"),
                "intraday_confirmation": deepcopy(confirmation),
            }
        )
        coverage = confirmation.get("data_coverage") if isinstance(confirmation.get("data_coverage"), dict) else {}
        for key in coverage_totals:
            coverage_totals[key] = coverage_totals[key] or bool(coverage.get(key))
        if isinstance(confirmation.get("unavailable"), list):
            unavailable.extend(deepcopy(confirmation["unavailable"]))
    return {
        "symbols": [item["symbol"] for item in confirmations if item.get("symbol")],
        "symbol_confirmations": confirmations,
        "data_coverage": coverage_totals,
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def _append_intraday_confirmation_state(result: dict[str, Any], inferred: dict[str, Any]) -> None:
    if not _has_analysis_layer(inferred, "intraday"):
        return
    screen_result = result["outputs"].get("screen_result")
    if not isinstance(screen_result, dict):
        return
    state = _collect_intraday_confirmation_state(screen_result)
    if state["symbol_confirmations"]:
        result["outputs"]["intraday_confirmation_state"] = state


def run_longbridge_adaptive_task(
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    inferred = infer_adaptive_request(request)
    validate_trading_plan_candidate_provenance(inferred)
    safe_runner = build_safe_longbridge_runner(runner)
    task_type = clean_text(inferred.get("task_type"))
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_type": task_type,
        "request": deepcopy(request),
        "inferred_request": deepcopy(inferred),
        "workflow_steps": [],
        "outputs": {},
        "should_apply": False,
        "side_effects": "none",
    }
    if task_type == "trading_plan":
        result["workflow_steps"].append("longbridge-adaptive preflight")
        result["outputs"]["workflow_preflight"] = build_trading_plan_workflow_preflight(inferred)

    if task_type == "portfolio_review":
        result["workflow_steps"].extend(["longbridge portfolio", "longbridge assets", "longbridge positions"])
        result["outputs"]["account_snapshot"] = _fetch_account_snapshot(runner=safe_runner, env=env)
        if _has_analysis_layer(inferred, "account_review_plus"):
            result["workflow_steps"].append("longbridge account-review-plus")
            result["outputs"]["account_review_plus"] = _fetch_account_review_plus(
                inferred,
                runner=safe_runner,
                env=env,
            )
        _append_subscription_sharelist_state(result, inferred, runner=safe_runner, env=env)
        return _sanitize_json_value(result)

    if task_type == "review":
        plan_report = deepcopy(request.get("plan_report") if isinstance(request.get("plan_report"), dict) else {})
        if not plan_report:
            screen_result = deepcopy(request.get("screen_result") if isinstance(request.get("screen_result"), dict) else {})
            if not screen_result:
                screen_result = _run_screen(inferred, runner=safe_runner, env=env)
                result["workflow_steps"].append("longbridge-screen")
                result["outputs"]["screen_result"] = screen_result
            plan_report = build_trading_plan_report(screen_result, session_type="premarket")
            result["workflow_steps"].append("longbridge-trading-plan")
            result["outputs"]["trading_plan_report"] = plan_report
        if _has_analysis_layer(inferred, "account_review_plus"):
            result["workflow_steps"].append("longbridge account-review-plus")
            result["outputs"]["account_review_plus"] = _fetch_account_review_plus(
                inferred,
                runner=safe_runner,
                env=env,
                plan_report=plan_report,
                screen_result=result["outputs"].get("screen_result")
                if isinstance(result["outputs"].get("screen_result"), dict)
                else None,
            )
        actuals = deepcopy(request.get("actuals") if isinstance(request.get("actuals"), dict) else {})
        if not actuals:
            actuals = _fetch_quote_actuals(
                plan_report,
                runner=safe_runner,
                env=env,
                review_date=clean_text(inferred.get("review_date")) or clean_text(inferred.get("analysis_date")),
            )
            result["workflow_steps"].append("longbridge quote actuals")
        review = build_postclose_review(
            plan_report,
            actuals,
            review_date=clean_text(inferred.get("review_date")) or None,
        )
        result["workflow_steps"].append("longbridge-trading-plan review")
        result["outputs"]["postclose_review"] = review
        result["outputs"]["actuals"] = actuals
        _append_subscription_sharelist_state(result, inferred, runner=safe_runner, env=env)
        return _sanitize_json_value(result)

    screen_result = _run_screen(inferred, runner=safe_runner, env=env)
    result["workflow_steps"].append("longbridge-screen")
    result["outputs"]["screen_result"] = screen_result
    _promote_screen_outputs(result, screen_result)
    _append_subscription_sharelist_state(result, inferred, runner=safe_runner, env=env)
    _append_intraday_confirmation_state(result, inferred)

    if _has_analysis_layer(inferred, "governance_structure"):
        governance_structure = _collect_governance_structure(screen_result)
        screen_result["governance_structure"] = governance_structure
        result["workflow_steps"].append("longbridge governance-structure")
        result["outputs"]["governance_structure"] = governance_structure

    if task_type == "trading_plan" and _has_analysis_layer(inferred, "execution_preflight"):
        preflight = _fetch_execution_preflight(inferred, runner=safe_runner, env=env)
        screen_result["execution_preflight"] = preflight
        result["workflow_steps"].append("longbridge execution-preflight")
        result["outputs"]["preflight"] = preflight

    if _has_analysis_layer(inferred, "derivative_event_risk"):
        derivative_event_risk = _fetch_derivative_event_risk(inferred, runner=safe_runner, env=env)
        screen_result["derivative_event_risk"] = derivative_event_risk
        _attach_symbol_layer_to_candidates(
            screen_result,
            layer_name="derivative_event_risk",
            records=derivative_event_risk.get("symbol_risks") or [],
        )
        result["workflow_steps"].append("longbridge derivative-event-risk")
        result["outputs"]["derivative_event_risk"] = derivative_event_risk

    if _has_analysis_layer(inferred, "hk_microstructure"):
        hk_microstructure = _fetch_hk_microstructure(inferred, runner=safe_runner, env=env)
        screen_result["hk_microstructure"] = hk_microstructure
        _attach_symbol_layer_to_candidates(
            screen_result,
            layer_name="hk_microstructure",
            records=hk_microstructure.get("symbol_microstructure") or [],
        )
        result["workflow_steps"].append("longbridge hk-microstructure")
        result["outputs"]["hk_microstructure"] = hk_microstructure

    if task_type == "trading_plan":
        session_type = clean_text(inferred.get("session_type")) or "premarket"
        intraday_monitor_result: dict[str, Any] | None = None
        if session_type == "intraday":
            intraday_request = {
                "tickers": inferred.get("tickers") or [],
                "analysis_date": clean_text(inferred.get("analysis_date")),
                "market": clean_text(inferred.get("market")),
                "session": clean_text(inferred.get("intraday_session") or "intraday"),
                "plan_levels": _candidate_plan_levels(screen_result),
            }
            intraday_monitor_result = run_longbridge_intraday_monitor(intraday_request, runner=safe_runner, env=env)
            result["workflow_steps"].append("longbridge-intraday-monitor")
            result["outputs"]["intraday_monitor_result"] = intraday_monitor_result
        plan = build_trading_plan_report(
            screen_result,
            session_type=session_type,
            intraday_monitor_result=intraday_monitor_result,
        )
        if isinstance(result["outputs"].get("derivative_event_risk"), dict):
            _inject_symbol_records_into_plan(
                plan,
                layer_name="derivative_event_risk",
                records=(result["outputs"]["derivative_event_risk"].get("symbol_risks") or []),
            )
        if isinstance(result["outputs"].get("hk_microstructure"), dict):
            _inject_symbol_records_into_plan(
                plan,
                layer_name="hk_microstructure",
                records=(result["outputs"]["hk_microstructure"].get("symbol_microstructure") or []),
            )
        if isinstance(result["outputs"].get("preflight"), dict):
            _inject_symbol_records_into_plan(
                plan,
                layer_name="execution_preflight",
                records=(result["outputs"]["preflight"].get("symbol_checks") or []),
            )
        _merge_layer_evidence_into_plan(plan, screen_result=screen_result, outputs=result["outputs"])
        result["workflow_steps"].append("longbridge-trading-plan")
        result["outputs"]["trading_plan_report"] = plan
    return _sanitize_json_value(result)


def _readable_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _format_level(value: Any) -> str:
    parsed = _readable_float(value)
    if parsed is None:
        return "-"
    return f"{parsed:.2f}".rstrip("0").rstrip(".")


def _plan_candidate_score(candidate: dict[str, Any]) -> float:
    scores = candidate.get("scores") if isinstance(candidate.get("scores"), dict) else {}
    for key in ("workbench_score", "screen_score"):
        value = _readable_float(scores.get(key))
        if value is not None:
            return value
    return 0.0


def _plan_candidate_display(candidate: dict[str, Any]) -> str:
    symbol = clean_text(candidate.get("symbol"))
    name = clean_text(candidate.get("name"))
    if symbol and name and name != symbol:
        return f"`{symbol}` {name}"
    return f"`{symbol}`" if symbol else name


def _candidate_theme_hint(candidate: dict[str, Any]) -> str:
    symbol = clean_text(candidate.get("symbol"))
    name = clean_text(candidate.get("name"))
    theme_by_symbol = {
        "002384.SZ": "PCB/CPO/AI 硬件",
        "002913.SZ": "PCB/AI 硬件",
        "002130.SZ": "AI 硬件/高速连接",
        "300162.SZ": "光电/AI 硬件观察",
        "000066.SZ": "国产算力/AI 硬件",
        "300115.SZ": "消费电子/AI 硬件",
        "688362.SH": "半导体封测",
        "002050.SZ": "机器人/热管理",
        "002151.SZ": "卫星导航/商业航天",
        "688568.SH": "卫星遥感/商业航天",
        "600590.SH": "电力设备/军工",
        "603505.SH": "战略资源",
        "605090.SH": "能源/LNG",
        "300589.SZ": "船舶/航运弹性",
        "002150.SZ": "电力设备",
        "688032.SH": "电力设备",
    }
    if symbol in theme_by_symbol:
        return theme_by_symbol[symbol]
    if any(keyword in name for keyword in ("航天", "星图", "北斗")):
        return "商业航天/卫星"
    if any(keyword in name for keyword in ("精密", "电子", "光电", "长城")):
        return "AI 硬件/电子链"
    if any(keyword in name for keyword in ("能源", "船", "海能", "轮船")):
        return "能源/航运"
    if any(keyword in name for keyword in ("资源", "稀土", "金石")):
        return "战略资源"
    return "强势异动候选"


def _candidate_action_label(candidate: dict[str, Any]) -> str:
    signal = clean_text(candidate.get("signal"))
    score = _plan_candidate_score(candidate)
    if signal == "momentum_breakout" and score >= 70:
        return "执行候选：只在触发位上方且成交/资金确认后试仓"
    if signal == "momentum_breakout":
        return "弱执行候选：需板块联动确认"
    if signal == "watch_reclaim":
        return "观察修复：重新站稳触发位前不主动加仓"
    if signal == "rebound_only":
        return "默认观望：只看反弹，不占主线仓位"
    return "观察：等待价格、成交、资金三确认"


def _candidate_tier_rows(candidates: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]], str]]:
    execution = [
        item
        for item in candidates
        if clean_text(item.get("signal")) == "momentum_breakout" and _plan_candidate_score(item) >= 70
    ]
    watch = [
        item
        for item in candidates
        if item not in execution
        and (clean_text(item.get("signal")) in {"momentum_breakout", "watch_reclaim"} or _plan_candidate_score(item) >= 30)
    ]
    defensive = [item for item in candidates if item not in execution and item not in watch]
    return [
        ("第一层", execution, "可执行候选，但仍要等触发位、成交和资金确认"),
        ("第二层", watch, "观察/修复层，不能替代第一层主线"),
        ("第三层", defensive, "默认观望或放弃层，只保留盘中异动观察"),
    ]


def _candidate_direction(candidate: dict[str, Any]) -> str:
    theme = _candidate_theme_hint(candidate)
    if any(keyword in theme for keyword in ("AI", "PCB", "电子", "半导体", "机器人", "热管理", "光电")):
        return "AI 硬件 / CPO / PCB / 电子链"
    if any(keyword in theme for keyword in ("商业航天", "卫星", "军工")):
        return "商业航天 / 卫星 / 军工"
    if "资源" in theme:
        return "战略资源"
    if any(keyword in theme for keyword in ("能源", "航运", "船舶")):
        return "能源 / 航运"
    if "电力设备" in theme:
        return "电力设备"
    return "其他强势异动"


def _direction_action(direction: str, items: list[dict[str, Any]]) -> str:
    best = max((_plan_candidate_score(item) for item in items), default=0.0)
    has_breakout = any(clean_text(item.get("signal")) == "momentum_breakout" for item in items)
    if direction.startswith("AI") and has_breakout:
        return "主观察线：只做承接确认，不追缩量高开"
    if direction.startswith("商业航天") and has_breakout:
        return "事件观察线：需板块联动和触发位确认后才升级"
    if direction == "战略资源":
        return "次观察线：不能只靠单票异动升主线"
    if direction == "能源 / 航运":
        return "事件弹性线：突破触发位前不主线化"
    if best >= 70 and has_breakout:
        return "强势候选线：等开盘换手和资金确认"
    return "观察线：默认不占主线仓位"


def _direction_group_rows(candidates: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]], str]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        groups.setdefault(_candidate_direction(candidate), []).append(candidate)
    rows = []
    for direction, items in groups.items():
        items.sort(key=_plan_candidate_score, reverse=True)
        rows.append((direction, items, _direction_action(direction, items)))
    rows.sort(key=lambda row: max((_plan_candidate_score(item) for item in row[1]), default=0.0), reverse=True)
    return rows


def build_readable_trading_plan_markdown(result: dict[str, Any]) -> str:
    outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
    report = outputs.get("trading_plan_report") if isinstance(outputs.get("trading_plan_report"), dict) else {}
    if not report:
        return ""
    request = result.get("request") if isinstance(result.get("request"), dict) else {}
    inferred = result.get("inferred_request") if isinstance(result.get("inferred_request"), dict) else {}
    plan_context = request.get("plan_context") if isinstance(request.get("plan_context"), dict) else {}
    if not plan_context:
        plan_context = inferred.get("plan_context") if isinstance(inferred.get("plan_context"), dict) else {}
    target_date = clean_text(plan_context.get("target_trading_date")) or clean_text(report.get("plan_date")) or "下一交易日"
    candidates = [item for item in report.get("candidates") or [] if isinstance(item, dict)]
    candidates.sort(key=lambda item: int(_readable_float(item.get("rank")) or 9999))
    top_execution = _candidate_tier_rows(candidates)[0][1]
    top_names = "、".join(_plan_candidate_display(item) for item in top_execution[:4])
    if not top_names and candidates:
        top_names = "、".join(_plan_candidate_display(item) for item in candidates[:3])
    one_line = (
        f"标准链路把 {top_names} 放在优先观察层；但 `should_apply=false`，"
        "这不是直接买入清单，开盘只能按触发位、成交放大、资金/盘口确认逐级执行。"
        if top_names
        else "标准链路没有给出可直接执行的第一层候选；默认等开盘确认，不提前加仓。"
    )
    workflow_steps = ", ".join(result.get("workflow_steps") or [])
    reason = clean_text(request.get("candidate_universe_reason") or inferred.get("candidate_universe_reason"))
    universe_source = clean_text(plan_context.get("candidate_universe_source"))
    dynamic_sources = plan_context.get("dynamic_candidate_sources")
    source_types = []
    if isinstance(dynamic_sources, list):
        source_types = [clean_text(item.get("source_type")) for item in dynamic_sources if isinstance(item, dict)]
    data_coverage = {}
    intraday_state = outputs.get("intraday_confirmation_state")
    if isinstance(intraday_state, dict) and isinstance(intraday_state.get("data_coverage"), dict):
        data_coverage = intraday_state["data_coverage"]
    preflight = outputs.get("preflight") if isinstance(outputs.get("preflight"), dict) else {}
    lines = [
        f"# {target_date} A 股交易计划",
        "",
        "生成来源：`longbridge-adaptive -> longbridge-screen -> longbridge-trading-plan`。用途：开盘执行清单，不是源数据转储。",
        "",
        "## 数据边界",
        "",
        f"- 标准链路：`{workflow_steps}`",
        f"- 计划日期：`{clean_text(report.get('plan_date'))}`；目标交易日：`{target_date}`",
        f"- 候选池来源：`{universe_source or '见 dynamic_candidate_sources'}`",
        f"- 动态证据：`{', '.join(source_types) if source_types else '未列出'}`",
        f"- 执行边界：`should_apply={str(bool(result.get('should_apply'))).lower()}`，`side_effects={clean_text(result.get('side_effects'))}`",
    ]
    if reason:
        lines.append(f"- 候选池说明：{reason}")
    if data_coverage:
        lines.append(f"- 盘中确认覆盖：`{json.dumps(data_coverage, ensure_ascii=False, sort_keys=True)}`")
    if isinstance(preflight.get("data_coverage"), dict):
        lines.append(f"- 执行预检覆盖：`{json.dumps(preflight.get('data_coverage'), ensure_ascii=False, sort_keys=True)}`")
    lines.extend(["", "## 一句话结论", "", one_line, "", "## 主线排序", "", "| 优先级 | 方向 | 候选 | 操作定义 |", "|---:|---|---|---|"])
    for priority, (direction, items, action) in enumerate(_direction_group_rows(candidates), start=1):
        names = "、".join(_plan_candidate_display(item) for item in items[:6]) if items else "-"
        if len(items) > 6:
            names += f" 等 {len(items)} 只"
        lines.append(f"| {priority} | {direction} | {names} | {action} |")
    lines.extend(
        [
            "",
            "## 个股锚点",
            "",
            "| 标的 | 方向 | 状态 | 收盘/触发/止损/放弃 | 动作 |",
            "|---|---|---|---|---|",
        ]
    )
    for item in candidates:
        levels = item.get("levels") if isinstance(item.get("levels"), dict) else {}
        prices = " / ".join(
            [
                _format_level(levels.get("last_close")),
                _format_level(levels.get("trigger_price")),
                _format_level(levels.get("stop_loss")),
                _format_level(levels.get("abandon_below")),
            ]
        )
        lines.append(
            f"| {_plan_candidate_display(item)} | {_candidate_theme_hint(item)} | {clean_text(item.get('signal'))} / "
            f"{_format_level(_plan_candidate_score(item))} | {prices} | {_candidate_action_label(item)} |"
        )
    top_symbols = [_plan_candidate_display(item) for item in candidates[:3]]
    top_line = "、".join(top_symbols) if top_symbols else "第一层候选"
    lines.extend(
        [
            "",
            "## 盘中验证",
            "",
            f"- 09:15-09:35：不追第一波，先看 {top_line} 是否在触发位上方承接，跌回止损位则降级。",
            "- 09:45-10:30：只有价格、成交放大、资金/盘口确认同时出现，才允许从观察转为试仓。",
            "- 若第一层只剩单票强，不能把单票弹性当作主线；仓位按卫星仓处理。",
            "- 若触发价被冲过但收不住，按观察处理，不把瞬时突破当确认。",
            "",
            "## 仓位框架",
            "",
            "| 场景 | 总仓位 | 处理 |",
            "|---|---:|---|",
            "| 第一层两只以上同时确认 | 20%-40% | 分批，只选 1-2 只，单票 5%-10% 起步 |",
            "| 只有单票确认 | 5%-10% | 卫星仓，不占主线仓位 |",
            "| 第一层跌破止损或板块不跟 | 0%-10% | 降到防守，等待二次确认 |",
            "| 无明确主线 | 0%-10% | 宁可空仓等 10:30 后再评估 |",
            "",
            "## 放弃条件",
            "",
            "- 第一层候选跌破各自止损位，且板块没有同步修复。",
            "- 只有新闻或主题热度，没有价格和成交确认。",
            "- 资金/盘口与价格方向背离，或强票冲高后无法站回触发位。",
            "- 候选池来源显示的动态证据失效时，必须重新跑动态刷新，不沿用本报告。",
            "",
            "## 标准链路与证据",
            "",
            f"- workflow_steps: `{workflow_steps}`",
            f"- schema_version: `{clean_text(report.get('schema_version'))}`",
            f"- should_apply: `{str(bool(result.get('should_apply'))).lower()}`",
            f"- side_effects: `{clean_text(result.get('side_effects'))}`",
        ]
    )
    if universe_source:
        lines.append(f"- candidate_universe_source: `{universe_source}`")
    if isinstance(dynamic_sources, list) and dynamic_sources:
        for source in dynamic_sources:
            if not isinstance(source, dict):
                continue
            path_value = clean_text(source.get("path") or source.get("artifact_path") or source.get("summary"))
            lines.append(f"- {clean_text(source.get('source_type')) or 'dynamic_source'}: `{path_value}`")
    return "\n".join(lines).rstrip() + "\n"


def build_adaptive_markdown(result: dict[str, Any]) -> str:
    readable_plan = build_readable_trading_plan_markdown(result)
    lines = []
    if readable_plan:
        lines.extend([readable_plan.rstrip(), "", "---", ""])
    lines.extend([
        "# Longbridge Adaptive Runner",
        "",
        f"- task_type: `{clean_text(result.get('task_type'))}`",
        f"- workflow_steps: `{', '.join(result.get('workflow_steps') or [])}`",
        f"- should_apply: `{str(bool(result.get('should_apply'))).lower()}`",
        f"- side_effects: `{clean_text(result.get('side_effects'))}`",
        "",
    ])
    request = result.get("request") if isinstance(result.get("request"), dict) else {}
    inferred = result.get("inferred_request") if isinstance(result.get("inferred_request"), dict) else {}
    plan_context = request.get("plan_context") if isinstance(request.get("plan_context"), dict) else {}
    if not plan_context:
        plan_context = inferred.get("plan_context") if isinstance(inferred.get("plan_context"), dict) else {}
    tickers = _listify(request.get("tickers") or inferred.get("tickers") or inferred.get("symbols"))
    if plan_context:
        lines.extend(["## Candidate Universe Provenance", ""])
        if tickers:
            lines.append(f"- tickers: `{', '.join(tickers)}`")
        for key in (
            "source_plan",
            "source_supplement",
            "source_postclose_plan",
            "source_adaptive_result",
            "target_trading_date",
            "candidate_universe_source",
            "side_effect_boundary",
        ):
            value = clean_text(plan_context.get(key))
            if value:
                lines.append(f"- {key}: `{value}`")
        dynamic_sources = plan_context.get("dynamic_candidate_sources")
        if isinstance(dynamic_sources, list) and dynamic_sources:
            lines.append("- dynamic_candidate_sources:")
            for source in dynamic_sources:
                if not isinstance(source, dict):
                    continue
                source_type = clean_text(source.get("source_type")) or "unknown"
                path_value = clean_text(source.get("path") or source.get("artifact_path") or source.get("summary"))
                if path_value:
                    lines.append(f"  - `{source_type}`: `{path_value}`")
                else:
                    lines.append(f"  - `{source_type}`")
        reason = clean_text(request.get("candidate_universe_reason") or inferred.get("candidate_universe_reason"))
        if reason:
            lines.append(f"- candidate_universe_reason: `{reason}`")
        lines.append("")
    outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
    workflow_preflight = outputs.get("workflow_preflight") if isinstance(outputs.get("workflow_preflight"), dict) else {}
    if workflow_preflight:
        lines.extend(
            [
                "## Workflow Preflight",
                "",
                f"- target_trading_date: `{clean_text(workflow_preflight.get('target_trading_date'))}`",
                f"- candidate_universe_source: `{clean_text(workflow_preflight.get('candidate_universe_source'))}`",
                f"- candidate_universe_reason: `{clean_text(workflow_preflight.get('candidate_universe_reason'))}`",
                f"- allow_manual_ticker_universe: `{str(bool(workflow_preflight.get('allow_manual_ticker_universe'))).lower()}`",
                f"- dynamic_source_count: `{int(workflow_preflight.get('dynamic_source_count', 0) or 0)}`",
                f"- social_artifact_count: `{int(workflow_preflight.get('social_artifact_count', 0) or 0)}`",
            ]
        )
        social_artifacts = workflow_preflight.get("social_artifacts")
        if isinstance(social_artifacts, list) and social_artifacts:
            lines.append("- social_artifacts:")
            for artifact in social_artifacts:
                if not isinstance(artifact, dict):
                    continue
                lines.append(
                    f"  - `{clean_text(artifact.get('source_type'))}` "
                    f"kind=`{clean_text(artifact.get('artifact_kind')) or 'unknown'}` "
                    f"exists=`{str(bool(artifact.get('artifact_exists'))).lower()}` "
                    f"path=`{clean_text(artifact.get('artifact_path'))}`"
                )
        lines.append("")
    if isinstance(outputs.get("trading_plan_report"), dict):
        lines.append(build_trading_plan_markdown(outputs["trading_plan_report"]).rstrip())
        lines.append("")
    if isinstance(outputs.get("postclose_review"), dict):
        lines.append(build_postclose_review_markdown(outputs["postclose_review"]).rstrip())
        lines.append("")
    if isinstance(outputs.get("account_snapshot"), dict):
        snapshot = outputs["account_snapshot"]
        lines.extend(
            [
                "## Account Snapshot",
                "",
                f"- data_coverage: `{json.dumps(snapshot.get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- should_apply: `{str(bool(snapshot.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(snapshot.get('side_effects'))}`",
                "",
            ]
        )
    if isinstance(outputs.get("account_review_plus"), dict):
        review_plus = outputs["account_review_plus"]
        lines.extend(
            [
                "## Account Review Plus",
                "",
                f"- symbols: `{json.dumps(review_plus.get('symbols') or [], ensure_ascii=False)}`",
                f"- data_coverage: `{json.dumps(review_plus.get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- should_apply: `{str(bool(review_plus.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(review_plus.get('side_effects'))}`",
                "",
            ]
        )
    if isinstance(outputs.get("subscription_sharelist_state"), dict):
        state = outputs["subscription_sharelist_state"]
        lines.extend(
            [
                "## Subscription And Sharelist State",
                "",
                f"- data_coverage: `{json.dumps(state.get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- should_apply: `{str(bool(state.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(state.get('side_effects'))}`",
                "",
            ]
        )
    if isinstance(outputs.get("intraday_confirmation_state"), dict):
        state = outputs["intraday_confirmation_state"]
        lines.extend(
            [
                "## Intraday Confirmation State",
                "",
                f"- symbols: `{json.dumps(state.get('symbols') or [], ensure_ascii=False)}`",
                f"- data_coverage: `{json.dumps(state.get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- should_apply: `{str(bool(state.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(state.get('side_effects'))}`",
                "",
            ]
        )
    if isinstance(outputs.get("preflight"), dict):
        preflight = outputs["preflight"]
        lines.extend(
            [
                "## Execution Preflight",
                "",
                f"- markets: `{json.dumps(preflight.get('markets') or [], ensure_ascii=False)}`",
                f"- data_coverage: `{json.dumps(preflight.get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- should_apply: `{str(bool(preflight.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(preflight.get('side_effects'))}`",
                "",
            ]
        )
    if isinstance(outputs.get("derivative_event_risk"), dict):
        risk = outputs["derivative_event_risk"]
        lines.extend(
            [
                "## Derivative Event Risk",
                "",
                f"- symbols: `{json.dumps(risk.get('symbols') or [], ensure_ascii=False)}`",
                f"- data_coverage: `{json.dumps(risk.get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- should_apply: `{str(bool(risk.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(risk.get('side_effects'))}`",
                "",
            ]
        )
    if isinstance(outputs.get("hk_microstructure"), dict):
        hk_microstructure = outputs["hk_microstructure"]
        lines.extend(
            [
                "## HK Microstructure",
                "",
                f"- symbols: `{json.dumps(hk_microstructure.get('symbols') or [], ensure_ascii=False)}`",
                f"- data_coverage: `{json.dumps(hk_microstructure.get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- should_apply: `{str(bool(hk_microstructure.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(hk_microstructure.get('side_effects'))}`",
                "",
            ]
        )
    if isinstance(outputs.get("governance_structure"), dict):
        governance = outputs["governance_structure"]
        lines.extend(
            [
                "## Governance Structure",
                "",
                f"- symbols: `{json.dumps(governance.get('symbols') or [], ensure_ascii=False)}`",
                f"- data_coverage: `{json.dumps(governance.get('data_coverage') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- should_apply: `{str(bool(governance.get('should_apply'))).lower()}`",
                f"- side_effects: `{clean_text(governance.get('side_effects'))}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adaptively run read-only Longbridge workflows for analysis, plans, and reviews.")
    parser.add_argument("request_json", help="Path to adaptive request JSON.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--markdown-output", help="Optional markdown output path.")
    args = parser.parse_args(argv)

    from tradingagents_longbridge_market import run_longbridge_cli

    request = load_json(Path(args.request_json))
    result = run_longbridge_adaptive_task(request, runner=run_longbridge_cli, env=dict(os.environ))
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    if args.markdown_output:
        Path(args.markdown_output).write_text(build_adaptive_markdown(result), encoding="utf-8")
    if not args.output and not args.markdown_output:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
