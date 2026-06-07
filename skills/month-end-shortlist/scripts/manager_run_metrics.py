#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "local_stock_pool_manager_run_metrics/v1"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def number_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_datetime_value(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except (OSError, OverflowError, ValueError):
            return None
    text = clean_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def latest_published_at(rows: list[Any]) -> datetime | None:
    latest: datetime | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        published_at = parse_datetime_value(row.get("published_at") or row.get("datetime") or row.get("date"))
        if published_at is None:
            continue
        if latest is None or published_at > latest:
            latest = published_at
    return latest


def age_days(reference: datetime | None, published_at: datetime | None) -> float:
    if reference is None or published_at is None:
        return 0.0
    return round((reference - published_at).total_seconds() / 86400, 2)


def ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def package_path_for_run(run_dir: str | Path) -> Path:
    path = Path(run_dir).expanduser().resolve()
    if path.is_file():
        return path
    return path / "local-stock-pool-manager-package.json"


def load_optional_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return load_json(path)


def load_source_run(package: dict[str, Any], package_path: Path) -> dict[str, Any]:
    embedded = safe_dict(package.get("longbridge_plan_source_run"))
    if embedded:
        return embedded
    source_path = clean_text(safe_dict(package.get("longbridge_artifact_sources")).get("plan_source_run"))
    if source_path:
        return safe_dict(load_optional_json(Path(source_path)))
    sibling = package_path.parent / "longbridge-plan-source-run.json"
    if sibling.exists():
        return safe_dict(load_optional_json(sibling))
    parent_sibling = package_path.parent.parent / "longbridge-plan-source-run.json"
    if parent_sibling.exists():
        return safe_dict(load_optional_json(parent_sibling))
    return {}


def load_audit(package: dict[str, Any], package_path: Path) -> dict[str, Any]:
    embedded = safe_dict(package.get("institutional_signal_audit"))
    if embedded:
        return embedded
    return safe_dict(load_optional_json(package_path.parent / "institutional-signal-audit.json"))


def x_index_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    posts = [row for row in safe_list(payload.get("x_posts")) if isinstance(row, dict)]
    evidence_pack = safe_dict(payload.get("evidence_pack"))
    pack_posts = [row for row in safe_list(evidence_pack.get("x_posts")) if isinstance(row, dict)]
    return posts if len(posts) >= len(pack_posts) else pack_posts


def x_index_post_uses_detail_text(post: dict[str, Any]) -> bool:
    source = clean_text(post.get("post_text_source")).lower()
    return source in {"dom", "dom_target", "accessibility", "accessibility_root"}


def x_index_post_has_expansion(post: dict[str, Any]) -> bool:
    notes = " ".join(
        clean_text(item)
        for item in [
            *safe_list(post.get("crawl_notes")),
            *safe_list(post.get("session_notes")),
        ]
    ).lower()
    for match in re.findall(r"expand_clicks=(\d+)", notes):
        try:
            if int(match) > 0:
                return True
        except ValueError:
            continue
    return False


def load_x_index_result(package: dict[str, Any], package_path: Path) -> dict[str, Any]:
    followups = [row for row in safe_list(package.get("institutional_evidence_followups")) if isinstance(row, dict)]
    candidate_paths: list[Path] = []
    for row in followups:
        if clean_text(row.get("id")) != "social_altdata":
            continue
        for key in ("result_path", "expected_result_path"):
            path_text = clean_text(row.get(key))
            if path_text:
                candidate_paths.append(Path(path_text).expanduser())
        break
    candidate_paths.extend(
        [
            package_path.parent / "x-index-social-evidence" / "x-index-result.json",
            package_path.parent / "x-index-result.json",
        ]
    )
    for path in candidate_paths:
        if path.exists():
            try:
                return safe_dict(load_json(path))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
    return {}


def summarize_x_index_result(payload: dict[str, Any]) -> dict[str, Any]:
    posts = x_index_posts(payload)
    post_count = len(posts)
    browser_session_post_count = sum(1 for post in posts if clean_text(post.get("access_mode")) == "browser_session")
    dom_text_post_count = sum(1 for post in posts if x_index_post_uses_detail_text(post))
    hydrated_detail_post_count = sum(
        1
        for post in posts
        if "hydrated fixed-profile capture from detail page" in " ".join(
            clean_text(item)
            for item in [*safe_list(post.get("crawl_notes")), *safe_list(post.get("session_notes"))]
        ).lower()
    )
    expanded_detail_post_count = sum(1 for post in posts if x_index_post_has_expansion(post))
    max_text_length = max((len(clean_text(post.get("post_text_raw") or post.get("text"))) for post in posts), default=0)
    return {
        "x_index_post_count": post_count,
        "x_index_browser_session_post_count": browser_session_post_count,
        "x_index_dom_text_post_count": dom_text_post_count,
        "x_index_hydrated_detail_post_count": hydrated_detail_post_count,
        "x_index_expanded_detail_post_count": expanded_detail_post_count,
        "x_index_max_text_length": max_text_length,
    }


