#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCHEMA_VERSION = "institutional_evidence_bundle/v1"
EASTMONEY_NOTICE_API_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
SEC_BRIDGE_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "tradingagents-decision-bridge" / "scripts"
MACRO_HEALTH_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "macro-health-overlay" / "scripts"
MONTH_END_SHORTLIST_SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
REPO_SCRIPTS_DIR = REPO_ROOT / "scripts"
GetFundamentals = Callable[[str, str], str]
MacroHealthBuilder = Callable[[dict[str, Any]], dict[str, Any]]
SectorRankingsFetcher = Callable[[dict[str, Any]], list[dict[str, Any]]]
SectorViewsBuilder = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
NoticeParser = Callable[[Path, dict[str, Any]], list[dict[str, Any]]]
NoticeFetcher = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
AkshareFundamentalFetcher = Callable[[dict[str, Any]], dict[str, Any]]
PackageFinder = Callable[[str], Any]
HealthProbeRunner = Callable[[dict[str, Any]], dict[str, Any]]


REPORT_NOTICE_KEYWORDS = (
    "年度报告",
    "半年度报告",
    "季度报告",
    "第一季度报告",
    "第三季度报告",
    "一季报",
    "三季报",
    "业绩预告",
    "业绩快报",
    "定期报告",
    "财务报表",
)

AKSHARE_FUNDAMENTAL_FIELD_ALIASES = {
    "report_period": ("report_period", "报告期", "报告日期", "截止日期", "日期"),
    "revenue": ("revenue", "营业总收入", "营业收入"),
    "net_profit": ("net_profit", "净利润"),
    "net_profit_parent": ("net_profit_parent", "归母净利润", "归属于母公司股东的净利润"),
    "roe_pct": ("roe_pct", "净资产收益率", "净资产收益率(%)", "ROE"),
    "gross_margin_pct": ("gross_margin_pct", "销售毛利率", "毛利率", "毛利率(%)"),
    "debt_to_asset_pct": ("debt_to_asset_pct", "资产负债率", "资产负债率(%)"),
    "eps": ("eps", "基本每股收益", "每股收益", "EPS"),
}


OPTIONAL_PACKAGE_CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "package.akshare",
        "name": "AKShare",
        "package": "akshare",
        "role": ["china_market_data", "macro_data", "public_web_data_adapter"],
        "install_hint": "pip install akshare",
    },
    {
        "id": "package.openbb",
        "name": "OpenBB",
        "package": "openbb",
        "role": ["cross_market_data_integration", "analyst_workspace"],
        "install_hint": "pip install openbb",
    },
    {
        "id": "package.pandas",
        "name": "pandas",
        "package": "pandas",
        "role": ["dataframe_normalization", "local_research_runtime"],
        "install_hint": "pip install pandas",
    },
    {
        "id": "package.vectorbt",
        "name": "vectorbt",
        "package": "vectorbt",
        "role": ["vectorized_backtest", "signal_validation"],
        "install_hint": "pip install vectorbt",
    },
    {
        "id": "package.quantstats",
        "name": "QuantStats",
        "package": "quantstats",
        "role": ["performance_reporting", "drawdown_risk"],
        "install_hint": "pip install quantstats",
    },
    {
        "id": "package.talib",
        "name": "TA-Lib",
        "package": "talib",
        "role": ["technical_indicators", "candlestick_patterns"],
        "install_hint": "Install TA-Lib binaries, then pip install TA-Lib",
    },
]

REPO_NATIVE_CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "repo.eastmoney_sector_rank",
        "name": "Eastmoney sector rankings",
        "path": MONTH_END_SHORTLIST_SCRIPTS_DIR / "month_end_shortlist_runtime.py",
        "role": ["a_share_sector_leadership", "fresh_discovery_breadth"],
    },
    {
        "id": "repo.eastmoney_notice_cache",
        "name": "Eastmoney notice cache",
        "path": REPO_SCRIPTS_DIR / "stock_watch_workflow.py",
        "role": ["a_share_company_announcements", "official_catalyst_evidence"],
    },
    {
        "id": "repo.sec_companyfacts",
        "name": "SEC companyfacts fundamentals",
        "path": SEC_BRIDGE_SCRIPTS_DIR / "tradingagents_sec_fundamentals.py",
        "role": ["us_filing_fundamentals", "companyfacts"],
    },
    {
        "id": "repo.macro_health_overlay",
        "name": "Macro health overlay",
        "path": MACRO_HEALTH_SCRIPTS_DIR / "macro_health_overlay_runtime.py",
        "role": ["rates_fx_liquidity_regime", "macro_risk_overlay"],
    },
]

LONGBRIDGE_DEFAULT_BINARY_CANDIDATES: tuple[str, ...] = (
    "longbridge",
    str(Path.home() / "AppData" / "Local" / "Programs" / "longbridge" / "longbridge.exe"),
    "/usr/local/bin/longbridge",
    "/opt/homebrew/bin/longbridge",
)

HOST_BINARY_CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "host.longbridge_cli",
        "name": "Longbridge CLI",
        "binary": "longbridge",
        "binary_candidates": LONGBRIDGE_DEFAULT_BINARY_CANDIDATES,
        "role": [
            "live_quote_feed",
            "us_hk_cn_market_status",
            "company_news_headlines",
            "market_temperature",
            "company_filings_and_fundamentals",
            "qualitative_evidence",
        ],
        "install_hint": "Install Longbridge CLI from https://open.longbridgeapp.com/cli, then run `longbridge auth login`.",
    },
]

SOURCE_HEALTH_PROBE_SPECS: list[dict[str, Any]] = [
    {
        "id": "probe.eastmoney_sector_rank",
        "name": "Eastmoney sector rankings live probe",
        "adapter_id": "repo.eastmoney_sector_rank",
        "adapter_kind": "repo_native",
        "primary_market": "CN",
    },
    {
        "id": "probe.eastmoney_notice_cache",
        "name": "Eastmoney notice cache live probe",
        "adapter_id": "repo.eastmoney_notice_cache",
        "adapter_kind": "repo_native",
        "primary_market": "CN",
    },
    {
        "id": "probe.sec_companyfacts",
        "name": "SEC companyfacts live probe",
        "adapter_id": "repo.sec_companyfacts",
        "adapter_kind": "repo_native",
        "primary_market": "US",
    },
    {
        "id": "probe.macro_health_overlay",
        "name": "Macro health overlay live probe",
        "adapter_id": "repo.macro_health_overlay",
        "adapter_kind": "repo_native",
    },
    {
        "id": "probe.akshare",
        "name": "AKShare A-share data live probe",
        "adapter_id": "package.akshare",
        "adapter_kind": "optional_package",
        "primary_market": "CN",
    },
    {
        "id": "probe.longbridge",
        "name": "Longbridge CLI auth + market-status live probe",
        "adapter_id": "host.longbridge_cli",
        "adapter_kind": "host_binary",
    },
]


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")


