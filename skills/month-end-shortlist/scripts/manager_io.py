#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import load_json


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")


def load_pool_or_template(path: str | Path | None = None) -> dict[str, Any]:
    if path:
        payload = load_json(path)
        if isinstance(payload, dict) and isinstance(payload.get("local_stock_pool"), dict):
            return payload["local_stock_pool"]
        if isinstance(payload, dict):
            return payload
    return {
        "name": "local-watch-pool",
        "stocks": [],
        "strategy_rules": [
            {
                "name": "MA20 reclaim",
                "conditions": ["close_above_ma20", "ma20_turning_up"],
                "usage_boundary": "technical_context_only",
            }
        ],
    }


__all__ = [
    "load_pool_or_template",
    "write_json",
]
