"""HTTP layer. Thin on purpose: validate, call the repository, shape the response."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query

from . import ingest as ingestion
from . import repository as repo
from .db import connect, get_db, init_schema
from .schemas import (
    CandidateMatch, CandidateMatches, CandidateOut, IngestPayload, IngestResult,
    JobMatch, JobMatches, JobOut, ScoreBreakdown,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    conn = connect()
    try:
        init_schema(conn)
    finally:
        conn.close()
    yield


app = FastAPI(
    title="Recruiter Bot",
    version="1.0.0",
    description="Ranks fictional candidates against fictional jobs. Raw SQL, no ORM.",
    lifespan=lifespan,
)

Db = Depends(get_db)


def _breakdown(row: sqlite3.Row) -> ScoreBreakdown:
    return ScoreBreakdown(
        skills=row["skill_score"], experience=row["experience_score"],
        culture=row["culture_score"], availability=row["availability_score"],
    )


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- Ingestion --------------------------------------------------------------

@app.post("/ingest", response_model=IngestResult, tags=["ingestion"],
          summary="Bulk upsert candidates and/or jobs, then recompute matches")
def ingest_data(payload: IngestPayload, conn: sqlite3.Connection = Db) -> IngestResult:
    return ingestion.ingest(conn, payload)


@app.post("/ingest/seed", response_model=IngestResult, tags=["ingestion"],
          summary="Load the bundled fictional candidates and jobs (idempotent)")
def ingest_seed(conn: sqlite3.Connection = Db) -> IngestResult:
    return ingestion.seed(conn)


# --- Catalogue --------------------------------------------------------------

@app.get("/candidates", response_model=list[CandidateOut], tags=["candidates"])
def list_candidates(conn: sqlite3.Connection = Db) -> list[dict]:
    return repo.fetch_candidates(conn)


@app.get("/candidates/{candidate_id}", response_model=CandidateOut, tags=["candidates"])
def get_candidate(candidate_id: int, conn: sqlite3.Connection = Db) -> dict:
    rows = repo.fetch_candidates(conn, candidate_id)
    if not rows:
        raise HTTPException(404, f"Candidate {candidate_id} not found")
    return rows[0]


@app.get("/jobs", response_model=list[JobOut], tags=["jobs"])
def list_jobs(conn: sqlite3.Connection = Db) -> list[dict]:
    return repo.fetch_jobs(conn)


@app.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
def get_job(job_id: int, conn: sqlite3.Connection = Db) -> dict:
    rows = repo.fetch_jobs(conn, job_id)
    if not rows:
        raise HTTPException(404, f"Job {job_id} not found")
    return rows[0]


# --- Matching ---------------------------------------------------------------

@app.get("/jobs/{job_id}/matches", response_model=JobMatches, tags=["matching"],
         summary="Ranked candidates for a job")
def job_matches(
    job_id: int,
    limit: int = Query(10, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100, description="Hide matches scoring below this"),
    available_only: bool = Query(False, description="Exclude candidates who are not looking"),
    conn: sqlite3.Connection = Db,
) -> JobMatches:
    jobs = repo.fetch_jobs(conn, job_id)
    if not jobs:
        raise HTTPException(404, f"Job {job_id} not found")
    rows = repo.fetch_job_matches(
        conn, job_id, limit=limit, min_score=min_score, available_only=available_only
    )
    matches = [
        CandidateMatch(
            rank=i, candidate_id=r["candidate_id"], name=r["name"], score=r["score"],
            breakdown=_breakdown(r), availability=r["availability"], reason=r["reason"],
        )
        for i, r in enumerate(rows, start=1)
    ]
    return JobMatches(job=JobOut(**jobs[0]), matches=matches)


@app.get("/candidates/{candidate_id}/matches", response_model=CandidateMatches, tags=["matching"],
         summary="Ranked jobs for a candidate")
def candidate_matches(
    candidate_id: int,
    limit: int = Query(10, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100, description="Hide matches scoring below this"),
    conn: sqlite3.Connection = Db,
) -> CandidateMatches:
    candidates = repo.fetch_candidates(conn, candidate_id)
    if not candidates:
        raise HTTPException(404, f"Candidate {candidate_id} not found")
    rows = repo.fetch_candidate_matches(conn, candidate_id, limit=limit, min_score=min_score)
    matches = [
        JobMatch(
            rank=i, job_id=r["job_id"], title=r["title"], score=r["score"],
            breakdown=_breakdown(r), reason=r["reason"],
        )
        for i, r in enumerate(rows, start=1)
    ]
    return CandidateMatches(candidate=CandidateOut(**candidates[0]), matches=matches)
