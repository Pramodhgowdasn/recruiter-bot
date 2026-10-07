# Recruiter Bot

A small backend that ingests candidate profiles and job openings, then ranks the best
matches in both directions: *who fits this job?* and *which jobs fit this candidate?*
Test data is a cast of fictional characters (Sherlock is, correctly, the top
**Backend Detective**).

- **Python 3.11+**, **FastAPI**, **SQLite** via the standard-library `sqlite3` driver
- **Raw SQL only**: hand-written DDL (`app/schema.sql`) and hand-written, parameterised
  queries (`app/repository.py`). No ORM, no query builder.
- Interactive API docs at `/docs` once running; 23 automated tests.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload                         # http://127.0.0.1:8000/docs
```

The database file (`recruiter_bot.db`) and tables are created on first start.
Set `RECRUITER_BOT_DB=/path/to/file.db` to put it elsewhere. Requires SQLite 3.35+
(`RETURNING` clause), which ships with any recent Python.

```bash
# 1. Load the seed data (idempotent: safe to run repeatedly)
curl -X POST localhost:8000/ingest/seed

# 2. Browse ids
curl localhost:8000/jobs
curl localhost:8000/candidates

# 3. Ranked candidates for a job (job 1 = Backend Detective)
curl "localhost:8000/jobs/1/matches"
curl "localhost:8000/jobs/2/matches?available_only=true&min_score=60&limit=5"

# 4. Ranked jobs for a candidate (candidate 6 = Rick S.)
curl "localhost:8000/candidates/6/matches"

# 5. Ingest your own data (names and tags are normalised; same payload shape as the seed file)
curl -X POST localhost:8000/ingest -H 'Content-Type: application/json' -d '{
  "candidates": [{"name": "Hercule P.", "skills": ["deduction", "forensics"],
                  "experience_years": 30, "availability": "2 weeks", "traits": ["analytical"]}]
}'
```

Tests: `pytest`

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/ingest/seed` | Load the bundled fictional data |
| POST | `/ingest` | Bulk upsert candidates and/or jobs, then recompute matches |
| GET | `/candidates`, `/candidates/{id}` | Catalogue |
| GET | `/jobs`, `/jobs/{id}` | Catalogue |
| GET | `/jobs/{id}/matches` | Ranked candidates. Query: `limit`, `min_score`, `available_only` |
| GET | `/candidates/{id}/matches` | Ranked jobs. Query: `limit`, `min_score` |

Example response (`GET /jobs/1/matches?limit=1`, trimmed):

```json
{ "rank": 1, "name": "Sherlock H.", "score": 95.0,
  "breakdown": { "skills": 1.0, "experience": 1.0, "culture": 0.5, "availability": 1.0 },
  "reason": "Covers 3/3 required skills (deduction, forensics, pattern-recognition); 8 yrs experience vs 3 required; culture fit: analytical; available immediately." }
```

## How matching works

Each component is normalised to 0..1, then combined with weights that read as percentages:

| Component | Weight | Definition |
|---|---|---|
| Skills | 60% | Share of the job's required skills the candidate has (1 of 3 → 0.33) |
| Experience | 20% | See below |
| Culture | 10% | Share of the job's culture keywords found in the candidate's traits |
| Availability | 10% | immediate 1.0 · two weeks 0.7 · not looking 0.0 |

`score = 100 × (0.6·skills + 0.2·experience + 0.1·culture + 0.1·availability)`.
Sherlock → Backend Detective: 100 × (0.6 + 0.2 + 0.05 + 0.1) = **95**. Weights are constants at the
top of `app/matching.py`.

**Experience curve.** Below the minimum, the score is proportional (2 yrs vs 4 required → 0.5).
Meeting the minimum, up to 3× it, is full marks. Beyond 3× it decays gently to a floor of 0.7
(Rick, 20 years, for a 2-year role scores 0.7, not 0). Over-qualification is a mild retention
risk, not a disqualifier; a hard cut-off would punish exactly the people you'd most like to talk to.

## Decisions and trade-offs

