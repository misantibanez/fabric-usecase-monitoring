# Editable use-case catalog and workspace observations

The [classification notebook](../notebooks/classify_use_cases.py) writes to the
independent monitoring Lakehouse, not FUAM. It reads FUAM's `tags`, `workspaces`,
`workspace_tags`, `active_items` and `domains_flatten` Delta tables. Run it manually with the source
workspace/Lakehouse IDs and the monitoring Lakehouse attached as the default.
Set `source_table_schema` to the source Lakehouse's actual Delta schema for
schema-enabled sources; leave it empty for legacy `Tables/<table>` sources.
SQL endpoint `dbo` alone does not prove a Delta `Tables/dbo` directory exists.
The single-notebook installer discovers this distinction from Lakehouse metadata.
An hourly classification schedule has not been configured.

## Tables

| Table | Purpose |
| --- | --- |
| `dbo.use_cases` | Team-editable catalog: stable `use_case_id`, display name, Fabric `tag_id`, Boolean `is_enabled`. |
| `dbo.classification_runs` | Running/Succeeded/Failed evidence, UTC start/end and failure type/message. |
| `dbo.workspace_use_case_snapshots` | One observation per workspace/run, including capacity/domain IDs, source metadata and classification. |
| `dbo.use_case_catalog_snapshots` | Catalog copy associated with each completed capture. |
| `dbo.item_use_case_snapshots` | One item per run, inheriting its workspace observation, with item type/lifecycle, separate item-capacity metadata and extraction timestamp. |
| `dbo.domain_hierarchy_snapshots` | Per-run original domain/parent IDs and names with resolved root/subdomain/path evidence. |

Only enabled entries referencing an existing Fabric **Domain-scope tag ID**
participate. Domain-scoped tags are not identified by display-name equality or
by counting all workspace tags. A tag may belong to only one enabled use case.
Use-case IDs must also be unique; invalid catalogs fail explicitly.

- Exactly one matching case: `Assigned`.
- None: `Unclassified`.
- More than one: `Ambiguous`, with no assigned use-case ID.
- Workspace referenced by items/tags but absent from FUAM workspace metadata:
  `MissingWorkspace`, with no inferred assignment, capacity or domain.

Repeated/descriptive tags cannot multiply workspace rows. Workspace observations
include inventory-only references and workspaces with no observed consumption.
FUAM deletion flags are retained as metadata, not used to erase observations.
The normalized item inventory now inherits workspace classification in the same
capture. It retains objects without metrics and marked-deleted records. Item
tags do not override that inheritance, and metric kind names are not used as
item identity. Domain/subdomain hierarchy is now captured and inherited by
stable domain/parent IDs. Exact historical assignment remains a subsequent step.

## Maintaining the catalog

The Lakehouse SQL analytics endpoint is read-only. Edit through a Spark notebook
with the monitoring Lakehouse as its default, using Spark SQL or Delta APIs.
Coordinate edits with collection; do not edit during a classification run.
Do not allow users to edit the collector's evidence/snapshot tables.

To add a case, obtain its actual Fabric tag UUID and choose a new stable case
UUID. The following is synthetic Spark SQL; replace the identifiers and name:

```sql
INSERT INTO dbo.use_cases (use_case_id, use_case_name, tag_id, is_enabled)
VALUES (
    '11111111-1111-1111-1111-111111111111',
    'Example use case',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    true
);
```

Keep `use_case_id` stable when renaming a case. To retire it, set `is_enabled`
to `false` rather than deleting its lineage. To change the assigned tag, update
`tag_id` explicitly and verify no other enabled case uses it. Renaming a Fabric
tag does not change ID-based attribution.

`initial_use_cases_json` is a one-time seed, accepted **only when the catalog
does not exist**. It fails if seed records are supplied to an existing catalog.
Keep deployed defaults at `[]`; never commit live seed data to this repository.
Subsequent runs must use `[]` and read the team's edited table.