def package_is_available(package_name: str, package_finder: PackageFinder | None = None) -> bool:
    finder = package_finder or importlib.util.find_spec
    try:
        return finder(package_name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def resolve_host_binary_path(spec: dict[str, Any]) -> str:
    primary = clean_text(spec.get("binary"))
    if primary:
        located = shutil.which(primary)
        if located:
            return located
    for candidate in spec.get("binary_candidates") or ():
        candidate_text = clean_text(candidate)
        if not candidate_text:
            continue
        path = Path(candidate_text)
        if path.is_absolute() and path.exists():
            return str(path)
        located = shutil.which(candidate_text)
        if located:
            return located
    return ""


def build_source_capability_snapshot(
    *,
    package_finder: PackageFinder | None = None,
    repo_native_overrides: dict[str, bool] | None = None,
    host_binary_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for spec in OPTIONAL_PACKAGE_CAPABILITIES:
        available = package_is_available(clean_text(spec.get("package")), package_finder)
        rows.append(
            {
                "id": clean_text(spec.get("id")),
                "name": clean_text(spec.get("name")),
                "adapter_kind": "optional_package",
                "package": clean_text(spec.get("package")),
                "status": "available" if available else "missing",
                "role": safe_list(spec.get("role")),
                "install_hint": clean_text(spec.get("install_hint")),
            }
        )
    overrides = repo_native_overrides or {}
    for spec in REPO_NATIVE_CAPABILITIES:
        capability_id = clean_text(spec.get("id"))
        path = spec.get("path")
        available = bool(overrides[capability_id]) if capability_id in overrides else isinstance(path, Path) and path.exists()
        rows.append(
            {
                "id": capability_id,
                "name": clean_text(spec.get("name")),
                "adapter_kind": "repo_native",
                "status": "available" if available else "missing",
                "role": safe_list(spec.get("role")),
                "path": str(path) if isinstance(path, Path) else clean_text(path),
            }
        )
    host_overrides = host_binary_overrides or {}
    for spec in HOST_BINARY_CAPABILITIES:
        capability_id = clean_text(spec.get("id"))
        if capability_id in host_overrides:
            resolved = clean_text(host_overrides[capability_id])
        else:
            resolved = resolve_host_binary_path(spec)
        rows.append(
            {
                "id": capability_id,
                "name": clean_text(spec.get("name")),
                "adapter_kind": "host_binary",
                "binary": clean_text(spec.get("binary")),
                "binary_path": resolved,
                "status": "available" if resolved else "missing",
                "role": safe_list(spec.get("role")),
                "install_hint": clean_text(spec.get("install_hint")),
            }
        )
    summary = {
        "capability_count": len(rows),
        "available_count": sum(1 for row in rows if row.get("status") == "available"),
        "missing_count": sum(1 for row in rows if row.get("status") == "missing"),
        "optional_package_count": sum(1 for row in rows if row.get("adapter_kind") == "optional_package"),
        "repo_native_count": sum(1 for row in rows if row.get("adapter_kind") == "repo_native"),
        "host_binary_count": sum(1 for row in rows if row.get("adapter_kind") == "host_binary"),
    }
    return {
        "schema_version": "source-capability-snapshot/v1",
        "status": "ok",
        "generated_at": isoformat_z(datetime.now(UTC)),
        "source_capabilities": rows,
        "summary": summary,
    }


def build_source_capability_source_item(
    *,
    host_binary_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    if host_binary_overrides:
        payload = build_source_capability_snapshot(
            host_binary_overrides=host_binary_overrides,
        )
    else:
        payload = build_source_capability_snapshot()
    return {
        "source_path": "local://source-capability-snapshot",
        "source_modified_at": isoformat_z(datetime.now(UTC)),
        "payload": payload,
    }


def a_share_symbol_digits(stock: dict[str, Any]) -> str:
    ticker = clean_text(stock.get("ticker") or stock.get("symbol") or stock.get("code")).upper()
    digits = "".join(ch for ch in ticker if ch.isdigit())
    return digits[:6]


def tabular_to_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        records = value.get("records")
        if isinstance(records, list):
            return [dict(row) for row in records if isinstance(row, dict)]
        data = value.get("data")
        if isinstance(data, list):
            return [dict(row) for row in data if isinstance(row, dict)]
        return [dict(value)] if value else []
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            records = to_dict("records")
        except TypeError:
            records = to_dict()
        if isinstance(records, list):
            return [dict(row) for row in records if isinstance(row, dict)]
        if isinstance(records, dict):
            return [records]
    return []


def first_present_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def normalize_akshare_fundamental_metric(
    row: dict[str, Any],
    stock: dict[str, Any],
    *,
    source_function: str,
) -> dict[str, Any]:
    metric = {
        "ticker": clean_text(stock.get("ticker") or stock.get("symbol") or stock.get("code")).upper(),
        "name": clean_text(stock.get("name") or stock.get("stock_name")),
        "source": "akshare",
        "source_function": source_function,
        "raw_metrics": dict(row),
    }
    for target_key, aliases in AKSHARE_FUNDAMENTAL_FIELD_ALIASES.items():
        value = first_present_value(row, aliases)
        if value not in (None, ""):
            metric[target_key] = value
    return metric


def default_fetch_akshare_fundamental_metrics(stock: dict[str, Any]) -> dict[str, Any]:
    import akshare as ak  # type: ignore[import-not-found]

    symbol = a_share_symbol_digits(stock)
    if not symbol:
        raise ValueError("a_share_symbol_required")
    for function_name in (
        "stock_financial_abstract",
        "stock_financial_analysis_indicator_em",
        "stock_financial_analysis_indicator",
    ):
        function = getattr(ak, function_name, None)
        if not callable(function):
            continue
        try:
            result = function(symbol=symbol)
        except TypeError:
            result = function(symbol)
        records = tabular_to_records(result)
        if records:
            return {"function": function_name, "records": records}
    return {"function": "", "records": []}


def build_akshare_fundamental_source_item(
    stock: dict[str, Any],
    *,
    source_path: str = "",
    fetch_fundamentals: AkshareFundamentalFetcher | None = None,
    metric_limit: int = 8,
) -> dict[str, Any]:
    stock_payload = dict(stock)
    fetcher = fetch_fundamentals or default_fetch_akshare_fundamental_metrics
    source_function = ""
    fetch_status = "not_requested"
    fetch_error = ""
    records: list[dict[str, Any]] = []
    try:
        fetched = fetcher(stock_payload)
    except Exception as exc:
        fetch_status = "error"
        fetch_error = clean_text(exc) or exc.__class__.__name__
    else:
        source_function = clean_text(safe_dict(fetched).get("function"))
        records = tabular_to_records(safe_dict(fetched).get("records") if isinstance(fetched, dict) else fetched)
        fetch_status = "ok" if records else "empty"
    try:
        limit = int(metric_limit)
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 50))
    metrics = [
        normalize_akshare_fundamental_metric(row, stock_payload, source_function=source_function)
        for row in records[:limit]
        if isinstance(row, dict)
    ]
    payload = {
        "schema_version": "akshare-a-share-fundamental-metrics/v1",
        "status": "ok" if metrics else "empty",
        "source_kind": "akshare_a_share_fundamentals",
        "source_mode": "akshare_optional_package",
        "fetch_status": fetch_status,
        "stock": stock_payload,
        "fundamental_metrics": metrics,
    }
    if source_function:
        payload["source_function"] = source_function
    if fetch_error:
        payload["status"] = "error"
        payload["fetch_error"] = fetch_error
    ticker = clean_text(stock_payload.get("ticker")).upper()
    return {
        "source_path": source_path or f"akshare-fundamentals://{ticker or 'unknown'}",
        "source_modified_at": isoformat_z(datetime.now(UTC)),
        "payload": payload,
    }


def source_capability_status_map(snapshot: dict[str, Any]) -> dict[str, str]:
    rows = snapshot.get("source_capabilities")
    return {
        clean_text(row.get("id")): clean_text(row.get("status")) or "unknown"
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and clean_text(row.get("id"))
    }


def source_capability_row_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = snapshot.get("source_capabilities")
    return {
        clean_text(row.get("id")): row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and clean_text(row.get("id"))
    }


CLOSED_SESSION_TOKENS: tuple[str, ...] = (
    "closed",
    "weekend",
    "holiday",
    "halt",
    "suspended",
)


def is_session_closed(session_label: str) -> bool:
    text = clean_text(session_label).lower()
    if not text:
        return False
    return any(token in text for token in CLOSED_SESSION_TOKENS)


def default_longbridge_run_json(
    binary_path: str,
    args: list[str],
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    cmd = [binary_path, *args, "--format", "json"]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:
        return {
            "status": "error",
            "error": clean_text(exc) or exc.__class__.__name__,
            "stdout": "",
            "stderr": "",
        }
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        return {
            "status": "error",
            "error": f"longbridge cli exited with code {completed.returncode}",
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    if not stdout.strip():
        return {"status": "empty", "stdout": stdout, "stderr": stderr}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "error": f"longbridge json decode error: {exc}",
            "stdout": stdout,
            "stderr": stderr,
        }
    return {"status": "ok", "payload": payload, "stdout": stdout, "stderr": stderr}


LONG_BRIDGE_VALID_TOKEN_STATUSES = {"valid", "ok", "authenticated"}


def normalize_longbridge_auth_token_status(payload: Any) -> str:
    data = safe_dict(payload)
    token = safe_dict(data.get("token"))
    token_status = clean_text(token.get("status")).lower()
    if token_status:
        return token_status
    session = safe_dict(data.get("session"))
    session_token = clean_text(session.get("token")).lower()
    if session_token:
        return session_token
    if data.get("authorized") is True:
        return "valid"
    status = clean_text(data.get("status")).lower()
    if status:
        return status
    return ""


def longbridge_auth_token_path(payload: Any) -> str:
    return clean_text(safe_dict(safe_dict(payload).get("token")).get("path"))


def longbridge_token_status_is_valid(status: str) -> bool:
    return clean_text(status).lower() in LONG_BRIDGE_VALID_TOKEN_STATUSES


def normalize_longbridge_market_status_payload(payload: Any) -> dict[str, str]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("data")
            or payload.get("market_status")
            or payload.get("markets")
            or payload.get("rows")
            or []
        )
    else:
        rows = []
    index: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        market = clean_text(
            row.get("market")
            or row.get("region")
            or row.get("market_region")
            or row.get("code")
        ).upper()
        if not market:
            continue
        session = clean_text(
            row.get("session")
            or row.get("market_session")
            or row.get("status")
            or row.get("market_status")
            or row.get("trade_status")
        )
        if session:
            index[market] = session
    return index


def default_longbridge_market_session_index(binary_path: str) -> dict[str, str]:
    if not clean_text(binary_path):
        return {}
    result = default_longbridge_run_json(binary_path, ["market-status"])
    if result.get("status") != "ok":
        return {}
    return normalize_longbridge_market_status_payload(result.get("payload"))


def default_source_health_probe_runner(spec: dict[str, Any]) -> dict[str, Any]:
    adapter_id = clean_text(spec.get("adapter_id"))
    if adapter_id == "repo.eastmoney_sector_rank":
        rows = default_eastmoney_sector_rankings_fetcher({"sector_rank_limit": 1})
        return {
            "probe_status": "healthy" if rows else "degraded",
            "sample_count": len(rows),
            "message": "Eastmoney sector ranking endpoint returned rows." if rows else "Eastmoney sector ranking endpoint returned no rows.",
        }
    if adapter_id == "repo.eastmoney_notice_cache":
        cache_files = list((REPO_ROOT / ".tmp").glob("eastmoney_*_notices.json"))
        return {
            "probe_status": "healthy" if cache_files else "not_run",
            "sample_count": len(cache_files),
            "message": "Eastmoney notice cache files found." if cache_files else "No notice cache file was present for a stock-specific probe.",
        }
    if adapter_id == "repo.sec_companyfacts":
        report = default_sec_get_fundamentals("NVDA", datetime.now(UTC).date().isoformat())
        return {
            "probe_status": "healthy" if clean_text(report) else "degraded",
            "sample_count": 1 if clean_text(report) else 0,
            "message": "SEC companyfacts adapter returned a fundamentals report." if clean_text(report) else "SEC companyfacts adapter returned an empty report.",
        }
    if adapter_id == "repo.macro_health_overlay":
        result = default_build_macro_health_overlay_result(
            {
                "provider": "public_macro_mix",
                "as_of": datetime.now(UTC).date().isoformat(),
                "lookback_trading_days": 20,
            }
        )
        return {
            "probe_status": "healthy" if safe_dict(result.get("macro_health_overlay")) else "degraded",
            "sample_count": 1 if safe_dict(result.get("macro_health_overlay")) else 0,
            "message": "Macro-health overlay adapter returned an overlay." if safe_dict(result.get("macro_health_overlay")) else "Macro-health overlay adapter returned no overlay.",
        }
    if adapter_id == "package.akshare":
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            row_count = len(df) if df is not None else 0
            return {
                "probe_status": "healthy" if row_count > 0 else "degraded",
                "sample_count": row_count,
                "message": f"AKShare A-share spot endpoint returned {row_count} rows." if row_count else "AKShare A-share spot endpoint returned no rows.",
            }
        except Exception as exc:
            return {
                "probe_status": "error",
                "sample_count": 0,
                "message": clean_text(exc) or "AKShare probe failed.",
            }
    if adapter_id == "host.longbridge_cli":
        binary_path = clean_text(spec.get("binary_path"))
        if not binary_path:
            return {
                "probe_status": "blocked",
                "sample_count": 0,
                "message": "Longbridge CLI binary path was not resolved.",
            }
        auth_result = default_longbridge_run_json(binary_path, ["auth", "status"])
        auth_status = auth_result.get("status")
        if auth_status != "ok":
            return {
                "probe_status": "error",
                "sample_count": 0,
                "message": clean_text(auth_result.get("error")) or "Longbridge auth status check failed.",
                "longbridge_auth_status": auth_status,
            }
        auth_payload = safe_dict(auth_result.get("payload"))
        auth_token_status = normalize_longbridge_auth_token_status(auth_payload)
        auth_token_path = longbridge_auth_token_path(auth_payload)
        check_result = default_longbridge_run_json(binary_path, ["check"])
        check_status = check_result.get("status")
        check_token_status = (
            normalize_longbridge_auth_token_status(check_result.get("payload"))
            if check_status == "ok"
            else ""
        )
        if not longbridge_token_status_is_valid(auth_token_status) or (
            check_token_status and not longbridge_token_status_is_valid(check_token_status)
        ):
            return {
                "probe_status": "blocked",
                "sample_count": 0,
                "message": (
                    "Longbridge auth token is not valid in this execution context "
                    f"(auth_status={auth_token_status or 'unknown'}; "
                    f"check_token={check_token_status or check_status or 'unknown'})."
                ),
                "longbridge_auth_status": auth_token_status or auth_status,
                "longbridge_auth_token_path": auth_token_path,
                "longbridge_check_status": check_status,
                "longbridge_check_token_status": check_token_status,
            }
        if check_status != "ok":
            return {
                "probe_status": "error",
                "sample_count": 0,
                "message": clean_text(check_result.get("error")) or "Longbridge connectivity check failed.",
                "longbridge_auth_status": auth_token_status or auth_status,
                "longbridge_auth_token_path": auth_token_path,
                "longbridge_check_status": check_status,
            }
        market_result = default_longbridge_run_json(binary_path, ["market-status"])
        market_status = market_result.get("status")
        market_index = (
            normalize_longbridge_market_status_payload(market_result.get("payload"))
            if market_status == "ok"
            else {}
        )
        return {
            "probe_status": "healthy" if market_status == "ok" else "degraded",
            "sample_count": len(market_index),
            "message": (
                f"Longbridge CLI auth ok; market-status returned {len(market_index)} markets."
                if market_status == "ok"
                else clean_text(market_result.get("error")) or "Longbridge market-status check did not return data."
            ),
            "longbridge_auth_status": auth_token_status or auth_status,
            "longbridge_auth_token_path": auth_token_path,
            "longbridge_check_status": check_status,
            "longbridge_check_token_status": check_token_status,
            "longbridge_market_status_status": market_status,
            "longbridge_market_session_index": market_index,
        }
    return {"probe_status": "not_run", "message": "No default live probe is registered for this adapter."}


WEEKDAY_FALLBACK_CLOSED_MARKETS: tuple[str, ...] = ("CN", "HK", "US", "SG")


def weekday_market_session_index(now: datetime | None = None) -> dict[str, str]:
    moment = now or datetime.now(UTC)
    if moment.weekday() < 5:
        return {}
    label = "weekend"
    return {market: label for market in WEEKDAY_FALLBACK_CLOSED_MARKETS}


def build_source_health_probe_snapshot(
    *,
    capability_snapshot: dict[str, Any] | None = None,
    run_live_probes: bool = False,
    probe_runner: HealthProbeRunner | None = None,
    market_session_index: dict[str, str] | None = None,
    weekday_fallback: bool = True,
) -> dict[str, Any]:
    capabilities = capability_snapshot if isinstance(capability_snapshot, dict) else build_source_capability_snapshot()
    capability_rows = source_capability_row_map(capabilities)
    capability_status = source_capability_status_map(capabilities)
    rows: list[dict[str, Any]] = []
    runner = probe_runner or default_source_health_probe_runner
    longbridge_session_index: dict[str, str] = {}
    for spec in SOURCE_HEALTH_PROBE_SPECS:
        adapter_id = clean_text(spec.get("adapter_id"))
        adapter_status = capability_status.get(adapter_id, "unknown")
        primary_market = clean_text(spec.get("primary_market")).upper()
        row = {
            "id": clean_text(spec.get("id")),
            "name": clean_text(spec.get("name")),
            "adapter_id": adapter_id,
            "adapter_kind": clean_text(spec.get("adapter_kind")),
            "adapter_status": adapter_status,
        }
        if primary_market:
            row["primary_market"] = primary_market
        if adapter_status != "available":
            row.update(
                {
                    "probe_status": "blocked",
                    "message": f"Adapter status is `{adapter_status}`; live probe was not attempted.",
                }
            )
        elif not run_live_probes:
            row.update(
                {
                    "probe_status": "not_run",
                    "message": "Live source probe was not requested.",
                }
            )
        else:
            try:
                probe_spec = dict(spec)
                capability_row = capability_rows.get(adapter_id)
                if isinstance(capability_row, dict):
                    for key in ("binary", "binary_path", "package", "path", "role", "install_hint"):
                        if key in capability_row and key not in probe_spec:
                            probe_spec[key] = capability_row[key]
                    probe_spec["adapter_status"] = adapter_status
                probe_result = runner(probe_spec)
            except Exception as exc:
                row.update(
                    {
                        "probe_status": "error",
                        "message": clean_text(exc) or exc.__class__.__name__,
                    }
                )
            else:
                if isinstance(probe_result, dict):
                    fresh_session_index = probe_result.pop("longbridge_market_session_index", None)
                    if isinstance(fresh_session_index, dict) and fresh_session_index:
                        longbridge_session_index.update(
                            {
                                clean_text(market).upper(): clean_text(session)
                                for market, session in fresh_session_index.items()
                                if clean_text(market) and clean_text(session)
                            }
                        )
                    row.update(probe_result)
                row["probe_status"] = clean_text(row.get("probe_status")) or "unknown"
        rows.append(row)
    effective_index: dict[str, str] = {}
    if isinstance(market_session_index, dict):
        for market, session in market_session_index.items():
            market_text = clean_text(market).upper()
            session_text = clean_text(session)
            if market_text and session_text:
                effective_index[market_text] = session_text
    for market, session in longbridge_session_index.items():
        if market and session:
            effective_index.setdefault(market, session)
    if weekday_fallback:
        for market, session in weekday_market_session_index().items():
            effective_index.setdefault(market, session)
    quiet_count = 0
    for row in rows:
        market = clean_text(row.get("primary_market")).upper()
        if not market:
            continue
        session_label = effective_index.get(market)
        if not session_label:
            continue
        row["market_session"] = session_label
        if not is_session_closed(session_label):
            continue
        previous_status = row.get("probe_status")
        if previous_status in {"error", "degraded", "not_run"}:
            row["probe_status"] = "quiet"
            row["pre_quiet_status"] = previous_status
            existing_message = clean_text(row.get("message"))
            row["message"] = (
                f"{market} market is `{session_label}`; downgraded `{previous_status}` to `quiet`."
                + (f" Original: {existing_message}" if existing_message else "")
            )
            quiet_count += 1
    summary = {
        "probe_count": len(rows),
        "healthy_count": sum(1 for row in rows if row.get("probe_status") == "healthy"),
        "degraded_count": sum(1 for row in rows if row.get("probe_status") == "degraded"),
        "blocked_count": sum(1 for row in rows if row.get("probe_status") == "blocked"),
        "not_run_count": sum(1 for row in rows if row.get("probe_status") == "not_run"),
        "error_count": sum(1 for row in rows if row.get("probe_status") == "error"),
        "quiet_count": quiet_count,
    }
    return {
        "schema_version": "source-health-probe-snapshot/v1",
        "status": "ok",
        "generated_at": isoformat_z(datetime.now(UTC)),
        "live_probes_requested": bool(run_live_probes),
        "source_health_probes": rows,
        "market_session_index": effective_index,
        "summary": summary,
    }


def build_source_health_probe_source_item(
    *,
    run_live_probes: bool = False,
    market_session_index: dict[str, str] | None = None,
    weekday_fallback: bool = True,
) -> dict[str, Any]:
    return {
        "source_path": "local://source-health-probe-snapshot",
        "source_modified_at": isoformat_z(datetime.now(UTC)),
        "payload": build_source_health_probe_snapshot(
            run_live_probes=run_live_probes,
            market_session_index=market_session_index,
            weekday_fallback=weekday_fallback,
        ),
    }


def default_sec_get_fundamentals(ticker: str, curr_date: str) -> str:
    if SEC_BRIDGE_SCRIPTS_DIR.exists() and str(SEC_BRIDGE_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SEC_BRIDGE_SCRIPTS_DIR))
    from tradingagents_sec_fundamentals import get_fundamentals

    return str(get_fundamentals(ticker, curr_date=curr_date))


