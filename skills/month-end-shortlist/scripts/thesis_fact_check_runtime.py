#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from typing import Any

from local_stock_pool_runtime import clean_string_list, clean_text
from manager_html_primitives import safe_dict, safe_list
from manager_pool_merge import normalize_workflow_display_ticker


THESIS_STATUS_BLOCKING = {"weak", "contradicted", "not_found"}
CHAIN_POSITION_BLOCKING = {"concept_only", "false_positive"}
TRADING_CONCLUSION_BLOCKING = {"block_entry", "remove"}
DEFAULT_TRANSFORMER_EVIDENCE_KEYS = ("海外产能", "北美订单", "数据中心客户", "出口收入占比", "关税规避能力")
NEGATION_MARKERS = ("不涉及", "无相关", "未涉及", "没有相关", "否认", "没有披露", "未披露", "未提供")


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in ("", None, [], {})}


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", [], {}):
        return []
    return value if isinstance(value, list) else [value]


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = clean_text(value)
        return [text] if text else []
    return clean_string_list(value)


def _walk_dict_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        rows.append(value)
        for nested in value.values():
            rows.extend(_walk_dict_rows(nested))
    elif isinstance(value, list):
        for item in value:
            rows.extend(_walk_dict_rows(item))
    return rows


def _evidence_rows(evidence_payloads: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in evidence_payloads or []:
        if isinstance(payload, dict):
            rows.extend(_walk_dict_rows(payload))
    return rows


def _row_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in row.items():
        if isinstance(value, (dict, list)):
            continue
        text = clean_text(value)
        if text:
            parts.append(text)
    return " ".join(parts)


def _source_url(row: dict[str, Any]) -> str:
    return clean_text(row.get("url") or row.get("source_url") or row.get("link") or row.get("href"))


def _source_type(row: dict[str, Any]) -> str:
    explicit = clean_text(row.get("source_type") or row.get("source_kind") or row.get("provider"))
    if explicit:
        return explicit
    source_text = " ".join(
        clean_text(row.get(key))
        for key in ("source", "source_name", "source_path", "url", "source_url", "link")
    ).lower()
    if "longbridge" in source_text:
        return "longbridge"
    if "eastmoney" in source_text or "eastmoney" in _source_url(row).lower():
        return "eastmoney"
    if "annual" in source_text or "年报" in source_text:
        return "annual_report"
    if "investor" in source_text or "互动易" in source_text:
        return "investor_qna"
    if "web" in source_text or "search" in source_text:
        return "web_search"
    return clean_text(row.get("source")) or "unknown"


def _source_tier(row: dict[str, Any]) -> str:
    explicit = clean_text(row.get("source_tier") or row.get("evidence_tier"))
    if explicit:
        return explicit
    source_type = _source_type(row).lower()
    if source_type.startswith("longbridge") or "eastmoney" in source_type or "institutional" in source_type:
        return "repo_native"
    if source_type in {"annual_report", "semiannual_report", "investor_qna", "announcement"}:
        return "company_disclosure"
    if "web_search" in source_type or source_type == "web":
        return "web_search"
    return "unclassified"


def _evidence_source(row: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "source_tier": _source_tier(row),
            "source_type": _source_type(row),
            "title": clean_text(row.get("title") or row.get("headline") or row.get("name")),
            "url": _source_url(row),
        }
    )


