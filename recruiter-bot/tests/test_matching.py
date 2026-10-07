"""Unit tests for the pure scoring functions (no database, no HTTP)."""

import pytest

from app.matching import (
    CandidateProfile, JobProfile, compute_matches, experience_score, score_pair,
)


def candidate(**overrides) -> CandidateProfile:
    base = dict(id=1, name="Test C.", experience_years=5, availability="immediate",
                skills=frozenset({"a", "b"}), traits=frozenset({"calm"}))
    return CandidateProfile(**{**base, **overrides})


def job(**overrides) -> JobProfile:
    base = dict(id=1, title="Test Job", min_experience=3,
                required_skills=frozenset({"a", "b"}), culture_keywords=frozenset({"calm"}))
    return JobProfile(**{**base, **overrides})


def test_perfect_match_scores_100():
    result = score_pair(candidate(), job())
    assert result is not None and result.score == 100.0


def test_no_skill_overlap_is_not_a_match():
    assert score_pair(candidate(skills=frozenset({"x"})), job()) is None


def test_partial_skill_coverage_is_proportional():
    result = score_pair(candidate(skills=frozenset({"a"})), job())
    assert result is not None and result.skill_score == 0.5


@pytest.mark.parametrize(
    "years, minimum, expected",
    [
        (2, 4, 0.5),     # under the bar: proportional shortfall
        (4, 4, 1.0),     # exactly meets it
        (12, 4, 1.0),    # up to 3x the minimum is full marks
        (24, 4, 0.7),    # 6x or more bottoms out at the floor, never zero
        (30, 0, 1.0),    # no minimum => always fine
    ],
)
def test_experience_score(years, minimum, expected):
    assert experience_score(years, minimum) == pytest.approx(expected)


def test_overqualified_never_beats_a_perfect_fit():
    fit = score_pair(candidate(experience_years=4), job(min_experience=3))
    senior = score_pair(candidate(experience_years=30), job(min_experience=3))
    assert fit.score > senior.score


def test_availability_orders_otherwise_identical_candidates():
    scores = [score_pair(candidate(availability=a), job()).score
              for a in ("immediate", "two_weeks", "not_looking")]
    assert scores == sorted(scores, reverse=True) and len(set(scores)) == 3


def test_reason_names_matched_and_missing_skills():
    result = score_pair(candidate(skills=frozenset({"a"})), job())
    assert "1/2" in result.reason and "missing b" in result.reason


def test_compute_matches_skips_non_overlapping_pairs():
    results = compute_matches(
        [candidate(id=1), candidate(id=2, skills=frozenset({"zzz"}))], [job()]
    )
    assert [r.candidate_id for r in results] == [1]
