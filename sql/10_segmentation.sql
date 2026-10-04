-- 10_segmentation.sql
-- Age-band and income-band metrics for matched clients (credit clients with a
-- non-conflicting application record). No cross-tabs. Suppression flags use the
-- configured minimum clients and events.
-- Metrics: ever-60+ by MOB {{SEG_HORIZON}} among accounts old enough (open_month + horizon <= 0),
-- 30+ prevalence over open account-months, one-step cure from 30-149 DPD buckets.
-- DuckDB notes: UNION ALL BY NAME is DuckDB (PostgreSQL: list columns explicitly).

CREATE OR REPLACE TABLE segment_metrics AS
WITH seg AS (
    SELECT 'age_band' AS SEG_TYPE, AGE_BAND AS SEGMENT, ID FROM opened_clients WHERE AGE_BAND IS NOT NULL
    UNION ALL
    SELECT 'income_band', INCOME_BAND, ID FROM opened_clients WHERE INCOME_BAND IS NOT NULL
),
vint AS (
    SELECT s.SEG_TYPE, s.SEGMENT,
        COUNT(*) AS clients,
        COUNT(*) FILTER (WHERE v.OPEN_MONTH + {{SEG_HORIZON}} <= 0) AS eligible_h,
        COUNT(*) FILTER (WHERE v.OPEN_MONTH + {{SEG_HORIZON}} <= 0
                           AND v.FIRST_60P_MOB <= {{SEG_HORIZON}}) AS ever60_h
    FROM seg s JOIN vintage_clients v USING (ID)
    GROUP BY ALL
),
prev AS (
    SELECT s.SEG_TYPE, s.SEGMENT,
        COUNT(*) FILTER (WHERE p.IS_OPEN) AS open_months,
        COUNT(*) FILTER (WHERE p.IS_30P) AS months_30p
    FROM seg s JOIN panel p USING (ID)
    WHERE p.IS_OPENED
    GROUP BY ALL
),
cure AS (
    SELECT s.SEG_TYPE, s.SEGMENT,
        COUNT(*) AS trans_30p,
        COUNT(*) FILTER (WHERE t.TO_STATE IN ('1-29', 'PAID-OFF')) AS cures
    FROM seg s JOIN transitions t USING (ID)
    WHERE t.FROM_STATE IN ('30-59', '60-89', '90-119', '120-149')
    GROUP BY ALL
)
SELECT
    v.SEG_TYPE, v.SEGMENT, v.clients, v.eligible_h, v.ever60_h,
    COALESCE(p.open_months, 0) AS open_months, COALESCE(p.months_30p, 0) AS months_30p,
    COALESCE(c.trans_30p, 0) AS trans_30p, COALESCE(c.cures, 0) AS cures,
    v.clients < {{SEG_MIN_CLIENTS}} OR v.ever60_h < {{SEG_MIN_EVENTS}} AS suppress_ever60,
    v.clients < {{SEG_MIN_CLIENTS}} OR COALESCE(p.months_30p, 0) < {{SEG_MIN_EVENTS}} AS suppress_prev30,
    v.clients < {{SEG_MIN_CLIENTS}} OR COALESCE(c.cures, 0) < {{SEG_MIN_EVENTS}} AS suppress_cure
FROM vint v
LEFT JOIN prev p USING (SEG_TYPE, SEGMENT)
LEFT JOIN cure c USING (SEG_TYPE, SEGMENT);

-- Segment stock cube by month and state (small cells suppressed at export).
CREATE OR REPLACE TABLE segment_stock_cube AS
SELECT 'age_band' AS SEG_TYPE, AGE_BAND AS SEGMENT, MONTHS_BALANCE, STATE, COUNT(*) AS n
FROM panel WHERE IS_OPENED AND AGE_BAND IS NOT NULL GROUP BY ALL
UNION ALL
SELECT 'income_band', INCOME_BAND, MONTHS_BALANCE, STATE, COUNT(*)
FROM panel WHERE IS_OPENED AND INCOME_BAND IS NOT NULL GROUP BY ALL;

-- Selection caveat counts for the segmentation page.
CREATE OR REPLACE TABLE segment_coverage AS
SELECT
    COUNT(*) AS opened_clients,
    COUNT(*) FILTER (WHERE HAS_APPLICATION) AS matched_opened,
    COUNT(*) FILTER (WHERE AGE_BAND IS NOT NULL) AS with_age_band,
    COUNT(*) FILTER (WHERE INCOME_BAND IS NOT NULL) AS with_income_band
FROM opened_clients;

-- Per-client contributions to the segment metrics (input to the client-level bootstrap;
-- stays in DuckDB / git-ignored storage, never committed).
CREATE OR REPLACE TABLE segment_client_stats AS
SELECT
    o.ID,
    o.AGE_BAND,
    o.INCOME_BAND,
    CASE WHEN v.OPEN_MONTH + {{SEG_HORIZON}} <= 0 THEN 1 ELSE 0 END AS eligible_h,
    CASE WHEN v.OPEN_MONTH + {{SEG_HORIZON}} <= 0 AND v.FIRST_60P_MOB <= {{SEG_HORIZON}} THEN 1 ELSE 0 END AS ever60_h,
    COALESCE(p.open_months, 0) AS open_months,
    COALESCE(p.months_30p, 0) AS months_30p,
    COALESCE(t.trans_30p, 0) AS trans_30p,
    COALESCE(t.cures, 0) AS cures
FROM opened_clients o
JOIN vintage_clients v USING (ID)
LEFT JOIN (
    SELECT ID, COUNT(*) FILTER (WHERE IS_OPEN) AS open_months, COUNT(*) FILTER (WHERE IS_30P) AS months_30p
    FROM panel WHERE IS_OPENED GROUP BY ID
) p USING (ID)
LEFT JOIN (
    SELECT ID, COUNT(*) AS trans_30p, COUNT(*) FILTER (WHERE TO_STATE IN ('1-29', 'PAID-OFF')) AS cures
    FROM transitions WHERE FROM_STATE IN ('30-59', '60-89', '90-119', '120-149') GROUP BY ID
) t USING (ID)
WHERE o.AGE_BAND IS NOT NULL OR o.INCOME_BAND IS NOT NULL;
