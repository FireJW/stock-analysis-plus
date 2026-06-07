#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import (
    display_status_text,
    parse_float,
    render_html_table,
    safe_dict,
    safe_list,
)


__all__ = [
    "macro_health_band",
    "macro_health_dimension_score",
    "render_macro_health_overlay_status",
    "render_macro_health_scorecard",
    "render_macro_svg_chart",
    "render_macro_trend_charts",
]


def macro_health_band(score: int) -> str:
    if score >= 80:
        return "constructive"
    if score >= 65:
        return "mixed / neutral"
    if score >= 50:
        return "selective"
    if score >= 35:
        return "weak"
    return "adverse"


def macro_health_dimension_score(value: Any, *, kind: str) -> tuple[int, str, str]:
    text = clean_text(value)
    lower = text.lower()
    if kind == "regime":
        if "favorable" in lower:
            return 84, "favorable", text or "favorable"
        if "adverse" in lower:
            return 34, "adverse", text or "adverse"
        if "mixed" in lower or "neutral" in lower:
            return 66, "mixed / neutral", text or "mixed / neutral"
        return 55, text.replace("_", " ") or "neutral", text or "neutral"
    if kind == "posture":
        if "constructive" in lower or "aggressive" in lower:
            return 78, "constructive", text or "constructive"
        if "neutral_selective" in lower or "selective" in lower:
            return 66, "neutral selective", text or "neutral selective"
        if "defensive" in lower or "protective" in lower:
            return 46, "defensive", text or "defensive"
        if "restricted" in lower:
            return 34, "restricted", text or "restricted"
        return 55, text.replace("_", " ") or "neutral", text or "neutral"
    if kind == "window":
        if "support" in lower or "stable" in lower or "constructive" in lower:
            return 72, "supportive", text or "supportive"
        if "mixed" in lower:
            return 60, "mixed", text or "mixed"
        if "tight" in lower or "fragile" in lower:
            return 42, "tight", text or "tight"
        return 55, text.replace("_", " ") or "mixed", text or "mixed"
    if kind == "liquidity":
        if any(term in lower for term in ("supportive", "easing", "improving", "loose")):
            return 76, "supportive", text or "supportive"
        if any(term in lower for term in ("drain", "tight", "stress", "warning")):
            return 42, "tight", text or "tight"
        return 58, text.replace("_", " ") or "mixed", text or "mixed"
    if kind == "plumbing":
        if any(term in lower for term in ("stable", "available", "below iorb", "funding still available")):
            return 74, "stable", text or "stable"
        if any(term in lower for term in ("stress", "tight", "acute")):
            return 44, "stressed", text or "stressed"
        return 58, text.replace("_", " ") or "mixed", text or "mixed"
    if kind == "freshness":
        if lower in {"ok", "covered"}:
            return 82, "ok", text or "ok"
        if lower in {"partial", "degraded"}:
            return 56, lower, text or lower
        return 60, text or "ok", text or "ok"
    return 55, text or "mixed", text or "mixed"


