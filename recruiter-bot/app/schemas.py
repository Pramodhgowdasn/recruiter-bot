"""Pydantic models: request validation and response shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Availability = Literal["immediate", "two_weeks", "not_looking"]

_AVAILABILITY_ALIASES = {
    "immediate": "immediate",
    "immediately": "immediate",
    "2 weeks": "two_weeks",
    "two weeks": "two_weeks",
    "two_weeks": "two_weeks",
    "not looking": "not_looking",
    "not_looking": "not_looking",
}


def _clean_tags(values: list[str]) -> list[str]:
    """Lower-case, trim, drop blanks and de-duplicate while keeping order."""
    seen: dict[str, None] = {}
    for value in values:
        tag = value.strip().lower()
        if "," in tag:
            raise ValueError(f"tag {value!r} must not contain a comma")
        if tag:
            seen.setdefault(tag)
    return list(seen)


class CandidateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    skills: list[str] = Field(min_length=1)
    experience_years: int = Field(ge=0, le=60)
    availability: Availability
    traits: list[str] = []
    quirk: str | None = None

    @field_validator("availability", mode="before")
    @classmethod
    def _normalise_availability(cls, v: object) -> object:
        if isinstance(v, str):
            return _AVAILABILITY_ALIASES.get(v.strip().lower(), v)
        return v

    @field_validator("skills", "traits")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class JobIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    required_skills: list[str] = Field(min_length=1)
    min_experience: int = Field(ge=0, le=60)
    culture_keywords: list[str] = []
    tagline: str | None = None

    @field_validator("required_skills", "culture_keywords")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class IngestPayload(BaseModel):
    candidates: list[CandidateIn] = []
    jobs: list[JobIn] = []


class IngestResult(BaseModel):
    candidates_upserted: int
    jobs_upserted: int
    matches_computed: int


class CandidateOut(BaseModel):
    id: int
    name: str
    experience_years: int
    availability: Availability
    skills: list[str]
    traits: list[str]
    quirk: str | None


class JobOut(BaseModel):
    id: int
    title: str
    min_experience: int
    required_skills: list[str]
    culture_keywords: list[str]
    tagline: str | None


class ScoreBreakdown(BaseModel):
    skills: float
    experience: float
    culture: float
    availability: float


class CandidateMatch(BaseModel):
    rank: int
    candidate_id: int
    name: str
    score: float
    breakdown: ScoreBreakdown
    availability: Availability
    reason: str


class JobMatch(BaseModel):
    rank: int
    job_id: int
    title: str
    score: float
    breakdown: ScoreBreakdown
    reason: str


class JobMatches(BaseModel):
    job: JobOut
    matches: list[CandidateMatch]


class CandidateMatches(BaseModel):
    candidate: CandidateOut
    matches: list[JobMatch]
