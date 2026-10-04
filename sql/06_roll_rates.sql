-- 06_roll_rates.sql
-- Count and probability matrices by slice, and the named roll metrics.
-- Slices: overall, calendar period (on origin month), MOB band, vintage quarter, age band,
-- income band. View A keeps DORMANT as a destination; view B renormalises over
-- open and absorbing destinations only.
-- DuckDB notes: GROUP BY ALL and FILTER are used; in PostgreSQL list the GROUP BY columns.

CREATE OR REPLACE TABLE roll_counts AS
SELECT 'overall' AS SLICE_TYPE, 'All' AS SLICE, FROM_STATE, TO_STATE, COUNT(*) AS n
FROM transitions GROUP BY ALL
UNION ALL
SELECT 'period', p.PERIOD, t.FROM_STATE, t.TO_STATE, COUNT(*)
FROM transitions t
JOIN config_periods p ON t.ORIGIN_MONTH BETWEEN p.START_MONTH AND p.END_MONTH
GROUP BY ALL
UNION ALL
SELECT 'mob_band', MOB_BAND, FROM_STATE, TO_STATE, COUNT(*)
FROM transitions GROUP BY ALL
UNION ALL
SELECT 'vintage_qtr', CAST(VINTAGE_QTR AS VARCHAR), FROM_STATE, TO_STATE, COUNT(*)
FROM transitions GROUP BY ALL
UNION ALL
SELECT 'age_band', AGE_BAND, FROM_STATE, TO_STATE, COUNT(*)
FROM transitions WHERE AGE_BAND IS NOT NULL GROUP BY ALL
UNION ALL
SELECT 'income_band', INCOME_BAND, FROM_STATE, TO_STATE, COUNT(*)
FROM transitions WHERE INCOME_BAND IS NOT NULL GROUP BY ALL;

CREATE OR REPLACE TABLE roll_probs AS
SELECT
    SLICE_TYPE,
    SLICE,
    FROM_STATE,
    TO_STATE,
    n,
    SUM(n) OVER (PARTITION BY SLICE_TYPE, SLICE, FROM_STATE) AS ROW_N_A,
    n / SUM(n) OVER (PARTITION BY SLICE_TYPE, SLICE, FROM_STATE) AS P_A,
    CASE WHEN TO_STATE = 'DORMANT' THEN NULL
         ELSE SUM(n) FILTER (WHERE TO_STATE <> 'DORMANT')
              OVER (PARTITION BY SLICE_TYPE, SLICE, FROM_STATE) END AS ROW_N_B,
    CASE WHEN TO_STATE = 'DORMANT' THEN NULL
         ELSE n / SUM(n) FILTER (WHERE TO_STATE <> 'DORMANT')
              OVER (PARTITION BY SLICE_TYPE, SLICE, FROM_STATE) END AS P_B
FROM roll_counts;

-- Named roll metrics on view A. Each metric is numerator / denominator so that the
-- bootstrap and the dashboard can rebuild it from counts.
CREATE OR REPLACE TABLE named_rolls AS
WITH c AS (
    SELECT r.*, sf.STATE_ORDER AS FROM_ORDER, st.STATE_ORDER AS TO_ORDER
    FROM roll_counts r
    JOIN status_lookup sf ON sf.STATE = r.FROM_STATE
    JOIN status_lookup st ON st.STATE = r.TO_STATE
)
SELECT SLICE_TYPE, SLICE, 'cure_30p' AS METRIC,
    SUM(n) FILTER (WHERE TO_STATE IN ('1-29', 'PAID-OFF')) AS NUM,
    SUM(n) AS DEN
FROM c WHERE FROM_STATE IN ('30-59', '60-89', '90-119', '120-149') GROUP BY ALL
UNION ALL
SELECT SLICE_TYPE, SLICE, 'cure_30p_to_1_29',
    SUM(n) FILTER (WHERE TO_STATE = '1-29'), SUM(n)
FROM c WHERE FROM_STATE IN ('30-59', '60-89', '90-119', '120-149') GROUP BY ALL
UNION ALL
SELECT SLICE_TYPE, SLICE, 'cure_30p_to_paid_off',
    SUM(n) FILTER (WHERE TO_STATE = 'PAID-OFF'), SUM(n)
FROM c WHERE FROM_STATE IN ('30-59', '60-89', '90-119', '120-149') GROUP BY ALL
UNION ALL
SELECT SLICE_TYPE, SLICE, 'persistence_' || FROM_STATE,
    SUM(n) FILTER (WHERE TO_STATE = FROM_STATE), SUM(n)
FROM c WHERE FROM_STATE IN ('1-29', '30-59', '60-89', '90-119', '120-149') GROUP BY ALL
UNION ALL
SELECT SLICE_TYPE, SLICE, 'forward_' || FROM_STATE,
    SUM(n) FILTER (WHERE TO_ORDER > FROM_ORDER AND TO_STATE NOT IN ('DORMANT', 'PAID-OFF')), SUM(n)
FROM c WHERE FROM_STATE IN ('1-29', '30-59', '60-89', '90-119', '120-149') GROUP BY ALL
UNION ALL
SELECT SLICE_TYPE, SLICE, 'roll_30_59_to_60p',
    SUM(n) FILTER (WHERE TO_STATE IN ('60-89', '90-119', '120-149', 'CHARGE-OFF')), SUM(n)
FROM c WHERE FROM_STATE = '30-59' GROUP BY ALL
UNION ALL
SELECT SLICE_TYPE, SLICE, 'severe_roll_60_89_to_90p',
    SUM(n) FILTER (WHERE TO_STATE IN ('90-119', '120-149', 'CHARGE-OFF')), SUM(n)
FROM c WHERE FROM_STATE = '60-89' GROUP BY ALL
UNION ALL
SELECT SLICE_TYPE, SLICE, 'roll_90p_to_co',
    SUM(n) FILTER (WHERE TO_STATE = 'CHARGE-OFF'), SUM(n)
FROM c WHERE FROM_STATE IN ('90-119', '120-149') GROUP BY ALL;

-- Transition cube for the dashboard: counts by origin month, from, to, MOB band and
-- vintage quarter. No client identifiers.
CREATE OR REPLACE TABLE transition_cube AS
SELECT ORIGIN_MONTH, FROM_STATE, TO_STATE, MOB_BAND, VINTAGE_QTR, COUNT(*) AS n
FROM transitions
GROUP BY ALL;

-- Segment transition cube by calendar period (suppressed for small cells at export).
CREATE OR REPLACE TABLE segment_transition_cube AS
SELECT 'age_band' AS SEG_TYPE, t.AGE_BAND AS SEGMENT, p.PERIOD, t.FROM_STATE, t.TO_STATE, COUNT(*) AS n
FROM transitions t
JOIN config_periods p ON t.ORIGIN_MONTH BETWEEN p.START_MONTH AND p.END_MONTH
WHERE t.AGE_BAND IS NOT NULL
GROUP BY ALL
UNION ALL
SELECT 'income_band', t.INCOME_BAND, p.PERIOD, t.FROM_STATE, t.TO_STATE, COUNT(*)
FROM transitions t
JOIN config_periods p ON t.ORIGIN_MONTH BETWEEN p.START_MONTH AND p.END_MONTH
WHERE t.INCOME_BAND IS NOT NULL
GROUP BY ALL;
