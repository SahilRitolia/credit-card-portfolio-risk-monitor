-- 01_schema.sql
-- Typed views over the two raw files, the status lookup and configuration tables.
-- Inputs: src_application, src_credit (all VARCHAR; registered by src/data/ingestion.py).
-- Template values in double braces are substituted by src/data/sql_runner.py from
-- config/params.yaml; nothing in this file is a hand-typed result.
-- DuckDB notes: TRY_CAST returns NULL instead of failing (PostgreSQL has no TRY_CAST;
-- use a CASE with a regex test). CREATE OR REPLACE VIEW/TABLE is DuckDB syntax
-- (PostgreSQL: CREATE OR REPLACE VIEW exists, tables need DROP TABLE IF EXISTS first).

CREATE OR REPLACE VIEW raw_credit_text AS
SELECT
    TRIM(CAST(ID AS VARCHAR))             AS ID_TEXT,
    TRIM(CAST(MONTHS_BALANCE AS VARCHAR)) AS MONTHS_BALANCE_TEXT,
    UPPER(TRIM(CAST(STATUS AS VARCHAR)))  AS STATUS
FROM src_credit;

CREATE OR REPLACE TABLE raw_credit AS
SELECT
    TRY_CAST(ID_TEXT AS BIGINT)              AS ID,
    TRY_CAST(MONTHS_BALANCE_TEXT AS INTEGER) AS MONTHS_BALANCE,
    STATUS
FROM raw_credit_text;

CREATE OR REPLACE TABLE raw_application AS
SELECT
    TRY_CAST(ID AS BIGINT)                AS ID,
    CODE_GENDER,
    FLAG_OWN_CAR,
    FLAG_OWN_REALTY,
    TRY_CAST(CNT_CHILDREN AS INTEGER)     AS CNT_CHILDREN,
    TRY_CAST(AMT_INCOME_TOTAL AS DOUBLE)  AS AMT_INCOME_TOTAL,
    NAME_INCOME_TYPE,
    NAME_EDUCATION_TYPE,
    NAME_FAMILY_STATUS,
    NAME_HOUSING_TYPE,
    TRY_CAST(DAYS_BIRTH AS INTEGER)       AS DAYS_BIRTH,
    TRY_CAST(DAYS_EMPLOYED AS INTEGER)    AS DAYS_EMPLOYED,
    TRY_CAST(FLAG_MOBIL AS INTEGER)       AS FLAG_MOBIL,
    TRY_CAST(FLAG_WORK_PHONE AS INTEGER)  AS FLAG_WORK_PHONE,
    TRY_CAST(FLAG_PHONE AS INTEGER)       AS FLAG_PHONE,
    TRY_CAST(FLAG_EMAIL AS INTEGER)       AS FLAG_EMAIL,
    NULLIF(TRIM(OCCUPATION_TYPE), '')     AS OCCUPATION_TYPE,
    TRY_CAST(CNT_FAM_MEMBERS AS DOUBLE)   AS CNT_FAM_MEMBERS
FROM src_application;

-- Status lookup. STATE_ORDER is the severity rank used by every chart and roll definition.
-- STATE_LITERAL is the source documentation's reading, kept only for the sensitivity view.
CREATE OR REPLACE TABLE status_lookup AS
SELECT * FROM (VALUES
    ('C', 'PAID-OFF',   'CURRENT',  0, 'absorbing exit',               FALSE, FALSE),
    ('X', 'DORMANT',    'OUTSIDE',  1, 'transient, outside open book', FALSE, FALSE),
    ('0', '1-29',       '1-29',     2, 'open, transient',              TRUE,  FALSE),
    ('1', '30-59',      '30-59',    3, 'open, transient',              TRUE,  TRUE),
    ('2', '60-89',      '60-89',    4, 'open, transient',              TRUE,  TRUE),
    ('3', '90-119',     '90-119',   5, 'open, transient',              TRUE,  TRUE),
    ('4', '120-149',    '120-149',  6, 'open, transient',              TRUE,  TRUE),
    ('5', 'CHARGE-OFF', 'CHARGE-OFF', 7, 'absorbing',                  TRUE,  TRUE)
) AS t(RAW_STATUS, STATE, STATE_LITERAL, STATE_ORDER, STATE_CLASS, IS_OPEN, IS_30P);

-- Configuration tables generated from config/params.yaml.
CREATE OR REPLACE TABLE config_kv AS
SELECT * FROM (VALUES {{CONFIG_VALUES}}) AS t(KEY, VALUE);

CREATE OR REPLACE TABLE config_mob_bands AS
SELECT * FROM (VALUES {{MOB_BANDS_VALUES}}) AS t(BAND_ORDER, MOB_BAND, LO, HI);

CREATE OR REPLACE TABLE config_age_bands AS
SELECT * FROM (VALUES {{AGE_BANDS_VALUES}}) AS t(BAND_ORDER, AGE_BAND, LO, HI);

CREATE OR REPLACE TABLE config_periods AS
SELECT * FROM (VALUES {{PERIODS_VALUES}}) AS t(PERIOD_ORDER, PERIOD, START_MONTH, END_MONTH);

-- Clients excluded from analysis by an evidence-based rule (file truncation test).
CREATE OR REPLACE TABLE config_excluded_ids AS
SELECT * FROM (VALUES {{EXCLUDED_IDS_VALUES}}) AS t(ID, REASON)
WHERE ID IS NOT NULL;