def default_build_macro_health_overlay_result(request: dict[str, Any]) -> dict[str, Any]:
    if MACRO_HEALTH_SCRIPTS_DIR.exists() and str(MACRO_HEALTH_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(MACRO_HEALTH_SCRIPTS_DIR))
    from macro_health_overlay_runtime import build_macro_health_overlay_result

    return build_macro_health_overlay_result(request)


def default_eastmoney_sector_rankings_fetcher(request: dict[str, Any]) -> list[dict[str, Any]]:
    if MONTH_END_SHORTLIST_SCRIPTS_DIR.exists() and str(MONTH_END_SHORTLIST_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(MONTH_END_SHORTLIST_SCRIPTS_DIR))
    from month_end_shortlist_runtime import default_sector_rankings_fetcher

    return [dict(row) for row in default_sector_rankings_fetcher(request) if isinstance(row, dict)]


def default_build_sector_views_from_rankings(rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if MONTH_END_SHORTLIST_SCRIPTS_DIR.exists() and str(MONTH_END_SHORTLIST_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(MONTH_END_SHORTLIST_SCRIPTS_DIR))
    from month_end_shortlist_runtime import build_sector_views_from_rankings

    return [dict(row) for row in build_sector_views_from_rankings(rankings) if isinstance(row, dict)]


def default_parse_eastmoney_notices(repo_root: Path, stock: dict[str, Any]) -> list[dict[str, Any]]:
    if REPO_SCRIPTS_DIR.exists() and str(REPO_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(REPO_SCRIPTS_DIR))
    from stock_watch_workflow import parse_notice_cache

    return [dict(row) for row in parse_notice_cache(repo_root, stock) if isinstance(row, dict)]


def eastmoney_notice_stock_list_value(stock: dict[str, Any]) -> str:
    ticker = clean_text(stock.get("ticker") or stock.get("code") or stock.get("symbol")).upper()
    digits = "".join(ch for ch in ticker if ch.isdigit())
    if not digits:
        return ""
    market_id = "1" if ticker.endswith((".SH", ".SS", ".XSHG")) or digits.startswith(("6", "9")) else "0"
    return f"{digits},{market_id}"


def build_eastmoney_notice_request(stock: dict[str, Any], *, page_size: int = 50) -> dict[str, Any]:
    stock_list = eastmoney_notice_stock_list_value(stock)
    return {
        "sr": "-1",
        "page_size": str(max(1, min(int(page_size or 50), 100))),
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "stock_list": stock_list,
    }


def eastmoney_notice_payload_to_notices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = safe_dict(payload.get("data")).get("list")
    notices: list[dict[str, Any]] = []
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title") or item.get("title_ch"))
        if not title:
            continue
        display_time = clean_text(item.get("display_time") or item.get("eiTime"))
        notices.append(
            {
                "art_code": clean_text(item.get("art_code") or item.get("artCode")),
                "title": title,
                "notice_date": clean_text(item.get("notice_date") or item.get("noticeDate"))[:10],
                "published_at": clean_text(item.get("published_at") or item.get("publishedAt")),
                "display_time": display_time,
                "columns": [
                    clean_text(col.get("column_name") or col.get("columnName") or col.get("name"))
                    for col in safe_list(item.get("columns"))
                    if isinstance(col, dict) and clean_text(col.get("column_name") or col.get("columnName") or col.get("name"))
                ],
            }
        )
    return notices


def default_fetch_eastmoney_notice_payload(stock: dict[str, Any], request_payload: dict[str, Any]) -> dict[str, Any]:
    query = urlencode({key: value for key, value in request_payload.items() if clean_text(value)})
    request = Request(
        f"{EASTMONEY_NOTICE_API_URL}?{query}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/notices/",
        },
    )
    with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed Eastmoney public endpoint
        return json.loads(response.read().decode("utf-8", errors="replace"))


