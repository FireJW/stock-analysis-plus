#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import safe_dict, safe_list, parse_float


def source_status_pill_class(status: Any) -> str:
    normalized = clean_text(status).lower()
    if normalized in {"available", "healthy", "ok", "covered"}:
        return "covered"
    return "pending"


def source_role_text(row: dict[str, Any]) -> str:
    role = row.get("role")
    if not isinstance(role, list):
        return ""
    return ", ".join(clean_text(item) for item in role if clean_text(item))


def render_source_capabilities_status(package: dict[str, Any]) -> str:
    capability_source = package.get("source_capabilities")
    capabilities = [
        row
        for row in (capability_source if isinstance(capability_source, list) else [])
        if isinstance(row, dict)
    ]
    if not capabilities:
        return ""
    summary = safe_dict(package.get("source_capability_summary"))
    capability_count = clean_text(summary.get("capability_count", len(capabilities))) or clean_text(len(capabilities))
    available_count = clean_text(
        summary.get("available_count", sum(1 for row in capabilities if clean_text(row.get("status")) == "available"))
    ) or "0"
    missing_count = clean_text(
        summary.get("missing_count", sum(1 for row in capabilities if clean_text(row.get("status")) == "missing"))
    ) or "0"
    repo_native_count = clean_text(
        summary.get("repo_native_count", sum(1 for row in capabilities if clean_text(row.get("adapter_kind")) == "repo_native"))
    ) or "0"
    optional_count = clean_text(
        summary.get("optional_package_count", sum(1 for row in capabilities if clean_text(row.get("adapter_kind")) == "optional_package"))
    ) or "0"
    status_class = "pending" if missing_count != "0" else "covered"
    rows = []
    for capability in capabilities[:10]:
        capability_id = clean_text(capability.get("id"))
        name = clean_text(capability.get("name")) or capability_id
        status = clean_text(capability.get("status")) or "unknown"
        adapter_kind = clean_text(capability.get("adapter_kind")) or "source"
        detail = source_role_text(capability) or clean_text(capability.get("package")) or clean_text(capability.get("path"))
        rows.append(
            '<div class="source-status-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(capability_id)}</span>'
            f'<span class="overview-name">{html.escape(name)}</span>'
            "</div>"
            f'<span class="bucket-pill">{html.escape(adapter_kind)}</span>'
            f'<span class="status-pill status-{html.escape(source_status_pill_class(status))}">{html.escape(status)}</span>'
            f'<span class="metric-label">{html.escape(detail)}</span>'
            "</div>"
        )
    return (
        '<section class="source-capabilities-status source-diagnostic-status" aria-label="Source capability status">'
        '<details class="source-diagnostic-details">'
        '<summary class="section-head">'
        '<span class="source-diagnostic-toggle" aria-hidden="true"></span>'
        "<h2>Source Capabilities</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(available_count)}/{html.escape(capability_count)} available</span>'
        "</summary>"
        '<div class="source-status-body">'
        "<p>Adapters and optional open-source packages attached to this package before the audit.</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(capability_count)}</span><span class="metric-label">Capabilities</span></div>'
        f'<div><span class="metric-value">{html.escape(available_count)}</span><span class="metric-label">Available</span></div>'
        f'<div><span class="metric-value">{html.escape(missing_count)}</span><span class="metric-label">Missing</span></div>'
        f'<div><span class="metric-value">{html.escape(repo_native_count)}</span><span class="metric-label">Repo native</span></div>'
        f'<div><span class="metric-value">{html.escape(optional_count)}</span><span class="metric-label">Optional packages</span></div>'
        "</div>"
        '<div class="source-status-list">'
        + "".join(rows)
        + "</div>"
        "</div>"
        "</details>"
        "</section>"
    )


def render_source_health_probes_status(package: dict[str, Any]) -> str:
    probe_source = package.get("source_health_probes")
    probes = [
        row
        for row in (probe_source if isinstance(probe_source, list) else [])
        if isinstance(row, dict)
    ]
    if not probes:
        return ""
    summary = safe_dict(package.get("source_health_probe_summary"))
    probe_count = clean_text(summary.get("probe_count", len(probes))) or clean_text(len(probes))
    healthy_count = clean_text(
        summary.get("healthy_count", sum(1 for row in probes if clean_text(row.get("probe_status")) == "healthy"))
    ) or "0"
    degraded_count = clean_text(
        summary.get("degraded_count", sum(1 for row in probes if clean_text(row.get("probe_status")) == "degraded"))
    ) or "0"
    blocked_count = clean_text(
        summary.get("blocked_count", sum(1 for row in probes if clean_text(row.get("probe_status")) == "blocked"))
    ) or "0"
    not_run_count = clean_text(
        summary.get("not_run_count", sum(1 for row in probes if clean_text(row.get("probe_status")) == "not_run"))
    ) or "0"
    error_count = clean_text(
        summary.get("error_count", sum(1 for row in probes if clean_text(row.get("probe_status")) == "error"))
    ) or "0"
    status_class = "covered" if healthy_count == probe_count and probe_count != "0" else "pending"
    rows = []
    for probe in probes[:10]:
        probe_id = clean_text(probe.get("id"))
        name = clean_text(probe.get("name")) or probe_id
        probe_status = clean_text(probe.get("probe_status")) or "unknown"
        adapter_status = clean_text(probe.get("adapter_status")) or "unknown"
        message = clean_text(probe.get("message"))
        sample_count = clean_text(probe.get("sample_count"))
        detail = message
        if sample_count:
            detail = f"{detail} samples={sample_count}" if detail else f"samples={sample_count}"
        rows.append(
            '<div class="source-status-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(probe_id)}</span>'
            f'<span class="overview-name">{html.escape(name)}</span>'
            "</div>"
            f'<span class="bucket-pill">adapter {html.escape(adapter_status)}</span>'
            f'<span class="status-pill status-{html.escape(source_status_pill_class(probe_status))}">{html.escape(probe_status)}</span>'
            f'<span class="metric-label">{html.escape(detail)}</span>'
            "</div>"
        )
    return (
        '<section class="source-health-probes-status source-diagnostic-status" aria-label="Source health probe status">'
        '<details class="source-diagnostic-details">'
        '<summary class="section-head">'
        '<span class="source-diagnostic-toggle" aria-hidden="true"></span>'
        "<h2>Source Health Probes</h2>"
        f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(healthy_count)}/{html.escape(probe_count)} healthy</span>'
        "</summary>"
        '<div class="source-status-body">'
        "<p>Endpoint health is tracked separately from adapter availability; live probes stay explicit when not requested.</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(probe_count)}</span><span class="metric-label">Probes</span></div>'
        f'<div><span class="metric-value">{html.escape(healthy_count)}</span><span class="metric-label">Healthy</span></div>'
        f'<div><span class="metric-value">{html.escape(not_run_count)}</span><span class="metric-label">Not run</span></div>'
        f'<div><span class="metric-value">{html.escape(blocked_count)}</span><span class="metric-label">Blocked</span></div>'
        f'<div><span class="metric-value">{html.escape(degraded_count)}</span><span class="metric-label">Degraded</span></div>'
        f'<div><span class="metric-value">{html.escape(error_count)}</span><span class="metric-label">Errors</span></div>'
        "</div>"
        '<div class="source-status-list">'
        + "".join(rows)
        + "</div>"
        "</div>"
        "</details>"
        "</section>"
    )
