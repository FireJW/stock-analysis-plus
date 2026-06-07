#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_artifact_links import artifact_label_for_path, render_file_link
from manager_html_primitives import safe_dict


LOGIC_CHECK_BLOCKING_STATUSES = {
    "blocked",
    "partial",
    "pending",
    "review",
    "needs_review",
    "unknown",
    "thin",
    "fail",
    "failed",
    "unverified",
}


def _longbridge_source_metric_block(source_health: dict[str, Any]) -> str:
    rows: list[str] = []
    for key, label in (
        ("longbridge_financial_report_count", "Financial reports"),
        ("longbridge_operating_review_count", "Operating reviews"),
        ("longbridge_industry_valuation_count", "Industry valuation"),
        ("longbridge_expectation_source_count", "Expectation rows"),
        ("longbridge_filing_count", "Filings"),
        ("longbridge_topic_count", "Topics"),
        ("longbridge_capital_flow_count", "Capital flow"),
        ("news_detail_html_fallback_success_count", "HTML full text"),
        ("news_detail_language_fallback_success_count", "Language fallback"),
        ("news_detail_cache_hit_count", "Detail cache hits"),
        ("latest_news_detail_age_days", "Latest detail age"),
    ):
        value = clean_text(source_health.get(key))
        if not value or value == "0":
            continue
        rows.append(
            f'<div><span class="metric-value">{html.escape(value)}</span>'
            f'<span class="metric-label">{html.escape(label)}</span></div>'
        )
    if not rows:
        return ""
    return '<div class="coverage-metrics source-breadth-metrics">' + "".join(rows) + "</div>"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _followup_fulltext_metric_parts(followup: dict[str, Any]) -> list[str]:
    post_count = _safe_int(followup.get("result_post_count"))
    browser_session_count = _safe_int(followup.get("result_browser_session_post_count"))
    detail_text_count = _safe_int(followup.get("result_dom_text_post_count"))
    hydrated_detail_count = _safe_int(followup.get("result_hydrated_detail_post_count"))
    expanded_detail_count = _safe_int(followup.get("result_expanded_detail_post_count"))
    thread_text_count = _safe_int(followup.get("result_thread_text_post_count"))
    news_detail_count = _safe_int(followup.get("result_news_detail_usable_count"))
    news_detail_error_count = _safe_int(followup.get("result_news_detail_error_count"))
    max_text_length = _safe_int(followup.get("result_max_text_length"))
    parts: list[str] = []
    if post_count:
        if browser_session_count:
            parts.append(f"browser session {browser_session_count}/{post_count}")
        if detail_text_count:
            parts.append(f"dom/detail text {detail_text_count}/{post_count}")
        if hydrated_detail_count:
            parts.append(f"hydrated detail {hydrated_detail_count}/{post_count}")
        if expanded_detail_count:
            parts.append(f"expanded detail {expanded_detail_count}/{post_count}")
        if thread_text_count:
            parts.append(f"thread text {thread_text_count}/{post_count}")
    if news_detail_count:
        parts.append(f"news detail usable {news_detail_count}")
        if news_detail_error_count:
            parts.append(f"news detail error {news_detail_error_count}")
    if max_text_length:
        parts.append(f"max text {max_text_length}")
    return parts


