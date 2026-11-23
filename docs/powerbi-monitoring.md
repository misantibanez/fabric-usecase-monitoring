# Independent semantic model and visual report

The independent Import model and four-page Power BI report are deployed in the
monitoring workspace. Neither changes the FUAM or Chargeback semantic models.
Actual report/model IDs, source addresses, selected pilot dates and outputs stay
outside this public repository.

## Where to see the estimate

The Lakehouse table explorer shows physical Delta tables, not SQL views.
Switch to the Lakehouse **SQL analytics endpoint**, expand **Views**, and open
`dbo.vw_use_case_capacity_estimate`.
Group by capacity, report date and use case, sum observed CU seconds, and take
the single capacity/day denominator once. Do not add repeated denominators
across domain, classification or use-case rows.

The report's first page presents this calculation using explicit model measures:

1. **Estimated consumption:** real CU seconds, assumed availability, estimated
   ratio, missing capacity/day assumptions, domain/subdomain/use-case/capacity
   slicers, a use-case chart and summary table.
2. **Synthetic demo:** scenario selector, expected synthetic outcomes via the
   calculated measures, a results table and chart. Demo does not share real
   report-date, capacity or classification filters.
3. **Objects:** current inherited domain/subdomain/use-case classification,
   workspace, item type/state/deletion observations and inventory count.
   Items without usage remain present. This is a current inventory, not a
   date-filtered historical inventory.
4. **Assumptions and coverage:** distinct real capacity/report days, source
   offset, UTC bounds, scenario notes, availability and missing assumptions.
   Missing telemetry or assumptions never appears as measured zero usage.

All pages carry not-for-billing warnings. A scenario-ready status permits
estimated arithmetic only. No certified billing percentage is supplied.

The initial report day is chosen privately at deployment. To change it, use
the report's **Filters** pane and change/clear the page-level `ReportDay` filter.
The date slicer operates within that page filter; it cannot expand a locked
single-day page filter by itself.

## Model design

`Consumption`, `Availability` and `Inventory` share single-direction Capacity
and Classification dimensions where appropriate. Availability relates to
Capacity and Date only, so use-case/domain filters cannot shrink capacity.
The contiguous Date dimension filters consumption and availability, not current
inventory. Demo and refresh metadata are intentionally disconnected utilities.

Availability imports one distinct denominator per capacity/report day from the
estimate view. Period usage divides summed CU seconds by summed distinct-day
availability; it is not an average of daily ratios or share of observed usage.
Any selected recorded capacity/day missing valid assumptions blocks the period
percentage. Nonexistent capacity/date combinations remain blank and do not
produce a visual cross-product. A known day with no missing assumptions displays
zero for the quality count, not an unknown/blank value.

CU seconds retain the source floating-point representation to avoid rounding
away fractional consumption with a four-decimal fixed type. Comparisons use
explicit numerical tolerance; display formatting does not change stored values.
Technical keys and measure inputs are hidden; explicit measures carry formats.
Classifications preserve unresolved states and blank use-case names instead of
assigning unmatched consumption to a team.

## Reproducible generation and deployment

Generate definition-part JSON into a private/session directory:

```powershell
python scripts\build_monitoring_model.py --server "<SQL endpoint>" --database "<Monitoring database>" --output "<private model parts JSON>"
python scripts\build_monitoring_report.py --model-id "<deployed independent model UUID>" --focus-date "<complete report day YYYY-MM-DD>" --output "<private report parts JSON>"
```

The model generator emits TMDL and parameterized SQL Import partitions; the
report generator emits PBIR with a by-connection reference to the model.
Generated payloads contain deployment-specific values; never commit them.
Create the model/report via the Fabric REST API with InlineBase64 parts, inspect
existing names first and follow LRO receipts rather than blindly recreating.
For later updates, retrieve all current definition parts and change only the
owned objects, preserving other parts and connection configuration.

The modeling MCP connection could not resolve the target workspace in this
session. The authenticated Fabric REST path was used after that failure.

## Credentials and refresh

A default/automatic SQL connection did not permit Import refresh. The user
configured an explicit SQL cloud connection using organizational credentials
in the semantic model's Service settings; the subsequent transactional refresh
completed successfully. Do not save tokens in the model or programmatically
work around a credential failure.

Import is a snapshot: subsequent FUAM or assumption-table changes require model
refresh before the report shows them. The first page shows the refresh UTC
timestamp. No new refresh schedule was configured. Trigger refresh manually
until an ongoing source/model refresh policy is separately agreed.

## Verification

- Repository Python tests cover classification-key SQL serialization, generated
  report/model reference consistency and missing-availability visual semantics.
- Fabric parsed the complete TMDL and the user-configured SQL source refreshed.
- All PBIR parts validated against the official Microsoft JSON schemas.
- Live DAX reproduced synthetic 50%, 25%, 100%, 120%, zero and unknown results.
  [validate_monitoring_model.dax](../scripts/validate_monitoring_model.dax)
  compares demo actual versus expected ratios.
- Real use-case filtering preserved the denominator and reproduced the SQL
  estimate. All-period selection remained blank where assumptions were missing.
- The browser rendered the four pages, including the actual use-case
  percentage, synthetic outcomes, current inventory and coverage rows.
- A read-only query matching the assumptions visual verified exactly existing
  capacity/days rather than date/scenario cross-products.

This pilot unblocks estimated visualization, not source/billing certification,
alerting, precise historical inventory or automated refresh.