def render_macro_health_scorecard(
    overlay: dict[str, Any],
    live_fetch_summary: dict[str, Any],
) -> str:
    if not overlay:
        return ""
    liquidity_monitor = safe_dict(overlay.get("liquidity_monitor"))
    health_label = clean_text(overlay.get("health_label"))
    risk_posture = clean_text(overlay.get("risk_posture"))
    window_state = clean_text(overlay.get("window_state"))
    liquidity_signal = clean_text(overlay.get("liquidity_signal"))
    liquidity_plumbing_signal = clean_text(overlay.get("liquidity_plumbing_signal"))
    takeaway = clean_text(overlay.get("takeaway"))
    freshness_status = clean_text(live_fetch_summary.get("status")) or clean_text(overlay.get("source_health")) or "ok"
    fetched = safe_list(live_fetch_summary.get("fetched"))
    warnings = [clean_text(item) for item in safe_list(live_fetch_summary.get("warnings")) if clean_text(item)]
    dimensions: list[dict[str, Any]] = []
    for label, kind, value, evidence, weight in (
        ("Regime", "regime", health_label, health_label or "mixed_or_neutral_window", 2),
        ("Posture", "posture", risk_posture, risk_posture or "neutral_selective", 2),
        ("Window", "window", window_state, window_state or "mixed_window", 1),
        ("Liquidity", "liquidity", liquidity_signal, liquidity_signal or "n/a", 2),
        ("Plumbing", "plumbing", liquidity_plumbing_signal, liquidity_plumbing_signal or "n/a", 2),
        (
            "Freshness",
            "freshness",
            freshness_status,
            f"provider={clean_text(live_fetch_summary.get('provider')) or 'n/a'}; fetched={len(fetched)}; warnings={len(warnings)}",
            1,
        ),
    ):
        score, read, read_evidence = macro_health_dimension_score(value, kind=kind)
        display_evidence = read_evidence if label == "Freshness" else evidence
        if label in {"Regime", "Posture", "Window", "Freshness"}:
            display_evidence = display_status_text(display_evidence, clean_text(display_evidence))
        dimensions.append(
            {
                "label": label,
                "score": score,
                "read": read,
                "evidence": display_evidence,
                "weight": weight,
            }
        )
    overall_weight = sum(int(row["weight"]) for row in dimensions) or 1
    overall_score = round(sum(int(row["score"]) * int(row["weight"]) for row in dimensions) / overall_weight)
    overall_label = macro_health_band(overall_score)
    summary_text = (
        f"Today's macro health is {overall_label} at {overall_score}/100. "
        f"{takeaway or 'Keep the tape selective until the regime is cleaner.'}"
    )
    if not takeaway:
        liquidity_note = clean_text(liquidity_monitor.get("liquidity_signal")) or "Liquidity is mixed."
        plumbing_note = clean_text(liquidity_monitor.get("liquidity_plumbing_signal")) or "Plumbing is mixed."
        summary_text = f"Today's macro health is {overall_label} at {overall_score}/100. {liquidity_note} {plumbing_note}"
    summary_cells = [
        f'<div class="macro-score-card">'
        f'<span class="macro-score-value">{html.escape(str(overall_score))}</span>'
        '<span class="macro-score-label">Macro score</span>'
        f'<span class="macro-score-tier">{html.escape(overall_label)}</span>'
        "</div>",
        '<div class="macro-summary-copy">'
        f"<p>{html.escape(summary_text)}</p>"
        '<div class="macro-summary-meta">'
        f'<span class="macro-summary-chip">Risk {html.escape(display_status_text(risk_posture, "neutral selective"))}</span>'
        f'<span class="macro-summary-chip">Window {html.escape(display_status_text(window_state, "mixed window"))}</span>'
        f'<span class="macro-summary-chip">Source {html.escape(display_status_text(freshness_status, "ok"))}</span>'
        "</div>"
        "</div>",
    ]
    table_rows = [
        ["Overall", f"{overall_score}/100", overall_label, summary_text],
    ] + [
        [row["label"], f'{row["score"]}/100', row["read"], row["evidence"]]
        for row in dimensions
    ]
    return (
        '<div class="macro-summary-shell">'
        '<div class="macro-summary-head">'
        + "".join(summary_cells)
        + "</div>"
        + render_html_table(
            "macro-health-scorecard",
            ["Dimension", "Score", "Read", "Evidence"],
            table_rows,
        )
        + "</div>"
    )


def render_macro_svg_chart(series: dict[str, Any]) -> str:
    points = [
        safe_dict(point)
        for point in safe_list(series.get("points"))
        if parse_float(safe_dict(point).get("value")) is not None and clean_text(safe_dict(point).get("date"))
    ]
    if len(points) < 2:
        return ""
    values = [float(parse_float(point.get("value")) or 0.0) for point in points]
    dates = [clean_text(point.get("date")) for point in points]
    width = 640
    height = 180
    padding_left = 40
    padding_right = 14
    padding_top = 18
    padding_bottom = 28
    plot_width = width - padding_left - padding_right
    plot_height = height - padding_top - padding_bottom
    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        min_value -= 1.0
        max_value += 1.0
    span = max_value - min_value
    coordinate_pairs = []
    last_index = max(1, len(values) - 1)
    for index, value in enumerate(values):
        x = padding_left + (plot_width * index / last_index)
        y = padding_top + plot_height - ((value - min_value) / span * plot_height)
        coordinate_pairs.append(f"{x:.2f},{y:.2f}")
    latest_value = values[-1]
    latest_date = dates[-1]
    first_date = dates[0]
    unit = clean_text(series.get("unit"))
    label = clean_text(series.get("label"))
    last_x, last_y = coordinate_pairs[-1].split(",", 1)
    return (
        '<svg class="macro-chart-svg" viewBox="0 0 640 180" role="img" '
        f'aria-label="{html.escape(label)} 3 month trend">'
        f'<line class="macro-chart-axis" x1="{padding_left}" y1="{height - padding_bottom}" x2="{width - padding_right}" y2="{height - padding_bottom}"></line>'
        f'<line class="macro-chart-axis" x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{height - padding_bottom}"></line>'
        f'<polyline class="macro-chart-line" points="{" ".join(coordinate_pairs)}"></polyline>'
        f'<circle class="macro-chart-last-point" cx="{last_x}" cy="{last_y}" r="3.5"></circle>'
        f'<text class="macro-chart-label" x="{padding_left}" y="14">{html.escape(str(round(max_value, 2)))} {html.escape(unit)}</text>'
        f'<text class="macro-chart-label" x="{padding_left}" y="{height - 8}">{html.escape(first_date)}</text>'
        f'<text class="macro-chart-label macro-chart-label-end" x="{width - padding_right}" y="{height - 8}">{html.escape(latest_date)}</text>'
        f'<text class="macro-chart-label macro-chart-latest" x="{width - padding_right}" y="14">{html.escape(str(round(latest_value, 2)))} {html.escape(unit)}</text>'
        "</svg>"
    )


