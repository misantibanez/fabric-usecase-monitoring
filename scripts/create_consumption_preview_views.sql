-- Execute each GO-delimited batch against the monitoring SQL analytics endpoint.
-- FUAM_Lakehouse is the source database; replace this identifier for other deployments.
CREATE OR ALTER VIEW dbo.vw_latest_item_use_case_inventory AS
WITH latest AS (
    SELECT TOP (1) run_id FROM dbo.classification_runs
    WHERE [status] = 'Succeeded' AND inventory_snapshot_count IS NOT NULL
    ORDER BY started_at DESC, run_id
)
SELECT i.*
FROM dbo.item_use_case_snapshots i JOIN latest r ON i.run_id = r.run_id;
GO

CREATE OR ALTER VIEW dbo.vw_item_consumption_preview AS
SELECT
    m.[Date] AS metric_date,
    UPPER(TRIM(m.CapacityId)) AS metric_capacity_id,
    UPPER(TRIM(m.WorkspaceId)) AS workspace_id,
    UPPER(TRIM(m.ItemId)) AS item_id,
    m.OperationName AS operation_name,
    m.ItemKind AS metric_item_kind,
    m.TotalCUs AS source_total_cus,
    m.OperationCount AS operation_count,
    i.item_type AS current_inventory_type,
    i.run_id AS classification_run_id,
    i.observed_at AS classification_observed_at,
    CASE WHEN i.workspace_id = UPPER(TRIM(m.WorkspaceId)) THEN i.use_case_id END AS use_case_id,
    CASE WHEN i.workspace_id = UPPER(TRIM(m.WorkspaceId)) THEN i.use_case_name END AS use_case_name,
    CASE WHEN i.workspace_id = UPPER(TRIM(m.WorkspaceId)) THEN i.domain_id END AS domain_id,
    CASE WHEN i.item_id IS NULL THEN 'MissingItem'
         WHEN NULLIF(TRIM(m.WorkspaceId), '') IS NULL THEN 'MetricWorkspaceMissing'
         WHEN i.workspace_id <> UPPER(TRIM(m.WorkspaceId)) THEN 'CurrentItemWorkspaceMismatch'
         ELSE 'ItemWorkspaceMatched' END AS inventory_join_status,
    CASE WHEN i.item_id IS NULL THEN 'MissingItem'
         WHEN NULLIF(TRIM(m.WorkspaceId), '') IS NULL THEN 'MetricWorkspaceMissing'
         WHEN i.workspace_id <> UPPER(TRIM(m.WorkspaceId)) THEN 'CurrentItemWorkspaceMismatch'
         ELSE i.classification_status END AS classification_status,
    CASE WHEN i.item_id IS NULL THEN 'MissingItem'
         WHEN NULLIF(TRIM(m.WorkspaceId), '') IS NULL THEN 'MetricWorkspaceMissing'
         WHEN i.workspace_id <> UPPER(TRIM(m.WorkspaceId)) THEN 'CurrentItemWorkspaceMismatch'
         WHEN i.capacity_id IS NULL THEN 'CurrentWorkspaceCapacityUnknown'
         WHEN NULLIF(TRIM(m.CapacityId), '') IS NULL THEN 'MetricCapacityUnknown'
         WHEN i.capacity_id <> UPPER(TRIM(m.CapacityId)) THEN 'MetricCurrentCapacityMismatch'
         ELSE 'MetricCurrentCapacityMatched' END AS capacity_comparison_status,
    CAST('CurrentClassificationPreview' AS varchar(40)) AS attribution_basis,
    CAST('Unvalidated' AS varchar(20)) AS historical_attribution_status
FROM FUAM_Lakehouse.dbo.capacity_metrics_by_item_by_operation_by_day m
LEFT JOIN dbo.vw_latest_item_use_case_inventory i ON UPPER(TRIM(m.ItemId)) = i.item_id;
GO

CREATE OR ALTER VIEW dbo.vw_use_case_consumption_preview AS
SELECT
    metric_date, metric_capacity_id, use_case_id, use_case_name, domain_id,
    inventory_join_status, classification_status, capacity_comparison_status,
    attribution_basis, historical_attribution_status,
    COUNT_BIG(*) AS metric_row_count,
    COUNT(DISTINCT item_id) AS observed_item_count,
    SUM(source_total_cus) AS observed_total_cus,
    SUM(CASE WHEN source_total_cus IS NULL THEN 1 ELSE 0 END) AS missing_cu_value_count
FROM dbo.vw_item_consumption_preview
GROUP BY metric_date, metric_capacity_id, use_case_id, use_case_name, domain_id,
    inventory_join_status, classification_status, capacity_comparison_status,
    attribution_basis, historical_attribution_status;
GO
