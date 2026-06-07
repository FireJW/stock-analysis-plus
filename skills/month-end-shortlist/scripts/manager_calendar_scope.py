#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text, unique_strings
from manager_html_primitives import title_case_display_text


CALENDAR_SCOPE_LABELS = {
    "high_importance": "High importance",
    "local_stock_pool": "Local pool",
    "local_pool": "Local pool",
    "manual_focus": "Manual focus",
    "industry_leader": "Industry leader",
    "market_cap_headliner": "Market cap headliner",
    "macro": "Macro watch",
    "macro_policy": "Macro policy",
}


def calendar_scope_labels(scope: Any) -> list[str]:
    labels: list[str] = []
    for item in clean_string_list(scope):
        key = clean_text(item)
        label = CALENDAR_SCOPE_LABELS.get(key, title_case_display_text(key))
        if label:
            labels.append(label)
    return unique_strings(labels)


def render_calendar_scope_chips(scope: Any) -> str:
    labels = calendar_scope_labels(scope)
    if not labels:
        return '<span class="muted-text">General watch</span>'
    return "".join(f'<span class="calendar-scope-chip">{html.escape(label)}</span>' for label in labels)


__all__ = [
    "CALENDAR_SCOPE_LABELS",
    "calendar_scope_labels",
    "render_calendar_scope_chips",
]