def _matching_evidence(rows: list[dict[str, Any]], terms: list[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    lowered_terms = [term.lower() for term in terms if clean_text(term)]
    if not lowered_terms:
        return matches
    for row in rows:
        text = _row_text(row)
        lowered = text.lower()
        if any(term in lowered and not _term_is_negated(lowered, term) for term in lowered_terms):
            matches.append(row)
    return matches


def _term_is_negated(text: str, term: str) -> bool:
    separators = "。；;，,\n\r"
    clauses = [text]
    for separator in separators:
        clauses = [part for clause in clauses for part in clause.split(separator)]
    normalized_term = term.lower().replace(" ", "")
    for clause in clauses:
        normalized_clause = clause.lower().replace(" ", "")
        if normalized_term not in normalized_clause:
            continue
        term_index = normalized_clause.find(normalized_term)
        prefix = normalized_clause[:term_index]
        if any(marker.lower().replace(" ", "") in prefix for marker in NEGATION_MARKERS):
            return True
    return False


def _claim(
    claim_text: str,
    *,
    verdict: str,
    evidence_rows: list[dict[str, Any]] | None = None,
    missing_evidence: list[str] | None = None,
    contradiction: str = "",
    confidence: float = 0.0,
) -> dict[str, Any]:
    evidence_rows = evidence_rows or []
    return {
        "claim_text": claim_text,
        "verdict": verdict,
        "evidence": [_row_text(row) for row in evidence_rows[:3] if _row_text(row)],
        "missing_evidence": missing_evidence or [],
        "contradiction": contradiction,
        "source_urls": [url for url in (_source_url(row) for row in evidence_rows[:5]) if url],
        "evidence_sources": [_evidence_source(row) for row in evidence_rows[:5] if _evidence_source(row)],
        "confidence": confidence,
    }


def _peer_comparison(thesis: str, name: str) -> dict[str, list[str]]:
    if "变压器" in thesis or "缺电" in thesis or "数据中心" in thesis:
        concept = [name] if name else []
        return {
            "core_beneficiary": ["金盘科技", "思源电气"],
            "second_tier": ["伊戈尔"],
            "concept_only": concept,
            "false_positive": [],
        }
    return {
        "core_beneficiary": [],
        "second_tier": [],
        "concept_only": [name] if name else [],
        "false_positive": [],
    }


def _extract_expected_evidence(payload: dict[str, Any]) -> list[str]:
    values = payload.get("expected_evidence") or payload.get("required_evidence") or payload.get("evidence_points")
    return _as_text_list(values)


def _build_single_check(payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    ticker = normalize_workflow_display_ticker(payload.get("ticker") or payload.get("symbol") or payload.get("code"))
    name = clean_text(payload.get("name") or payload.get("company_name"))
    thesis = clean_text(payload.get("thesis") or payload.get("logic") or payload.get("investment_logic"))
    expected = _extract_expected_evidence(payload)
    identity_terms = [term for term in (ticker, name) if term]
    scoped_rows = rows
    identity_matches = _matching_evidence(rows, identity_terms)
    if identity_matches:
        scoped_rows = identity_matches

    business_terms = [name, ticker, "变压器", "输变电", "电力设备"]
    business_matches = _matching_evidence(scoped_rows, business_terms)
    contradiction_matches = _matching_evidence(scoped_rows, ["不涉及", "无相关", "未涉及", "没有相关", "否认"])

    claims: list[dict[str, Any]] = []
    business_verdict = "confirmed" if business_matches else "not_found"
    claims.append(
        _claim(
            "公司是否有相关业务",
            verdict=business_verdict,
            evidence_rows=business_matches,
            missing_evidence=[] if business_matches else ["相关业务证据"],
            contradiction=_row_text(contradiction_matches[0]) if contradiction_matches else "",
            confidence=0.75 if business_matches else 0.2,
        )
    )

    evidence_claim_terms = {
        "海外产能": ["海外产能", "美国工厂", "墨西哥", "海外基地", "北美产能"],
        "北美订单": ["北美订单", "美国订单", "北美客户", "海外订单"],
        "数据中心客户": ["数据中心客户", "AI 数据中心", "北美数据中心", "数据中心订单"],
        "出口收入占比": ["出口收入", "海外收入", "外销", "境外收入", "收入占比"],
        "关税规避能力": ["关税规避", "海外制造", "原产地", "墨西哥产能", "美国本土产能"],
    }
    expected_keys = list(dict.fromkeys(expected or DEFAULT_TRANSFORMER_EVIDENCE_KEYS))

    missing_evidence: list[str] = []
    hard_confirmed_count = 0
    for expected_key in expected_keys:
        terms = evidence_claim_terms.get(expected_key, [expected_key])
        matches = _matching_evidence(scoped_rows, terms)
        verdict = "confirmed" if matches else "not_found"
        if matches:
            hard_confirmed_count += 1
        else:
            missing_evidence.append(expected_key)
        claims.append(
            _claim(
                expected_key,
                verdict=verdict,
                evidence_rows=matches,
                missing_evidence=[] if matches else [expected_key],
                confidence=0.8 if matches else 0.25,
            )
        )

    peer = _peer_comparison(thesis, name)
    if contradiction_matches:
        logic_existence = "contradicted"
        chain_position = "false_positive"
        trading_conclusion = "remove"
    elif business_matches and hard_confirmed_count == 0:
        logic_existence = "weak"
        chain_position = "concept_only"
        trading_conclusion = "block_entry"
    elif business_matches and hard_confirmed_count < max(1, len(expected)):
        logic_existence = "partial"
        chain_position = "second_tier"
        trading_conclusion = "watch_only"
    elif business_matches:
        logic_existence = "confirmed"
        chain_position = "core_beneficiary"
        trading_conclusion = "allow_entry"
    else:
        logic_existence = "weak"
        chain_position = "concept_only"
        trading_conclusion = "block_entry"

    claims.append(
        _claim(
            "是否只是概念映射且弱于同逻辑核心标的",
            verdict="confirmed" if chain_position in {"concept_only", "false_positive"} else "partial",
            evidence_rows=business_matches,
            missing_evidence=missing_evidence,
            contradiction="",
            confidence=0.7 if chain_position == "concept_only" else 0.5,
        )
    )

    return {
        "ticker": ticker,
        "name": name,
        "thesis": thesis,
        "logic_existence": logic_existence,
        "chain_position": chain_position,
        "missing_evidence": list(dict.fromkeys(missing_evidence)),
        "trading_conclusion": trading_conclusion,
        "peer_comparison": peer,
        "claims": claims,
    }


def build_thesis_fact_check(
    thesis_payloads: list[dict[str, Any]] | dict[str, Any],
    *,
    evidence_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload_rows = [row for row in _as_list(thesis_payloads) if isinstance(row, dict)]
    rows = _evidence_rows(evidence_payloads)
    checks = [_build_single_check(payload, rows) for payload in payload_rows]
    blocking_count = sum(
        1
        for check in checks
        if clean_text(check.get("logic_existence")) in THESIS_STATUS_BLOCKING
        or clean_text(check.get("chain_position")) in CHAIN_POSITION_BLOCKING
        or clean_text(check.get("trading_conclusion")) in TRADING_CONCLUSION_BLOCKING
    )
    status = "blocked" if blocking_count else "pass" if checks else "empty"
    return {
        "schema_version": "thesis_fact_check/v1",
        "status": status,
        "summary": {
            "check_count": len(checks),
            "blocked_count": blocking_count,
            "watch_only_count": sum(1 for check in checks if check.get("trading_conclusion") == "watch_only"),
            "allow_entry_count": sum(1 for check in checks if check.get("trading_conclusion") == "allow_entry"),
        },
        "checks": checks,
    }


def render_thesis_fact_check_markdown(result: dict[str, Any]) -> str:
    lines = ["# Thesis Fact Check", ""]
    lines.append(f"- status: `{clean_text(result.get('status'))}`")
    for check in safe_list(result.get("checks")):
        if not isinstance(check, dict):
            continue
        identity = " ".join(part for part in (clean_text(check.get("ticker")), clean_text(check.get("name"))) if part)
        lines.extend(
            [
                "",
                f"## {identity or 'thesis'}",
                "",
                f"- thesis: {clean_text(check.get('thesis'))}",
                f"- logic_existence: `{clean_text(check.get('logic_existence'))}`",
                f"- chain_position: `{clean_text(check.get('chain_position'))}`",
                f"- trading_conclusion: `{clean_text(check.get('trading_conclusion'))}`",
                f"- missing_evidence: {', '.join(clean_string_list(check.get('missing_evidence'))) or 'none'}",
                "",
                "### Peer comparison",
            ]
        )
        peer = safe_dict(check.get("peer_comparison"))
        for key in ("core_beneficiary", "second_tier", "concept_only", "false_positive"):
            lines.append(f"- {key}: {', '.join(clean_string_list(peer.get(key))) or 'none'}")
        lines.extend(["", "### Claims"])
        for claim in safe_list(check.get("claims")):
            if not isinstance(claim, dict):
                continue
            lines.append(
                "- claim_text: "
                f"{clean_text(claim.get('claim_text'))} | verdict: `{clean_text(claim.get('verdict'))}` | "
                f"missing: {', '.join(clean_string_list(claim.get('missing_evidence'))) or 'none'}"
            )
    return "\n".join(lines).rstrip() + "\n"


def _status_class(status: str) -> str:
    if status in {"pass", "confirmed"}:
        return "covered"
    if status in {"blocked", "block_entry", "remove", "weak", "contradicted", "not_found"}:
        return "blocked"
    return "pending"


def render_thesis_fact_check_status(package: dict[str, Any]) -> str:
    result = safe_dict(package.get("thesis_fact_check"))
    if not result:
        return ""
    status = clean_text(result.get("status")) or "blocked"
    summary = safe_dict(result.get("summary"))
    rows: list[str] = []
    for check in safe_list(result.get("checks"))[:6]:
        if not isinstance(check, dict):
            continue
        identity = " ".join(part for part in (clean_text(check.get("ticker")), clean_text(check.get("name"))) if part)
        conclusion = clean_text(check.get("trading_conclusion"))
        chain_position = clean_text(check.get("chain_position"))
        missing = ", ".join(clean_string_list(check.get("missing_evidence"))) or "none"
        peer = safe_dict(check.get("peer_comparison"))
        peer_text = ", ".join(clean_string_list(peer.get("core_beneficiary")) + clean_string_list(peer.get("second_tier")))
        rows.append(
            '<div class="source-status-item thesis-fact-check-item">'
            '<div class="source-status-copy">'
            f'<span class="overview-ticker">{html.escape(clean_text(check.get("ticker")) or "thesis")}</span>'
            f'<span class="overview-name">{html.escape(identity or clean_text(check.get("thesis")) or "thesis")}</span>'
            "</div>"
            f'<span class="status-pill status-{html.escape(_status_class(conclusion))}">{html.escape(conclusion or status)}</span>'
            f'<span class="bucket-pill">{html.escape(chain_position)}</span>'
            f'<span class="metric-label">missing {html.escape(missing)} | peers {html.escape(peer_text or "none")}</span>'
            "</div>"
        )
    return (
        '<section id="thesis-fact-check" class="thesis-fact-check-status" aria-label="Logic fact check status">'
        '<div class="section-head">'
        "<h2>Logic Fact Check</h2>"
        f'<span class="status-pill status-{html.escape(_status_class(status))}">{html.escape(status)}</span>'
        "</div>"
        '<div class="source-status-body">'
        "<p>Investment theses are checked against hard company evidence before entry-list promotion.</p>"
        '<div class="coverage-metrics">'
        f'<div><span class="metric-value">{html.escape(clean_text(summary.get("check_count")) or "0")}</span><span class="metric-label">Checks</span></div>'
        f'<div><span class="metric-value">{html.escape(clean_text(summary.get("blocked_count")) or "0")}</span><span class="metric-label">Blocked</span></div>'
        f'<div><span class="metric-value">{html.escape(clean_text(summary.get("watch_only_count")) or "0")}</span><span class="metric-label">Watch only</span></div>'
        "</div>"
        '<div class="source-status-list thesis-fact-check-list">'
        + "".join(rows)
        + "</div>"
        "</div>"
        "</section>"
    )


__all__ = [
    "build_thesis_fact_check",
    "render_thesis_fact_check_markdown",
    "render_thesis_fact_check_status",
]
