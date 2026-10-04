-- 02_data_quality.sql
-- Raw-level data quality: duplicates, nulls, invalid statuses, key overlap (anti-joins),
-- history lengths, month gaps (LAG), sentinel values and raw status behaviour.
-- Nothing here is cleaned or dropped; every finding is a measured count.
-- DuckDB notes: FILTER (WHERE ...) on aggregates is standard SQL and works in PostgreSQL;
-- QUALIFY is DuckDB-specific (PostgreSQL: wrap the window in a subquery).

-- Month-gap table: one row per successive pair of records within a client.
CREATE OR REPLACE TABLE dq_month_gaps AS
WITH ordered AS (
    SELECT
        ID,
        LAG(MONTHS_BALANCE) OVER (PARTITION BY ID ORDER BY MONTHS_BALANCE) AS previous_month,
        MONTHS_BALANCE AS current_month
    FROM raw_credit
    WHERE ID IS NOT NULL AND MONTHS_BALANCE IS NOT NULL
)
SELECT
    ID,
    previous_month,
    current_month,
    current_month - previous_month AS month_difference,
    CASE
        WHEN current_month - previous_month = 1 THEN 'consecutive'
        WHEN current_month - previous_month = 2 THEN 'single_gap'
        WHEN current_month - previous_month = 0 THEN 'duplicate_month'
        ELSE 'multi_gap'
    END AS gap_flag
FROM ordered
WHERE previous_month IS NOT NULL;

-- Raw consecutive transitions on raw STATUS (used for status-semantics evidence).
CREATE OR REPLACE TABLE raw_transitions AS
WITH ordered AS (
    SELECT
        ID,
        MONTHS_BALANCE,
        STATUS,
        LEAD(MONTHS_BALANCE) OVER w AS next_month,
        LEAD(STATUS) OVER w AS next_status,
        LAG(STATUS) OVER w AS prev_status,
        LAG(MONTHS_BALANCE) OVER w AS prev_month
    FROM raw_credit
    WINDOW w AS (PARTITION BY ID ORDER BY MONTHS_BALANCE)
)
SELECT ID, MONTHS_BALANCE AS ORIGIN_MONTH, STATUS AS FROM_STATUS, next_status AS TO_STATUS
FROM ordered
WHERE next_month = MONTHS_BALANCE + 1;

CREATE OR REPLACE TABLE dq_raw_transition_counts AS
SELECT FROM_STATUS, TO_STATUS, COUNT(*) AS n
FROM raw_transitions
GROUP BY ALL;

-- Per-client raw profile.
CREATE OR REPLACE TABLE dq_client_profile AS
WITH firsts AS (
    SELECT ID, STATUS AS FIRST_STATUS
    FROM raw_credit
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ID ORDER BY MONTHS_BALANCE) = 1
),
first_nonx AS (
    SELECT ID, STATUS AS FIRST_NONX_STATUS, MONTHS_BALANCE AS FIRST_NONX_MONTH
    FROM raw_credit
    WHERE STATUS <> 'X'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ID ORDER BY MONTHS_BALANCE) = 1
)
SELECT
    c.ID,
    COUNT(*) AS n_records,
    MIN(c.MONTHS_BALANCE) AS first_month,
    MAX(c.MONTHS_BALANCE) AS last_month,
    COUNT(*) FILTER (WHERE c.STATUS <> 'X') AS n_nonx,
    any_value(f.FIRST_STATUS) AS first_status,
    any_value(n.FIRST_NONX_STATUS) AS first_nonx_status,
    any_value(n.FIRST_NONX_MONTH) AS first_nonx_month
FROM raw_credit c
LEFT JOIN firsts f USING (ID)
LEFT JOIN first_nonx n USING (ID)
WHERE c.ID IS NOT NULL
GROUP BY c.ID;

