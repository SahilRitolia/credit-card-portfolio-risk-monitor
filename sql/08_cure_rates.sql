-- 08_cure_rates.sql
-- 30+ episodes and their competing outcomes, looked up by calendar month (never by next row).
-- Episode: a month with raw status 1-5 whose previous calendar month (t-1) exists in the
-- opened book and is not 1-5. Episodes whose previous month is missing or pre-open (the
-- first-ever open month is already 30+) are left-censored: flagged and excluded by default.
-- For j = 1..{{CURE_MAX_H}}: CURED = first month in 1-29 or PAID-OFF; CHARGED-OFF = first month
-- in CHARGE-OFF; CENSORED = first month with no record (data ended or window past month 0)
-- or DORMANT, before any resolution. An episode that enters directly at CHARGE-OFF is
-- charged off at j = 0.
-- DuckDB notes: LEAST over NULLs ignores NULLs in DuckDB (PostgreSQL LEAST does too).

CREATE OR REPLACE TABLE cure_episodes AS
WITH seq AS (
    SELECT
        p.ID,
        p.MONTHS_BALANCE,
        p.STATE,
        p.IS_30P,
        LAG(p.MONTHS_BALANCE) OVER w AS PREV_MONTH,
        LAG(p.STATE) OVER w AS PREV_STATE,
        LAG(p.IS_30P) OVER w AS PREV_30P,
        LAG(p.IS_OPENED) OVER w AS PREV_OPENED
    FROM panel p
    WHERE p.IS_OPENED OR p.MOB IS NULL
    WINDOW w AS (PARTITION BY p.ID ORDER BY p.MONTHS_BALANCE)
),
entries AS (
    SELECT
        ID,
        MONTHS_BALANCE AS ENTRY_MONTH,
        STATE AS ENTRY_STATE,
        CASE WHEN PREV_MONTH = MONTHS_BALANCE - 1 AND PREV_OPENED THEN PREV_STATE END AS PREV_STATE,
        NOT (PREV_MONTH = MONTHS_BALANCE - 1 AND COALESCE(PREV_OPENED, FALSE)) AS LEFT_CENSORED
    FROM seq
    WHERE IS_30P
      AND NOT (PREV_MONTH = MONTHS_BALANCE - 1 AND COALESCE(PREV_OPENED, FALSE) AND PREV_30P)
),
grid AS (
    SELECT e.*, j.range AS J
    FROM entries e
    CROSS JOIN range(1, {{CURE_MAX_H}} + 1) j
),
looked AS (
    SELECT g.*, p.STATE AS STATE_J
    FROM grid g
    LEFT JOIN panel p ON p.ID = g.ID AND p.MONTHS_BALANCE = g.ENTRY_MONTH + g.J
),
firsts AS (
    SELECT
        ID, ENTRY_MONTH, ENTRY_STATE, PREV_STATE, LEFT_CENSORED,
        MIN(J) FILTER (WHERE STATE_J IN ('1-29', 'PAID-OFF')) AS CURE_J,
        MIN(J) FILTER (WHERE STATE_J = 'CHARGE-OFF') AS CO_J,
        MIN(J) FILTER (WHERE STATE_J IS NULL OR STATE_J = 'DORMANT') AS CENS_J
    FROM looked
    GROUP BY ALL
)
SELECT
    ID,
    ENTRY_MONTH,
    ENTRY_STATE,
    COALESCE(PREV_STATE, 'none') AS PREV_STATE,
    LEFT_CENSORED,
    CASE
        WHEN ENTRY_STATE = 'CHARGE-OFF' THEN 'CHARGED-OFF'
        WHEN LEAST(CURE_J, CO_J, CENS_J) IS NULL THEN 'STILL 30+'
        WHEN CURE_J = LEAST(CURE_J, CO_J, CENS_J) THEN 'CURED'
        WHEN CO_J = LEAST(CURE_J, CO_J, CENS_J) THEN 'CHARGED-OFF'
        ELSE 'CENSORED'
    END AS EVENT_TYPE,
    CASE WHEN ENTRY_STATE = 'CHARGE-OFF' THEN 0 ELSE LEAST(CURE_J, CO_J, CENS_J) END AS EVENT_J,
    CASE WHEN CURE_J = LEAST(CURE_J, CO_J, CENS_J) AND ENTRY_STATE <> 'CHARGE-OFF'
         THEN (SELECT STATE FROM panel q WHERE q.ID = f.ID AND q.MONTHS_BALANCE = f.ENTRY_MONTH + f.CURE_J)
    END AS CURE_TO
FROM firsts f;