def build_run_metric_row(run_dir: str | Path) -> dict[str, Any]:
    package_path = package_path_for_run(run_dir)
    package = safe_dict(load_json(package_path))
    source_run = load_source_run(package, package_path)
    audit = load_audit(package, package_path)
    x_index_summary = summarize_x_index_result(load_x_index_result(package, package_path))
    coverage_summary = safe_dict(safe_dict(package.get("ticker_quote_news_coverage")).get("summary"))
    source_summary = {
        **safe_dict(package.get("longbridge_plan_source_summary")),
        **safe_dict(source_run.get("summary")),
    }
    ticker_count = (
        number_value(source_summary.get("information_completion_ticker_count"))
        or number_value(source_summary.get("ticker_count"))
        or number_value(coverage_summary.get("stock_count"))
    )
    completion_count = (
        number_value(source_summary.get("information_completion_complete_count"))
        or number_value(coverage_summary.get("information_completion_complete_count"))
    )
    detail_ok_count = (
        number_value(source_summary.get("news_detail_ok_count"))
        or number_value(coverage_summary.get("news_detail_ok_count"))
    )
    detail_usable_count = (
        number_value(source_summary.get("news_detail_usable_count"))
        or number_value(coverage_summary.get("news_detail_usable_count"))
    )
    detail_error_count = (
        number_value(source_summary.get("news_detail_error_count"))
        or number_value(coverage_summary.get("news_detail_error_count"))
    )
    detail_html_fallback_success_count = (
        number_value(source_summary.get("news_detail_html_fallback_success_count"))
        or number_value(coverage_summary.get("news_detail_html_fallback_success_count"))
    )
    detail_language_fallback_success_count = (
        number_value(source_summary.get("news_detail_language_fallback_success_count"))
        or number_value(coverage_summary.get("news_detail_language_fallback_success_count"))
    )
    detail_rows = safe_list(package.get("longbridge_news_details")) or safe_list(source_run.get("longbridge_news_details"))
    latest_detail = latest_published_at(detail_rows)
    reference_time = parse_datetime_value(source_run.get("retrieved_at") or package.get("retrieved_at"))
    command_statuses = [row for row in safe_list(source_run.get("command_statuses")) if isinstance(row, dict)]
    reused_count = sum(1 for row in command_statuses if clean_text(row.get("status")) == "reused")
    command_status_count = len(command_statuses)
    artifact_reuse_count = number_value(source_summary.get("artifact_reuse_count")) or reused_count
    runtime_seconds = number_value(source_summary.get("runtime_seconds"))
    missing_required = unique_strings(safe_list(audit.get("missing_required")))
    status = clean_text(audit.get("status")) or clean_text(safe_dict(package.get("institutional_signal_audit")).get("status"))
    passed = status == "institutional_ready" and not missing_required
    return {
        "run_dir": str(package_path.parent),
        "package_path": str(package_path),
        "status": status or "unknown",
        "passed": passed,
        "ticker_count": int(ticker_count),
        "information_completion_complete_count": int(completion_count),
        "source_completion_rate": ratio(completion_count, ticker_count),
        "news_detail_ok_count": int(detail_ok_count),
        "news_detail_usable_count": int(detail_usable_count),
        "news_detail_error_count": int(detail_error_count),
        "news_detail_html_fallback_success_count": int(detail_html_fallback_success_count),
        "news_detail_language_fallback_success_count": int(detail_language_fallback_success_count),
        "detail_ok_per_ticker": ratio(detail_ok_count, ticker_count),
        "detail_usable_per_ticker": ratio(detail_usable_count, ticker_count),
        "detail_error_per_ticker": ratio(detail_error_count, ticker_count),
        "latest_news_detail_published_at": latest_detail.isoformat() if latest_detail else "",
        "latest_news_detail_age_days": age_days(reference_time, latest_detail),
        "artifact_reuse_count": int(artifact_reuse_count),
        "command_status_count": command_status_count,
        "cache_reuse_rate": ratio(reused_count, command_status_count),
        "runtime_seconds": round(runtime_seconds, 3),
        "source_error_count": int(number_value(source_summary.get("source_error_count"))),
        **x_index_summary,
        "remaining_blockers": missing_required,
    }


