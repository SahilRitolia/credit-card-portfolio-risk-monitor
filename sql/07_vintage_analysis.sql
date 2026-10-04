-- 07_vintage_analysis.sql
-- Vintage (OPEN_MONTH) x MOB ever-delinquency curves with the calendar observability rule:
-- cell (v, k) exists only if v + k <= 0. Denominator = every account opened in v (including
-- accounts that later paid off, went dormant or whose records ended); numerator = accounts
-- whose 'ever' flag is set by MOB k. Curves are never extrapolated.
-- DuckDB notes: range() table function (PostgreSQL: generate_series).

CREATE OR REPLACE TABLE vintage_clients AS
SELECT
    o.ID,
    o.OPEN_MONTH,
    o.VINTAGE_QTR,
    o.AGE_BAND,
    o.INCOME_BAND,
    MIN(p.MOB) FILTER (WHERE p.IS_30P) AS FIRST_30P_MOB,
    MIN(p.MOB) FILTER (WHERE p.IS_60P) AS FIRST_60P_MOB,
    MIN(p.MOB) FILTER (WHERE p.IS_90P) AS FIRST_90P_MOB,
    MIN(p.MOB) FILTER (WHERE p.IS_CHARGEOFF) AS FIRST_CO_MOB,
    MAX(p.STATE_ORDER) FILTER (WHERE p.IS_OPEN) AS MAX_OPEN_ORDER,
    MAX(p.MOB) AS LAST_MOB,
    any_value(p.STATE) FILTER (WHERE p.MOB = 0) AS MOB0_STATE
FROM opened_clients o
JOIN panel p ON p.ID = o.ID AND p.IS_OPENED
GROUP BY ALL;

CREATE OR REPLACE TABLE vintage_curves AS
WITH grid AS (
    SELECT v.OPEN_MONTH, k.range AS MOB
    FROM (SELECT DISTINCT OPEN_MONTH FROM vintage_clients) v
    CROSS JOIN range(0, 61) k
    WHERE v.OPEN_MONTH + k.range <= 0
)
SELECT
    g.OPEN_MONTH AS VINTAGE_MONTH,
    (g.OPEN_MONTH + 60) // 3 AS VINTAGE_QTR,
    g.MOB,
    COUNT(*) AS n_accounts,
    COUNT(*) FILTER (WHERE c.FIRST_30P_MOB <= g.MOB) AS ever_30p,
    COUNT(*) FILTER (WHERE c.FIRST_60P_MOB <= g.MOB) AS ever_60p,
    COUNT(*) FILTER (WHERE c.FIRST_90P_MOB <= g.MOB) AS ever_90p,
    COUNT(*) FILTER (WHERE c.FIRST_CO_MOB <= g.MOB) AS ever_co,
    COUNT(*) FILTER (WHERE c.LAST_MOB < g.MOB) AS records_ended
FROM grid g
JOIN vintage_clients c ON c.OPEN_MONTH = g.OPEN_MONTH
GROUP BY ALL;

-- First-delinquency (first 30+) MOB distribution by vintage quarter.
CREATE OR REPLACE TABLE vintage_first_delinquency AS
SELECT VINTAGE_QTR, FIRST_30P_MOB AS MOB, COUNT(*) AS n
FROM vintage_clients
WHERE FIRST_30P_MOB IS NOT NULL
GROUP BY ALL;

-- Maximum severity reached (open buckets only) by vintage quarter.
CREATE OR REPLACE TABLE vintage_max_severity AS
SELECT c.VINTAGE_QTR, COALESCE(s.STATE, 'never open') AS MAX_STATE, COUNT(*) AS n
FROM vintage_clients c
LEFT JOIN status_lookup s ON s.STATE_ORDER = c.MAX_OPEN_ORDER
GROUP BY ALL;

-- Left-truncation evidence: MOB-0 state mix by vintage month.
CREATE OR REPLACE TABLE vintage_mob0_mix AS
SELECT OPEN_MONTH, MOB0_STATE AS STATE, COUNT(*) AS n
FROM vintage_clients
GROUP BY ALL;
