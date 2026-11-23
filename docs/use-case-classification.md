# Editable use-case catalog and workspace observations

The [classification notebook](../notebooks/classify_use_cases.py) writes to the
independent monitoring Lakehouse, not FUAM. It reads FUAM's `tags`, `workspaces`,
`workspace_tags` and `active_items` Delta tables. Run it manually with the source
workspace/Lakehouse IDs and the monitoring Lakehouse attached as the default.
An hourly classification schedule has not been configured.

## Tables

| Table | Purpose |
| --- | --- |
| `dbo.use_cases` | Team-editable catalog: stable `use_case_id`, display name, Fabric `tag_id`, Boolean `is_enabled`. |
| `dbo.classification_runs` | Running/Succeeded/Failed evidence, UTC start/end and failure type/message. |
| `dbo.workspace_use_case_snapshots` | One observation per workspace/run, including capacity/domain IDs, source metadata and classification. |
| `dbo.use_case_catalog_snapshots` | Catalog copy associated with each completed capture. |

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
Item inheritance and domain/subdomain hierarchy enrichment are subsequent steps;
these tables do not yet deploy a normalized item inventory.

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
can synchronize them. Scope `tables` to these four `dbo` tables and keep
`recreateTables` at `false`; do not rebuild tables or rerun the seed to address
SQL visibility. This refresh succeeded for the pilot's classification tables.

Local tests cover domain-tag validation, descriptive/repeated tags, ambiguous and
missing-workspace states, immutability of prior results and canonical Spark paths.
The saved SQL diagnostic returned its four expected result sets and all 12
integrity checks passed. Source workspace-key reconciliation also passed without
missing/extra keys. A subsequent notebook run with no seed records succeeded,
confirming it reads the persisted editable catalog. Unit tests alone do not prove
deployed table contents or historical billing eligibility.
