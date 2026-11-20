# FUAM source contract

## Evidence status

Initial local review has been followed by read-only live validation of Lakehouse
discovery, table discovery, selected schemas, aggregate counts, freshness and
candidate metric-key uniqueness. Billing eligibility, historical attribution and
complete denominator coverage have NOT been validated.
All live findings must stay outside this public repository; publish only
sanitized summaries and synthetic examples.

The separate Fabric Monitoring MCP connection confirmed workspace/Lakehouse
discovery and table metadata through stable IDs under namespace `dbo`.
Friendly-name namespace discovery failed; ID-based discovery succeeded.
The independent SQL endpoint MCP tool returned a resource-not-found error for
both Lakehouse and SQL endpoint identifiers. An encrypted SQL connection using
the isolated CLI profile successfully executed read-only schema and aggregate
queries. No tokens were printed or persisted in repository files.

The upstream links below identify the corresponding source files. Upstream main
can change; capture the deployed FUAM version when performing live validation.

## Candidate sources

The per-source `Pending` entries below refer to full acceptance of that source,
not initial discovery. The live findings section records completed partial checks
and blocking gaps; presence alone does not pass source validation.

| Source | Required fields or role | Local evidence | Live validation |
| --- | --- | --- | --- |
| `capacities` | `CapacityId`, `displayName`, `sku`, `state`, `fuam_modified_at`, `fuam_deleted` | Core model table exposes these fields. Current state is not a historical state ledger. | Pending |
| `workspaces` | `WorkspaceId`, `CapacityId`, `DomainId`, name, deletion state | Core model exposes workspace/capacity/domain identifiers. Transfer notebook also handles workspace tags. | Pending |
| `workspace_tags` | `WorkspaceId`, `tagId`, `displayName` | Workspace transfer explodes tags and overwrites this association table. | Pending |
| `tags` | `tagId`, `scope`, `displayName` | Tags notebook uppercases IDs, flattens `scope.type`, and overwrites the catalog. | Pending |
| `domains_flatten` | `DomainId`, `OriginalParentDomainId`, `MainDomainName`, `SubDomainName` | Domains notebook resolves the domain hierarchy. | Pending |
| `capacity_metrics_by_item_by_operation_by_day` | `CapacityId`, `WorkspaceId`, `ItemId`, `Date`, `ItemKind`, `OperationName`, `TotalCUs`, operation counts | Core model exposes item/operation/day consumption; extraction reads CU seconds from Capacity Metrics. | Pending |
| `capacity_metrics_by_timepoint` | `CapacityId`, `TimePoint`, `TotalCUs`, `SKUCUByTimePoint`, utilization and carry-over fields | Extraction reads Capacity Metrics measures; Core utilization divides summed consumption by summed SKU capacity. | Pending |
| `active_items` | Item/workspace/capacity identity and lifecycle state | Active-items notebook performs an ID-based merge and excludes the all-zero ID. The deployed payload schema must be inspected. | Pending |
| Scanner inventory tables | `WorkspaceId`, type-specific item ID, name, type/lifecycle metadata | Incremental inventory handles Lakehouse, Notebook, DataPipeline and Environment, among other types. | Pending |
| `activities` | Observed event time, workspace/item identity where present, operation | Core model contains audit activities. These are supplementary evidence, not a substitute for measured CU consumption. | Pending |

## Source locations