-- Dormancy exits and re-entries on raw rows.
CREATE OR REPLACE TABLE dq_x_behaviour AS
WITH seq AS (
    SELECT
        ID,
        MONTHS_BALANCE,
        STATUS,
        LAG(STATUS) OVER (PARTITION BY ID ORDER BY MONTHS_BALANCE) AS prev_status,
        LAG(MONTHS_BALANCE) OVER (PARTITION BY ID ORDER BY MONTHS_BALANCE) AS prev_month,
        COUNT(*) FILTER (WHERE STATUS IN ('0','1','2','3','4','5')) OVER (
            PARTITION BY ID ORDER BY MONTHS_BALANCE ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_active_rows
    FROM raw_credit
)
SELECT
    ID,
    MONTHS_BALANCE,
    (prev_status IN ('0','1','2','3','4','5') AND STATUS = 'X' AND prev_month = MONTHS_BALANCE - 1)
        AS is_active_to_x,
    -- Re-entry: dormant month followed by any non-X month (including C) after earlier 0-5 activity.
    (prev_status = 'X' AND STATUS <> 'X' AND prev_month = MONTHS_BALANCE - 1
        AND prior_active_rows > 0) AS is_x_reentry
FROM seq;

CREATE OR REPLACE TABLE dq_status_counts AS
SELECT STATUS, COUNT(*) AS n_rows, COUNT(DISTINCT ID) AS n_clients
FROM raw_credit
GROUP BY STATUS;

CREATE OR REPLACE TABLE dq_status_month0 AS
SELECT STATUS, COUNT(*) AS n
FROM raw_credit
WHERE MONTHS_BALANCE = 0
GROUP BY STATUS;

-- Scalar metrics in one long table: (metric, value).
CREATE OR REPLACE TABLE dq_metrics AS
WITH app_ids AS (SELECT DISTINCT ID FROM raw_application WHERE ID IS NOT NULL),
cr_ids AS (SELECT DISTINCT ID FROM raw_credit WHERE ID IS NOT NULL),
app_only AS (SELECT a.ID FROM app_ids a ANTI JOIN cr_ids c ON a.ID = c.ID),
credit_only AS (SELECT c.ID FROM cr_ids c ANTI JOIN app_ids a ON a.ID = c.ID),
dup_ids AS (SELECT ID FROM raw_application GROUP BY ID HAVING COUNT(*) > 1),
dup_month AS (SELECT ID, MONTHS_BALANCE FROM raw_credit GROUP BY ALL HAVING COUNT(*) > 1),
max_credit AS (SELECT MAX(ID) AS max_id FROM cr_ids),
co_from AS (
    SELECT * FROM raw_transitions WHERE FROM_STATUS = '5' AND TO_STATUS <> 'X'
),
m AS (
    SELECT 'credit_rows' AS metric, (SELECT COUNT(*) FROM raw_credit)::DOUBLE AS value
    UNION ALL SELECT 'credit_clients', (SELECT COUNT(*) FROM cr_ids)
    UNION ALL SELECT 'credit_dup_id_month', (SELECT COUNT(*) FROM dup_month)
    UNION ALL SELECT 'credit_null_id', (SELECT COUNT(*) FROM raw_credit WHERE ID IS NULL)
    UNION ALL SELECT 'credit_null_month', (SELECT COUNT(*) FROM raw_credit WHERE MONTHS_BALANCE IS NULL)
    UNION ALL SELECT 'credit_invalid_status',
        (SELECT COUNT(*) FROM raw_credit c ANTI JOIN status_lookup s ON c.STATUS = s.RAW_STATUS)
    UNION ALL SELECT 'month_min', (SELECT MIN(MONTHS_BALANCE) FROM raw_credit)
    UNION ALL SELECT 'month_max', (SELECT MAX(MONTHS_BALANCE) FROM raw_credit)
    UNION ALL SELECT 'month_values', (SELECT COUNT(DISTINCT MONTHS_BALANCE) FROM raw_credit)
    UNION ALL SELECT 'month_successive_pairs', (SELECT COUNT(*) FROM dq_month_gaps)
    UNION ALL SELECT 'month_gap_pairs', (SELECT COUNT(*) FROM dq_month_gaps WHERE gap_flag <> 'consecutive')
    UNION ALL SELECT 'month_single_gap_pairs', (SELECT COUNT(*) FROM dq_month_gaps WHERE gap_flag = 'single_gap')
    UNION ALL SELECT 'month_multi_gap_pairs', (SELECT COUNT(*) FROM dq_month_gaps WHERE gap_flag = 'multi_gap')
    UNION ALL SELECT 'app_rows', (SELECT COUNT(*) FROM raw_application)
    UNION ALL SELECT 'app_unique_ids', (SELECT COUNT(*) FROM app_ids)
    UNION ALL SELECT 'app_duplicated_ids', (SELECT COUNT(*) FROM dup_ids)
    UNION ALL SELECT 'app_null_id', (SELECT COUNT(*) FROM raw_application WHERE ID IS NULL)
    UNION ALL SELECT 'matched_clients', (SELECT COUNT(*) FROM cr_ids c SEMI JOIN app_ids a ON a.ID = c.ID)
    UNION ALL SELECT 'application_only', (SELECT COUNT(*) FROM app_only)
    UNION ALL SELECT 'credit_only', (SELECT COUNT(*) FROM credit_only)
    UNION ALL SELECT 'app_ids_above_max_credit_id',
        (SELECT COUNT(*) FROM app_ids, max_credit WHERE ID > max_id)
    UNION ALL SELECT 'app_ids_at_or_below_max_credit_id',
        (SELECT COUNT(*) FROM app_ids, max_credit WHERE ID <= max_id)
    UNION ALL SELECT 'matched_at_or_below_max_credit_id',
        (SELECT COUNT(*) FROM app_ids a, max_credit WHERE a.ID <= max_id
           AND a.ID IN (SELECT ID FROM cr_ids))
    UNION ALL SELECT 'matched_above_max_credit_id',
        (SELECT COUNT(*) FROM app_ids a, max_credit WHERE a.ID > max_id
           AND a.ID IN (SELECT ID FROM cr_ids))
    UNION ALL SELECT 'records_per_client_median', (SELECT MEDIAN(n_records) FROM dq_client_profile)
    UNION ALL SELECT 'records_per_client_mean', (SELECT AVG(n_records) FROM dq_client_profile)
    UNION ALL SELECT 'records_per_client_max', (SELECT MAX(n_records) FROM dq_client_profile)
    UNION ALL SELECT 'single_record_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE n_records = 1)
    UNION ALL SELECT 'short_history_clients',
        (SELECT COUNT(*) FROM dq_client_profile WHERE n_records < {{SHORT_HISTORY_MONTHS}})
    UNION ALL SELECT 'full_window_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE n_records = 61)
    UNION ALL SELECT 'first_status_x_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE first_status = 'X')
    UNION ALL SELECT 'first_status_0_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE first_status = '0')
    UNION ALL SELECT 'first_status_c_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE first_status = 'C')
    UNION ALL SELECT 'first_status_other_clients',
        (SELECT COUNT(*) FROM dq_client_profile WHERE first_status NOT IN ('X','0','C'))
    UNION ALL SELECT 'x_only_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE n_nonx = 0)
    UNION ALL SELECT 'clients_with_nonx', (SELECT COUNT(*) FROM dq_client_profile WHERE n_nonx > 0)
    UNION ALL SELECT 'first_nonx_0_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE first_nonx_status = '0')
    UNION ALL SELECT 'first_nonx_c_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE first_nonx_status = 'C')
    UNION ALL SELECT 'first_nonx_1_clients', (SELECT COUNT(*) FROM dq_client_profile WHERE first_nonx_status = '1')
    UNION ALL SELECT 'record_mob_differs_clients',
        (SELECT COUNT(*) FROM dq_client_profile WHERE n_nonx > 0 AND first_nonx_month <> first_month)
    UNION ALL SELECT 'c_transitions_total', (SELECT COUNT(*) FROM raw_transitions WHERE FROM_STATUS = 'C')
    UNION ALL SELECT 'c_to_c', (SELECT COUNT(*) FROM raw_transitions WHERE FROM_STATUS = 'C' AND TO_STATUS = 'C')
    UNION ALL SELECT 'c_to_open',
        (SELECT COUNT(*) FROM raw_transitions WHERE FROM_STATUS = 'C' AND TO_STATUS IN ('0','1','2','3','4','5'))
    UNION ALL SELECT 'c_to_x', (SELECT COUNT(*) FROM raw_transitions WHERE FROM_STATUS = 'C' AND TO_STATUS = 'X')
    UNION ALL SELECT 'c_preceded_by_open',
        (SELECT COUNT(*) FROM raw_transitions WHERE TO_STATUS = 'C' AND FROM_STATUS IN ('0','1','2','3','4','5'))
    UNION ALL SELECT 'open_preceded_by_c',
        (SELECT COUNT(*) FROM raw_transitions WHERE FROM_STATUS = 'C' AND TO_STATUS IN ('0','1','2','3','4','5'))
    UNION ALL SELECT 'delinquent_preceded_by_c',
        (SELECT COUNT(*) FROM raw_transitions WHERE FROM_STATUS = 'C' AND TO_STATUS IN ('1','2','3','4','5'))
    UNION ALL SELECT 'active_to_x_exits', (SELECT COUNT(*) FROM dq_x_behaviour WHERE is_active_to_x)
    UNION ALL SELECT 'active_to_x_clients', (SELECT COUNT(DISTINCT ID) FROM dq_x_behaviour WHERE is_active_to_x)
    UNION ALL SELECT 'x_to_active_reentries', (SELECT COUNT(*) FROM dq_x_behaviour WHERE is_x_reentry)
    UNION ALL SELECT 'x_to_active_clients', (SELECT COUNT(DISTINCT ID) FROM dq_x_behaviour WHERE is_x_reentry)
    UNION ALL SELECT 'exiting_clients_who_reenter',
        (SELECT COUNT(*) FROM (
            SELECT ID FROM dq_x_behaviour GROUP BY ID
            HAVING BOOL_OR(is_active_to_x) AND BOOL_OR(is_x_reentry)))
    UNION ALL SELECT 'co_transitions_nonx', (SELECT COUNT(*) FROM co_from)
    UNION ALL SELECT 'co_to_nonco_consecutive_nonx', (SELECT COUNT(*) FROM co_from WHERE TO_STATUS <> '5')
    UNION ALL SELECT 'co_to_x', (SELECT COUNT(*) FROM raw_transitions WHERE FROM_STATUS = '5' AND TO_STATUS = 'X')
    UNION ALL SELECT 'co_to_c', (SELECT COUNT(*) FROM co_from WHERE TO_STATUS = 'C')
    UNION ALL SELECT 'co_to_0', (SELECT COUNT(*) FROM co_from WHERE TO_STATUS = '0')
    UNION ALL SELECT 'co_to_1', (SELECT COUNT(*) FROM co_from WHERE TO_STATUS = '1')
    UNION ALL SELECT 'co_to_2', (SELECT COUNT(*) FROM co_from WHERE TO_STATUS = '2')
    UNION ALL SELECT 'co_to_3', (SELECT COUNT(*) FROM co_from WHERE TO_STATUS = '3')
    UNION ALL SELECT 'co_to_4', (SELECT COUNT(*) FROM co_from WHERE TO_STATUS = '4')
    UNION ALL SELECT 'open_accounts_m0',
        (SELECT COUNT(*) FROM raw_credit WHERE MONTHS_BALANCE = 0 AND STATUS IN ('0','1','2','3','4','5'))
    UNION ALL SELECT 'open_accounts_m1',
        (SELECT COUNT(*) FROM raw_credit WHERE MONTHS_BALANCE = -1 AND STATUS IN ('0','1','2','3','4','5'))
    UNION ALL SELECT 'nonx_m1', (SELECT COUNT(*) FROM raw_credit WHERE MONTHS_BALANCE = -1 AND STATUS <> 'X')
    UNION ALL SELECT 'app_days_employed_sentinel',
        (SELECT COUNT(*) FROM raw_application WHERE DAYS_EMPLOYED = 365243)
    UNION ALL SELECT 'app_occupation_null', (SELECT COUNT(*) FROM raw_application WHERE OCCUPATION_TYPE IS NULL)
    UNION ALL SELECT 'app_income_null', (SELECT COUNT(*) FROM raw_application WHERE AMT_INCOME_TOTAL IS NULL)
    UNION ALL SELECT 'app_days_birth_null', (SELECT COUNT(*) FROM raw_application WHERE DAYS_BIRTH IS NULL)
    UNION ALL SELECT 'app_age_min_years', (SELECT MIN(-DAYS_BIRTH / 365.25) FROM raw_application)
    UNION ALL SELECT 'app_age_max_years', (SELECT MAX(-DAYS_BIRTH / 365.25) FROM raw_application)
    UNION ALL SELECT 'max_credit_id', (SELECT max_id FROM max_credit)
    UNION ALL SELECT 'max_credit_id_records',
        (SELECT n_records FROM dq_client_profile, max_credit WHERE ID = max_id)
    UNION ALL SELECT 'max_credit_id_first_month',
        (SELECT first_month FROM dq_client_profile, max_credit WHERE ID = max_id)
    UNION ALL SELECT 'max_credit_id_last_month',
        (SELECT last_month FROM dq_client_profile, max_credit WHERE ID = max_id)
    UNION ALL SELECT 'max_credit_id_first_status_is_c',
        (SELECT CASE WHEN first_status = 'C' THEN 1 ELSE 0 END FROM dq_client_profile, max_credit WHERE ID = max_id)
)
SELECT metric, value FROM m;

-- Null counts per application column (for the missing-values check).
CREATE OR REPLACE TABLE dq_app_nulls AS
UNPIVOT (
    SELECT
        COUNT(*) FILTER (WHERE ID IS NULL) AS ID,
        COUNT(*) FILTER (WHERE CODE_GENDER IS NULL) AS CODE_GENDER,
        COUNT(*) FILTER (WHERE AMT_INCOME_TOTAL IS NULL) AS AMT_INCOME_TOTAL,
        COUNT(*) FILTER (WHERE DAYS_BIRTH IS NULL) AS DAYS_BIRTH,
        COUNT(*) FILTER (WHERE DAYS_EMPLOYED IS NULL) AS DAYS_EMPLOYED,
        COUNT(*) FILTER (WHERE NAME_INCOME_TYPE IS NULL) AS NAME_INCOME_TYPE,
        COUNT(*) FILTER (WHERE NAME_EDUCATION_TYPE IS NULL) AS NAME_EDUCATION_TYPE,
        COUNT(*) FILTER (WHERE NAME_FAMILY_STATUS IS NULL) AS NAME_FAMILY_STATUS,
        COUNT(*) FILTER (WHERE NAME_HOUSING_TYPE IS NULL) AS NAME_HOUSING_TYPE,
        COUNT(*) FILTER (WHERE OCCUPATION_TYPE IS NULL) AS OCCUPATION_TYPE,
        COUNT(*) FILTER (WHERE CNT_FAM_MEMBERS IS NULL) AS CNT_FAM_MEMBERS
    FROM raw_application
) ON COLUMNS(*) INTO NAME column_name VALUE n_null;

-- New charge-offs within 12 months among accounts open in status 0-4 at an origin month
-- (raw rows; verification target for the event-count discussion in the audit).
CREATE OR REPLACE TABLE dq_new_chargeoffs AS
WITH origins AS (SELECT * FROM (VALUES (-36), (-30), (-24), (-18), (-12)) t(ORIGIN)),
open_at AS (
    SELECT o.ORIGIN, r.ID
    FROM origins o
    JOIN raw_credit r ON r.MONTHS_BALANCE = o.ORIGIN AND r.STATUS IN ('0','1','2','3','4')
)
SELECT
    a.ORIGIN,
    COUNT(*) AS open_0_4,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM raw_credit r
        WHERE r.ID = a.ID AND r.STATUS = '5'
          AND r.MONTHS_BALANCE BETWEEN a.ORIGIN + 1 AND a.ORIGIN + 12
    )) AS new_co_12m
FROM open_at a
GROUP BY a.ORIGIN;
