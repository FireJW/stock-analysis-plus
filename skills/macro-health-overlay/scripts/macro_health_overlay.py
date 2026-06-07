#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from macro_health_overlay_runtime import build_macro_health_overlay_result, load_json, write_json


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bounded macro-health overlay for shortlist workflows.")
    parser.add_argument("request_json", help="Path to the macro-health overlay request JSON.")
    parser.add_argument("--output", help="Write the JSON result to this path.")
    parser.add_argument("--markdown-output", help="Write the markdown report to this path.")
    parser.add_argument(
        "--request-output",
        help="Optional path to write the resolved month-end-shortlist request when shortlist_request_path is supplied.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    request = load_json(Path(args.request_json).expanduser().resolve())
    result = build_macro_health_overlay_result(request)

    if args.output:
        write_json(Path(args.output).expanduser().resolve(), result)
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")

    if args.markdown_output:
        markdown_path = Path(args.markdown_output).expanduser().resolve()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(str(result.get("report_markdown") or ""), encoding="utf-8")

    if args.request_output and isinstance(result.get("resolved_shortlist_request"), dict):
        write_json(Path(args.request_output).expanduser().resolve(), result["resolved_shortlist_request"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