def build_run_metrics(run_dirs: list[str | Path]) -> dict[str, Any]:
    rows = [build_run_metric_row(path) for path in run_dirs]
    total_runs = len(rows)
    total_tickers = sum(number_value(row.get("ticker_count")) for row in rows)
    total_completion = sum(number_value(row.get("information_completion_complete_count")) for row in rows)
    total_detail_ok = sum(number_value(row.get("news_detail_ok_count")) for row in rows)
    total_detail_usable = sum(number_value(row.get("news_detail_usable_count")) for row in rows)
    total_detail_errors = sum(number_value(row.get("news_detail_error_count")) for row in rows)
    total_detail_html_fallback_success = sum(
        number_value(row.get("news_detail_html_fallback_success_count")) for row in rows
    )
    total_detail_language_fallback_success = sum(
        number_value(row.get("news_detail_language_fallback_success_count")) for row in rows
    )
    total_x_index_posts = sum(number_value(row.get("x_index_post_count")) for row in rows)
    total_x_index_browser_session_posts = sum(number_value(row.get("x_index_browser_session_post_count")) for row in rows)
    total_x_index_dom_text_posts = sum(number_value(row.get("x_index_dom_text_post_count")) for row in rows)
    total_x_index_hydrated_detail_posts = sum(number_value(row.get("x_index_hydrated_detail_post_count")) for row in rows)
    total_x_index_expanded_detail_posts = sum(number_value(row.get("x_index_expanded_detail_post_count")) for row in rows)
    max_x_index_text_length = max((number_value(row.get("x_index_max_text_length")) for row in rows), default=0)
    latest_detail_dates = [
        published_at
        for published_at in (parse_datetime_value(row.get("latest_news_detail_published_at")) for row in rows)
        if published_at is not None
    ]
    latest_detail_ages = [
        number_value(row.get("latest_news_detail_age_days"))
        for row in rows
        if clean_text(row.get("latest_news_detail_published_at"))
    ]
    latest_detail = max(latest_detail_dates) if latest_detail_dates else None
    total_reused = sum(number_value(row.get("artifact_reuse_count")) for row in rows)
    total_command_statuses = sum(number_value(row.get("command_status_count")) for row in rows)
    total_runtime_seconds = round(sum(number_value(row.get("runtime_seconds")) for row in rows), 3)
    remaining_blockers = unique_strings(
        [blocker for row in rows for blocker in safe_list(row.get("remaining_blockers"))]
    )
    summary = {
        "total_runs": total_runs,
        "pass_count": sum(1 for row in rows if row.get("passed")),
        "fail_count": sum(1 for row in rows if not row.get("passed")),
        "source_completion_rate": ratio(total_completion, total_tickers),
        "detail_ok_per_ticker": ratio(total_detail_ok, total_tickers),
        "detail_usable_per_ticker": ratio(total_detail_usable, total_tickers),
        "detail_error_per_ticker": ratio(total_detail_errors, total_tickers),
        "news_detail_ok_count": int(total_detail_ok),
        "news_detail_usable_count": int(total_detail_usable),
        "news_detail_html_fallback_success_count": int(total_detail_html_fallback_success),
        "news_detail_language_fallback_success_count": int(total_detail_language_fallback_success),
        "x_index_post_count": int(total_x_index_posts),
        "x_index_browser_session_post_count": int(total_x_index_browser_session_posts),
        "x_index_dom_text_post_count": int(total_x_index_dom_text_posts),
        "x_index_hydrated_detail_post_count": int(total_x_index_hydrated_detail_posts),
        "x_index_expanded_detail_post_count": int(total_x_index_expanded_detail_posts),
        "x_index_max_text_length": int(max_x_index_text_length),
        "latest_news_detail_published_at": latest_detail.isoformat() if latest_detail else "",
        "latest_news_detail_age_days": round(min(latest_detail_ages), 2) if latest_detail_ages else 0.0,
        "cache_reuse_rate": ratio(total_reused, total_command_statuses),
        "total_runtime_seconds": total_runtime_seconds,
        "avg_runtime_seconds": round(total_runtime_seconds / total_runs, 3) if total_runs else 0.0,
        "remaining_blockers": remaining_blockers,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": summary,
        "runs": rows,
    }


