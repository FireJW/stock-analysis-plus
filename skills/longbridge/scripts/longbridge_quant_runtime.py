#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[[list[str], dict[str, str] | None, int], Any]
SCRIPT_DIR = Path(__file__).resolve().parent
TRADINGAGENTS_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "tradingagents-decision-bridge" / "scripts"
DEFAULT_PERIOD = "day"
RUN_TIMEOUT_SECONDS = 30
DEFAULT_QUANT_SCRIPTS: tuple[dict[str, Any], ...] = (
    {
        "name": "trend_momentum",
        "script": "\n".join(
            [
                "//@version=6",
                "indicator('Trend Momentum')",
                "fast = ta.ema(close, 20)",
                "slow = ta.ema(close, 60)",
                "plot(fast - slow, title='momentum')",
            ]
        ),
    },
    {
        "name": "rsi_bias",
        "script": "\n".join(
            [
                "//@version=6",
                "indicator('RSI Bias')",
                "rsi = ta.rsi(close, 14)",
                "plot(rsi - 50, title='rsi_bias')",
            ]
        ),
    },
)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", " ").split()).strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"), strict=False)
    return payload if isinstance(payload, dict) else {}


def load_longbridge_cli_runner() -> CommandRunner:
    if str(TRADINGAGENTS_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(TRADINGAGENTS_SCRIPT_DIR))
    from tradingagents_longbridge_market import run_longbridge_cli

    return run_longbridge_cli


def to_float(value: Any) -> float:
    if isinstance(value, bool):
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def normalize_tickers(request: dict[str, Any]) -> list[str]:
    raw_tickers = request.get("tickers") or request.get("symbols") or []
    if isinstance(raw_tickers, str):
        raw_tickers = [item.strip() for item in raw_tickers.split(",")]
    return [clean_text(item) for item in raw_tickers if clean_text(item)]


