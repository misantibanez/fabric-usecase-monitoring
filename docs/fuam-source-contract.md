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
- After the user reran FUAM, workspace tag associations and the tag catalog are
  populated. Read-only checks found no orphaned workspace/tag associations,
  missing tag-catalog matches, duplicate workspace/tag pairs or unresolved
  nonempty workspace domain IDs in the queried data.
- Capacity and workspace history tables exist but are empty.
- The general active-item inventory is populated. The queried Lakehouse,
  Notebook, DataPipeline and Environment scanner tables are empty; this is an
  scanner-specific coverage gap, not proof that those items do not exist. The
  general inventory includes Lakehouse, Notebook, DataPipeline, Environment and
  VariableLibrary records, with workspace identity and deletion flags. It is a
  viable candidate for MVP inventory without requiring the scanner tables to be
  populated first. The inventory validation below confirms observed key
  uniqueness and metric/item matches, but also records unresolved workspaces;
  historical completeness remains unvalidated.
- Workspace/capacity extraction timestamps are current after the rerun.
- Item-operation metrics now include recent records and resolve to known
  workspaces. This confirms ingestion progress, not continuous usage coverage.
- Timepoint metrics initially did not advance after the rerun. The source
  Capacity Metrics semantic model had stale calendars and refresh history
  reported `ModelRefreshDisabled`. A current-period query returned no rows.
  After the user refreshed that model, its calendars advanced and the deployed
  timepoint measure query returned recent data.
- With explicit approval, only the timepoint notebook was submitted once, for a
  three-day scope with explicit source workspace/model parameters and display
  disabled. Its job completed without a reported failure or error exit value.
  OneLake metadata confirmed persisted table changes; SQL initially showed the
  earlier snapshot, then reflected recent timepoints after synchronization.
  No notebook code, full-pipeline execution or refresh schedule was changed.
- Recovered timepoints still cover only scattered measured intervals. Calendar
  rows are not evidence of measured availability, and missing intervals do not
  prove inactivity or a pause. Complete active capacity availability for a
  billing period remains unvalidated.
- No duplicate groups were found for `(CapacityId, TimePoint)` or the candidate
  `(CapacityId, WorkspaceId, ItemId, ItemKind, OperationName, Date)` key in the
  queried metrics. This does not establish completeness.
- Item-operation and timepoint metric coverage windows now differ. Their
  unfiltered totals are not a meaningful reconciliation. Compare identical
  covered windows and account for smoothing/date boundaries; no billing
  percentage is approved from the current comparison.

Detailed tenant counts, dates and usage totals are not published here.
Source validation remains open. The rerun resolved the empty classification and
stale workspace/capacity metadata findings from the initial check. Source refresh
and targeted extraction restored recent timepoints, but did not establish a
complete denominator. Next: validate zero-usage/active-interval coverage, the
general inventory joins and ongoing source-refresh health. Standalone notebook
and child-pipeline defaults differ from the master pipeline's source parameters;
always supply the verified source explicitly for directed runs. Do not rerun all of
FUAM solely because scanner-specific tables remain empty.
The local scanner supports `extract_powerbi_artifacts_only` and
`has_tenant_domains`; their deployed values and actual run behavior are unverified.

### Subsequent source refresh and targeted recovery

The user refreshed both Capacity Metrics models. Allowed calendar queries and
the Power BI parameters API confirmed refreshed source calendars and matching
configured `UTC_offset` values. A model refresh did not automatically advance
the persisted FUAM metric facts.

The existing item-operation and timepoint notebooks were then executed
sequentially with explicit verified source parameters, a three-day lookback and
display disabled. Their deployed default Lakehouse, parameter contracts and
gold-table merge behavior were inspected first, and no active source pipeline
or overlapping extraction notebook was found. Staging cleanup remained the
existing notebook behavior; no FUAM code, pipeline or schedule was changed.

