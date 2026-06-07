#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from earnings_calendar_runtime import (
    build_combined_earnings_calendar_payload,
    write_json as write_earnings_calendar_json,
)
from event_calendar_runtime import (
    BLS_ICS_URL,
    build_event_calendar_payload,
    load_ics_rows_with_errors,
    load_fed_rows_with_errors,
    write_json as write_event_calendar_json,
)
from local_stock_pool_manager_runtime import (
    DEFAULT_EARNINGS_CALENDAR_HEADLINERS,
    implicit_institutional_evidence_roots,
    load_pool_or_template,
    load_json,
    load_market_snapshots,
    load_trading_plan_result,
    merge_market_snapshots_into_local_stock_pool,
    merge_market_snapshots_into_trading_plan_result,
    write_local_stock_pool_manager_package,
)
from longbridge_plan_sources import collect_longbridge_plan_sources


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static local stock-pool manager that exports month-end-shortlist requests."
    )
    parser.add_argument("--pool", default="", help="Path to a local_stock_pool/v1 JSON file or request JSON.")
    parser.add_argument(
        "--trading-plan-result",
        default="",
        help="Optional month-end/trading-plan JSON, Markdown, text file, or result directory to import into the pool UI.",
    )
    parser.add_argument(
        "--market-snapshots",
        default="",
        help="Optional Longbridge quote JSON file to attach as current market snapshots for imported plan rows.",
    )
    parser.add_argument("--output-dir", required=True, help="Directory for generated HTML and JSON artifacts.")
    parser.add_argument("--tdx-vipdoc-path", default="", help="Optional local Tongdaxin vipdoc root.")
    parser.add_argument("--target-date", default="", help="Target date for the generated shortlist request.")
    parser.add_argument("--analysis-time", default="", help="Optional analysis timestamp for the generated request.")
    parser.add_argument(
        "--institutional-ready",
        action="store_true",
        help="Run the standard institutional-ready chain: shortlist, postclose review, audit, gate, and local HTML/package outputs.",
    )
    parser.add_argument(
        "--run-shortlist",
        action="store_true",
        help="Run month_end_shortlist from the generated request and attach fresh discovery coverage outputs.",
    )
    parser.add_argument(
        "--shortlist-input",
        default="",
        help="Optional existing month-end-shortlist result JSON to reuse instead of running live shortlist again.",
    )
    parser.add_argument("--shortlist-output", default="", help="Optional path for the generated shortlist result JSON.")
    parser.add_argument(
        "--shortlist-markdown-output",
        default="",
        help="Optional path for the generated shortlist markdown report.",
    )
    parser.add_argument(
        "--run-postclose-review",
        action="store_true",
        help="Run postclose_review from the generated shortlist result and attach review artifacts.",
    )
    parser.add_argument("--postclose-output", default="", help="Optional path for the generated postclose review JSON.")
    parser.add_argument(
        "--postclose-markdown-output",
        default="",
        help="Optional path for the generated postclose review markdown report.",
    )
    parser.add_argument("--postclose-plan", default="", help="Optional path to the morning/intraday plan markdown.")
    parser.add_argument(
        "--institutional-evidence",
        action="append",
        default=[],
        help="Optional external evidence JSON to merge into the institutional audit, such as x-index, filing, ownership, or fundamentals artifacts.",
    )
    parser.add_argument(
        "--institutional-evidence-dir",
        action="append",
        default=[],
        help="Optional directory to scan for institutional evidence JSON. Auto-discovery scans the output directory and, for run-root/html style outputs, the run root.",
    )
    parser.add_argument(
        "--no-auto-institutional-evidence",
        action="store_true",
        help="Disable automatic scanning of the output directory and eligible run root for x-index/fundamental evidence JSON.",
    )
    parser.add_argument(
        "--longbridge-news",
        default="",
        help="Optional path to a Longbridge news headlines JSON; auto-discovery scans the run root when omitted.",
    )
    parser.add_argument(
        "--longbridge-market-status",
        default="",
        help="Optional path to a Longbridge market-status JSON; used to feed the weekend-aware probe downgrade.",
    )
    parser.add_argument(
        "--longbridge-market-temp",
        default="",
        help="Optional path to a Longbridge market-temperature JSON; surfaced as catalyst-news evidence.",
    )
    parser.add_argument(
        "--auto-longbridge-sources",
        action="store_true",
        help=(
            "Fetch Longbridge quote/news/detail/market-status/market-temp/capital, "
            "topic, filing, ownership, valuation, forecast, financial-report, operating, "
            "and industry-valuation artifacts before building the manager package."
        ),
    )
    parser.add_argument(
        "--auto-longbridge-output",
        default="",
        help="Optional directory for generated Longbridge artifacts. Defaults to the run root when output-dir is html/outputs.",
    )
    parser.add_argument(
        "--longbridge-news-count",
        type=int,
        default=None,
        help="Maximum Longbridge headlines to fetch per ticker when auto-longbridge-sources is enabled. Defaults to 3, or 5 under --institutional-ready.",
    )
    parser.add_argument(
        "--longbridge-news-detail-limit",
        type=int,
        default=None,
        help="Maximum Longbridge news details to fetch per ticker when auto-longbridge-sources is enabled. Defaults to 2, or 4 under --institutional-ready.",
    )
    parser.add_argument(
        "--reuse-longbridge-artifacts",
        action="store_true",
        help="Reuse existing quote/news/news-detail artifacts in the auto-longbridge output directory before live fetches.",
    )
    parser.add_argument(
        "--longbridge-temp-market",
        action="append",
        default=[],
        help="Market code for Longbridge market-temp collection, such as CN or US. Can be repeated.",
    )
    parser.add_argument(
        "--no-longbridge-capital",
        action="store_true",
        help="Skip Longbridge capital-flow collection when auto-longbridge-sources is enabled.",
    )
    parser.add_argument(
        "--earnings-calendar",
        action="append",
        default=[],
        help="Optional earnings calendar JSON. Supports top-level lists or keys such as earnings_calendar_events/events.",
    )
    parser.add_argument(
        "--auto-earnings-calendar",
        action="store_true",
        help="Generate <run-root>/earnings-calendar.json before building the local stock-pool manager.",
    )
    parser.add_argument(
        "--auto-earnings-calendar-output",
        default="",
        help="Optional generated earnings-calendar JSON path. Defaults to the current run root.",
    )
    parser.add_argument(
        "--earnings-calendar-period",
        action="append",
        default=[],
        help="Optional A-share report period for auto-generated earnings calendar, such as 20260331. Defaults to target-date-based periods.",
    )
    parser.add_argument(
        "--no-a-share-earnings-calendar",
        action="store_true",
        help="Skip A-share disclosure-calendar fetches when auto-generating the earnings calendar.",
    )
    parser.add_argument(
        "--earnings-calendar-focus-source",
        action="append",
        default=[],
        help="Optional package or trading-plan JSON to extract auto-generated earnings-calendar focus names from.",
    )
    parser.add_argument(
        "--include-us-earnings-calendar",
        action="store_true",
        help="Include Nasdaq U.S. earnings calendar data in the auto-generated calendar.",
    )
    parser.add_argument(
        "--nasdaq-earnings-date",
        action="append",
        default=[],
        help="Optional explicit Nasdaq earnings-calendar date for auto-generated calendar.",
    )
    parser.add_argument(
        "--earnings-calendar-watchlist",
        action="append",
        default=[],
        help="Optional ticker or company name to force into the earnings-calendar focus set.",
    )
    parser.add_argument(
        "--earnings-calendar-lookahead-days",
        type=int,
        default=7,
        help="Lookahead window for earnings-calendar reminders. Defaults to 7 calendar days.",
    )
    parser.add_argument(
        "--event-calendar",
        action="append",
        default=[],
        help="Optional hard-event calendar JSON. Supports keys such as event_calendar_events or macro_calendar_events.",
    )
    parser.add_argument(
        "--auto-event-calendar",
        action="store_true",
        help="Generate <run-root>/event-calendar.json before building the local stock-pool manager.",
    )
    parser.add_argument(
        "--auto-event-calendar-output",
        default="",
        help="Optional generated event-calendar JSON path. Defaults to the current run root.",
    )
    parser.add_argument(
        "--include-bls-event-calendar",
        action="store_true",
        help="Include the BLS official news-release iCalendar in the auto-generated hard-event calendar.",
    )
    parser.add_argument(
        "--no-bls-event-calendar",
        action="store_true",
        help=(
            "Skip the BLS official news-release iCalendar when auto-generating the hard-event calendar, "
            "including under --institutional-ready."
        ),
    )
    parser.add_argument(
        "--include-fed-calendar",
        action="store_true",
        help="Include the Federal Reserve monetary-policy calendar in the auto-generated hard-event calendar.",
    )
    parser.add_argument(
        "--event-calendar-ics-url",
        action="append",
        default=[],
        help="Optional official iCalendar URL for the auto-generated hard-event calendar.",
    )
    parser.add_argument(
        "--event-calendar-watchlist",
        action="append",
        default=[],
        help="Optional ticker or company name to force into the hard-event calendar focus set.",
    )
    parser.add_argument(
        "--event-calendar-lookahead-days",
        type=int,
        default=7,
        help="Lookahead window for hard-event reminders. Defaults to 7 calendar days.",
    )
    parser.add_argument(
        "--run-trigger-monitor",
        action="store_true",
        help="Run one trigger-monitor cycle from generated trade cards and attach the quote/alert snapshot.",
    )
    parser.add_argument(
        "--trigger-monitor-output",
        default="",
        help="Optional path for the generated trigger-monitor JSON snapshot.",
    )
    parser.add_argument(
        "--longbridge-binary",
        default="",
        help="Optional Longbridge CLI binary path for live source probes and trigger-monitor quotes.",
    )
    parser.add_argument(
        "--record-trade-journal",
        action="store_true",
        help="Append decision and outcome rows to the persistent trade journal JSONL log.",
    )
    parser.add_argument(
        "--trade-journal-path",
        default="",
        help="Optional path for the trade-journal JSONL file; defaults to <output-dir>/trade-journal.jsonl.",
    )
    parser.add_argument(
        "--update-direction-risk-register",
        action="store_true",
        help="Update the direction risk register from postclose review and attach warnings to plan snapshots.",
    )
    parser.add_argument(
        "--direction-risk-register-path",
        default="",
        help="Optional path for the direction-risk-register JSON; defaults to <output-dir>/direction-risk-register.json.",
    )
    parser.add_argument(
        "--thesis-check",
        "--stock-logic",
        action="append",
        default=[],
        dest="thesis_check",
        help=(
            "Inline JSON or path to JSON describing a ticker/name/thesis/expected_evidence payload. "
            "Can be repeated; --stock-logic is an alias."
        ),
    )
    args = parser.parse_args(argv)
    if args.longbridge_news_count is None:
        args.longbridge_news_count = 5 if args.institutional_ready else 3
    if args.longbridge_news_detail_limit is None:
        args.longbridge_news_detail_limit = 4 if args.institutional_ready else 2
    return args


