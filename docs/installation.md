# Single-notebook customer installation

Download [Install_UseCase_Monitoring.ipynb](../notebooks/Install_UseCase_Monitoring.ipynb),
import it into the destination workspace, edit its parameter cell and select
**Run all**. There is no local CLI, Git connection, runtime GitHub download or
manual creation of monitoring Lakehouses, tables, collector notebooks, SQL
views, semantic models or reports. The notebook embeds the implementation.

## Prerequisites, not resources provisioned by this installer

- Existing FUAM and Capacity Metrics installation with accessible data.
- Run interactively as an authorized organizational user, with Contributor or
  higher in the target workspace, access to the FUAM Delta tables and SQL
  endpoint, and the capacity/source-model access needed by the history collector.
  Power BI executeQueries must be permitted by tenant policy.
- FUAM may be in the destination workspace or a different accessible workspace.
  A OneLake table shortcut exposes its metric fact in the monitoring Lakehouse;
  SQL views never query directly across workspaces. The executing and model
  connection identities must have the necessary source/shortcut access.
- A running Fabric Spark-capable capacity and a runtime with `requests`,
  `pyodbc`, ODBC Driver 18 for SQL Server, and the existing collectors'
  `semantic-link`/Spark/Delta dependencies. No driver/system installation,
  capacity creation/resume, privilege grants or source-model refresh is attempted.
- Authorized SQL cloud connection matching the **new monitoring** SQL endpoint
  server and database. A FUAM connection to a different database is not a match.
  Fabric may require the customer to create/share/configure this connection in
  Service after the Lakehouse/model exists. The installer cannot grant access,
  obtain consent or enter organizational credentials on the customer's behalf.
  Copy the server/database printed by the installer **exactly**, including
  database casing. The installer uses a lowercase SQL database alias. A cloud
  connection path with different casing may not bind even when SQL resolves
  both aliases to the same Lakehouse.

## Parameter cell

| Parameter | Meaning |
| --- | --- |
| `source_workspace_id` | FUAM source workspace UUID, or empty when FUAM is in the destination workspace. |
| `source_lakehouse_name` | Existing FUAM Lakehouse name; default `FUAM_Lakehouse`. Resource IDs are discovered. |
| `installation_prefix` | Names of the isolated monitoring resources; default `UseCaseMonitoring`. Use a new prefix for a separate installation. |
| `metric_sources` | One mapping per monitored capacity: `capacity_id`, Capacity Metrics `workspace_id`, `model_id`. No access tokens. |
| `initial_use_cases` | Optional initial entries `{"UC": "Report name", "TAG": "EXACT_TAG_NAME"}`. Domain tag IDs are resolved from FUAM and internal case IDs generated automatically. Empty means all workspaces remain unclassified. The previous ID-based format remains supported; do not mix formats. |
| `initial_estimates` | Optional explicitly approved full-report-day assumptions; see [scenario schema](capacity-scenarios.md). Empty means real consumption is visible but real percentages stay blank. No inferred F-SKU or active time is seeded. |
| `daily_policies` | Optional automatic daily mode: one explicitly approved F8-active-24h policy per monitored capacity, with source report UTC offset. Requires `initial_estimates=[]`. See below. Empty preserves the original one-time scenario mode. |
| `sql_connection_id` | Optional explicit existing authorized connection. Required if multiple matches exist. Never a password/token. |
| `focus_date` | Initial report page day, or empty for latest stored metric day. Changing the report's date is done in its Filters pane. |
| `operation` | `install` creates/resumes and validates; `refresh` also reruns collectors and refreshes the Import model. |

Keep installation/source/initial seed parameters unchanged on resumptions.
Edit the resulting catalog/assumption tables through Spark for subsequent
business changes, not by reseeding or changing installed notebook definitions.
Connections may be configured after the first run: set `sql_connection_id`
and rerun the same notebook. SQL credentials are never accepted as parameters.

For the initial catalog, paste a list directly into the parameter cell:

```python
initial_use_cases = [
    {"UC": "Example analytics", "TAG": "EXAMPLE_ANALYTICS"},
    {"UC": "Example operations", "TAG": "EXAMPLE_OPERATIONS"},
]
```

`UC` is the report display name and may differ from `TAG`. Names are trimmed
at the input boundary; tag matching is exact and case-sensitive, restricted
to Domain-scope tags in FUAM's `tags` table (`tagId`, `scope`, `displayName`).
Each name must resolve to one tag. Missing or ambiguous tags, repeated use-case
names or repeated resolved tags fail the initial load explicitly. No Fabric
tags are created. If a new tag is missing from FUAM, refresh the upstream
extraction first. The generated IDs are persisted once in `dbo.use_cases`;
later runs classify by those IDs, not by names. This is an initial seed only,
not an import/update mechanism for an existing catalog.

