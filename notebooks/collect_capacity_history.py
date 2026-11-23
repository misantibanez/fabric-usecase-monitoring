# Fabric notebook source

# METADATA ********************
# META {
# META   "kernel_info": {"name": "synapse_pyspark"},
# META   "dependencies": {"lakehouse": {}}
# META }

# PARAMETERS CELL ********************
metric_workspace = ""
metric_dataset = ""
capacity_id = ""
history_window_days = 14

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}

# CELL ********************
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from urllib.parse import quote
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def canonical_id(value: str) -> str:
    return str(UUID(value)).upper()


def required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid {field}")
    return value.strip()


def source_timezone(offset_minutes: int) -> timezone:
    if type(offset_minutes) is not int or not -720 <= offset_minutes <= 840:
        raise ValueError("Source UTC offset must be whole minutes between -12 and +14 hours")
    return timezone(timedelta(minutes=offset_minutes))


def utc_offset_minutes(value: object) -> int:
    text = required_text(value, "UTC_offset")
    try:
        hours = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("UTC_offset must be numeric") from error
    if not hours.is_finite() or not Decimal(-12) <= hours <= Decimal(14):
        raise ValueError("UTC_offset must be between -12 and +14 hours")
    minutes = hours * 60
    if not minutes.is_finite() or minutes != minutes.to_integral_value():
        raise ValueError("UTC_offset must represent whole minutes")
    offset = int(minutes)
    source_timezone(offset)
    return offset


def utc_time(value: object, source_offset_minutes: int = 0) -> datetime:
    zone = source_timezone(source_offset_minutes)
    text = required_text(value, "timestamp")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc)


