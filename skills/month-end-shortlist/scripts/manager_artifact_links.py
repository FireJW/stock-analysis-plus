#!/usr/bin/env python3
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from local_stock_pool_runtime import clean_text


def render_file_link(path_text: Any, label: str) -> str:
    path = clean_text(path_text)
    if not path:
        return ""
    try:
        href = Path(path).expanduser().resolve().as_uri()
    except (OSError, ValueError):
        return ""
    return (
        '<a class="artifact-link" href="'
        f'{html.escape(href)}" target="_blank" rel="noreferrer">'
        f"{html.escape(label)}</a>"
    )


def artifact_label_for_path(path_text: Any, fallback: str) -> str:
    path = clean_text(path_text)
    if not path:
        return fallback
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or fallback
