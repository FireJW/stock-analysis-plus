#!/usr/bin/env python3
from __future__ import annotations

import argparse
from importlib.machinery import SourcelessFileLoader
from importlib.util import module_from_spec, spec_from_loader
import json
from pathlib import Path
import sys


PYC_PATH = (
    Path(__file__).resolve().parents[2]
    / "short-horizon-shortlist"
    / "scripts"
    / "__pycache__"
    / "month_end_shortlist.cpython-312.pyc"
)


def load_compiled_module():
    if not PYC_PATH.exists():
        raise ModuleNotFoundError(f"Compiled month_end_shortlist artifact is missing: {PYC_PATH}")
    loader = SourcelessFileLoader(__name__ + "._compiled", str(PYC_PATH))
    spec = spec_from_loader(__name__ + "._compiled", loader)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to create an import spec for {PYC_PATH}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_compiled = load_compiled_module()
__doc__ = getattr(_compiled, "__doc__", None)

for _name in dir(_compiled):
    if _name.startswith("__") and _name not in {"__all__"}:
        continue
    globals()[_name] = getattr(_compiled, _name)

if "__all__" not in globals():
    __all__ = [name for name in dir(_compiled) if not name.startswith("_")]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run month_end_shortlist through the wrapper runtime.")
    parser.add_argument("request_json", help="Path to the shortlist request JSON.")
    parser.add_argument("--output", help="Write shortlist result JSON to this path.")
    parser.add_argument("--markdown-output", help="Write shortlist markdown report to this path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from month_end_shortlist_runtime import (
        apply_default_macro_health_overlay,
        build_markdown_report,
        load_json,
        run_month_end_shortlist,
        write_json,
    )

    args = parse_args(argv)
    request = load_json(Path(args.request_json))
    request = apply_default_macro_health_overlay(request, request, enabled=True)
    result = run_month_end_shortlist(request)
    if args.output:
        write_json(Path(args.output), result)
    if args.markdown_output:
        Path(args.markdown_output).expanduser().resolve().write_text(
            str(result.get("report_markdown") or build_markdown_report(result)),
            encoding="utf-8",
        )
    if not args.output:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0

for _extra in ("parse_args",):
    if _extra not in __all__:
        __all__.append(_extra)


if __name__ == "__main__":
    raise SystemExit(main())
