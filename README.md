# Fabric Use-Case Monitoring

Fabric-only monitoring and capacity utilization attribution by use-case tags,
domains and subdomains, extending Fabric Unified Admin Monitoring (FUAM).

## Scope

- Classify workspaces by Fabric tags and their domain/subdomain.
- Attribute each item's consumption to its workspace's use case.
- Show consumed CU seconds and percentage of available capacity by period.
- Inventory items even when they have no observed consumption.
- Identify observed usage, potential inactivity and telemetry gaps.
- Preserve historical classification and capacity assignments.

Azure APIs, Azure tags, invoice ingestion and automatic capacity pause/resume are
out of scope. No tenant data, credentials, notebook outputs or model backups may
be committed to this public repository.

## Attribution rule

```text
Domain -> Subdomain -> Use case (TagId) -> Workspace -> Item
```

Only designated use-case tags participate in attribution. Other Fabric tags
remain descriptive metadata. One workspace must resolve to exactly one use case.
Workspaces without a matching tag are unclassified; multiple matching tags are
ambiguous and must not duplicate consumption.

Item inheritance is analytical: the solution does not write tags to Fabric items.
Item-native tags do not override workspace classification in the MVP.

## Capacity percentage

```text
Capacity usage % =
    use-case consumed CU seconds
    / available capacity CU seconds for the same capacity and period
    * 100
```

This is NOT the use case's share of total observed consumption.
For a continuously active F64 over one day:

```text
Available capacity = 64 * 86,400 = 5,529,600 CU seconds
Use-case consumption = 2,764,800 CU seconds
Capacity usage = 50%
```

Under the requested billing policy, 50% means 50% of the applicable capacity
invoice. Invoice values are not collected by the MVP.

- Period percentages use a ratio of totals, not an unweighted average of daily
  percentages.
- The denominator keeps capacity and period filters but is not reduced by
  use-case, workspace, domain or item filters.
- SKU changes and active intervals require historical evidence.
- Missing telemetry is not zero consumption or a confirmed pause.
- Unconsumed capacity is not automatically redistributed to teams.
- Consumption without a classified use case remains visible.
- Usage above 100% is shown without clipping; its billing treatment requires a
  separate decision.
- Timepoint and item-operation metrics must not be added together.
- Operation-date consumption and smoothed timepoint utilization must be
  reconciled before being presented as equivalent utilization percentages.

## Report

The primary view contains period, domain, subdomain, use case, capacity, SKU,
consumed CU seconds, available CU seconds, capacity usage percentage and coverage
status. Drill-through views cover workspaces, items, operations and last observed
usage. Capacity utilization, unattributed consumption, classification conflicts
and data quality are separate views.

## Delivery sequence

1. Validate FUAM sources, permissions and temporal coverage.
2. Define use-case classification and historical assignment.
3. Normalize the item inventory.
4. Implement and reconcile capacity percentages.
5. Implement usage and potential-inactivity indicators.
6. Build the independent semantic model.
7. Build the Power BI report.
8. Validate a pilot and document deployment and operation.

Work is tracked in [GitHub issues](https://github.com/misantibanez/fabric-usecase-monitoring/issues).
Start with source validation; do not assume a local source definition proves that
the deployed table exists or contains complete data.

## Current implementation status

This repository currently contains the approved scope, backlog, a
[FUAM source contract with sanitized live findings](docs/fuam-source-contract.md)
and a [read-only validation script](scripts/validate_fuam_sources.sql).
After FUAM was rerun, classification tables and workspace/capacity metadata are
populated and refreshed, and item-operation metrics include recent data.
The general inventory includes the requested item types, including Variable
Library. A stale Capacity Metrics source model blocked recent timepoint extraction.
After the user refreshed it and approved a targeted timepoint notebook run, recent
timepoints were verified in the Lakehouse SQL endpoint without duplicate keys.
Timepoint coverage remains incomplete, history tables remain empty, and
scanner-specific inventory tables remain empty. Source validation remains open;
no billing percentage is approved from the current data.
There is not yet a deployed semantic model, ingestion pipeline or Power BI report.

## Upstream references

- [FUAM](https://github.com/microsoft/fabric-toolbox/tree/main/monitoring/fabric-unified-admin-monitoring)
- [Fabric tags](https://learn.microsoft.com/en-us/fabric/governance/tags-overview)
- [Fabric smoothing and throttling](https://learn.microsoft.com/en-us/fabric/enterprise/throttling)
- [Chargeback app](https://learn.microsoft.com/en-us/fabric/enterprise/chargeback-app)

FUAM is a solution accelerator, not an officially supported Microsoft product.
Its Capacity Metrics app extraction can change with the app.
Microsoft supports the Chargeback semantic model only with the app's supplied
reports; this solution uses an independent model, not that model as a dependency.