- [Core model tables](https://github.com/microsoft/fabric-toolbox/tree/main/monitoring/fabric-unified-admin-monitoring/src/FUAM_Core_SM.SemanticModel/definition/tables)
- [Workspace transfer](https://github.com/microsoft/fabric-toolbox/blob/main/monitoring/fabric-unified-admin-monitoring/src/02_Transfer_Workspaces_Unit.Notebook/notebook-content.ipynb)
- [Tags transfer](https://github.com/microsoft/fabric-toolbox/blob/main/monitoring/fabric-unified-admin-monitoring/src/01_Tags_Unit.Notebook/notebook-content.ipynb)
- [Domains transfer](https://github.com/microsoft/fabric-toolbox/blob/main/monitoring/fabric-unified-admin-monitoring/src/01_Transfer_Domains_Unit.Notebook/notebook-content.ipynb)
- [Active items transfer](https://github.com/microsoft/fabric-toolbox/blob/main/monitoring/fabric-unified-admin-monitoring/src/01_Transfer_Active_Items_Unit.Notebook/notebook-content.ipynb)
- [Incremental inventory](https://github.com/microsoft/fabric-toolbox/blob/main/monitoring/fabric-unified-admin-monitoring/src/01_Transfer_Incremental_Inventory_Unit.Notebook/notebook-content.ipynb)
- [Item-operation metrics transfer](https://github.com/microsoft/fabric-toolbox/blob/main/monitoring/fabric-unified-admin-monitoring/src/03_Transfer_CapacityMetricData_ItemOperation_Unit.Notebook/notebook-content.ipynb)
- [Timepoint metrics transfer](https://github.com/microsoft/fabric-toolbox/blob/main/monitoring/fabric-unified-admin-monitoring/src/01_Transfer_CapacityMetricData_Timepoints_Unit.Notebook/notebook-content.ipynb)

## Sanitized live findings

- Required classification, metric and inventory table names exist.
- Workspace tag associations and the tag catalog are empty in the queried
  deployment. Current workspace metadata exposes tags, so the empty tables
  cannot be treated as proof that no Fabric tags are configured.
- Capacity and workspace history tables exist but are empty.
- The general active-item inventory is populated. The queried Lakehouse,
  Notebook, DataPipeline and Environment scanner tables are empty; this is an
  extraction/coverage gap to investigate, not proof that those items do not
  exist.
- Workspace/capacity extraction timestamps and metric dates are stale.
- Timepoint data covers only scattered dates/intervals. It cannot establish
  complete active capacity availability for a billing period.
- No duplicate groups were found for `(CapacityId, TimePoint)` or the candidate
  `(CapacityId, WorkspaceId, ItemId, ItemKind, OperationName, Date)` key in the
  queried metrics. This does not establish completeness.
- Summed item-operation CU consumption differs from summed timepoint
  consumption. Smoothing, date boundaries and missing intervals must be
  reconciled; no billing percentage is approved from this comparison.

Detailed tenant counts, dates and usage totals are not published here.
Source validation remains open. Next: inspect deployed orchestration parameters,
recent run history and refresh configuration before proposing targeted refreshes.
The local scanner supports `extract_powerbi_artifacts_only` and
`has_tenant_domains`; their deployed values and actual run behavior are unverified.

### Reusable read-only validation

Run [validate_fuam_sources.sql](../scripts/validate_fuam_sources.sql) against the
FUAM Lakehouse SQL analytics endpoint. It returns aggregate table counts,
freshness, candidate-key duplicates and timepoint distribution without exposing
item names, workspace IDs or users. Its results still describe tenant usage and
must stay private.

The script executed successfully and returned all six result sets. It is a
diagnostic, not a passing acceptance test: empty and stale sources remain blockers.

## Open correctness questions

1. Confirm the actual item-operation grain and deduplication key.
2. Verify that `TotalCUs` and `SKUCUByTimePoint` have compatible CU-second units,
   including whether the timepoint duration is already included.
3. Check which usage is billable/non-billable and choose the numerator explicitly.
4. Reconcile operation-date consumption against smoothed timepoint consumption
   over identical windows. Do not claim equivalence across period boundaries
   without supporting evidence.
5. Establish denominator coverage for zero-usage periods. Missing timepoint rows
   cannot be assumed to represent paused capacity or omitted from the denominator
   without qualification.
6. Verify what historical SKU and capacity-state information Fabric exposes.
   Current `capacities.state` alone cannot reconstruct active intervals.
7. Check whether scanner extraction is configured to include Fabric artifacts,
   rather than Power BI artifacts only.
8. Confirm Variable Library coverage separately. Environment is not equivalent
   to Variable Library or notebook/pipeline parameters. Do not extract secret
   values or item definitions containing credentials.
9. Verify that deleted and never-used items remain discoverable in the chosen
   inventory; a consumption table is not a complete inventory.
10. Define use-case tags by stable IDs, not all workspace tags or tag names alone.
    Existing tag associations are overwritten, so historical attribution needs
    its own effective-dated records.

## Live validation checklist

- Identify the deployed FUAM workspace, Lakehouse, version and pilot capacity.
- Confirm read access to required tables and metadata.
- Inspect schemas and uniqueness using read-only queries.
- Measure freshness, earliest/latest coverage and missing intervals.
- Validate domain/tag joins and orphaned identifiers without publishing names.
- Select a tagged workspace, an untagged workspace and a workspace with no
  observed usage when available.
- Reconcile capacity and workspace/item consumption on the same covered period.
- Record unresolved gaps explicitly; source validation remains open until these
  checks pass or an approved scope limitation is documented.

There are no automated project tests or report validations yet. Live schema and
aggregate diagnostics have run; the report and its percentages are not deployed.
