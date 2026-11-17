"""Synthetic fixtures are algorithm tests, never shipped as knowledge content."""
import copy
from collections import Counter

import pytest

from app.recommendation import DEFAULT_CONFIG, diversity, learnability, novelty, recommend


def candidate(index=0, discipline=None, **overrides):
    result = {"id": f"t{index}", "title": f"Concept {index}", "primary_discipline_id": discipline or f"d{index % 10}", "subfield": f"s{index % 20}", "summary": "A beginner summary describing a specific concept.", "sources": [{"url": f"https://example.org/concept/{index}"}], "quality_score": 0.8, "prerequisite_load": 0.2, "quality_features": {"has_example": True}}
    result.update(overrides)
    return result


def library(size=50):
    return [candidate(index) for index in range(size)]


def ids(result):
    return [item["topic_id"] for item in result["items"]]


def test_weights_ranges_and_defaults():
    batch = recommend(library(), {}, seed=14)
    assert sum(DEFAULT_CONFIG["weights"].values()) == 1
    for item in batch["items"]:
        assert all(0 <= score <= 1 for score in item["features"].values())
        assert 0 <= item["score"] <= 1
    one = candidate(1)
    del one["quality_score"]
    del one["prerequisite_load"]
    result = recommend([one], {}, count=1)["items"][0]
    assert result["features"]["quality"] == 0.6
    assert any("默认" in text for text in result["feature_evidence"]["defaults"])
    assert learnability(candidate(summary=None), config=None) < learnability(candidate())
    assert 0 <= novelty(candidate(), {"intensity": float("inf")}) <= 1


@pytest.mark.parametrize("config", [
    {"weights": {"novelty": 1}},
    {"weights": {"novelty": 0.5, "quality": 0.5, "diversity": 0.5, "learnability": 0.5}},
    {"minimum_quality": -0.1}, {"maximum_per_discipline": 0}, {"bogus": True},
])
def test_invalid_configuration_rejected(config):
    with pytest.raises(ValueError):
        recommend(library(), {}, config=config)


def test_diversity_is_dynamic_and_secondary_tags_never_count():
    first = candidate(1, "one", related_disciplines=["two", "three", "four"])
    repeated = candidate(2, "one", subfield=first["subfield"])
    different = candidate(3, "two")
    assert diversity(first, []) == 1
    assert diversity(repeated, [first]) < diversity(different, [first])
    batch = recommend([candidate(i, "one", related_disciplines=[str(j) for j in range(10)]) for i in range(6)], {})
    assert batch["constraints"]["achieved"]["primary_disciplines"] == 1
    assert "primary_discipline_coverage" in batch["constraints"]["relaxed"]


def test_diversity_cap_four_disciplines_and_two_new_opportunities():
    candidates = library(60)
    history = {"explored_disciplines": ["d0", "d1"], "explored_subfields": [f"s{i}" for i in range(4)]}
    batch = recommend(candidates, history, seed=43)
    selected = [next(item for item in candidates if item["id"] == value) for value in ids(batch)]
    counts = Counter(item["primary_discipline_id"] for item in selected)
    assert len(selected) == 5 and len(counts) >= 4 and max(counts.values()) <= 2
    assert batch["constraints"]["achieved"]["new_opportunities"] >= 2
    assert not batch["constraints"]["relaxed"]


def test_feasible_greedy_reserves_scarce_new_topics():
    candidates = [candidate(i, "old", subfield="old") for i in range(6)]
    candidates += [candidate(10, "new1"), candidate(11, "new2"), candidate(12, "old2"), candidate(13, "old3")]
    batch = recommend(candidates, {"explored_disciplines": ["old", "old2", "old3"], "explored_subfields": ["old", "s12", "s13"]}, seed=1)
    assert {"t10", "t11"} <= set(ids(batch))
    assert batch["constraints"]["achieved"]["primary_disciplines"] >= 4


def test_recent_exposure_and_explicit_known_are_suppressed():
    candidates = library()
    first = recommend(candidates, {}, seed=20)
    recent = ids(first)
    second = recommend(candidates, {"recent_ids": recent}, seed=20)
    assert not set(recent) & set(ids(second))
    assert novelty(candidate(), {"known_ids": ["t0"]}) < novelty(candidate(), {})
    assert novelty(candidate(), {"unfamiliar_ids": ["t0"]}) > novelty(candidate(), {})
    assert novelty(candidate(), {"intensity": 1}) > novelty(candidate(), {"intensity": 0})


def test_recent_lexical_similarity_penalizes_nearby_topics():
    topic = candidate(title="Quantum entanglement", subfield="Quantum physics")
    assert novelty(topic, {"recent_candidates": [candidate(99, title="Quantum entanglement", subfield="Quantum physics")]}) < novelty(topic, {})


def test_unexplored_fields_get_opportunity_despite_familiar_high_quality():
    candidates = [candidate(i, "familiar", subfield="old", quality_score=1) for i in range(20)]
    candidates += [candidate(100 + i, f"new{i}", quality_score=0.7) for i in range(5)]
    history = {"familiar_disciplines": ["familiar"], "explored_disciplines": ["familiar"], "explored_subfields": ["old"]}
    batch = recommend(candidates, history, seed=3)
    assert batch["constraints"]["achieved"]["new_opportunities"] >= 2


def path(from_id, to_id):
    return [{"from_id": from_id, "from_title": "Starting concept", "from_discipline_id": "familiar", "to_id": to_id, "type": "manual_teaching", "label": "共同原理", "explanation": "The provided source explains a shared principle.", "source_url": "https://example.org/evidence"}]


def test_modes_have_real_policy_differences():
    candidates = library(50)
    paths = {"t1": path("anchor", "t1"), "t12": path("anchor", "t12")}
    history = {"known_ids": ["anchor"], "bridge_paths": paths}
    bridge = recommend(candidates, history, "bridge", seed=5)
    assert ids(bridge)[:2] == ["t1", "t12"] or set(ids(bridge)[:2]) == {"t1", "t12"}
    assert all(item["bridge_path"] for item in bridge["items"][:2])
    assert "BRIDGE_POOL_EXPANDED" in bridge["constraints"]["reason_codes"]
    broad = recommend(candidates, history, "broad", seed=5)
    assert broad["items"][0]["feature_evidence"]["weights"] != bridge["items"][0]["feature_evidence"]["weights"]
    assert "分层抽样" in broad["items"][0]["reason"]
    unknown = recommend(candidates, history, "unknown", seed=5)
    assert all(not item["bridge_path"] for item in unknown["items"])


def test_bridge_rejects_unreliable_or_unconnected_paths_and_degrades_honestly():
    candidates = library()
    invalid = path("unexplored-origin", "t1")
    batch = recommend(candidates, {"bridge_paths": {"t1": invalid}}, "bridge")
    assert "BRIDGE_PATH_UNAVAILABLE" in batch["constraints"]["reason_codes"]
    invalid[0]["type"] = "ai_analogy"
    batch = recommend(candidates, {"known_ids": ["unexplored-origin"], "bridge_paths": {"t1": invalid}}, "bridge")
    assert not any(item["bridge_path"] for item in batch["items"])
    disconnected = path("known", "t9") + path("other", "t1")
    batch = recommend(candidates, {"known_ids": ["known"], "bridge_paths": {"t1": disconnected}}, "bridge")
    assert not any(item["bridge_path"] for item in batch["items"])


def test_history_free_broad_is_strictly_history_independent():
    candidates = library()
    first = recommend(candidates, {"broad_use_history": False}, "broad", seed=15)
    second = recommend(candidates, {"broad_use_history": False, "known_ids": [f"t{i}" for i in range(50)], "recent_ids": [f"t{i}" for i in range(25)], "skipped_ids": [f"t{i}" for i in range(25)], "explored_disciplines": [f"d{i}" for i in range(10)], "bridge_paths": {"t1": path("t2", "t1")}}, "broad", seed=15)
    assert first == second
    assert first["history_snapshot"] == {}
    assert first["constraints"]["achieved"]["new_opportunities"] is None


def test_history_aware_broad_reduces_recent_exposure():
    candidates = library()
    first = recommend(candidates, {}, "broad", seed=10)
    second = recommend(candidates, {"recent_ids": ids(first)}, "broad", seed=10)
    assert not set(ids(first)) & set(ids(second))


def test_insufficient_candidates_never_duplicate_or_invent():
    batch = recommend([candidate(1), candidate(1), candidate(2, sources=[])], {})
    assert ids(batch) == ["t1"]
    assert batch["constraints"]["actual"] == 1
    assert "INSUFFICIENT_TRACEABLE_CANDIDATES" in batch["constraints"]["reason_codes"]
    assert "source_traceable" not in batch["constraints"]["relaxed"]
    empty = recommend([], {})
    assert empty["items"] == [] and empty["constraints"]["actual"] == 0