def should_run_postclose_review(args: argparse.Namespace) -> bool:
    return bool(
        args.institutional_ready
        or args.run_postclose_review
        or args.postclose_output
        or args.postclose_markdown_output
    )


def should_run_shortlist(args: argparse.Namespace) -> bool:
    return bool(
        args.institutional_ready
        or args.run_shortlist
        or args.shortlist_output
        or args.shortlist_markdown_output
        or should_run_postclose_review(args)
    )


def should_run_trigger_monitor(args: argparse.Namespace) -> bool:
    return bool(args.institutional_ready or args.run_trigger_monitor or args.trigger_monitor_output)


def should_record_trade_journal(args: argparse.Namespace) -> bool:
    return bool(args.institutional_ready or args.record_trade_journal or args.trade_journal_path)


def should_update_direction_risk_register(args: argparse.Namespace) -> bool:
    return bool(
        args.institutional_ready
        or args.update_direction_risk_register
        or args.direction_risk_register_path
    )


def should_auto_earnings_calendar(args: argparse.Namespace) -> bool:
    return bool(args.institutional_ready or args.auto_earnings_calendar or args.auto_earnings_calendar_output)


def should_include_us_earnings_calendar(args: argparse.Namespace) -> bool:
    return bool(args.institutional_ready or args.include_us_earnings_calendar or args.nasdaq_earnings_date)