def render_institutional_signal_audit_status(package: dict[str, Any]) -> str:
    audit = safe_dict(package.get("institutional_signal_audit"))
    if not audit:
        return ""
    status = clean_text(audit.get("status")) or "unknown"
    status_class = "covered" if status == "institutional_ready" else "pending"
    score = clean_text(audit.get("score"))
    max_score = clean_text(audit.get("max_score"))
    ratio = clean_text(audit.get("coverage_ratio"))
    missing = [clean_text(item) for item in audit.get("missing_required", []) if clean_text(item)]
    missing_text = ", ".join(missing) if missing else "none"
    source_health = safe_dict(audit.get("source_health")) or safe_dict(package.get("source_health"))
    source_metric_block = _longbridge_source_metric_block(source_health)
    upgrade_priorities = [
        row
        for row in (audit.get("upgrade_priorities") if isinstance(audit.get("upgrade_priorities"), list) else [])
        if isinstance(row, dict)
    ]
    upgrade_rows: list[str] = []
    for item in upgrade_priorities[:5]:
        item_id = clean_text(item.get("id"))
        label = clean_text(item.get("label")) or item_id
        item_status = clean_text(item.get("status")) or "partial"
        missing_items = item.get("missing")
        missing_detail = ", ".join(
            clean_text(value)
            for value in (missing_items if isinstance(missing_items, list) else [])
            if clean_text(value)
        )
        evidence_items = item.get("evidence")
        evidence_detail = "; ".join(
            clean_text(value)
            for value in (evidence_items if isinstance(evidence_items, list) else [])
            if clean_text(value)
        )
        rationale = clean_text(item.get("rationale"))
        detail_parts = [part for part in (missing_detail, evidence_detail, rationale) if part]
        detail = " | ".join(detail_parts) or "optional evidence not attached"
        upgrade_rows.append(
            '<div class="source-status-item audit-upgrade-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(item_id)}</span>'
            f'<span class="overview-name">{html.escape(label)}</span>'
            "</div>"
            f'<span class="status-pill status-pending">{html.escape(item_status)}</span>'
            f'<span class="metric-label">{html.escape(detail)}</span>'
            "</div>"
        )
    upgrade_block = ""
    if upgrade_rows:
        upgrade_block = (
            '<p class="data-note">Upgrade priorities</p>'
            '<div class="source-status-list audit-upgrade-list">'
            + "".join(upgrade_rows)
            + "</div>"
        )
    artifact_links = "".join(
        link
        for link in (
            render_file_link(package.get("institutional_signal_audit_path"), "institutional-signal-audit.json"),
            render_file_link(package.get("institutional_signal_audit_report_path"), "institutional-signal-audit.md"),
        )
        if link
    )
    artifact_link_block = f'<div class="artifact-links">{artifact_links}</div>' if artifact_links else ""
    return (
        '<section id="institutional-signal-audit" class="institutional-audit-status" aria-label="Institutional signal audit status">'
        '<div class="section-head">'
        "<h2>Institutional Signal Audit</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(status)}</span>'
        "</div>"
        '<div class="institutional-audit-body">'
        "<p>This package was checked against the institutional signal stack before delivery.</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(score or "0")}</span><span class="metric-label">Score</span></div>'
        f'<div><span class="metric-value">{html.escape(max_score or "0")}</span><span class="metric-label">Max</span></div>'
        f'<div><span class="metric-value">{html.escape(ratio or "0")}</span><span class="metric-label">Coverage</span></div>'
        "</div>"
        f"{source_metric_block}"
        f'<p class="data-note">Missing required layers: {html.escape(missing_text)}</p>'
        f"{upgrade_block}"
        f"{artifact_link_block}"
        "</div>"
        "</section>"
    )


def _logic_check_blocking_requirement(stock_logic_check: dict[str, Any]) -> dict[str, Any]:
    status = clean_text(stock_logic_check.get("status")) or "partial"
    rows = [
        row
        for row in (stock_logic_check.get("rows") if isinstance(stock_logic_check.get("rows"), list) else [])
        if isinstance(row, dict)
    ]
    blocking_rows = [
        row
        for row in rows
        if clean_text(row.get("status")).lower() in LOGIC_CHECK_BLOCKING_STATUSES
    ]
    if not blocking_rows and status.lower() in LOGIC_CHECK_BLOCKING_STATUSES:
        blocking_rows = rows[:3]
    identities: list[str] = []
    missing_items: list[str] = []
    rationales: list[str] = []
    for row in blocking_rows[:5]:
        identity = " ".join(
            part for part in (clean_text(row.get("ticker")), clean_text(row.get("name"))) if part
        )
        if identity:
            identities.append(identity)
        missing = row.get("missing")
        missing_items.extend(
            clean_text(item)
            for item in (missing if isinstance(missing, list) else [])
            if clean_text(item)
        )
        rationale = clean_text(row.get("rationale") or row.get("reason") or row.get("note"))
        if rationale:
            rationales.append(rationale)
    detail_parts = []
    if identities:
        detail_parts.append(", ".join(identities))
    if rationales:
        detail_parts.append("; ".join(rationales[:3]))
    return {
        "id": "stock_logic_check",
        "label": "Stock logic check",
        "status": status,
        "missing": missing_items or ["single-name logic check must pass before entry promotion"],
        "rationale": " | ".join(detail_parts) or "Stock logic check is not pass.",
    }