def render_markdown_metrics(metrics: dict[str, Any]) -> str:
    summary = safe_dict(metrics.get("summary"))
    lines = [
        "# Local Stock Pool Manager Run Metrics",
        "",
        f"- total_runs: `{summary.get('total_runs', 0)}`",
        f"- pass_count: `{summary.get('pass_count', 0)}`",
        f"- fail_count: `{summary.get('fail_count', 0)}`",
        f"- source_completion_rate: `{summary.get('source_completion_rate', 0)}`",
        f"- detail_ok_per_ticker: `{summary.get('detail_ok_per_ticker', 0)}`",
        f"- detail_usable_per_ticker: `{summary.get('detail_usable_per_ticker', 0)}`",
        f"- detail_error_per_ticker: `{summary.get('detail_error_per_ticker', 0)}`",
        f"- news_detail_ok_count: `{summary.get('news_detail_ok_count', 0)}`",
        f"- news_detail_usable_count: `{summary.get('news_detail_usable_count', 0)}`",
        f"- news_detail_html_fallback_success_count: `{summary.get('news_detail_html_fallback_success_count', 0)}`",
        f"- news_detail_language_fallback_success_count: `{summary.get('news_detail_language_fallback_success_count', 0)}`",
        f"- x_index_post_count: `{summary.get('x_index_post_count', 0)}`",
        f"- x_index_browser_session_post_count: `{summary.get('x_index_browser_session_post_count', 0)}`",
        f"- x_index_dom_text_post_count: `{summary.get('x_index_dom_text_post_count', 0)}`",
        f"- x_index_hydrated_detail_post_count: `{summary.get('x_index_hydrated_detail_post_count', 0)}`",
        f"- x_index_expanded_detail_post_count: `{summary.get('x_index_expanded_detail_post_count', 0)}`",
        f"- x_index_max_text_length: `{summary.get('x_index_max_text_length', 0)}`",
        f"- latest_news_detail_published_at: `{summary.get('latest_news_detail_published_at', '')}`",
        f"- latest_news_detail_age_days: `{summary.get('latest_news_detail_age_days', 0)}`",
        f"- cache_reuse_rate: `{summary.get('cache_reuse_rate', 0)}`",
        f"- total_runtime_seconds: `{summary.get('total_runtime_seconds', 0)}`",
        f"- avg_runtime_seconds: `{summary.get('avg_runtime_seconds', 0)}`",
        f"- remaining_blockers: `{', '.join(clean_text(item) for item in safe_list(summary.get('remaining_blockers'))) or 'none'}`",
        "",
        "## Runs",
        "",
    ]
    for row in safe_list(metrics.get("runs")):
        if not isinstance(row, dict):
            continue
        lines.append(
            "- "
            f"`{clean_text(row.get('run_dir'))}` "
            f"status=`{clean_text(row.get('status'))}` "
            f"source_completion_rate=`{row.get('source_completion_rate', 0)}` "
            f"detail_ok_per_ticker=`{row.get('detail_ok_per_ticker', 0)}` "
            f"detail_usable_per_ticker=`{row.get('detail_usable_per_ticker', 0)}` "
            f"detail_error_per_ticker=`{row.get('detail_error_per_ticker', 0)}` "
            f"news_detail_ok_count=`{row.get('news_detail_ok_count', 0)}` "
            f"news_detail_usable_count=`{row.get('news_detail_usable_count', 0)}` "
            f"x_index_post_count=`{row.get('x_index_post_count', 0)}` "
            f"x_index_browser_session_post_count=`{row.get('x_index_browser_session_post_count', 0)}` "
            f"x_index_dom_text_post_count=`{row.get('x_index_dom_text_post_count', 0)}` "
            f"x_index_hydrated_detail_post_count=`{row.get('x_index_hydrated_detail_post_count', 0)}` "
            f"x_index_expanded_detail_post_count=`{row.get('x_index_expanded_detail_post_count', 0)}` "
            f"x_index_max_text_length=`{row.get('x_index_max_text_length', 0)}` "
            f"latest_news_detail_published_at=`{clean_text(row.get('latest_news_detail_published_at'))}` "
            f"latest_news_detail_age_days=`{row.get('latest_news_detail_age_days', 0)}` "
            f"cache_reuse_rate=`{row.get('cache_reuse_rate', 0)}` "
            f"runtime_seconds=`{row.get('runtime_seconds', 0)}` "
            f"remaining_blockers=`{', '.join(clean_text(item) for item in safe_list(row.get('remaining_blockers'))) or 'none'}`"
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize local_stock_pool_manager run metrics.")
    parser.add_argument("--run-dir", action="append", required=True, help="Run html dir or package JSON path.")
    parser.add_argument("--output", required=True, help="Metrics JSON output path.")
    parser.add_argument("--markdown-output", default="", help="Optional Markdown metrics output path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metrics = build_run_metrics(args.run_dir)
    output_path = Path(args.output).expanduser().resolve()
    write_json(output_path, metrics)
    print(output_path)
    if args.markdown_output:
        markdown_path = Path(args.markdown_output).expanduser().resolve()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown_metrics(metrics), encoding="utf-8")
        print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