**Skills dominate, and zero overlap means no match.** A candidate who can't do any of the required
work shouldn't appear because they're optimistic and available. So pairs with no skill overlap
are never stored. The flip side: partial overlap (1 of 3) can still reach ~50 on the strength of
experience and availability. `min_score` lets a caller cut that tail; I'd rather expose the
knob than hide candidates by default.

**"Not looking" is penalised, not excluded.** Tony S. is a perfect fit for Rapid Prototyping Engineer
and *not looking*. Dropping him silently would hide a real signal (a recruiter may still want to
reach out), so he ranks lower via the availability weight, and `?available_only=true` removes
him when you want an actionable shortlist.

**Matches are materialised in a `matches` table.** Scores are computed in Python (`matching.py`,
pure functions, unit-tested without a database) and stored with every sub-score and the reason text.
Reads are then one indexed `SELECT … ORDER BY`, and the breakdown is auditable in SQL. The cost is
that matches are recomputed whenever data is ingested: a full O(candidates × jobs) rebuild inside
the ingest transaction. That's right at this scale; at real scale I'd recompute only the rows touched
by the changed candidate/job.

**Deterministic ranking.** Order is score → skill coverage → sooner availability → name. Two
candidates with equal scores (Leslie and Ted for Engineering Manager) always come back in the same order.

**Schema.** Skills and traits are normalised lookup tables with junction tables, so a tag is one row.
Candidate traits and job culture keywords share a single `traits` vocabulary so they can be compared directly.
All statements bind values with `?` / named parameters. The one f-string in the repo builds an
`INSERT` for a table name chosen from two hard-coded literals (never user input), to avoid duplicating
the statement.

**Ingestion is idempotent and atomic.** Upserts are keyed on the unique candidate name / job title
(`INSERT … ON CONFLICT DO UPDATE`), and the whole ingest plus the match rebuild run in one
transaction: an invalid payload is rejected (422) and leaves nothing half-written.

### Known limitations (what I'd do next)

- **Culture matching is exact-string.** `calm` (MacGyver) does not match `calm-under-pressure`
  (Incident Commander). A synonym map or embeddings would fix this; I kept it explainable.
- All required skills count equally and there are no skill levels or "nice to have" skills.
- No pagination beyond `limit`, no auth, no delete endpoints, single-writer SQLite.

## Part 2: SQL Detective

Answers are in [`sql_detective.sql`](sql_detective.sql), one query per question. The dataset is loaded
unchanged from [`sql/hiring_ops_setup.sql`](sql/hiring_ops_setup.sql). To run them:

```bash
python sql/run_detective.py     # loads the dataset into memory and prints every answer
```

Or paste the setup file and any query into any SQL client (e.g. DB Browser for SQLite).

The data is deliberately messy, and the answers account for it:

- **Q3**: Ananya Rao is two applicant rows (ids 1 and 2, email differs only by case). Identity is
  keyed on `LOWER(TRIM(email))`, so she counts once, as a person who applied to postings 1 and 4. Expected result:
  Ananya Rao, Ben Turner and Elena Popescu.
- **Q2**: `LEFT JOIN` so postings no one reached still show `0`.
- **Q4**: `1.0 *` avoids integer division. Priya Shah 3/4 = 0.75, Daniel Ortiz 2/4 = 0.50;
  Fatima, Wei and Grace are excluded by the 3-interview floor.
- **Q5**: `RANK()` (not `ROW_NUMBER()`) so a tie for first returns every leader.

## Project layout

```
app/
  main.py        HTTP routes (thin)
  matching.py    scoring engine: pure functions, no I/O
  repository.py  every SQL statement
  ingest.py      transactional upsert + match rebuild
  schemas.py     request/response validation
  db.py          sqlite3 connection handling
  schema.sql     hand-written DDL
  seed/seed.json fictional candidates and jobs
tests/           unit tests (matching) + API tests (real SQLite)
sql/             Part 2 dataset + run_detective.py
sql_detective.sql
```

## AI usage

I used Claude (Anthropic's AI assistant) to help design and draft this project: the schema, the
matching algorithm, the tests and the SQL. Every query result and test was run locally against SQLite.