def build_macro_health_source_item(
    request: dict[str, Any],
    *,
    source_path: str = "macro-health-overlay-request.json",
    build_macro_health_overlay_result: MacroHealthBuilder | None = None,
) -> dict[str, Any]:
    builder = build_macro_health_overlay_result or default_build_macro_health_overlay_result
    payload = dict(builder(request))
    payload.setdefault("schema_version", "macro_health_overlay_result/v1")
    return {
        "source_path": source_path,
        "source_modified_at": isoformat_z(datetime.now(UTC)),
        "payload": payload,
    }


def build_sec_fundamentals_source_item(
    ticker: str,
    analysis_date: str,
    *,
    get_fundamentals: GetFundamentals | None = None,
) -> dict[str, Any]:
    normalized_ticker = clean_text(ticker).upper()
    date_text = clean_text(analysis_date)
    fetcher = get_fundamentals or default_sec_get_fundamentals
    report = clean_text(fetcher(normalized_ticker, date_text))
    filings = []
    if report and ("filing" in report.lower() or "10-q" in report.lower() or "10-k" in report.lower()):
        filings.append(
            {
                "ticker": normalized_ticker,
                "source": "sec_companyfacts",
                "analysis_date": date_text,
                "summary": "SEC filing evidence found in fundamentals report.",
            }
        )
    return {
        "source_path": f"sec://companyfacts/{normalized_ticker}/{date_text}",
        "source_modified_at": isoformat_z(datetime.now(UTC)),
        "payload": {
            "schema_version": "sec-fundamentals-evidence/v1",
            "status": "ok" if report else "empty",
            "fundamentals": {
                "ticker": normalized_ticker,
                "source": "sec_companyfacts",
                "analysis_date": date_text,
                "text": report,
            },
            "filings": filings,
        },
    }