def render_macro_trend_charts(chart_series: list[Any]) -> str:
    cards = []
    for raw_series in chart_series:
        series = safe_dict(raw_series)
        series_id = clean_text(series.get("id"))
        anchor = clean_text(series.get("anchor")) or f"macro-chart-{series_id.replace('_', '-')}"
        label = clean_text(series.get("label")) or series_id
        unit = clean_text(series.get("unit"))
        source = clean_text(series.get("source"))
        points = safe_list(series.get("points"))
        chart_svg = render_macro_svg_chart(series)
        if not chart_svg:
            continue
        first_date = clean_text(safe_dict(points[0]).get("date")) if points else ""
        latest_date = clean_text(safe_dict(points[-1]).get("date")) if points else ""
        date_range = f"{first_date} to {latest_date}" if first_date and latest_date else "3m"
        cards.append(
            '<article class="macro-trend-chart"'
            f' id="{html.escape(anchor)}">'
            '<div class="macro-chart-head">'
            f'<div><h3>{html.escape(label)}</h3><span>{html.escape(date_range)}</span></div>'
            f'<span class="macro-chart-unit">{html.escape(unit)}</span>'
            "</div>"
            f"{chart_svg}"
            f'<p class="data-note">Source: {html.escape(source or "macro overlay")}; points={html.escape(str(len(points)))}</p>'
            "</article>"
        )
    if not cards:
        return ""
    return (
        '<div class="macro-info-panel macro-trend-panel">'
        '<div class="macro-panel-title">Macro Trend Charts</div>'
        '<div class="macro-chart-grid">'
        f"{''.join(cards)}"
        "</div>"
        "</div>"
    )


