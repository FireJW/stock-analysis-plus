#!/usr/bin/env python3
from __future__ import annotations

import html
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import display_status_text, safe_dict, safe_list
from manager_ui_summary import summary_count_text


def _numeric_count(value: Any) -> int:
    count_text = summary_count_text(value)
    try:
        return int(float(count_text.replace(",", "")))
    except ValueError:
        return 0


def _count_zh(count: int, noun: str) -> str:
    return f"{count} 个{noun}"


def _zh_status(value: Any, fallback: str = "") -> str:
    text = clean_text(value)
    if not text:
        return fallback
    normalized = text.lower().replace(" ", "_")
    mapping = {
        "official_confirmed": "事件已确认",
        "unconfirmed": "仍待确认",
        "medium": "中等",
        "strong": "强",
        "weak": "弱",
        "wait_for_confirmation": "等待确认",
        "market_strength_scan": "市场强度扫描",
        "company_event": "公司事件",
        "entry_list_allowed": "允许条件入场",
        "watchlist_only": "仅观察",
        "filing": "公告",
        "source_signal": "来源信号",
        "institution_rating": "机构评级",
        "ownership": "持仓",
        "theme_tracking": "主题跟踪",
    }
    return mapping.get(normalized, display_status_text(text))


def _candidate_label(candidate: dict[str, Any]) -> str:
    ticker = clean_text(candidate.get("ticker"))
    name = clean_text(candidate.get("name"))
    return " ".join(item for item in (ticker, name) if item) or "Unnamed candidate"


def _format_setup_reason(candidate: dict[str, Any]) -> str:
    event_state = _zh_status(candidate.get("event_state_label"), "事件待确认")
    validation = _zh_status(candidate.get("market_validation_label"), "价格验证待补")
    usability = _zh_status(candidate.get("trading_usability_label"), "")
    parts = [event_state, f"{validation}价格验证"]
    if usability:
        parts.append(f"{usability}交易可用性")
    return "; ".join(parts)


def _latest_row(rows: list[dict[str, Any]], title_key: str, time_key: str) -> dict[str, Any]:
    candidates = [row for row in rows if clean_text(row.get(title_key))]
    if not candidates:
        return {}
    return max(candidates, key=lambda row: clean_text(row.get(time_key)))


