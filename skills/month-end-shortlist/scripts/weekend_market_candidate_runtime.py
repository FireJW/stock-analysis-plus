#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Callable


TOPIC_LABELS: dict[str, str] = {
    "optical_interconnect": "光通信 / 光模块",
    "oil_shipping": "油运 / Hormuz",
    "commercial_space": "商业航天 / 卫星链",
    "satellite_chain": "卫星链 / 卫星互联网",
    "tgv_upstream": "TGV / 玻璃基板上游熔炉",
}

TOPIC_ALIASES: dict[str, list[str]] = {
    "optical_interconnect": [
        "光通信",
        "光互联",
        "光模块",
        "光器件",
        "硅光子",
        "photonics",
        "optical interconnect",
        "optics",
    ],
    "oil_shipping": [
        "油运",
        "油轮",
        "shipping",
        "tanker",
        "hormuz",
        "strait of hormuz",
    ],
    "commercial_space": [
        "商业航天",
        "火箭",
        "航天发射",
        "spacex",
        "rocket",
        "launch",
        "space launch",
        "starship",
    ],
    "satellite_chain": [
        "卫星",
        "卫星互联网",
        "卫星链",
        "星链",
        "starlink",
        "satellite",
    ],
    "tgv_upstream": [
        "玻璃基板",
        "tgv",
        "熔炉",
        "康宁",
        "agc",
        "schott",
        "neg",
    ],
}

_GEOPOLITICS_TOPIC_KEYWORDS = frozenset({
    "oil", "shipping", "defense", "gold", "energy", "hormuz",
    "geopolit", "war", "military", "sanctions",
})
_STALE_POST_DAYS_DEFAULT = 7
_STALE_POST_DAYS_GEOPOLITICS = 3
_HEADWIND_KEYWORDS = frozenset({
    "通胀", "inflation", "降息推迟", "利空", "压力大",
    "回调风险", "获利了结", "泡沫", "过热",
    "overbought", "overheated",
})


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in (_clean_text(value) for value in values) if item]


