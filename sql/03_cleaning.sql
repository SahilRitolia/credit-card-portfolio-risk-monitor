-- 03_cleaning.sql
-- Application dedupe, sentinel handling, age in years, age and income bands.
-- Duplicated IDs are kept once with a flag; when duplicates disagree on any attribute
-- the client's segment attributes are set to NULL (excluded from segmentation).
-- DuckDB notes: quantile_cont is DuckDB (PostgreSQL: percentile_cont(...) WITHIN GROUP).
-- Integer division '//' is DuckDB (PostgreSQL: '/' on integers).

CREATE OR REPLACE TABLE app_dedup AS
WITH attrs AS (
    SELECT
        *,
        md5(concat_ws('|', CODE_GENDER, FLAG_OWN_CAR, FLAG_OWN_REALTY, CNT_CHILDREN,
            AMT_INCOME_TOTAL, NAME_INCOME_TYPE, NAME_EDUCATION_TYPE, NAME_FAMILY_STATUS,
            NAME_HOUSING_TYPE, DAYS_BIRTH, DAYS_EMPLOYED, FLAG_WORK_PHONE, FLAG_PHONE,
            FLAG_EMAIL, OCCUPATION_TYPE, CNT_FAM_MEMBERS)) AS attr_hash
    FROM raw_application
    WHERE ID IS NOT NULL
),
per_id AS (
    SELECT ID, COUNT(*) AS n_rows, COUNT(DISTINCT attr_hash) AS n_versions
    FROM attrs
    GROUP BY ID
)
SELECT
    a.* EXCLUDE (attr_hash),
    p.n_rows > 1 AS IS_DUPLICATE_ID,
    p.n_versions > 1 AS HAS_CONFLICT
FROM attrs a
JOIN per_id p USING (ID)
QUALIFY ROW_NUMBER() OVER (PARTITION BY a.ID ORDER BY a.attr_hash) = 1;

CREATE OR REPLACE TABLE app_clean AS
SELECT
    ID,
    IS_DUPLICATE_ID,
    HAS_CONFLICT,
    CODE_GENDER,
    AMT_INCOME_TOTAL,
    NAME_INCOME_TYPE,
    NAME_EDUCATION_TYPE,
    CASE WHEN DAYS_EMPLOYED = 365243 THEN NULL ELSE DAYS_EMPLOYED END AS DAYS_EMPLOYED,
    DAYS_EMPLOYED = 365243 AS EMPLOYED_SENTINEL,
    -DAYS_BIRTH / 365.25 AS AGE_YEARS
FROM app_dedup;

-- Income quartile thresholds are computed on matched, non-conflicting clients only.
CREATE OR REPLACE TABLE income_thresholds AS
SELECT
    quantile_cont(AMT_INCOME_TOTAL, 0.25) AS q25,
    quantile_cont(AMT_INCOME_TOTAL, 0.50) AS q50,
    quantile_cont(AMT_INCOME_TOTAL, 0.75) AS q75
FROM app_clean a
SEMI JOIN (SELECT DISTINCT ID FROM raw_credit) c ON a.ID = c.ID
WHERE NOT HAS_CONFLICT;

-- One row per credit client with segment attributes (NULL when unmatched or conflicting).
CREATE OR REPLACE TABLE client_segments AS
WITH cr AS (SELECT DISTINCT ID FROM raw_credit WHERE ID IS NOT NULL)
SELECT
    cr.ID,
    a.ID IS NOT NULL AS HAS_APPLICATION,
    COALESCE(a.HAS_CONFLICT, FALSE) AS HAS_CONFLICT,
    CASE WHEN a.ID IS NULL OR a.HAS_CONFLICT THEN NULL ELSE a.AGE_YEARS END AS AGE_YEARS,
    CASE WHEN a.ID IS NULL OR a.HAS_CONFLICT THEN NULL ELSE ab.AGE_BAND END AS AGE_BAND,
    CASE
        WHEN a.ID IS NULL OR a.HAS_CONFLICT OR a.AMT_INCOME_TOTAL IS NULL THEN NULL
        WHEN a.AMT_INCOME_TOTAL <= t.q25 THEN 'Q1 (lowest)'
        WHEN a.AMT_INCOME_TOTAL <= t.q50 THEN 'Q2'
        WHEN a.AMT_INCOME_TOTAL <= t.q75 THEN 'Q3'
        ELSE 'Q4 (highest)'
    END AS INCOME_BAND
FROM cr
LEFT JOIN app_clean a ON a.ID = cr.ID
LEFT JOIN config_age_bands ab ON a.AGE_YEARS >= ab.LO AND a.AGE_YEARS < ab.HI
CROSS JOIN income_thresholds t;