-- Episode groups used in every cure output.
CREATE OR REPLACE TABLE cure_episode_groups AS
SELECT e.*, g.GRP
FROM cure_episodes e
CROSS JOIN (VALUES ('All episodes'), ('Entry 30-59'), ('Entry 60+'), ('From 1-29'), ('From dormant')) g(GRP)
WHERE NOT (e.LEFT_CENSORED AND {{EXCLUDE_LEFT_CENSORED}})
  AND (
    g.GRP = 'All episodes'
    OR (g.GRP = 'Entry 30-59' AND e.ENTRY_STATE = '30-59')
    OR (g.GRP = 'Entry 60+' AND e.ENTRY_STATE IN ('60-89', '90-119', '120-149', 'CHARGE-OFF'))
    OR (g.GRP = 'From 1-29' AND e.PREV_STATE = '1-29')
    OR (g.GRP = 'From dormant' AND e.PREV_STATE = 'DORMANT')
  );

-- Discrete-time hazard table: for month j, episodes at risk at the start of j and the
-- events of each type in j (cause-specific hazards for the cumulative incidence estimator).
CREATE OR REPLACE TABLE cure_hazards AS
WITH j AS (SELECT range AS J FROM range(1, {{CURE_MAX_H}} + 1))
SELECT
    e.GRP,
    j.J,
    COUNT(*) FILTER (WHERE COALESCE(e.EVENT_J, 99) >= j.J) AS at_risk,
    COUNT(*) FILTER (WHERE e.EVENT_J = j.J AND e.EVENT_TYPE = 'CURED') AS cured,
    COUNT(*) FILTER (WHERE e.EVENT_J = j.J AND e.EVENT_TYPE = 'CHARGED-OFF') AS charged_off,
    COUNT(*) FILTER (WHERE e.EVENT_J = j.J AND e.EVENT_TYPE = 'CENSORED') AS censored
FROM cure_episode_groups e
CROSS JOIN j
WHERE e.EVENT_J IS NULL OR e.EVENT_J >= 1
GROUP BY ALL;

-- Episodes charged off at entry (j = 0), per group, for the estimator's starting mass.
CREATE OR REPLACE TABLE cure_immediate AS
SELECT GRP, COUNT(*) FILTER (WHERE EVENT_J = 0) AS co_at_entry, COUNT(*) AS episodes
FROM cure_episode_groups
GROUP BY GRP;

-- Fixed-window outcome classification for k in the configured horizons.
CREATE OR REPLACE TABLE cure_outcomes AS
WITH k AS (SELECT * FROM (VALUES {{CURE_HORIZONS_VALUES}}) t(K))
SELECT
    e.GRP,
    k.K,
    COUNT(*) AS episodes,
    COUNT(*) FILTER (WHERE e.EVENT_TYPE = 'CURED' AND e.EVENT_J <= k.K) AS cured,
    COUNT(*) FILTER (WHERE e.EVENT_TYPE = 'CURED' AND e.EVENT_J <= k.K AND e.CURE_TO = '1-29') AS cured_to_1_29,
    COUNT(*) FILTER (WHERE e.EVENT_TYPE = 'CURED' AND e.EVENT_J <= k.K AND e.CURE_TO = 'PAID-OFF') AS cured_to_paid_off,
    COUNT(*) FILTER (WHERE e.EVENT_TYPE = 'CHARGED-OFF' AND e.EVENT_J <= k.K) AS charged_off,
    COUNT(*) FILTER (WHERE e.EVENT_TYPE = 'CENSORED' AND e.EVENT_J <= k.K) AS censored,
    COUNT(*) FILTER (WHERE NOT (e.EVENT_J <= k.K) OR e.EVENT_J IS NULL) AS still_30p,
    -- Fixed-window estimator: complete k-month window inside the data and not censored
    -- before resolution.
    COUNT(*) FILTER (WHERE e.ENTRY_MONTH + k.K <= 0
                       AND NOT (e.EVENT_TYPE = 'CENSORED' AND e.EVENT_J <= k.K)) AS fw_eligible,
    COUNT(*) FILTER (WHERE e.ENTRY_MONTH + k.K <= 0
                       AND e.EVENT_TYPE = 'CURED' AND e.EVENT_J <= k.K) AS fw_cured,
    COUNT(*) FILTER (WHERE e.ENTRY_MONTH + k.K <= 0
                       AND e.EVENT_TYPE = 'CHARGED-OFF' AND e.EVENT_J <= k.K) AS fw_charged_off
FROM cure_episode_groups e
CROSS JOIN k
GROUP BY ALL;

-- Re-delinquency within 6 months after a cure (complete 6-month window only).
CREATE OR REPLACE TABLE cure_redelinquency AS
WITH cured AS (
    SELECT ID, ENTRY_MONTH + EVENT_J AS CURE_MONTH
    FROM cure_episodes
    WHERE EVENT_TYPE = 'CURED' AND NOT (LEFT_CENSORED AND {{EXCLUDE_LEFT_CENSORED}})
      AND ENTRY_MONTH + EVENT_J + 6 <= 0
)
SELECT
    COUNT(*) AS cured_with_window,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM panel p
        WHERE p.ID = c.ID AND p.IS_30P
          AND p.MONTHS_BALANCE BETWEEN c.CURE_MONTH + 1 AND c.CURE_MONTH + 6
    )) AS redelinquent_6m
FROM cured c;
