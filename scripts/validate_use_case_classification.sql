-- Read-only against the independent monitoring Lakehouse SQL endpoint.
-- Results describe tenant classification; keep them private.
SELECT use_case_id, use_case_name, tag_id, is_enabled
FROM dbo.use_cases
ORDER BY use_case_name;

SELECT [status], COUNT_BIG(*) AS RunCount, MAX(completed_at) AS LastCompletion
FROM dbo.classification_runs
GROUP BY [status];

SELECT s.classification_status, COUNT_BIG(*) AS WorkspaceCount,
    SUM(CASE WHEN s.capacity_id IS NULL THEN 1 ELSE 0 END) AS MissingCapacityCount,
    SUM(CASE WHEN s.domain_id IS NULL THEN 1 ELSE 0 END) AS MissingDomainCount
FROM dbo.workspace_use_case_snapshots s
WHERE s.run_id = (
    SELECT TOP (1) run_id FROM dbo.classification_runs
    WHERE [status] = 'Succeeded' ORDER BY started_at DESC, run_id
)
GROUP BY s.classification_status;

SELECT 'duplicate_runs' AS CheckName, COUNT_BIG(*) AS FailingGroups
FROM (
    SELECT run_id FROM dbo.classification_runs
    GROUP BY run_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_case_ids', COUNT_BIG(*)
FROM (
    SELECT use_case_id FROM dbo.use_cases
    GROUP BY use_case_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_enabled_tags', COUNT_BIG(*)
FROM (
    SELECT tag_id FROM dbo.use_cases WHERE is_enabled = 1
    GROUP BY tag_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_workspace_snapshots', COUNT_BIG(*)
FROM (
    SELECT run_id, workspace_id FROM dbo.workspace_use_case_snapshots
    GROUP BY run_id, workspace_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_catalog_snapshots', COUNT_BIG(*)
FROM (
    SELECT run_id, use_case_id FROM dbo.use_case_catalog_snapshots
    GROUP BY run_id, use_case_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'orphaned_workspace_runs', COUNT_BIG(*)
FROM dbo.workspace_use_case_snapshots s
LEFT JOIN dbo.classification_runs r ON s.run_id = r.run_id
WHERE r.run_id IS NULL
UNION ALL
SELECT 'orphaned_catalog_runs', COUNT_BIG(*)
FROM dbo.use_case_catalog_snapshots c
LEFT JOIN dbo.classification_runs r ON c.run_id = r.run_id
WHERE r.run_id IS NULL
UNION ALL
SELECT 'invalid_successful_runs', COUNT_BIG(*)
FROM dbo.classification_runs
WHERE [status] = 'Succeeded' AND (
    started_at IS NULL OR completed_at IS NULL OR completed_at < started_at
    OR error_type IS NOT NULL OR error_message IS NOT NULL
)
UNION ALL
SELECT 'invalid_classification_states', COUNT_BIG(*)
FROM dbo.workspace_use_case_snapshots
WHERE classification_status IS NULL OR matched_case_count IS NULL
    OR classification_status NOT IN ('Assigned', 'Unclassified', 'Ambiguous', 'MissingWorkspace')
    OR (classification_status = 'Assigned' AND (
        matched_case_count <> 1 OR use_case_id IS NULL OR use_case_name IS NULL
    ))
    OR (classification_status <> 'Assigned' AND (
        use_case_id IS NOT NULL OR use_case_name IS NOT NULL
    ))
    OR (classification_status = 'Ambiguous' AND matched_case_count < 2)
    OR (classification_status IN ('Unclassified', 'MissingWorkspace') AND matched_case_count <> 0)
UNION ALL
SELECT 'unresolved_workspace_metadata', COUNT_BIG(*)
FROM dbo.workspace_use_case_snapshots
WHERE classification_status = 'MissingWorkspace' AND (
    capacity_id IS NOT NULL OR domain_id IS NOT NULL
    OR workspace_deleted_flag IS NOT NULL OR source_modified_at IS NOT NULL
)
UNION ALL
SELECT 'assigned_case_snapshot_mismatch', COUNT_BIG(*)
FROM dbo.workspace_use_case_snapshots s
LEFT JOIN dbo.use_case_catalog_snapshots c
    ON s.run_id = c.run_id AND s.use_case_id = c.use_case_id
WHERE s.classification_status = 'Assigned' AND (
    c.use_case_id IS NULL OR c.is_enabled <> 1 OR s.use_case_name <> c.use_case_name
)
UNION ALL
SELECT 'invalid_observation_times', COUNT_BIG(*)
FROM dbo.workspace_use_case_snapshots s
JOIN dbo.classification_runs r ON s.run_id = r.run_id
WHERE r.[status] = 'Succeeded' AND (
    s.observed_at IS NULL OR s.observed_at < r.started_at OR s.observed_at > r.completed_at
);