def should_include_a_share_earnings_calendar(args: argparse.Namespace) -> bool:
    return not bool(args.no_a_share_earnings_calendar)


def should_auto_event_calendar(args: argparse.Namespace) -> bool:
    return bool(args.institutional_ready or args.auto_event_calendar or args.auto_event_calendar_output)


def should_include_bls_event_calendar(args: argparse.Namespace) -> bool:
    return bool((args.institutional_ready or args.include_bls_event_calendar) and not args.no_bls_event_calendar)


def should_include_fed_calendar(args: argparse.Namespace) -> bool:
    return bool(args.institutional_ready or args.include_fed_calendar)


def should_auto_longbridge_sources(args: argparse.Namespace) -> bool:
    return bool(args.institutional_ready or args.auto_longbridge_sources or args.auto_longbridge_output)


def default_auto_earnings_calendar_output_path(output_dir: Path) -> Path:
    if output_dir.name.lower() in {"html", "output", "outputs", "artifacts"}:
        return output_dir.parent / "earnings-calendar.json"
    return output_dir / "earnings-calendar.json"


def default_auto_longbridge_sources_output_path(output_dir: Path) -> Path:
    if output_dir.name.lower() in {"html", "output", "outputs", "artifacts"}:
        return output_dir.parent
    return output_dir


