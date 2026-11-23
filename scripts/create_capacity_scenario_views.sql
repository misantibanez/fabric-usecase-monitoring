-- Run GO-delimited batches in the monitoring SQL analytics endpoint.
-- These views never enable billing or write to production history/consumption.
CREATE OR ALTER VIEW dbo.vw_capacity_scenario_denominators AS
WITH periods AS (
    SELECT 'Demo' AS data_mode, * FROM dbo.capacity_demo_periods
    UNION ALL SELECT 'Estimated', * FROM dbo.capacity_estimate_periods
), intervals AS (
    SELECT 'Demo' AS data_mode, * FROM dbo.capacity_demo_intervals
    UNION ALL SELECT 'Estimated', * FROM dbo.capacity_estimate_intervals
), ordered AS (
    SELECT i.*,
        MAX(interval_end) OVER (
            PARTITION BY data_mode, scenario_id
            ORDER BY interval_start, interval_end, interval_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS previous_max_end
    FROM intervals i
), stats AS (
    SELECT p.data_mode, p.scenario_id,
        COUNT(i.scenario_id) AS interval_count,
        MIN(i.interval_start) AS first_start, MAX(i.interval_end) AS last_end,
        SUM(CASE WHEN i.previous_max_end > i.interval_start THEN 1 ELSE 0 END) AS overlap_count,
        SUM(CASE WHEN i.scenario_id IS NOT NULL AND (
            i.interval_start IS NULL OR i.interval_end IS NULL
            OR i.interval_start >= i.interval_end
            OR i.interval_start < p.window_start OR i.interval_end > p.window_end
            OR i.[state] IS NULL OR i.[state] NOT IN ('Active','Inactive','Unknown')
            OR NULLIF(TRIM(i.state_basis),'') IS NULL
            OR NULLIF(TRIM(i.sku_basis),'') IS NULL
            OR (i.sku_cu IS NOT NULL AND (
                i.sku_cu NOT IN (2,4,8,16,32,64,128,256,512,1024,2048)
                OR i.sku IS NULL OR i.sku <> CONCAT('F',i.sku_cu)))
        ) THEN 1 ELSE 0 END) AS invalid_count,
        SUM(CASE WHEN i.[state] = 'Unknown'
            OR (i.[state] = 'Active' AND i.sku_cu IS NULL) THEN 1 ELSE 0 END) AS unknown_count,
        SUM(DATEDIFF_BIG(microsecond,i.interval_start,i.interval_end)/1000000.0) AS interval_seconds,
        SUM(CASE WHEN i.[state]='Active'
            THEN DATEDIFF_BIG(microsecond,i.interval_start,i.interval_end)/1000000.0
            ELSE 0 END) AS active_seconds,
        SUM(CASE WHEN i.[state]='Inactive' THEN 0
            WHEN i.[state]='Active' THEN
                (DATEDIFF_BIG(microsecond,i.interval_start,i.interval_end)/1000000.0)*i.sku_cu
        END) AS raw_available_cus
    FROM periods p LEFT JOIN ordered i
        ON p.data_mode=i.data_mode AND p.scenario_id=i.scenario_id
    GROUP BY p.data_mode,p.scenario_id
), assessed AS (
    SELECT p.*, s.interval_count,s.overlap_count,s.unknown_count,
        s.interval_seconds,s.active_seconds,s.raw_available_cus,
        CASE
            WHEN p.scenario_id IS NULL OR p.capacity_id IS NULL OR p.metric_date IS NULL
                OR p.window_start IS NULL OR p.window_end IS NULL
                OR p.source_utc_offset_minutes IS NULL
                OR p.source_utc_offset_minutes NOT BETWEEN -720 AND 840
                OR NULLIF(TRIM(p.assumption_note),'') IS NULL
                OR p.window_start <> DATEADD(minute,-p.source_utc_offset_minutes,CAST(p.metric_date AS datetime2))
                OR p.window_end <> DATEADD(day,1,p.window_start)
                OR s.invalid_count>0 THEN 'BlockedInvalidDefinition'
            WHEN s.interval_count=0 THEN 'BlockedMissingIntervals'
            WHEN s.overlap_count>0 THEN 'BlockedOverlappingIntervals'
            WHEN s.first_start<>p.window_start OR s.last_end<>p.window_end
                OR ABS(s.interval_seconds-DATEDIFF_BIG(microsecond,p.window_start,p.window_end)/1000000.0)>0.000001
                THEN 'BlockedTelemetryGap'
            WHEN s.unknown_count>0 THEN 'BlockedUnknownStateOrSKU'
            WHEN s.raw_available_cus=0 THEN 'NoActiveCapacity'
            ELSE 'ScenarioReady'
        END AS availability_status
    FROM periods p JOIN stats s ON p.data_mode=s.data_mode AND p.scenario_id=s.scenario_id
)
SELECT data_mode,scenario_id,capacity_id,metric_date,source_utc_offset_minutes,
    window_start,window_end,assumption_note,interval_count,overlap_count,
    unknown_count,interval_seconds,active_seconds,availability_status,
    CASE WHEN availability_status IN ('ScenarioReady','NoActiveCapacity')
        THEN raw_available_cus END AS scenario_available_cus,
    CAST(0 AS bit) AS can_bill
FROM assessed;
GO

CREATE OR ALTER VIEW dbo.vw_capacity_demo AS
SELECT d.*, c.use_case_name,c.root_domain_name,c.subdomain_name,
    c.observed_total_cus,c.missing_cu_value_count,
    c.expected_available_cus,c.expected_capacity_percentage,
    CASE WHEN d.scenario_available_cus>0 AND c.missing_cu_value_count=0
        AND c.observed_total_cus>=0
        THEN 100.0*c.observed_total_cus/d.scenario_available_cus END AS scenario_capacity_percentage,
    CAST('Synthetic' AS varchar(40)) AS attribution_basis,
    CAST('Demo - not for billing' AS varchar(80)) AS usage_warning
FROM dbo.capacity_demo_consumption c
JOIN dbo.vw_capacity_scenario_denominators d
    ON d.data_mode='Demo' AND d.scenario_id=c.scenario_id;
GO

CREATE OR ALTER VIEW dbo.vw_use_case_capacity_estimate AS
WITH estimate_keys AS (
    SELECT capacity_id,metric_date,COUNT_BIG(*) AS matching_scenario_count,
        MIN(scenario_id) AS scenario_id
    FROM dbo.capacity_estimate_periods GROUP BY capacity_id,metric_date
), scenario_ids AS (
    SELECT scenario_id,COUNT_BIG(*) AS matching_id_count
    FROM dbo.capacity_estimate_periods GROUP BY scenario_id
)
SELECT p.*, CAST('Estimated' AS varchar(20)) AS data_mode,
    d.scenario_id,d.assumption_note,d.source_utc_offset_minutes,
    d.window_start,d.window_end,d.active_seconds,d.interval_count,d.overlap_count,
    d.unknown_count,d.scenario_available_cus,
    CASE WHEN k.matching_scenario_count>1 THEN 'BlockedMultipleScenarios'
        WHEN ids.matching_id_count>1 THEN 'BlockedDuplicateScenarioId'
        ELSE COALESCE(d.availability_status,'BlockedMissingAssumptions')
    END AS estimate_status,
    CASE WHEN d.scenario_available_cus>0 AND p.missing_cu_value_count=0
        AND p.observed_total_cus>=0
        THEN 100.0*p.observed_total_cus/d.scenario_available_cus
    END AS estimated_capacity_percentage,
    CAST('FUAMOperationDate_Unreconciled' AS varchar(40)) AS numerator_basis,
    CAST(0 AS bit) AS can_bill,
    CAST(NULL AS float) AS billing_capacity_percentage,
    CAST('Estimated - not for billing; current classification and unvalidated continuity/SKU' AS varchar(120)) AS usage_warning
FROM dbo.vw_use_case_consumption_preview p
LEFT JOIN estimate_keys k ON p.metric_capacity_id=k.capacity_id AND p.metric_date=k.metric_date
LEFT JOIN scenario_ids ids ON k.scenario_id=ids.scenario_id AND k.matching_scenario_count=1
LEFT JOIN dbo.vw_capacity_scenario_denominators d
    ON k.matching_scenario_count=1 AND ids.matching_id_count=1
        AND d.data_mode='Estimated' AND k.scenario_id=d.scenario_id;
GO
