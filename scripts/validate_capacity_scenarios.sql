-- Read-only validation; real estimate outputs must stay private.
SELECT scenario_id,use_case_name,availability_status,scenario_available_cus,
    scenario_capacity_percentage,expected_available_cus,expected_capacity_percentage,
    CASE WHEN
        (scenario_available_cus IS NULL AND expected_available_cus IS NOT NULL)
        OR (scenario_available_cus IS NOT NULL AND expected_available_cus IS NULL)
        OR ABS(scenario_available_cus-expected_available_cus)>0.000001
        OR (scenario_capacity_percentage IS NULL AND expected_capacity_percentage IS NOT NULL)
        OR (scenario_capacity_percentage IS NOT NULL AND expected_capacity_percentage IS NULL)
        OR ABS(scenario_capacity_percentage-expected_capacity_percentage)>0.000001
        THEN 1 ELSE 0 END AS FailingDemoResult
FROM dbo.vw_capacity_demo ORDER BY scenario_id,use_case_name;

SELECT 'duplicate_scenario_ids' AS CheckName,COUNT_BIG(*) AS FailingGroups
FROM (
    SELECT scenario_id FROM dbo.capacity_demo_periods GROUP BY scenario_id HAVING COUNT_BIG(*)>1
    UNION ALL
    SELECT scenario_id FROM dbo.capacity_estimate_periods GROUP BY scenario_id HAVING COUNT_BIG(*)>1
) d
UNION ALL
SELECT 'duplicate_estimate_capacity_days',COUNT_BIG(*) FROM (
    SELECT capacity_id,metric_date FROM dbo.capacity_estimate_periods
    GROUP BY capacity_id,metric_date HAVING COUNT_BIG(*)>1
) d
UNION ALL
SELECT 'billing_enabled_by_scenario',COUNT_BIG(*)
FROM dbo.vw_use_case_capacity_estimate WHERE can_bill<>0 OR billing_capacity_percentage IS NOT NULL
UNION ALL
SELECT 'estimated_source_changed',COUNT_BIG(*)
FROM dbo.vw_use_case_capacity_estimate
WHERE data_mode<>'Estimated' OR historical_attribution_status<>'Unvalidated'
    OR numerator_basis<>'FUAMOperationDate_Unreconciled'
UNION ALL
SELECT 'unknown_estimate_has_percentage',COUNT_BIG(*)
FROM dbo.vw_use_case_capacity_estimate
WHERE (scenario_available_cus IS NULL OR scenario_available_cus<=0
    OR missing_cu_value_count>0 OR observed_total_cus IS NULL)
    AND estimated_capacity_percentage IS NOT NULL
UNION ALL
SELECT 'demo_source_mixed',COUNT_BIG(*)
FROM dbo.vw_capacity_demo WHERE data_mode<>'Demo' OR attribution_basis<>'Synthetic' OR can_bill<>0;

SELECT 'RealConsumptionConservation' AS Scope,
    (SELECT COUNT_BIG(*) FROM dbo.vw_use_case_consumption_preview) AS SourceGroups,
    (SELECT COUNT_BIG(*) FROM dbo.vw_use_case_capacity_estimate) AS EstimateGroups,
    (SELECT SUM(metric_row_count) FROM dbo.vw_use_case_consumption_preview) AS SourceMetricRows,
    (SELECT SUM(metric_row_count) FROM dbo.vw_use_case_capacity_estimate) AS EstimateMetricRows,
    (SELECT SUM(observed_total_cus) FROM dbo.vw_use_case_consumption_preview) AS SourceCUs,
    (SELECT SUM(observed_total_cus) FROM dbo.vw_use_case_capacity_estimate) AS EstimateCUs;

SELECT metric_date,metric_capacity_id,scenario_id,estimate_status,
    SUM(metric_row_count) AS MetricRows,SUM(observed_total_cus) AS ObservedCUs,
    MAX(scenario_available_cus) AS ScenarioAvailableCUs,
    MAX(assumption_note) AS AssumptionNote
FROM dbo.vw_use_case_capacity_estimate
GROUP BY metric_date,metric_capacity_id,scenario_id,estimate_status
ORDER BY metric_date DESC;
