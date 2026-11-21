# Fabric capacity history collector

## Deployment and scope

[collect_capacity_history.py](../notebooks/collect_capacity_history.py) is a
Fabric PySpark notebook source with a tagged parameter cell. A manual pilot is
deployed in an independent, schema-enabled `UseCaseMonitoring_Lakehouse` in the
FUAM workspace. No existing FUAM tables, notebooks or pipelines were changed.
No recurring schedule is enabled.

The first pilot completed and encrypted SQL queries confirmed its successful run
record, current-state/SKU snapshot, empty-but-present event table, zero duplicate
keys and valid snapshot/run linkage. Empty event results are source observations,
not proof of historical inactivity or uninterrupted availability.
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
the Capacity Metrics model's `Dates`, `Capacities` and `System Events` tables.
Fabric and Power BI REST clients acquire the execution identity's tokens; no
credentials, Azure resource APIs, user names, owners or tag values are persisted.
Execution requires capacity visibility, source-model query permissions and
write access to the destination Lakehouse.

Events use a half-open UTC query window `[run start - lookback, run start)`.
Offset-free timestamps returned by Power BI executeQueries are interpreted as
source UTC timestamps. Snapshots record when Core metadata was observed, not
when the capacity was originally created or last changed.

## Tables

| Table | Key | Meaning |
| --- | --- | --- |
| `dbo.capacity_collection_runs` | `run_id` | Running/Succeeded/Failed, query window, source identity, source-calendar maximum, observation counts and failure stage/type |
| `dbo.capacity_state_snapshots` | `snapshot_id` | Selected capacity's observed state and SKU, observation time and run linkage |
| `dbo.capacity_system_events` | `event_id` | Raw state/reason/time/activation identity, nullable availability effect and first observation/run |

`event_id` hashes normalized capacity identity, UTC event time, state, reason
and activation identity. Overlapping windows/reruns merge existing events without
duplicating or overwriting their first observation. Each new run retains a new
snapshot, including unchanged state/SKU.

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

Collection currently runs serially for one capacity. No parallel writer or
automatic schedule is enabled. Schedule design and additional capacities follow
pilot approval; overlapping windows should preserve events before they age out
of the source's available window.

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

Six tests passed for replay/offset-stable event identity, lifecycle versus
performance effects, scope/limit validation, partial-response rejection,
missing/duplicate capacities and bounded query construction.
The live pilot verified Spark/REST/Delta integration. Pylance file validation
could not resolve this sibling repository in its current workspace; Python test
imports and the live notebook execution validated syntax/runtime instead.
The saved SQL diagnostic also passed: all four result sets returned, all seven
invariant checks had zero failures, and a successful snapshot was persisted.
`git diff --check` passed.

The first observed snapshot is a prospective anchor only. It cannot reconstruct
pre-observation availability, exact transitions between sampled SKUs or the
original creation time when the `Created` event is unavailable. Billing
percentages remain blocked until those coverage requirements pass.