## What Run all does

1. Checks FUAM schemas and nonempty inventory/consumption, and verifies each
   source model contains its configured capacity.
2. Creates a schema-enabled monitoring Lakehouse and resolves its SQL endpoint.
   Tests SQL access using the executing user's token; the Import connection is
   a separate prerequisite.
3. Creates a OneLake metric shortcut without copying/modifying the source, plus
   parameterized, Lakehouse-attached history notebooks (one per
   capacity), classification/inventory notebook and isolated scenario notebook.
4. Runs the initial collectors sequentially, retaining run ledgers and source
   evidence. Existing catalog/scenario tables are not overwritten.
5. Synchronizes SQL metadata without recreating source tables and creates
   inventory, consumption, demo and estimated views.
6. Validates source/joined/estimated metric row and CU conservation and inventory
   identity uniqueness.
7. Creates the independent Import semantic model and four-page PBIR report.
8. Binds an exactly matching authorized SQL connection, verifies the binding,
   submits one transactional refresh, and follows its receipt.
9. Checks all synthetic model outcomes and real imported metric/inventory counts
   against SQL. Prints the report URL only as **ready** after validation.

The report pages are estimated consumption, synthetic demo, current objects and
assumptions/coverage. No historical/billing certification is implied.

## Reruns, blocked steps and operating the solution

The new Lakehouse contains a private resume record:
`Files/usecase-monitoring-install/state.json`. It stores resource IDs, package
identity, completed steps and pending API receipts, never tokens/passwords.
Keep it private; do not commit notebook outputs or tenant-edited notebooks.

Run the installer **sequentially**, never concurrently. It reuses only resources
with its matching ownership/configuration marker. Name collisions or changed
packages fail instead of adopting/overwriting existing items. It is an
installer, not an automatic upgrade or disaster-recovery tool.

Pending operations/jobs/refreshes are followed through their original receipt,
not resubmitted. Network failures before a receipt leave an ambiguous submission
that requires an operator to inspect the relevant resource/history before
repairing the pending record. Do not blindly clear it.

Missing/ambiguous connections stop with `SQL_CONNECTION_REQUIRED`. Configure the
model connection in **Service > Semantic model settings > Gateway and cloud
connections**, then rerun with its connection ID. Resources and completed
collector steps remain intact. Binding visibility is checked for up to 60
seconds without repeating the bind request. An already matching binding is
reused. If verification times out, inspect model settings and rerun the same
installed notebook; a binding that has since become visible can be reused.
Do not replace the package or change the installation prefix to resolve a
visibility delay.
Refresh failures stop immediately, retain the
failed receipt and do not automatically retry credentials. After investigating
and correcting the failure, an explicitly initiated rerun can try again.

For subsequent operation use the same notebook with `operation = "refresh"`.
This recaptures classification, collects capacity observations and refreshes
the model after SQL synchronization. It does **not** refresh FUAM or Capacity
Metrics upstream. Run after their own successful refresh/extraction.

No automatic schedule is created. Scheduling identities, frequency, capacity
cost and credential access must be agreed separately. New use cases and
estimated dates are not added automatically in the original seed-only mode. Unknown periods stay blank,
not measured zero. Monitoring itself consumes capacity.

## Initial 30 days, then D-1 and catch-up

For a **new installation**, keep the initial catalog and metric source mappings
and configure the parameter cell once:

```python
initial_estimates = []
daily_policies = [{
    "capacity_id": metric_sources[0]["capacity_id"],
    "sku": "F8",
    "source_utc_offset_minutes": -240,
}]
operation = "install"
```

This is explicit approval of **assumed F8 active 24 hours**, not measured
availability. The installer checks the offset against the source Capacity
Metrics model's `UTC_offset`. One policy is required per monitored capacity;
other SKUs and combining daily policies with initial scenario seeds are rejected
to avoid applying an unapproved assumption. Never infer the source offset from
the workstation time zone. Fixed offsets do not infer daylight-saving rules.

The new Lakehouse-attached `_Daily` notebook:

1. Persists an installation start at D-30 and initially attempts the 30 complete
   source report days through D-1. It reads the **existing FUAM Delta fact**,
   not the Capacity Metrics model's historical data API.
2. Copies available rows into `dbo.monitoring_daily_metrics`, partitioned by
   capacity/report day. It preserves source duplicates and unknown quantities
   and validates row, null-quantity and CU totals before completing the scan.
   Partition replacement on retry does not append duplicate consumption.
3. Writes one coverage record per requested capacity/day in
   `dbo.monitoring_daily_periods`. `MissingSourceDay` means unknown consumption:
   no synthetic zero fact is inserted. `SourceRowsObserved` means rows exist,
   **not** that the day has certified complete telemetry.
4. Creates deterministic, explicitly assumed F8 availability periods/intervals
   once; it rejects conflicts rather than overwriting manually approved periods.
