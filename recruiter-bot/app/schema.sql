-- Recruiter Bot schema (SQLite dialect, hand-written DDL).
--
-- Design notes
--   * Skills and traits are normalised into lookup tables so "public-speaking"
--     is one row, not a string repeated in 5 places. Candidate/job links are
--     plain junction tables.
--   * Traits (candidates) and culture keywords (jobs) share one vocabulary
--     table, `traits`, so they can be compared with a simple join.
--   * `matches` is a materialised result table: the matching engine writes one
--     row per (candidate, job) pair that shares at least one required skill,
--     including every score component and the human-readable reason.
--     Reads are then a single indexed SELECT ... ORDER BY.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS candidates (
    id               INTEGER PRIMARY KEY,
    name             TEXT    NOT NULL UNIQUE,
    experience_years INTEGER NOT NULL CHECK (experience_years >= 0),
    availability     TEXT    NOT NULL CHECK (availability IN ('immediate', 'two_weeks', 'not_looking')),
    quirk            TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id             INTEGER PRIMARY KEY,
    title          TEXT    NOT NULL UNIQUE,
    min_experience INTEGER NOT NULL CHECK (min_experience >= 0),
    tagline        TEXT
);

CREATE TABLE IF NOT EXISTS skills (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS traits (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS candidate_skills (
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    skill_id     INTEGER NOT NULL REFERENCES skills(id)     ON DELETE CASCADE,
    PRIMARY KEY (candidate_id, skill_id)
);

CREATE TABLE IF NOT EXISTS candidate_traits (
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    trait_id     INTEGER NOT NULL REFERENCES traits(id)     ON DELETE CASCADE,
    PRIMARY KEY (candidate_id, trait_id)
);

CREATE TABLE IF NOT EXISTS job_required_skills (
    job_id   INTEGER NOT NULL REFERENCES jobs(id)   ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, skill_id)
);

CREATE TABLE IF NOT EXISTS job_culture_keywords (
    job_id   INTEGER NOT NULL REFERENCES jobs(id)   ON DELETE CASCADE,
    trait_id INTEGER NOT NULL REFERENCES traits(id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, trait_id)
);

CREATE TABLE IF NOT EXISTS matches (
    candidate_id        INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id              INTEGER NOT NULL REFERENCES jobs(id)       ON DELETE CASCADE,
    score               REAL    NOT NULL CHECK (score BETWEEN 0 AND 100),
    skill_score         REAL    NOT NULL,   -- 0..1  share of required skills covered
    experience_score    REAL    NOT NULL,   -- 0..1
    culture_score       REAL    NOT NULL,   -- 0..1
    availability_score  REAL    NOT NULL,   -- 0..1
    reason              TEXT    NOT NULL,
    PRIMARY KEY (candidate_id, job_id)
);

-- Ranking reads: "best candidates for a job" and "best jobs for a candidate".
-- The tie-break columns are part of the index so the ORDER BY is index-friendly.
CREATE INDEX IF NOT EXISTS idx_matches_job
    ON matches (job_id, score DESC, skill_score DESC, availability_score DESC);
CREATE INDEX IF NOT EXISTS idx_matches_candidate
    ON matches (candidate_id, score DESC, skill_score DESC, availability_score DESC);
