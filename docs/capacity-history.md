# Fabric capacity history collector

## Deployment and scope

[collect_capacity_history.py](../notebooks/collect_capacity_history.py) is a
Fabric PySpark notebook source with a tagged parameter cell. A manual pilot is
deployed in an independent, schema-enabled `UseCaseMonitoring_Lakehouse` in the
FUAM workspace. No existing FUAM tables, notebooks or pipelines were changed.
One hourly UTC schedule is enabled for the pilot capacity, with a bounded
90-day validity and no automatic renewal. Expiry is recorded in the private
Fabric schedule configuration, not in this public repository.

The first pilot completed and encrypted SQL queries confirmed its successful run
record, current-state/SKU snapshot, empty-but-present event table, zero duplicate
keys and valid snapshot/run linkage. Later recovery identified a native-query
UUID casing issue that affected those empty event results; they do not establish
historical inactivity or uninterrupted availability.
Tenant names, identifiers, timestamps and counts remain private.

## Parameters and sources

| Parameter | Meaning |
| --- | --- |
| `metric_workspace` | Capacity Metrics source workspace UUID |
| `metric_dataset` | Capacity Metrics source semantic model UUID |
| `capacity_id` | One explicitly selected capacity UUID |
| `history_window_days` | Integer from 1 through 14; default 14 |

Keep empty source/identity defaults in the public notebook. Supply real values
only at deployment/execution, not in committed files. Attach the independent
Lakehouse as the notebook's default and verify its `dbo` schema before executing.

The collector reads Fabric Core `GET /v1/capacities`, including pagination, and
the Capacity Metrics model's `Dates`, `Capacities` and `System Events` tables,
plus its `UTC_offset` through the Power BI dataset parameters API.
Fabric and Power BI REST clients acquire the execution identity's tokens; no
credentials, Azure resource APIs, user names, owners or tag values are persisted.
Execution requires capacity visibility, source-model query permissions and
write access to the destination Lakehouse.