def _short_time(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    normalized = text.replace("T", " ")
    for suffix in ("Z", "+00:00"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized[:16] if len(normalized) >= 16 else normalized


def _time_suffix(row: dict[str, Any], key: str) -> str:
    short_time = _short_time(row.get(key))
    return f" @ {short_time}" if short_time else ""


def _fresh_signal_lines(coverage: dict[str, Any]) -> list[str]:
    rows = [row for row in safe_list(coverage.get("rows")) if isinstance(row, dict)]
    lines: list[str] = []
    latest_news = _latest_row(rows, "latest_news_title", "latest_news_time")
    if latest_news:
        lines.append(
            f"最新新闻：{_candidate_label(latest_news)} {clean_text(latest_news.get('latest_news_title'))}"
            f"{_time_suffix(latest_news, 'latest_news_time')}"
        )
    latest_topic = _latest_row(rows, "latest_topic_title", "latest_topic_time")
    if latest_topic:
        lines.append(
            f"最新讨论：{_candidate_label(latest_topic)} {clean_text(latest_topic.get('latest_topic_title'))}"
            f"{_time_suffix(latest_topic, 'latest_topic_time')}"
        )
    latest_signal = _latest_row(rows, "latest_source_signal_title", "latest_source_signal_time")
    if latest_signal:
        signal_type = _zh_status(latest_signal.get("latest_source_signal_type"), "")
        suffix = f"（{signal_type}）" if signal_type else ""
        lines.append(
            f"最新来源信号：{_candidate_label(latest_signal)} "
            f"{clean_text(latest_signal.get('latest_source_signal_title'))}{suffix}"
            f"{_time_suffix(latest_signal, 'latest_source_signal_time')}"
        )
    return lines


def _screening_counts(screening: dict[str, Any], ui_summary: dict[str, Any]) -> tuple[int, int]:
    entry_count = _numeric_count(screening.get("entry_candidate_count"))
    watch_count = _numeric_count(screening.get("watchlist_candidate_count"))
    if entry_count == 0 or watch_count == 0:
        bucket_counts = safe_dict(ui_summary.get("bucket_counts"))
        entry_count = entry_count or _numeric_count(bucket_counts.get("Directly Actionable"))
        watch_count = watch_count or _numeric_count(bucket_counts.get("Priority Watch"))
    return entry_count, watch_count


def _overall_lines(
    macro_summary: str,
    screening: dict[str, Any],
    ui_summary: dict[str, Any],
    monitor: dict[str, Any],
) -> list[str]:
    entry_count, watch_count = _screening_counts(screening, ui_summary)
    alerts = [row for row in safe_list(monitor.get("alerts")) if isinstance(row, dict)]
    if entry_count > 0:
        plan_read = (
            f"明天不是普买日。计划只筛出{_count_zh(entry_count, '条件主线候选')}，"
            f"另有{_count_zh(watch_count, '动量观察票')}；执行必须等触发确认。"
        )
    elif watch_count > 0:
        plan_read = (
            f"明天以观察为主。计划有{_count_zh(watch_count, '动量观察票')}，"
            "但还没有标的进入执行通道。"
        )
    else:
        plan_read = "明天没有明确执行通道。先保持复盘模式，等新的触发信号出现。"
    if alerts:
        plan_read += " 旧池触发报警较多，加仓前先处理风险。"
    return [plan_read, f"宏观：{macro_summary}"]


def _primary_setup_lines(screening: dict[str, Any]) -> list[str]:
    entry_candidates = [row for row in safe_list(screening.get("entry_candidates")) if isinstance(row, dict)]
    if not entry_candidates:
        return ["没有主线候选进入执行通道；先把清单当作观察上下文，等触发确认。"]
    lines: list[str] = []
    single_entry = len(entry_candidates) == 1
    for candidate in entry_candidates[:2]:
        label = _candidate_label(candidate)
        promotion_text = "唯一进入执行通道的主线候选" if single_entry else "进入执行通道的主线候选"
        lines.append(f"{label}：{promotion_text}。")
        lines.append(f"入选原因：{_format_setup_reason(candidate)}。")
        market_signal = clean_text(candidate.get("market_signal_summary"))
        if market_signal:
            lines.append(f"盘面验证：{market_signal}。")
        usage = clean_text(candidate.get("trading_profile_usage")) or clean_text(candidate.get("trading_profile_playbook"))
        if usage:
            lines.append(f"使用方式：{usage}")
        else:
            lines.append("使用方式：等关键价位收复和放量确认后，再考虑小仓执行。")
    return lines


def _watchlist_signal_text(candidate: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "latest_source_signal_title",
        "source_signal_summary",
        "institutional_signal",
        "priority_reason",
        "priority_note",
        "reason",
        "event_type",
        "market_signal_summary",
    ):
        text = clean_text(candidate.get(key))
        if text:
            values.append(text)
    for key in ("tags", "strategy_tags", "message_source_types"):
        for item in safe_list(candidate.get(key)):
            text = clean_text(item)
            if text:
                values.append(text)
    return " ".join(values)


def _explicit_watchlist_group(candidate: dict[str, Any]) -> str:
    for key in ("watchlist_priority_group", "priority_group", "priority_tier", "priority_level"):
        value = clean_text(candidate.get(key)).lower().replace("-", "_").replace(" ", "_")
        if not value:
            continue
        if value in {"high", "high_priority", "p0", "p1", "top", "高优先级", "重点"}:
            return "high"
        if value in {"secondary", "medium", "p2", "次级观察", "次级"}:
            return "secondary"
        if value in {"theme", "theme_only", "p3", "主题跟踪", "主题"}:
            return "theme"
    return ""


def _watchlist_group_key(candidate: dict[str, Any]) -> str:
    explicit_group = _explicit_watchlist_group(candidate)
    if explicit_group:
        return explicit_group
    signal_text = _watchlist_signal_text(candidate)
    normalized = signal_text.lower()
    if (
        _numeric_count(candidate.get("source_signal_count")) > 0
        or "龙虎榜" in signal_text
        or "机构买入" in signal_text
        or "institution" in normalized
        or "source_signal" in normalized
        or clean_text(candidate.get("latest_source_signal_title"))
    ):
        return "high"
    validation = clean_text(candidate.get("market_validation_label")).lower()
    action = clean_text(candidate.get("action")).lower()
    if validation in {"strong", "medium"} or "confirmation" in action or "确认" in action:
        return "secondary"
    return "theme"


def _watchlist_reason(candidate: dict[str, Any]) -> str:
    signal = (
        clean_text(candidate.get("priority_reason"))
        or clean_text(candidate.get("latest_source_signal_title"))
        or clean_text(candidate.get("source_signal_summary"))
    )
    if signal:
        return signal
    validation = _zh_status(candidate.get("market_validation_label"), "")
    if validation:
        return f"{validation}盘面验证"
    event_type = _zh_status(candidate.get("event_type"), "")
    if event_type:
        return event_type
    return "主题跟踪，等待确认"


def _render_watchlist_groups(screening: dict[str, Any]) -> str:
    watch_candidates = [row for row in safe_list(screening.get("watchlist_candidates")) if isinstance(row, dict)]
    if not watch_candidates:
        return '<ul class="summary-plan-lines"><li>没有附加观察名单。</li></ul>'
    groups = {
        "high": ("高优先级", "watchlist-group-high", []),
        "secondary": ("次级观察", "watchlist-group-secondary", []),
        "theme": ("主题跟踪", "watchlist-group-theme", []),
    }
    for candidate in watch_candidates[:5]:
        groups[_watchlist_group_key(candidate)][2].append(candidate)
    group_html: list[str] = []
    for key in ("high", "secondary", "theme"):
        label, css_class, candidates = groups[key]
        if not candidates:
            continue
        items = "".join(
            '<li>'
            f'<strong>{html.escape(_candidate_label(candidate))}</strong>'
            f'<span>{html.escape(_watchlist_reason(candidate))}</span>'
            "</li>"
            for candidate in candidates
        )
        group_html.append(
            f'<div class="watchlist-group {css_class}">'
            f'<div class="watchlist-group-label">{html.escape(label)}</div>'
            f'<ul class="watchlist-group-items">{items}</ul>'
            "</div>"
        )
    return (
        '<div class="watchlist-priority-groups">'
        + "".join(group_html)
        + '<p class="watchlist-group-note">这些是强势盘面观察票，不是自动买入清单；只做确认后的快进快出。</p>'
        + "</div>"
    )


def _risk_lines(monitor: dict[str, Any]) -> list[str]:
    alerts = [row for row in safe_list(monitor.get("alerts")) if isinstance(row, dict)]
    if not alerts:
        return ["当前没有触发报警；执行前仍要复核关键价位。"]
    stop_hit_count = sum(1 for row in alerts if clean_text(row.get("alert_type")) == "stop_hit")
    stop_near_count = sum(1 for row in alerts if clean_text(row.get("alert_type")) == "stop_approaching")
    parts = []
    if stop_hit_count:
        parts.append(f"{stop_hit_count} 个止损触发")
    if stop_near_count:
        parts.append(f"{stop_near_count} 个接近止损")
    lead = "触发监控显示" + "、".join(parts) + "。" if parts else "触发监控有活跃报警。"
    return [
        lead,
        "先剔除失败标的，再考虑新增风险；旧池承压时不要补跌或摊平。",
    ]


def _source_lines(coverage: dict[str, Any]) -> list[str]:
    coverage_summary = safe_dict(coverage.get("summary"))
    if not coverage_summary:
        return ["缺少价格和催化来源覆盖；刷新来源前不要把计划当成可执行清单。"]
    stock_count = _numeric_count(coverage_summary.get("stock_count"))
    quote_covered = _numeric_count(coverage_summary.get("quote_covered_count"))
    news_covered = _numeric_count(coverage_summary.get("news_covered_count"))
    detail_errors = _numeric_count(coverage_summary.get("news_detail_error_count"))
    detail_empty = _numeric_count(coverage_summary.get("news_detail_empty_count"))
    topic_covered = _numeric_count(coverage_summary.get("topic_covered_count"))
    source_signal_covered = _numeric_count(coverage_summary.get("source_signal_covered_count"))
    lines: list[str] = []
    if stock_count and quote_covered >= stock_count:
        lines.append("价格和标题可用，可以支撑观察和触发计划。")
    elif quote_covered:
        lines.append("价格数据只覆盖部分标的，缺口标的只能观察。")
    else:
        lines.append("价格数据缺失，计划不能直接执行。")
    if detail_errors or detail_empty:
        lines.append("新闻正文抓取失败，本轮只能给观察/触发计划，不能给高信心仓位。")
    elif stock_count and news_covered >= stock_count:
        lines.append("新闻标题已覆盖跟踪标的，但仍要区分直接催化和背景噪音。")
    elif news_covered:
        lines.append("新闻标题只覆盖部分标的，催化信心不均衡。")
    signal_parts: list[str] = []
    if topic_covered and stock_count and topic_covered < stock_count:
        signal_parts.append("话题信号不完整")
    elif topic_covered:
        signal_parts.append("话题信号已附加")
    if source_signal_covered:
        signal_parts.append("公告/来源信号已附加")
    if signal_parts:
        lines.append("；".join(signal_parts) + "，只作证据和情绪上下文，不单独构成买入触发。")
    return lines[:3]


def _render_plan_section(
    title: str,
    lines: list[str],
    *,
    detail_lines: list[str] | None = None,
    body_html: str = "",
) -> str:
    details_html = ""
    if detail_lines:
        details_html = (
            '<details class="summary-plan-details">'
            "<summary>展开最新来源线索</summary>"
            '<ul class="summary-plan-lines summary-plan-detail-lines">'
            + "".join(f"<li>{html.escape(line)}</li>" for line in detail_lines if clean_text(line))
            + "</ul>"
            + "</details>"
        )
    if body_html:
        body = body_html
    else:
        body = (
            '<ul class="summary-plan-lines">'
            + "".join(f"<li>{html.escape(line)}</li>" for line in lines if clean_text(line))
            + "</ul>"
        )
    return (
        '<div class="summary-plan-section">'
        f'<div class="summary-plan-title">{html.escape(title)}</div>'
        + body
        + details_html
        + "</div>"
    )


def _render_risk_strip(monitor: dict[str, Any]) -> str:
    alerts = [row for row in safe_list(monitor.get("alerts")) if isinstance(row, dict)]
    if not alerts:
        return ""
    stop_hit_count = sum(1 for row in alerts if clean_text(row.get("alert_type")) == "stop_hit")
    stop_near_count = sum(1 for row in alerts if clean_text(row.get("alert_type")) == "stop_approaching")
    parts = []
    if stop_hit_count:
        parts.append(f"{stop_hit_count} 个止损触发")
    if stop_near_count:
        parts.append(f"{stop_near_count} 个接近止损")
    risk_text = "、".join(parts) if parts else f"{len(alerts)} 个触发报警"
    return (
        '<div class="summary-risk-strip">'
        '<strong>先处理风险</strong>'
        f"<span>{html.escape(risk_text)}；确认旧池风险后再看新机会。</span>"
        "</div>"
    )


def render_decision_overview(ui_summary: dict[str, Any], package: dict[str, Any]) -> str:
    request = safe_dict(package.get("month_end_request"))
    overlay = safe_dict(package.get("macro_health_overlay")) or safe_dict(request.get("macro_health_overlay"))
    if overlay:
        macro_summary = (
            clean_text(overlay.get("takeaway"))
            or "; ".join(
                item
                for item in (
                    clean_text(overlay.get("health_label")),
                    clean_text(overlay.get("risk_posture")),
                    clean_text(overlay.get("window_state")),
                )
                if item
            )
        )
    else:
        macro_summary = "宏观环境未接入，仓位结论先保持条件化。"
    screening = safe_dict(package.get("entry_list_screening"))
    monitor = safe_dict(package.get("trigger_monitor"))
    coverage = safe_dict(package.get("ticker_quote_news_coverage"))
    sections = [
        ("整体判断", _overall_lines(macro_summary, screening, ui_summary, monitor), None, ""),
        ("主线候选", _primary_setup_lines(screening), None, ""),
        ("观察名单", [], None, _render_watchlist_groups(screening)),
        ("风险判断", _risk_lines(monitor), None, ""),
        ("来源判断", _source_lines(coverage), _fresh_signal_lines(coverage), ""),
    ]
    return (
        '<div class="summary-plan">'
        + _render_risk_strip(monitor)
        + "".join(
            _render_plan_section(title, lines, detail_lines=detail_lines, body_html=body_html)
            for title, lines, detail_lines, body_html in sections
        )
        + "</div>"
    )


__all__ = ["render_decision_overview"]
