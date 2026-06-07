#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from manager_html_primitives import parse_float, safe_dict, safe_list


def calendar_watch_count(package: dict[str, Any], key: str) -> int:
    watch = safe_dict(package.get(key))
    summary = safe_dict(watch.get("summary"))
    parsed = parse_float(summary.get("event_count"))
    if parsed is not None:
        return int(parsed)
    return len([row for row in safe_list(watch.get("events")) if isinstance(row, dict)])


def calendar_source_error_count(package: dict[str, Any], key: str) -> int:
    watch = safe_dict(package.get(key))
    summary = safe_dict(watch.get("summary"))
    parsed = parse_float(summary.get("source_error_count"))
    if parsed is not None:
        return int(parsed)
    return len([row for row in safe_list(watch.get("source_errors")) if isinstance(row, dict)])


__all__ = [
    "calendar_source_error_count",
    "calendar_watch_count",
]
