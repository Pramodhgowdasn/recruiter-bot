"""Integration tests: real FastAPI app, real SQLite file, real SQL."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RECRUITER_BOT_DB", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(client):
    assert client.post("/ingest/seed").status_code == 200
    return client


def job_id(client, title):
    return next(j["id"] for j in client.get("/jobs").json() if j["title"] == title)


def candidate_id(client, name):
    return next(c["id"] for c in client.get("/candidates").json() if c["name"] == name)


def test_seed_loads_expected_rows(client):
    body = client.post("/ingest/seed").json()
    assert body["candidates_upserted"] == 15 and body["jobs_upserted"] == 6
    assert len(client.get("/candidates").json()) == 15
    assert len(client.get("/jobs").json()) == 6


def test_seed_is_idempotent(client):
    first = client.post("/ingest/seed").json()
    second = client.post("/ingest/seed").json()
    assert first == second
    assert len(client.get("/candidates").json()) == 15


def test_sherlock_is_top_match_for_backend_detective(seeded):
    data = seeded.get(f"/jobs/{job_id(seeded, 'Backend Detective')}/matches").json()
    top = data["matches"][0]
    assert top["name"] == "Sherlock H." and top["rank"] == 1
    assert top["breakdown"]["skills"] == 1.0
    assert "3/3" in top["reason"]


def test_matches_are_sorted_by_score_descending(seeded):
    for job in seeded.get("/jobs").json():
        scores = [m["score"] for m in seeded.get(f"/jobs/{job['id']}/matches").json()["matches"]]
        assert scores == sorted(scores, reverse=True)


def test_reverse_direction_ranks_jobs_for_a_candidate(seeded):
    data = seeded.get(f"/candidates/{candidate_id(seeded, 'Olivia P.')}/matches").json()
    assert data["matches"][0]["title"] == "Incident Commander"


def test_available_only_hides_candidates_who_are_not_looking(seeded):
    jid = job_id(seeded, "Rapid Prototyping Engineer")
    everyone = {m["name"] for m in seeded.get(f"/jobs/{jid}/matches").json()["matches"]}
    available = {m["name"] for m in
                 seeded.get(f"/jobs/{jid}/matches", params={"available_only": True}).json()["matches"]}
    assert "Tony S." in everyone and "Tony S." not in available


def test_min_score_and_limit_filters(seeded):
    jid = job_id(seeded, "Developer Relations Lead")
    high = seeded.get(f"/jobs/{jid}/matches", params={"min_score": 80}).json()["matches"]
    assert high and all(m["score"] >= 80 for m in high)
    assert len(seeded.get(f"/jobs/{jid}/matches", params={"limit": 1}).json()["matches"]) == 1


def test_unknown_ids_return_404(seeded):
    assert seeded.get("/jobs/999/matches").status_code == 404
    assert seeded.get("/candidates/999/matches").status_code == 404


def test_ingesting_a_new_candidate_updates_rankings(seeded):
    jid = job_id(seeded, "Backend Detective")
    seeded.post("/ingest", json={"candidates": [{
        "name": "Hercule P.", "skills": ["Deduction", " Pattern-Recognition ", "forensics"],
        "experience_years": 30, "availability": "2 weeks", "traits": ["analytical"],
    }]})
    names = [m["name"] for m in seeded.get(f"/jobs/{jid}/matches").json()["matches"]]
    assert "Hercule P." in names[:2]                 # skills were normalised and matched
    stored = next(c for c in seeded.get("/candidates").json() if c["name"] == "Hercule P.")
    assert stored["availability"] == "two_weeks"     # "2 weeks" alias accepted


def test_invalid_payload_is_rejected_and_nothing_is_written(client):
    bad = {"candidates": [{"name": "X", "skills": [], "experience_years": -1, "availability": "maybe"}]}
    assert client.post("/ingest", json=bad).status_code == 422
    assert client.get("/candidates").json() == []


def test_sql_injection_attempt_is_stored_as_plain_text(client):
    evil = "Robert'); DROP TABLE candidates;--"
    client.post("/ingest", json={"candidates": [{
        "name": evil, "skills": ["x"], "experience_years": 1, "availability": "immediate"}]})
    assert [c["name"] for c in client.get("/candidates").json()] == [evil]
