#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from typing import Any

from local_stock_pool_runtime import clean_text


__all__ = [
    "display_status_text",
    "parse_float",
    "render_html_table",
    "safe_dict",
    "safe_list",
    "title_case_display_text",
]


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_float(value: Any) -> float | None:
    text = clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def display_status_text(value: Any, default: str = "") -> str:
    text = clean_text(value)
    if not text:
        return default
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def title_case_display_text(value: Any, default: str = "") -> str:
    text = display_status_text(value, default)
    return text[:1].upper() + text[1:] if text else ""


def render_html_table(table_class: str, headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header_html = "".join(f"<th>{html.escape(clean_text(header))}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(clean_text(cell))}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-wrap">'
        f'<table class="{html.escape(table_class)}">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )
