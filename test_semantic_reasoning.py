from __future__ import annotations

from deep_rag import (
    analyze_query,
    canonical_domain_concepts,
    semantic_alignment,
    semantic_query_expansions,
)


PARAPHRASED_QUESTION = "خاور رسیده مبدأ، سرویس کنسل شده؛ هزینه‌اش چقدر می‌شود؟"
MANAGER_TRAINING = "کنسلی خاور ۴۰۰ هزار تومنه."


def test_operational_paraphrase_matches_short_manager_training() -> None:
    alignment = semantic_alignment(PARAPHRASED_QUESTION, MANAGER_TRAINING)

    assert alignment["entity_conflict"] is False
    assert alignment["core_matches"] >= 1
    assert alignment["matched_categories"] >= 3
    assert alignment["score"] >= 0.75


def test_concepts_are_stable_across_colloquial_wording() -> None:
    question = canonical_domain_concepts(PARAPHRASED_QUESTION)
    training = canonical_domain_concepts(MANAGER_TRAINING)

    expected = {"entity:خاور", "event:cancellation", "request:cost"}
    assert expected.issubset(question)
    assert expected.issubset(training)
    assert "state:origin_arrival" in question


def test_explicit_different_vehicle_is_rejected() -> None:
    alignment = semantic_alignment(
        PARAPHRASED_QUESTION,
        "هزینه کنسلی نیسان ۲۰۰ هزار تومان است.",
    )

    assert alignment["entity_conflict"] is True
    assert alignment["score"] < 0.25


def test_same_vehicle_but_unrelated_event_is_not_strong_match() -> None:
    alignment = semantic_alignment(
        PARAPHRASED_QUESTION,
        "حداکثر ظرفیت بار خاور سه تن است و هزینه حمل جداگانه محاسبه می‌شود.",
    )

    assert alignment["entity_conflict"] is False
    assert alignment["score"] < 0.62


def test_query_plan_contains_source_neutral_semantic_rewrites() -> None:
    plan = analyze_query(PARAPHRASED_QUESTION, max_subqueries=6)
    rewrites = "\n".join(plan.subqueries[1:])

    assert len(plan.subqueries) >= 3
    assert "خاور" in rewrites
    assert "کنسلی" in rewrites
    assert "هزینه" in rewrites
    assert any("مبدأ" in value for value in plan.subqueries)


def test_expansions_never_invent_an_answer_value() -> None:
    expansions = semantic_query_expansions(PARAPHRASED_QUESTION)

    assert expansions
    assert all("۴۰۰" not in value and "400" not in value for value in expansions)


def test_strong_training_alignment_is_safe_for_direct_provider_free_answer() -> None:
    alignment = semantic_alignment(PARAPHRASED_QUESTION, MANAGER_TRAINING)

    assert alignment["score"] >= 0.62
    assert alignment["entity_conflict"] is False
    assert "۴۰۰" in MANAGER_TRAINING