def build_eastmoney_sector_source_item(
    request: dict[str, Any],
    *,
    source_path: str = "eastmoney-sector-rankings-request.json",
    fetch_sector_rankings: SectorRankingsFetcher | None = None,
    build_sector_views: SectorViewsBuilder | None = None,
) -> dict[str, Any]:
    request_payload = dict(request)
    fetcher = fetch_sector_rankings or default_eastmoney_sector_rankings_fetcher
    rankings = [dict(row) for row in fetcher(request_payload) if isinstance(row, dict)]
    view_builder = build_sector_views or default_build_sector_views_from_rankings
    sector_views = [dict(row) for row in view_builder(rankings) if isinstance(row, dict)]
    return {
        "source_path": source_path,
        "source_modified_at": isoformat_z(datetime.now(UTC)),
        "payload": {
            "schema_version": "eastmoney-sector-rankings/v1",
            "status": "ok" if rankings else "empty",
            "source_kind": "eastmoney_sector_rankings",
            "request": request_payload,
            "sector_rankings": rankings,
            "sector_views": sector_views,
        },
    }


def eastmoney_notice_to_announcement(notice: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    title = clean_text(notice.get("title") or notice.get("title_ch"))
    if not title:
        return {}
    columns = [clean_text(item) for item in safe_list(notice.get("columns")) if clean_text(item)]
    notice_date = clean_text(notice.get("notice_date"))[:10]
    summary = clean_text(notice.get("summary"))
    if not summary:
        summary = clean_text(f"{notice_date}: {title}" if notice_date else title)
    return {
        "ticker": clean_text(stock.get("ticker")),
        "name": clean_text(stock.get("name") or stock.get("stock_name")),
        "art_code": clean_text(notice.get("art_code")),
        "title": title,
        "summary": summary,
        "notice_date": notice_date,
        "published_at": clean_text(notice.get("published_at")),
        "display_time": clean_text(notice.get("display_time")),
        "columns": columns,
        "source": "eastmoney_notice_cache",
        "source_type": "company_filing",
    }


def build_eastmoney_notice_source_item(
    stock: dict[str, Any],
    *,
    repo_root: Path | str | None = None,
    source_path: str = "",
    parse_notices: NoticeParser | None = None,
    refresh_notices: bool = False,
    fetch_notices: NoticeFetcher | None = None,
    notice_limit: int = 20,
) -> dict[str, Any]:
    stock_payload = dict(stock)
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    parser = parse_notices or default_parse_eastmoney_notices
    notices = [dict(row) for row in parser(root, stock_payload) if isinstance(row, dict)]
    source_mode = "cache"
    fetch_status = "not_requested"
    notice_request = build_eastmoney_notice_request(stock_payload)
    if refresh_notices and not notices and clean_text(notice_request.get("stock_list")):
        fetcher = fetch_notices or default_fetch_eastmoney_notice_payload
        try:
            fetched_payload = fetcher(stock_payload, notice_request)
        except Exception as exc:
            source_mode = "live_fetch"
            fetch_status = "error"
            stock_payload["notice_fetch_error"] = clean_text(exc) or exc.__class__.__name__
        else:
            fetched_notices = eastmoney_notice_payload_to_notices(fetched_payload if isinstance(fetched_payload, dict) else {})
            if fetched_notices:
                notices = fetched_notices
                source_mode = "live_fetch"
                fetch_status = "ok"
            else:
                source_mode = "live_fetch"
                fetch_status = "empty"
    try:
        limit = int(notice_limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))
    announcements = unique_dicts(
        [
            row
            for row in (eastmoney_notice_to_announcement(notice, stock_payload) for notice in notices[:limit])
            if row
        ]
    )
    ticker = clean_text(stock_payload.get("ticker")).upper()
    payload = {
        "schema_version": "eastmoney-notice-cache-evidence/v1",
        "status": "ok" if announcements else "empty",
        "source_kind": "eastmoney_notice_cache",
        "source_mode": source_mode,
        "fetch_status": fetch_status,
        "notice_request": notice_request,
        "stock": stock_payload,
        "announcements": announcements,
    }
    notice_fetch_error = clean_text(stock_payload.get("notice_fetch_error"))
    if notice_fetch_error:
        payload["notice_fetch_error"] = notice_fetch_error
    return {
        "source_path": source_path or f"eastmoney-notices-cache://{ticker or 'unknown'}",
        "source_modified_at": isoformat_z(datetime.now(UTC)),
        "payload": payload,
    }


def isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_datetime(value: Any) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def source_freshness(
    *,
    source_modified_at: str,
    as_of: datetime,
    freshness_threshold_hours: float,
) -> dict[str, Any]:
    modified_at = parse_datetime(source_modified_at)
    if modified_at is None:
        return {"freshness_status": "unknown", "source_age_hours": None}
    source_age_hours = max(0.0, (as_of - modified_at).total_seconds() / 3600)
    return {
        "freshness_status": "fresh" if source_age_hours <= freshness_threshold_hours else "stale",
        "source_age_hours": round(source_age_hours, 2),
    }


def detect_source_kind(payload: dict[str, Any]) -> str:
    schema_text = " ".join(
        clean_text(payload.get(key)).lower()
        for key in ("schema_version", "workflow_kind", "source_kind")
    )
    if "x-index" in schema_text or "x_index" in schema_text:
        return "x_index"
    if safe_list(payload.get("x_posts")) or safe_dict(payload.get("evidence_pack")):
        return "x_index"
    if "source-capability" in schema_text or safe_list(payload.get("source_capabilities")):
        return "source_capability_snapshot"
    if "source-health-probe" in schema_text or safe_list(payload.get("source_health_probes")):
        return "source_health_probe_snapshot"
    if (
        "flow-positioning" in schema_text
        or "flow_positioning" in schema_text
        or any(
            payload.get(key)
            for key in (
                "positioning_flows",
                "flow_positioning",
                "northbound_flows",
                "southbound_flows",
                "stock_connect_flows",
                "etf_flows",
                "short_sale_volume",
                "short_interest",
                "margin_financing",
                "securities_lending",
                "dragon_tiger",
                "options_flows",
                "put_call",
                "options_skew",
                "cftc_cot",
                "cot_positioning",
            )
        )
    ):
        return "flow_positioning"
    if isinstance(payload.get("macro_health_overlay"), dict):
        return "macro_health_overlay"
    if isinstance(payload.get("decision_memo"), dict):
        return "tradingagents_decision_bridge"
    if (
        "akshare" in schema_text
        or "a-share" in schema_text
        or "a_share" in schema_text
        or "eastmoney_notice_cache" in schema_text
        or "eastmoney-notice-cache" in schema_text
        or any(
            payload.get(key)
            for key in (
                "sector_rankings",
                "sector_views",
                "capital_flows",
                "fund_flows",
                "announcements",
            )
        )
    ):
        return "a_share_public"
    if (
        "vectorbt" in schema_text
        or "quantstats" in schema_text
        or "backtest" in schema_text
        or any(
            payload.get(key)
            for key in (
                "recent_validation",
                "validation",
                "validations",
                "backtest",
                "backtests",
                "actuals",
                "quant_analysis",
                "performance_metrics",
            )
        )
    ):
        return "validation_backtest"
    if any(payload.get(key) for key in ("news", "articles", "event_cards", "events")):
        return "news_event"
    if any(payload.get(key) for key in ("filings", "fundamentals", "ownership")):
        return "generic_institutional_evidence"
    return "unknown"


def unique_dicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        marker = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(row)
    return unique


def normalize_x_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in [*safe_list(payload.get("x_posts")), *safe_list(payload.get("posts"))]:
        if isinstance(value, dict):
            rows.append(dict(value))
    evidence_pack = safe_dict(payload.get("evidence_pack"))
    for value in safe_list(evidence_pack.get("x_posts")):
        if isinstance(value, dict):
            rows.append(dict(value))
    return unique_dicts(rows)


