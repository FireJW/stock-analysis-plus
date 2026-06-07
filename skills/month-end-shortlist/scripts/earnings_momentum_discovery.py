#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


SOURCE_ROLE_MAP = {
    "official_filing": "official_filing_reference",
    "company_response": "company_response_reference",
    "x_summary": "summary_or_relay",
    "x_thread": "personal_thesis",
    "market_rumor": "market_rumor",
    "xueqiu_summary": "summary_or_relay",
    "community_post": "personal_thesis",
}
CODE_PATTERN = re.compile(r"(?P<name>[\u4e00-\u9fffA-Za-z0-9]+)\((?P<code>\d{6})\)")
ADVISORY_SIGNAL_EVIDENCE_BOUNDARY = [
    "not_fact_evidence",
    "not_hard_filter",
    "not_direct_trade_recommendation",
    "requires_longbridge_eastmoney_sina_filing_research_validation",
]
ADVISORY_SIGNAL_VALIDATION_NOTE = (
    "Hot X/Grok/research summaries are qualitative clues only; verify facts, fundamentals, "
    "and price data with Longbridge/Eastmoney/Sina/filings/research before use."
)
RESPONSE_CONFIRM_KEYWORDS = ("确认", "证实", "属实", "已签", "confirm", "confirmed")
RESPONSE_DENY_KEYWORDS = ("否认", "不属实", "不实", "谣言", "澄清", "denied", "false")
RESPONSE_AMBIGUOUS_KEYWORDS = ("不予置评", "以公告为准", "无法评论", "适时披露", "no comment")


