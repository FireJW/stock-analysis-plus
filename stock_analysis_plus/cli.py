from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SKILLS = {
    "longbridge": "Market data adapters and Longbridge references",
    "macro-health-overlay": "Macro regime overlay runner",
    "month-end-shortlist": "Stock shortlist and evidence bundle workflows",
}


def list_skills() -> int:
    for name, description in SKILLS.items():
        path = ROOT / "skills" / name
        marker = "available" if path.exists() else "missing"
        print(f"{name:24} {marker:9} {description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stock-analysis-plus")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("list", help="List packaged workflows")
    args = parser.parse_args(argv)
    if args.command in (None, "list"):
        return list_skills()
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