def default_auto_event_calendar_output_path(output_dir: Path) -> Path:
    if output_dir.name.lower() in {"html", "output", "outputs", "artifacts"}:
        return output_dir.parent / "event-calendar.json"
    return output_dir / "event-calendar.json"


def auto_earnings_calendar_output_path(args: argparse.Namespace) -> Path:
    if args.auto_earnings_calendar_output:
        return Path(args.auto_earnings_calendar_output)
    return default_auto_earnings_calendar_output_path(Path(args.output_dir))


def auto_event_calendar_output_path(args: argparse.Namespace) -> Path:
    if args.auto_event_calendar_output:
        return Path(args.auto_event_calendar_output)
    return default_auto_event_calendar_output_path(Path(args.output_dir))


def auto_longbridge_sources_output_path(args: argparse.Namespace) -> Path:
    if args.auto_longbridge_output:
        return Path(args.auto_longbridge_output)
    return default_auto_longbridge_sources_output_path(Path(args.output_dir))


def discover_shortlist_input_path(output_dir: Path) -> Path | None:
    candidates = (
        output_dir / "month-end-shortlist-result.json",
        output_dir / "month_end_shortlist_result.json",
    )
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def calendar_output_is_auto_discoverable(calendar_output_path: Path, output_dir: Path) -> bool:
    try:
        resolved_calendar_parent = calendar_output_path.expanduser().resolve().parent
        discovery_roots = {
            root.expanduser().resolve()
            for root in implicit_institutional_evidence_roots(output_dir.expanduser().resolve())
        }
    except OSError:
        return False
    return resolved_calendar_parent in discovery_roots


