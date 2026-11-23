-- Read-only; tenant inventory/usage results must remain private.
DECLARE @WindowEnd datetime2 = (
    SELECT DATEADD(day, 1, CAST(MAX([Date]) AS date))
    FROM FUAM_Lakehouse.dbo.capacity_metrics_by_item_by_operation_by_day
);
DECLARE @WindowStart datetime2 = DATEADD(day, -14, @WindowEnd);

SELECT @WindowStart AS WindowStartInclusive, @WindowEnd AS WindowEndExclusive,
    SYSUTCDATETIME() AS CheckedAtUtc,
    (SELECT MAX(item_source_modified_at) FROM dbo.vw_latest_item_use_case_inventory)
        AS LatestItemExtraction,
    (SELECT MAX(observed_at) FROM dbo.vw_latest_item_use_case_inventory)
        AS ClassificationObservation;

WITH inventory AS (
    SELECT i.*, CASE WHEN EXISTS (
        SELECT 1 FROM dbo.vw_item_consumption_preview m
        WHERE m.item_id = i.item_id AND m.workspace_id = i.workspace_id
            AND m.metric_date >= @WindowStart AND m.metric_date < @WindowEnd
    ) THEN 1 ELSE 0 END AS HasWindowMetrics
    FROM dbo.vw_latest_item_use_case_inventory i
)
SELECT i.item_type, i.classification_status, i.capacity_join_status,
    i.item_deleted_flag, COUNT_BIG(*) AS InventoryCount,
    SUM(i.HasWindowMetrics) AS ItemsWithWindowMetrics
FROM inventory i
GROUP BY i.item_type, i.classification_status, i.capacity_join_status, i.item_deleted_flag;

SELECT metric_capacity_id, use_case_id, use_case_name, classification_status,
    capacity_comparison_status, attribution_basis, historical_attribution_status,
    SUM(metric_row_count) AS MetricRows, SUM(observed_total_cus) AS ObservedTotalCUs,
    SUM(missing_cu_value_count) AS MissingCUValues
FROM dbo.vw_use_case_consumption_preview
WHERE metric_date >= @WindowStart AND metric_date < @WindowEnd
GROUP BY metric_capacity_id, use_case_id, use_case_name, classification_status,
    capacity_comparison_status, attribution_basis, historical_attribution_status;

SELECT 'duplicate_item_snapshots' AS CheckName, COUNT_BIG(*) AS FailingGroups
FROM (
    SELECT run_id, item_id FROM dbo.item_use_case_snapshots
    GROUP BY run_id, item_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'orphaned_item_runs', COUNT_BIG(*)
FROM dbo.item_use_case_snapshots i
LEFT JOIN dbo.classification_runs r ON i.run_id = r.run_id
WHERE r.run_id IS NULL
UNION ALL
SELECT 'item_workspace_inheritance_mismatch', COUNT_BIG(*)
FROM dbo.item_use_case_snapshots i
LEFT JOIN dbo.workspace_use_case_snapshots w
    ON i.run_id = w.run_id AND i.workspace_id = w.workspace_id
JOIN dbo.classification_runs r ON i.run_id = r.run_id
WHERE r.[status] = 'Succeeded' AND (
    w.workspace_id IS NULL OR i.classification_status <> w.classification_status
    OR i.matched_case_count <> w.matched_case_count
    OR COALESCE(i.use_case_id, '') <> COALESCE(w.use_case_id, '')
    OR COALESCE(i.use_case_name, '') <> COALESCE(w.use_case_name, '')
    OR COALESCE(i.domain_id, '') <> COALESCE(w.domain_id, '')
    OR COALESCE(i.capacity_id, '') <> COALESCE(w.capacity_id, '')
)
UNION ALL
SELECT 'successful_inventory_count_mismatch', COUNT_BIG(*)
FROM dbo.classification_runs r
WHERE r.[status] = 'Succeeded' AND r.inventory_snapshot_count IS NOT NULL
    AND r.inventory_snapshot_count <> (
        SELECT COUNT_BIG(*) FROM dbo.item_use_case_snapshots i WHERE i.run_id = r.run_id
    )
UNION ALL
SELECT 'invalid_inventory_capacity_states', COUNT_BIG(*)
FROM dbo.item_use_case_snapshots
WHERE capacity_join_status IS NULL OR capacity_join_status NOT IN (
    'MissingWorkspace', 'ItemCapacityMissing', 'WorkspaceCapacityMissing',
    'CurrentCapacityMatched', 'CurrentCapacityMismatch'
)
    OR (capacity_join_status = 'CurrentCapacityMatched' AND (
        capacity_id IS NULL OR item_capacity_id IS NULL OR capacity_id <> item_capacity_id
    ))
    OR (capacity_join_status = 'CurrentCapacityMismatch' AND (
        capacity_id IS NULL OR item_capacity_id IS NULL OR capacity_id = item_capacity_id
    ))
UNION ALL
SELECT 'invalid_preview_attribution', COUNT_BIG(*)
FROM dbo.vw_item_consumption_preview
WHERE attribution_basis <> 'CurrentClassificationPreview'
    OR historical_attribution_status <> 'Unvalidated'
    OR (inventory_join_status <> 'ItemWorkspaceMatched' AND (
        use_case_id IS NOT NULL OR use_case_name IS NOT NULL OR domain_id IS NOT NULL
    ))
    OR (classification_status = 'Assigned' AND use_case_id IS NULL);

WITH scopes AS (
    SELECT 'AllStoredMetrics' AS Scope
    UNION ALL SELECT 'SelectedWindow'
)
SELECT Scope,
    (SELECT COUNT_BIG(*) FROM FUAM_Lakehouse.dbo.capacity_metrics_by_item_by_operation_by_day
     WHERE Scope = 'AllStoredMetrics' OR ([Date] >= @WindowStart AND [Date] < @WindowEnd))
        AS SourceRows,
    (SELECT COUNT_BIG(*) FROM dbo.vw_item_consumption_preview
     WHERE Scope = 'AllStoredMetrics' OR (metric_date >= @WindowStart AND metric_date < @WindowEnd))
        AS JoinedRows,
    (SELECT COALESCE(SUM(metric_row_count), 0) FROM dbo.vw_use_case_consumption_preview
     WHERE Scope = 'AllStoredMetrics' OR (metric_date >= @WindowStart AND metric_date < @WindowEnd))
        AS GroupedMetricRows,
    (SELECT SUM(TotalCUs) FROM FUAM_Lakehouse.dbo.capacity_metrics_by_item_by_operation_by_day
     WHERE Scope = 'AllStoredMetrics' OR ([Date] >= @WindowStart AND [Date] < @WindowEnd))
        AS SourceCUs,
    (SELECT SUM(source_total_cus) FROM dbo.vw_item_consumption_preview
     WHERE Scope = 'AllStoredMetrics' OR (metric_date >= @WindowStart AND metric_date < @WindowEnd))
        AS JoinedCUs,
    (SELECT SUM(observed_total_cus) FROM dbo.vw_use_case_consumption_preview
     WHERE Scope = 'AllStoredMetrics' OR (metric_date >= @WindowStart AND metric_date < @WindowEnd))
        AS GroupedCUs
FROM scopes;
