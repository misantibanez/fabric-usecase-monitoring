CREATE OR ALTER VIEW dbo.vw_monitoring_daily_coverage AS
WITH denominators AS (
    SELECT capacity_id,metric_date,COUNT_BIG(*) AS scenario_count,
        MAX(scenario_available_cus) AS scenario_available_cus,
        MAX(availability_status) AS availability_status,
        MAX(assumption_note) AS assumption_note,
        MAX(source_utc_offset_minutes) AS source_utc_offset_minutes,
        MAX(window_start) AS window_start,MAX(window_end) AS window_end
    FROM dbo.vw_capacity_scenario_denominators
    WHERE data_mode='Estimated'
    GROUP BY capacity_id,metric_date
)
SELECT p.capacity_id,p.metric_date,p.source_status,p.metric_rows,
    p.observed_cus,p.missing_cu_values,p.processed_at,
    CASE WHEN d.scenario_count>1 THEN 'BlockedMultipleScenarios'
         ELSE COALESCE(d.availability_status,'BlockedMissingAssumptions') END AS estimate_status,
    CASE WHEN d.scenario_count=1 THEN d.scenario_available_cus END AS scenario_available_cus,
    d.assumption_note,d.source_utc_offset_minutes,d.window_start,d.window_end,
    CAST(CASE WHEN p.metric_date BETWEEN s.window_start_day AND s.window_end_day
         THEN 1 ELSE 0 END AS int) AS in_rolling_window
FROM dbo.monitoring_daily_periods p
JOIN dbo.monitoring_daily_state s ON p.capacity_id=s.capacity_id
LEFT JOIN denominators d ON p.capacity_id=d.capacity_id AND p.metric_date=d.metric_date;
