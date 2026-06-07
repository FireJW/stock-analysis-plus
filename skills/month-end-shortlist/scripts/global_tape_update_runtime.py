#!/usr/bin/env python3
"""Render a post-holiday global tape update plan from local artifacts.

The first slice is intentionally render-only: callers provide the external tape
payload as JSON, while the local shortlist result supplies stock names and
baseline metadata.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


INLINE_A_SHARE_TICKER_RE = re.compile(r"`(?P<ticker>\d{6}(?:\.(?:SZ|SS|SH))?)`\s*")


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().resolve().read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    path.expanduser().resolve().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _looks_like_a_share_ticker(value: str) -> bool:
    return bool(re.fullmatch(r"\d{6}(?:\.(?:SZ|SS|SH))?", clean_text(value).upper()))


def _add_ticker_name_aliases(lookup: dict[str, str], ticker: str, name: str) -> None:
    normalized_ticker = clean_text(ticker).upper()
    normalized_name = clean_text(name)
    if not normalized_ticker or not normalized_name:
        return
    if normalized_name == normalized_ticker or not _looks_like_a_share_ticker(normalized_ticker):
        return
    lookup.setdefault(normalized_ticker, normalized_name)
    lookup.setdefault(normalized_ticker[:6], normalized_name)


def build_ticker_name_lookup(value: Any) -> dict[str, str]:
    lookup: dict[str, str] = {}

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            name = (
                clean_text(item.get("name"))
                or clean_text(item.get("resolved_name"))
                or clean_text(item.get("stock_name"))
                or clean_text(item.get("symbol_name"))
            )
            ticker = clean_text(item.get("ticker")) or clean_text(item.get("symbol"))
            if not ticker and _looks_like_a_share_ticker(clean_text(item.get("code"))):
                ticker = clean_text(item.get("code"))
            _add_ticker_name_aliases(lookup, ticker, name)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return lookup


def display_ticker(ticker: str, lookup: dict[str, str]) -> str:
    normalized_ticker = clean_text(ticker).upper()
    if not normalized_ticker:
        return "`unknown`"
    name = lookup.get(normalized_ticker) or lookup.get(normalized_ticker[:6])
    return f"`{normalized_ticker}` {name}" if name else f"`{normalized_ticker}`"


def annotate_ticker_names_in_markdown(markdown: str, lookup: dict[str, str]) -> str:
    if not markdown or not lookup:
        return markdown

    annotated_lines: list[str] = []
    for line in markdown.splitlines():
        def replace(match: re.Match[str]) -> str:
            ticker = clean_text(match.group("ticker")).upper()
            name = lookup.get(ticker) or lookup.get(ticker[:6])
            if not name or name in line:
                return match.group(0)
            return f"`{match.group('ticker')}` {name}"

        annotated_lines.append(INLINE_A_SHARE_TICKER_RE.sub(replace, line))
    return "\n".join(annotated_lines)


def _list_items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _render_bullets(lines: list[str], items: Any) -> None:
    for item in _list_items(items):
        text = clean_text(item)
        if text:
            lines.append(f"- {text}")


def _render_named_bullet_sections(lines: list[str], sections: Any, *, empty_text: str) -> None:
    rendered = False
    for section in _list_items(sections):
        if not isinstance(section, dict):
            continue
        title = clean_text(section.get("title"))
        bullets = [clean_text(item) for item in _list_items(section.get("bullets")) if clean_text(item)]
        if not title and not bullets:
            continue
        rendered = True
        if title:
            lines.extend(["", f"### {title}", ""])
        for bullet in bullets:
            lines.append(f"- {bullet}")
    if not rendered:
        lines.append(f"- {empty_text}")


def _core_levels(tape_update: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _list_items(tape_update.get("core_levels")) if isinstance(item, dict)]


def _core_roles(tape_update: dict[str, Any]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for item in _core_levels(tape_update):
        ticker = clean_text(item.get("ticker")).upper()
        role = clean_text(item.get("role"))
        if ticker and role:
            roles[ticker] = role
            roles.setdefault(ticker[:6], role)
    return roles


def render_global_tape_update(shortlist_result: dict[str, Any], tape_update: dict[str, Any]) -> str:
    target_trade_date = clean_text(tape_update.get("target_trade_date")) or "unknown"
    analysis_date = clean_text(tape_update.get("analysis_date")) or "unknown"
    lookup = build_ticker_name_lookup(shortlist_result)
    for item in _core_levels(tape_update):
        _add_ticker_name_aliases(lookup, clean_text(item.get("ticker")), clean_text(item.get("name")))

    filter_summary = shortlist_result.get("filter_summary") if isinstance(shortlist_result.get("filter_summary"), dict) else {}
    run_completeness = shortlist_result.get("run_completeness") if isinstance(shortlist_result.get("run_completeness"), dict) else {}
    baseline_date = clean_text(filter_summary.get("cache_baseline_trade_date"))
    live_status = clean_text(filter_summary.get("live_supplement_status"))
    completion_status = clean_text(run_completeness.get("status"))

    lines: list[str] = [f"# {target_trade_date} 节后交易计划：全球 tape 更新版", "", "## 数据边界", ""]
    lines.append(f"- 目标交易日：{target_trade_date}，A 股尚未开盘，本稿不把目标日盘中行情当成已发生事实。")
    lines.append(f"- 分析日期：{analysis_date}")
    if baseline_date:
        lines.append(f"- 本地价格底稿：`result.month-end-shortlist`，价格基线为 {baseline_date} 盘后缓存。")
    if live_status:
        lines.append(f"- 实时补充状态：`{live_status}`")
    if completion_status:
        lines.append(f"- 本地运行完整性：`{completion_status}`")
    _render_bullets(lines, tape_update.get("local_artifacts"))
    _render_bullets(lines, tape_update.get("external_boundary"))

    roles = _core_roles(tape_update)
    core_tickers = [clean_text(item.get("ticker")).upper() for item in _core_levels(tape_update) if clean_text(item.get("ticker"))]
    if core_tickers:
        lines.extend(["", "## 代码名称映射", ""])
        lines.append("下文股票显示统一采用“代码 + 股票名称”。")
        lines.extend(["", "| 代码 | 股票名称 | 执行角色 |", "|---|---|---|"])
        for ticker in core_tickers:
            name = lookup.get(ticker) or lookup.get(ticker[:6]) or ""
            lines.append(f"| `{ticker}` | {name or ticker} | {roles.get(ticker) or ''} |")

    lines.extend(["", "## 外盘信号", ""])
    _render_named_bullet_sections(lines, tape_update.get("markets"), empty_text="外盘信号未提供，保持原执行版观察优先级。")

    lines.extend(["", "## 事件信号", ""])
    _render_named_bullet_sections(lines, tape_update.get("events"), empty_text="事件催化未提供，不能提高事件副线权重。")

    lines.extend(["", "## 方向权重", ""])
    directions = [item for item in _list_items(tape_update.get("directions")) if isinstance(item, dict)]
    if directions:
        lines.append("| 方向 | 更新前 | 最新权重 | 调整 | 原因 |")
        lines.append("|---|---|---|---|---|")
        for item in directions:
            lines.append(
                "| {name} | {previous} | {current} | {adjustment} | {reason} |".format(
                    name=clean_text(item.get("name")),
                    previous=clean_text(item.get("previous")),
                    current=clean_text(item.get("current")),
                    adjustment=clean_text(item.get("adjustment")),
                    reason=clean_text(item.get("reason")),
                )
            )
    else:
        lines.append("- 方向权重未提供，维持原执行版。")

    lines.extend(["", "## 核心价位不变", ""])
    if core_tickers:
        lines.append("| 标的 | 角色 | 确认 / 边界 | 目标 / 压力 | 放弃线 | 本轮处理 |")
        lines.append("|---|---|---:|---:|---:|---|")
        for item in _core_levels(tape_update):
            ticker = clean_text(item.get("ticker")).upper()
            lines.append(
                "| {display} | {role} | {confirm} | {target} | {abandon} | {handling} |".format(
                    display=display_ticker(ticker, lookup),
                    role=clean_text(item.get("role")),
                    confirm=clean_text(item.get("confirm")),
                    target=clean_text(item.get("target")),
                    abandon=clean_text(item.get("abandon")),
                    handling=clean_text(item.get("handling")),
                )
            )
    else:
        lines.append("- 核心价位未提供，不能生成执行表。")

    lines.extend(["", "## 分时触发", ""])
    triggers = [clean_text(item) for item in _list_items(tape_update.get("intraday_triggers")) if clean_text(item)]
    if triggers:
        for idx, trigger in enumerate(triggers, 1):
            lines.append(f"{idx}. {trigger}")
    else:
        lines.append("1. 09:45-10:30 没有核心票站稳确认位前，不执行。")

    lines.extend(["", "## 仓位", ""])
    _render_bullets(lines, tape_update.get("position_rules"))
    if not _list_items(tape_update.get("position_rules")):
        lines.append("- 无确认：0%，保持空仓观察。")

    lines.extend(["", "## 确认 / 放弃规则", ""])
    if core_tickers:
        lines.append("维持原执行版规则，并增加全球 tape 过滤：")
        for item in _core_levels(tape_update):
            ticker = clean_text(item.get("ticker")).upper()
            confirm = clean_text(item.get("confirm"))
            abandon = clean_text(item.get("abandon"))
            handling = clean_text(item.get("handling"))
            lines.append(f"- {display_ticker(ticker, lookup)}：确认 {confirm}；放弃线 {abandon}；{handling}。")
    else:
        lines.append("- 未提供核心价位，无法生成逐票确认/放弃规则。")

    lines.extend(["", "## 哪些情况继续空仓观察", ""])
    _render_bullets(lines, tape_update.get("empty_watch_rules"))
    if not _list_items(tape_update.get("empty_watch_rules")):
        lines.append("- 09:45-10:30 没有任何核心票站稳确认位。")

    lines.extend(["", "## 剩余风险", ""])
    _render_bullets(lines, tape_update.get("remaining_risks"))
    if not _list_items(tape_update.get("remaining_risks")):
        lines.append("- 外部 tape 和 A 股开盘确认仍可能发生偏离。")

    lines.extend(["", "## 盘中需要确认的数据", ""])
    confirmation_points = [
        clean_text(item)
        for item in _list_items(tape_update.get("confirmation_points") or tape_update.get("intraday_confirmation_points"))
        if clean_text(item)
    ] or triggers
    if confirmation_points:
        for idx, item in enumerate(confirmation_points, 1):
            lines.append(f"{idx}. {item}")
    else:
        lines.append("1. 核心票确认位、成交放大和板块联动是否同时成立。")

    sources = [item for item in _list_items(tape_update.get("sources")) if isinstance(item, dict)]
    if sources:
        lines.extend(["", "## 来源", ""])
        for item in sources:
            label = clean_text(item.get("label")) or clean_text(item.get("name")) or "source"
            url = clean_text(item.get("url"))
            lines.append(f"- {label}: `{url}`" if url else f"- {label}")

    return annotate_ticker_names_in_markdown("\n".join(lines).strip() + "\n", lookup)


def run_global_tape_update(
    shortlist_result: dict[str, Any],
    tape_update: dict[str, Any],
    *,
    markdown_output: Path | None = None,
) -> dict[str, Any]:
    markdown = render_global_tape_update(shortlist_result, tape_update)
    markdown_path = ""
    if markdown_output is not None:
        markdown_output.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        markdown_output.expanduser().resolve().write_text(markdown, encoding="utf-8")
        markdown_path = str(markdown_output)
    return {"markdown": markdown, "markdown_path": markdown_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a global tape update markdown plan.")
    parser.add_argument("--shortlist-result", required=True, help="Path to month-end-shortlist result JSON.")
    parser.add_argument("--tape-json", required=True, help="Path to external tape update JSON.")
    parser.add_argument("--markdown-output", help="Write rendered markdown to this path.")
    parser.add_argument("--json-output", help="Write renderer result JSON to this path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_global_tape_update(
        load_json(Path(args.shortlist_result)),
        load_json(Path(args.tape_json)),
        markdown_output=Path(args.markdown_output) if args.markdown_output else None,
    )
    if args.json_output:
        write_json(Path(args.json_output), result)
    if not args.markdown_output and not args.json_output:
        sys.stdout.write(result["markdown"])
    return 0


__all__ = [
    "annotate_ticker_names_in_markdown",
    "build_ticker_name_lookup",
    "display_ticker",
    "load_json",
    "main",
    "parse_args",
    "render_global_tape_update",
    "run_global_tape_update",
    "write_json",
]


if __name__ == "__main__":
    raise SystemExit(main())
