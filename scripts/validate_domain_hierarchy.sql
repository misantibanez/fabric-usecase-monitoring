-- Read-only; keep domain names, identities and aggregate results private.
DECLARE @RunId varchar(36) = (
    SELECT TOP (1) run_id FROM dbo.classification_runs
    WHERE [status] = 'Succeeded' AND domain_snapshot_count IS NOT NULL
    ORDER BY started_at DESC, run_id
);
SELECT domain_resolution_status, hierarchy_depth, COUNT_BIG(*) AS DomainCount
FROM dbo.domain_hierarchy_snapshots
WHERE run_id = @RunId
GROUP BY domain_resolution_status, hierarchy_depth;

SELECT classification_status, domain_resolution_status, COUNT_BIG(*) AS ItemCount
FROM dbo.item_use_case_snapshots
WHERE run_id = @RunId
GROUP BY classification_status, domain_resolution_status;

SELECT 'duplicate_domain_observations' AS CheckName, COUNT_BIG(*) AS FailingGroups
FROM (
    SELECT run_id, domain_id FROM dbo.domain_hierarchy_snapshots
    GROUP BY run_id, domain_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'successful_domain_count_mismatch', COUNT_BIG(*)
FROM dbo.classification_runs r
WHERE r.[status] = 'Succeeded' AND r.domain_snapshot_count IS NOT NULL
    AND r.domain_snapshot_count <> (
        SELECT COUNT_BIG(*) FROM dbo.domain_hierarchy_snapshots d WHERE d.run_id = r.run_id
    )
UNION ALL
SELECT 'invalid_resolved_domains', COUNT_BIG(*)
FROM dbo.domain_hierarchy_snapshots d
JOIN dbo.classification_runs r ON d.run_id = r.run_id
LEFT JOIN dbo.domain_hierarchy_snapshots root
    ON d.run_id = root.run_id AND d.root_domain_id = root.domain_id
WHERE r.[status] = 'Succeeded' AND d.domain_resolution_status = 'Resolved' AND (
    root.domain_id IS NULL OR root.parent_domain_id IS NOT NULL
    OR d.root_domain_name <> root.domain_name OR d.root_domain_name IS NULL
    OR d.hierarchy_depth IS NULL OR d.hierarchy_depth < 0
    OR ISJSON(d.domain_path_ids) <> 1 OR d.domain_path_ids IS NULL
    OR (d.hierarchy_depth = 0 AND (
        d.domain_id <> d.root_domain_id OR d.subdomain_id IS NOT NULL
        OR d.subdomain_name IS NOT NULL OR d.parent_domain_id IS NOT NULL
    ))
    OR (d.hierarchy_depth > 0 AND (
        d.subdomain_id IS NULL OR d.subdomain_id <> d.domain_id
        OR d.subdomain_name IS NULL OR d.subdomain_name <> d.domain_name
        OR d.parent_domain_id IS NULL
    ))
    OR (d.hierarchy_depth = 1 AND d.parent_domain_id <> d.root_domain_id)
)
UNION ALL
SELECT 'invalid_unresolved_domains', COUNT_BIG(*)
FROM dbo.domain_hierarchy_snapshots
WHERE domain_resolution_status IS NULL OR domain_resolution_status NOT IN (
    'Resolved', 'DomainNotFound', 'ParentDomainNotFound', 'HierarchyCycle'
)
    OR (domain_resolution_status <> 'Resolved' AND (
        root_domain_id IS NOT NULL OR root_domain_name IS NOT NULL
        OR subdomain_id IS NOT NULL OR subdomain_name IS NOT NULL
        OR hierarchy_depth IS NOT NULL OR domain_path_ids IS NOT NULL
    ))
UNION ALL
SELECT 'item_workspace_hierarchy_mismatch', COUNT_BIG(*)
FROM dbo.item_use_case_snapshots i
JOIN dbo.workspace_use_case_snapshots w
    ON i.run_id = w.run_id AND i.workspace_id = w.workspace_id
JOIN dbo.classification_runs r ON i.run_id = r.run_id
WHERE r.[status] = 'Succeeded' AND r.domain_snapshot_count IS NOT NULL AND (
    COALESCE(i.root_domain_id, '') <> COALESCE(w.root_domain_id, '')
    OR COALESCE(i.root_domain_name, '') <> COALESCE(w.root_domain_name, '')
    OR COALESCE(i.subdomain_id, '') <> COALESCE(w.subdomain_id, '')
    OR COALESCE(i.subdomain_name, '') <> COALESCE(w.subdomain_name, '')
    OR COALESCE(i.domain_path_ids, '') <> COALESCE(w.domain_path_ids, '')
    OR COALESCE(i.hierarchy_depth, -1) <> COALESCE(w.hierarchy_depth, -1)
    OR COALESCE(i.domain_resolution_status, '') <> COALESCE(w.domain_resolution_status, '')
);
