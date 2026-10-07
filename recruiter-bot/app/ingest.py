"""Ingestion: one transaction that upserts people/jobs and rebuilds matches."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import repository as repo
from .schemas import IngestPayload, IngestResult

SEED_PATH = Path(__file__).with_name("seed") / "seed.json"


def ingest(conn: sqlite3.Connection, payload: IngestPayload) -> IngestResult:
    # `with conn` commits on success and rolls back on any exception, so a bad
    # payload can never leave half-loaded data or stale matches behind.
    with conn:
        for candidate in payload.candidates:
            repo.upsert_candidate(conn, candidate)
        for job in payload.jobs:
            repo.upsert_job(conn, job)
        matches = repo.refresh_matches(conn)
    return IngestResult(
        candidates_upserted=len(payload.candidates),
        jobs_upserted=len(payload.jobs),
        matches_computed=matches,
    )


def load_seed_payload() -> IngestPayload:
    return IngestPayload.model_validate(json.loads(SEED_PATH.read_text(encoding="utf-8")))


def seed(conn: sqlite3.Connection) -> IngestResult:
    return ingest(conn, load_seed_payload())
