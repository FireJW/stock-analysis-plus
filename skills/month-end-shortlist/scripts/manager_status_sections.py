#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


MAIN_STATUS_SECTION_ORDER = (
    "macro_health_overlay",
    "earnings_calendar_watch",
    "event_calendar_watch",
    "fresh_discovery",
    "entry_list_screening",
    "trigger_monitor",
    "ticker_quote_news_coverage",
    "stock_logic_check",
    "thesis_fact_check",
    "trade_journal",
    "direction_risk_register",
    "fresh_discovery_sector",
    "postclose_review",
    "postclose_observation",
    "institutional_actionability_gate",
    "institutional_audit",
    "institutional_evidence_followups",
)

SOURCE_STATUS_SECTION_ORDER = (
    "source_capabilities",
    "source_health_probes",
)


def render_status_sections(sections: dict[str, Any], order: tuple[str, ...]) -> str:
    rendered = [str(sections.get(key)) for key in order if sections.get(key)]
    return "\n      ".join(rendered)


__all__ = [
    "MAIN_STATUS_SECTION_ORDER",
    "SOURCE_STATUS_SECTION_ORDER",
    "render_status_sections",
]
