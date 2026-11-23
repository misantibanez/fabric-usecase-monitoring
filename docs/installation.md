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
estimated dates are not added automatically. Unknown periods stay blank,
not measured zero. Monitoring itself consumes capacity.

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

The report is published, but rendering in the browser remains a customer check
requiring an interactive sign-in. These checks do not certify billing readiness,
other tenants' permissions/runtimes, or unattended scheduling.
