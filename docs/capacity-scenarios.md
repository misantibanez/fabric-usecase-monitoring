# Demo and real-consumption estimates

These sources unblock calculation/report development, not billing acceptance.
No synthetic events or assumptions are written into FUAM, classification or
the independent capacity history.

## Deployment

Deploy [initialize_capacity_scenarios.py](../notebooks/initialize_capacity_scenarios.py)
as a separate manual Fabric notebook with the monitoring Lakehouse as default.
Its public `initial_estimates_json` parameter defaults to `[]`.
Demo sources are deterministic and entirely synthetic. Real estimate seeds
are deployment-only JSON and must never be committed or printed publicly.

The notebook creates five separate tables only when absent:

| Table | Role |
| --- | --- |
| `dbo.capacity_demo_periods` | Synthetic capacity/report-day scenarios |
| `dbo.capacity_demo_intervals` | Synthetic state and SKU intervals |
| `dbo.capacity_demo_consumption` | Synthetic use-case consumption and expected results |
| `dbo.capacity_estimate_periods` | Editable real-capacity/report-day assumptions |
| `dbo.capacity_estimate_intervals` | Editable intervals, state/SKU basis and optional source-event reference |

Existing tables are preserved, including team edits. Running again does not
replace seeds, reset assumptions or extend an estimate to newer days.
For explicitly approved automatic F8 daily assumptions, use the installer's
[daily mode](installation.md#initial-30-days-then-d-1-and-catch-up) instead of
manually extending `initial_estimates`. This optional collector adds stable
daily periods and coverage without changing this initializer's seed-only behavior.
Creation across tables is not transactional: inspect all five tables after
failure, and verify the complete sources before deploying/reporting.
No new schedule is created.

Synchronize SQL metadata without recreating tables, then execute the
GO-delimited [view deployment](../scripts/create_capacity_scenario_views.sql).
Run [validate_capacity_scenarios.sql](../scripts/validate_capacity_scenarios.sql)
and the existing history/preview diagnostics.

## Demo

`dbo.vw_capacity_demo` has no real tenant identities, metrics or classifications.
It exposes expected and calculated percentages for these independent scenarios:

| Scenario | Expected result |
| --- | --- |
| Full F64 day, two use cases | 50% and 25%, with the same denominator |
| F64 paused for half the day | 100% for the specified synthetic consumption |
| F8/F16 change halfway through the day | 50% |
| Active F8, zero measured consumption | 0% |
| F8 consumption above capacity | 120%, not clipped |
| Missing telemetry interval | Null percentage and explicit gap |
| Unknown state or active SKU | Null percentage |
| No active capacity | Zero availability; percentage is undefined/null |
| Overlapping intervals | Null percentage and explicit overlap |
| Missing consumption | Null percentage, not zero |

Demo calculates the sum of `SKU CU * active interval seconds`. Inactive
intervals contribute zero. Gaps, unknown state/SKU and overlaps never yield a
successful denominator.

## Estimated view

`dbo.vw_use_case_capacity_estimate` preserves every existing
`vw_use_case_consumption_preview` group and its actual CU values, including
unclassified, unresolved and older facts without assumptions. The numerator
is FUAM operation-date CU seconds, not reconciled smoothed utilization.
Current classification remains explicitly historically unvalidated.

The denominator uses only the separate estimate intervals. An initial pilot
can use recovered lifecycle transitions for complete report days and an
explicitly **assumed constant F-SKU** from a current snapshot. Observed events
do not certify that no transition was missed; state continuity remains
unvalidated and must be stated in `state_basis` and `assumption_note`.
Do not apply the current SKU retroactively without labeling that assumption.

Each period must cover exactly its whole source report-clock day. Store its
configured source offset and corresponding half-open UTC boundaries; daily
aggregates cannot be prorated into partial UTC/report days. No daylight-saving
rules are inferred from the fixed source offset.

Use one estimate per capacity/report day. Multiple stored scenarios for that
key block its percentage without multiplying real consumption. A scenario ID
reused across capacity/days also blocks the percentage without multiplying real
groups. Absent
assumptions, gaps, unknown state/active SKU, invalid definitions and overlaps
leave percentage null with an explicit status. All-inactive days keep zero
availability but no percentage. Unknown quantities are never treated as zero.

All rows carry `can_bill = 0`, a not-for-billing warning and null
`billing_capacity_percentage`. A scenario-ready denominator is only readiness
for estimated arithmetic, not certified availability.
Do not sum repeated denominators across use cases/domains. Future period
measures must divide total consumption by distinct capacity/day denominators,
not average daily percentages or divide by total observed consumption.

## Editing assumptions

Edit the estimate Delta tables with a Fabric notebook; the SQL analytics
endpoint is read-only for Lakehouse data. Keep real identifiers in the Lakehouse.
For each period, maintain `scenario_id`, capacity UUID, report date, source offset,
UTC start/end and a nonempty `assumption_note`. Each interval links by scenario ID
and has UTC start/end, `Active`/`Inactive`/`Unknown`, F-SKU label/CU size (or null
for unknown), nonempty `state_basis`/`sku_basis`, and optional `source_event_id`.
Never edit source history to make a scenario pass.
Keep intervals within the period and avoid overlaps. Re-run validation after
edits; source views reflect current assumptions without a collector rerun.

This stage supplies SQL demo/estimate sources. The subsequent
[independent semantic model and Power BI report](powerbi-monitoring.md) are now
deployed on top of these sources; billing certification remains separate.

## Verified pilot status

The manual notebook and three SQL views are deployed in the monitoring
Lakehouse. Exact expected outputs passed for all synthetic cases, including
50%, 25%, 100%, 120%, zero and unknown outcomes. All real preview groups,
metric rows and CU totals were conserved.
The initial real pilot covers two completed report days for the selected
capacity, using an explicitly assumed constant F8 and recovered transition
references. Other dates/capacities remain visible without a percentage.
No historical classification, lifecycle or SKU evidence was overwritten.
An actual seed-free replay completed and preserved all five scenario tables,
including the initial real assumptions. Read-only synthetic SQL fixtures tested
the production estimate join against duplicate IDs, multiple scenarios per
capacity/day, missing assumptions and a valid 50% result without altering tenant
tables. Pilot interval states, UTC boundaries and offsets matched their
recovered event references. The production billing eligibility diagnostic
remained blocked with null percentages.
Python regression tests and live Spark imports validated the implementation;
Pylance could not resolve this sibling repository as a workspace user file.