SCHEDULE_ONLY_KEYWORDS = ("披露时间", "预约披露", "提前至", "将于", "定于", "预约日期")
POSITIVE_EXPECTATION_KEYWORDS = ("超预期", "大超预期", "明显超预期", "很硬", "强劲", "弹性最大", "价格可能上行", "涨价", "景气", "环比增长", "稳中有升", "放量攀升")
NEGATIVE_EXPECTATION_KEYWORDS = ("不及预期", "低于预期", "承压", "利空", "弱于预期", "低于一致预期")
METRIC_PATTERN = re.compile(r"(?:\d+(?:\.\d+)?(?:%|x|X|GW|G|T|亿|亿元|万亿|万颗|万台|倍|万亿Token)|Q\d|\d+月\d+日)")
TRADING_PROFILE_BUCKETS = (
    "稳健核心",
    "高弹性",
    "补涨候选",
    "预期差最大",
    "兑现风险最高",
)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def to_int_safe(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float_safe(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_source_role(source_type: str) -> str:
    return SOURCE_ROLE_MAP.get(clean_text(source_type), "personal_thesis")


def normalize_event_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    sources = deepcopy(raw.get("sources") or [])
    candidate = {
        "ticker": clean_text(raw.get("ticker")),
        "name": clean_text(raw.get("name")) or clean_text(raw.get("ticker")),
        "event_type": clean_text(raw.get("event_type")),
        "event_strength": clean_text(raw.get("event_strength")) or "medium",
        "chain_name": clean_text(raw.get("chain_name")) or "unknown",
        "chain_role": clean_text(raw.get("chain_role")) or "unknown",
        "benefit_type": clean_text(raw.get("benefit_type")) or "mapping",
        "sources": sources,
        "source_roles": [normalize_source_role(item.get("source_type")) for item in sources if isinstance(item, dict)],
        "market_validation": deepcopy(raw.get("market_validation") or {}),
        "peer_tier_1": [clean_text(item) for item in raw.get("peer_tier_1", []) if clean_text(item)],
        "peer_tier_2": [clean_text(item) for item in raw.get("peer_tier_2", []) if clean_text(item)],
        "leaders": [clean_text(item) for item in raw.get("leaders", []) if clean_text(item)],
        "advisory_only": bool(raw.get("advisory_only")),
        "qualitative_reference_only": bool(raw.get("qualitative_reference_only")),
        "evidence_boundary": [clean_text(item) for item in raw.get("evidence_boundary", []) if clean_text(item)],
        "validation_note": clean_text(raw.get("validation_note")),
        "excluded_candidate_names": [clean_text(item) for item in raw.get("excluded_candidate_names", []) if clean_text(item)],
        "exclusion_reasons": [clean_text(item) for item in raw.get("exclusion_reasons", []) if clean_text(item)],
        "mapping_chain_role": clean_text(raw.get("mapping_chain_role")),
        "relevance_basis": clean_text(raw.get("relevance_basis")),
        "required_evidence": [clean_text(item) for item in raw.get("required_evidence", []) if clean_text(item)],
        "mismatch_risks": [clean_text(item) for item in raw.get("mismatch_risks", []) if clean_text(item)],
    }
    return candidate


def compute_rumor_confidence_range(candidate: dict[str, Any]) -> dict[str, Any]:
    roles = set(candidate.get("source_roles") or [])
    state = classify_event_state(candidate)
    if state["label"] == "response_denied":
        return {"label": "low", "range": [10, 25]}
    if state["label"] in {"official_confirmed", "response_confirmed"}:
        return {"label": "high", "range": [80, 90]}
    if state["label"] == "response_ambiguous":
        return {"label": "medium_high", "range": [55, 75]}
    if "market_rumor" in roles:
        return {"label": "medium", "range": [40, 65]}
    return {"label": "low", "range": [20, 40]}


def classify_market_validation(candidate: dict[str, Any]) -> dict[str, Any]:
    data = candidate.get("market_validation") if isinstance(candidate.get("market_validation"), dict) else {}
    score = 0
    if to_float_safe(data.get("volume_multiple_5d")) >= 1.5:
        score += 1
    if bool(data.get("breakout")):
        score += 1
    if clean_text(data.get("relative_strength")).lower() == "strong":
        score += 1
    if bool(data.get("chain_resonance")):
        score += 1

    if score >= 3:
        return {"label": "strong", "summary": "强资金先行，存在提前进场迹象。"}
    if score >= 2:
        return {"label": "medium", "summary": "中等资金先行，已有部分提前验证。"}
    return {"label": "weak", "summary": "弱资金先行，仍需更多量价确认。"}


def assign_discovery_bucket(candidate: dict[str, Any]) -> str:
    if bool(candidate.get("advisory_only")) or bool(candidate.get("qualitative_reference_only")):
        return "track"
    confidence = compute_rumor_confidence_range(candidate)
    validation = classify_market_validation(candidate)
    state = classify_event_state(candidate)
    if state["label"] == "response_denied":
        return "track"
    if clean_text(candidate.get("event_type")).lower() == "rumor" and state["label"] not in {"response_confirmed", "official_confirmed"}:
        return "watch"
    if (
        clean_text(candidate.get("event_strength")).lower() == "strong"
        and validation["label"] in {"strong", "medium"}
        and confidence["label"] in {"medium", "medium_high", "high"}
    ):
        return "qualified"
    return "watch"


def detect_response_signal(text: str) -> str:
    normalized = clean_text(text)
    if any(keyword in normalized for keyword in RESPONSE_DENY_KEYWORDS):
        return "deny"
    if any(keyword in normalized for keyword in RESPONSE_CONFIRM_KEYWORDS):
        return "confirm"
    if any(keyword in normalized for keyword in RESPONSE_AMBIGUOUS_KEYWORDS):
        return "ambiguous"
    return ""


def classify_event_state(candidate: dict[str, Any]) -> dict[str, Any]:
    sources = candidate.get("sources") if isinstance(candidate.get("sources"), list) else []
    has_official_filing = False
    seen_signals: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_type = clean_text(source.get("source_type"))
        if source_type == "official_filing":
            has_official_filing = True
        summary = clean_text(source.get("summary"))
        response_signal = clean_text(source.get("response_signal")) or detect_response_signal(summary)
        if response_signal:
            seen_signals.add(response_signal)

    if has_official_filing:
        return {"label": "official_confirmed"}
    if "deny" in seen_signals:
        return {"label": "response_denied"}
    if "confirm" in seen_signals:
        return {"label": "response_confirmed"}
    if "ambiguous" in seen_signals:
        return {"label": "response_ambiguous"}
    if clean_text(candidate.get("event_type")).lower() == "rumor":
        return {"label": "rumor_unconfirmed"}
    return {"label": "unconfirmed"}


def classify_trading_usability(candidate: dict[str, Any]) -> dict[str, Any]:
    state = classify_event_state(candidate)
    validation = classify_market_validation(candidate)
    if state["label"] == "response_denied":
        return {"label": "low", "summary": "交易可用性低，优先等待进一步证据或回避。"}
    if state["label"] in {"official_confirmed", "response_confirmed"} and validation["label"] == "strong":
        return {"label": "high", "summary": "交易可用性高，已具备升级为执行判断的基础。"}
    if state["label"] in {"official_confirmed", "response_confirmed"}:
        return {"label": "medium", "summary": "交易可用性中等，事件已确认但仍需进一步量价确认。"}
    if validation["label"] == "strong":
        return {"label": "medium", "summary": "交易可用性中等，可作为重点观察对象。"}
    return {"label": "low", "summary": "交易可用性偏低，更多是线索而非执行依据。"}


def _event_type_priority(value: str) -> tuple[int, str]:
    normalized = clean_text(value)
    priorities = {
        "annual_report_preview": 0,
        "quarterly_preview": 1,
        "earnings": 2,
        "company_event": 3,
        "structured_catalyst": 4,
        "x_logic_signal": 5,
        "rumor": 6,
    }
    return (priorities.get(normalized, 99), normalized)


def _chain_role_priority(value: str) -> tuple[int, str]:
    normalized = clean_text(value)
    priorities = {
        "upstream_material": 0,
        "midstream_manufacturing": 1,
        "downstream_brand": 2,
        "direct_pick": 3,
        "theme_basket": 4,
        "logic_support": 5,
        "quote_only": 6,
    }
    return (priorities.get(normalized, 99), normalized)


def _benefit_type_priority(value: str) -> tuple[int, str]:
    normalized = clean_text(value)
    priorities = {
        "direct": 0,
        "mapping": 1,
    }
    return (priorities.get(normalized, 99), normalized)


def _state_priority(value: str) -> int:
    return {
        "response_denied": 0,
        "official_confirmed": 1,
        "response_confirmed": 2,
        "response_ambiguous": 3,
        "rumor_unconfirmed": 4,
        "unconfirmed": 5,
    }.get(clean_text(value), 99)


def compute_event_priority_score(candidate: dict[str, Any]) -> int:
    state = classify_event_state(candidate)
    usability = classify_trading_usability(candidate)
    validation = classify_market_validation(candidate)
    source_roles = set(candidate.get("source_roles") or [])
    score = 0
    if state["label"] == "official_confirmed":
        score += 40
    elif state["label"] == "response_confirmed":
        score += 30
    elif state["label"] == "response_ambiguous":
        score += 20
    elif state["label"] == "rumor_unconfirmed":
        score += 10
    if usability["label"] == "high":
        score += 25
    elif usability["label"] == "medium":
        score += 15
    if validation["label"] == "strong":
        score += 20
    elif validation["label"] == "medium":
        score += 10
    if "official_filing_reference" in source_roles:
        score += 10
    if "summary_or_relay" in source_roles or "personal_thesis" in source_roles:
        score += 5
    return score


def build_evidence_mix(sources: list[dict[str, Any]]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_type = clean_text(source.get("source_type")) or "unknown"
        mix[source_type] = mix.get(source_type, 0) + 1
    return mix


def collect_source_urls(sources: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("status_url", "url", "source_url"):
            url = clean_text(source.get(key))
            if url and url not in urls:
                urls.append(url)
    return urls


def build_key_evidence(sources: list[dict[str, Any]], *, limit: int = 4) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_type = clean_text(source.get("source_type")) or "unknown"
        account = clean_text(source.get("account"))
        date = clean_text(source.get("date") or source.get("published_at"))[:10]
        text = clean_text(source.get("evidence_excerpt")) or clean_text(source.get("summary")) or clean_text(source.get("quoted_text"))
        if not text:
            continue
        if len(text) > 120:
            text = text[:117].rstrip() + "..."
        prefix = [source_type]
        if account:
            prefix.append(account)
        if date:
            prefix.append(date)
        bullet = f"[{' | '.join(prefix)}] {text}"
        if bullet in seen:
            continue
        seen.add(bullet)
        bullets.append(bullet)
        if len(bullets) >= limit:
            break
    return bullets


def build_market_signal_summary(candidate: dict[str, Any]) -> str:
    data = candidate.get("market_validation") if isinstance(candidate.get("market_validation"), dict) else {}
    volume_multiple = to_float_safe(data.get("volume_multiple_5d"))
    breakout = "yes" if bool(data.get("breakout")) else "no"
    relative_strength = clean_text(data.get("relative_strength")) or "unknown"
    chain_resonance = "yes" if bool(data.get("chain_resonance")) else "no"
    return (
        f"volume_5d={volume_multiple:.1f}x; breakout={breakout}; "
        f"rs={relative_strength}; chain_resonance={chain_resonance}"
    )


def build_chain_path_summary(candidate: dict[str, Any]) -> str:
    return (
        f"{clean_text(candidate.get('chain_name')) or 'unknown'} / "
        f"{clean_text(candidate.get('chain_role')) or 'unknown'} / "
        f"{clean_text(candidate.get('benefit_type')) or 'mapping'}"
    )


def extract_headline_metrics(sources: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    metrics: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        text = clean_text(source.get("summary")) or clean_text(source.get("evidence_excerpt")) or clean_text(source.get("quoted_text"))
        if not text:
            continue
        for match in METRIC_PATTERN.finditer(text):
            snippet = clean_text(match.group(0))
            if snippet and snippet not in seen:
                seen.add(snippet)
                metrics.append(snippet)
            if len(metrics) >= limit:
                return metrics
    return metrics


def classify_event_phase(candidate: dict[str, Any]) -> str:
    sources = candidate.get("sources") if isinstance(candidate.get("sources"), list) else []
    joined = " ".join(clean_text(item.get("summary")) for item in sources if isinstance(item, dict))
    if clean_text(candidate.get("event_type")).lower() == "rumor":
        return "传闻博弈"
    if any(keyword in joined for keyword in SCHEDULE_ONLY_KEYWORDS):
        return "预期交易"
    if any(item.get("source_type") == "official_filing" for item in sources if isinstance(item, dict)):
        if clean_text(candidate.get("event_type")).lower() in {"quarterly_preview", "annual_report_preview", "earnings"}:
            return "官方预告"
        return "正式结果"
    return "预期交易"


def classify_expectation_verdict(candidate: dict[str, Any]) -> str:
    sources = candidate.get("sources") if isinstance(candidate.get("sources"), list) else []
    joined = " ".join(clean_text(item.get("summary")) for item in sources if isinstance(item, dict))
    phase = classify_event_phase(candidate)
    if any(keyword in joined for keyword in NEGATIVE_EXPECTATION_KEYWORDS):
        return "不及预期"
    if any(keyword in joined for keyword in POSITIVE_EXPECTATION_KEYWORDS):
        if phase == "预期交易":
            return "市场押注超预期"
        return "超预期"
    if phase == "预期交易":
        return "暂无一致预期"
    return "符合预期"


def build_community_reaction_summary(candidate: dict[str, Any]) -> str:
    sources = candidate.get("sources") if isinstance(candidate.get("sources"), list) else []
    named_accounts = sorted(
        {
            clean_text(item.get("account"))
            for item in sources
            if isinstance(item, dict) and clean_text(item.get("account"))
        }
    )
    account_summary = ", ".join(named_accounts) if named_accounts else "无明确账号"
    verdict = classify_expectation_verdict(candidate)
    validation = classify_market_validation(candidate)["label"]
    return f"{account_summary}；当前社区判断偏 `{verdict}`，量价验证 `{validation}`。"


def classify_community_conviction(candidate: dict[str, Any]) -> str:
    accounts = sorted(
        {
            clean_text(item.get("account"))
            for item in candidate.get("sources", [])
            if isinstance(item, dict) and clean_text(item.get("account"))
        }
    )
    validation = classify_market_validation(candidate)["label"]
    if len(accounts) >= 3 and validation == "strong":
        return "high"
    if len(accounts) >= 2:
        return "medium"
    return "low"


def build_expectation_basis_summary(candidate: dict[str, Any]) -> str:
    text = " ".join(
        clean_text(item.get("summary")) or clean_text(item.get("evidence_excerpt"))
        for item in candidate.get("sources", [])
        if isinstance(item, dict)
    )
    drivers: list[str] = []
    if any(term in text for term in ("800G", "1.6T", "放量攀升", "环比增长")):
        drivers.append("800G/1.6T放量")
    if any(term in text for term in ("毛利率", "硅光", "高端占比", "良率", "稳中有升")):
        drivers.append("毛利率改善")
    if any(term in text for term in ("EML", "缺货", "紧缺", "锁定产能", "涨价")):
        drivers.append("EML紧缺")
    if any(term in text for term in ("9.4GW", "120万亿", "算力租赁", "需求", "上行")):
        drivers.append("需求扩张")
    return "；".join(drivers) if drivers else "暂无清晰预期驱动"


def build_expectation_risk_summary(candidate: dict[str, Any]) -> str:
    verdict = classify_expectation_verdict(candidate)
    if verdict == "市场押注超预期":
        return "若财报兑现弱于这些线索，或者环比/毛利率改善不持续，预期可能快速回吐。"
    if verdict == "暂无一致预期":
        return "当前更偏主题跟踪，若缺少后续数据或新增催化，热度容易下降。"
    if verdict == "不及预期":
        return "若后续没有更强催化或公司修正指引，股价可能继续消化负反馈。"
    return "关注预期兑现节奏与资金是否继续强化主线。"


def build_why_now_summary(candidate: dict[str, Any]) -> str:
    state = classify_event_state(candidate)
    validation = classify_market_validation(candidate)
    accounts = [clean_text(item.get("account")) for item in candidate.get("sources", []) if isinstance(item, dict) and clean_text(item.get("account"))]
    account_text = ", ".join(sorted(set(accounts))) if accounts else "no_named_accounts"
    return (
        f"{state['label']} + {validation['label']} validation"
        f" + accounts[{account_text}]"
    )


def classify_trading_profile(candidate: dict[str, Any]) -> dict[str, str]:
    name = clean_text(candidate.get("name")) or clean_text(candidate.get("ticker"))
    leaders = {clean_text(item) for item in candidate.get("leaders", []) if clean_text(item)}
    peer_tier_1 = {clean_text(item) for item in candidate.get("peer_tier_1", []) if clean_text(item)}
    peer_tier_2 = {clean_text(item) for item in candidate.get("peer_tier_2", []) if clean_text(item)}
    event_state = clean_text((candidate.get("event_state") or {}).get("label"))
    trading_usability = clean_text((candidate.get("trading_usability") or {}).get("label"))
    market_validation = clean_text((candidate.get("market_validation_summary") or {}).get("label"))
    expectation_verdict = clean_text(candidate.get("expectation_verdict"))
    event_phase = clean_text(candidate.get("event_phase"))
    community_conviction = clean_text(candidate.get("community_conviction"))
    benefit_type = clean_text(candidate.get("benefit_type")) or "mapping"
    chain_role = clean_text(candidate.get("chain_role")) or "unknown"
    priority_score = to_int_safe(candidate.get("priority_score"))
    is_core_name = bool(name and (name in leaders or name in peer_tier_1))
    is_secondary_name = bool(name and name in peer_tier_2)

    if event_state == "response_denied":
        return {
            "bucket": "兑现风险最高",
            "subtype": "澄清或证伪后的兑现风险",
            "reason": "公司回应偏否认或澄清，继续交易原有预期的兑现风险最高。",
        }

    if (
        event_phase in {"正式结果", "官方预告"}
        and expectation_verdict in {"超预期", "市场押注超预期"}
        and community_conviction == "high"
        and market_validation == "strong"
        and priority_score >= 90
    ):
        return {
            "bucket": "兑现风险最高",
            "subtype": "拥挤交易后的兑现风险",
            "reason": "正式结果或官方预告已被强势交易，当前更像兑现风险最高的拥挤段。",
        }

    if (
        event_phase in {"正式结果", "官方预告"}
        and event_state in {"official_confirmed", "response_confirmed"}
        and benefit_type == "direct"
        and is_core_name
        and priority_score >= 80
        and expectation_verdict != "暂无一致预期"
    ):
        return {
            "bucket": "兑现风险最高",
            "subtype": "结果落地后的 sell-the-fact 风险",
            "reason": "正式结果或官方预告已落入兑现窗口，作为核心直接受益票更需要防范 sell-the-fact 风险。",
        }

    # --- Path 3b: 预期交易阶段的过度定价风险 ---
    source_accounts = candidate.get("source_accounts") or []
    if not isinstance(source_accounts, list):
        source_accounts = []
    if (
        event_phase == "预期交易"
        and community_conviction == "high"
        and market_validation == "strong"
        and expectation_verdict == "市场押注超预期"
        and len(source_accounts) >= 3
        and priority_score >= 85
    ):
        return {
            "bucket": "兑现风险最高",
            "subtype": "预期交易阶段的过度定价风险",
            "reason": "虽然还没到正式结果，但多个社区声音已经高度一致且量价强势验证，当前更像预期过度定价的兑现窗口。",
        }

    if is_core_name and benefit_type == "direct":
        if trading_usability in {"high", "medium"}:
            return {
                "bucket": "稳健核心",
                "subtype": "核心稳健承载",
                "reason": "位于链条核心且属于直接受益方向，当前更像稳定承载主线预期的核心票。",
            }
        return {
            "bucket": "稳健核心",
            "subtype": "弱验证下的核心锚点",
            "reason": "虽然量价验证还不算充分，但作为链条核心且直接受益的锚点，仍应优先按稳健核心理解。",
        }

    if (
        is_core_name
        and benefit_type != "direct"
        and event_phase == "预期交易"
        and expectation_verdict == "市场押注超预期"
        and trading_usability in {"high", "medium"}
    ):
        return {
            "bucket": "高弹性",
            "subtype": "核心链条攻击性弹性",
            "reason": "处于核心链条但表达更偏攻击性，当前更适合作为高弹性方向而不是稳健承载。",
        }

    # --- Path 6: mapping with strong validation → 高弹性 (new, before old Path 6) ---
    if (
        benefit_type == "mapping"
        and market_validation in {"strong", "medium"}
        and trading_usability in {"high", "medium"}
        and not is_secondary_name
        and chain_role not in {"logic_support", "quote_only"}
    ):
        return {
            "bucket": "高弹性",
            "subtype": "映射受益但验证充分的弹性表达",
            "reason": "虽然属于映射受益，但量价验证和交易可用性已经足够，更像高弹性表达。",
        }

    # --- Path 7: secondary / weak-mapping / logic_support → 补涨候选 ---
    if is_secondary_name or benefit_type == "mapping" or chain_role in {"logic_support", "quote_only"}:
        subtype = "链条扩散补涨"
        if is_core_name:
            subtype = "核心后的轮动补涨"
        return {
            "bucket": "补涨候选",
            "subtype": subtype,
            "reason": "更偏链条扩散或映射受益，当前更适合作为补涨候选跟踪。",
        }

    # --- Path 8: non-core direct with validation → 高弹性 ---
    if (
        benefit_type == "direct"
        and not is_core_name
        and not is_secondary_name
        and market_validation in {"strong", "medium"}
        and trading_usability in {"high", "medium"}
    ):
        subtype = "事件确认后攻击性弹性" if event_phase in {"正式结果", "官方预告"} else "预期博弈型弹性"
        return {
            "bucket": "高弹性",
            "subtype": subtype,
            "reason": "不是最稳的链条核心，但事件和量价都已具备交易性，更像高弹性表达。",
        }

    # --- Path 9: tightened 预期差最大 (all three conditions must hold) ---
    if (
        community_conviction == "low"
        and expectation_verdict == "暂无一致预期"
        and market_validation not in {"strong", "medium"}
    ):
        has_positive_signal = expectation_verdict != "暂无一致预期" or community_conviction != "low"
        evidence = "genuine_gap" if has_positive_signal else "weak_evidence"
        return {
            "bucket": "预期差最大",
            "subtype": "预期尚未充分定价",
            "reason": "市场一致预期尚未完全收敛，当前更像预期差最大的博弈方向。",
            "evidence_strength": evidence,
        }

    # --- Path 10: final fallback → 高弹性 (strong) or 补涨候选 (default) ---
    if market_validation == "strong":
        return {
            "bucket": "高弹性",
            "subtype": "事件确认后攻击性弹性",
            "reason": "当前更适合按弹性表达理解，而不是按静态行业位次理解。",
        }
    return {
        "bucket": "补涨候选",
        "subtype": "证据不足的扩散候选",
        "reason": "当前证据不足以归入更强的交易属性分类，先按补涨候选跟踪。",
    }


def build_trading_profile_playbook(candidate: dict[str, Any]) -> str:
    bucket = clean_text(candidate.get("trading_profile_bucket") or candidate.get("bucket"))
    subtype = clean_text(candidate.get("trading_profile_subtype") or candidate.get("subtype"))
    if bucket == "稳健核心":
        if subtype == "事件确认后攻击性弹性":
            return "打法: 核心身份不变，但更适合按进攻节奏处理，优先等回踩确认后的主动进攻。"
        if subtype == "弱验证下的核心锚点":
            return "打法: 先按核心锚点跟踪，不急追价，等量价确认后再扩大进攻。"
        return "打法: 以核心承载思路看待，优先关注回踩确认和趋势延续。"
    if bucket == "高弹性":
        if subtype == "核心链条攻击性弹性":
            return "打法: 更像核心链条里的攻击性表达，适合顺着主线强化做进攻，而不是当补涨处理。"
        if subtype == "事件确认后攻击性弹性":
            return "打法: 事件已确认，适合按确认后的进攻弹性处理，重点看加速与回踩二选一。"
        return "打法: 偏预期博弈型弹性，适合快进快出和节奏确认，不适合钝化持有。"
    if bucket == "补涨候选":
        if subtype == "核心后的轮动补涨":
            return "打法: 更像核心票后的轮动补涨，优先等主线继续扩散而不是抢先孤立进攻。"
        return "打法: 按链条扩散轮动补涨处理，关注板块共振和后排补涨窗口。"
    if bucket == "兑现风险最高":
        return "打法: 不再按新开仓进攻理解，优先防范 sell-the-fact 和高位兑现。"
    return "打法: 当前更适合按预期差博弈处理，先等市场把预期交易得更清楚。"


def build_trading_profile_judgment(candidate: dict[str, Any]) -> str:
    phase = clean_text(candidate.get("event_phase"))
    verdict = clean_text(candidate.get("expectation_verdict"))
    bucket = clean_text(candidate.get("trading_profile_bucket") or candidate.get("bucket"))
    subtype = clean_text(candidate.get("trading_profile_subtype") or candidate.get("subtype"))
    reason = clean_text(candidate.get("trading_profile_reason") or candidate.get("reason"))

    leading = ""
    if phase and verdict and bucket:
        leading = f"{phase}阶段先按{bucket}处理，当前{verdict}"
    elif bucket and verdict:
        leading = f"当前按{bucket}处理，市场判断偏{verdict}"
    elif bucket:
        leading = f"当前按{bucket}处理"
    elif verdict:
        leading = f"当前市场判断偏{verdict}"

    if subtype and subtype != bucket:
        if leading:
            leading = f"{leading}（{subtype}）"
        else:
            leading = f"当前更像{subtype}"

    clauses = [text for text in [leading, reason] if text]
    if not clauses:
        return "判断: 当前仍以观察预期交易方向为主。"
    return f"判断: {'；'.join(text.rstrip('。') for text in clauses[:2])}。"


def build_trading_profile_usage(candidate: dict[str, Any]) -> str:
    playbook = clean_text(candidate.get("trading_profile_playbook"))
    if not playbook:
        return "用法: 先等市场把预期交易得更清楚，再决定是否进攻。"
    if playbook.startswith("打法:"):
        return f"用法:{playbook[len('打法:'):]}"
    return f"用法: {playbook}"


def build_event_cards(discovery_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred_ticker_by_name: dict[str, str] = {}
    for row in discovery_rows:
        if not isinstance(row, dict):
            continue
        name = clean_text(row.get("name"))
        ticker = clean_text(row.get("ticker"))
        if name and ticker:
            preferred_ticker_by_name.setdefault(name, ticker)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in discovery_rows:
        if not isinstance(row, dict):
            continue
        name = clean_text(row.get("name"))
        ticker = clean_text(row.get("ticker")) or preferred_ticker_by_name.get(name) or name
        if not ticker:
            continue
        grouped.setdefault(ticker, []).append(row)

    cards: list[dict[str, Any]] = []
    for ticker, rows in grouped.items():
        base = deepcopy(rows[0])
        all_sources: list[dict[str, Any]] = []
        all_roles: list[str] = []
        all_accounts: list[str] = []
        event_types: list[str] = []
        chain_names: list[str] = []
        chain_roles: list[str] = []
        benefit_types: list[str] = []
        peer_tier_1: list[str] = []
        peer_tier_2: list[str] = []
        leaders: list[str] = []
        merged_validation = {"volume_multiple_5d": 0.0, "breakout": False, "relative_strength": "", "chain_resonance": False}

        for row in rows:
            event_types.append(clean_text(row.get("event_type")))
            chain_names.append(clean_text(row.get("chain_name")))
            chain_roles.append(clean_text(row.get("chain_role")))
            benefit_types.append(clean_text(row.get("benefit_type")))
            peer_tier_1.extend([clean_text(item) for item in row.get("peer_tier_1", []) if clean_text(item)])
            peer_tier_2.extend([clean_text(item) for item in row.get("peer_tier_2", []) if clean_text(item)])
            leaders.extend([clean_text(item) for item in row.get("leaders", []) if clean_text(item)])
            for source in row.get("sources", []) if isinstance(row.get("sources"), list) else []:
                if not isinstance(source, dict):
                    continue
                all_sources.append(deepcopy(source))
                role = normalize_source_role(clean_text(source.get("source_type")))
                if role:
                    all_roles.append(role)
                account = clean_text(source.get("account"))
                if account:
                    all_accounts.append(account)
            validation = row.get("market_validation") if isinstance(row.get("market_validation"), dict) else {}
            merged_validation["volume_multiple_5d"] = max(to_float_safe(merged_validation.get("volume_multiple_5d")), to_float_safe(validation.get("volume_multiple_5d")))
            merged_validation["breakout"] = bool(merged_validation.get("breakout")) or bool(validation.get("breakout"))
            merged_validation["chain_resonance"] = bool(merged_validation.get("chain_resonance")) or bool(validation.get("chain_resonance"))
            if clean_text(validation.get("relative_strength")).lower() == "strong":
                merged_validation["relative_strength"] = "strong"

        merged_candidate = normalize_event_candidate(
            {
                "ticker": ticker,
                "name": clean_text(base.get("name")),
                "event_type": sorted([item for item in event_types if item], key=_event_type_priority)[0] if any(event_types) else clean_text(base.get("event_type")),
                "event_strength": "strong" if any(clean_text(row.get("event_strength")).lower() == "strong" for row in rows) else clean_text(base.get("event_strength")) or "medium",
                "chain_name": next((item for item in chain_names if item and item != "unknown"), "unknown"),
                "chain_role": sorted([item for item in chain_roles if item and item != "unknown"], key=_chain_role_priority)[0] if any(item and item != "unknown" for item in chain_roles) else "unknown",
                "benefit_type": sorted([item for item in benefit_types if item], key=_benefit_type_priority)[0] if any(item for item in benefit_types) else (clean_text(base.get("benefit_type")) or "mapping"),
                "sources": all_sources,
                "market_validation": merged_validation,
                "peer_tier_1": sorted({item for item in peer_tier_1 if item}),
                "peer_tier_2": sorted({item for item in peer_tier_2 if item}),
                "leaders": sorted({item for item in leaders if item}),
            }
        )
        event_state = classify_event_state(merged_candidate)
        rumor_confidence = compute_rumor_confidence_range(merged_candidate)
        market_validation_summary = classify_market_validation(merged_candidate)
        trading_usability = classify_trading_usability(merged_candidate)
        discovery_bucket = assign_discovery_bucket(merged_candidate)
        card = {
            **merged_candidate,
            "event_types": sorted({item for item in event_types if item}, key=_event_type_priority),
            "primary_event_type": clean_text(merged_candidate.get("event_type")),
            "source_roles": sorted(set(all_roles)),
            "source_accounts": sorted(set(all_accounts)),
            "source_count": len(all_sources),
            "evidence_mix": build_evidence_mix(all_sources),
            "source_urls": collect_source_urls(all_sources),
            "key_evidence": build_key_evidence(all_sources),
            "market_signal_summary": build_market_signal_summary(merged_candidate),
            "chain_path_summary": build_chain_path_summary(merged_candidate),
            "event_phase": classify_event_phase(merged_candidate),
            "expectation_verdict": classify_expectation_verdict(merged_candidate),
            "headline_metrics": extract_headline_metrics(all_sources),
            "community_reaction_summary": build_community_reaction_summary(merged_candidate),
            "community_conviction": classify_community_conviction(merged_candidate),
            "expectation_basis_summary": build_expectation_basis_summary(merged_candidate),
            "expectation_risk_summary": build_expectation_risk_summary(merged_candidate),
            "peer_tier_1": sorted({item for item in merged_candidate.get("peer_tier_1", []) if item}),
            "peer_tier_2": sorted({item for item in merged_candidate.get("peer_tier_2", []) if item}),
            "leaders": sorted({item for item in merged_candidate.get("leaders", []) if item}),
            "event_state": event_state,
            "rumor_confidence_range": rumor_confidence,
            "market_validation_summary": market_validation_summary,
            "trading_usability": trading_usability,
            "discovery_bucket": discovery_bucket,
            "priority_score": compute_event_priority_score(merged_candidate),
            "why_now": build_why_now_summary(merged_candidate),
        }
        trading_profile = classify_trading_profile(card)
        card["trading_profile_bucket"] = trading_profile["bucket"]
        card["trading_profile_subtype"] = trading_profile["subtype"]
        card["trading_profile_reason"] = trading_profile["reason"]
        card["trading_profile_playbook"] = build_trading_profile_playbook(card)
        card["trading_profile_judgment"] = build_trading_profile_judgment(card)
        card["trading_profile_usage"] = build_trading_profile_usage(card)
        cards.append(card)

    cards.sort(key=lambda item: (-to_int_safe(item.get("priority_score")), _state_priority(item.get("event_state", {}).get("label")), clean_text(item.get("ticker"))))
    return cards


def build_market_validation_from_shortlist_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    trend = candidate.get("trend_template") if isinstance(candidate.get("trend_template"), dict) else {}
    price_snapshot = candidate.get("price_snapshot") if isinstance(candidate.get("price_snapshot"), dict) else {}
    rs90 = to_float_safe(price_snapshot.get("rs90"))
    distance_to_high = to_float_safe(price_snapshot.get("distance_to_high52_pct"), default=1000.0)
    return {
        "volume_multiple_5d": to_float_safe(candidate.get("volume_ratio")),
        "breakout": bool(trend.get("trend_pass")) and distance_to_high <= 25.0,
        "relative_strength": "strong" if rs90 >= 500 else "normal",
        "chain_resonance": False,
    }


def infer_event_type_from_shortlist_candidate(candidate: dict[str, Any]) -> str:
    snapshot = candidate.get("structured_catalyst_snapshot") if isinstance(candidate.get("structured_catalyst_snapshot"), dict) else {}
    previews = snapshot.get("performance_preview") if isinstance(snapshot.get("performance_preview"), list) else []
    if previews:
        report_period = clean_text((previews[0] or {}).get("report_period"))
        if report_period.endswith("-12-31"):
            return "annual_report_preview"
        return "quarterly_preview"
    company_events = snapshot.get("structured_company_events") if isinstance(snapshot.get("structured_company_events"), list) else []
    if company_events:
        return "company_event"
    return "structured_catalyst"


def build_source_items_from_shortlist_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = candidate.get("structured_catalyst_snapshot") if isinstance(candidate.get("structured_catalyst_snapshot"), dict) else {}
    rows: list[dict[str, Any]] = []
    for item in snapshot.get("performance_preview", []) if isinstance(snapshot.get("performance_preview"), list) else []:
        if not isinstance(item, dict):
            continue
        summary = clean_text(item.get("summary"))
        if summary:
            rows.append(
                {
                    "source_type": "official_filing",
                    "date": clean_text(item.get("notice_date")),
                    "summary": summary,
                }
            )
    for item in snapshot.get("structured_company_events", []) if isinstance(snapshot.get("structured_company_events"), list) else []:
        if not isinstance(item, dict):
            continue
        detail = clean_text(item.get("detail"))
        if detail:
            rows.append(
                {
                    "source_type": "official_filing",
                    "date": clean_text(item.get("date")),
                    "summary": detail,
                }
            )
    return rows


def build_auto_discovery_candidates(assessed_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in assessed_candidates:
        if not isinstance(candidate, dict):
            continue
        snapshot = candidate.get("structured_catalyst_snapshot") if isinstance(candidate.get("structured_catalyst_snapshot"), dict) else {}
        sources = build_source_items_from_shortlist_candidate(candidate)
        if not snapshot.get("structured_catalyst_within_window") and not sources:
            continue
        rows.append(
            normalize_event_candidate(
                {
                    "ticker": clean_text(candidate.get("ticker")),
                    "name": clean_text(candidate.get("name")),
                    "event_type": infer_event_type_from_shortlist_candidate(candidate),
                    "event_strength": "strong" if to_float_safe((candidate.get("score_components") or {}).get("structured_catalyst_score")) >= 10 else "medium",
                    "chain_name": clean_text(candidate.get("sector")),
                    "chain_role": clean_text(candidate.get("chain_role")) or "unknown",
                    "benefit_type": "direct",
                    "sources": sources,
                    "market_validation": build_market_validation_from_shortlist_candidate(candidate),
                }
            )
        )
    return rows


def build_x_style_discovery_candidates(
    batch_payload: dict[str, Any],
    *,
    selected_handles: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    desired_handles = {clean_text(item).lstrip("@") for item in (selected_handles or []) if clean_text(item)}
    if isinstance(batch_payload.get("subject_runs"), list):
        subject_runs = batch_payload.get("subject_runs", [])
    elif isinstance(batch_payload.get("recommendation_ledger"), list):
        subject_runs = [batch_payload]
    else:
        subject_runs = []
    for subject_run in subject_runs:
        if not isinstance(subject_run, dict):
            continue
        subject = subject_run.get("subject") if isinstance(subject_run.get("subject"), dict) else {}
        handle = clean_text(subject.get("handle")).lstrip("@")
        if desired_handles and handle not in desired_handles:
            continue

        name_to_ticker: dict[str, str] = {}
        for event in subject_run.get("recommendation_ledger", []) if isinstance(subject_run.get("recommendation_ledger"), list) else []:
            if not isinstance(event, dict):
                continue
            for scored in event.get("scored_names", []) if isinstance(event.get("scored_names"), list) else []:
                if not isinstance(scored, dict):
                    continue
                name = clean_text(scored.get("name"))
                ticker = clean_text(scored.get("ticker"))
                if name and ticker and name not in name_to_ticker:
                    name_to_ticker[name] = ticker

        source_board_by_status: dict[str, dict[str, Any]] = {}
        for item in subject_run.get("source_board", []) if isinstance(subject_run.get("source_board"), list) else []:
            if not isinstance(item, dict):
                continue
            status_url = clean_text(item.get("status_url"))
            status_id = clean_text(item.get("status_id"))
            if status_url:
                source_board_by_status[status_url] = item
            if status_id:
                source_board_by_status[status_id] = item

        for event in subject_run.get("recommendation_ledger", []) if isinstance(subject_run.get("recommendation_ledger"), list) else []:
            if not isinstance(event, dict):
                continue
            classification = clean_text(event.get("classification"))
            if classification not in {"direct_pick", "theme_basket", "logic_support", "quote_only"}:
                continue
            is_cross_market_advisory = (
                classification in {"logic_support", "quote_only"}
                or clean_text(event.get("suggested_basket_usage_boundary")) == "advisory_only"
                or bool(event.get("suggested_basket_qualitative_reference_only"))
            )
            advisory_evidence_boundary = [
                clean_text(item)
                for item in event.get("suggested_basket_evidence_boundary", [])
                if clean_text(item)
            ] or (deepcopy(ADVISORY_SIGNAL_EVIDENCE_BOUNDARY) if is_cross_market_advisory else [])
            advisory_validation_note = clean_text(event.get("suggested_basket_validation_note")) or (
                ADVISORY_SIGNAL_VALIDATION_NOTE if is_cross_market_advisory else ""
            )

            source_item = source_board_by_status.get(clean_text(event.get("status_url"))) or source_board_by_status.get(clean_text(event.get("status_id")))
            source_text = ""
            published_at = ""
            source_kind = ""
            if isinstance(source_item, dict):
                source_text = clean_text(source_item.get("direct_text")) or clean_text(source_item.get("quoted_text"))
                published_at = clean_text(source_item.get("published_at"))
                source_kind = clean_text(source_item.get("source_kind"))

            raw_names = event.get("names", []) if isinstance(event.get("names"), list) else []
            if not raw_names:
                raw_names = event.get("suggested_basket_core_candidates", []) if isinstance(event.get("suggested_basket_core_candidates"), list) else []
            if not raw_names:
                raw_names = event.get("suggested_basket_candidates", []) if isinstance(event.get("suggested_basket_candidates"), list) else []
            excluded_names = {
                clean_text(item)
                for item in event.get("suggested_basket_excluded_candidates", [])
                if clean_text(item)
            }
            exclusion_reasons = [
                clean_text(item)
                for item in event.get("suggested_basket_exclusion_reasons", [])
                if clean_text(item)
            ]
            relevance_by_name = {
                clean_text(item.get("name")): item
                for item in event.get("suggested_basket_candidate_relevance", [])
                if isinstance(item, dict) and clean_text(item.get("name"))
            }
            raw_names = [raw_name for raw_name in raw_names if clean_text(raw_name) and clean_text(raw_name) not in excluded_names]

            for raw_name in raw_names:
                name = clean_text(raw_name)
                if not name:
                    continue
                relevance = relevance_by_name.get(name, {})
                ticker = name_to_ticker.get(name, "")
                if not ticker:
                    for match in CODE_PATTERN.finditer(source_text):
                        if clean_text(match.group("name")) == name:
                            code = clean_text(match.group("code"))
                            if code.startswith(("6", "9")):
                                ticker = f"{code}.SS"
                            else:
                                ticker = f"{code}.SZ"
                            break
                candidate = normalize_event_candidate(
                    {
                        "ticker": ticker,
                        "name": name,
                        "event_type": clean_text(event.get("catalyst_type")) or "x_logic_signal",
                        "event_strength": "strong" if "strong" in clean_text(event.get("strength")).lower() else "medium",
                        "chain_name": clean_text(event.get("sector_or_chain") or event.get("suggested_basket_sector")),
                        "chain_role": classification,
                        "benefit_type": "direct" if classification == "direct_pick" else "mapping",
                        "peer_tier_1": [
                            clean_text(item)
                            for item in event.get("suggested_basket_core_candidates", [])
                            if clean_text(item) and clean_text(item) not in excluded_names
                        ],
                        "peer_tier_2": [
                            clean_text(item)
                            for item in event.get("suggested_basket_candidates", [])
                            if clean_text(item)
                            and clean_text(item) not in excluded_names
                            and clean_text(item) not in {clean_text(core) for core in event.get("suggested_basket_core_candidates", []) if clean_text(core)}
                        ],
                        "leaders": [name] if classification == "direct_pick" else [
                            clean_text(item)
                            for item in event.get("suggested_basket_core_candidates", [])
                            if clean_text(item) and clean_text(item) not in excluded_names
                        ],
                        "sources": [
                            {
                                "source_type": "x_summary",
                                "account": handle,
                                "summary": clean_text(event.get("thesis_excerpt")) or source_text,
                                "evidence_excerpt": source_text or clean_text(event.get("thesis_excerpt")),
                                "status_url": clean_text(event.get("status_url")),
                                "published_at": published_at,
                                "source_kind": source_kind,
                                "advisory_only": is_cross_market_advisory,
                                "qualitative_reference_only": is_cross_market_advisory,
                            }
                        ],
                        "market_validation": {},
                        "advisory_only": is_cross_market_advisory,
                        "qualitative_reference_only": is_cross_market_advisory,
                        "evidence_boundary": advisory_evidence_boundary,
                        "validation_note": advisory_validation_note,
                        "excluded_candidate_names": sorted(excluded_names),
                        "exclusion_reasons": exclusion_reasons,
                        "mapping_chain_role": clean_text(relevance.get("chain_role")),
                        "relevance_basis": clean_text(relevance.get("relevance_basis")),
                        "required_evidence": [
                            clean_text(item)
                            for item in relevance.get("required_evidence", [])
                            if clean_text(item)
                        ],
                        "mismatch_risks": [
                            clean_text(item)
                            for item in relevance.get("mismatch_risks", [])
                            if clean_text(item)
                        ],
                    }
                )
                if candidate.get("chain_role") == "logic_support":
                    bucket = assign_discovery_bucket(candidate)
                    if bucket in {"qualified", "watch"}:
                        candidate["discovery_bucket"] = bucket
                    else:
                        candidate["discovery_bucket"] = "track"
                rows.append(candidate)
    return rows