Both jobs completed. SQL initially still exposed old timepoints; after
non-recreating metadata synchronization, persisted item-operation dates and
timepoints advanced. The current-classification previews conserved all stored
and selected-window metric rows and CU totals, with their unresolved item
matches visible. Timepoint keys remained unique. Newer observed facts are not
proof of complete interval coverage or historical classification.

The independent capacity collector also recovered lifecycle events after fixing
native row-query UUID casing and source report-clock handling. Both models'
bounded row-returning queries matched its persisted normalized event identities;
they were not appended as duplicate sources. See
[capacity history](capacity-history.md) for offset provenance and replay checks.
Protected service-app semantic model definition export was denied and was not
bypassed; only permitted queries and parameter metadata were used.

The source denominator diagnostic returned a full report-calendar grid but
reported availability only on a subset of timepoints. A nonblank available-CU
measure is therefore still not certified capacity uptime. Its date is a
report-clock day under `UTC_offset`, not automatically a UTC billing day.
Daily operation aggregates, smoothed timepoints and UTC lifecycle intervals
must be aligned and reconciled before billing arithmetic. Exact historical SKU
transitions and period coverage remain unvalidated; denominator and percentage
outputs remain blocked/null.

### Reusable read-only validation

Run [validate_fuam_sources.sql](../scripts/validate_fuam_sources.sql) against the
FUAM Lakehouse SQL analytics endpoint. It returns aggregate table counts,
freshness, candidate-key duplicates and timepoint distribution without exposing
item names, workspace IDs or users. Its results still describe tenant usage and
must stay private.

The script executed successfully again after the rerun and returned all six
result sets. Additional read-only checks validated classification joins and
general inventory type coverage. These are diagnostics, not complete acceptance
tests: timepoint coverage and historical attribution remain unresolved. Following
the targeted run, read-only SQL confirmed recent persisted timepoints and no
duplicate `(CapacityId, TimePoint)` groups. This checks recovery and uniqueness,
not billing eligibility.

### Inventory/workspace relationship validation

Run [validate_inventory_joins.sql](../scripts/validate_inventory_joins.sql)
read-only against the FUAM Lakehouse SQL endpoint. Its seven result sets expose:

1. Validation time, item/workspace extraction timestamps and the selected metric
   window. The default window ends after the latest **stored** metric date; it
   is not necessarily the current period or a complete 14-day extraction.
2. Normalized item/workspace/domain/tag-pair uniqueness and item UUID checks.
3. Workspace presence/lifecycle and current capacity correspondence, including
   missing capacity-catalog records.
4. Inventory by type/deletion flag with and without metrics in the selected
   window. Metric existence checks use both item and workspace IDs.
5. All-history and selected-window consumption joins, keeping unmatched facts
   and facts whose workspace is currently marked deleted.
6. Observed metric-kind/inventory-type pairs resolved by IDs, not type names.
7. Workspace-derived domain and raw tag-count status without exploding inventory
   rows across tags.

The saved diagnostic executed successfully. Seven result sets returned;
six key checks had no failures, all stored metric rows resolved to their
inventory item/workspace pair, and the inventory totals reconciled across the
workspace, consumption-presence and domain/tag summaries without dropping or
multiplying rows. Items without metric rows remained present. This validates
the queried snapshot, not full issue acceptance or historical attribution.

**Sanitized findings and implementation rules:**

- General inventory includes Lakehouse, Notebook, DataPipeline, Environment
  and VariableLibrary, including items with no observed metric rows in the
  selected window. Do not build the inventory from consumption facts.
- Some items marked active/not-deleted have no matching FUAM workspace and
  no matching capacity-catalog record. Keep an explicit `MissingWorkspace`
  classification, item-source lineage and unresolved capacity state. Do not
  guess their domain/use case or infer deletion from absence.
- A direct paginated Fabric Admin workspace reconciliation was attempted but
  rejected with `InsufficientScopes`. Their current workspace type/state was
  therefore not established. Required delegated scope is `Tenant.Read.All` or
  `Tenant.ReadWrite.All`; successful SQL access does not imply this API scope.
  No access grants, login changes or FUAM writes were performed.
