"""Matching engine: pure functions, no database access.

Keeping scoring free of I/O means it can be unit-tested with plain dicts and
tuned without touching SQL. The database layer (see ``repository.py``) feeds it
data and stores its output.

Score model (0-100)
-------------------
    score = 100 * ( W_SKILLS * skill_score
                  + W_EXPERIENCE * experience_score
                  + W_CULTURE * culture_score
                  + W_AVAILABILITY * availability_score )

Every component is normalised to 0..1 so the weights read as percentages.
A pair with zero skill overlap is *not a match* and is never produced.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Tunable knobs -----------------------------------------------------------
W_SKILLS = 0.60        # Can they actually do the job?
W_EXPERIENCE = 0.20    # Do they meet the bar without being wildly over it?
W_CULTURE = 0.10       # Trait <-> culture keyword overlap (soft signal).
W_AVAILABILITY = 0.10  # Can they start soon?

AVAILABILITY_SCORE = {"immediate": 1.0, "two_weeks": 0.7, "not_looking": 0.0}
AVAILABILITY_LABEL = {
    "immediate": "available immediately",
    "two_weeks": "available in 2 weeks",
    "not_looking": "not currently looking",
}

# Being over-qualified is only mildly penalised: experience beyond
# OVERQUALIFIED_RATIO x the minimum loses points, bottoming out at the floor.
OVERQUALIFIED_RATIO = 3.0
OVERQUALIFIED_FLOOR = 0.7
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateProfile:
    id: int
    name: str
    experience_years: int
    availability: str
    skills: frozenset[str]
    traits: frozenset[str]


@dataclass(frozen=True)
class JobProfile:
    id: int
    title: str
    min_experience: int
    required_skills: frozenset[str]
    culture_keywords: frozenset[str]


@dataclass(frozen=True)
class MatchResult:
    candidate_id: int
    job_id: int
    score: float
    skill_score: float
    experience_score: float
    culture_score: float
    availability_score: float
    reason: str


def skill_score(candidate: CandidateProfile, job: JobProfile) -> float:
    """Share of the job's required skills the candidate covers (recall, 0..1)."""
    if not job.required_skills:
        return 0.0
    return len(candidate.skills & job.required_skills) / len(job.required_skills)


def experience_score(years: int, minimum: int) -> float:
    """Experience fit against the job's minimum.

    * Below the minimum: proportional shortfall (2 yrs vs 4 min -> 0.5).
    * Meeting it, up to OVERQUALIFIED_RATIO x minimum: full marks.
    * Beyond that: linear decay down to OVERQUALIFIED_FLOOR, which is reached
      at 2 x the ratio. Seniority is a mild retention risk, not a disqualifier.
    """
    if minimum <= 0:
        return 1.0
    if years < minimum:
        return years / minimum
    ratio = years / minimum
    if ratio <= OVERQUALIFIED_RATIO:
        return 1.0
    decay_span = OVERQUALIFIED_RATIO  # ratio 3x -> 6x covers the whole decay
    progress = min((ratio - OVERQUALIFIED_RATIO) / decay_span, 1.0)
    return 1.0 - progress * (1.0 - OVERQUALIFIED_FLOOR)


def culture_score(candidate: CandidateProfile, job: JobProfile) -> float:
    """Share of the job's culture keywords found among the candidate's traits."""
    if not job.culture_keywords:
        return 0.0
    return len(candidate.traits & job.culture_keywords) / len(job.culture_keywords)


def availability_score(availability: str) -> float:
    return AVAILABILITY_SCORE[availability]


def build_reason(candidate: CandidateProfile, job: JobProfile, parts: dict[str, float]) -> str:
    matched = sorted(candidate.skills & job.required_skills)
    missing = sorted(job.required_skills - candidate.skills)
    culture = sorted(candidate.traits & job.culture_keywords)

    clauses = [f"Covers {len(matched)}/{len(job.required_skills)} required skills ({', '.join(matched)})"]
    if missing:
        clauses.append(f"missing {', '.join(missing)}")

    gap = candidate.experience_years - job.min_experience
    if gap < 0:
        clauses.append(f"{candidate.experience_years} yrs experience, {-gap} below the {job.min_experience}-yr minimum")
    elif parts["experience"] < 1.0:
        clauses.append(f"{candidate.experience_years} yrs experience, well over the {job.min_experience}-yr minimum")
    else:
        clauses.append(f"{candidate.experience_years} yrs experience vs {job.min_experience} required")

    if culture:
        clauses.append(f"culture fit: {', '.join(culture)}")
    clauses.append(AVAILABILITY_LABEL[candidate.availability])
    return "; ".join(clauses) + "."


def score_pair(candidate: CandidateProfile, job: JobProfile) -> MatchResult | None:
    """Score one candidate/job pair. Returns None if there is no skill overlap."""
    s = skill_score(candidate, job)
    if s == 0.0:
        return None

    e = experience_score(candidate.experience_years, job.min_experience)
    c = culture_score(candidate, job)
    a = availability_score(candidate.availability)

    total = 100 * (W_SKILLS * s + W_EXPERIENCE * e + W_CULTURE * c + W_AVAILABILITY * a)
    reason = build_reason(candidate, job, {"skill": s, "experience": e, "culture": c, "availability": a})
    return MatchResult(
        candidate_id=candidate.id,
        job_id=job.id,
        score=round(total, 2),
        skill_score=round(s, 4),
        experience_score=round(e, 4),
        culture_score=round(c, 4),
        availability_score=a,
        reason=reason,
    )


def compute_matches(candidates: list[CandidateProfile], jobs: list[JobProfile]) -> list[MatchResult]:
    """Score every candidate against every job (O(C x J), fine at this scale)."""
    results = []
    for job in jobs:
        for candidate in candidates:
            result = score_pair(candidate, job)
            if result is not None:
                results.append(result)
    return results