Events use a half-open UTC query window `[run start - lookback, run start)`.
The source model must expose exactly one valid `UTC_offset`; missing or invalid
metadata fails rather than silently assuming UTC. The organization-configured
offset supports fractional hours representing whole minutes, from -12 through
+14 hours. UTC query bounds are translated into that report clock before DAX
filtering. Offset-free event timestamps returned by executeQueries are converted
back to UTC using the verified source offset. Explicit ISO offsets remain
authoritative. Do not infer a timezone name or daylight-saving transitions from
this fixed-offset setting.
The parameter's meaning and range are documented in the
[Capacity Metrics app installation guidance](https://learn.microsoft.com/en-us/fabric/enterprise/metrics-app-install).

Native row-returning `System Events` queries use lowercase UUIDs, while stored
identities remain canonical uppercase. Live comparison showed that an uppercase
row predicate could return no events even when aggregate count probes reported
matches. Validate the actual bounded row-returning query, not only `COUNTROWS`.
Snapshots record when Core metadata was observed, not when the capacity was
originally created or last changed. `source_calendar_max` retains the source
calendar label; it is not converted into an event instant or coverage guarantee.

## Tables

| Table | Key | Meaning |
| --- | --- | --- |
| `dbo.capacity_collection_runs` | `run_id` | Running/Succeeded/Failed, UTC query window, source identity, source-calendar maximum, verified source offset, observation counts and failure stage/type |
| `dbo.capacity_state_snapshots` | `snapshot_id` | Selected capacity's observed state and SKU, observation time and run linkage |
| `dbo.capacity_system_events` | `event_id` | UTC event instant, raw source timestamp and offset, state/reason/activation identity, nullable availability effect and first observation/run |

`event_id` hashes normalized capacity identity, UTC event time, state, reason
and activation identity. Overlapping windows/reruns merge existing events without
duplicating or overwriting their first observation. Each new run retains a new
snapshot, including unchanged state/SKU.
Missing provenance columns are added with an empty Delta schema-evolution
append before merging, even for an empty event result. Existing observations
are retained; legacy provenance remains null rather than being backfilled.

Only `Active/Created`, `Active/ManuallyResumed`, `Suspended/ManuallyPaused`
and `Deleted/Deleted` carry availability effects. Performance events, including
`Active/NotOverloaded`, and unknown state/reason pairs remain raw facts with
no inferred availability effect.

## Failure and completeness semantics

- HTTP failures, partial/error query responses, invalid data, out-of-scope
  events and event-limit saturation fail explicitly.
- A valid empty event table is accepted; an invalid response is not converted
  into an empty result.
- A missing/inaccessible capacity fails; it is not inferred deleted.
- Runs start as `Running`. Success is recorded only after both history writes
  complete; persisted run/snapshot checks are performed before notebook success.
- On failure, record stage and exception type and rethrow. No raw error bodies or
  tokens are stored. A hard process interruption can leave a `Running` record;
  treat it as incomplete, not successful.
- Delta commits across these three tables are not a single transaction. Ignore
  snapshots whose run is not `Succeeded`. Raw events may remain after a failed
  run; their presence never establishes complete window coverage.
- `event_count` is the number of unique events observed by that run, not the
  number newly inserted into the event table.
- `Succeeded` means extraction/persistence completed. It is not a billing
  eligibility flag: source freshness, event-window coverage, initial state,
  usage completeness and historical SKU transitions still require validation.

Collection targets one capacity through one schedule. Do not introduce parallel
writers or overlapping manual runs. Hourly scheduling does not itself provide a
writer lock if an execution takes longer than its interval. Overlapping query
windows preserve observed events without duplicating them; expanding the pilot
to additional capacities requires separate validation.

## Hourly scheduling and operation

The selected interval is 60 minutes (nominally 24 Spark executions per day).
The proposed 90-day validity was retained when no duration was supplied.
There is no automatic renewal or capacity resume action.

The schedule API accepts configuration and execution data, but does not expose
the top-level parameter array used by the successful manual notebook run.
Therefore, bind the verified source workspace/model/capacity and 14-day lookback
in the **deployed** notebook's parameter cell before scheduling. Public source
defaults remain empty. Preserve the implementation cells and default Lakehouse
binding; export/read the definition to verify them.

1. Inspect existing schedules; do not create a duplicate.
2. Create one disabled `RunNotebook` schedule using the Core Job Scheduler API,
   `Cron`, interval `60`, timezone `UTC` and explicit UTC start/end timestamps.
3. Read it back and verify owner, interval, validity and disabled state.
4. Enable it with `PATCH`, preserving the chosen configuration. Read it back
   again and verify that only one schedule exists.
5. Verify an actual `Scheduled` job and its persisted run/snapshot, not a manual
   substitute or merely a `Completed` job status.
6. Recheck successful-run freshness and `Running`/`Failed` records regularly.
   No notification/alerting service is deployed yet.

The first scheduler-origin execution completed and its successful run and
additional snapshot were independently confirmed in SQL. Subsequent validation
encountered an inactive capacity and a disabled schedule. After the user
confirmed resumption, Fabric's active state was verified and the **same**
schedule was re-enabled without changing its expiry. The cause of the earlier
disablement was not established.

Pausing the hosting capacity can prevent Spark execution and SQL endpoint
validation. Do not assume its schedule remains enabled after resumption: inspect
the existing schedule and explicitly re-enable it when approved. Do not create
a replacement, extend expiry silently or resume the capacity automatically.
Keep the gap visible; a later successful query does not prove every earlier
window was fully observed.

The collector consumes capacity itself. Show monitoring overhead separately
from business activity in later reporting, without silently discarding or
redistributing its CU consumption. Monitoring-only operations must not be
presented as proof of a business use case being active.

## Reproducible deployment

1. Create a schema-enabled independent Lakehouse.
2. Split the notebook source into its parameter, implementation and invocation
   cells, preserving the parameter tag, and bind the actual default Lakehouse
   in deployment-only notebook metadata.
3. Publish using the Notebook REST API's `ipynb` definition format. The initial
   Git-source import did not preserve cells in this deployment; it was detected
   before execution and corrected using explicit `ipynb` cells.
4. Export/read the deployed definition and verify all three cells, exactly one
   parameter cell, collector code and the intended Lakehouse binding.
5. Run once with explicit parameters, track its accepted job ID and verify
   persisted tables, not just the notebook job's `Completed` status.
6. Run [validate_capacity_history.sql](../scripts/validate_capacity_history.sql)
   against the new Lakehouse SQL endpoint after synchronization.

## Validation

From the repository root:

```powershell
python -m unittest discover -s tests -v
```

Regression tests passed for replay/offset-stable event identity, lifecycle versus
performance effects, scope/limit validation, partial-response rejection,
missing/duplicate capacities, lowercase native predicates, report-clock query
bounds, fractional offsets and half-open UTC event windows.
The live pilot verified Spark/REST/Delta integration. Pylance file validation
could not resolve this sibling repository in its current workspace; Python test
imports and the live notebook execution validated syntax/runtime instead.
The saved SQL diagnostic also passed: all four result sets returned, all seven
original invariant checks had zero failures, and a successful snapshot was
persisted.
`git diff --check` passed.
Hourly automation was verified through a scheduler-origin job, schedule
readback/owner checks and its additional persisted snapshot. SQL verification
was interrupted while the capacity was inactive and resumed after reactivation;
the hosting capacity was not resumed by this solution.

Following the user's source refresh, the corrected collector was deployed
without changing its parameter defaults, destination or hourly schedule.
Its successful persisted run recovered lifecycle events with raw timestamp
and verified offset provenance. Both source models' actual bounded row queries
were compared against saved UTC event identities, not combined as separate
events. Recovered pause/resume evidence was checked against independent Core
snapshots around the collection gap. These checks do not certify exact SKU
transitions, event-source completeness or billing availability.
The SQL diagnostic now also checks source-offset ranges, paired event
provenance and first-observation/run-window linkage.
The corrected scheduler-origin execution subsequently completed; its overlapping
window preserved event keys and original first-observation fields. All ten SQL
history invariants passed. The existing single schedule remained enabled with
the same owner, interval and expiry.

The first observed snapshot is a prospective anchor only. It cannot reconstruct
pre-observation availability, exact transitions between sampled SKUs or the
original creation time when the `Created` event is unavailable. Billing
percentages remain blocked until those coverage requirements pass.

## Denominator eligibility evidence

Run [validate_capacity_eligibility.sql](../scripts/validate_capacity_eligibility.sql)
against the monitoring SQL endpoint. Set a positive half-open UTC window
explicitly, or use its default 14-calendar-day window ending after the latest
stored FUAM item-operation date. Missing dates or non-positive windows raise an
explicit SQL error rather than reporting a successful empty denominator.

The single result set has 14 fields and includes capacities seen in metrics
even when no history has been collected for them. It reports first/last successful
observations, baseline observation count, observations in the window, the largest
gap between adjacent snapshots intersecting the window, latest source calendar,
successful event-query windows containing the period and raw lifecycle-event
observations.

A baseline count is point-in-time evidence, not proof of uninterrupted state.
The reported snapshot gap is the full adjacent-observation separation, not
measured downtime or certified active/inactive seconds. A query-window count
does not prove model freshness, continuous event coverage or exact historical
SKU. Raw events, including those first persisted in a failed capture, do not
establish extraction completeness. Source calendar maxima are freshness evidence,
not confirmation that every interval is represented.

This diagnostic is deliberately **not an availability calculator**. With the
current snapshot/raw-event contract, every row has
`DenominatorStatus = Blocked_UnvalidatedLifecycleAndSKUIntervals`;
`AvailableCUSeconds` and `BillingCapacityPercentage` remain null.
There is no optimistic eligibility based on repeated Active/F-SKU snapshots,
zero events, a populated calendar or an enabled hourly schedule.
Future billing calculation requires a separately verified lifecycle/SKU interval
contract, usage/numerator reconciliation and historical classification.

Live validation checked the exact result shape for both the stored-metric window
and the prospective observation window, preserved null denominator/percentage
values and rejected a zero-duration window. It exposed missing history for a
metric capacity, missing period-start observations, stale source calendar evidence
and a substantial collection gap. Schedule readback was enabled, but does not
erase earlier gaps. No schedule, capacity state or source-model configuration
was changed. Tenant identities, dates, gap durations and counts remain private.
