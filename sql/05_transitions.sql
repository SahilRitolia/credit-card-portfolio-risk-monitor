-- 05_transitions.sql
-- Consecutive-month transitions (ID, t, STATE_t, STATE_t+1) on the opened book.
-- A transition exists only when both rows exist and the months differ by exactly 1
-- (LEAD + month check), so non-consecutive rows are never paired.
-- Rows leaving PAID-OFF or CHARGE-OFF go to transition_anomalies, never to the matrix.
-- First activation (leading X or no prior row -> first open month) is an entry flow,
-- not a roll, and is reported in entry_flows.
-- DuckDB notes: WINDOW clause and LEAD/LAG are standard and PostgreSQL-compatible.

CREATE OR REPLACE TABLE transitions_all AS
WITH seq AS (
    SELECT
        p.*,
        LEAD(MONTHS_BALANCE) OVER w AS NEXT_MONTH,
        LEAD(STATE) OVER w AS NEXT_STATE,
        LEAD(RAW_STATUS) OVER w AS NEXT_RAW
    FROM panel p
    WINDOW w AS (PARTITION BY ID ORDER BY MONTHS_BALANCE)
)
SELECT
    ID,
    MONTHS_BALANCE AS ORIGIN_MONTH,
    NEXT_MONTH AS DEST_MONTH,
    STATE AS FROM_STATE,
    NEXT_STATE AS TO_STATE,
    RAW_STATUS AS FROM_RAW,
    NEXT_RAW AS TO_RAW,
    MOB,
    MOB_BAND,
    VINTAGE_MONTH,
    VINTAGE_QTR,
    AGE_BAND,
    INCOME_BAND,
    FROM_STATE IN ('PAID-OFF', 'CHARGE-OFF') AS FROM_ABSORBING
FROM seq
WHERE IS_OPENED AND NEXT_MONTH = MONTHS_BALANCE + 1;

-- Transitions that feed every matrix: origin is a transient state.
CREATE OR REPLACE TABLE transitions AS
SELECT * EXCLUDE (FROM_ABSORBING)
FROM transitions_all
WHERE NOT FROM_ABSORBING;

-- Rows leaving an absorbing state (raw-data anomalies, flagged and reported, not fixed).
CREATE OR REPLACE TABLE transition_anomalies AS
SELECT ID, ORIGIN_MONTH, DEST_MONTH, FROM_STATE, TO_STATE, FROM_RAW, TO_RAW
FROM transitions_all
WHERE FROM_ABSORBING AND TO_STATE <> FROM_STATE;

CREATE OR REPLACE TABLE absorbing_stays AS
SELECT FROM_STATE, COUNT(*) AS n
FROM transitions_all
WHERE FROM_ABSORBING AND TO_STATE = FROM_STATE
GROUP BY FROM_STATE;

-- Entry flows: first activation by month (from leading X or first record) and returns
-- from DORMANT; exit flows: open bucket to DORMANT. Reported as flows, not rolls.
CREATE OR REPLACE TABLE entry_exit_flows AS
SELECT DEST_MONTH AS MONTH, 'return from dormant' AS FLOW, COUNT(*) AS n
FROM transitions
WHERE FROM_STATE = 'DORMANT' AND TO_STATE IN ('1-29','30-59','60-89','90-119','120-149','CHARGE-OFF')
GROUP BY ALL
UNION ALL
SELECT DEST_MONTH, 'exit to dormant', COUNT(*)
FROM transitions
WHERE FROM_STATE <> 'DORMANT' AND TO_STATE = 'DORMANT'
GROUP BY ALL
UNION ALL
SELECT OPEN_MONTH, 'first activation', COUNT(*)
FROM opened_clients
GROUP BY ALL;

-- Second-order triples (previous, current, next) on consecutive months for the
-- Anderson-Goodman history test.
CREATE OR REPLACE TABLE transition_triples AS
WITH seq AS (
    SELECT
        ID,
        MONTHS_BALANCE,
        STATE,
        IS_OPENED,
        LAG(STATE) OVER w AS PREV_STATE,
        LAG(MONTHS_BALANCE) OVER w AS PREV_MONTH,
        LAG(IS_OPENED) OVER w AS PREV_OPENED,
        LEAD(STATE) OVER w AS NEXT_STATE,
        LEAD(MONTHS_BALANCE) OVER w AS NEXT_MONTH
    FROM panel
    WINDOW w AS (PARTITION BY ID ORDER BY MONTHS_BALANCE)
)
SELECT PREV_STATE, STATE AS CUR_STATE, NEXT_STATE, COUNT(*) AS n
FROM seq
WHERE IS_OPENED AND PREV_OPENED
  AND PREV_MONTH = MONTHS_BALANCE - 1 AND NEXT_MONTH = MONTHS_BALANCE + 1
  AND STATE NOT IN ('PAID-OFF', 'CHARGE-OFF') AND PREV_STATE NOT IN ('PAID-OFF', 'CHARGE-OFF')
GROUP BY ALL;
