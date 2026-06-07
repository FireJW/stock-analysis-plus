#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any

from local_stock_pool_runtime import clean_text
from manager_html_primitives import parse_float, safe_dict, safe_list
from manager_pool_merge import normalize_workflow_display_ticker


LONGBRIDGE_EXPECTATION_SOURCE_CONFIGS: tuple[dict[str, Any], ...] = (
    {
        "source_kind": "valuation",
        "payload_field": "valuation",
        "package_keys": (
            "longbridge_valuation",
            "longbridge_valuations",
            "valuation",
            "valuations",
        ),
        "row_keys": ("valuations", "valuation", "rows", "items", "data", "results"),
    },
    {
        "source_kind": "institution_rating",
        "payload_field": "institutional",
        "package_keys": (
            "longbridge_institution_rating",
            "longbridge_institution_ratings",
            "longbridge_institutional_rating",
            "longbridge_institutional_ratings",
            "institution_rating",
            "institution_ratings",
            "analyst_ratings",
            "ratings",
        ),
        "row_keys": ("ratings", "institution_ratings", "institution_rating", "rows", "items", "data", "results"),
    },
    {
        "source_kind": "forecast_eps",
        "payload_field": "fundamentals",
        "package_keys": (
            "longbridge_forecast_eps",
            "longbridge_eps_forecast",
            "longbridge_eps_forecasts",
            "forecast_eps",
            "eps_forecast",
            "eps_forecasts",
            "earnings_forecast",
            "earnings_forecasts",
        ),
        "row_keys": ("forecast_eps", "eps_forecasts", "forecasts", "estimates", "rows", "items", "data", "results"),
    },
    {
        "source_kind": "consensus",
        "payload_field": "fundamentals",
        "package_keys": (
            "longbridge_consensus",
            "longbridge_consensus_estimates",
            "consensus",
            "consensus_estimates",
            "estimates",
        ),
        "row_keys": ("consensus", "consensus_estimates", "estimates", "rows", "items", "data", "results"),
    },
)


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in ("", None, [], {})}


EXPECTATION_METADATA_KEYS = {
    "ticker",
    "symbol",
    "code",
    "name",
    "stock_name",
    "security_name",
    "source",
    "source_kind",
    "source_path",
    "path",
    "artifact_path",
    "schema",
    "schema_version",
    "retrieved_at",
    "current_index",
    "current_period",
    "opt_periods",
}