def decode_query_response(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Invalid or failed executeQueries response")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError("Expected exactly one query result")
    result = results[0]
    if not isinstance(result, dict) or result.get("error"):
        raise ValueError("Query returned an error or partial result")
    tables = result.get("tables")
    if not isinstance(tables, list) or len(tables) != 1:
        raise ValueError("Expected exactly one result table")
    table = tables[0]
    if not isinstance(table, dict):
        raise ValueError("Invalid result table")
    rows = table.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("Invalid result rows")
    decoded: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid result row")
        clean: dict[str, object] = {}
        for name, value in row.items():
            if not isinstance(name, str) or not name.startswith("[") or not name.endswith("]"):
                raise ValueError("Expected explicitly aliased query columns")
            clean[name[1:-1]] = value
        decoded.append(clean)
    return decoded


def select_capacity(rows: object, selected_id: str) -> dict[str, str]:
    selected_id = canonical_id(selected_id)
    if not isinstance(rows, list):
        raise ValueError("Invalid capacity list")
    matches: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid capacity record")
        identifier = canonical_id(required_text(row.get("id"), "capacity ID"))
        if identifier == selected_id:
            matches.append({
                "capacity_id": identifier,
                "state": required_text(row.get("state"), "capacity state"),
                "sku": required_text(row.get("sku"), "capacity SKU"),
            })
    if len(matches) != 1:
        raise ValueError("Selected capacity is missing, inaccessible or duplicated")
    return matches[0]


def dax_time(value: datetime) -> str:
    if value.tzinfo is None or value.microsecond:
        raise ValueError("Query boundaries must be timezone-aware whole seconds")
    value = value.astimezone(timezone.utc)
    return (
        f"DATE({value.year},{value.month},{value.day})"
        f"+TIME({value.hour},{value.minute},{value.second})"
    )


def events_query(
    selected_id: str, start: datetime, end: datetime, source_offset_minutes: int = 0,
) -> str:
    selected_id = canonical_id(selected_id).lower()
    if start >= end:
        raise ValueError("Event query window must have positive duration")
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Event query boundaries must be timezone-aware")
    zone = source_timezone(source_offset_minutes)
    # DAX literals use report wall time, while the ledger retains UTC boundaries.
    source_start = start.astimezone(zone).replace(tzinfo=timezone.utc)
    source_end = end.astimezone(zone).replace(tzinfo=timezone.utc)
    return f"""
DEFINE MPARAMETER 'CapacitiesList' = {{"{selected_id}"}}
EVALUATE SELECTCOLUMNS(
    TOPN(10001,
        FILTER('System Events',
            'System Events'[Capacity Id] = "{selected_id}"
            && 'System Events'[Capacity state transition time] >= {dax_time(source_start)}
            && 'System Events'[Capacity state transition time] < {dax_time(source_end)}),
        'System Events'[Capacity state transition time], ASC),
    "CapacityId", 'System Events'[Capacity Id],
    "State", 'System Events'[Capacity state],
    "Reason", 'System Events'[Capacity state change reason],
    "ActivationId", 'System Events'[Capacity activation Id],
    "EventTime", 'System Events'[Capacity state transition time])
"""


def normalize_events(
    rows: list[dict[str, object]],
    selected_id: str,
    start: datetime,
    end: datetime,
    run_id: str,
    observed_at: datetime,
    source_offset_minutes: int = 0,
) -> list[dict[str, object]]:
    selected_id = canonical_id(selected_id)
    source_timezone(source_offset_minutes)
    if len(rows) > 10000:
        raise ValueError("Event limit reached; completeness is not established")
    effects = {
        ("Active", "Created"): "ACTIVE",
        ("Active", "ManuallyResumed"): "ACTIVE",
        ("Suspended", "ManuallyPaused"): "INACTIVE",
        ("Deleted", "Deleted"): "INACTIVE",
    }
    events: dict[str, dict[str, object]] = {}
    for row in rows:
        identifier = canonical_id(required_text(row.get("CapacityId"), "event capacity"))
        event_time = utc_time(row.get("EventTime"), source_offset_minutes)
        if identifier != selected_id or not start <= event_time < end:
            raise ValueError("Event lies outside the requested capacity/window")
        state = required_text(row.get("State"), "event state")
        reason = required_text(row.get("Reason"), "event reason")
        activation = row.get("ActivationId")
        if activation is not None:
            activation = required_text(activation, "activation ID")
        identity = json.dumps(
            [identifier, event_time.isoformat(), state, reason, activation],
            separators=(",", ":"),
        )
        event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        events[event_id] = {
            "event_id": event_id,
            "capacity_id": identifier,
            "event_time": event_time,
            "state": state,
            "reason": reason,
            "activation_id": activation,
            "availability_effect": effects.get((state, reason)),
            "first_observed_at": observed_at,
            "first_observed_run_id": run_id,
            "source_event_time": required_text(row.get("EventTime"), "event timestamp"),
            "source_utc_offset_minutes": source_offset_minutes,
        }
    return list(events.values())


def run_capacity_history(
    spark: "SparkSession",
    source_workspace: str,
    source_model: str,
    selected_id: str,
    window_days: int,
) -> None:
    import sempy.fabric as fabric
    from delta.tables import DeltaTable
    from pyspark.sql.types import (
        DataType, IntegerType, StringType, StructField, StructType, TimestampType,
    )

    source_workspace = canonical_id(source_workspace)
    source_model = canonical_id(source_model)
    selected_id = canonical_id(selected_id)
    if type(window_days) is not int or not 1 <= window_days <= 14:
        raise ValueError("history_window_days must be an integer from 1 to 14")
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    run_id = str(uuid4())
    started = datetime.now(timezone.utc).replace(microsecond=0)
    start = started - timedelta(days=window_days)
    string = StringType()
    timestamp = TimestampType()
    integer = IntegerType()

    def schema(fields: list[tuple[str, DataType]]) -> StructType:
        return StructType([StructField(name, kind, True) for name, kind in fields])

    run_schema = schema([
        ("run_id", string), ("capacity_id", string), ("status", string),
        ("started_at", timestamp), ("completed_at", timestamp),
        ("window_start", timestamp), ("window_end", timestamp),
        ("source_workspace_id", string), ("source_model_id", string),
        ("source_calendar_max", timestamp), ("snapshot_count", integer),
        ("event_count", integer), ("failure_stage", string), ("error_type", string),
        ("source_utc_offset_minutes", integer),
    ])
    snapshot_schema = schema([
        ("snapshot_id", string), ("run_id", string), ("capacity_id", string),
        ("observed_at", timestamp), ("state", string), ("sku", string),
    ])
    event_schema = schema([
        ("event_id", string), ("capacity_id", string), ("event_time", timestamp),
        ("state", string), ("reason", string), ("activation_id", string),
        ("availability_effect", string), ("first_observed_at", timestamp),
        ("first_observed_run_id", string),
        ("source_event_time", string), ("source_utc_offset_minutes", integer),
    ])
    run: dict[str, object] = {
        "run_id": run_id, "capacity_id": selected_id, "status": "Running",
        "started_at": started, "completed_at": None,
        "window_start": start, "window_end": started,
        "source_workspace_id": source_workspace, "source_model_id": source_model,
        "source_calendar_max": None, "snapshot_count": 0, "event_count": 0,
        "failure_stage": None, "error_type": None,
        "source_utc_offset_minutes": None,
    }

    def persist(
        table: str, rows: list[dict[str, object]], table_schema: StructType,
        key: str, update: bool = False,
    ) -> None:
        data = spark.createDataFrame(rows, schema=table_schema)
        if not spark.catalog.tableExists(table):
            data.write.format("delta").mode("errorifexists").saveAsTable(table)
        else:
            if set(table_schema.fieldNames()) - set(spark.table(table).columns):
                data.limit(0).write.format("delta").option("mergeSchema", "true").mode(
                    "append"
                ).saveAsTable(table)
            if rows:
                merge = (
                    DeltaTable.forName(spark, table).alias("t")
                    .merge(data.alias("s"), f"t.{key} = s.{key}")
                )
                if update:
                    merge = merge.whenMatchedUpdateAll()
                merge.whenNotMatchedInsertAll().execute()

    runs_table = "dbo.capacity_collection_runs"
    snapshots_table = "dbo.capacity_state_snapshots"
    events_table = "dbo.capacity_system_events"
    persist(runs_table, [run], run_schema, "run_id", update=True)
    stage = "capacity_metadata"
    try:
        client = fabric.FabricRestClient()
        capacities: list[object] = []
        path = "/v1/capacities"
        seen_tokens: set[str] = set()
        while True:
            response = client.get(path)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                raise ValueError("Invalid paginated capacity response")
            capacities.extend(payload["value"])
            token = payload.get("continuationToken")
            if token is None:
                break
            token = required_text(token, "continuation token")
            if token in seen_tokens:
                raise ValueError("Repeated capacity continuation token")
            seen_tokens.add(token)
            path = "/v1/capacities?continuationToken=" + quote(token, safe="")
        capacity = select_capacity(capacities, selected_id)
        observed_at = datetime.now(timezone.utc)
        powerbi = fabric.PowerBIRestClient()
        endpoint = (
            f"https://api.powerbi.com/v1.0/myorg/groups/{source_workspace}"
            f"/datasets/{source_model}/executeQueries"
        )
        stage = "source_parameters"
        parameters_response = powerbi.get(endpoint.rsplit("/", 1)[0] + "/parameters")
        parameters_response.raise_for_status()
        parameters = parameters_response.json()
        if not isinstance(parameters, dict) or not isinstance(parameters.get("value"), list):
            raise ValueError("Invalid source model parameter response")
        offsets = [
            parameter.get("currentValue") for parameter in parameters["value"]
            if isinstance(parameter, dict) and parameter.get("name") == "UTC_offset"
        ]
        if len(offsets) != 1:
            raise ValueError("Source model must expose exactly one UTC_offset parameter")
        source_offset = utc_offset_minutes(offsets[0])
        run["source_utc_offset_minutes"] = source_offset

        def query(dax: str) -> list[dict[str, object]]:
            response = powerbi.post(
                endpoint,
                json={"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}},
            )
            response.raise_for_status()
            return decode_query_response(response.json())

        stage = "source_calendar"
        health = query(
            f'''EVALUATE ROW("CalendarMax", MAX('Dates'[Date]),
            "CapacityMatches", CALCULATE(COUNTROWS('Capacities'),
                TREATAS({{"{selected_id}"}}, 'Capacities'[Capacity Id])))'''
        )
        if len(health) != 1 or health[0].get("CapacityMatches") != 1:
            raise ValueError("Source model does not uniquely contain the selected capacity")
        run["source_calendar_max"] = utc_time(health[0].get("CalendarMax"))
        stage = "system_events"
        events = normalize_events(
            query(events_query(selected_id, start, started, source_offset)),
            selected_id, start, started, run_id, datetime.now(timezone.utc),
            source_offset,
        )
        stage = "persist_history"
        snapshot = {
            "snapshot_id": run_id + ":" + selected_id,
            "run_id": run_id, "observed_at": observed_at, **capacity,
        }
        persist(snapshots_table, [snapshot], snapshot_schema, "snapshot_id")
        persist(events_table, events, event_schema, "event_id")
        run.update(
            status="Succeeded", completed_at=datetime.now(timezone.utc),
            snapshot_count=1, event_count=len(events),
        )
        stage = "finalize_run"
        persist(runs_table, [run], run_schema, "run_id", update=True)
        saved = spark.table(runs_table).where(f"run_id = '{run_id}'").collect()
        if len(saved) != 1 or saved[0]["status"] != "Succeeded":
            raise RuntimeError("Persisted run status verification failed")
        if spark.table(snapshots_table).where(f"run_id = '{run_id}'").count() != 1:
            raise RuntimeError("Persisted snapshot verification failed")
        print(f"Capacity history collection succeeded. Run ID: {run_id}")
    except Exception as error:
        run.update(
            status="Failed", completed_at=datetime.now(timezone.utc),
            failure_stage=stage, error_type=type(error).__name__,
        )
        persist(runs_table, [run], run_schema, "run_id", update=True)
        raise

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}

# CELL ********************
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    run_capacity_history(
        SparkSession.builder.getOrCreate(),
        metric_workspace, metric_dataset, capacity_id, history_window_days,
    )

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}