def test_quality_and_learning_floors_are_not_relaxed():
    candidates = [candidate(1, quality_score=0.1), candidate(2, summary="", prerequisite_load=1), candidate(3, quality_features={"anomalous": True})]
    assert recommend(candidates, {})["constraints"]["actual"] == 0


def test_news_mix_and_all_news_fallback():
    candidates = [candidate(i, content_type="news", quality_score=1) for i in range(20)] + [candidate(99, content_type="evergreen", quality_score=0.5)]
    batch = recommend(candidates, {})
    assert "t99" in ids(batch)
    all_news = recommend(candidates[:-1], {})
    assert "ONLY_NEWS_AVAILABLE" in all_news["constraints"]["reason_codes"]
    assert all_news["constraints"]["achieved"]["primary_disciplines"] >= 4


def test_skip_is_weak_item_feedback_not_discipline_ban():
    candidates = [candidate(i, "one") for i in range(5)]
    batch = recommend(candidates, {"skipped_ids": ["t0"]})
    assert set(ids(batch)) == {f"t{i}" for i in range(5)}
    first = recommend(library(), {}, seed=7)
    second = recommend(library(), {"skipped_ids": ids(first)}, seed=7)
    assert set(ids(first)) != set(ids(second))
    # Expiry is handled by service history selection; omission restores behaviour.
    assert recommend(library(), {}, seed=7) == first


def test_reproducibility_input_order_and_no_mutation():
    candidates, history = library(), {"recent_ids": ["t1", "t2"]}
    originals = copy.deepcopy((candidates, history))
    first = recommend(candidates, history, seed=194)
    second = recommend(list(reversed(candidates)), history, seed=194)
    assert first == second
    assert (candidates, history) == originals
    replay = recommend(first["candidate_snapshot"], first["history_snapshot"], first["mode"], first["constraints"]["requested"], first["seed"], first["config_snapshot"])
    assert replay == first


def test_explanation_matches_actual_features_and_score():
    batch = recommend(library(), {}, seed=1)
    for item in batch["items"]:
        evidence = item["feature_evidence"]
        expected = sum(evidence["weights"][key] * item["features"][key] for key in item["features"])
        assert item["score"] == pytest.approx(expected, abs=1e-6)
        assert "尚无探索记录" in item["reason"]
        assert evidence["new_opportunity"] is True
        assert len(evidence["selected_before"]) == batch["items"].index(item)


def test_user_snapshots_are_isolated_without_global_history():
    candidates = library()
    baseline = recommend(candidates, {}, seed=19)
    private = recommend(candidates, {"recent_ids": ids(baseline), "known_ids": ids(baseline)}, seed=19)
    assert set(ids(private)) != set(ids(baseline))
    assert recommend(candidates, {}, seed=19) == baseline


def test_evaluation_uses_equal_fixed_prefixes_and_never_fabricates_feedback():
    import importlib.util
    from pathlib import Path
    specification = importlib.util.spec_from_file_location("offline_evaluate", Path(__file__).resolve().parents[2] / "scripts" / "evaluate.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    payload = {"topics": library(50)}
    report = module.evaluate(payload)
    assert report == module.evaluate(payload)
    assert report["kind"] == "synthetic_history_algorithm_behaviour_only"
    groups = {}
    for trial in report["trials"]:
        groups.setdefault((trial["profile"], trial["seed"]), []).append(trial)
        assert trial["self_reported_unfamiliar_ratio"] is None
        assert len(trial["topic_ids"]) <= 5
    assert len(groups) == 15
    assert all(len(group) == 3 and len({row["history_fingerprint"] for row in group}) == 1 for group in groups.values())
    assert all(row["batch_count"] == 15 and row["requested_topics"] == 75 for row in report["aggregate"].values())
    assert report["aggregate"]["anti_cocoon"]["constraint_satisfaction_rate"] == 1


def test_traceability_cannot_be_bypassed_by_boolean_or_malformed_url():
    candidates = [candidate(1, sources=[], quality_features={"source_traceable": True}), candidate(2, sources=[{"url": "https://["}]), candidate(3, sources=[{"url": "https://secret@example.org/page"}]), candidate(4, sources=[{"url": "javascript:alert(1)"}])]
    assert recommend(candidates, {})["items"] == []
