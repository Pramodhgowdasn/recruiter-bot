-- SQL Detective Challenge: answers
-- Standard SQL, tested on SQLite. Q5 needs window-function support (MySQL 8+, PostgreSQL, SQLite 3.25+).
-- One dialect note: GROUP_CONCAT in Q3 is SQLite/MySQL; on PostgreSQL use STRING_AGG(DISTINCT ...::text, ',').
-- Load sql/hiring_ops_setup.sql first.
--
-- Data-quality findings that shape the answers:
--   * The same person can appear twice with different applicant ids and different
--     email casing (Ananya Rao = ids 1 and 2). Identity is therefore keyed on
--     LOWER(TRIM(email)), never on applicants.id.
--   * There is no "applications" table; an applicant is considered to have
--     applied to a posting if they have at least one interview for it.
--   * An interview's posting can differ from the one an applicant first
--     appeared in (Ben Turner: Technical failed on #1, later Final on #3), so
--     counts are driven off `interviews.job_posting_id`, not off applied_date.


-- Question 1 ---------------------------------------------------------------
-- All currently open job postings with the owning recruiter's name.
SELECT jp.id            AS job_posting_id,
       jp.title,
       jp.department,
       jp.opened_date,
       r.name           AS recruiter
FROM   job_postings AS jp
JOIN   recruiters   AS r ON r.id = jp.recruiter_id
WHERE  jp.status = 'open'
ORDER  BY jp.id;


-- Question 2 ---------------------------------------------------------------
-- Per job posting: how many applicants reached the Final stage.
-- "Reached" = has a Final interview on that posting, whatever the outcome.
-- LEFT JOIN keeps postings that nobody reached (count = 0), and DISTINCT on the
-- de-duplicated person guards against double-counting someone with two rows.
SELECT jp.id    AS job_posting_id,
       jp.title,
       jp.status,
       COUNT(DISTINCT LOWER(TRIM(a.email))) AS applicants_reaching_final
FROM   job_postings AS jp
LEFT   JOIN interviews AS i
       ON  i.job_posting_id = jp.id
       AND i.stage = 'Final'
LEFT   JOIN applicants AS a ON a.id = i.applicant_id
GROUP  BY jp.id, jp.title, jp.status
ORDER  BY jp.id;


-- Question 3 ---------------------------------------------------------------
-- People who effectively applied to more than one job posting.
-- Group by normalised email so "Ananya Rao" (ids 1 and 2) is ONE person.
-- Expected: Ananya Rao (postings 1, 4), Ben Turner (1, 3), Elena Popescu (2, 7).
SELECT MIN(a.full_name)                          AS person,
       LOWER(TRIM(a.email))                      AS email,
       COUNT(DISTINCT i.job_posting_id)          AS postings_applied_to,
       GROUP_CONCAT(DISTINCT i.job_posting_id)   AS posting_ids
FROM   applicants AS a
JOIN   interviews AS i ON i.applicant_id = a.id
GROUP  BY LOWER(TRIM(a.email))
HAVING COUNT(DISTINCT i.job_posting_id) > 1
ORDER  BY person;


-- Question 4 ---------------------------------------------------------------
-- Final-stage conversion rate per recruiter (passed / all Final interviews),
-- only for recruiters with at least 3 Final-stage interviews.
-- Pending / no-show Finals stay in the denominator: they were scheduled and did
-- not convert. (There are none in this data, so the result is unaffected.)
-- The 1.0 * forces decimal division instead of integer division.
SELECT r.name                                                            AS recruiter,
       COUNT(*)                                                          AS final_interviews,
       SUM(CASE WHEN i.outcome = 'passed' THEN 1 ELSE 0 END)             AS passed,
       ROUND(1.0 * SUM(CASE WHEN i.outcome = 'passed' THEN 1 ELSE 0 END)
                 / COUNT(*), 2)                                          AS conversion_rate
FROM   interviews   AS i
JOIN   job_postings AS jp ON jp.id = i.job_posting_id
JOIN   recruiters   AS r  ON r.id  = jp.recruiter_id
WHERE  i.stage = 'Final'
GROUP  BY r.id, r.name
HAVING COUNT(*) >= 3
ORDER  BY conversion_rate DESC, recruiter;


-- Question 5 (Bonus) -------------------------------------------------------
-- Recruiter with the most successful placements (passed at Final) per department.
-- Aggregate to (department, recruiter), then RANK() within each department.
-- RANK (not ROW_NUMBER) so a genuine tie for first place returns every leader.
-- Departments with zero placements are omitted: nobody "won" there.
WITH placements AS (
    SELECT jp.department,
           r.name       AS recruiter,
           COUNT(*)     AS successful_placements
    FROM   interviews   AS i
    JOIN   job_postings AS jp ON jp.id = i.job_posting_id
    JOIN   recruiters   AS r  ON r.id  = jp.recruiter_id
    WHERE  i.stage = 'Final'
      AND  i.outcome = 'passed'
    GROUP  BY jp.department, r.id, r.name
),
ranked AS (
    SELECT department,
           recruiter,
           successful_placements,
           RANK() OVER (PARTITION BY department
                        ORDER BY successful_placements DESC) AS rnk
    FROM   placements
)
SELECT department, recruiter, successful_placements
FROM   ranked
WHERE  rnk = 1
ORDER  BY department;