def _split_top_level_csv(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char in "[{":
            depth += 1
            continue
        if char in "]}":
            depth = max(0, depth - 1)
            continue
        if char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _clean_cmd_stripped_value(text: str) -> str:
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_cmd_stripped_inline_json(text: str) -> dict | list[dict]:
    stripped = text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        rows: list[dict] = []
        for item in _split_top_level_csv(stripped[1:-1]):
            parsed = _parse_cmd_stripped_inline_json(item)
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ValueError("not a cmd-stripped inline object")
    payload: dict[str, object] = {}
    for part in _split_top_level_csv(stripped[1:-1]):
        if ":" not in part:
            raise ValueError(f"invalid inline thesis field: {part}")
        key, raw_value = part.split(":", 1)
        clean_key = _clean_cmd_stripped_value(key)
        value = raw_value.strip()
        if value.startswith("[") and value.endswith("]"):
            payload[clean_key] = [
                _clean_cmd_stripped_value(item)
                for item in _split_top_level_csv(value[1:-1])
                if _clean_cmd_stripped_value(item)
            ]
        else:
            payload[clean_key] = _clean_cmd_stripped_value(value)
    return payload


def load_thesis_check_payloads(values: list[str]) -> list[dict]:
    payloads: list[dict] = []
    for value in values:
        text = value.strip()
        if not text:
            continue
        if text.startswith("{") or text.startswith("["):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = _parse_cmd_stripped_inline_json(text)
        else:
            payload = load_json(text)
        if isinstance(payload, list):
            payloads.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            rows = payload.get("thesis_checks") or payload.get("checks")
            if isinstance(rows, list) and not any(
                key in payload for key in ("ticker", "symbol", "code", "thesis", "logic", "investment_logic")
            ):
                payloads.extend(item for item in rows if isinstance(item, dict))
            else:
                payloads.append(payload)
    return payloads


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir_path = Path(args.output_dir)
    pool = load_pool_or_template(args.pool or None)
    trading_plan_result = load_trading_plan_result(args.trading_plan_result or None)
    market_snapshots = load_market_snapshots(args.market_snapshots or None)
    pool = merge_market_snapshots_into_local_stock_pool(pool, market_snapshots)
    trading_plan_result = merge_market_snapshots_into_trading_plan_result(trading_plan_result, market_snapshots)
    generated_longbridge_dir: Path | None = None
    generated_longbridge_result: dict | None = None
    if should_auto_longbridge_sources(args):
        generated_longbridge_dir = auto_longbridge_sources_output_path(args)
        generated_longbridge_result = collect_longbridge_plan_sources(
            [pool, trading_plan_result],
            output_dir=generated_longbridge_dir,
            longbridge_binary=args.longbridge_binary or "longbridge",
            target_date=args.target_date,
            news_count=args.longbridge_news_count,
            detail_limit_per_ticker=args.longbridge_news_detail_limit,
            include_capital=not args.no_longbridge_capital,
            markets=args.longbridge_temp_market or ["CN"],
            reuse_existing_artifacts=args.reuse_longbridge_artifacts,
        )
        generated_market_snapshots = load_market_snapshots(generated_longbridge_dir / "longbridge-quotes.json")
        pool = merge_market_snapshots_into_local_stock_pool(pool, generated_market_snapshots)
        trading_plan_result = merge_market_snapshots_into_trading_plan_result(trading_plan_result, generated_market_snapshots)
    shortlist_input_path = Path(args.shortlist_input) if args.shortlist_input else discover_shortlist_input_path(output_dir_path)
    institutional_evidence_payloads = [
        payload
        for payload in (load_json(path) for path in args.institutional_evidence)
        if isinstance(payload, dict)
    ]
    earnings_calendar_payloads = [
        payload
        for payload in (load_json(path) for path in args.earnings_calendar)
        if isinstance(payload, (dict, list))
    ]
    event_calendar_payloads = [
        payload
        for payload in (load_json(path) for path in args.event_calendar)
        if isinstance(payload, (dict, list))
    ]
    thesis_check_payloads = load_thesis_check_payloads(args.thesis_check)
    generated_earnings_calendar_path: Path | None = None
    if should_auto_earnings_calendar(args):
        generated_earnings_calendar_path = auto_earnings_calendar_output_path(args)
        generated_earnings_calendar_payload = build_combined_earnings_calendar_payload(
            output_path=generated_earnings_calendar_path,
            target_date=args.target_date,
            lookahead_days=args.earnings_calendar_lookahead_days,
            periods=args.earnings_calendar_period,
            focus_source_paths=args.earnings_calendar_focus_source,
            focus_payloads=[pool, trading_plan_result],
            explicit_focus=args.earnings_calendar_watchlist,
            headliner_values=list(DEFAULT_EARNINGS_CALENDAR_HEADLINERS),
            include_a_share=should_include_a_share_earnings_calendar(args),
            include_us=should_include_us_earnings_calendar(args),
            nasdaq_dates=args.nasdaq_earnings_date,
        )
        write_earnings_calendar_json(generated_earnings_calendar_path, generated_earnings_calendar_payload)
        if not calendar_output_is_auto_discoverable(generated_earnings_calendar_path, Path(args.output_dir)):
            earnings_calendar_payloads.append(generated_earnings_calendar_payload)
    generated_event_calendar_path: Path | None = None
    if should_auto_event_calendar(args):
        generated_event_calendar_path = auto_event_calendar_output_path(args)
        ics_urls = list(args.event_calendar_ics_url)
        if should_include_bls_event_calendar(args):
            ics_urls.append(BLS_ICS_URL)
        ics_rows, source_errors = load_ics_rows_with_errors(ics_urls)
        if should_include_fed_calendar(args):
            fed_rows, fed_errors = load_fed_rows_with_errors(args.target_date)
            ics_rows.extend(fed_rows)
            source_errors.extend(fed_errors)
        generated_event_calendar_payload = build_event_calendar_payload(
            ics_rows,
            target_date=args.target_date,
            lookahead_days=args.event_calendar_lookahead_days,
            focus_values=args.event_calendar_watchlist,
            source="auto.event_calendar",
            source_errors=source_errors,
        )
        write_event_calendar_json(generated_event_calendar_path, generated_event_calendar_payload)
        if not calendar_output_is_auto_discoverable(generated_event_calendar_path, Path(args.output_dir)):
            event_calendar_payloads.append(generated_event_calendar_payload)
    institutional_evidence_dirs = list(args.institutional_evidence_dir)
    if generated_longbridge_dir is not None:
        institutional_evidence_dirs.append(str(generated_longbridge_dir))
    package = write_local_stock_pool_manager_package(
        pool,
        output_dir=output_dir_path,
        trading_plan_result=trading_plan_result,
        tdx_vipdoc_path=args.tdx_vipdoc_path,
        target_date=args.target_date,
        analysis_time=args.analysis_time,
        institutional_ready=args.institutional_ready,
        run_shortlist=should_run_shortlist(args),
        shortlist_input_path=shortlist_input_path,
        shortlist_output_path=args.shortlist_output or None,
        shortlist_markdown_output_path=args.shortlist_markdown_output or None,
        run_postclose_review=should_run_postclose_review(args),
        postclose_output_path=args.postclose_output or None,
        postclose_markdown_output_path=args.postclose_markdown_output or None,
        postclose_plan_path=args.postclose_plan or None,
        institutional_evidence_payloads=institutional_evidence_payloads,
        institutional_evidence_dirs=institutional_evidence_dirs,
        auto_discover_institutional_evidence=not args.no_auto_institutional_evidence,
        execute_institutional_evidence_followups=args.institutional_ready,
        run_live_source_probes=args.institutional_ready,
        longbridge_news_path=(
            args.longbridge_news
            or (str(generated_longbridge_dir / "longbridge-news-headlines.json") if generated_longbridge_dir else None)
        ),
        longbridge_market_status_path=(
            args.longbridge_market_status
            or (str(generated_longbridge_dir / "longbridge-market-status.json") if generated_longbridge_dir else None)
        ),
        longbridge_market_temp_path=(
            args.longbridge_market_temp
            or (str(generated_longbridge_dir / "longbridge-market-temp.json") if generated_longbridge_dir else None)
        ),
        earnings_calendar_payloads=earnings_calendar_payloads,
        earnings_calendar_source_paths=args.earnings_calendar,
        earnings_calendar_watchlist=args.earnings_calendar_watchlist,
        earnings_calendar_lookahead_days=args.earnings_calendar_lookahead_days,
        event_calendar_payloads=event_calendar_payloads,
        event_calendar_source_paths=args.event_calendar,
        event_calendar_watchlist=args.event_calendar_watchlist,
        event_calendar_lookahead_days=args.event_calendar_lookahead_days,
        auto_macro_health_overlay=should_run_shortlist(args),
        run_trigger_monitor=should_run_trigger_monitor(args),
        trigger_monitor_output_path=args.trigger_monitor_output or None,
        longbridge_binary_path=args.longbridge_binary,
        record_trade_journal=should_record_trade_journal(args),
        trade_journal_path=args.trade_journal_path or None,
        update_direction_risk_register=should_update_direction_risk_register(args),
        direction_risk_register_path=args.direction_risk_register_path or None,
        thesis_check_payloads=thesis_check_payloads,
    )
    print(package["html_path"])
    print(package["month_end_request_path"])
    if generated_earnings_calendar_path is not None:
        print(generated_earnings_calendar_path)
    if generated_event_calendar_path is not None:
        print(generated_event_calendar_path)
    if generated_longbridge_result is not None:
        for path in generated_longbridge_result.get("output_paths", {}).values():
            if path:
                print(path)
    if package.get("shortlist_result_path"):
        print(package["shortlist_result_path"])
    if package.get("shortlist_report_path"):
        print(package["shortlist_report_path"])
    if package.get("postclose_review_path"):
        print(package["postclose_review_path"])
    if package.get("postclose_report_path"):
        print(package["postclose_report_path"])
    if package.get("institutional_signal_audit_path"):
        print(package["institutional_signal_audit_path"])
    if package.get("institutional_signal_audit_report_path"):
        print(package["institutional_signal_audit_report_path"])
    if package.get("trigger_monitor_path"):
        print(package["trigger_monitor_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
