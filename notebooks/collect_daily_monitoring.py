# Fabric notebook source

# METADATA ********************
# META {"kernel_info": {"name": "synapse_pyspark"}, "dependencies": {"lakehouse": {}}}

# PARAMETERS CELL ********************
source_metrics_path = ""
daily_policies_json = "[]"

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}

# CELL ********************
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID


def daily_policies(rows: object) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("daily_policies must be a nonempty list")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"capacity_id", "sku", "source_utc_offset_minutes"}:
            raise ValueError("Each daily policy requires capacity_id, sku and source_utc_offset_minutes")
        capacity = str(UUID(row["capacity_id"])).upper()
        offset = row["source_utc_offset_minutes"]
        if UUID(capacity).int == 0 or capacity in seen:
            raise ValueError("Invalid or duplicate daily policy capacity")
        if row["sku"] != "F8":
            raise ValueError("The daily estimate policy currently supports only explicitly assumed F8 active 24h")
        if type(offset) is not int or not -720 <= offset <= 840:
            raise ValueError("Invalid source UTC offset in daily policy")
        seen.add(capacity)
        result.append({**row, "capacity_id": capacity})
    return result


def report_yesterday(now: datetime, offset: int) -> date:
    if now.tzinfo is None:
        raise ValueError("Daily processing requires an aware UTC clock")
    return now.astimezone(timezone(timedelta(minutes=offset))).date() - timedelta(days=1)


def pending_days(first: date, last: date, completed: dict[date, str]) -> list[date]:
    if first > last:
        raise ValueError("Daily processing clock precedes the installation start")
    return [
        day for index in range((last - first).days + 1)
        if (day := first + timedelta(days=index)) not in completed
        or completed[day] != "SourceRowsObserved"
        or day >= last - timedelta(days=2)
    ]


def assumed_day(policy: dict, day: date) -> tuple[dict, dict]:
    start = datetime.combine(
        day, time.min, timezone(timedelta(minutes=policy["source_utc_offset_minutes"])),
    ).astimezone(timezone.utc).replace(tzinfo=None)
    end = start + timedelta(days=1)
    scenario = f"DailyAssumedF8_{policy['capacity_id']}_{day.isoformat()}"
    period = {
        "scenario_id": scenario, "capacity_id": policy["capacity_id"], "metric_date": day,
        "source_utc_offset_minutes": policy["source_utc_offset_minutes"],
        "window_start": start, "window_end": end,
        "assumption_note": "F8 active 24h assumed by explicit daily policy; NOT FOR BILLING.",
    }
    interval = {
        "scenario_id": scenario, "interval_id": scenario + ":0",
        "interval_start": start, "interval_end": end, "state": "Active",
        "sku": "F8", "sku_cu": 8, "state_basis": "Continuous activity assumed; not certified.",
        "sku_basis": "Constant F8 assumed; not certified.", "source_event_id": None,
    }
    return period, interval


def check_daily_totals(expected: dict, actual: dict) -> None:
    if set(expected) != set(actual):
        raise RuntimeError("Archived metric dates differ from available source dates")
    for day, left in expected.items():
        right = actual[day]
        if left["rows"] != right["rows"] or left["null_cus"] != right["null_cus"]:
            raise RuntimeError("Archived row/null quantity counts differ from source")
        a, b = left["cus"], right["cus"]
        if (a is None) != (b is None) or (
            a is not None and not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8)
        ):
            raise RuntimeError("Archived CU seconds differ from source")


