"""Transparent proxy ranking, stratified sampling, and feasible greedy reranking.

Input is an immutable-in-practice snapshot supplied by the service. No future
behaviour, global random state, network, or current clock is read here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse
from app.recommendation.semantic import similarity as semantic_similarity, lexical_tokens

STRATEGY_VERSION = "unknown-rerank-2.0"
DEFAULT_CONFIG: dict[str, Any] = {
    "version": "2026-11-17.1",
    "weights": {"novelty": 0.35, "quality": 0.25, "diversity": 0.20, "learnability": 0.20},
    "broad_weights": {"novelty": 0.05, "quality": 0.35, "diversity": 0.40, "learnability": 0.20},
    "minimum_quality": 0.40,
    "minimum_learnability": 0.25,
    "default_quality": 0.60,
    "default_prerequisite_load": 0.50,
    "minimum_disciplines": 4,
    "maximum_per_discipline": 2,
    "minimum_new": 2,
    "maximum_batch_size": 20,
    "maximum_bridge_hops": 3,
    "recent_penalty": 0.80,
    "skip_penalty": 0.12,
    "random_tiebreak": 0.000001,
    "semantic_similarity": True,
    "long_term_weight": 0.10,
}
FEATURES = ("novelty", "quality", "diversity", "learnability")


def _unit(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
        return max(0.0, min(1.0, number)) if math.isfinite(number) else default
    except (ValueError, TypeError):
        return default


def _settings(config: dict | None) -> dict:
    result = copy.deepcopy(DEFAULT_CONFIG)
    if config:
        unknown = set(config) - set(result)
        if unknown:
            raise ValueError(f"unknown configuration keys: {sorted(unknown)}")
        result.update(copy.deepcopy(config))
    if not isinstance(result['semantic_similarity'],bool): raise ValueError('semantic_similarity must be boolean')
    for key in ("weights", "broad_weights"):
        weights = result[key]
        if set(weights) != set(FEATURES):
            raise ValueError(f"{key} must contain {FEATURES}")
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in weights.values()):
            raise ValueError("weights must be finite and non-negative")
        if not math.isclose(sum(weights.values()), 1, abs_tol=1e-9):
            raise ValueError("weights must sum to one")
    for key in ("minimum_quality", "minimum_learnability", "default_quality", "default_prerequisite_load", "recent_penalty", "skip_penalty", "random_tiebreak", "long_term_weight"):
        value = result[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key} must be in [0,1]")
    for key in ("minimum_disciplines", "maximum_per_discipline", "minimum_new", "maximum_batch_size", "maximum_bridge_hops"):
        if not isinstance(result[key], int) or result[key] < (0 if key == "minimum_new" else 1):
            raise ValueError(f"{key} must be an appropriate non-negative integer")
    return result


def _sets(history: dict, key: str) -> set[str]:
    value=history.get(key, [])
    return value if isinstance(value,set) else {str(x) for x in value}


def _tokens(text: str) -> set[str]:
    """Word tokens and Han bigrams; a transparent lexical repetition proxy."""
    return lexical_tokens(str(text))


def _similarity(first: dict, second: dict, enabled=True) -> float:
    return semantic_similarity(first,second,enabled=enabled)


def _is_new(candidate: dict, history: dict) -> bool:
    discipline_new = candidate["primary_discipline_id"] not in _sets(history, "explored_disciplines")
    subfield = candidate.get("subfield")
    subfield_new = bool(subfield and subfield not in _sets(history, "explored_subfields"))
    return candidate["id"] not in (_sets(history, "explored_ids")|_sets(history,'known_ids')) and (discipline_new or subfield_new)


def novelty(candidate: dict, history: dict, config: dict | None = None) -> float:
    """An estimate of unfamiliarity, never a measurement of understanding."""
    settings = _settings(config)
    return _novelty(candidate,history,settings)


def _novelty(candidate,history,settings):
    topic_id = str(candidate["id"])
    discipline = str(candidate["primary_discipline_id"])
    intensity = _unit(history.get("intensity"), 0.5)
    value = 0.35
    value += (0.10 + 0.20 * intensity) if discipline not in _sets(history, "explored_disciplines") else 0.0
    value += (0.10 + 0.10 * intensity) if candidate.get("subfield") not in _sets(history, "explored_subfields") else 0.0
    value += 0.15 if topic_id not in _sets(history, "explored_ids") else -0.20
    value -= 0.10 if discipline in _sets(history, "familiar_disciplines") else 0.0
    value += 0.15 if topic_id in _sets(history, "unfamiliar_ids") else 0.0
    if topic_id in _sets(history,'name_only_ids'): value+=0.08
    if topic_id in _sets(history,'concept_only_ids'): value+=0.04
    if topic_id in _sets(history,'connection_gap_ids'): value+=0.06
    if topic_id in _sets(history,'forgotten_ids'): value+=0.10
    coverage=history.get('coverage_windows',{}).get('30',{})
    long_term=(0.6/(1+coverage.get('disciplines',{}).get(discipline,0)) + 0.4/(1+coverage.get('subfields',{}).get(candidate.get('subfield',''),0))) if coverage else 0
    value+=settings['long_term_weight']*long_term
    if topic_id in _sets(history, "known_ids"):
        value *= 0.15
    if topic_id in _sets(history, "recent_ids"):
        value *= 1.0 - settings["recent_penalty"]
    similarity = max((_similarity(candidate, item,settings['semantic_similarity']) for item in history.get("recent_candidates", [])), default=0.0)
    value *= 1.0 - 0.20 * similarity
    # Repeated exposure is a repetition signal, not dislike or comprehension.
    exposures=history.get('exposure_counts',{}).get(topic_id,0)
    value*=1-min(0.25,max(0,exposures-1)*0.05)
    return round(_unit(value), 6)


def diversity(candidate: dict, selected: list[dict], semantic=True) -> float:
    """Marginal set contribution; secondary tags never count as disciplines."""
    if not selected:
        return 1.0
    same_discipline = sum(item["primary_discipline_id"] == candidate["primary_discipline_id"] for item in selected)
    subfield = candidate.get("subfield")
    same_subfield = sum(bool(subfield and item.get("subfield") == subfield) for item in selected)
    similarity = max((_similarity(candidate, item,semantic) for item in selected), default=0.0)
    return round(_unit(0.65 / (1 + same_discipline) + 0.25 / (1 + same_subfield) + 0.10 * (1 - similarity)), 6)


def learnability(candidate: dict, has_bridge: bool = False, config: dict | None = None) -> float:
    settings = _settings(config)
    features = candidate.get("quality_features") or {}
    summary_available = bool(str(candidate.get("summary") or candidate.get("original_summary") or "").strip())
    load = _unit(candidate.get("prerequisite_load", features.get("prerequisite_load")), settings["default_prerequisite_load"])
    value = 0.35 * summary_available + 0.35 * (1 - load)
    value += 0.15 if features.get("has_example") is True else 0.0
    value += 0.15 if has_bridge else 0.0
    return round(_unit(value), 6)


def _url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value or ""))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _traceable(candidate: dict) -> bool:
    sources = candidate.get("sources") or []
    return any(_url(source.get("url")) for source in sources if isinstance(source, dict))


def _bridge(candidate: dict, history: dict, settings: dict) -> list[dict]:
    supplied = (history.get("bridge_paths") or {}).get(str(candidate["id"]), [])
    if not isinstance(supplied, list) or not 0 < len(supplied) <= settings["maximum_bridge_hops"]:
        return []
    prior = None
    visited: set[str] = set()
    for hop in supplied:
        if not isinstance(hop, dict):
            return []
        if not all(hop.get(key) for key in ("from_id", "to_id", "type", "label", "explanation", "source_url")):
            return []
        if not _url(hop["source_url"]) or "analogy" in str(hop["type"]).lower() or "类比" in str(hop["type"]):
            return []
        if hop.get('evidence_status','curated') not in ('curated','source_checked') or hop.get('direction','forward') not in ('forward','both'):
            return []
        if prior is not None and str(hop["from_id"]) != prior:
            return []
        if str(hop["to_id"]) in visited or str(hop['from_id'])==str(hop['to_id']):
            return []
        visited.add(str(hop["from_id"]))
        prior = str(hop["to_id"])
    first = supplied[0]
    origin_known = str(first["from_id"]) in (_sets(history, "explored_ids") | _sets(history, "known_ids"))
    origin_familiar = str(first.get("from_discipline_id", "")) in _sets(history, "familiar_disciplines")
    if not (origin_known or origin_familiar) or prior != str(candidate["id"]):
        return []
    return copy.deepcopy(supplied)


def _evergreen(candidate: dict) -> bool:
    return candidate.get("content_type", "evergreen") not in {"news", "hot", "breaking"}


def _feasible(pool: list[dict], selected: list[dict], count: int, coverage: int, cap: int, minimum_new: int, require_evergreen: bool) -> bool:
    """Exact small quota DP, grouped by primary discipline and binary features.

    This avoids choosing a locally attractive topic that makes the final batch
    impossible. Runtime depends on batch size, not combinations of all topics.
    """
    remaining = count - len(selected)
    if remaining < 0 or len(pool) < remaining:
        return False
    existing = Counter(item["primary_discipline_id"] for item in selected)
    if any(value > cap for value in existing.values()):
        return False
    initial_new = min(minimum_new, sum(item["_new"] for item in selected))
    initial_evergreen = any(_evergreen(item) for item in selected)
    groups: dict[str, Counter] = defaultdict(Counter)
    for item in pool:
        groups[item["primary_discipline_id"]][(int(item["_new"]), int(_evergreen(item)))] += 1
    # state = (slots filled, total newly represented disciplines, new opportunities, evergreen)
    states = {(0, len(existing), initial_new, initial_evergreen)}
    for discipline, categories in sorted(groups.items()):
        capacity = min(remaining, cap - existing[discipline])
        if capacity <= 0:
            continue
        # Enumerate possible counts inside one discipline, cap is normally two.
        options = {(0, 0, False)}
        for (is_new, is_evergreen), available in sorted(categories.items()):
            new_options = set()
            for used, nnew, green in options:
                for number in range(min(available, capacity - used) + 1):
                    new_options.add((used + number, min(minimum_new, nnew + is_new * number), green or bool(is_evergreen and number)))
            options = new_options
        next_states = set()
        for slots, nd, nnew, green in states:
            for number, added_new, added_green in options:
                if slots + number <= remaining:
                    next_states.add((slots + number, min(coverage, nd + int(number > 0 and discipline not in existing)), min(minimum_new, nnew + added_new), green or added_green))
        states = next_states
        if not states:
            return False
    return any(slots == remaining and nd >= coverage and nnew >= minimum_new and (green or not require_evergreen) for slots, nd, nnew, green in states)


def _reason(candidate: dict, history: dict, mode: str, features: dict, bridge_path: list[dict], history_free: bool) -> str:
    pieces: list[str] = []
    if mode == "broad":
        pieces.append("按一级学科分层抽样")
        pieces.append("本批次完全不使用个人历史" if history_free else "仅将近期曝光作为重复抑制，并检查未探索机会")
    elif mode == "bridge" and bridge_path:
        first = bridge_path[0]
        pieces.append(f"从「{first.get('from_title') or first['from_id']}」沿{len(bridge_path)}条有出处的关系进入此主题")
        pieces.append(" → ".join(hop["label"] for hop in bridge_path))
    else:
        for key,label in [('name_only_ids','你标记为知道名称、不了解含义'),('concept_only_ids','你想了解这个概念的真实应用'),('connection_gap_ids','你想了解它与其他学科的联系'),('forgotten_ids','你主动标记希望重新认识这个知识')]:
            if candidate['id'] in _sets(history,key): pieces.append(label)
        if candidate["id"] in _sets(history, "unfamiliar_ids"):
            pieces.append("你曾主动标记此前不了解此主题")
        if candidate["primary_discipline_id"] not in _sets(history, "explored_disciplines"):
            pieces.append("该主学科尚无探索记录")
        elif candidate.get("subfield") not in _sets(history, "explored_subfields"):
            pieces.append("这个细分领域尚无探索记录")
        elif candidate["id"] not in _sets(history, "explored_ids"):
            pieces.append("该主题尚无探索记录")
        else:
            pieces.append("已有探索记录，本次作为可用候选补充")
        if mode == "bridge":
            pieces.append("未找到可用桥梁，本条按广域候选补充")
        window=history.get('coverage_windows',{}).get('30',{})
        if window and not window.get('disciplines',{}).get(candidate['primary_discipline_id'],0):
            pieces.append('近30天该学科没有首次探索记录')
    if features["diversity"] >= 0.8:
        pieces.append("为当前组合补充不同学科或细分主题")
    if not history_free and candidate["id"] in _sets(history, "recent_ids"):
        pieces.append("近期已展示，因候选或约束需要保留")
    if features["quality"] >= 0.75:
        pieces.append("来源与内容完整性代理指标较好（不代表已证明内容正确）")
    return "；".join(pieces) + "。"


def novelty_basis(topic_id,history):
    for key,label in [('unfamiliar_ids','self_unfamiliar'),('name_only_ids','name_only'),('concept_only_ids','application_gap'),('connection_gap_ids','connection_gap'),('forgotten_ids','self_forgotten'),('known_ids','self_known')]:
        if topic_id in _sets(history,key): return label
    if topic_id in _sets(history,'stale_ids'): return 'old_contact_not_proven_forgotten'
    return 'encountered_not_proven_understood' if topic_id in _sets(history,'explored_ids') else 'no_record_of_contact'


def recommend(candidates: list[dict], history: dict, mode: str = "unknown", count: int = 5, seed: int = 0, config: dict | None = None) -> dict:
    """Generate a reproducible batch from caller-owned snapshots.

    All inputs and outputs are JSON serializable. No input object is mutated.
    Caller must persist the result before exposing it as the current batch.
    """
    settings = _settings(config)
    if mode not in {"unknown", "bridge", "broad"}:
        raise ValueError("unsupported recommendation mode")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= settings["maximum_batch_size"]:
        raise ValueError("invalid batch size")
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    original_history = copy.deepcopy(history)
    history_free = mode == "broad" and not history.get("broad_use_history", True)
    effective_history = {} if history_free else copy.deepcopy(history)
    for key,value in list(effective_history.items()):
        if key.endswith('_ids') or key.endswith('_disciplines') or key.endswith('_subfields'):
            effective_history[key]=set(map(str,value))
    pool: list[dict] = []
    excluded: Counter = Counter()
    seen: set[str] = set()
    for original in sorted(candidates, key=lambda item: str(item.get("id", ""))):
        item = copy.deepcopy(original)
        topic_id = str(item.get("id", ""))
        if not topic_id or topic_id in seen:
            excluded["DUPLICATE_ID"] += 1
            continue
        seen.add(topic_id)
        if 'content_status' in item and item['content_status']!='PUBLISHED':
            excluded['CONTENT_NOT_PUBLISHED']+=1
            continue
        if not item.get("title") or not item.get("primary_discipline_id") or not _traceable(item):
            excluded["UNTRACEABLE_OR_INCOMPLETE"] += 1
            continue
        item["id"] = topic_id
        item["primary_discipline_id"] = str(item["primary_discipline_id"])
        quality_features = item.get("quality_features") or {}
        if quality_features.get("duplicate") is True or quality_features.get("anomalous") is True:
            excluded["QUALITY_ANOMALY"] += 1
            continue
        item["_quality"] = _unit(item.get("quality_score"), settings["default_quality"])
        # Explicitly stale time-sensitive material loses quality; evergreen age is not truth.
        if not _evergreen(item) and quality_features.get("stale") is True:
            item["_quality"] *= 0.5
        item["_bridge"] = _bridge(item, effective_history, settings) if not history_free else []
        item["_learnability"] = learnability(item, bool(item["_bridge"]), settings)
        item["_new"] = False if history_free else _is_new(item, effective_history)
        if item["_quality"] < settings["minimum_quality"] or item["_learnability"] < settings["minimum_learnability"]:
            excluded["BELOW_PROXY_FLOOR"] += 1
            continue
        item["_tie"] = rng.random()
        item['_novelty']=_novelty(item,effective_history,settings)
        pool.append(item)
    actual = min(count, len(pool))
    reason_codes: list[str] = []
    relaxed: list[str] = []
    if actual < count:
        reason_codes.append("INSUFFICIENT_TRACEABLE_CANDIDATES")
        relaxed.append("requested_count")
    if history_free:
        reason_codes.append("HISTORY_FREE_BROAD")
    bridge_pool = [item for item in pool if item["_bridge"] and item["_new"]]
    if mode == "bridge" and len(bridge_pool) < actual:
        reason_codes.append("BRIDGE_PATH_UNAVAILABLE" if not bridge_pool else "BRIDGE_POOL_EXPANDED")
    # Full traceable pool is considered before any quota is relaxed.
    coverage = min(settings["minimum_disciplines"], count)
    cap = settings["maximum_per_discipline"]
    minimum_new = 0 if history_free else min(settings["minimum_new"], count)
    evergreen = True
    if actual and not any(_evergreen(item) for item in pool):
        evergreen = False
        relaxed.append("evergreen_presence")
        reason_codes.append("ONLY_NEWS_AVAILABLE")
    if actual == 0:
        coverage, minimum_new, evergreen = 0, 0, False
    else:
        # Ordered relaxation: opportunity quota -> primary coverage -> primary cap
        # -> evergreen mix. Sources and minimum quality/learnability never relax.
        while not _feasible(pool, [], actual, coverage, cap, minimum_new, evergreen):
            if minimum_new > 0:
                minimum_new -= 1
                if "unexplored_opportunity" not in relaxed:
                    relaxed.append("unexplored_opportunity")
                    reason_codes.append("NEW_OPPORTUNITY_UNAVAILABLE")
            elif coverage > 1:
                coverage -= 1
                if "primary_discipline_coverage" not in relaxed:
                    relaxed.append("primary_discipline_coverage")
                    reason_codes.append("DISCIPLINE_COVERAGE_UNAVAILABLE")
            elif cap < actual:
                cap += 1
                if "primary_discipline_cap" not in relaxed:
                    relaxed.append("primary_discipline_cap")
                    reason_codes.append("DISCIPLINE_CAP_RELAXED")
            elif evergreen:
                evergreen = False
                relaxed.append("evergreen_presence")
                reason_codes.append("ONLY_NEWS_AVAILABLE")
            else:
                # Defensive guard; capacity=count makes every finite pool feasible.
                raise RuntimeError("quota feasibility invariant failed")
    selected: list[dict] = []
    output_items: list[dict] = []
    weights = settings["broad_weights"] if mode == "broad" else settings["weights"]
    strata = sorted({item["primary_discipline_id"] for item in pool})
    rng.shuffle(strata)
    stratum_rank = {value: index for index, value in enumerate(strata)}
    for _ in range(actual):
        options: list[tuple[tuple, dict, dict, float]] = []
        feasibility_cache: dict[tuple, bool] = {}
        for item in pool:
            group = (item["primary_discipline_id"], item["_new"], _evergreen(item))
            if group not in feasibility_cache:
                remaining = [other for other in pool if other["id"] != item["id"]]
                feasibility_cache[group] = _feasible(remaining, selected + [item], actual, coverage, cap, minimum_new, evergreen)
            if not feasibility_cache[group]:
                continue
            if mode == "broad":
                n = 1.0
                if not history_free and item["id"] in _sets(effective_history, "recent_ids"):
                    n = 1.0 - settings["recent_penalty"]
            else:
                n = item['_novelty']
            features = {"novelty": n, "quality": round(item["_quality"], 6), "diversity": diversity(item, selected,settings['semantic_similarity']), "learnability": item["_learnability"]}
            score = sum(weights[key] * features[key] for key in FEATURES)
            if item["id"] in _sets(effective_history, "skipped_ids") and not history_free:
                score -= settings["skip_penalty"]
            score = round(_unit(score), 6)
            tie = item["_tie"] * settings["random_tiebreak"]
            if mode == "broad":
                # Equal discipline turns, seeded stratum permutation, then proxies.
                n_selected = sum(other["primary_discipline_id"] == item["primary_discipline_id"] for other in selected)
                recent = not history_free and item["id"] in _sets(effective_history, "recent_ids")
                key = (-int(recent), -n_selected, -stratum_rank[item["primary_discipline_id"]], score + tie)
            elif mode == "bridge":
                key = (int(bool(item["_bridge"]) and item["_new"]), score + tie)
            else:
                key = (score + tie,)
            options.append((key, item, features, score))
        if not options:
            raise RuntimeError("feasible reranking invariant failed")
        _, chosen, features, score = max(options, key=lambda option: option[0])
        bridge_path = chosen["_bridge"] if mode == "bridge" else []
        assumptions = []
        if chosen.get("quality_score") is None:
            assumptions.append(f"缺失质量评分，采用默认代理值 {settings['default_quality']}")
        if chosen.get("prerequisite_load") is None and (chosen.get("quality_features") or {}).get("prerequisite_load") is None:
            assumptions.append(f"缺失前置概念负担，采用中性默认值 {settings['default_prerequisite_load']}")
        if (chosen.get("quality_features") or {}).get("has_example") is not True:
            assumptions.append("未确认有可用例子，不给予例子加分")
        output_items.append({
            "topic_id": chosen["id"],
            "reason": _reason(chosen, effective_history, mode, features, bridge_path, history_free),
            "features": features,
            "score": score,
            "bridge_path": bridge_path,
            "feature_evidence": {
                "primary_discipline_id": chosen["primary_discipline_id"],
                "subfield": chosen.get("subfield"),
                "new_opportunity": None if history_free else chosen["_new"],
                "recently_exposed": None if history_free else chosen["id"] in _sets(effective_history, "recent_ids"),
                "explicitly_known": None if history_free or mode == "broad" else chosen["id"] in _sets(effective_history, "known_ids"),
                "temporary_skip": False if history_free else chosen["id"] in _sets(effective_history, "skipped_ids"),
                "quality_basis": copy.deepcopy(chosen.get("quality_features") or {}),
                "defaults": assumptions,
                "selected_before": [item["id"] for item in selected],
                "weights": copy.deepcopy(weights),
                "novelty_basis": None if history_free else novelty_basis(chosen['id'],effective_history),
                "long_term_coverage": None if history_free else copy.deepcopy(effective_history.get('coverage_windows',{})),
                "semantic_method": 'curated_bilingual_aliases_with_lexical_fallback' if settings['semantic_similarity'] else 'lexical',
            },
        })
        selected.append(chosen)
        pool = [item for item in pool if item["id"] != chosen["id"]]
    counts = Counter(item["primary_discipline_id"] for item in selected)
    achieved_new = None if history_free else sum(item["_new"] for item in selected)
    satisfied = ["source_traceable", "quality_floor", "learnability_floor"]
    if len(counts) >= min(settings["minimum_disciplines"], count):
        satisfied.append("primary_discipline_coverage")
    if all(number <= settings["maximum_per_discipline"] for number in counts.values()):
        satisfied.append("primary_discipline_cap")
    if not history_free and achieved_new is not None and achieved_new >= min(settings["minimum_new"], count):
        satisfied.append("unexplored_opportunity")
    if any(_evergreen(item) for item in selected):
        satisfied.append("evergreen_presence")
    if actual == count:
        satisfied.append("requested_count")
    message_parts = [f"已提供 {actual}/{count} 个有来源的主题，覆盖 {len(counts)} 个主学科。"]
    if "BRIDGE_PATH_UNAVAILABLE" in reason_codes:
        message_parts.append("尚无从熟悉或已探索主题出发的可靠关系路径，已扩展到广域候选；可先探索一个主题。")
    elif "BRIDGE_POOL_EXPANDED" in reason_codes:
        message_parts.append("有依据的桥梁不足以填满组合，其余条目来自广域候选并逐条标注。")
    if "INSUFFICIENT_TRACEABLE_CANDIDATES" in reason_codes:
        message_parts.append("达到质量与可学习性底线的可追溯候选不足，没有复制或补造主题。")
    if any(code in reason_codes for code in ("NEW_OPPORTUNITY_UNAVAILABLE", "DISCIPLINE_COVERAGE_UNAVAILABLE", "DISCIPLINE_CAP_RELAXED", "ONLY_NEWS_AVAILABLE")):
        message_parts.append("现有候选无法满足全部约束，已按记录的顺序放宽组合要求，来源与质量底线保持不变。")
    if history_free:
        message_parts.append("本批广域抽样完全不使用个人历史，因此未检查个人未探索比例，也可能出现已看过的主题。")
    # Canonical input snapshot, including excluded candidates, enables exact replay.
    candidate_snapshot = sorted(copy.deepcopy(candidates), key=lambda item: str(item.get("id", "")))
    fingerprint = hashlib.sha256(json.dumps(candidate_snapshot, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()
    return {
        "items": output_items,
        "constraints": {"requested": count, "actual": actual, "satisfied": satisfied, "relaxed": relaxed, "reason_codes": reason_codes, "message": "".join(message_parts), "achieved": {"primary_disciplines": len(counts), "maximum_per_discipline": max(counts.values(), default=0), "new_opportunities": achieved_new}, "applied": {"minimum_disciplines": coverage, "maximum_per_discipline": cap, "minimum_new": minimum_new, "require_evergreen": evergreen}, "excluded": dict(excluded)},
        "strategy_version": STRATEGY_VERSION,
        "seed": seed,
        "candidate_fingerprint": fingerprint,
        "candidate_snapshot": candidate_snapshot,
        "history_snapshot": {} if history_free else original_history,
        "config_snapshot": settings,
        "mode": mode,
    }


def surprise(candidates,history,*,strength='cross',history_free=False,seed=0,config=None):
    if strength not in ('gentle','cross','far'): raise ValueError('invalid exploration strength')
    weights={'gentle':{'novelty':.15,'quality':.35,'diversity':.10,'learnability':.40},
             'cross':{'novelty':.40,'quality':.25,'diversity':.10,'learnability':.25},
             'far':{'novelty':.60,'quality':.20,'diversity':.10,'learnability':.10}}
    effective={} if history_free else copy.deepcopy(history)
    effective['intensity']={'gentle':.15,'cross':.65,'far':1.0}[strength]
    result=recommend(candidates,effective,mode='unknown',count=1,seed=seed,config={'weights':weights[strength],'minimum_disciplines':1,'minimum_new':0,**(config or {})})
    if history_free:
        result['history_snapshot']={}
        result['constraints']['reason_codes'].append('HISTORY_FREE_SURPRISE')
        result['constraints']['achieved']['new_opportunities']=None
    result['surprise']={'strength':strength,'history_free':history_free}
    for item in result['items']:
        prefix='本次不使用个人历史；按合格知识库主动抽取' if history_free else {'gentle':'温和探索优先兼顾入门材料与可学习性','cross':'跨界探索提高未探索细分领域的权重','far':'完全陌生提高陌生程度权重，来源底线相同'}[strength]
        item['reason']=prefix+'；'+('选择基于材料质量与入门可读性，不能据此判断你是否了解。' if history_free else item['reason'])
        if history_free:
            for k in ('novelty_basis','new_opportunity','recently_exposed','explicitly_known','long_term_coverage'): item['feature_evidence'][k]=None
    return result