Changes apply to the next successful observation, not retrospectively.
Snapshot timestamps describe collection, not the exact time a tag, domain or
capacity assignment changed. Historical consumption before observation, and
periods with unobserved changes, remain unvalidated.

## Validation and failure handling

Run [validate_use_case_classification.sql](../scripts/validate_use_case_classification.sql)
against the monitoring Lakehouse SQL endpoint. It returns four result sets:
current catalog, run outcomes, latest successful workspace-state counts and
12 integrity checks. Each integrity check must have zero failing groups.
Keep all results and failure details private.

Downstream consumers must join snapshots to `classification_runs` and select
only `Succeeded` runs. Delta writes to different tables are not one transaction;
a failed capture may have partial snapshots. Do not treat them as valid history
or automatically retry a seed.

The first successful pilot persisted the approved catalog and workspace/catalog
observations. Earlier attempts failed reading the source Delta log with a Spark
403. Using lowercase canonical source resource IDs resolved the observed Spark
read without changing permissions. Matching/classification IDs remain normalized
independently. Detailed failure messages are now persisted in the run ledger.
OneLake and SQL schema visibility can lag; check OneLake before concluding a
failed run made no writes or before deciding to reseed.
If tables are present in OneLake but missing/stale in SQL, the documented
[SQL endpoint metadata refresh](https://learn.microsoft.com/en-us/rest/api/fabric/sqlendpoint/items/refresh-sql-endpoint-metadata)
can synchronize them. Scope `tables` to the affected `dbo` tables above and keep
`recreateTables` at `false`; do not rebuild tables or rerun the seed to address
SQL visibility. This refresh succeeded for the pilot's classification tables.

Local tests cover domain-tag validation, descriptive/repeated tags, ambiguous and
missing-workspace states, immutability of prior results and canonical Spark paths.
The saved SQL diagnostic returned its four expected result sets and all 12
integrity checks passed. Source workspace-key reconciliation also passed without
missing/extra keys. A subsequent notebook run with no seed records succeeded,
confirming it reads the persisted editable catalog. Unit tests alone do not prove
deployed table contents or historical billing eligibility.

The collector also records `inventory_snapshot_count`; older runs have no count
and did not capture items. The inventory view selects the latest successful run
with a non-null inventory count, including a valid empty capture. The
[item inventory and consumption-preview guide](item-consumption-preview.md)
describes the deployed views, source-key checks and additional reconciliation.

## Domain hierarchy

Domain ancestry uses `DomainId` and `OriginalParentDomainId`; names are display
metadata, not join keys. The collector does not trust flattened display-name
matches or the synthetic "Without Subdomain" label as a domain identity.

Workspace/item observations include `root_domain_id/name`, `subdomain_id/name`,
`domain_path_ids`, `hierarchy_depth` and `domain_resolution_status`.
The root is the ancestor with no parent. A root-assigned workspace has null
subdomain fields and depth zero. A descendant's subdomain is its assigned leaf;
the root-to-leaf UUID path preserves intermediate ancestors if present.
The original workspace `domain_id` remains unchanged.

`NoDomain`, `MissingWorkspace`, `DomainNotFound`, `ParentDomainNotFound` and
`HierarchyCycle` distinguish absent/unresolvable hierarchy from a resolved root.
No root or subdomain is inferred for unresolved chains. Duplicate domain IDs or
invalid required source fields fail the capture explicitly.
The domain catalog is snapshotted in the same run with `domain_snapshot_count`.
Older captures have null new fields/counts and are not backfilled.
The metric preview labels uncaptured hierarchy `NotCaptured` and failed item
joins `ItemWorkspaceUnresolved`.

Run [validate_domain_hierarchy.sql](../scripts/validate_domain_hierarchy.sql):
three result sets report domain/item coverage and five integrity checks. The
pilot passed all checks and exact source domain-ID/name/parent reconciliation.
Synthetic tests cover identical names in different roots, inherited subdomains,
root-only assignments, missing parents and cycles. Hierarchy enrichment did not
change inventory cardinality or metric/CU conservation.