def normalize_input_value(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_quant_scripts(request: dict[str, Any]) -> list[dict[str, Any]]:
    raw_scripts: list[Any] = []
    for key in ("quant_scripts", "indicators"):
        value = request.get(key)
        if isinstance(value, list):
            raw_scripts.extend(value)
        elif value:
            raw_scripts.append(value)

    if not raw_scripts:
        return [deepcopy(item) for item in DEFAULT_QUANT_SCRIPTS]

    scripts: list[dict[str, Any]] = []
    for index, item in enumerate(raw_scripts, start=1):
        if isinstance(item, str):
            script_text = str(item).strip()
            name = f"script_{index}"
            input_value = None
        elif isinstance(item, dict):
            script_text = str(item.get("script") or item.get("script_text") or item.get("text") or "").strip()
            name = clean_text(item.get("name") or item.get("indicator") or f"script_{index}")
            input_value = item.get("input", item.get("inputs"))
        else:
            continue
        if not script_text:
            continue
        script: dict[str, Any] = {"name": name, "script": script_text}
        if input_value is not None:
            script["input"] = input_value
        scripts.append(script)
    return scripts or [deepcopy(item) for item in DEFAULT_QUANT_SCRIPTS]


def build_quant_run_args(symbol: str, script: dict[str, Any], start: str, end: str, period: str) -> list[str]:
    args = [
        "quant",
        "run",
        symbol,
        "--period",
        period,
        "--start",
        start,
        "--end",
        end,
        "--script",
        str(script.get("script") or ""),
    ]
    if "input" in script:
        args.extend(["--input", normalize_input_value(script.get("input"))])
    args.extend(["--format", "json"])
    return args


def latest_numeric(value: Any) -> float:
    direct = to_float(value)
    if is_finite_number(direct):
        return direct
    if isinstance(value, list):
        for item in reversed(value):
            nested = latest_numeric(item)
            if is_finite_number(nested):
                return nested
    if isinstance(value, dict):
        for key in ("value", "latest", "last", "y", "v", "close"):
            if key in value:
                nested = latest_numeric(value.get(key))
                if is_finite_number(nested):
                    return nested
        for nested_value in reversed(list(value.values())):
            nested = latest_numeric(nested_value)
            if is_finite_number(nested):
                return nested
    return float("nan")


def add_latest_value(indicators: dict[str, float], name: str, value: Any) -> None:
    latest = latest_numeric(value)
    if is_finite_number(latest):
        indicators[clean_text(name) or f"value_{len(indicators) + 1}"] = float(latest)


def extract_latest_values(payload: Any) -> dict[str, float]:
    indicators: dict[str, float] = {}
    if isinstance(payload, dict):
        series = payload.get("series")
        if isinstance(series, dict):
            for name, values in series.items():
                add_latest_value(indicators, clean_text(name), values)

        values = payload.get("values")
        if isinstance(values, dict):
            for name, value in values.items():
                add_latest_value(indicators, clean_text(name), value)
        elif values is not None:
            add_latest_value(indicators, "value", values)

        plots = payload.get("plots")
        if isinstance(plots, list):
            for index, plot in enumerate(plots, start=1):
                if not isinstance(plot, dict):
                    add_latest_value(indicators, f"plot_{index}", plot)
                    continue
                name = clean_text(plot.get("name") or plot.get("title") or f"plot_{index}")
                plot_values = plot.get("values", plot.get("series", plot.get("data", plot.get("value"))))
                add_latest_value(indicators, name, plot_values)

        if not indicators:
            add_latest_value(indicators, "value", payload)
    else:
        add_latest_value(indicators, "value", payload)
    return indicators


def score_latest_value(name: str, value: float) -> int:
    if not is_finite_number(value):
        return 0
    normalized_name = clean_text(name).lower()
    if "rsi" in normalized_name and 0 <= value <= 100:
        if value >= 55:
            return 1
        if value <= 45:
            return -1
        return 0
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def alignment_from_score(score: int) -> str:
    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"
    return "neutral"


def normalize_quant_payload(payload: Any) -> dict[str, Any]:
    latest_values = extract_latest_values(payload)
    score = sum(score_latest_value(name, value) for name, value in latest_values.items())
    alignment = alignment_from_score(score)
    return {
        "alignment": alignment,
        "score": score,
        "latest_values": latest_values,
        "raw_payload": payload,
    }


def aggregate_alignments(alignments: list[str]) -> dict[str, Any]:
    counts = {
        "bullish": sum(1 for item in alignments if item == "bullish"),
        "bearish": sum(1 for item in alignments if item == "bearish"),
        "neutral": sum(1 for item in alignments if item == "neutral"),
    }
    score = counts["bullish"] - counts["bearish"]
    return {
        "overall": alignment_from_score(score),
        "score": score,
        "counts": counts,
    }


def run_longbridge_quant_analysis(
    request: dict[str, Any],
    *,
    runner: CommandRunner,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    tickers = normalize_tickers(request)
    start = clean_text(request.get("start"))
    end = clean_text(request.get("end"))
    if not start or not end:
        raise ValueError("Longbridge quant analysis requires request start and end values.")
    period = clean_text(request.get("period")) or DEFAULT_PERIOD
    scripts = normalize_quant_scripts(request)

    quant_analysis: dict[str, dict[str, dict[str, Any]]] = {}
    indicators: dict[str, dict[str, dict[str, Any]]] = {}
    unavailable: list[dict[str, str]] = []
    attempted_runs = 0
    successful_runs = 0

    for symbol in tickers:
        quant_analysis[symbol] = {}
        indicators[symbol] = {}
        for script in scripts:
            script_name = clean_text(script.get("name"))
            attempted_runs += 1
            args = build_quant_run_args(symbol, script, start, end, period)
            try:
                payload = runner(args, env, RUN_TIMEOUT_SECONDS)
            except Exception as exc:
                unavailable.append(
                    {
                        "symbol": symbol,
                        "script_name": script_name,
                        "command": "quant run",
                        "reason": clean_text(exc),
                    }
                )
                continue

            normalized = normalize_quant_payload(payload)
            analysis_item = {
                "symbol": symbol,
                "script_name": script_name,
                "period": period,
                "start": start,
                "end": end,
                **normalized,
            }
            quant_analysis[symbol][script_name] = analysis_item
            indicators[symbol][script_name] = {
                "alignment": normalized["alignment"],
                "score": normalized["score"],
                "latest_values": normalized["latest_values"],
            }
            successful_runs += 1

    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol, items in quant_analysis.items():
        symbol_alignments = [item.get("alignment", "neutral") for item in items.values()]
        by_symbol[symbol] = aggregate_alignments(symbol_alignments)
        by_symbol[symbol]["scripts"] = {
            script_name: item.get("alignment", "neutral") for script_name, item in items.items()
        }

    all_alignments = [
        item.get("alignment", "neutral")
        for symbol_items in quant_analysis.values()
        for item in symbol_items.values()
    ]
    signal_alignment = aggregate_alignments(all_alignments)
    signal_alignment["by_symbol"] = by_symbol

    failed_runs = len(unavailable)
    data_coverage = {
        "requested_symbols": len(tickers),
        "requested_scripts": len(scripts),
        "attempted_runs": attempted_runs,
        "successful_runs": successful_runs,
        "failed_runs": failed_runs,
        "symbols_with_data": sum(1 for items in quant_analysis.values() if items),
        "coverage_ratio": round(successful_runs / attempted_runs, 4) if attempted_runs else 0.0,
    }

    return {
        "request": deepcopy(request),
        "quant_analysis": quant_analysis,
        "indicators": indicators,
        "signal_alignment": signal_alignment,
        "data_coverage": data_coverage,
        "unavailable": unavailable,
        "should_apply": False,
        "side_effects": "none",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run read-only Longbridge quant indicator diagnostics.")
    parser.add_argument("request_json", help="Path to request JSON.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args(argv)

    request = load_json(Path(args.request_json))
    result = run_longbridge_quant_analysis(
        request,
        runner=load_longbridge_cli_runner(),
        env=dict(os.environ),
    )
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
