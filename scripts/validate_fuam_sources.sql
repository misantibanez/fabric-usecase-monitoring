-- Run read-only against the deployed FUAM Lakehouse SQL analytics endpoint.
-- Results may describe tenant usage; do not commit or publish them.
SELECT 'workspace_tags' AS Source, COUNT_BIG(*) AS RecordCount FROM dbo.workspace_tags
UNION ALL SELECT 'tags', COUNT_BIG(*) FROM dbo.tags
UNION ALL SELECT 'capacities', COUNT_BIG(*) FROM dbo.capacities
UNION ALL SELECT 'capacities_history', COUNT_BIG(*) FROM dbo.capacities_history
UNION ALL SELECT 'workspaces', COUNT_BIG(*) FROM dbo.workspaces
UNION ALL SELECT 'workspaces_history', COUNT_BIG(*) FROM dbo.workspaces_history
UNION ALL SELECT 'domains_flatten', COUNT_BIG(*) FROM dbo.domains_flatten
UNION ALL SELECT 'active_items', COUNT_BIG(*) FROM dbo.active_items
UNION ALL SELECT 'lakehouses', COUNT_BIG(*) FROM dbo.lakehouses
UNION ALL SELECT 'notebooks', COUNT_BIG(*) FROM dbo.notebooks
UNION ALL SELECT 'pipelines', COUNT_BIG(*) FROM dbo.pipelines
UNION ALL SELECT 'environments', COUNT_BIG(*) FROM dbo.environments;

SELECT
    'timepoint' AS Source,
    COUNT_BIG(*) AS RecordCount,
    COUNT(DISTINCT CapacityId) AS CapacityCount,
    MIN(TimePoint) AS Earliest,
    MAX(TimePoint) AS Latest,
    MIN(SKUCUByTimePoint) AS MinSKUUnits,
    MAX(SKUCUByTimePoint) AS MaxSKUUnits,
    SUM(TotalCUs) AS Consumed,
    SUM(CAST(SKUCUByTimePoint AS float)) AS Available
FROM dbo.capacity_metrics_by_timepoint;

SELECT
    'item_operation_day' AS Source,
    COUNT_BIG(*) AS RecordCount,
    COUNT(DISTINCT CapacityId) AS CapacityCount,
    COUNT(DISTINCT WorkspaceId) AS WorkspaceCount,
    MIN([Date]) AS Earliest,
    MAX([Date]) AS Latest,
    SUM(TotalCUs) AS Consumed
FROM dbo.capacity_metrics_by_item_by_operation_by_day;

SELECT
    'capacities' AS Source,
    MIN(fuam_modified_at) AS EarliestExtraction,
    MAX(fuam_modified_at) AS LatestExtraction
FROM dbo.capacities
UNION ALL
SELECT 'workspaces', MIN(fuam_modified_at), MAX(fuam_modified_at)
FROM dbo.workspaces;

SELECT 'duplicate_timepoint_keys' AS CheckName, COUNT_BIG(*) AS FailingGroups
FROM (
    SELECT CapacityId, TimePoint
    FROM dbo.capacity_metrics_by_timepoint
    GROUP BY CapacityId, TimePoint
    HAVING COUNT_BIG(*) > 1
) AS duplicates
UNION ALL
SELECT 'duplicate_item_operation_day_keys', COUNT_BIG(*)
FROM (
    SELECT CapacityId, WorkspaceId, ItemId, ItemKind, OperationName, [Date]
    FROM dbo.capacity_metrics_by_item_by_operation_by_day
    GROUP BY CapacityId, WorkspaceId, ItemId, ItemKind, OperationName, [Date]
    HAVING COUNT_BIG(*) > 1
) AS duplicates;

SELECT TOP (10)
    CAST(TimePoint AS date) AS MetricDate,
    COUNT_BIG(*) AS TimepointRecords,
    COUNT(DISTINCT CapacityId) AS CapacityCount,
    MIN(SKUCUByTimePoint) AS MinSKUUnits,
    MAX(SKUCUByTimePoint) AS MaxSKUUnits
FROM dbo.capacity_metrics_by_timepoint
GROUP BY CAST(TimePoint AS date)
ORDER BY MetricDate DESC;