- Where both current inventory/workspace records resolved, their capacity IDs
  matched. This is current-state correspondence, not historical assignment.
- FUAM workspace deletion flags can coexist with `State = Active`; some stored
  consumption still refers to those workspaces. Preserve both source fields and
  those facts. Do not filter out historical consumption solely because a
  current workspace/item deletion flag is set.
- Upstream active-item transfer merges by `id` and updates missing-source
  records' `fuam_deleted` flag. It updates metadata in place rather than keeping
  an effective-dated item/workspace assignment ledger. A flag is a source
  observation, not verified original deletion time.
- Metric kind names differ from inventory type names: observed examples include
  `SynapseNotebook / Notebook`, `Pipeline / DataPipeline`,
  `Variables / VariableLibrary` and `Dataset / SemanticModel`. Also,
  `Warehouse` metric rows resolved to both `Warehouse` and `SQLEndpoint` items.
  A one-to-one kind-name alias is not a safe join key. Keep original metric kind
  and canonical inventory type separately.
- For the MVP, use general `active_items` as the inventory source. The empty
  scanner tables are not additional records to union blindly; introduce
  source precedence only when a populated second source has been validated.
- Raw Fabric tag counts are not use-case classification. One raw tag does not
  prove a designated use-case tag, and multiple raw tags do not necessarily
  constitute a use-case conflict. Classification must use the approved stable
  tag-ID allowlist from issue 2 before resolving zero/one/multiple matches.
- Source extraction and metric dates lag the validation time. Show those
  timestamps and telemetry gaps; no-metric labels mean only "no observation in
  the selected stored window", not "never used" or zero current usage.
- Only schema and aggregate metadata were read. Item definitions, descriptions,
  creator identities and Variable Library values were not extracted or published.

Remaining inventory acceptance gates: reconcile missing workspace coverage,
establish exact effective-dated assignments, and verify behavior after actual reassignment or
deletion. Current joins do not retrospectively prove either event.

The pilot's designated Domain-scope tags are now approved and registered in an
[editable monitoring catalog](use-case-classification.md). A successful manual
classification capture preserves catalog and workspace observations, including
explicit unclassified/ambiguous/missing-workspace states. This begins prospective
classification history without modifying FUAM. It does not establish exact
effective-change times or backfill historical item attribution.
Domain ancestry is now snapshotted from stable `DomainId`/
`OriginalParentDomainId` chains and inherited by workspace/items. Root/subdomain
display names remain metadata, not keys. Source domain-parent reconciliation
and hierarchy integrity checks passed without changing metric/CU conservation.
The collector subsequently deployed normalized item observations inheriting the
workspace capture and preserving no-metric/deleted inventory records. A
[current-classification consumption preview](item-consumption-preview.md) now
groups source item-operation measures without fanout. Exact retained inventory
metadata and raw/joined/grouped metric row/CU totals passed live reconciliation.
This preview always labels historical attribution as unvalidated; it does not
resolve source freshness or billing gates.

### Denominator validation