def render_macro_health_overlay_status(package: dict[str, Any]) -> str:
    overlay = safe_dict(package.get("macro_health_overlay"))
    live_fetch_summary = safe_dict(package.get("macro_health_overlay_live_fetch_summary"))
    seed_summary = safe_dict(package.get("macro_health_overlay_seed_summary"))
    if not overlay:
        request = safe_dict(package.get("month_end_request"))
        overlay = safe_dict(request.get("macro_health_overlay"))
        if not live_fetch_summary:
            live_fetch_summary = safe_dict(request.get("macro_health_overlay_live_fetch_summary"))
        if not seed_summary:
            seed_summary = safe_dict(request.get("macro_health_overlay_seed_summary"))
    if not overlay:
        return ""
    health_label = clean_text(overlay.get("health_label")) or "mixed_or_neutral_window"
    risk_posture = clean_text(overlay.get("risk_posture")) or "neutral_selective"
    window_state = clean_text(overlay.get("window_state")) or "mixed_window"
    status_label = health_label.replace("_", " ")
    status_class = "status-covered" if "favorable" in health_label else "status-blocked" if "adverse" in health_label else "status-pending"
    liquidity_monitor = safe_dict(overlay.get("liquidity_monitor"))
    warnings = [clean_text(item) for item in safe_list(liquidity_monitor.get("warnings")) if clean_text(item)]
    source_rows = [
        safe_dict(row)
        for row in safe_list(liquidity_monitor.get("sources"))
        if isinstance(row, dict) and clean_text(row.get("label"))
    ]
    chart_series = [safe_dict(row) for row in safe_list(liquidity_monitor.get("chart_series")) if isinstance(row, dict)]
    chart_anchor_by_id = {
        clean_text(row.get("id")): clean_text(row.get("anchor"))
        for row in chart_series
        if clean_text(row.get("id")) and clean_text(row.get("anchor"))
    }
    metric_series_ids = {
        "reserve_rrp_tga_total_bil": "reserve_rrp_tga_total",
        "reserve_rrp_tga_total_change_bil_20d": "reserve_rrp_tga_total",
        "reserve_rrp_tga_total_change_bil_1d": "reserve_rrp_tga_total",
        "reserve_balances_date": "reserve_balances",
        "reserve_balances_latest_date": "reserve_balances",
        "reserve_balances_change_bil_1d": "reserve_balances",
        "rrp_date": "rrp",
        "rrp_latest_date": "rrp",
        "rrp_change_bil_1d": "rrp",
        "tga_date": "tga",
        "tga_latest_date": "tga",
        "tga_change_bil_1d": "tga",
        "sofr_date": "sofr",
        "sofr_latest_date": "sofr",
        "sofr_latest": "sofr",
        "sofr_change_bp_1d": "sofr",
        "iorb_date": "iorb",
        "iorb_latest_date": "iorb",
        "iorb_latest": "iorb",
        "iorb_change_bp_1d": "iorb",
    }

    def chart_anchor_for_metric(key: str) -> str:
        return chart_anchor_by_id.get(metric_series_ids.get(key, ""), "")

    metrics = [
        ("Reserve+RRP+TGA", "reserve_rrp_tga_total_bil", clean_text(liquidity_monitor.get("reserve_rrp_tga_total_bil")) or "n/a"),
        ("20d change", "reserve_rrp_tga_total_change_bil_20d", clean_text(liquidity_monitor.get("reserve_rrp_tga_total_change_bil_20d")) or "n/a"),
        ("SOFR", "sofr_latest", clean_text(liquidity_monitor.get("sofr_latest")) or "n/a"),
        ("IORB", "iorb_latest", clean_text(liquidity_monitor.get("iorb_latest")) or "n/a"),
        ("SOFR-IORB bp", "sofr_iorb_spread_bp", clean_text(liquidity_monitor.get("sofr_iorb_spread_bp")) or "n/a"),
        ("SOFR/IORB", "sofr_iorb_ratio", clean_text(liquidity_monitor.get("sofr_iorb_ratio")) or "n/a"),
    ]
    metric_tiles = []
    for label, key, value in metrics:
        anchor = chart_anchor_for_metric(key)
        inner = f'<span class="metric-value">{html.escape(value)}</span><span class="metric-label">{html.escape(label)}</span>'
        if anchor:
            metric_tiles.append(f'<a class="macro-metric-link" href="#{html.escape(anchor)}">{inner}</a>')
        else:
            metric_tiles.append(f"<div>{inner}</div>")
    metric_html = "".join(metric_tiles)

    def render_macro_kv_panel(title: str, rows: list[tuple[str, str, str]]) -> str:
        cells = []
        for label, key, value in rows:
            if not clean_text(value):
                continue
            anchor = chart_anchor_for_metric(key)
            tag_name = "a" if anchor else "div"
            href_attr = f' href="#{html.escape(anchor)}"' if anchor else ""
            link_class = " macro-kv-link" if anchor else ""
            cells.append(
                f'<{tag_name} class="macro-kv-cell{link_class}"{href_attr}'
                f' data-key="{html.escape(key)}">'
                f'<span class="macro-kv-label">{html.escape(label)}</span>'
                f'<span class="macro-kv-value">{html.escape(clean_text(value))}</span>'
                f"</{tag_name}>"
            )
        if not cells:
            return ""
        return (
            '<div class="macro-info-panel">'
            f'<div class="macro-panel-title">{html.escape(title)}</div>'
            '<div class="macro-kv-grid">'
            f"{''.join(cells)}"
            "</div>"
            "</div>"
        )

    summary_block = render_macro_health_scorecard(overlay, live_fetch_summary)

    observation_rows = []
    for label, key in (
        ("Reserve balances", "reserve_balances_latest_date"),
        ("RRP", "rrp_latest_date"),
        ("TGA", "tga_latest_date"),
        ("SOFR", "sofr_latest_date"),
        ("IORB", "iorb_latest_date"),
    ):
        value = clean_text(liquidity_monitor.get(key))
        if value:
            display_key = {
                "reserve_balances_latest_date": "reserve_balances_date",
                "rrp_latest_date": "rrp_date",
                "tga_latest_date": "tga_date",
                "sofr_latest_date": "sofr_date",
                "iorb_latest_date": "iorb_date",
            }.get(key, key)
            observation_rows.append((label, display_key, value))
    observation_block = render_macro_kv_panel("Observation Freshness", observation_rows)

    daily_change_rows = []
    for label, key in (
        ("Reserve balances", "reserve_balances_change_bil_1d"),
        ("RRP", "rrp_change_bil_1d"),
        ("Reserve+RRP+TGA", "reserve_rrp_tga_total_change_bil_1d"),
        ("SOFR bp", "sofr_change_bp_1d"),
        ("IORB bp", "iorb_change_bp_1d"),
    ):
        value = clean_text(liquidity_monitor.get(key))
        if value:
            daily_change_rows.append((label, key, value))
    daily_change_block = render_macro_kv_panel("1d Moves", daily_change_rows)

    provider = clean_text(live_fetch_summary.get("provider"))
    status = clean_text(live_fetch_summary.get("status"))
    fetched = ", ".join(clean_text(item) for item in safe_list(live_fetch_summary.get("fetched")) if clean_text(item))
    live_warnings = "; ".join(clean_text(item) for item in safe_list(live_fetch_summary.get("warnings")) if clean_text(item))
    live_fetch_block = render_macro_kv_panel(
        "Live Data",
        [
            ("Provider", "provider", provider or "n/a" if provider or status else ""),
            ("Status", "status", status or "n/a" if provider or status else ""),
            ("Fetched layers", "fetched", fetched),
        ],
    )

    diagnostic_rows: list[tuple[str, str, str]] = []
    if live_warnings:
        diagnostic_rows.append(("Live warnings", "live_warnings", live_warnings))
    if warnings:
        diagnostic_rows.append(("Liquidity warnings", "liquidity_warnings", "; ".join(warnings)))
    seed_path = clean_text(seed_summary.get("path"))
    if seed_path or seed_summary.get("loaded") or seed_summary.get("used") or seed_summary.get("written"):
        diagnostic_rows.extend(
            [
                ("Seed cache path", "seed_cache_path", seed_path or "n/a"),
                ("Seed cache loaded", "seed_cache_loaded", "yes" if bool(seed_summary.get("loaded")) else "no"),
                ("Seed cache used", "seed_cache_used", "yes" if bool(seed_summary.get("used")) else "no"),
                ("Seed cache written", "seed_cache_written", "yes" if bool(seed_summary.get("written")) else "no"),
                ("Seed cache fill mode", "seed_cache_fill_mode", clean_text(seed_summary.get("fill_mode")) or "n/a"),
            ]
        )
    diagnostic_block = ""
    if source_rows:
        rendered_sources = []
        for row in source_rows:
            label = clean_text(row.get("label"))
            url = clean_text(row.get("url"))
            if url:
                rendered_sources.append(f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer">{html.escape(label)}</a>')
            else:
                rendered_sources.append(html.escape(label))
        diagnostic_rows.append(("Sources", "sources", ", ".join(rendered_sources)))
    if diagnostic_rows:
        diagnostic_items = []
        for label, key, value in diagnostic_rows:
            value_html = value if key == "sources" else html.escape(value)
            diagnostic_items.append(
                '<div class="macro-diagnostic-row"'
                f' data-key="{html.escape(key)}">'
                f'<span class="macro-kv-label">{html.escape(label)}</span>'
                f'<span class="macro-kv-value">{value_html}</span>'
                "</div>"
            )
        diagnostic_block = (
            '<details class="evidence-drawer macro-diagnostic-detail">'
            "<summary>Diagnostic Detail</summary>"
            '<div class="macro-diagnostic-grid">'
            f"{''.join(diagnostic_items)}"
            "</div>"
            "</details>"
        )
    trend_chart_block = render_macro_trend_charts(chart_series)
    return (
        '<section id="macro-health-overlay" class="macro-health-overlay-status" aria-label="Macro health overlay">'
        '<div class="section-head">'
        "<h2>Macro Health Overlay</h2>"
        f'<span class="status-pill {html.escape(status_class)}">{html.escape(status_label)}</span>'
        "</div>"
        '<div class="source-status-body">'
        f"{summary_block}"
        '<div class="coverage-metrics">'
        f"{metric_html}"
        "</div>"
        f"{observation_block}"
        f"{daily_change_block}"
        f"{live_fetch_block}"
        f"{diagnostic_block}"
        f"{trend_chart_block}"
        "</div>"
        "</section>"
    )
