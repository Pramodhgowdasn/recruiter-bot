"""All SQL lives here. Hand-written, parameterised statements only.

Values are always bound with ``?`` placeholders, never string-formatted into
the query, so there is no SQL-injection surface.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from .matching import CandidateProfile, JobProfile, MatchResult, compute_matches
from .schemas import CandidateIn, JobIn

# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #

# GROUP_CONCAT collapses each junction table into one comma-separated column so
# a candidate (or job) comes back as a single row. Tags are validated to never
# contain commas on the way in (see schemas._clean_tags).
_CANDIDATES_SQL = """
SELECT c.id, c.name, c.experience_years, c.availability, c.quirk,
       (SELECT GROUP_CONCAT(s.name, ',')
          FROM candidate_skills cs JOIN skills s ON s.id = cs.skill_id
         WHERE cs.candidate_id = c.id) AS skills,
       (SELECT GROUP_CONCAT(t.name, ',')
          FROM candidate_traits ct JOIN traits t ON t.id = ct.trait_id
         WHERE ct.candidate_id = c.id) AS traits
  FROM candidates c
 WHERE (:id IS NULL OR c.id = :id)
 ORDER BY c.id
"""

_JOBS_SQL = """
SELECT j.id, j.title, j.min_experience, j.tagline,
       (SELECT GROUP_CONCAT(s.name, ',')
          FROM job_required_skills js JOIN skills s ON s.id = js.skill_id
         WHERE js.job_id = j.id) AS required_skills,
       (SELECT GROUP_CONCAT(t.name, ',')
          FROM job_culture_keywords jk JOIN traits t ON t.id = jk.trait_id
         WHERE jk.job_id = j.id) AS culture_keywords
  FROM jobs j
 WHERE (:id IS NULL OR j.id = :id)
 ORDER BY j.id
"""

# Ranking order is the single source of truth for "who is best":
#   1. total score, 2. skill coverage, 3. sooner availability, 4. name (stable).
_JOB_MATCHES_SQL = """
SELECT m.candidate_id, c.name, c.availability,
       m.score, m.skill_score, m.experience_score, m.culture_score,
       m.availability_score, m.reason
  FROM matches m
  JOIN candidates c ON c.id = m.candidate_id
 WHERE m.job_id = :job_id
   AND m.score >= :min_score
   AND (:available_only = 0 OR c.availability <> 'not_looking')
 ORDER BY m.score DESC, m.skill_score DESC, m.availability_score DESC, c.name ASC
 LIMIT :limit
"""

_CANDIDATE_MATCHES_SQL = """
SELECT m.job_id, j.title,
       m.score, m.skill_score, m.experience_score, m.culture_score,
       m.availability_score, m.reason
  FROM matches m
  JOIN jobs j ON j.id = m.job_id
 WHERE m.candidate_id = :candidate_id
   AND m.score >= :min_score
 ORDER BY m.score DESC, m.skill_score DESC, j.title ASC
 LIMIT :limit