def collect_daily(spark, source_path: str, policies_json: str) -> None:
    from delta.tables import DeltaTable
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        DateType, DoubleType, IntegerType, LongType, StringType,
        StructField, StructType, TimestampType,
    )

    policies = daily_policies(json.loads(policies_json))
    if not source_path.startswith("abfss://") or not source_path.endswith("/capacity_metrics_by_item_by_operation_by_day"):
        raise ValueError("Expected the discovered FUAM Delta metric source path")
    now = datetime.now(timezone.utc)
    stamp = now.replace(tzinfo=None)
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    metrics_table = "dbo.monitoring_daily_metrics"
    coverage_table = "dbo.monitoring_daily_periods"
    state_table = "dbo.monitoring_daily_state"
    metrics_schema = StructType([StructField(name, kind, True) for name, kind in [
        ("CapacityId", StringType()), ("WorkspaceId", StringType()), ("ItemId", StringType()),
        ("Date", DateType()), ("ItemKind", StringType()), ("OperationName", StringType()),
        ("TotalCUs", DoubleType()), ("OperationCount", DoubleType()),
    ]])
    coverage_schema = StructType([StructField(name, kind, True) for name, kind in [
        ("capacity_id", StringType()), ("metric_date", DateType()), ("source_status", StringType()),
        ("metric_rows", LongType()), ("observed_cus", DoubleType()), ("missing_cu_values", LongType()),
        ("processed_at", TimestampType()),
    ]])
    state_schema = StructType([StructField(name, kind, True) for name, kind in [
        ("capacity_id", StringType()), ("first_day", DateType()), ("window_start_day", DateType()),
        ("window_end_day", DateType()), ("last_completed_day", DateType()),
        ("sku", StringType()), ("source_utc_offset_minutes", IntegerType()),
    ]])
    for table, schema in (
        (metrics_table, metrics_schema), (coverage_table, coverage_schema), (state_table, state_schema),
    ):
        if not spark.catalog.tableExists(table):
            writer = spark.createDataFrame([], schema).write.format("delta").mode("errorifexists")
            if table == metrics_table:
                writer = writer.partitionBy("CapacityId", "Date")
            writer.saveAsTable(table)

    def merge_rows(table, rows, schema, keys, update=True):
        incoming = spark.createDataFrame(rows, schema)
        predicate = " AND ".join(f"t.`{key}` = s.`{key}`" for key in keys)
        merge = DeltaTable.forName(spark, table).alias("t").merge(incoming.alias("s"), predicate)
        if update:
            merge = merge.whenMatchedUpdateAll()
        merge.whenNotMatchedInsertAll().execute()

    def statistics(frame):
        rows = frame.groupBy("Date").agg(
            F.count("*").alias("rows"), F.sum("TotalCUs").alias("cus"),
            F.sum(F.when(F.col("TotalCUs").isNull(), 1).otherwise(0)).alias("null_cus"),
        ).collect()
        return {row["Date"]: row.asDict() for row in rows}

    raw = spark.read.format("delta").load(source_path)
    source = raw.select(*[
        F.col(field.name).cast(field.dataType).alias(field.name) for field in metrics_schema
    ]).withColumn("CapacityId", F.upper(F.trim(F.col("CapacityId"))))
    for policy in policies:
        cap = policy["capacity_id"]
        monitored = raw.where(F.upper(F.trim(F.col("CapacityId"))) == cap)
        for column in ("TotalCUs", "OperationCount"):
            if monitored.where(F.col(column).isNotNull() & F.col(column).cast("double").isNull()).take(1):
                raise RuntimeError(f"FUAM contains an invalid numeric metric: {column}")
        last = report_yesterday(now, policy["source_utc_offset_minutes"])
        stored = [row.asDict() for row in spark.table(state_table).where(F.col("capacity_id") == cap).collect()]
        if len(stored) > 1:
            raise RuntimeError("Duplicate daily state capacity")
        if stored:
            state = stored[0]
            if state["sku"] != policy["sku"] or state["source_utc_offset_minutes"] != policy["source_utc_offset_minutes"]:
                raise RuntimeError("Installed daily policy changed; explicit upgrade required")
            first = state["first_day"]
            if state["last_completed_day"] is not None and last < state["last_completed_day"]:
                raise RuntimeError("Daily processing clock moved behind the last completed scan")
        else:
            first = last - timedelta(days=29)
            state = {
                **policy, "first_day": first, "window_start_day": first,
                "window_end_day": last, "last_completed_day": None,
            }
            merge_rows(state_table, [state], state_schema, ["capacity_id"], update=False)
        ledger = spark.table(coverage_table).where(F.col("capacity_id") == cap).collect()
        if len({row["metric_date"] for row in ledger}) != len(ledger):
            raise RuntimeError("Duplicate daily coverage keys")
        days = pending_days(first, last, {row["metric_date"]: row["source_status"] for row in ledger})
        if source.where((F.col("CapacityId") == cap) & F.col("Date").isNull()).take(1):
            raise RuntimeError("FUAM contains a monitored metric with an invalid date")
        selected = source.where((F.col("CapacityId") == cap) & F.col("Date").isin(days)).cache()
        try:
            expected = statistics(selected)
            if expected:
                dates = ",".join(f"DATE '{day.isoformat()}'" for day in sorted(expected))
                predicate = f"CapacityId = '{cap}' AND Date IN ({dates})"
                selected.write.format("delta").mode("overwrite").option(
                    "replaceWhere", predicate,
                ).saveAsTable(metrics_table)
                archived = spark.table(metrics_table).where(
                    (F.col("CapacityId") == cap) & F.col("Date").isin(list(expected)),
                )
                check_daily_totals(expected, statistics(archived))
            retained = statistics(spark.table(metrics_table).where(
                (F.col("CapacityId") == cap) & F.col("Date").isin(days),
            ))
            periods, intervals = [], []
            for day in days:
                period, interval = assumed_day(policy, day)
                periods.append(period)
                intervals.append(interval)
            # Never overwrite independently approved assumptions.
            for table, records, keys in (
                ("dbo.capacity_estimate_intervals", intervals, ["scenario_id", "interval_id"]),
                ("dbo.capacity_estimate_periods", periods, ["capacity_id", "metric_date"]),
            ):
                existing = spark.table(table)
                stored_rows = existing.collect()
                index = {tuple(row[key] for key in keys): row.asDict() for row in stored_rows}
                if len(index) != len(stored_rows):
                    raise RuntimeError("Duplicate stored availability assumption keys")
                for row in records:
                    old = index.get(tuple(row[key] for key in keys))
                    if old is not None and any(old[key] != value for key, value in row.items()):
                        raise RuntimeError("Daily policy conflicts with existing availability assumptions")
                merge_rows(table, records, existing.schema, keys, update=False)
            outcomes = []
            for day in days:
                stats = retained.get(day)
                outcomes.append({
                    "capacity_id": cap, "metric_date": day,
                    "source_status": (
                        "SourceRowsObserved" if day in expected else
                        "RetainedArchiveSourceUnavailable" if stats else "MissingSourceDay"
                    ),
                    "metric_rows": stats["rows"] if stats else None,
                    "observed_cus": stats["cus"] if stats else None,
                    "missing_cu_values": stats["null_cus"] if stats else None,
                    "processed_at": stamp,
                })
            merge_rows(coverage_table, outcomes, coverage_schema, ["capacity_id", "metric_date"])
            state.update(window_start_day=last - timedelta(days=29), window_end_day=last, last_completed_day=last)
            merge_rows(state_table, [state], state_schema, ["capacity_id"])
            missing = sum(row["source_status"] == "MissingSourceDay" for row in outcomes)
            print(f"Daily scan complete through {last}: {len(days)} dates checked; {missing} missing source dates. NOT FOR BILLING.")
        finally:
            selected.unpersist()

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}

# CELL ********************
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    collect_daily(SparkSession.builder.getOrCreate(), source_metrics_path, daily_policies_json)

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}