def _expectation_value_is_meaningful(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) != 0.0
    if isinstance(value, str):
        return bool(clean_text(value))
    if isinstance(value, list):
        return any(_expectation_value_is_meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(_expectation_value_is_meaningful(item) for item in value.values())
    return True


def _expectation_row_has_meaningful_payload(row: dict[str, Any]) -> bool:
    payload = {key: value for key, value in row.items() if key not in EXPECTATION_METADATA_KEYS}
    return any(_expectation_value_is_meaningful(value) for value in payload.values())


def _iter_source_rows(value: Any, row_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict) and _compact_row(row)]
    if not isinstance(value, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in row_keys:
        nested = value.get(key)
        if nested is value:
            continue
        nested_rows = _iter_source_rows(nested, row_keys)
        if nested_rows:
            rows.extend(nested_rows)
    if rows:
        return rows
    compacted = _compact_row(value)
    return [compacted] if compacted else []


def _longbridge_expectation_containers(package: dict[str, Any]) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = [package]
    plan_source_run = safe_dict(package.get("longbridge_plan_source_run"))
    if plan_source_run:
        containers.append(plan_source_run)
        inherited_meta = {
            key: plan_source_run.get(key)
            for key in ("retrieved_at", "analysis_time", "target_date", "source_path")
            if plan_source_run.get(key) not in (None, "", [], {})
        }
        for key in ("outputs", "artifacts", "evidence", "payload"):
            nested = safe_dict(plan_source_run.get(key))
            if nested:
                containers.append({**inherited_meta, **nested})
    return containers


def build_longbridge_expectation_evidence_rows(package: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(package, dict):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    artifact_sources = safe_dict(package.get("longbridge_expectation_artifact_sources"))
    for container in _longbridge_expectation_containers(package):
        retrieved_at = clean_text(container.get("retrieved_at") or container.get("analysis_time") or container.get("target_date"))
        for config in LONGBRIDGE_EXPECTATION_SOURCE_CONFIGS:
            source_kind = clean_text(config.get("source_kind"))
            payload_field = clean_text(config.get("payload_field"))
            row_keys = tuple(config.get("row_keys") or ())
            for package_key in config.get("package_keys") or ():
                source_payload = container.get(package_key)
                if source_payload in (None, "", [], {}):
                    continue
                for raw_row in _iter_source_rows(source_payload, row_keys):
                    ticker = normalize_workflow_display_ticker(
                        raw_row.get("ticker") or raw_row.get("symbol") or raw_row.get("code")
                    )
                    row_payload = _compact_row(dict(raw_row))
                    if not _expectation_row_has_meaningful_payload(row_payload):
                        continue
                    row: dict[str, Any] = {
                        "schema_version": "longbridge-expectation-evidence-row/v1",
                        "source": "longbridge",
                        "source_kind": source_kind,
                        "evidence_category": source_kind,
                        payload_field: row_payload,
                        "raw": row_payload,
                    }
                    if ticker:
                        row["ticker"] = ticker
                    name = clean_text(raw_row.get("name") or raw_row.get("stock_name") or raw_row.get("security_name"))
                    if name:
                        row["name"] = name
                    source_path = clean_text(
                        raw_row.get("source_path")
                        or raw_row.get("path")
                        or raw_row.get("artifact_path")
                        or container.get("source_path")
                        or artifact_sources.get(source_kind)
                    )
                    if source_path:
                        row["source_path"] = source_path
                    if retrieved_at:
                        row["retrieved_at"] = retrieved_at
                    marker = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    rows.append(_compact_row(row))
    return rows


def build_longbridge_capital_flow_rows(package: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(package, dict):
        return []
    raw_rows = package.get("longbridge_capital_flows")
    if raw_rows in (None, "", [], {}):
        raw_rows = [
            row
            for row in safe_list(package.get("capital_flows"))
            if isinstance(row, dict) and clean_text(row.get("source")).lower().startswith("longbridge")
        ]
    artifact_sources = safe_dict(package.get("longbridge_artifact_sources"))
    source_path = clean_text(artifact_sources.get("capital_flows"))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_row in safe_list(raw_rows):
        if not isinstance(raw_row, dict):
            continue
        row = _compact_row(dict(raw_row))
        ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
        if ticker:
            row["ticker"] = ticker
        row.setdefault("source", "longbridge.capital")
        if source_path and not clean_text(row.get("source_path")):
            row["source_path"] = source_path
        marker = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        rows.append(row)
    return rows


def is_longbridge_aggregate_evidence_payload(payload: dict[str, Any]) -> bool:
    schema_text = clean_text(payload.get("schema_version") or payload.get("schema") or payload.get("workflow_kind")).lower()
    source_path = clean_text(payload.get("source_path") or payload.get("path") or payload.get("artifact_path")).lower()
    return (
        "longbridge-institutional-evidence" in schema_text
        or "longbridge_plan_source" in schema_text
        or "longbridge-institutional-evidence" in source_path
    )


def package_has_loaded_longbridge_source_artifacts(package: dict[str, Any]) -> bool:
    if safe_dict(package.get("longbridge_plan_source_summary")):
        return True
    return any(
        package.get(key) not in (None, "", [], {})
        for key in (
            "longbridge_quotes",
            "longbridge_news_headlines",
            "longbridge_news_details",
            "longbridge_capital_flows",
            "longbridge_topics",
            "longbridge_filings",
            "longbridge_shareholders",
            "longbridge_fund_holders",
            "longbridge_insider_trades",
            "longbridge_short_positions",
            "longbridge_financial_reports",
            "longbridge_operating_reviews",
            "longbridge_industry_valuation",
            "longbridge_valuation",
            "longbridge_institution_rating",
            "longbridge_forecast_eps",
            "longbridge_consensus",
        )
    )


def build_volume_anomaly_evidence_from_shortlist(shortlist_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(shortlist_result, dict):
        return []
    rows: list[dict[str, Any]] = []
    for bucket in ("top_picks", "directly_actionable", "priority_watchlist", "near_miss_candidates", "diagnostic_scorecard"):
        bucket_rows = shortlist_result.get(bucket)
        if not isinstance(bucket_rows, list):
            continue
        for raw in bucket_rows:
            row = safe_dict(raw)
            ticker = normalize_workflow_display_ticker(row.get("ticker") or row.get("symbol") or row.get("code"))
            if not ticker:
                continue
            volume_ratio = parse_float(row.get("volume_ratio"))
            turnover_rate = parse_float(row.get("turnover_rate_pct"))
            turnover = parse_float(row.get("day_turnover_cny"))
            signals: list[str] = []
            if volume_ratio is not None and volume_ratio >= 1.5:
                signals.append("volume_ratio")
            if turnover_rate is not None and turnover_rate >= 3.0:
                signals.append("turnover_rate_pct")
            if turnover is not None and turnover >= 500_000_000:
                signals.append("day_turnover_cny")
            if not signals:
                continue
            evidence: dict[str, Any] = {
                "source": "shortlist_participation",
                "ticker": ticker,
                "name": clean_text(row.get("name")),
                "bucket": bucket,
                "signals": signals,
            }
            if volume_ratio is not None:
                evidence["volume_ratio"] = volume_ratio
            if turnover_rate is not None:
                evidence["turnover_rate_pct"] = turnover_rate
            if turnover is not None:
                evidence["day_turnover_cny"] = turnover
            day_pct = parse_float(row.get("day_pct"))
            if day_pct is not None:
                evidence["day_pct"] = day_pct
            rows.append({key: value for key, value in evidence.items() if value not in ("", None, [], {})})
    return rows


def build_postclose_validation_evidence(postclose_review: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(postclose_review, dict):
        return [], {}
    trade_date = clean_text(postclose_review.get("trade_date"))
    actuals: list[dict[str, Any]] = []
    for raw_candidate in safe_list(postclose_review.get("candidates_reviewed")):
        candidate = safe_dict(raw_candidate)
        ticker = normalize_workflow_display_ticker(candidate.get("ticker") or candidate.get("symbol") or candidate.get("code"))
        if not ticker:
            continue
        actual_return_pct = parse_float(candidate.get("actual_return_pct"))
        if actual_return_pct is None and not clean_text(candidate.get("judgment") or candidate.get("outcome")):
            continue
        row: dict[str, Any] = {
            "schema_version": "postclose-validation-actual/v1",
            "source": "postclose_review",
            "ticker": ticker,
            "name": clean_text(candidate.get("name")),
            "trade_date": trade_date,
            "planned_action": clean_text(candidate.get("plan_action") or candidate.get("midday_action")),
            "actual_return_pct": actual_return_pct,
            "intraday_structure": clean_text(candidate.get("intraday_structure")),
            "outcome": clean_text(candidate.get("judgment") or candidate.get("outcome")),
            "adjustment": clean_text(candidate.get("adjustment")),
        }
        priority_delta = parse_float(candidate.get("priority_delta"))
        if priority_delta is not None:
            row["priority_delta"] = priority_delta
        actuals.append(_compact_row(row))
    if not actuals:
        return [], {}
    summary = safe_dict(postclose_review.get("summary"))
    reviewed_count = int(parse_float(summary.get("total_reviewed")) or len(actuals))
    correct_count = int(parse_float(summary.get("correct")) or 0)
    correct_negative_count = int(parse_float(summary.get("correct_negative")) or 0)
    missed_count = int(parse_float(summary.get("missed")) or 0)
    too_aggressive_count = int(parse_float(summary.get("too_aggressive")) or 0)
    effective_correct_count = correct_count + correct_negative_count
    hit_rate = round(effective_correct_count / reviewed_count, 4) if reviewed_count > 0 else None
    validation = _compact_row(
        {
            "schema_version": "postclose-validation-summary/v1",
            "source": "postclose_review",
            "trade_date": trade_date,
            "reviewed_count": reviewed_count,
            "correct_count": correct_count,
            "correct_negative_count": correct_negative_count,
            "missed_count": missed_count,
            "too_aggressive_count": too_aggressive_count,
            "hit_rate": hit_rate,
        }
    )
    return actuals, validation


def build_institutional_signal_audit_payload(
    package: dict[str, Any],
    *,
    shortlist_result: dict[str, Any] | None = None,
    postclose_review_result: dict[str, Any] | None = None,
    institutional_evidence_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if isinstance(shortlist_result, dict):
        payload.update(shortlist_result)
    payload["local_stock_pool"] = package.get("local_stock_pool")
    payload["month_end_request"] = package.get("month_end_request")
    month_end_request = safe_dict(package.get("month_end_request"))
    for key in ("target_date", "analysis_time"):
        value = clean_text(package.get(key) or month_end_request.get(key))
        if value:
            payload[key] = value
    payload["source_health"] = {
        "shortlist_result_path": clean_text(package.get("shortlist_result_path")),
        "shortlist_report_path": clean_text(package.get("shortlist_report_path")),
        "postclose_review_path": clean_text(package.get("postclose_review_path")),
        "postclose_report_path": clean_text(package.get("postclose_report_path")),
    }
    longbridge_plan_source_summary = safe_dict(package.get("longbridge_plan_source_summary"))
    if longbridge_plan_source_summary:
        payload["longbridge_plan_source_summary"] = longbridge_plan_source_summary
        source_health = dict(safe_dict(payload.get("source_health")))
        quality = clean_text(longbridge_plan_source_summary.get("longbridge_plan_source_quality"))
        if quality:
            source_health["longbridge_plan_sources"] = quality
        for key in (
            "source_error_count",
            "recovered_source_error_count",
            "news_detail_usable_count",
            "news_detail_error_count",
            "news_detail_unattributed_count",
            "news_detail_stale_count",
            "news_detail_empty_count",
            "news_detail_html_fallback_success_count",
            "news_detail_language_fallback_success_count",
            "news_detail_cache_hit_count",
        ):
            value = longbridge_plan_source_summary.get(key)
            if value not in (None, "", [], {}):
                source_health[key] = value
        payload["source_health"] = source_health
    information_completion_index = safe_dict(
        package.get("information_completion_index")
        or safe_dict(package.get("longbridge_plan_source_run")).get("information_completion_index")
    )
    if information_completion_index:
        payload["information_completion_index"] = information_completion_index
        completion_summary = safe_dict(information_completion_index.get("summary"))
        source_health = dict(safe_dict(payload.get("source_health")))
        for source_key, health_key in (
            ("ticker_count", "information_completion_ticker_count"),
            ("complete_count", "information_completion_complete_count"),
            ("partial_count", "information_completion_partial_count"),
            ("missing_count", "information_completion_missing_count"),
        ):
            value = completion_summary.get(source_key)
            if value not in (None, "", [], {}):
                source_health[health_key] = value
        payload["source_health"] = source_health
    if isinstance(package.get("fresh_discovery_coverage"), dict) and "fresh_discovery_coverage" not in payload:
        payload["fresh_discovery_coverage"] = package["fresh_discovery_coverage"]
    if isinstance(package.get("fresh_discovery_sector_layer"), dict):
        payload["fresh_discovery_sector_layer"] = package["fresh_discovery_sector_layer"]
    for key in (
        "macro_health_overlay",
        "macro_health_overlay_live_fetch_summary",
        "macro_health_overlay_seed_summary",
    ):
        if isinstance(package.get(key), dict):
            payload[key] = package[key]
    if isinstance(package.get("source_capabilities"), list):
        payload["source_capabilities"] = package["source_capabilities"]
    if isinstance(package.get("source_health_probes"), list):
        payload["source_health_probes"] = package["source_health_probes"]
    if isinstance(package.get("longbridge_news_headlines"), list):
        payload["longbridge_news_headlines"] = package["longbridge_news_headlines"]
    if isinstance(package.get("longbridge_news_details"), list):
        payload["longbridge_news_details"] = package["longbridge_news_details"]
    if isinstance(package.get("ticker_quote_news_coverage"), dict):
        payload["ticker_quote_news_coverage"] = package["ticker_quote_news_coverage"]
    if isinstance(package.get("stock_logic_check"), dict):
        payload["stock_logic_check"] = package["stock_logic_check"]
    if isinstance(package.get("thesis_fact_check"), dict):
        payload["thesis_fact_check"] = package["thesis_fact_check"]
    longbridge_quotes = [row for row in safe_list(package.get("longbridge_quotes")) if isinstance(row, dict)]
    if longbridge_quotes:
        payload["longbridge_quotes"] = longbridge_quotes
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["longbridge_quote_count"] = len(longbridge_quotes)
        source_health["longbridge_quote_source"] = "longbridge"
        payload["source_health"] = source_health
    if isinstance(package.get("longbridge_market_session_index"), dict):
        payload["longbridge_market_session_index"] = package["longbridge_market_session_index"]
    if isinstance(package.get("longbridge_market_temperature"), dict):
        payload["longbridge_market_temperature"] = package["longbridge_market_temperature"]
    longbridge_capital_flows = build_longbridge_capital_flow_rows(package)
    if longbridge_capital_flows:
        existing_capital_flows = [row for row in safe_list(payload.get("capital_flows")) if isinstance(row, dict)]
        payload["capital_flows"] = existing_capital_flows + longbridge_capital_flows
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["longbridge_capital_flow_count"] = len(longbridge_capital_flows)
        source_health["longbridge_capital_flow_source"] = "longbridge"
        payload["source_health"] = source_health
    longbridge_topics = [row for row in safe_list(package.get("longbridge_topics")) if isinstance(row, dict)]
    if longbridge_topics:
        existing_social_evidence = [row for row in safe_list(payload.get("social_evidence")) if isinstance(row, dict)]
        payload["social_evidence"] = existing_social_evidence + longbridge_topics
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["longbridge_topic_count"] = len(longbridge_topics)
        source_health["longbridge_topic_source"] = "longbridge"
        payload["source_health"] = source_health
    longbridge_filings = [row for row in safe_list(package.get("longbridge_filings")) if isinstance(row, dict)]
    if longbridge_filings:
        existing_filings = [row for row in safe_list(payload.get("filings")) if isinstance(row, dict)]
        payload["filings"] = existing_filings + longbridge_filings
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["longbridge_filing_count"] = len(longbridge_filings)
        source_health["longbridge_filing_source"] = "longbridge"
        payload["source_health"] = source_health
    longbridge_ownership_records: list[dict[str, Any]] = []
    for key in ("longbridge_shareholders", "longbridge_fund_holders", "longbridge_insider_trades"):
        longbridge_ownership_records.extend(row for row in safe_list(package.get(key)) if isinstance(row, dict))
    if longbridge_ownership_records:
        ownership = dict(safe_dict(payload.get("ownership")))
        ownership["records"] = [
            *[row for row in safe_list(ownership.get("records")) if isinstance(row, dict)],
            *longbridge_ownership_records,
        ]
        payload["ownership"] = ownership
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["longbridge_ownership_record_count"] = len(longbridge_ownership_records)
        source_health["longbridge_ownership_source"] = "longbridge"
        payload["source_health"] = source_health
    longbridge_short_positions = [row for row in safe_list(package.get("longbridge_short_positions")) if isinstance(row, dict)]
    if longbridge_short_positions:
        existing_positioning_flows = [row for row in safe_list(payload.get("positioning_flows")) if isinstance(row, dict)]
        payload["positioning_flows"] = existing_positioning_flows + longbridge_short_positions
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["longbridge_short_position_count"] = len(longbridge_short_positions)
        source_health["longbridge_short_position_source"] = "longbridge"
        payload["source_health"] = source_health
    longbridge_financial_reports = [row for row in safe_list(package.get("longbridge_financial_reports")) if isinstance(row, dict)]
    longbridge_operating_reviews = [row for row in safe_list(package.get("longbridge_operating_reviews")) if isinstance(row, dict)]
    if longbridge_financial_reports or longbridge_operating_reviews:
        fundamentals = dict(safe_dict(payload.get("fundamentals")))
        if longbridge_financial_reports:
            fundamentals["financial_reports"] = [
                *[row for row in safe_list(fundamentals.get("financial_reports")) if isinstance(row, dict)],
                *longbridge_financial_reports,
            ]
        if longbridge_operating_reviews:
            fundamentals["operating_reviews"] = [
                *[row for row in safe_list(fundamentals.get("operating_reviews")) if isinstance(row, dict)],
                *longbridge_operating_reviews,
            ]
        payload["fundamentals"] = fundamentals
        source_health = dict(safe_dict(payload.get("source_health")))
        if longbridge_financial_reports:
            source_health["longbridge_financial_report_count"] = len(longbridge_financial_reports)
            source_health["longbridge_financial_report_source"] = "longbridge"
        if longbridge_operating_reviews:
            source_health["longbridge_operating_review_count"] = len(longbridge_operating_reviews)
            source_health["longbridge_operating_review_source"] = "longbridge"
        payload["source_health"] = source_health
    longbridge_industry_valuation = [
        row for row in safe_list(package.get("longbridge_industry_valuation")) if isinstance(row, dict)
    ]
    if longbridge_industry_valuation:
        existing_industry_valuation = [row for row in safe_list(payload.get("industry_valuation")) if isinstance(row, dict)]
        payload["industry_valuation"] = existing_industry_valuation + longbridge_industry_valuation
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["longbridge_industry_valuation_count"] = len(longbridge_industry_valuation)
        source_health["longbridge_industry_valuation_source"] = "longbridge"
        payload["source_health"] = source_health
    if isinstance(postclose_review_result, dict):
        payload["postclose_review"] = postclose_review_result
    elif isinstance(package.get("postclose_review"), dict):
        payload["postclose_review"] = package["postclose_review"]
    postclose_actuals, postclose_validation = build_postclose_validation_evidence(safe_dict(payload.get("postclose_review")))
    if postclose_actuals:
        existing_actuals = [row for row in safe_list(payload.get("actuals")) if isinstance(row, dict)]
        payload["actuals"] = existing_actuals + postclose_actuals
        validations = [row for row in safe_list(payload.get("validations")) if isinstance(row, dict)]
        if postclose_validation:
            validations.append(postclose_validation)
            if not isinstance(payload.get("recent_validation"), dict):
                payload["recent_validation"] = postclose_validation
        if validations:
            payload["validations"] = validations
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["postclose_validation_actual_count"] = len(postclose_actuals)
        source_health["postclose_validation_source"] = "postclose_review"
        payload["source_health"] = source_health
    if isinstance(package.get("postclose_observation_layer"), dict):
        payload["postclose_observation_layer"] = package["postclose_observation_layer"]
    derived_volume_anomalies = build_volume_anomaly_evidence_from_shortlist(shortlist_result)
    if derived_volume_anomalies:
        existing_volume_anomalies = [row for row in safe_list(payload.get("volume_anomaly")) if isinstance(row, dict)]
        payload["volume_anomaly"] = existing_volume_anomalies + derived_volume_anomalies
    longbridge_expectation_rows = build_longbridge_expectation_evidence_rows(package)
    loaded_longbridge_sources = package_has_loaded_longbridge_source_artifacts(package)
    filtered_external_evidence = [
        row
        for row in (institutional_evidence_payloads or [])
        if isinstance(row, dict)
        and not (loaded_longbridge_sources and is_longbridge_aggregate_evidence_payload(row))
    ]
    evidence_rows = [row for row in [*filtered_external_evidence, *longbridge_expectation_rows] if isinstance(row, dict)]
    if evidence_rows:
        try:
            from institutional_signal_audit import merge_external_evidence
        except ModuleNotFoundError:
            payload["external_evidence"] = evidence_rows
            source_health = dict(safe_dict(payload.get("source_health")))
            source_health["external_evidence_count"] = len(evidence_rows)
            payload["source_health"] = source_health
        else:
            payload = merge_external_evidence(payload, evidence_rows)
    if longbridge_expectation_rows:
        source_health = dict(safe_dict(payload.get("source_health")))
        source_health["longbridge_expectation_source_count"] = len(longbridge_expectation_rows)
        source_health["longbridge_expectation_source_kinds"] = sorted(
            {
                clean_text(row.get("source_kind"))
                for row in longbridge_expectation_rows
                if clean_text(row.get("source_kind"))
            }
        )
        payload["source_health"] = source_health
    return payload


def render_institutional_signal_audit_markdown(audit: dict[str, Any]) -> str:
    try:
        from institutional_signal_audit import render_markdown_report
    except ModuleNotFoundError:
        return json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
    return str(render_markdown_report(audit))


def audit_upgrade_priority_ids(audit: dict[str, Any]) -> set[str]:
    priorities = audit.get("upgrade_priorities")
    return {
        clean_text(row.get("id"))
        for row in (priorities if isinstance(priorities, list) else [])
        if isinstance(row, dict) and clean_text(row.get("id"))
    }


__all__ = [
    "audit_upgrade_priority_ids",
    "build_institutional_signal_audit_payload",
    "build_longbridge_capital_flow_rows",
    "build_longbridge_expectation_evidence_rows",
    "build_postclose_validation_evidence",
    "build_volume_anomaly_evidence_from_shortlist",
    "render_institutional_signal_audit_markdown",
]
