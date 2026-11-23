# Item inheritance and current-classification consumption preview

The [classification collector](../notebooks/classify_use_cases.py) now captures
`dbo.item_use_case_snapshots` alongside workspace and catalog observations.
The same successful run governs all three; failed/partial captures are excluded
by the deployed inventory view. Collection is manual, not automatically hourly.

Each FUAM `active_items` ID is retained exactly once per capture, including
marked-deleted objects and objects with no metric rows. Duplicate item IDs fail
explicitly. The snapshot retains item name, type, state, deletion flag and source
extraction timestamp. No descriptions, creator identities, item definitions,
Variable Library values or credentials are collected.

Workspace classification, use-case ID/name, domain ID and current workspace
capacity are inherited by workspace ID. Item-native tags are ignored.
`item_capacity_id` is separate from the workspace's `capacity_id`; mismatches
and missing values have explicit statuses. Missing FUAM workspaces remain
unresolved, without inferring a domain, use case or workspace capacity.
Environment and VariableLibrary remain distinct inventory types.

## SQL views

Execute the three `GO`-delimited batches in
[create_consumption_preview_views.sql](../scripts/create_consumption_preview_views.sql)
against the monitoring SQL analytics endpoint after table metadata synchronization.
Adjust the source database identifier `FUAM_Lakehouse` if needed. These are SQL
views, not extra metric Delta copies or changes to FUAM.

| View | Purpose |
| --- | --- |
| `dbo.vw_latest_item_use_case_inventory` | Complete inventory from the latest successful item-enabled capture. |
| `dbo.vw_item_consumption_preview` | One row per FUAM item-operation metric row, joined by item ID with an explicit workspace-match check. |
| `dbo.vw_use_case_consumption_preview` | Daily totals by metric capacity, current use case/domain and quality statuses. |

The metric capacity always comes from the metric fact. A current capacity
mismatch never moves historical consumption to the workspace's current capacity.
Missing items and current item/workspace mismatches remain visible and unassigned.
Joining by metric item-kind display names is not supported: for example,
Warehouse metric labels can refer to different inventory types.

This is **not historical chargeback attribution**. Every metric-preview row has
`attribution_basis = CurrentClassificationPreview` and
`historical_attribution_status = Unvalidated`. The use case reflects the latest
inventory/workspace observation, not proven classification at metric execution
time. Renaming/reassigning a case may change this preview, while prior stored
inventory/catalog observations remain unchanged.

`observed_total_cus` preserves the source `TotalCUs` measure. This preview does not
certify it as the billing numerator, add smoothed timepoint consumption, calculate
available capacity, redistribute unclassified consumption or produce a billing
percentage. Null CU quantities remain unknown, not zero.
Distinct item counts are per view group and must not be summed across days or
operations as a global distinct count.

Live FUAM metric rows can change after collection; classification only advances
after another successful manual capture. Display metric dates, item extraction
timestamps and classification observation time. No metric row in a selected
window does not mean an item was never used.

## Validation

Run [validate_item_consumption_preview.sql](../scripts/validate_item_consumption_preview.sql)
against the monitoring SQL endpoint. Its five result sets describe:

1. The default 14-calendar-day window ending after the latest stored metric date,
   source extraction and observation times; this is not a freshness guarantee.
2. Inventory type/classification/lifecycle coverage and window metric presence.
3. Current-classification totals, including unclassified/unresolved consumption.
4. Six integrity checks, each requiring zero failing groups.
5. Raw-source, joined and grouped metric row counts/CU totals for all stored
   metrics and the selected window.

The pilot passed these checks and an additional exact source-versus-snapshot
comparison of item IDs, workspace IDs and retained metadata, without dropped or
extra items. Both scopes conserved metric rows and CU sums. Source float totals
use a tolerance of `max(1e-8, abs(source_sum) * 1e-12)` for summation-order rounding;
null sums must remain null. Local synthetic tests also cover missing/ambiguous
classification, items without metrics, item-tag exclusion, duplicate source IDs
and separate item/workspace capacity evidence.

Remaining gates: reconcile missing workspace metadata, domain/subdomain hierarchy,
exact reassignment/deletion history, source freshness, numerator semantics and
complete capacity availability. No report or billing percentage is deployed.
