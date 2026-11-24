"""Build a deployable Import model definition; deployment values stay outside source."""
import argparse
import json
from pathlib import Path


def classification_key(alias: str = "") -> str:
    return "CONCAT(" + ",'|',".join(
        f"COALESCE({alias}{column},'~')"
        for column in (
            "use_case_id", "root_domain_id", "subdomain_id", "classification_status"
        )
    ) + ")"


def build_model(server: str, database: str, daily: bool = False) -> dict[str, str]:
    key = classification_key()
    estimate = "dbo.vw_use_case_capacity_estimate"
    inventory = "dbo.vw_latest_item_use_case_inventory"
    queries = {
        "Consumption": f"SELECT *,{key} AS classification_key FROM {estimate}",
        "Classification": f"""SELECT DISTINCT {key} AS classification_key,
            use_case_name,root_domain_name,subdomain_name,classification_status FROM (
            SELECT use_case_id,root_domain_id,subdomain_id,use_case_name,root_domain_name,subdomain_name,classification_status FROM {estimate}
            UNION SELECT use_case_id,root_domain_id,subdomain_id,use_case_name,root_domain_name,subdomain_name,classification_status FROM {inventory}
            ) q""",
        "Capacity": f"""SELECT metric_capacity_id AS capacity_id FROM {estimate}
            UNION SELECT capacity_id FROM {inventory} WHERE capacity_id IS NOT NULL""",
        "Availability": f"""SELECT DISTINCT metric_capacity_id AS capacity_id,
            CAST(metric_date AS date) AS metric_date,estimate_status,
            scenario_available_cus,assumption_note,source_utc_offset_minutes,
            window_start,window_end FROM {estimate}""",
        "Inventory": f"SELECT *,{key} AS classification_key FROM {inventory}",
        "Demo": "SELECT * FROM dbo.vw_capacity_demo",
        "Refresh": "SELECT GETUTCDATE() AS refreshed_at",
    }
    columns = {
        "Consumption": [
            ("Report Date", "metric_date", "dateTime", True),
            ("Capacity Key", "metric_capacity_id", "string", True),
            ("Classification Key", "classification_key", "string", True),
            ("Consumed CU Seconds", "observed_total_cus", "double", True),
            ("Missing Quantities", "missing_cu_value_count", "int64", True),
            ("Metric Rows", "metric_row_count", "int64", True),
            ("Estimate Status", "estimate_status", "string", False),
        ],
        "Classification": [
            ("Classification Key", "classification_key", "string", True),
            ("Use Case", "use_case_name", "string", False),
            ("Domain", "root_domain_name", "string", False),
            ("Subdomain", "subdomain_name", "string", False),
            ("Classification Status", "classification_status", "string", False),
        ],
        "Capacity": [("Capacity", "capacity_id", "string", False)],
        "Availability": [
            ("Capacity Key", "capacity_id", "string", True),
            ("Report Date", "metric_date", "dateTime", True),
            ("Estimate Status", "estimate_status", "string", False),
            ("Available CU Seconds", "scenario_available_cus", "double", True),
            ("Assumptions", "assumption_note", "string", False),
            ("Source Offset Minutes", "source_utc_offset_minutes", "int64", False),
            ("UTC Start", "window_start", "dateTime", False),
            ("UTC End", "window_end", "dateTime", False),
        ],
        "Inventory": [
            ("Item", "item_name", "string", False),
            ("Item Type", "item_type", "string", False),
            ("Item State", "item_state", "string", False),
            ("Workspace", "workspace_id", "string", False),
            ("Item Key", "item_id", "string", True),
            ("Capacity Key", "capacity_id", "string", True),
            ("Classification Key", "classification_key", "string", True),
            ("Marked Deleted", "item_deleted_flag", "boolean", False),
            ("Observation UTC", "observed_at", "dateTime", False),
        ],
        "Demo": [
            ("Scenario", "scenario_id", "string", False),
            ("Use Case", "use_case_name", "string", False),
            ("Status", "availability_status", "string", False),
            ("Consumed CU Seconds", "observed_total_cus", "double", True),
            ("Available CU Seconds", "scenario_available_cus", "double", True),
            ("Missing Quantities", "missing_cu_value_count", "int64", True),
            ("Expected Percentage", "expected_capacity_percentage", "double", True),
        ],
        "Refresh": [("Refresh UTC", "refreshed_at", "dateTime", False)],
        "Date": [
            ("Report Date", "Report Date", "dateTime", False),
            ("Year", "Year", "int64", False),
            ("Month", "Month", "int64", False),
        ],
    }
    measures = {
        "Consumption": [
            ("Observed CU Seconds", "IF(SUM('Consumption'[Missing Quantities])>0,BLANK(),SUM('Consumption'[Consumed CU Seconds]))", "#,##0.00", "FUAM operation-date CU seconds; not reconciled smoothed utilization."),
            ("Observed Metric Rows", "SUM('Consumption'[Metric Rows])", "#,##0", "Count of preserved FUAM metric rows."),
            ("Estimated Capacity Usage", "IF([Missing Availability Days]>0,BLANK(),DIVIDE([Observed CU Seconds],[Assumed Available CU Seconds]))", "0.00%", "Ratio of totals. Capacity/date denominator is not reduced by use case or domain. Not for billing."),
            ("Not For Billing", '"ESTIMADO - NO APTO PARA COBRO | Clasificacion actual e intervalos/SKU no validados"', "@", "Mandatory warning; no certified billing measure is supplied."),
        ],
        "Availability": [
            ("Assumed Available CU Seconds", "IF([Missing Availability Days]>0,BLANK(),SUM('Availability'[Available CU Seconds]))", "#,##0.00", "One denominator per capacity/report day, never summed per use case."),
            ("Missing Availability Days", "IF(COUNTROWS('Availability')>0,COALESCE(COUNTROWS(FILTER('Availability',ISBLANK('Availability'[Available CU Seconds]) || NOT('Availability'[Estimate Status] IN {\"ScenarioReady\",\"NoActiveCapacity\"}))),0),BLANK())", "#,##0", "Selected capacity/days without valid scenario arithmetic; blocks period percentage. Nonexistent combinations remain blank."),
        ],
        "Inventory": [
            ("Inventory Items", "COUNTROWS('Inventory')", "#,##0", "Current captured objects including no-metric and marked-deleted observations."),
        ],
        "Demo": [
            ("Demo CU Seconds", "IF(SUM('Demo'[Missing Quantities])>0,BLANK(),SUM('Demo'[Consumed CU Seconds]))", "#,##0.00", "Entirely synthetic consumption; unknown quantities remain blank."),
            ("Demo Available CU Seconds", "VAR _scenarios=CALCULATETABLE(SUMMARIZE('Demo','Demo'[Scenario],'Demo'[Available CU Seconds]),REMOVEFILTERS('Demo'[Use Case]),REMOVEFILTERS('Demo'[Status])) RETURN IF(COUNTROWS(FILTER(_scenarios,ISBLANK('Demo'[Available CU Seconds])))>0,BLANK(),SUMX(_scenarios,'Demo'[Available CU Seconds]))", "#,##0.00", "Distinct synthetic scenario denominator independent of use case."),
            ("Demo Capacity Usage", "DIVIDE([Demo CU Seconds],[Demo Available CU Seconds])", "0.00%", "Synthetic ratio of totals; zero or unknown denominator is blank, >100% is not clipped."),
            ("Demo Warning", '"DEMO SINTETICA - NO APTO PARA COBRO"', "@", "Synthetic data is isolated from tenant consumption."),
        ],
    }
    if daily:
        queries["Capacity"] += " UNION SELECT capacity_id FROM dbo.monitoring_daily_periods"
        queries["Availability"] = "SELECT * FROM dbo.vw_monitoring_daily_coverage"
        columns["Availability"] += [
            ("Source Coverage", "source_status", "string", False),
            ("Source Metric Rows", "metric_rows", "int64", True),
            ("Last Source Check UTC", "processed_at", "dateTime", False),
        ]
        columns["Date"].append(("In Rolling Window", "In Rolling Window", "int64", False))
        measures["Availability"] += [
            ("Missing Source Days",
             "IF(COUNTROWS('Availability')>0,COALESCE(COUNTROWS(FILTER('Availability','Availability'[Source Coverage]=\"MissingSourceDay\")),0),BLANK())",
             "#,##0", "Capacity/report days with no archived source rows; unknown consumption, never zero."),
            ("Source Days With Rows",
             "IF(COUNTROWS('Availability')>0,COALESCE(COUNTROWS(FILTER('Availability',NOT(ISBLANK('Availability'[Source Metric Rows])))),0),BLANK())",
             "#,##0", "Days containing source rows; presence of rows does not certify complete telemetry."),
        ]
        measures["Consumption"] = [
            (name, "IF([Missing Source Days]>0,BLANK()," + expression + ")", fmt, description)
            if name == "Estimated Capacity Usage" else (name, expression, fmt, description)
            for name, expression, fmt, description in measures["Consumption"]
        ]
    parts = {
        "definition.pbism": json.dumps({"version": "4.2", "settings": {"qnaEnabled": False}}),
        "definition/database.tmdl": "database\n\tcompatibilityLevel: 1702\n",
        "definition/model.tmdl": "model Model\n\tculture: es-ES\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\tdiscourageImplicitMeasures\n\n" + "\n".join(f"ref table '{t}'" for t in columns) + "\n",
        "definition/expressions.tmdl": (
            "expression Server = " + json.dumps(server) + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n\n'
            + "expression Database = " + json.dumps(database) + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        ),
    }
    for table, fields in columns.items():
        lines = [f"/// Isolated monitoring {table.lower()}; estimates and demo never certify billing.", f"table '{table}'", ""]
        for name, expression, fmt, description in measures.get(table, []):
            lines += [f"\t/// {description}", f"\tmeasure '{name}' = {expression}", f"\t\tformatString: {fmt}", ""]
        for name, source, dtype, hidden in fields:
            lines += [f"\t/// Source field {source}.", f"\tcolumn '{name}'", f"\t\tdataType: {dtype}"]
            if hidden:
                lines += ["\t\tisHidden"]
            lines += ["\t\tsummarizeBy: none", f"\t\tsourceColumn: {source}"]
            if dtype == "dateTime":
                lines += ["\t\tformatString: yyyy-MM-dd" if name == "Report Date" else "\t\tformatString: yyyy-MM-dd HH:mm:ss"]
            lines += [""]
        if table == "Date":
            sql = f"SELECT CAST(MIN(metric_date) AS date) AS first_date,CAST(MAX(metric_date) AS date) AS last_date FROM {estimate}"
            if daily:
                sql = "SELECT MIN(first_day) AS first_date,MAX(window_end_day) AS last_date FROM dbo.monitoring_daily_state"
            m = (
                'let Bounds=Sql.Database(Server,Database,[Query="' + sql + '"]), '
                'First=Date.From(Bounds{0}[first_date]), Last=Date.From(Bounds{0}[last_date]), '
                'Days=List.Dates(First,Duration.Days(Last-First)+1,#duration(1,0,0,0)), '
                'Dates=Table.FromList(Days,Splitter.SplitByNothing(),{"Report Date"}), '
                'Typed=Table.TransformColumnTypes(Dates,{{"Report Date",type datetime}}), '
                'Years=Table.AddColumn(Typed,"Year",each Date.Year([Report Date]),Int64.Type), '
                'Months=Table.AddColumn(Years,"Month",each Date.Month([Report Date]),Int64.Type) in Months'
            )
            if daily:
                m = m.removesuffix(" in Months") + (
                    ', Rolling=Table.AddColumn(Months,"In Rolling Window",'
                    'each if Date.From([Report Date])>Date.AddDays(Last,-30) '
                    'and Date.From([Report Date])<=Last then 1 else 0,Int64.Type) in Rolling'
                )
        else:
            sql = " ".join(queries[table].split())
            m = 'Sql.Database(Server, Database, [Query="' + sql.replace('"', '""') + '", CreateNavigationProperties=false])'
        lines += [f"\tpartition '{table}' = m", "\t\tmode: import", "\t\tsource = " + m, ""]
        parts[f"definition/tables/{table}.tmdl"] = "\n".join(lines)
    relationships = []
    for table in ("Consumption", "Availability"):
        for column, target, target_column in (
            ("Report Date", "Date", "Report Date"), ("Capacity Key", "Capacity", "Capacity")
        ):
            relationships += [f"relationship '{table} {target}'", f"\tfromColumn: '{table}'.'{column}'", f"\ttoColumn: '{target}'.'{target_column}'", ""]
    for table in ("Consumption", "Inventory"):
        relationships += [f"relationship '{table} Classification'", f"\tfromColumn: '{table}'.'Classification Key'", "\ttoColumn: 'Classification'.'Classification Key'", ""]
    relationships += ["relationship 'Inventory Capacity'", "\tfromColumn: 'Inventory'.'Capacity Key'", "\ttoColumn: 'Capacity'.'Capacity'", ""]
    parts["definition/relationships.tmdl"] = "\n".join(relationships)
    return parts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(build_model(args.server, args.database)), encoding="utf-8")