def _stock_logic_check_blocks(stock_logic_check: dict[str, Any]) -> bool:
    if not stock_logic_check:
        return False
    status = clean_text(stock_logic_check.get("status")).lower()
    if status in LOGIC_CHECK_BLOCKING_STATUSES:
        return True
    summary = safe_dict(stock_logic_check.get("summary"))
    try:
        if int(float(summary.get("blocked_count") or 0)) > 0:
            return True
    except (TypeError, ValueError):
        pass
    rows = stock_logic_check.get("rows")
    try:
        if int(float(summary.get("partial_count") or 0)) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return any(
        isinstance(row, dict) and clean_text(row.get("status")).lower() in LOGIC_CHECK_BLOCKING_STATUSES
        for row in (rows if isinstance(rows, list) else [])
    )


def _thesis_fact_check_blocks(thesis_fact_check: dict[str, Any]) -> bool:
    if not thesis_fact_check:
        return False
    status = clean_text(thesis_fact_check.get("status")).lower()
    if status in {"blocked", "fail", "failed"}:
        return True
    summary = safe_dict(thesis_fact_check.get("summary"))
    try:
        if int(float(summary.get("blocked_count") or 0)) > 0:
            return True
    except (TypeError, ValueError):
        pass
    checks = thesis_fact_check.get("checks")
    return any(
        isinstance(check, dict)
        and (
            clean_text(check.get("logic_existence")).lower() in {"weak", "contradicted", "not_found"}
            or clean_text(check.get("chain_position")).lower() in {"concept_only", "false_positive"}
            or clean_text(check.get("trading_conclusion")).lower() in {"block_entry", "remove"}
        )
        for check in (checks if isinstance(checks, list) else [])
    )


def _thesis_fact_blocking_requirement(thesis_fact_check: dict[str, Any]) -> dict[str, Any]:
    checks = [
        check
        for check in (thesis_fact_check.get("checks") if isinstance(thesis_fact_check.get("checks"), list) else [])
        if isinstance(check, dict)
    ]
    blocking_checks = [
        check
        for check in checks
        if (
            clean_text(check.get("logic_existence")).lower() in {"weak", "contradicted", "not_found"}
            or clean_text(check.get("chain_position")).lower() in {"concept_only", "false_positive"}
            or clean_text(check.get("trading_conclusion")).lower() in {"block_entry", "remove"}
        )
    ]
    if not blocking_checks:
        blocking_checks = checks[:3]
    identities: list[str] = []
    missing_items: list[str] = []
    details: list[str] = []
    for check in blocking_checks[:5]:
        identity = " ".join(
            part for part in (clean_text(check.get("ticker")), clean_text(check.get("name"))) if part
        )
        if identity:
            identities.append(identity)
        missing = check.get("missing_evidence")
        missing_items.extend(
            clean_text(item)
            for item in (missing if isinstance(missing, list) else [])
            if clean_text(item)
        )
        detail = " / ".join(
            part
            for part in (
                clean_text(check.get("logic_existence")),
                clean_text(check.get("chain_position")),
                clean_text(check.get("trading_conclusion")),
            )
            if part
        )
        if detail:
            details.append(detail)
    rationale_parts = []
    if identities:
        rationale_parts.append(", ".join(identities))
    if details:
        rationale_parts.append("; ".join(details[:3]))
    return {
        "id": "thesis_fact_alignment",
        "label": "Thesis fact alignment",
        "status": clean_text(thesis_fact_check.get("status")) or "blocked",
        "missing": missing_items or ["hard thesis evidence must support entry promotion"],
        "rationale": " | ".join(rationale_parts) or "Thesis fact check blocks entry promotion.",
    }