def normalize_claim_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    evidence_pack = safe_dict(payload.get("evidence_pack"))
    for value in [*safe_list(payload.get("claim_candidates")), *safe_list(evidence_pack.get("claim_candidates"))]:
        if isinstance(value, dict):
            rows.append(dict(value))
    return unique_dicts(rows)


def normalize_generic_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if isinstance(value, dict):
        return [dict(value)]
    return [dict(row) for row in safe_list(value) if isinstance(row, dict)]


def normalize_news_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("news", "articles", "source_items"):
        for row in safe_list(payload.get(key)):
            if isinstance(row, dict):
                rows.append(dict(row))
    retrieval_result = safe_dict(payload.get("retrieval_result"))
    for row in safe_list(retrieval_result.get("news")):
        if isinstance(row, dict):
            rows.append(dict(row))
    return unique_dicts(rows)


def normalize_rows_from_keys(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            rows.append(dict(value))
            continue
        for row in safe_list(value):
            if isinstance(row, dict):
                rows.append(dict(row))
    return unique_dicts(rows)


def normalize_sector_rankings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(
        payload,
        ("sector_rankings", "board_rankings", "industry_rankings"),
    )


def normalize_sector_views(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(payload, ("sector_views", "industry_views"))


def normalize_capital_flows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(payload, ("capital_flows", "fund_flows", "money_flows"))


POSITIONING_FLOW_KEYS: tuple[str, ...] = (
    "positioning_flows",
    "flow_positioning",
    "capital_flows",
    "fund_flows",
    "money_flows",
    "northbound_flows",
    "southbound_flows",
    "stock_connect_flows",
    "etf_flows",
    "short_sale_volume",
    "short_interest",
    "margin_financing",
    "securities_lending",
    "dragon_tiger",
    "options_flows",
    "put_call",
    "options_skew",
    "cftc_cot",
    "cot_positioning",
    "volume_anomaly",
)


def normalize_positioning_flows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in POSITIONING_FLOW_KEYS:
        value = payload.get(key)
        if isinstance(value, dict):
            row = dict(value)
            row.setdefault("flow_type", key)
            rows.append(row)
            continue
        for item in safe_list(value):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("flow_type", key)
            rows.append(row)
    return unique_dicts(rows)


def normalize_announcements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(payload, ("announcements", "company_announcements"))


def normalize_fundamental_reports(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fundamentals = payload.get("fundamentals")
    if isinstance(fundamentals, dict):
        reports = fundamentals.get("reports")
        if isinstance(reports, dict):
            rows.append(dict(reports))
        else:
            rows.extend(dict(row) for row in safe_list(reports) if isinstance(row, dict))
        remaining = {
            key: value
            for key, value in fundamentals.items()
            if key != "reports" and value not in (None, "", [], {})
        }
        if remaining:
            rows.append(remaining)
    else:
        rows.extend(dict(row) for row in safe_list(fundamentals) if isinstance(row, dict))
    rows.extend(
        normalize_rows_from_keys(
            payload,
            (
                "fundamental_reports",
                "fundamental_metrics",
                "financial_metrics",
                "a_share_fundamental_metrics",
            ),
        )
    )
    return unique_dicts(rows)


def normalize_validations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(payload, ("recent_validation", "validation", "validations"))


def normalize_backtests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(payload, ("backtest", "backtests"))


def normalize_actuals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(payload, ("actual", "actuals", "trigger_outcomes"))


def normalize_quant_analysis(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(
        payload,
        ("quant_analysis", "performance_metrics", "quantstats_report"),
    )


def normalize_source_capabilities(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(payload, ("source_capabilities", "capabilities"))


def normalize_source_health_probes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_rows_from_keys(payload, ("source_health_probes", "health_probes"))


def news_items_to_event_cards(news_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in news_items:
        title = clean_text(item.get("title") or item.get("headline") or item.get("summary"))
        summary = clean_text(item.get("summary") or item.get("description") or item.get("snippet"))
        if not title and not summary:
            continue
        cards.append(
            {
                "event_type": clean_text(item.get("event_type") or item.get("catalyst_type") or "news_event"),
                "source_type": clean_text(item.get("source_type") or item.get("type") or "news"),
                "title": title,
                "summary": summary,
                "url": clean_text(item.get("url") or item.get("source_url")),
                "source": clean_text(item.get("source") or item.get("publisher")),
            }
        )
    return unique_dicts(cards)


def announcements_to_event_cards(announcements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in announcements:
        title = clean_text(item.get("title") or item.get("headline") or item.get("summary"))
        summary = clean_text(item.get("summary") or item.get("description") or item.get("snippet"))
        if not title and not summary:
            continue
        cards.append(
            {
                "event_type": clean_text(item.get("event_type") or "announcement"),
                "source_type": clean_text(item.get("source_type") or "official_announcement"),
                "ticker": clean_text(item.get("ticker") or item.get("symbol") or item.get("code")),
                "title": title,
                "summary": summary,
                "url": clean_text(item.get("url") or item.get("source_url")),
                "source": clean_text(item.get("source") or item.get("publisher") or "announcement"),
            }
        )
    return unique_dicts(cards)


def is_report_or_fundamental_announcement(item: dict[str, Any]) -> bool:
    title = clean_text(item.get("title") or item.get("headline") or item.get("summary"))
    columns = " ".join(clean_text(value) for value in safe_list(item.get("columns")) if clean_text(value))
    haystack = f"{title} {columns}"
    return any(keyword in haystack for keyword in REPORT_NOTICE_KEYWORDS)


def announcements_to_filings(announcements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filings: list[dict[str, Any]] = []
    for item in announcements:
        if not is_report_or_fundamental_announcement(item):
            continue
        title = clean_text(item.get("title") or item.get("summary"))
        ticker = clean_text(item.get("ticker") or item.get("symbol") or item.get("code"))
        filings.append(
            {
                "ticker": ticker,
                "name": clean_text(item.get("name") or item.get("stock_name")),
                "source": clean_text(item.get("source")) or "eastmoney_notice_cache",
                "source_type": clean_text(item.get("source_type")) or "company_filing",
                "art_code": clean_text(item.get("art_code")),
                "filing_type": "a_share_periodic_or_earnings_notice",
                "title": title,
                "notice_date": clean_text(item.get("notice_date")),
                "published_at": clean_text(item.get("published_at")),
                "summary": clean_text(item.get("summary")) or title,
            }
        )
    return unique_dicts(filings)


def announcements_to_fundamental_reports(announcements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for item in announcements:
        if not is_report_or_fundamental_announcement(item):
            continue
        title = clean_text(item.get("title") or item.get("summary"))
        ticker = clean_text(item.get("ticker") or item.get("symbol") or item.get("code"))
        notice_date = clean_text(item.get("notice_date"))
        text = clean_text(item.get("summary")) or clean_text(f"{notice_date}: {title}" if notice_date else title)
        reports.append(
            {
                "ticker": ticker,
                "name": clean_text(item.get("name") or item.get("stock_name")),
                "source": clean_text(item.get("source")) or "eastmoney_notice_cache",
                "source_type": clean_text(item.get("source_type")) or "company_filing",
                "status": "bounded_notice_evidence",
                "title": title,
                "notice_date": notice_date,
                "published_at": clean_text(item.get("published_at")),
                "text": text,
                "usage_boundary": "A-share official notice evidence; parse full report metrics before treating this as a complete fundamental model.",
            }
        )
    return unique_dicts(reports)


def extract_tradingagents_fundamental_report(
    payload: dict[str, Any],
    *,
    source_path: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    memo = safe_dict(payload.get("decision_memo"))
    state = safe_dict(memo.get("state"))
    report = clean_text(state.get("fundamentals_report"))
    if not report:
        return [], [], []
    ticker = clean_text(memo.get("normalized_ticker") or memo.get("requested_ticker"))
    report_row = {
        "ticker": ticker,
        "source": "tradingagents_decision_bridge",
        "source_path": source_path,
        "status": clean_text(payload.get("status")),
        "memo_status": clean_text(memo.get("status")),
        "text": report,
    }
    filings = []
    if "filing" in report.lower() or "10-q" in report.lower() or "10-k" in report.lower():
        filings.append(
            {
                "ticker": ticker,
                "source": "tradingagents_sec_fundamentals",
                "source_path": source_path,
                "summary": "SEC filing evidence found in fundamentals report.",
            }
        )
    return [report_row], filings, [clean_text(item) for item in safe_list(memo.get("warnings")) if clean_text(item)]


def normalize_source_item(
    item: dict[str, Any],
    *,
    as_of: datetime,
    freshness_threshold_hours: float,
) -> dict[str, Any]:
    payload = safe_dict(item.get("payload"))
    source_path = clean_text(item.get("source_path"))
    source_kind = detect_source_kind(payload)
    source_modified_at = clean_text(item.get("source_modified_at"))
    source_mode = clean_text(payload.get("source_mode"))
    fetch_status = clean_text(payload.get("fetch_status"))
    notice_fetch_error = clean_text(payload.get("notice_fetch_error") or safe_dict(payload.get("stock")).get("notice_fetch_error"))
    fetch_error = clean_text(payload.get("fetch_error") or notice_fetch_error)
    fundamental_reports, sec_filings, warnings = extract_tradingagents_fundamental_report(
        payload,
        source_path=source_path,
    )
    payload_warnings = [clean_text(item) for item in safe_list(payload.get("warnings")) if clean_text(item)]
    if fetch_error:
        payload_warnings.append(f"{source_kind} fetch error: {fetch_error}")
    news_items = normalize_news_items(payload)
    announcements = normalize_announcements(payload)
    a_share_filings = announcements_to_filings(announcements)
    a_share_fundamental_reports = announcements_to_fundamental_reports(announcements)
    source_row = {
        "path": source_path,
        "kind": source_kind,
        "status": clean_text(payload.get("status")),
        "source_modified_at": source_modified_at,
        **source_freshness(
            source_modified_at=source_modified_at,
            as_of=as_of,
            freshness_threshold_hours=freshness_threshold_hours,
        ),
    }
    if source_mode:
        source_row["source_mode"] = source_mode
    if fetch_status:
        source_row["fetch_status"] = fetch_status
    if fetch_error:
        source_row["fetch_error"] = fetch_error
    if notice_fetch_error:
        source_row["notice_fetch_error"] = notice_fetch_error
    return {
        "source": source_row,
        "x_posts": normalize_x_posts(payload),
        "claim_candidates": normalize_claim_candidates(payload),
        "filings": unique_dicts([*normalize_generic_rows(payload, "filings"), *sec_filings, *a_share_filings]),
        "fundamental_reports": [
            *normalize_fundamental_reports(payload),
            *fundamental_reports,
            *a_share_fundamental_reports,
        ],
        "ownership_rows": normalize_generic_rows(payload, "ownership"),
        "macro_health_overlay": safe_dict(payload.get("macro_health_overlay")),
        "sector_rankings": normalize_sector_rankings(payload),
        "sector_views": normalize_sector_views(payload),
        "capital_flows": normalize_capital_flows(payload),
        "positioning_flows": normalize_positioning_flows(payload),
        "announcements": announcements,
        "validations": normalize_validations(payload),
        "backtests": normalize_backtests(payload),
        "actuals": normalize_actuals(payload),
        "quant_analysis": normalize_quant_analysis(payload),
        "source_capabilities": normalize_source_capabilities(payload),
        "source_health_probes": normalize_source_health_probes(payload),
        "news_items": news_items,
        "event_cards": [
            *normalize_generic_rows(payload, "event_cards"),
            *normalize_generic_rows(payload, "events"),
            *news_items_to_event_cards(news_items),
            *announcements_to_event_cards(announcements),
        ],
        "warnings": [*warnings, *payload_warnings],
    }


def build_institutional_evidence_bundle(
    source_items: list[dict[str, Any]],
    *,
    as_of: str | None = None,
    freshness_threshold_hours: float = 72,
) -> dict[str, Any]:
    as_of_dt = parse_datetime(as_of) or datetime.now(UTC)
    normalized = [
        normalize_source_item(
            item,
            as_of=as_of_dt,
            freshness_threshold_hours=freshness_threshold_hours,
        )
        for item in source_items
        if isinstance(item, dict)
    ]
    x_posts = unique_dicts([row for item in normalized for row in item["x_posts"]])
    claims = unique_dicts([row for item in normalized for row in item["claim_candidates"]])
    filings = unique_dicts([row for item in normalized for row in item["filings"]])
    fundamental_reports = unique_dicts([row for item in normalized for row in item["fundamental_reports"]])
    ownership_rows = unique_dicts([row for item in normalized for row in item["ownership_rows"]])
    macro_overlays = unique_dicts(
        [item["macro_health_overlay"] for item in normalized if item["macro_health_overlay"]]
    )
    sector_rankings = unique_dicts([row for item in normalized for row in item["sector_rankings"]])
    sector_views = unique_dicts([row for item in normalized for row in item["sector_views"]])
    capital_flows = unique_dicts([row for item in normalized for row in item["capital_flows"]])
    positioning_flows = unique_dicts([row for item in normalized for row in item["positioning_flows"]])
    announcements = unique_dicts([row for item in normalized for row in item["announcements"]])
    validations = unique_dicts([row for item in normalized for row in item["validations"]])
    backtests = unique_dicts([row for item in normalized for row in item["backtests"]])
    actuals = unique_dicts([row for item in normalized for row in item["actuals"]])
    quant_analysis = unique_dicts([row for item in normalized for row in item["quant_analysis"]])
    source_capabilities = unique_dicts([row for item in normalized for row in item["source_capabilities"]])
    source_health_probes = unique_dicts([row for item in normalized for row in item["source_health_probes"]])
    news_items = unique_dicts([row for item in normalized for row in item["news_items"]])
    event_cards = unique_dicts([row for item in normalized for row in item["event_cards"]])
    warnings = sorted({warning for item in normalized for warning in item["warnings"] if warning})
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "as_of": isoformat_z(as_of_dt),
        "freshness_threshold_hours": freshness_threshold_hours,
        "sources": [item["source"] for item in normalized],
        "x_posts": x_posts,
        "claim_candidates": claims,
        "filings": filings,
        "fundamentals": {"reports": fundamental_reports},
        "ownership": {"records": ownership_rows},
        "macro_health_overlays": macro_overlays,
        "sector_rankings": sector_rankings,
        "sector_views": sector_views,
        "capital_flows": capital_flows,
        "positioning_flows": positioning_flows,
        "announcements": announcements,
        "validations": validations,
        "backtests": backtests,
        "actuals": actuals,
        "quant_analysis": quant_analysis,
        "source_capabilities": source_capabilities,
        "source_health_probes": source_health_probes,
        "news": news_items,
        "event_cards": event_cards,
        "warnings": warnings,
        "summary": {
            "source_count": len(normalized),
            "x_post_count": len(x_posts),
            "claim_count": len(claims),
            "filing_count": len(filings),
            "fundamental_report_count": len(fundamental_reports),
            "ownership_record_count": len(ownership_rows),
            "macro_overlay_count": len(macro_overlays),
            "sector_ranking_count": len(sector_rankings),
            "sector_view_count": len(sector_views),
            "capital_flow_count": len(capital_flows),
            "positioning_flow_count": len(positioning_flows),
            "announcement_count": len(announcements),
            "validation_count": len(validations),
            "backtest_count": len(backtests),
            "actual_count": len(actuals),
            "quant_analysis_count": len(quant_analysis),
            "source_capability_count": len(source_capabilities),
            "source_health_probe_count": len(source_health_probes),
            "news_item_count": len(news_items),
            "event_card_count": len(event_cards),
            "warning_count": len(warnings),
            "live_fetch_source_count": sum(
                1 for item in normalized if item["source"].get("source_mode") == "live_fetch"
            ),
            "source_fetch_error_count": sum(
                1 for item in normalized if item["source"].get("fetch_status") == "error"
            ),
            "stale_source_count": sum(
                1 for item in normalized if item["source"].get("freshness_status") == "stale"
            ),
            "unknown_freshness_source_count": sum(
                1 for item in normalized if item["source"].get("freshness_status") == "unknown"
            ),
        },
    }
    if macro_overlays:
        bundle["macro_health_overlay"] = macro_overlays[0]
    return bundle


def load_source_items(paths: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path_text in paths:
        path = Path(path_text).expanduser().resolve()
        try:
            source_modified_at = isoformat_z(datetime.fromtimestamp(path.stat().st_mtime, UTC))
        except OSError:
            source_modified_at = ""
        items.append(
            {
                "source_path": str(path),
                "source_modified_at": source_modified_at,
                "payload": load_json(path),
            }
        )
    return items


def render_markdown_report(bundle: dict[str, Any]) -> str:
    summary = safe_dict(bundle.get("summary"))
    lines = [
        "# Institutional Evidence Bundle",
        "",
        f"- schema_version: `{clean_text(bundle.get('schema_version'))}`",
        f"- source_count: `{summary.get('source_count', 0)}`",
        f"- x_post_count: `{summary.get('x_post_count', 0)}`",
        f"- filing_count: `{summary.get('filing_count', 0)}`",
        f"- fundamental_report_count: `{summary.get('fundamental_report_count', 0)}`",
        f"- ownership_record_count: `{summary.get('ownership_record_count', 0)}`",
        f"- sector_ranking_count: `{summary.get('sector_ranking_count', 0)}`",
        f"- sector_view_count: `{summary.get('sector_view_count', 0)}`",
        f"- capital_flow_count: `{summary.get('capital_flow_count', 0)}`",
        f"- positioning_flow_count: `{summary.get('positioning_flow_count', 0)}`",
        f"- announcement_count: `{summary.get('announcement_count', 0)}`",
        f"- validation_count: `{summary.get('validation_count', 0)}`",
        f"- backtest_count: `{summary.get('backtest_count', 0)}`",
        f"- source_capability_count: `{summary.get('source_capability_count', 0)}`",
        f"- source_health_probe_count: `{summary.get('source_health_probe_count', 0)}`",
        f"- live_fetch_source_count: `{summary.get('live_fetch_source_count', 0)}`",
        f"- source_fetch_error_count: `{summary.get('source_fetch_error_count', 0)}`",
        f"- stale_source_count: `{summary.get('stale_source_count', 0)}`",
        "",
        "## Sources",
        "",
    ]
    for source in safe_list(bundle.get("sources")):
        if not isinstance(source, dict):
            continue
        parts = [
            f"`{clean_text(source.get('kind'))}`",
            f"status=`{clean_text(source.get('status'))}`",
            f"freshness=`{clean_text(source.get('freshness_status'))}`",
            f"age_hours=`{source.get('source_age_hours')}`",
        ]
        if clean_text(source.get("source_mode")):
            parts.append(f"mode=`{clean_text(source.get('source_mode'))}`")
        if clean_text(source.get("fetch_status")):
            parts.append(f"fetch=`{clean_text(source.get('fetch_status'))}`")
        source_fetch_error = clean_text(source.get("fetch_error") or source.get("notice_fetch_error"))
        if source_fetch_error:
            parts.append(f"fetch_error=`{source_fetch_error}`")
        parts.append(f"path=`{clean_text(source.get('path'))}`")
        lines.append("- " + " ".join(parts))
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize institutional evidence artifacts into one bundle.")
    parser.add_argument("inputs", nargs="*", help="Input JSON artifacts such as x-index or TradingAgents results.")
    parser.add_argument("--output", required=True, help="Output bundle JSON path.")
    parser.add_argument("--markdown-output", default="", help="Optional markdown report path.")
    parser.add_argument("--as-of", default="", help="Optional ISO timestamp used for evidence freshness scoring.")
    parser.add_argument(
        "--sec-ticker",
        action="append",
        default=[],
        help="Optional U.S. ticker to fetch through the SEC fundamentals public-source adapter.",
    )
    parser.add_argument(
        "--macro-health-request",
        action="append",
        default=[],
        help="Optional macro-health overlay request JSON to run and include as macro regime evidence.",
    )
    parser.add_argument(
        "--eastmoney-sector-request",
        action="append",
        default=[],
        help="Optional request JSON for the repo-native Eastmoney sector rankings public-source adapter.",
    )
    parser.add_argument(
        "--eastmoney-notice-stock",
        action="append",
        default=[],
        help="Optional stock JSON for the Eastmoney notice-cache adapter, using the repo .tmp notice cache.",
    )
    parser.add_argument(
        "--akshare-fundamental-stock",
        action="append",
        default=[],
        help="Optional stock JSON for the AKShare A-share fundamental metrics adapter.",
    )
    parser.add_argument(
        "--refresh-eastmoney-notices",
        action="store_true",
        help="When an Eastmoney notice cache is missing or empty, try the public Eastmoney notice endpoint for --eastmoney-notice-stock inputs.",
    )
    parser.add_argument(
        "--source-capabilities",
        action="store_true",
        help="Include a local source capability snapshot for optional packages and repo-native adapters.",
    )
    parser.add_argument(
        "--source-health-probes",
        action="store_true",
        help="Include source health probe status separated from adapter availability.",
    )
    parser.add_argument(
        "--run-live-source-probes",
        action="store_true",
        help="Attempt live endpoint probes for source-health-probes. May require network access.",
    )
    parser.add_argument(
        "--longbridge-binary",
        default="",
        help="Optional explicit path to the Longbridge CLI binary; overrides PATH discovery for capability + probe rows.",
    )
    parser.add_argument(
        "--no-weekday-fallback",
        action="store_true",
        help="Disable the weekday-based weekend fallback for closed-market probe downgrades.",
    )
    parser.add_argument("--analysis-date", default="", help="Analysis date for public-source adapters.")
    parser.add_argument(
        "--freshness-threshold-hours",
        type=float,
        default=72,
        help="Maximum source age in hours before a source is marked stale.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_items = load_source_items(args.inputs)
    analysis_date = clean_text(args.analysis_date) or clean_text(args.as_of)[:10]
    for ticker in args.sec_ticker:
        source_items.append(build_sec_fundamentals_source_item(ticker, analysis_date))
    for request_path_text in args.macro_health_request:
        request_path = Path(request_path_text).expanduser().resolve()
        source_items.append(
            build_macro_health_source_item(
                load_json(request_path),
                source_path=str(request_path),
            )
        )
    for request_path_text in args.eastmoney_sector_request:
        request_path = Path(request_path_text).expanduser().resolve()
        source_items.append(
            build_eastmoney_sector_source_item(
                load_json(request_path),
                source_path=str(request_path),
            )
        )
    for stock_path_text in args.eastmoney_notice_stock:
        stock_path = Path(stock_path_text).expanduser().resolve()
        source_items.append(
            build_eastmoney_notice_source_item(
                load_json(stock_path),
                source_path=str(stock_path),
                refresh_notices=args.refresh_eastmoney_notices,
            )
        )
    for stock_path_text in args.akshare_fundamental_stock:
        stock_path = Path(stock_path_text).expanduser().resolve()
        source_items.append(
            build_akshare_fundamental_source_item(
                load_json(stock_path),
                source_path=str(stock_path),
            )
        )
    longbridge_overrides: dict[str, str] = {}
    if clean_text(args.longbridge_binary):
        longbridge_overrides["host.longbridge_cli"] = clean_text(args.longbridge_binary)
    if args.source_capabilities:
        source_items.append(
            build_source_capability_source_item(
                host_binary_overrides=longbridge_overrides or None,
            )
        )
    if args.source_health_probes:
        capability_snapshot = build_source_capability_snapshot(
            host_binary_overrides=longbridge_overrides or None,
        )
        source_items.append(
            {
                "source_path": "local://source-health-probe-snapshot",
                "source_modified_at": isoformat_z(datetime.now(UTC)),
                "payload": build_source_health_probe_snapshot(
                    capability_snapshot=capability_snapshot,
                    run_live_probes=args.run_live_source_probes,
                    weekday_fallback=not args.no_weekday_fallback,
                ),
            }
        )
    if not source_items:
        raise SystemExit("At least one input JSON or public-source adapter request is required.")
    bundle = build_institutional_evidence_bundle(
        source_items,
        as_of=args.as_of or None,
        freshness_threshold_hours=args.freshness_threshold_hours,
    )
    output_path = Path(args.output).expanduser().resolve()
    write_json(output_path, bundle)
    if clean_text(args.markdown_output):
        report_path = Path(args.markdown_output).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_markdown_report(bundle), encoding="utf-8")
    return 0


__all__ = [
    "build_institutional_evidence_bundle",
    "build_macro_health_source_item",
    "build_akshare_fundamental_source_item",
    "build_eastmoney_notice_source_item",
    "build_eastmoney_sector_source_item",
    "build_sec_fundamentals_source_item",
    "build_source_capability_snapshot",
    "build_source_capability_source_item",
    "build_source_health_probe_snapshot",
    "build_source_health_probe_source_item",
    "default_longbridge_market_session_index",
    "default_longbridge_run_json",
    "detect_source_kind",
    "default_eastmoney_sector_rankings_fetcher",
    "default_parse_eastmoney_notices",
    "default_build_macro_health_overlay_result",
    "default_build_sector_views_from_rankings",
    "default_sec_get_fundamentals",
    "is_session_closed",
    "load_source_items",
    "main",
    "normalize_longbridge_market_status_payload",
    "render_markdown_report",
    "resolve_host_binary_path",
    "weekday_market_session_index",
]


if __name__ == "__main__":
    raise SystemExit(main())
