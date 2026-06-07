#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from typing import Any


def safe_json_for_script(payload: dict[str, Any]) -> str:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_json_preview_text(payload: Any) -> str:
    return html.escape(json.dumps(payload, ensure_ascii=False, indent=2))


__all__ = [
    "render_json_preview_text",
    "safe_json_for_script",
]