The [Capacity Metrics compute-page documentation](https://learn.microsoft.com/en-us/fabric/enterprise/metrics-app-compute-page#cards)
explicitly excludes both paused timepoints and active timepoints not reporting
usage from its average utilization. Summing reported `SKUCUByTimePoint` therefore
does not necessarily yield all capacity available while active. Do not use that
sum as the billing denominator without independent active-interval coverage.

Read-only probes of the deployed source model confirmed:

- Its calendar has a full day's 30-second slots, while availability measures
  populate only a subset. A tested day had no reported availability at all.
  These blanks remain unknown, not zero capacity or confirmed inactivity.
- A native detail sample exposed base CU units, SKU and 30-second start/end
  windows. Its reported availability agrees with base CU multiplied by window
  seconds. The timepoint availability is already in CU seconds; do not multiply
  it by 30 again. This validates the sample, not every historical SKU or interval.
- A `System Events` DirectQuery table exposes capacity identity, state, state
  change reason and transition time. No events were returned for the pilot in
  the queried recent window. Current capacity state alone cannot establish its
  state at the beginning of a historical billing period.
- FUAM has no discovered system-event table, and its capacity history table is
  empty. Its history schema includes a snapshot date, not a verified ledger of
  exact transition times.
- Source measure expressions were not exposed by the metadata query. A complex
  detail aggregation failed with a DirectQuery folding error; a simpler bounded
  detail query succeeded. The findings rely on returned values and documented
  semantics, not assumed internal measure definitions.

Run [validate_capacity_denominator.dax](../scripts/validate_capacity_denominator.dax)
against the Capacity Metrics source model, replacing its capacity/date placeholders
locally. Execute it as one query through Power BI `executeQueries`, with
`serializerSettings.includeNulls` enabled. It returns calendar and reported
availability counts, explicit-zero versus blank consumption counts, reported CU
seconds and lifecycle-event count. Counts use zero for empty sets; missing CU
values remain blank. It returns no chargeback percentage.
The explicit timepoint bounds are essential: filtering `Dates` alone can filter
the measures without reducing the enumerated timepoint calendar. The expected
count describes a full source-calendar day, not the number of active intervals.
Evaluate finalized days; an in-progress day's absent future slots cannot establish
a telemetry fault.
The saved DAX diagnostic passed live checks for a partially reported day and a
day without reported availability: exactly one row with the expected 12 fields,
2,880 calendar slots and reconciled interval counts. The sampled CU-second sum
matched its interval count; missing availability remained blank rather than zero.

**Required Fabric-only extension before billing:**

1. Persist lifecycle events before they age out of the app's documented
   14-day compute window, with extraction success, query window and source
   freshness evidence. An empty event result is not an initial-state anchor.
2. Establish an effective-dated state/SKU baseline and preserve subsequent
   observations. Sampled snapshots do not locate an intervening pause or SKU
   change precisely; unresolved transition intervals remain unvalidated.
3. Use lifecycle reasons `Created`, `ManuallyResumed`, `ManuallyPaused` and
   `Deleted` to distinguish existence/availability from performance state.
   Throttled or overloaded does not mean paused. In particular, an
   `Active / NotOverloaded` event after suspension does not prove resumption;
   this exception is documented in
   [Monitor a paused capacity](https://learn.microsoft.com/en-us/fabric/enterprise/monitor-paused-capacity#considerations-and-limitations).
4. Calculate available CU seconds from validated active intervals and their
   effective SKU, including active intervals with confirmed zero consumption.
   Do not infer zero consumption merely from an absent metric row.
5. Keep operational reported utilization separate from billing eligibility.
   Unknown initial state, incomplete event/usage coverage or unresolved SKU
   changes block the billing percentage, while observed consumption remains
   visible. Historical periods before the baseline cannot be reconstructed
   merely by starting future collection.

Inventory establishes observed existence, not the original creation timestamp.
Expose creation time only when a `Created` event or another verified Fabric
source supplies it; otherwise distinguish first observed time from creation time.
The subsequent [capacity-history collector pilot](capacity-history.md) deployed
an independent Lakehouse/notebook and verified its first persisted observations.
FUAM and source-model configuration were not changed. Hourly UTC collection is
now enabled with a bounded 90-day schedule; its first scheduler-origin run and
additional snapshot were verified. This prospective history does not validate
earlier billing periods. Schedule state and coverage gaps must be checked after
capacity pauses/resumption.
The new [denominator eligibility diagnostic](../scripts/validate_capacity_eligibility.sql)
validated its expected shape and invalid-window guard while exposing gaps,
source-calendar lag and metric capacities without history. Denominator and
billing percentages remain unknown; an enabled schedule and repeated Active/SKU
observations do not validate complete lifecycle/SKU intervals.

## Open correctness questions

1. Confirm the actual item-operation grain and deduplication key.
2. Sampled availability units are validated above. Confirm numerator units and
   historical SKU/window consistency before reconciliation.
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

Collector unit tests and live schema/aggregate diagnostics have run. There are
no report validations yet; the report and its percentages are not deployed.