5. Saves the scan watermark and rolling bounds in `dbo.monitoring_daily_state`
   only after archive validation, assumptions and coverage writes complete.

After installation, change **only** `operation = "refresh"` and run the same
installer manually after successful upstream FUAM extraction. Keep the same
prefix, source IDs, catalog seed and policy. It captures current classification
and history observations, ingests D-1 and every unprocessed day since the
installation start, retries missing source dates, and rechecks the latest
**three complete days** for late data. Previously archived rows survive source
retention; an absent upstream day does not delete the archive
(`RetainedArchiveSourceUnavailable`). Corrections to older already-observed
days outside this replay window need an explicit later backfill workflow.

The model is refreshed after SQL metadata synchronization and validation.
It still uses a **full Import refresh**; incremental ingestion describes the
Lakehouse collector, not Power BI incremental-refresh partitions.

The report defaults to the last 30 complete dates **as of the last successful
daily scan**, using an imported rolling-date flag, not a fixed `focus_date`.
It does not advance by itself without running `refresh`. The assumptions page
shows coverage and last source-check time. Any selected capacity/day with
missing source rows blocks the whole selected period's utilization percentage;
known partial consumption remains visible. Filtering to dates with rows may
show an estimate but does not certify completeness. The availability
denominator is never reduced by a use-case/domain filter.

### Limits

- No schedule is created and neither FUAM nor Capacity Metrics is refreshed.
  Run this only after their successful extraction; new missing dates remain
  explicit and can recover on a later run.
- Thirty requested dates do not guarantee thirty available dates. Historical
  source data must already exist in FUAM. No historical consumption, pauses,
  SKU or tags are fabricated.
- Historical consumption is still attributed using **current** inventory/tag
  classification. Daily snapshots start now, not retrospectively.
- The separate lifecycle collector retains its existing 14-day API query
  window; the 30-day backfill here is of the FUAM metric fact and assumed
  availability, not certified 30-day lifecycle history.
- Run sequentially. Delta updates across metrics, coverage, assumptions and
  state are not one transaction. Failures stop the installer; retries replace
  the affected metric partitions and upsert stable daily keys. The Import
  model is not refreshed after a failed collector.
- Existing installations are not upgraded automatically. Use a new prefix
  and configure its own authorized SQL connection, leaving V3 unchanged.

## Package maintenance and validation

```powershell
python scripts\build_install_notebook.py
python -m unittest discover -s tests -v
git diff --check
```

The builder regenerates the committed notebook from the existing collectors,
SQL scripts, model/report generators and installer. Never manually edit the
embedded implementation or replace source references with tenant values.

Tests cover self-contained packaging, parameter cells/default Lakehouse,
resource reuse/collision handling, pending receipt resumption, connection gates,
failed-refresh stop behavior, host validation, pagination, partial DAX errors
and row/CU conservation, including regional Power BI refresh receipts followed
through the canonical API without sending credentials to regional hosts.

Live validation in a separate target workspace with an existing cross-workspace
FUAM source confirmed Lakehouse/shortcut/collector/view/model/report creation,
notebook-user SQL access, the missing-connection gate and resumption, cloud
binding, transactional Import refresh, all 12 synthetic DAX outcomes, and exact
SQL/model metric and inventory count equality. An unchanged sequential install
reused all resources without repeating initial collector jobs or model refresh.
The `refresh` operation also passed: it reused resources, ran each collector
exactly once, submitted one new Import refresh and revalidated SQL/model counts.
The deployed notebook also passed an exact four-cell ipynb round-trip check.
The subsequent UC/TAG seed adapter passed focused resolver/collector integration
tests and a read-only lookup against actual FUAM tag metadata. Existing deployed
catalogs were not migrated or modified; use a new installation prefix to test
this package revision rather than replacing a previously installed package.

The optional daily mode was also installed in a new isolated workspace prefix.
Its initial scan recorded 30 expected source dates, archived only available
FUAM rows and retained explicit missing-source coverage. SQL and DAX checks
confirmed the full 30-day assumed F8 denominator, a blank utilization percentage
for an incomplete selected period, and an observed-day percentage equal to
that day's actual CU seconds divided by assumed daily availability. Automated
tests cover source-clock boundaries, catch-up, missing-day retries and
three-day replay. A full manual `refresh` replay passed SQL/model validation
and preserved the archive, coverage, assumption counts and date bounds without
duplicate ingestion. The final deployed notebook passed the exact package
round-trip check after removing private validation diagnostics. The 56-test
suite passed, and the daily PBIR definition passed all 35 official part schemas.

The report is published, but rendering in the browser remains a customer check
requiring an interactive sign-in. These checks do not certify billing readiness,
other tenants' permissions/runtimes, or unattended scheduling.
