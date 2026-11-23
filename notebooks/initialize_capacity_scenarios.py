# Fabric notebook source

# METADATA ********************
# META {"kernel_info": {"name": "synapse_pyspark"}, "dependencies": {"lakehouse": {}}}

# PARAMETERS CELL ********************
initial_estimates_json = "[]"

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}

# CELL ********************
import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Scenario text fields must be nonempty")
    return value.strip()


def instant(value: object) -> datetime:
    parsed = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Scenario boundaries require explicit UTC/ISO offsets")
    return parsed.astimezone(timezone.utc)


def validate_scenarios(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    periods: list[dict[str, object]] = []
    intervals: list[dict[str, object]] = []
    scenario_ids: set[str] = set()
    capacity_days: set[tuple[str, date]] = set()
    for row in rows:
        scenario_id = text(row["scenario_id"])
        capacity_id = str(UUID(text(row["capacity_id"]))).upper()
        if UUID(capacity_id).int == 0 or scenario_id in scenario_ids:
            raise ValueError("Invalid capacity or duplicate scenario identifier")
        scenario_ids.add(scenario_id)
        metric_date = date.fromisoformat(text(row["metric_date"]))
        key = (capacity_id, metric_date)
        if key in capacity_days:
            raise ValueError("Only one initial estimate is allowed per capacity/report day")
        capacity_days.add(key)
        offset = row["source_utc_offset_minutes"]
        if type(offset) is not int or not -720 <= offset <= 840:
            raise ValueError("Source offset must be whole minutes from -720 through 840")
        start, end = instant(row["window_start"]), instant(row["window_end"])
        zone = timezone(timedelta(minutes=offset))
        midnight = datetime.combine(metric_date, datetime.min.time(), zone)
        if start != midnight.astimezone(timezone.utc) or end != start + timedelta(days=1):
            raise ValueError("Daily consumption requires exactly its full source report day")
        periods.append({
            "scenario_id": scenario_id, "capacity_id": capacity_id,
            "metric_date": metric_date, "source_utc_offset_minutes": offset,
            "window_start": start, "window_end": end,
            "assumption_note": text(row["assumption_note"]),
        })
        segments = row["intervals"]
        if not isinstance(segments, list):
            raise ValueError("Scenario intervals must be a list")
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                raise ValueError("Invalid scenario interval")
            left, right = instant(segment["interval_start"]), instant(segment["interval_end"])
            if not start <= left < right <= end:
                raise ValueError("Interval lies outside its scenario or has invalid duration")
            state = text(segment["state"])
            if state not in {"Active", "Inactive", "Unknown"}:
                raise ValueError("Invalid interval state")
            units, sku = segment.get("sku_cu"), segment.get("sku")
            if units is not None:
                if type(units) is not int or units not in {2 ** n for n in range(1, 12)}:
                    raise ValueError("Only supported F-SKU CU sizes are accepted")
                if sku != f"F{units}":
                    raise ValueError("SKU label and CU size disagree")
            elif sku is not None:
                raise ValueError("Unknown SKU must not carry a claimed SKU label")
            event_id = segment.get("source_event_id")
            intervals.append({
                "scenario_id": scenario_id, "interval_id": f"{scenario_id}:{index}",
                "interval_start": left, "interval_end": right, "state": state,
                "sku": sku, "sku_cu": units,
                "state_basis": text(segment["state_basis"]),
                "sku_basis": text(segment["sku_basis"]),
                "source_event_id": text(event_id) if event_id is not None else None,
            })
    return periods, intervals


def demo_data() -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end, half = start + timedelta(days=1), start + timedelta(hours=12)
    definitions = [
        ("FullDay", [(start, end, "Active", 64)], [("Case A", 2764800.0, 50.0), ("Case B", 1382400.0, 25.0)], 5529600.0),
        ("HalfPaused", [(start, half, "Active", 64), (half, end, "Inactive", 64)], [("Case A", 2764800.0, 100.0)], 2764800.0),
        ("SKUChange", [(start, half, "Active", 8), (half, end, "Active", 16)], [("Case A", 518400.0, 50.0)], 1036800.0),
        ("ZeroUsage", [(start, end, "Active", 8)], [("Case A", 0.0, 0.0)], 691200.0),
        ("Over100", [(start, end, "Active", 8)], [("Case A", 829440.0, 120.0)], 691200.0),
        ("TelemetryGap", [(start, half, "Active", 8)], [("Case A", 345600.0, None)], None),
        ("UnknownState", [(start, end, "Unknown", 8)], [("Case A", 100.0, None)], None),
        ("NoActiveCapacity", [(start, end, "Inactive", 8)], [("Case A", 0.0, None)], 0.0),
        ("Overlap", [(start, end, "Active", 8), (half, end, "Active", 8)], [("Case A", 100.0, None)], None),
        ("UnknownSKU", [(start, end, "Active", None)], [("Case A", 100.0, None)], None),
        ("MissingConsumption", [(start, end, "Active", 8)], [("Case A", None, None)], 691200.0),
    ]
    periods, intervals, consumption = [], [], []
    for index, (name, segments, cases, expected_available) in enumerate(definitions, 1):
        scenario_id = "Demo_" + name
        row = {
            "scenario_id": scenario_id, "capacity_id": str(UUID(int=index)),
            "metric_date": start.date().isoformat(), "source_utc_offset_minutes": 0,
            "window_start": start.isoformat(), "window_end": end.isoformat(),
            "assumption_note": "Entirely synthetic scenario: " + name,
            "intervals": [{
                "interval_start": left.isoformat(), "interval_end": right.isoformat(),
                "state": state, "sku": f"F{units}" if units is not None else None,
                "sku_cu": units, "state_basis": "Synthetic",
                "sku_basis": "Synthetic",
            } for left, right, state, units in segments],
        }
        p, i = validate_scenarios([row])
        periods.extend(p)
        intervals.extend(i)
        for case_name, quantity, expected_percentage in cases:
            if quantity is not None and (not math.isfinite(quantity) or quantity < 0):
                raise ValueError("Invalid synthetic consumption")
            consumption.append({
                "scenario_id": scenario_id, "use_case_name": case_name,
                "root_domain_name": "Demo domain", "subdomain_name": "Demo subdomain",
                "observed_total_cus": quantity,
                "missing_cu_value_count": int(quantity is None),
                "expected_available_cus": expected_available,
                "expected_capacity_percentage": expected_percentage,
            })
    return periods, intervals, consumption


def initialize_scenarios(spark: "SparkSession", estimates_json: str) -> None:
    from pyspark.sql.types import (
        DateType, DoubleType, IntegerType, StringType, StructField, StructType, TimestampType,
    )

    estimates = json.loads(estimates_json)
    if not isinstance(estimates, list) or not all(isinstance(row, dict) for row in estimates):
        raise ValueError("Initial estimates must be a JSON array of scenarios")
    estimate_periods, estimate_intervals = validate_scenarios(estimates)
    demo_periods, demo_intervals, consumption = demo_data()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    string, timestamp, integer = StringType(), TimestampType(), IntegerType()
    period_schema = StructType([StructField(name, kind, True) for name, kind in [
        ("scenario_id", string), ("capacity_id", string), ("metric_date", DateType()),
        ("source_utc_offset_minutes", integer), ("window_start", timestamp),
        ("window_end", timestamp), ("assumption_note", string),
    ]])
    interval_schema = StructType([StructField(name, kind, True) for name, kind in [
        ("scenario_id", string), ("interval_id", string), ("interval_start", timestamp),
        ("interval_end", timestamp), ("state", string), ("sku", string), ("sku_cu", integer),
        ("state_basis", string), ("sku_basis", string), ("source_event_id", string),
    ]])
    consumption_schema = StructType([StructField(name, kind, True) for name, kind in [
        ("scenario_id", string), ("use_case_name", string), ("root_domain_name", string),
        ("subdomain_name", string), ("observed_total_cus", DoubleType()),
        ("missing_cu_value_count", integer), ("expected_available_cus", DoubleType()),
        ("expected_capacity_percentage", DoubleType()),
    ]])
    for table, rows, schema in [
        ("capacity_demo_periods", demo_periods, period_schema),
        ("capacity_demo_intervals", demo_intervals, interval_schema),
        ("capacity_demo_consumption", consumption, consumption_schema),
        ("capacity_estimate_periods", estimate_periods, period_schema),
        ("capacity_estimate_intervals", estimate_intervals, interval_schema),
    ]:
        target = "dbo." + table
        if spark.catalog.tableExists(target):
            print(f"Preserved existing scenario table: {target}")
        else:
            spark.createDataFrame(rows, schema).write.format("delta").mode(
                "errorifexists"
            ).saveAsTable(target)
            if spark.table(target).count() != len(rows):
                raise RuntimeError(f"Scenario table verification failed: {target}")
    print("Demo/estimate sources initialized; existing scenario and real history tables unchanged.")

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}

# CELL ********************
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    initialize_scenarios(SparkSession.builder.getOrCreate(), initial_estimates_json)

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}
