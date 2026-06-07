#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from manager_calendar_counts import calendar_source_error_count
from local_stock_pool_runtime import clean_text
from manager_html_primitives import display_status_text, safe_dict, safe_list
from manager_ui_summary import summary_count_text


def _numeric_count(value: Any) -> int:
    count_text = summary_count_text(value)
    try:
        return int(float(count_text.replace(",", "")))
    except ValueError:
        return 0


def _market_value(overlay: dict[str, Any]) -> str:
    if not overlay:
        return "宏观缺失"
    health = display_status_text(overlay.get("health_label"), "").lower()
    posture = display_status_text(overlay.get("risk_posture"), "").lower()
    if "risk on" in posture or "healthy" in health:
        return "顺风窗口"
    if "mixed" in health or "neutral" in posture or "selective" in posture:
        return "精选确认"
    if health:
        return display_status_text(overlay.get("health_label"))
    return "待复核"


def _trigger_risk_value(package: dict[str, Any], high_impact: int) -> tuple[str, str]:
    monitor = safe_dict(package.get("trigger_monitor"))
    alerts = [row for row in safe_list(monitor.get("alerts")) if isinstance(row, dict)]
    stop_hit_count = sum(1 for row in alerts if clean_text(row.get("alert_type")) == "stop_hit")
    stop_near_count = sum(1 for row in alerts if clean_text(row.get("alert_type")) == "stop_approaching")
    if stop_hit_count:
        return "止损先行", "先处理旧池止损，再看新机会。"
    if stop_near_count:
        return "接近止损", "旧池接近止损，新增仓位要降档。"
    if high_impact:
        return f"{high_impact} 高影响事件", "事件窗口内只做确认后的交易。"
    return "风险待复核", "执行前仍要复核事件和关键价位。"


def _source_value_and_detail(source_errors: int, coverage_summary: dict[str, Any]) -> tuple[str, str]:
    if source_errors:
        return f"{source_errors} 来源错误", "来源异常；执行前先刷新。"
    if not coverage_summary:
        return "来源待补", "缺少价格和催化来源，先观察。"
    stock_count = _numeric_count(coverage_summary.get("stock_count"))
    quote_covered = _numeric_count(coverage_summary.get("quote_covered_count"))
    news_covered = _numeric_count(coverage_summary.get("news_covered_count"))
    detail_errors = _numeric_count(coverage_summary.get("news_detail_error_count"))
    detail_empty = _numeric_count(coverage_summary.get("news_detail_empty_count"))
    if detail_errors or detail_empty:
        return "正文失败，信心降档", "来源只支撑观察；正文失败不支持高信心仓位。"
    if stock_count and quote_covered >= stock_count and news_covered >= stock_count:
        return "来源可用", "来源支撑观察；最新线索看展开区。"
    if quote_covered or news_covered:
        return "部分覆盖", "缺口标的只观察，执行前先补来源。"
    return "来源待补", "价格/标题缺失，执行前先刷新。"


def render_decision_rail(ui_summary: dict[str, Any], package: dict[str, Any]) -> str:
    request = safe_dict(package.get("month_end_request"))
    overlay = safe_dict(package.get("macro_health_overlay")) or safe_dict(request.get("macro_health_overlay"))
    macro_value = _market_value(overlay)
    macro_detail = (
        "只在确认信号后动仓。"
        if overlay
        else "先刷新宏观层，再决定仓位。"
    )
    bucket_counts = safe_dict(ui_summary.get("bucket_counts"))
    direct_count = summary_count_text(bucket_counts.get("Directly Actionable"))
    priority_count = summary_count_text(bucket_counts.get("Priority Watch"))
    pool_value = f"{direct_count} 主线 / {priority_count} 观察"
    pool_detail = "主线等触发，观察票不自动买入。"
    event_watch = safe_dict(package.get("event_calendar_watch"))
    event_summary = safe_dict(event_watch.get("summary"))
    high_impact = summary_count_text(event_summary.get("high_importance_count"))
    high_impact_count = _numeric_count(high_impact)
    calendar_value, calendar_detail = _trigger_risk_value(package, high_impact_count)
    earnings_health = display_status_text(safe_dict(package.get("earnings_calendar_watch")).get("source_health"), "not attached")
    event_health = display_status_text(safe_dict(package.get("event_calendar_watch")).get("source_health"), "not attached")
    source_errors = calendar_source_error_count(package, "earnings_calendar_watch") + calendar_source_error_count(
        package, "event_calendar_watch"
    )
    data_value = "来源可用" if source_errors == 0 and "degraded" not in {earnings_health.lower(), event_health.lower()} else f"{source_errors} 来源错误"
    data_detail = "来源支撑观察；最新线索看展开区。" if source_errors == 0 else "来源异常；执行前先刷新。"
    coverage = safe_dict(package.get("ticker_quote_news_coverage"))
    coverage_summary = safe_dict(coverage.get("summary"))
    if coverage_summary:
        data_value, data_detail = _source_value_and_detail(source_errors, coverage_summary)
    elif source_errors:
        data_value, data_detail = _source_value_and_detail(source_errors, coverage_summary)
    cards = [
        ("Market", macro_value, macro_detail),
        ("Entry", pool_value, pool_detail),
        ("Risk", calendar_value, calendar_detail),
        ("Source", data_value, data_detail),
    ]
    return (
        '<div class="decision-rail">'
        + "".join(
            '<div class="decision-rail-card">'
            f'<span class="decision-rail-label">{html.escape(label)}</span>'
            f'<strong>{html.escape(value)}</strong>'
            f'<span class="decision-rail-detail">{html.escape(detail)}</span>'
            "</div>"
            for label, value, detail in cards
        )
        + "</div>"
    )


__all__ = ["render_decision_rail"]
