-- 09_ageing_snapshot.sql
-- Stock of opened accounts by month x state x MOB band x vintage quarter, and the
-- month-over-month flow table (opening state -> closing state, with entries and exits).
-- DuckDB notes: none beyond GROUP BY ALL.

CREATE OR REPLACE TABLE stock_cube AS
SELECT MONTHS_BALANCE, STATE, MOB_BAND, VINTAGE_QTR, COUNT(*) AS n
FROM panel
WHERE IS_OPENED
GROUP BY ALL;

-- Flow table keyed by the closing month t. FROM_STATE 'NEW' = opened row at t with no opened
-- row at t-1 (first open month, or a gap); TO_STATE 'RECORD ENDS' = opened row at t-1 with
-- no row at t (history stops before the extraction month).
CREATE OR REPLACE TABLE flow_table AS
WITH opened AS (
    SELECT ID, MONTHS_BALANCE, STATE FROM panel WHERE IS_OPENED
),
pairs AS (
    SELECT
        COALESCE(cur.MONTHS_BALANCE, prev.MONTHS_BALANCE + 1) AS CLOSING_MONTH,
        COALESCE(prev.STATE, 'NEW') AS FROM_STATE,
        COALESCE(cur.STATE, 'RECORD ENDS') AS TO_STATE
    FROM opened cur
    FULL OUTER JOIN opened prev
        ON prev.ID = cur.ID AND prev.MONTHS_BALANCE = cur.MONTHS_BALANCE - 1
)
SELECT CLOSING_MONTH, FROM_STATE, TO_STATE, COUNT(*) AS n
FROM pairs
WHERE CLOSING_MONTH <= 0
GROUP BY ALL;
