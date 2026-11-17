#!/usr/bin/env python3
"""Offline behaviour evaluation. Synthetic histories are NOT user-effect evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.recommendation import DEFAULT_CONFIG, learnability, recommend  # noqa: E402
from app.recommendation.engine import _evergreen, _traceable, _unit  # noqa: E402

SEEDS = [11, 29, 47, 83, 101]
BUDGET = 5


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def eligible(topics):
    # The same availability, traceability, and proxy floors apply to all policies.
    eligible_topics = []
    # Replay filter using the same documented floors, without using policy ranks.
    for topic in topics:
        source_ok = _traceable(topic)
        features = topic.get("quality_features", {})
        quality = _unit(topic.get("quality_score"), DEFAULT_CONFIG["default_quality"])
        if not _evergreen(topic) and features.get("stale") is True:
            quality *= 0.5
        if source_ok and topic.get("title") and topic.get("primary_discipline_id") and quality >= 0.4 and learnability(topic) >= 0.25 and not features.get("duplicate") and not features.get("anomalous"):
            eligible_topics.append(topic)
    return eligible_topics


def profiles(topics):
    disciplines = sorted({item["primary_discipline_id"] for item in topics})
    snapshots = []
    for index, label in enumerate(["合成档案A：两个熟悉领域", "合成档案B：另两个熟悉领域", "合成档案C：无初始偏好"]):
        familiar = disciplines[index * 3:index * 3 + 2] if index < 2 else []
        explored = [item for item in topics if item["primary_discipline_id"] in familiar][:8]
        # An explicit fixed prefix, not generated or extended by any policy.
        recent = sorted(topics, key=lambda item: item["id"])[index * 3:index * 3 + 8]
        history = {"familiar_disciplines": familiar, "explored_ids": [item["id"] for item in explored], "explored_disciplines": sorted({item["primary_discipline_id"] for item in explored}), "explored_subfields": sorted({item.get("subfield", "") for item in explored}), "recent_ids": [item["id"] for item in recent], "recent_candidates": [{key: item.get(key, "") for key in ("id", "title", "subfield")} for item in recent], "known_ids": [], "unfamiliar_ids": [], "skipped_ids": [], "intensity": 0.5, "broad_use_history": True}
        snapshots.append({"label": label, "history": history, "fingerprint": fingerprint(history)})
    return snapshots


def interest_baseline(topics, history, seed):
    rng = random.Random(seed)
    familiar = set(history["familiar_disciplines"])
    scored = [(int(item["primary_discipline_id"] in familiar), item.get("quality_score", 0.6), rng.random(), item) for item in sorted(topics, key=lambda item: item["id"])]
    return [value[-1] for value in sorted(scored, key=lambda row: row[:3], reverse=True)[:BUDGET]], False


def stratified_baseline(topics, history, seed):
    rng = random.Random(seed)
    buckets = defaultdict(list)
    for item in sorted(topics, key=lambda item: item["id"]):
        buckets[item["primary_discipline_id"]].append(item)
    disciplines = sorted(buckets)
    rng.shuffle(disciplines)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    chosen = []
    while len(chosen) < BUDGET and any(buckets.values()):
        for discipline in disciplines:
            if buckets[discipline] and len(chosen) < BUDGET:
                chosen.append(buckets[discipline].pop())
    return chosen, False


def anti_cocoon(topics, history, seed):
    result = recommend(topics, history, mode="unknown", count=BUDGET, seed=seed)
    by_id = {item["id"]: item for item in topics}
    return [by_id[item["topic_id"]] for item in result["items"]], bool(result["constraints"]["relaxed"])


def batch_metrics(selected, history, catalogue_domains):
    counts = Counter(item["primary_discipline_id"] for item in selected)
    actual = len(selected)
    entropy = -sum((count / actual) * math.log(count / actual) for count in counts.values()) if actual else None
    new = sum(item["id"] not in history["explored_ids"] and (item["primary_discipline_id"] not in history["explored_disciplines"] or item.get("subfield") not in history["explored_subfields"]) for item in selected)
    repeat = sum(item["id"] in history["recent_ids"] for item in selected)
    new_topics = sum(item["id"] not in history["explored_ids"] for item in selected)
    constraint_ok = actual == BUDGET and len(counts) >= 4 and max(counts.values(), default=0) <= 2 and new >= 2 and any(item.get("content_type", "evergreen") not in {"news", "hot", "breaking"} for item in selected)
    return {"primary_discipline_coverage": len(counts), "discipline_entropy_nats": entropy, "normalized_entropy_catalogue": entropy / math.log(catalogue_domains) if entropy is not None and catalogue_domains > 1 else 0.0 if entropy is not None else None, "new_domain_or_subfield_ratio": new / actual if actual else None, "new_topic_ratio": new_topics / actual if actual else None, "recent_exposure_repeat_ratio": repeat / actual if actual else None, "constraint_satisfied": constraint_ok, "quality_proxy": sum(item.get("quality_score", 0.6) for item in selected) / actual if actual else None, "learnability_proxy": sum(learnability(item) for item in selected) / actual if actual else None, "actual_count": actual, "self_reported_unfamiliar_ratio": None}


def evaluate(payload):
    topics = eligible(sorted(payload["topics"], key=lambda item: item["id"]))
    if not topics:
        raise ValueError("种子库没有达到共同过滤底线的主题，无法进行可比评估。")
    catalogue_domains = len({item["primary_discipline_id"] for item in topics})
    history_prefixes = profiles(topics)
    policies = {"interest_baseline": interest_baseline, "stratified_random_baseline": stratified_baseline, "anti_cocoon": anti_cocoon}
    trials = []
    for profile in history_prefixes:
        for seed in SEEDS:
            for policy_name, policy in policies.items():
                chosen, degraded = policy(topics, profile["history"], seed)
                metrics = batch_metrics(chosen, profile["history"], catalogue_domains)
                trials.append({"profile": profile["label"], "history_fingerprint": profile["fingerprint"], "seed": seed, "policy": policy_name, "topic_ids": [item["id"] for item in chosen], "degraded": degraded, **metrics})
    aggregate = {}
    for policy in policies:
        rows = [row for row in trials if row["policy"] == policy]
        metrics = {}
        for key in ("primary_discipline_coverage", "discipline_entropy_nats", "normalized_entropy_catalogue", "new_domain_or_subfield_ratio", "new_topic_ratio", "recent_exposure_repeat_ratio", "quality_proxy", "learnability_proxy"):
            values = [row[key] for row in rows if row[key] is not None]
            metrics[key] = round(sum(values) / len(values), 6) if values else None
        metrics.update(batch_count=len(rows), requested_topics=len(rows) * BUDGET, actual_topics=sum(row["actual_count"] for row in rows), constraint_satisfaction_rate=sum(row["constraint_satisfied"] for row in rows) / len(rows), degradation_rate=sum(row["degraded"] for row in rows) / len(rows), self_reported_unfamiliar_ratio=None)
        aggregate[policy] = metrics
    return {"kind": "synthetic_history_algorithm_behaviour_only", "catalogue_count": len(topics), "catalogue_primary_disciplines": catalogue_domains, "catalogue_fingerprint": fingerprint(topics), "seeds": SEEDS, "budget_per_batch": BUDGET, "history_prefixes": history_prefixes, "definitions": {"shared_inputs": "三个策略读取相同完整候选库、相同固定历史前缀和相同每批五条预算；多随机种子。历史不随策略扩展，没有未来行为。", "proxy_filter": "全部策略共用：可追溯 URL、质量代理≥0.4、可学习性代理≥0.25、排除已标记重复或异常。", "coverage": "每批实际主题涉及的唯一主学科数量；关联标签不计。", "entropy": "逐批 H=-Σp ln p，单位 nats；归一化版本除以 ln(当前共同候选库主学科总数)，不是除以批次大小。", "new_opportunity": "实际推荐中，主题未探索且其主学科或细分主题未探索的比例。", "new_topic": "实际推荐中，没有首次详情打开记录的主题比例。", "repeat": "实际推荐中，出现在预设最近7天曝光前缀的主题比例；前缀为合成数据，不是实际用户事件。", "constraint": "每批五条、至少四主学科、每主学科≤2、至少两条新领域或细分主题机会、至少一条非热点内容全部满足的批次比例。", "degradation": "策略主动记录放宽约束的批次/总批次。两种基线无放宽流程，记为0；这不代表它们满足约束，需结合约束满足率。", "proxy_means": "质量和可学习性为实际推荐主题代理值的逐批均值，再对批次等权平均；不是事实正确率或学习成绩。", "self_report": "无真实反馈，自述陌生比例不可计算，JSON为null。合成画像不生成自述陌生标签。", "excluded": "无实际推荐的批次比例/均值分母排除；仍计入约束失败与降级率。固定种子和所有主题ID保留以复现。", "limits": "仅评估算法行为，不证明提升知识掌握、认知能力或真实用户的陌生比例。"}, "aggregate": aggregate, "trials": trials}


def markdown(report):
    lines = ["# 推荐离线评估", "", "这是合成历史的算法行为测试，不是真实用户实验，也不证明学习效果提高。", "", f"共同候选库：{report['catalogue_count']} 个主题、{report['catalogue_primary_disciplines']} 个主学科；3 个固定合成历史，5 个固定种子 {SEEDS}，每个策略 {len(SEEDS) * 3} 批、每批 {BUDGET} 条。", "", "| 策略 | 平均主学科数 | 归一化熵 | 新领域/细分主题比例 | 近期重复率 | 约束满足率 | 主动降级率 | 质量代理 | 可学习性代理 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    labels = {"interest_baseline": "兴趣偏好基线", "stratified_random_baseline": "分层广域随机基线", "anti_cocoon": "反信息茧房策略"}
    for name, row in report["aggregate"].items():
        lines.append(f"| {labels[name]} | {row['primary_discipline_coverage']:.2f} | {row['normalized_entropy_catalogue']:.3f} | {row['new_domain_or_subfield_ratio']:.1%} | {row['recent_exposure_repeat_ratio']:.1%} | {row['constraint_satisfaction_rate']:.1%} | {row['degradation_rate']:.1%} | {row['quality_proxy']:.3f} | {row['learnability_proxy']:.3f} |")
    lines += ["", "自述陌生比例：**不可计算（没有真实反馈）**。", "", "## 口径与限制", ""]
    lines += [f"- {value}" for value in report["definitions"].values()]
    lines += ["", "## 复现", "", "```sh", "python3 scripts/evaluate.py", "```", "", "完整逐批种子、历史指纹、主题ID和分母见 `docs/evaluation-results.json`。如种子库发生变化，需重新运行，不能把旧结果用于新候选库。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds-file", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "evaluation-results.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "docs" / "EVALUATION.md")
    args = parser.parse_args()
    seeds_file = args.seeds_file
    if seeds_file is None:
        options = sorted((ROOT / "data" / "seeds").glob("*.json"))
        options = [file for file in options if isinstance(json.loads(file.read_text()), dict) and "topics" in json.loads(file.read_text())]
        if len(options) != 1:
            parser.error("请通过 --seeds-file 指定包含 topics 的种子 JSON 文件。")
        seeds_file = options[0]
    payload = json.loads(seeds_file.read_text())
    report = evaluate(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    args.markdown.write_text(markdown(report))
    print(json.dumps({"catalogue_count": report["catalogue_count"], "primary_disciplines": report["catalogue_primary_disciplines"], "output": str(args.output), "markdown": str(args.markdown), "aggregate": report["aggregate"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
