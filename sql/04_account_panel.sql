-- 04_account_panel.sql
-- The analytical panel at grain ID x MONTHS_BALANCE.
-- OPEN_MONTH = first month whose status is not X; MOB counts calendar months since then
-- (dormant months count). Rows before OPEN_MONTH (leading X) have MOB NULL and are not part
-- of the opened book. Clients that never have a non-X month have no OPEN_MONTH and stay in
-- the audit only. Clients listed in config_excluded_ids are removed here.
-- DuckDB notes: '//' is integer division (PostgreSQL: '/').

CREATE OR REPLACE TABLE client_open AS
SELECT
    ID,
    MIN(MONTHS_BALANCE) AS FIRST_MONTH,
    MIN(MONTHS_BALANCE) FILTER (WHERE STATUS <> 'X') AS OPEN_MONTH,
    MAX(MONTHS_BALANCE) AS LAST_MONTH
FROM raw_credit
WHERE ID IS NOT NULL AND MONTHS_BALANCE IS NOT NULL
GROUP BY ID;

CREATE OR REPLACE TABLE panel AS
WITH base AS (
    SELECT
        r.ID,
        r.MONTHS_BALANCE,
        r.MONTHS_BALANCE + 60 AS MONTH_IDX,
        o.OPEN_MONTH,
        o.FIRST_MONTH,
        CASE WHEN o.OPEN_MONTH IS NOT NULL AND r.MONTHS_BALANCE >= o.OPEN_MONTH
             THEN r.MONTHS_BALANCE - o.OPEN_MONTH END AS MOB,
        r.MONTHS_BALANCE - o.FIRST_MONTH AS RECORD_MOB,
        r.STATUS AS RAW_STATUS,
        s.STATE,
        s.STATE_ORDER,
        s.IS_OPEN,
        s.IS_30P
    FROM raw_credit r
    JOIN client_open o USING (ID)
    JOIN status_lookup s ON s.RAW_STATUS = r.STATUS
    ANTI JOIN config_excluded_ids x ON x.ID = r.ID
)
SELECT
    b.ID,
    b.MONTHS_BALANCE,
    b.MONTH_IDX,
    b.OPEN_MONTH,
    b.MOB,
    b.RECORD_MOB,
    b.RAW_STATUS,
    b.STATE,
    b.STATE_ORDER,
    b.MOB IS NOT NULL AS IS_OPENED,
    b.IS_OPEN,
    b.STATE = 'DORMANT' AS IS_DORMANT,
    b.STATE = 'PAID-OFF' AS IS_PAID_OFF,
    b.IS_30P,
    b.RAW_STATUS IN ('2', '3', '4', '5') AS IS_60P,
    b.RAW_STATUS IN ('3', '4', '5') AS IS_90P,
    b.RAW_STATUS = '5' AS IS_CHARGEOFF,
    COALESCE(mb.MOB_BAND, 'pre-open') AS MOB_BAND,
    b.OPEN_MONTH AS VINTAGE_MONTH,
    (b.OPEN_MONTH + 60) // 3 AS VINTAGE_QTR,
    seg.HAS_APPLICATION,
    seg.AGE_BAND,
    seg.INCOME_BAND
FROM base b
LEFT JOIN config_mob_bands mb ON b.MOB BETWEEN mb.LO AND mb.HI
LEFT JOIN client_segments seg ON seg.ID = b.ID;

-- One row per opened client (has an OPEN_MONTH and is not excluded).
CREATE OR REPLACE TABLE opened_clients AS
SELECT
    o.ID,
    o.OPEN_MONTH,
    (o.OPEN_MONTH + 60) // 3 AS VINTAGE_QTR,
    o.FIRST_MONTH,
    o.LAST_MONTH,
    seg.HAS_APPLICATION,
    seg.AGE_BAND,
    seg.INCOME_BAND
FROM client_open o
LEFT JOIN client_segments seg USING (ID)
ANTI JOIN config_excluded_ids x ON x.ID = o.ID
WHERE o.OPEN_MONTH IS NOT NULL;