"""


def _split(value: str | None) -> list[str]:
    return sorted(value.split(",")) if value else []


def fetch_candidates(conn: sqlite3.Connection, candidate_id: int | None = None) -> list[dict]:
    rows = conn.execute(_CANDIDATES_SQL, {"id": candidate_id}).fetchall()
    return [
        {**dict(r), "skills": _split(r["skills"]), "traits": _split(r["traits"])}
        for r in rows
    ]


def fetch_jobs(conn: sqlite3.Connection, job_id: int | None = None) -> list[dict]:
    rows = conn.execute(_JOBS_SQL, {"id": job_id}).fetchall()
    return [
        {**dict(r), "required_skills": _split(r["required_skills"]),
         "culture_keywords": _split(r["culture_keywords"])}
        for r in rows
    ]


def fetch_job_matches(
    conn: sqlite3.Connection, job_id: int, *, limit: int, min_score: float, available_only: bool
) -> list[sqlite3.Row]:
    return conn.execute(
        _JOB_MATCHES_SQL,
        {"job_id": job_id, "limit": limit, "min_score": min_score, "available_only": int(available_only)},
    ).fetchall()


def fetch_candidate_matches(
    conn: sqlite3.Connection, candidate_id: int, *, limit: int, min_score: float
) -> list[sqlite3.Row]:
    return conn.execute(
        _CANDIDATE_MATCHES_SQL,
        {"candidate_id": candidate_id, "limit": limit, "min_score": min_score},
    ).fetchall()


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def _ensure_tag(conn: sqlite3.Connection, table: str, name: str) -> None:
    # `table` is only ever one of two hard-coded literals below, never user input.
    conn.execute(f"INSERT INTO {table} (name) VALUES (?) ON CONFLICT (name) DO NOTHING", (name,))


def upsert_candidate(conn: sqlite3.Connection, c: CandidateIn) -> int:
    """Insert or update by (unique) name, then rebuild the skill/trait links."""
    candidate_id: int = conn.execute(
        """
        INSERT INTO candidates (name, experience_years, availability, quirk)
        VALUES (:name, :experience_years, :availability, :quirk)
        ON CONFLICT (name) DO UPDATE SET
            experience_years = excluded.experience_years,
            availability     = excluded.availability,
            quirk            = excluded.quirk
        RETURNING id
        """,
        c.model_dump(include={"name", "experience_years", "availability", "quirk"}),
    ).fetchone()["id"]

    conn.execute("DELETE FROM candidate_skills WHERE candidate_id = ?", (candidate_id,))
    conn.execute("DELETE FROM candidate_traits  WHERE candidate_id = ?", (candidate_id,))
    for skill in c.skills:
        _ensure_tag(conn, "skills", skill)
        conn.execute(
            "INSERT INTO candidate_skills (candidate_id, skill_id) "
            "SELECT ?, id FROM skills WHERE name = ?",
            (candidate_id, skill),
        )
    for trait in c.traits:
        _ensure_tag(conn, "traits", trait)
        conn.execute(
            "INSERT INTO candidate_traits (candidate_id, trait_id) "
            "SELECT ?, id FROM traits WHERE name = ?",
            (candidate_id, trait),
        )
    return candidate_id


def upsert_job(conn: sqlite3.Connection, j: JobIn) -> int:
    job_id: int = conn.execute(
        """
        INSERT INTO jobs (title, min_experience, tagline)
        VALUES (:title, :min_experience, :tagline)
        ON CONFLICT (title) DO UPDATE SET
            min_experience = excluded.min_experience,
            tagline        = excluded.tagline
        RETURNING id
        """,
        j.model_dump(include={"title", "min_experience", "tagline"}),
    ).fetchone()["id"]

    conn.execute("DELETE FROM job_required_skills  WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_culture_keywords WHERE job_id = ?", (job_id,))
    for skill in j.required_skills:
        _ensure_tag(conn, "skills", skill)
        conn.execute(
            "INSERT INTO job_required_skills (job_id, skill_id) "
            "SELECT ?, id FROM skills WHERE name = ?",
            (job_id, skill),
        )
    for keyword in j.culture_keywords:
        _ensure_tag(conn, "traits", keyword)
        conn.execute(
            "INSERT INTO job_culture_keywords (job_id, trait_id) "
            "SELECT ?, id FROM traits WHERE name = ?",
            (job_id, keyword),
        )
    return job_id


def _insert_matches(conn: sqlite3.Connection, results: Iterable[MatchResult]) -> int:
    rows = [
        (r.candidate_id, r.job_id, r.score, r.skill_score, r.experience_score,
         r.culture_score, r.availability_score, r.reason)
        for r in results
    ]
    conn.executemany(
        """
        INSERT INTO matches (candidate_id, job_id, score, skill_score,
                             experience_score, culture_score, availability_score, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def refresh_matches(conn: sqlite3.Connection) -> int:
    """Recompute the whole `matches` table from the current candidates and jobs."""
    candidates = [
        CandidateProfile(
            id=c["id"], name=c["name"], experience_years=c["experience_years"],
            availability=c["availability"], skills=frozenset(c["skills"]),
            traits=frozenset(c["traits"]),
        )
        for c in fetch_candidates(conn)
    ]
    jobs = [
        JobProfile(
            id=j["id"], title=j["title"], min_experience=j["min_experience"],
            required_skills=frozenset(j["required_skills"]),
            culture_keywords=frozenset(j["culture_keywords"]),
        )
        for j in fetch_jobs(conn)
    ]
    conn.execute("DELETE FROM matches")
    return _insert_matches(conn, compute_matches(candidates, jobs))
