-- Read-only against the FUAM Lakehouse SQL analytics endpoint.
-- Aggregate results still describe tenant inventory/usage; keep them private.
-- Defaults cover 14 calendar days ending on the latest stored metric date.
-- This is NOT a claim of freshness or complete coverage.
DECLARE @WindowEnd datetime2 = (
    SELECT DATEADD(day, 1, CAST(MAX([Date]) AS date))
    FROM dbo.capacity_metrics_by_item_by_operation_by_day
);
DECLARE @WindowStart datetime2 = DATEADD(day, -14, @WindowEnd);

SELECT
    @WindowStart AS WindowStartInclusive,
    @WindowEnd AS WindowEndExclusive,
    SYSUTCDATETIME() AS CheckedAtUtc,
    (SELECT MAX(fuam_modified_at) FROM dbo.active_items) AS LatestItemExtraction,
    (SELECT MAX(fuam_modified_at) FROM dbo.workspaces) AS LatestWorkspaceExtraction,
    (SELECT MAX([Date]) FROM dbo.capacity_metrics_by_item_by_operation_by_day)
        AS LatestStoredMetricDate;

SELECT 'duplicate_item_ids' AS CheckName, COUNT_BIG(*) AS FailingGroupsOrRows
FROM (
    SELECT UPPER(TRIM(id)) AS ItemKey FROM dbo.active_items
    GROUP BY UPPER(TRIM(id)) HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_workspace_ids', COUNT_BIG(*)
FROM (
    SELECT UPPER(TRIM(WorkspaceId)) AS WorkspaceKey FROM dbo.workspaces
    GROUP BY UPPER(TRIM(WorkspaceId)) HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_domain_ids', COUNT_BIG(*)
FROM (
    SELECT UPPER(TRIM(DomainId)) AS DomainKey FROM dbo.domains_flatten
    GROUP BY UPPER(TRIM(DomainId)) HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_workspace_tag_pairs', COUNT_BIG(*)
FROM (
    SELECT UPPER(TRIM(WorkspaceId)) AS WorkspaceKey, UPPER(TRIM(tagId)) AS TagKey
    FROM dbo.workspace_tags
    GROUP BY UPPER(TRIM(WorkspaceId)), UPPER(TRIM(tagId))
    HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'invalid_item_ids', COUNT_BIG(*) FROM dbo.active_items
WHERE TRY_CONVERT(uniqueidentifier, id) IS NULL
    OR LEN(TRIM(id)) <> 36 OR TRIM(id) = '00000000-0000-0000-0000-000000000000'
UNION ALL
SELECT 'invalid_item_workspace_ids', COUNT_BIG(*) FROM dbo.active_items
WHERE TRY_CONVERT(uniqueidentifier, workspaceId) IS NULL
    OR LEN(TRIM(workspaceId)) <> 36
    OR TRIM(workspaceId) = '00000000-0000-0000-0000-000000000000';

WITH WorkspaceKeys AS (
    SELECT UPPER(TRIM(WorkspaceId)) AS WorkspaceKey, COUNT_BIG(*) AS KeyRows,
        MAX(CAST(fuam_deleted AS int)) AS DeletedFlag,
        MAX(UPPER(NULLIF(TRIM(CapacityId), ''))) AS CapacityKey
    FROM dbo.workspaces GROUP BY UPPER(TRIM(WorkspaceId))
), Inventory AS (
    SELECT i.*,
        CASE WHEN EXISTS (
            SELECT 1 FROM dbo.capacities c
            WHERE UPPER(TRIM(c.CapacityId)) = UPPER(TRIM(i.capacityId))
        ) THEN 0 ELSE 1 END AS MissingCapacityCatalog,
        CASE WHEN w.WorkspaceKey IS NULL THEN 'MissingWorkspace'
             WHEN w.KeyRows > 1 THEN 'AmbiguousWorkspaceKey'
             WHEN w.DeletedFlag = 1 THEN 'WorkspaceMarkedDeleted'
             WHEN w.DeletedFlag = 0 THEN 'WorkspaceNotMarkedDeleted'
             ELSE 'WorkspaceLifecycleUnknown' END AS WorkspaceJoinStatus,
        CASE WHEN w.WorkspaceKey IS NULL THEN 'MissingWorkspace'
             WHEN w.KeyRows > 1 THEN 'AmbiguousWorkspaceKey'
             WHEN NULLIF(TRIM(i.capacityId), '') IS NULL THEN 'ItemCapacityMissing'
             WHEN w.CapacityKey IS NULL THEN 'WorkspaceCapacityMissing'
             WHEN UPPER(TRIM(i.capacityId)) <> w.CapacityKey
                THEN 'CurrentCapacityMismatch'
             ELSE 'CurrentCapacityMatched' END AS CapacityJoinStatus
    FROM dbo.active_items i
    LEFT JOIN WorkspaceKeys w ON UPPER(TRIM(i.workspaceId)) = w.WorkspaceKey
)
SELECT WorkspaceJoinStatus, CapacityJoinStatus, fuam_deleted AS ItemDeletedFlag,
    COUNT_BIG(*) AS InventoryRows,
    SUM(CAST(MissingCapacityCatalog AS bigint)) AS MissingCapacityCatalogRows
FROM Inventory
GROUP BY WorkspaceJoinStatus, CapacityJoinStatus, fuam_deleted;

WITH Inventory AS (
    SELECT i.*,
        CASE WHEN EXISTS (
            SELECT 1 FROM dbo.capacity_metrics_by_item_by_operation_by_day m
            WHERE UPPER(TRIM(m.ItemId)) = UPPER(TRIM(i.id))
                AND UPPER(TRIM(m.WorkspaceId)) = UPPER(TRIM(i.workspaceId))
                AND m.[Date] >= @WindowStart AND m.[Date] < @WindowEnd
        ) THEN 1 ELSE 0 END AS HasWindowMetrics
    FROM dbo.active_items i
)
SELECT [type] AS InventoryType, fuam_deleted AS ItemDeletedFlag,
    COUNT_BIG(*) AS InventoryRows,
    SUM(CAST(HasWindowMetrics AS bigint)) AS ItemsWithWindowMetrics,
    SUM(CAST(1 - HasWindowMetrics AS bigint)) AS ItemsWithoutWindowMetrics
FROM Inventory GROUP BY [type], fuam_deleted;

WITH MetricScope AS (
    SELECT 'AllStoredMetrics' AS Scope, m.*
    FROM dbo.capacity_metrics_by_item_by_operation_by_day m
    UNION ALL
    SELECT 'SelectedWindow', m.*
    FROM dbo.capacity_metrics_by_item_by_operation_by_day m
    WHERE m.[Date] >= @WindowStart AND m.[Date] < @WindowEnd
), Matches AS (
    SELECT m.Scope, m.TotalCUs,
        CASE WHEN NOT EXISTS (
            SELECT 1 FROM dbo.active_items i
            WHERE UPPER(TRIM(i.id)) = UPPER(TRIM(m.ItemId))
        ) THEN 'MissingItem'
        WHEN NOT EXISTS (
            SELECT 1 FROM dbo.active_items i
            WHERE UPPER(TRIM(i.id)) = UPPER(TRIM(m.ItemId))
                AND UPPER(TRIM(i.workspaceId)) = UPPER(TRIM(m.WorkspaceId))
        ) THEN 'CurrentItemWorkspaceMismatch'
        ELSE 'ItemWorkspaceMatched' END AS ItemJoinStatus,
        CASE WHEN NOT EXISTS (
            SELECT 1 FROM dbo.workspaces w
            WHERE UPPER(TRIM(w.WorkspaceId)) = UPPER(TRIM(m.WorkspaceId))
        ) THEN 'MissingWorkspace'
        WHEN EXISTS (
            SELECT 1 FROM dbo.workspaces w
            WHERE UPPER(TRIM(w.WorkspaceId)) = UPPER(TRIM(m.WorkspaceId))
                AND w.fuam_deleted = 1
        ) THEN 'WorkspaceMarkedDeleted'
        ELSE 'WorkspaceFound' END AS WorkspaceJoinStatus
    FROM MetricScope m
)
SELECT Scope, ItemJoinStatus, WorkspaceJoinStatus,
    COUNT_BIG(*) AS MetricRows, SUM(TotalCUs) AS ConsumedCUs
FROM Matches GROUP BY Scope, ItemJoinStatus, WorkspaceJoinStatus;

-- Type pairs are observations, not a universal alias mapping.
WITH ItemKeys AS (
    SELECT UPPER(TRIM(id)) AS ItemKey,
        UPPER(TRIM(workspaceId)) AS WorkspaceKey,
        CASE WHEN COUNT_BIG(*) = 1 THEN MAX([type]) END AS InventoryType,
        COUNT_BIG(*) AS KeyRows
    FROM dbo.active_items
    GROUP BY UPPER(TRIM(id)), UPPER(TRIM(workspaceId))
)
SELECT m.ItemKind AS MetricItemKind, i.InventoryType,
    CASE WHEN i.ItemKey IS NULL THEN 'MissingItemWorkspacePair'
         WHEN i.KeyRows > 1 THEN 'AmbiguousInventoryPair'
         ELSE 'PairMatched' END AS PairJoinStatus,
    COUNT_BIG(*) AS MetricRows
FROM dbo.capacity_metrics_by_item_by_operation_by_day m
LEFT JOIN ItemKeys i ON UPPER(TRIM(m.ItemId)) = i.ItemKey
    AND UPPER(TRIM(m.WorkspaceId)) = i.WorkspaceKey
GROUP BY m.ItemKind, i.InventoryType,
    CASE WHEN i.ItemKey IS NULL THEN 'MissingItemWorkspacePair'
         WHEN i.KeyRows > 1 THEN 'AmbiguousInventoryPair'
         ELSE 'PairMatched' END;

WITH WorkspaceKeys AS (
    SELECT UPPER(TRIM(WorkspaceId)) AS WorkspaceKey, COUNT_BIG(*) AS KeyRows,
        MAX(UPPER(NULLIF(TRIM(DomainId), ''))) AS DomainKey
    FROM dbo.workspaces GROUP BY UPPER(TRIM(WorkspaceId))
), Tags AS (
    SELECT UPPER(TRIM(WorkspaceId)) AS WorkspaceKey,
        COUNT(DISTINCT UPPER(NULLIF(TRIM(tagId), ''))) AS TagCount
    FROM dbo.workspace_tags GROUP BY UPPER(TRIM(WorkspaceId))
), Inventory AS (
    SELECT
        CASE WHEN w.WorkspaceKey IS NULL THEN 'MissingWorkspace'
             WHEN w.KeyRows > 1 THEN 'AmbiguousWorkspaceKey'
             WHEN w.DomainKey IS NULL THEN 'NoDomain'
             WHEN EXISTS (
                 SELECT 1 FROM dbo.domains_flatten d
                 WHERE UPPER(TRIM(d.DomainId)) = w.DomainKey
             ) THEN 'DomainMatched' ELSE 'DomainUnresolved' END AS DomainStatus,
        CASE WHEN w.WorkspaceKey IS NULL THEN 'MissingWorkspace'
             WHEN w.KeyRows > 1 THEN 'AmbiguousWorkspaceKey'
             WHEN COALESCE(t.TagCount, 0) = 0 THEN 'NoFabricTags'
             WHEN t.TagCount = 1 THEN 'OneFabricTag'
             ELSE 'MultipleFabricTags' END AS TagStatus
    FROM dbo.active_items i
    LEFT JOIN WorkspaceKeys w ON UPPER(TRIM(i.workspaceId)) = w.WorkspaceKey
    LEFT JOIN Tags t ON w.WorkspaceKey = t.WorkspaceKey
)
SELECT DomainStatus, TagStatus, COUNT_BIG(*) AS InventoryRows
FROM Inventory GROUP BY DomainStatus, TagStatus;