def _is_stale_post(
    post: dict[str, Any],
    reference_date: str,
    *,
    inferred_topics: list[str] | None = None,
) -> bool:
    """Check if a live post is too old to count as a fresh weekend signal.

    Args:
        post: Normalized live post dict (must have 'posted_at' key).
        reference_date: ISO date string (YYYY-MM-DD) to measure age against.
        inferred_topics: Topics inferred from the post text.

    Returns True if the post is stale (should get zero weight).
    """
    from datetime import date, datetime

    posted_at = _clean_text(post.get("posted_at"))
    if not posted_at:
        return False  # missing timestamp → don't penalize

    try:
        # Parse ISO 8601 — handle both "2026-04-09T12:57:32+00:00" and "2026-04-09"
        posted_date = datetime.fromisoformat(posted_at.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return False  # unparseable → don't penalize

    try:
        ref_date = date.fromisoformat(reference_date[:10])
    except (ValueError, TypeError):
        return False

    age_days = (ref_date - posted_date).days
    if age_days < 0:
        return False  # future post → not stale

    # Geopolitics topics use stricter threshold
    is_geopolitics = False
    for topic in (inferred_topics or []):
        topic_lower = topic.lower()
        if any(kw in topic_lower for kw in _GEOPOLITICS_TOPIC_KEYWORDS):
            is_geopolitics = True
            break

    threshold = _STALE_POST_DAYS_GEOPOLITICS if is_geopolitics else _STALE_POST_DAYS_DEFAULT
    return age_days > threshold


def _has_headwind_keywords(text: str) -> bool:
    """Return True if text contains any headwind/bearish keywords."""
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    return any(kw in normalized for kw in _HEADWIND_KEYWORDS)


_REDDIT_SKEPTICAL_PATTERNS = [
    re.compile(r"why.*still", re.IGNORECASE),
    re.compile(r"how long can.*last", re.IGNORECASE),
    re.compile(r"overvalued|bubble|peak|overbought|顶部|见顶|泡沫", re.IGNORECASE),
]


def _classify_reddit_sentiment(thread_summary: str, direction_hint: str) -> str:
    """Classify reddit thread sentiment as confirming, questioning, or neutral.

    Args:
        thread_summary: The thread title/summary text.
        direction_hint: The direction_hint field from the reddit input.

    Returns one of: 'confirming', 'questioning', 'neutral'.
    """
    if direction_hint == "questioning":
        return "questioning"
    if any(pattern.search(thread_summary) for pattern in _REDDIT_SKEPTICAL_PATTERNS):
        return "questioning"
    if direction_hint == "confirming":
        return "confirming"
    return "neutral"


def _logic_level(value: int, *, high_at: int, medium_at: int = 1) -> str:
    if value >= high_at:
        return "high"
    if value >= medium_at:
        return "medium"
    return "low"


def _topic_label(topic_name: str) -> str:
    return TOPIC_LABELS.get(topic_name, topic_name)


def _alias_matches_text(alias: str, normalized_text: str) -> bool:
    cleaned_alias = _clean_text(alias).lower()
    if not cleaned_alias or not normalized_text:
        return False
    if re.search(r"[a-z]", cleaned_alias):
        pattern = rf"(?<![a-z0-9]){re.escape(cleaned_alias)}(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None
    return cleaned_alias in normalized_text


def _normalize_live_post(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    text_fields = [
        _clean_text(row.get("combined_summary")),
        _clean_text(row.get("post_text_raw")),
        _clean_text(row.get("post_summary")),
    ]
    thread_posts = row.get("thread_posts") if isinstance(row.get("thread_posts"), list) else []
    thread_texts = [
        _clean_text(item.get("post_text_raw") or item.get("post_summary"))
        for item in thread_posts
        if isinstance(item, dict)
    ]
    text_blob = " ".join(part for part in [*text_fields, *thread_texts] if part)
    url = _clean_text(row.get("post_url"))
    handle = _clean_text(row.get("author_handle"))
    if not text_blob and not url and not handle:
        return None
    return {
        "post_url": url,
        "author_handle": handle,
        "author_display_name": _clean_text(row.get("author_display_name")),
        "combined_summary": _clean_text(row.get("combined_summary")),
        "post_text_raw": _clean_text(row.get("post_text_raw")),
        "post_summary": _clean_text(row.get("post_summary")),
        "text_blob": text_blob,
        "session_source": _clean_text(row.get("session_source")),
        "discovery_reason": _clean_text(row.get("discovery_reason")),
        "posted_at": _clean_text(row.get("posted_at")),
    }


def _normalize_live_result(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    x_posts = [_normalize_live_post(item) for item in row.get("x_posts", [])]
    normalized_posts = [item for item in x_posts if item]
    source_result_path = _clean_text(row.get("source_result_path"))
    run_completeness = deepcopy(row.get("run_completeness")) if isinstance(row.get("run_completeness"), dict) else {}
    if not normalized_posts and not source_result_path and not run_completeness:
        return None
    normalized = {
        "x_posts": normalized_posts,
        "session_bootstrap": deepcopy(row.get("session_bootstrap")) if isinstance(row.get("session_bootstrap"), dict) else {},
    }
    if source_result_path:
        normalized["source_result_path"] = source_result_path
    if run_completeness:
        normalized["run_completeness"] = run_completeness
    source_mode = _clean_text(row.get("source_mode"))
    if source_mode:
        normalized["source_mode"] = source_mode
    analysis_time = _clean_text(row.get("analysis_time"))
    if analysis_time:
        normalized["analysis_time"] = analysis_time
    return normalized


def _load_live_result_from_path(raw_path: str) -> dict[str, Any] | None:
    path = Path(raw_path)
    if not raw_path or not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return _normalize_live_result(payload)


def _iter_live_posts(candidate_input: dict[str, Any]) -> list[dict[str, Any]]:
    live_posts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def append_posts(results: list[dict[str, Any]]) -> None:
        for payload in results:
            for row in payload.get("x_posts", []):
                url = _clean_text(row.get("post_url"))
                dedupe_key = url or f"{_clean_text(row.get('author_handle'))}:{_clean_text(row.get('text_blob'))}"
                if dedupe_key in seen_urls:
                    continue
                seen_urls.add(dedupe_key)
                live_posts.append(row)

    normalized_inline_results = [
        item
        for item in (_normalize_live_result(row) for row in candidate_input.get("x_live_index_results", []))
        if item
    ]
    append_posts(normalized_inline_results)

    loaded_results: list[dict[str, Any]] = []
    for raw_path in candidate_input.get("x_live_index_result_paths", []):
        normalized = _load_live_result_from_path(raw_path)
        if normalized:
            loaded_results.append(normalized)
    append_posts(loaded_results)
    return live_posts


def _infer_topics_from_text(text: str) -> list[str]:
    normalized_text = _clean_text(text).lower()
    if not normalized_text:
        return []
    matched: list[str] = []
    for topic_name, aliases in TOPIC_ALIASES.items():
        if any(_alias_matches_text(alias, normalized_text) for alias in aliases):
            matched.append(topic_name)
    return matched


def _select_key_sources(
    candidate_input: dict[str, Any],
    topic_name: str,
    live_posts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    key_sources: list[dict[str, str]] = []

    for row in candidate_input.get("x_seed_inputs", []):
        if topic_name not in row.get("tags", []):
            continue
        key_sources.append(
            {
                "source_name": _clean_text(row.get("display_name")) or _clean_text(row.get("handle")),
                "source_kind": "x_seed",
                "url": _clean_text(row.get("url")),
                "summary": f"Preferred seed concentrated on {_topic_label(topic_name)}.",
            }
        )
        break

    for row in live_posts:
        if topic_name not in _infer_topics_from_text(row.get("text_blob")):
            continue
        source_entry = {
            "source_name": _clean_text(row.get("author_display_name")) or _clean_text(row.get("author_handle")),
            "source_kind": "x_live_index",
            "url": _clean_text(row.get("post_url")),
            "summary": _clean_text(row.get("combined_summary") or row.get("post_summary") or row.get("post_text_raw")),
        }
        posted_at = _clean_text(row.get("posted_at"))
        if posted_at:
            source_entry["posted_at"] = posted_at
        key_sources.append(source_entry)
        if len(key_sources) >= 2:
            break

    for row in candidate_input.get("x_expansion_inputs", []):
        if topic_name not in row.get("theme_overlap", []):
            continue
        key_sources.append(
            {
                "source_name": _clean_text(row.get("handle")),
                "source_kind": "x_expansion",
                "url": _clean_text(row.get("url")),
                "summary": _clean_text(row.get("why_included")) or f"Expansion layer confirmed {_topic_label(topic_name)}.",
            }
        )
        break

    for row in candidate_input.get("reddit_inputs", []):
        if topic_name not in row.get("theme_tags", []):
            continue
        key_sources.append(
            {
                "source_name": _clean_text(row.get("subreddit")),
                "source_kind": "reddit_confirmation",
                "url": _clean_text(row.get("thread_url")),
                "summary": _clean_text(row.get("thread_summary")) or f"Reddit discussion confirmed {_topic_label(topic_name)}.",
            }
        )
        break

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in key_sources:
        key = (_clean_text(row.get("source_kind")), _clean_text(row.get("url")) or _clean_text(row.get("source_name")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[:3]


def normalize_weekend_market_candidate_input(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    def normalize_seed(row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        handle = _clean_text(row.get("handle"))
        if not handle:
            return None
        return {
            "handle": handle,
            "url": _clean_text(row.get("url")),
            "display_name": _clean_text(row.get("display_name")),
            "tags": _clean_list(row.get("tags")),
            "theme_aliases": deepcopy(row.get("theme_aliases")) if isinstance(row.get("theme_aliases"), dict) else {},
            "candidate_names": _clean_list(row.get("candidate_names")),
            "x_index_result_path": _clean_text(row.get("x_index_result_path")),
            "quality_hint": _clean_text(row.get("quality_hint")),
        }

    def normalize_expansion(row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        handle = _clean_text(row.get("handle"))
        if not handle:
            return None
        return {
            "handle": handle,
            "url": _clean_text(row.get("url")),
            "why_included": _clean_text(row.get("why_included")),
            "theme_overlap": _clean_list(row.get("theme_overlap")),
            "candidate_names": _clean_list(row.get("candidate_names")),
            "quality_hint": _clean_text(row.get("quality_hint")),
            "x_index_result_path": _clean_text(row.get("x_index_result_path")),
        }

    def normalize_reddit(row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        subreddit = _clean_text(row.get("subreddit"))
        summary = _clean_text(row.get("thread_summary"))
        if not subreddit and not summary:
            return None
        return {
            "subreddit": subreddit,
            "thread_url": _clean_text(row.get("thread_url")),
            "thread_summary": summary,
            "direction_hint": _clean_text(row.get("direction_hint")),
            "theme_tags": _clean_list(row.get("theme_tags")),
            "quality_hint": _clean_text(row.get("quality_hint")),
        }

    normalized = {
        "x_seed_inputs": [item for item in (normalize_seed(row) for row in raw.get("x_seed_inputs", [])) if item],
        "x_expansion_inputs": [item for item in (normalize_expansion(row) for row in raw.get("x_expansion_inputs", [])) if item],
        "reddit_inputs": [item for item in (normalize_reddit(row) for row in raw.get("reddit_inputs", [])) if item],
        "x_live_index_results": [item for item in (_normalize_live_result(row) for row in raw.get("x_live_index_results", [])) if item],
        "x_live_index_result_paths": [item for item in (_clean_text(path) for path in raw.get("x_live_index_result_paths", [])) if item],
    }
    return normalized if any(normalized.values()) else None


def default_ticker_resolver(name: str) -> str | None:
    """Resolve a Chinese company name to a 6-digit ticker code via Eastmoney suggest API.

    Returns ticker string like '300308' or None if not found.
    """
    try:
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen

        url = (
            "https://searchapi.eastmoney.com/api/suggest/get?"
            + urlencode({"input": name, "type": "14", "token": "D43BF722C8E33BDC906FB84D85E326E8"})
        )
        req = Request(url, headers={"Referer": "https://quote.eastmoney.com/"})
        with urlopen(req, timeout=5) as resp:
            import json as _json
            payload = _json.loads(resp.read())
        data = payload.get("QuotationCodeTable", {}).get("Data") or []
        for item in data:
            code = (item.get("Code") or "").strip()
            if code and re.fullmatch(r"\d{6}", code):
                return code
    except Exception:
        pass
    return None


def resolve_direction_tickers(
    direction_reference_map: list[dict[str, Any]],
    *,
    resolver: Callable[[str], str | None] | None = None,
) -> list[dict[str, Any]]:
    """Resolve empty ticker fields in direction_reference_map.

    For each leader/high_beta entry with ticker == "", calls the resolver.
    If resolution succeeds, fills the ticker field.
    Updates mapping_note to indicate resolution was attempted.
    """
    if resolver is None:
        resolver = default_ticker_resolver
    result = deepcopy(direction_reference_map)
    for entry in result:
        any_resolved = False
        for group_key in ("leaders", "high_beta_names"):
            for item in entry.get(group_key, []):
                if item.get("ticker") == "" and item.get("name"):
                    resolved_ticker = resolver(item["name"])
                    if resolved_ticker:
                        item["ticker"] = resolved_ticker
                        any_resolved = True
        if any_resolved:
            entry["mapping_note"] = "Tickers resolved at build time."
    return result


def build_weekend_market_candidate(candidate_input: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(candidate_input, dict):
        return (
            {
                "candidate_topics": [],
                "beneficiary_chains": [],
                "headwind_chains": [],
                "priority_watch_directions": [],
                "signal_strength": "low",
                "evidence_summary": ["No usable weekend market candidate input was provided."],
                "x_seed_alignment": "none",
                "reddit_confirmation": "none",
                "status": "insufficient_signal",
            },
            [],
        )

    topic_counter: Counter[str] = Counter()
    reference_candidates: dict[str, list[str]] = {}
    live_posts = _iter_live_posts(candidate_input)
    live_topic_rows: dict[str, list[dict[str, Any]]] = {}

    for row in candidate_input.get("x_seed_inputs", []):
        for topic in row.get("tags", []):
            topic_counter[topic] += 3
            reference_candidates.setdefault(topic, []).extend(row.get("candidate_names", []))

    for row in candidate_input.get("x_expansion_inputs", []):
        for topic in row.get("theme_overlap", []):
            topic_counter[topic] += 1
            reference_candidates.setdefault(topic, []).extend(row.get("candidate_names", []))

    reddit_questioning_topics: set[str] = set()
    for row in candidate_input.get("reddit_inputs", []):
        sentiment = _classify_reddit_sentiment(
            _clean_text(row.get("thread_summary")),
            _clean_text(row.get("direction_hint")),
        )
        for topic in row.get("theme_tags", []):
            if sentiment == "questioning":
                reddit_questioning_topics.add(topic)
            else:
                topic_counter[topic] += 1

    # Derive reference_date from candidate_input or default to empty (no filtering)
    reference_date = _clean_text(candidate_input.get("reference_date"))

    for row in live_posts:
        inferred = _infer_topics_from_text(row.get("text_blob"))
        stale = _is_stale_post(row, reference_date, inferred_topics=inferred) if reference_date else False
        mixed = bool(inferred) and _has_headwind_keywords(row.get("text_blob", ""))
        weight = 0 if stale else (1 if mixed else 2)
        for topic in inferred:
            if weight:
                topic_counter[topic] += weight
            live_topic_rows.setdefault(topic, []).append(row)

    if not topic_counter:
        return (
            {
                "candidate_topics": [],
                "beneficiary_chains": [],
                "headwind_chains": [],
                "priority_watch_directions": [],
                "signal_strength": "low",
                "evidence_summary": ["Weekend inputs did not converge on a usable A-share topic."],
                "x_seed_alignment": "low",
                "reddit_confirmation": "mixed",
                "status": "insufficient_signal",
            },
            [],
        )

    candidate_topics: list[dict[str, Any]] = []
    direction_reference_map: list[dict[str, Any]] = []
    top_topics = topic_counter.most_common(3)

    for priority_rank, (topic_name, topic_score) in enumerate(top_topics, start=1):
        seed_count = sum(1 for row in candidate_input.get("x_seed_inputs", []) if topic_name in row.get("tags", []))
        expansion_count = sum(1 for row in candidate_input.get("x_expansion_inputs", []) if topic_name in row.get("theme_overlap", []))
        reddit_count = sum(
            1 for row in candidate_input.get("reddit_inputs", [])
            if topic_name in row.get("theme_tags", [])
            and _classify_reddit_sentiment(
                _clean_text(row.get("thread_summary")),
                _clean_text(row.get("direction_hint")),
            ) != "questioning"
        )
        has_questioning = topic_name in reddit_questioning_topics
        live_count = len(live_topic_rows.get(topic_name, []))
        deduped_names = list(dict.fromkeys(name for name in reference_candidates.get(topic_name, []) if name))
        leaders = deduped_names[:2]
        high_beta_names = deduped_names[2:4]
        ranking_logic = {
            "seed_alignment": _logic_level(seed_count, high_at=2),
            "expansion_confirmation": _logic_level(expansion_count, high_at=1),
            "reddit_confirmation": "questioning" if has_questioning and reddit_count == 0
                else _logic_level(reddit_count, high_at=1),
            "noise_or_disagreement": "medium" if has_questioning
                else ("low" if live_count >= 1 or reddit_count >= 1 else "medium"),
        }

        if live_count and not seed_count:
            ranking_reason = (
                f"Live X evidence clustered most clearly on {_topic_label(topic_name)}, "
                f"so it ranks #{priority_rank} even without heavy manual seed tagging."
            )
        else:
            ranking_reason = (
                f"Preferred X seeds and confirmation layers aligned most clearly on {_topic_label(topic_name)}, "
                f"so it ranks #{priority_rank} for Monday watch."
            )

        key_sources = _select_key_sources(candidate_input, topic_name, live_posts)
        candidate_topics.append(
            {
                "topic_name": topic_name,
                "topic_label": _topic_label(topic_name),
                "priority_rank": priority_rank,
                "signal_strength": "high" if topic_score >= 6 else "medium",
                "why_it_matters": "Live X evidence and tagged confirmation inputs converged on this weekend direction.",
                "monday_watch": f"Watch whether {_topic_label(topic_name)} continues to lead on Monday open.",
                "ranking_logic": ranking_logic,
                "ranking_reason": ranking_reason,
                "key_sources": key_sources,
            }
        )
        direction_reference_map.append(
            {
                "direction_key": topic_name,
                "direction_label": _topic_label(topic_name),
                "leaders": [{"ticker": "", "name": name} for name in leaders],
                "high_beta_names": [{"ticker": "", "name": name} for name in high_beta_names],
                "mapping_note": "Direction reference only. Not a formal execution layer.",
            }
        )

    top_score = top_topics[0][1]
    live_topic_count = sum(len(rows) for rows in live_topic_rows.values())
    candidate = {
        "candidate_topics": candidate_topics,
        "beneficiary_chains": [item["topic_name"] for item in candidate_topics],
        "headwind_chains": [],
        "priority_watch_directions": [item["topic_label"] for item in candidate_topics],
        "signal_strength": "high" if top_score >= 6 else "medium",
        "evidence_summary": [
            f"Live X contributed {live_topic_count} matched post(s) across the surfaced weekend themes." if live_topic_count else "Weekend themes were driven mainly by tagged manual inputs.",
            "Reddit acted as confirmation instead of driving topic selection.",
        ],
        "x_seed_alignment": "high" if any(item["ranking_logic"]["seed_alignment"] == "high" for item in candidate_topics) else "medium",
        "reddit_confirmation": "confirming" if any(item["ranking_logic"]["reddit_confirmation"] != "low" for item in candidate_topics) else "mixed",
        "status": "candidate_only",
    }
    direction_reference_map = resolve_direction_tickers(direction_reference_map)
    return candidate, direction_reference_map


__all__ = [
    "build_weekend_market_candidate",
    "normalize_weekend_market_candidate_input",
    "default_ticker_resolver",
    "resolve_direction_tickers",
]
