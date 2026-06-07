#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from month_end_shortlist_runtime import build_markdown_report, load_json, run_month_end_shortlist, write_json


SCRIPT_DIR = Path(__file__).resolve().parent
MACRO_HEALTH_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "macro-health-overlay" / "scripts"
A_SHARE_SENTIMENT_SCRIPT_DIR = SCRIPT_DIR.parents[1] / "a-share-sentiment-overlay" / "scripts"
for _path in (MACRO_HEALTH_SCRIPT_DIR, A_SHARE_SENTIMENT_SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

DEFAULT_MACRO_HEALTH_REQUEST = (
    SCRIPT_DIR.parents[1]
    / "macro-health-overlay"
    / "examples"
    / "macro-health-overlay-public-mix.request.template.json"
)

try:
    from macro_health_overlay_runtime import build_macro_health_overlay_result
except ModuleNotFoundError:  # pragma: no cover
    def build_macro_health_overlay_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ModuleNotFoundError("macro_health_overlay_runtime")

try:
    from a_share_sentiment_overlay_runtime import build_a_share_sentiment_overlay_result
except ModuleNotFoundError:  # pragma: no cover
    def build_a_share_sentiment_overlay_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ModuleNotFoundError("a_share_sentiment_overlay_runtime")

try:
    from a_share_sentiment_overlay_runtime import build_cross_market_reference_overlay_result
except ModuleNotFoundError:  # pragma: no cover
    def build_cross_market_reference_overlay_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ModuleNotFoundError("a_share_sentiment_overlay_runtime")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run macro-health overlay and optional sentiment overlay before month_end_shortlist.")
    parser.add_argument("shortlist_request_json", help="Base shortlist request JSON.")
    parser.add_argument("macro_health_request_json", nargs="?", default="", help="Optional macro-health overlay request JSON.")
    parser.add_argument("--output", help="Write shortlist result JSON to this path.")
    parser.add_argument("--markdown-output", help="Write shortlist markdown report to this path.")
    parser.add_argument("--overlay-output", help="Write macro-health overlay JSON to this path.")
    parser.add_argument("--resolved-request-output", help="Write resolved shortlist request JSON to this path.")
    parser.add_argument("--sentiment-request-json", help="Optional A-share sentiment overlay request JSON.")
    parser.add_argument("--sentiment-output", help="Write sentiment overlay JSON to this path.")
    parser.add_argument("--cross-market-reference-json", help="Optional US AI / technology reference overlay JSON.")
    parser.add_argument("--cross-market-reference-output", help="Write cross-market reference overlay JSON to this path.")
    return parser.parse_args(argv)


def merge_overlay(shortlist_request: dict[str, Any], overlay_result: dict[str, Any], overlay_key: str) -> dict[str, Any]:
    request = dict(shortlist_request)
    payload = overlay_result.get(overlay_key)
    if isinstance(payload, dict):
        request[overlay_key] = payload
    return request


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    shortlist_request = load_json(Path(args.shortlist_request_json))

    macro_request_path = Path(args.macro_health_request_json) if args.macro_health_request_json else DEFAULT_MACRO_HEALTH_REQUEST
    macro_result = build_macro_health_overlay_result(load_json(macro_request_path))
    resolved_request = merge_overlay(shortlist_request, macro_result, "macro_health_overlay")

    sentiment_result: dict[str, Any] | None = None
    if args.sentiment_request_json:
        sentiment_result = build_a_share_sentiment_overlay_result(load_json(Path(args.sentiment_request_json)))
        resolved_request = merge_overlay(resolved_request, sentiment_result, "sentiment_vol_overlay")

    cross_market_result: dict[str, Any] | None = None
    if args.cross_market_reference_json:
        cross_market_result = build_cross_market_reference_overlay_result(load_json(Path(args.cross_market_reference_json)))
        resolved_request = merge_overlay(resolved_request, cross_market_result, "cross_market_reference_overlay")

    result = run_month_end_shortlist(resolved_request)

    if args.output:
        write_json(Path(args.output), result)
    if args.markdown_output:
        Path(args.markdown_output).expanduser().resolve().write_text(
            str(result.get("report_markdown") or build_markdown_report(result)),
            encoding="utf-8",
        )
    if args.overlay_output:
        write_json(Path(args.overlay_output), macro_result)
    if args.resolved_request_output:
        write_json(Path(args.resolved_request_output), resolved_request)
    if args.sentiment_output and sentiment_result is not None:
        write_json(Path(args.sentiment_output), sentiment_result)
    if args.cross_market_reference_output and cross_market_result is not None:
        write_json(Path(args.cross_market_reference_output), cross_market_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