def build_institutional_actionability_gate(
    audit: dict[str, Any],
    *,
    stock_logic_check: dict[str, Any] | None = None,
    thesis_fact_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit = safe_dict(audit)
    if not audit:
        return {}
    layer_source = audit.get("layers")
    layers = [row for row in (layer_source if isinstance(layer_source, list) else []) if isinstance(row, dict)]
    layers_by_id = {clean_text(layer.get("id")): layer for layer in layers if clean_text(layer.get("id"))}
    missing_source = audit.get("missing_required")
    blocking_required_layers = [
        clean_text(item)
        for item in (missing_source if isinstance(missing_source, list) else [])
        if clean_text(item)
    ]
    blocking_requirements: list[dict[str, Any]] = []
    for layer_id in blocking_required_layers:
        layer = safe_dict(layers_by_id.get(layer_id))
        missing = layer.get("missing")
        blocking_requirements.append(
            {
                "id": layer_id,
                "label": clean_text(layer.get("label")) or layer_id,
                "status": clean_text(layer.get("status")) or "missing",
                "missing": [
                    clean_text(item)
                    for item in (missing if isinstance(missing, list) else [])
                    if clean_text(item)
                ],
                "rationale": clean_text(layer.get("rationale")),
            }
        )
    logic_check = safe_dict(stock_logic_check) or safe_dict(audit.get("stock_logic_check"))
    if _stock_logic_check_blocks(logic_check):
        if "stock_logic_check" not in blocking_required_layers:
            blocking_required_layers.append("stock_logic_check")
        blocking_requirements.append(_logic_check_blocking_requirement(logic_check))
    thesis_check = safe_dict(thesis_fact_check) or safe_dict(audit.get("thesis_fact_check"))
    if _thesis_fact_check_blocks(thesis_check):
        if "thesis_fact_alignment" not in blocking_required_layers:
            blocking_required_layers.append("thesis_fact_alignment")
        blocking_requirements.append(_thesis_fact_blocking_requirement(thesis_check))
    priority_source = audit.get("upgrade_priorities")
    upgrade_priorities = [
        {
            "id": clean_text(priority.get("id")),
            "label": clean_text(priority.get("label")) or clean_text(priority.get("id")),
            "missing": [
                clean_text(item)
                for item in (priority.get("missing") if isinstance(priority.get("missing"), list) else [])
                if clean_text(item)
            ],
            "rationale": clean_text(priority.get("rationale")),
        }
        for priority in (priority_source if isinstance(priority_source, list) else [])
        if isinstance(priority, dict) and clean_text(priority.get("id"))
    ]
    audit_status = clean_text(audit.get("status")) or "unknown"
    status = "open" if audit_status == "institutional_ready" and not blocking_required_layers else "blocked"
    return {
        "schema_version": "institutional_actionability_gate/v1",
        "status": status,
        "decision": "entry_list_allowed" if status == "open" else "research_only_until_required_layers_pass",
        "audit_status": audit_status,
        "score": audit.get("score"),
        "max_score": audit.get("max_score"),
        "coverage_ratio": audit.get("coverage_ratio"),
        "blocking_required_layers": blocking_required_layers,
        "blocking_requirements": blocking_requirements,
        "upgrade_priorities": upgrade_priorities,
    }


def render_institutional_actionability_gate(package: dict[str, Any]) -> str:
    gate = safe_dict(package.get("institutional_actionability_gate"))
    if not gate:
        return ""
    promotion = safe_dict(package.get("entry_list_promotion"))
    promotion_status = clean_text(promotion.get("status"))
    status = clean_text(gate.get("status")) or "blocked"
    status_class = "covered" if status == "open" else "blocked"
    decision = clean_text(gate.get("decision")) or "research_only_until_required_layers_pass"
    display_decision = clean_text(promotion.get("decision")) or decision
    audit_status = clean_text(gate.get("audit_status")) or "unknown"
    coverage = clean_text(gate.get("coverage_ratio")) or "0"
    blocking_layers = [
        clean_text(item)
        for item in (gate.get("blocking_required_layers") if isinstance(gate.get("blocking_required_layers"), list) else [])
        if clean_text(item)
    ]
    blocking_count = clean_text(len(blocking_layers))
    blocking_requirements = [
        row
        for row in (gate.get("blocking_requirements") if isinstance(gate.get("blocking_requirements"), list) else [])
        if isinstance(row, dict)
    ]
    upgrade_priorities = [
        row
        for row in (gate.get("upgrade_priorities") if isinstance(gate.get("upgrade_priorities"), list) else [])
        if isinstance(row, dict)
    ]
    rows_source = blocking_requirements or upgrade_priorities[:5]
    rows = []
    for item in rows_source[:5]:
        item_id = clean_text(item.get("id"))
        label = clean_text(item.get("label")) or item_id
        item_status = clean_text(item.get("status")) or "missing"
        missing = item.get("missing")
        missing_text = ", ".join(
            clean_text(value)
            for value in (missing if isinstance(missing, list) else [])
            if clean_text(value)
        )
        rationale = clean_text(item.get("rationale"))
        detail = " | ".join(part for part in (missing_text, rationale) if part) or "needs review"
        rows.append(
            '<div class="source-status-item gate-priority-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(item_id)}</span>'
            f'<span class="overview-name">{html.escape(label)}</span>'
            "</div>"
            f'<span class="bucket-pill">{html.escape(item_status)}</span>'
            f'<span class="status-pill status-pending">required</span>'
            f'<span class="metric-label">{html.escape(detail)}</span>'
            "</div>"
        )
    if promotion_status == "empty":
        summary = (
            "No entry-list candidates passed into the promotion lane; keep this package as research or priority-watch "
            "until a top-pick candidate appears."
        )
    elif status == "open" and clean_text(promotion.get("promotion_tier")) == "fallback_watchlist":
        summary = (
            "Required audit layers have passed. No top-pick candidates exist, but priority-watchlist stocks "
            "have been promoted as fallback entry candidates."
        )
    elif status == "open":
        summary = "Required audit layers have passed; this package can be considered for entry-list promotion."
    else:
        summary = (
            "Entry-list promotion blocked. Required audit layers are still missing; keep this package research-only "
            "until the blockers are closed."
        )
    return (
        '<section class="institutional-actionability-gate" aria-label="Institutional actionability gate">'
        '<div class="section-head">'
        "<h2>Execution Gate</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(status)}</span>'
        "</div>"
        '<div class="institutional-gate-body source-status-body">'
        f"<p>{html.escape(summary)}</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(audit_status)}</span><span class="metric-label">Audit status</span></div>'
        f'<div><span class="metric-value">{html.escape(coverage)}</span><span class="metric-label">Coverage</span></div>'
        f'<div><span class="metric-value">{html.escape(blocking_count)}</span><span class="metric-label">Required blockers</span></div>'
        f'<div><span class="metric-value">{html.escape(display_decision)}</span><span class="metric-label">Decision</span></div>'
        "</div>"
        '<div class="source-status-list gate-priority-list">'
        + "".join(rows)
        + "</div>"
        "</div>"
        "</section>"
    )


def render_institutional_evidence_followups_status(package: dict[str, Any]) -> str:
    followups = [
        row
        for row in (package.get("institutional_evidence_followups") if isinstance(package.get("institutional_evidence_followups"), list) else [])
        if isinstance(row, dict)
    ]
    if not followups:
        return ""
    rows = []
    for followup in followups[:5]:
        label = clean_text(followup.get("label")) or clean_text(followup.get("id")) or "followup"
        status = clean_text(followup.get("status")) or "request_ready"
        status_class = "covered" if status == "result_ready" else "pending"
        detail = clean_text(followup.get("result_note")) or clean_text(followup.get("auto_discovery_note")) or "request ready"
        fulltext_parts = [part for part in _followup_fulltext_metric_parts(followup) if part not in detail]
        if fulltext_parts:
            detail = f"{detail}; {'; '.join(fulltext_parts)}"
        rows.append(
            '<div class="source-status-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(clean_text(followup.get("id")) or "followup")}</span>'
            f'<span class="overview-name">{html.escape(label)}</span>'
            "</div>"
            f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(status)}</span>'
            f'<span class="metric-label">{html.escape(detail)}</span>'
            "</div>"
        )
    artifact_link_rows: list[str] = []
    for followup in followups:
        result_path = followup.get("result_path") or followup.get("expected_result_path")
        report_path = followup.get("report_path") or followup.get("expected_report_path")
        request_link = render_file_link(
            followup.get("request_path"),
            artifact_label_for_path(followup.get("request_path"), "followup-request.json"),
        )
        result_link = render_file_link(
            result_path,
            artifact_label_for_path(result_path, "followup-result.json"),
        )
        report_link = render_file_link(
            report_path,
            artifact_label_for_path(report_path, "followup-report.md"),
        )
        artifact_link_rows.extend([link for link in (request_link, result_link, report_link) if link])
    artifact_links = "".join(artifact_link_rows)
    artifact_link_block = f'<div class="artifact-links">{artifact_links}</div>' if artifact_links else ""
    command_lines = "".join(
        f'<p class="data-note"><code>{html.escape(clean_text(followup.get("run_command")) or "")}</code></p>'
        for followup in followups[:3]
        if clean_text(followup.get("run_command"))
    )
    return (
        '<section id="institutional-evidence-followups" class="institutional-evidence-followups" aria-label="Institutional evidence followups">'
        '<div class="section-head">'
        "<h2>Institutional Evidence Followups</h2>"
        f'<span class="status-pill status-pending">{html.escape(str(len(followups)))} followups</span>'
        "</div>"
        '<div class="source-status-body">'
        "<p>Missing institutional evidence is converted into native followup request packages so the same run root can ingest real evidence later.</p>"
        '<div class="source-status-list">'
        + "".join(rows)
        + "</div>"
        f"{artifact_link_block}"
        f"{command_lines}"
        "</div>"
        "</section>"
    )
