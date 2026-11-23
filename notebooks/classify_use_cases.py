# Fabric notebook source

# METADATA ********************
# META {
# META   "kernel_info": {"name": "synapse_pyspark"},
# META   "dependencies": {"lakehouse": {}}
# META }

# PARAMETERS CELL ********************
source_workspace_id = ""
source_lakehouse_id = ""
source_table_schema = ""
initial_use_cases_json = "[]"

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}

# CELL ********************
import json
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def identifier(value: object) -> str:
    if not isinstance(value, str) or len(value.strip()) != 36:
        raise ValueError("Expected a UUID identifier")
    parsed = UUID(value.strip())
    if parsed.int == 0:
        raise ValueError("All-zero identifiers are not valid assignments")
    return str(parsed).upper()


def validate_catalog(
    rows: list[dict[str, object]], tags: dict[str, str],
) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    case_ids: set[str] = set()
    enabled_tags: set[str] = set()
    for row in rows:
        case_id = identifier(row.get("use_case_id"))
        tag_id = identifier(row.get("tag_id"))
        name = row.get("use_case_name")
        enabled = row.get("is_enabled")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Use-case name is required")
        if type(enabled) is not bool:
            raise ValueError("is_enabled must be a Boolean")
        if case_id in case_ids:
            raise ValueError("Duplicate use_case_id")
        case_ids.add(case_id)
        if enabled:
            if tags.get(tag_id) != "Domain":
                raise ValueError("Enabled use cases must reference an existing Domain tag ID")
            if tag_id in enabled_tags:
                raise ValueError("An enabled tag cannot belong to multiple use cases")
            enabled_tags.add(tag_id)
        cases.append({
            "use_case_id": case_id, "use_case_name": name.strip(),
            "tag_id": tag_id, "is_enabled": enabled,
        })
    return cases


def classify_workspace(
    workspace_exists: bool,
    tag_ids: list[str],
    enabled_cases: dict[str, dict[str, object]],
) -> dict[str, object]:
    if not workspace_exists:
        return {
            "classification_status": "MissingWorkspace", "matched_case_count": 0,
            "use_case_id": None, "use_case_name": None,
        }
    matches = {
        str(enabled_cases[tag]["use_case_id"]): enabled_cases[tag]
        for tag in {identifier(value) for value in tag_ids}
        if tag in enabled_cases
    }
    case = next(iter(matches.values())) if len(matches) == 1 else None
    return {
        "classification_status": (
            "Assigned" if case else "Ambiguous" if matches else "Unclassified"
        ),
        "matched_case_count": len(matches),
        "use_case_id": case["use_case_id"] if case else None,
        "use_case_name": case["use_case_name"] if case else None,
    }


def build_domain_index(
    rows: list[dict[str, object]],
) -> dict[str, tuple[str, str | None]]:
    domains: dict[str, tuple[str, str | None]] = {}
    for row in rows:
        key = identifier(row["DomainId"])
        name = row["OriginalDomainName"]
        parent = row["OriginalParentDomainId"]
        if key in domains:
            raise ValueError("Duplicate source domain ID")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Source domain name is required")
        parent_id = (
            None if parent is None or (isinstance(parent, str) and not parent.strip())
            else identifier(parent)
        )
        domains[key] = (name, parent_id)
    return domains


def resolve_domain(
    domain_id: str | None, domains: dict[str, tuple[str, str | None]],
    workspace_exists: bool = True,
) -> dict[str, object]:
    result: dict[str, object] = {
        "root_domain_id": None, "root_domain_name": None,
        "subdomain_id": None, "subdomain_name": None,
        "domain_path_ids": None, "hierarchy_depth": None,
        "domain_resolution_status": "MissingWorkspace",
    }
    if not workspace_exists:
        return result
    if domain_id is None:
        result["domain_resolution_status"] = "NoDomain"
        return result
    key = identifier(domain_id)
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = key
    while current is not None:
        if current in seen:
            result["domain_resolution_status"] = "HierarchyCycle"
            return result
        if current not in domains:
            result["domain_resolution_status"] = (
                "DomainNotFound" if not chain else "ParentDomainNotFound"
            )
            return result
        seen.add(current)
        chain.append(current)
        current = domains[current][1]
    root = chain[-1]
    result.update(
        root_domain_id=root, root_domain_name=domains[root][0],
        subdomain_id=key if len(chain) > 1 else None,
        subdomain_name=domains[key][0] if len(chain) > 1 else None,
        domain_path_ids=json.dumps(list(reversed(chain))),
        hierarchy_depth=len(chain) - 1, domain_resolution_status="Resolved",
    )
    return result


def inherit_item_inventory(
    items: list[dict[str, object]], snapshots: list[dict[str, object]],
) -> list[dict[str, object]]:
    workspaces: dict[str, dict[str, object]] = {}
    for snapshot in snapshots:
        key = identifier(snapshot["workspace_id"])
        if key in workspaces:
            raise ValueError("Duplicate workspace classification observation")
        workspaces[key] = snapshot
    result: list[dict[str, object]] = []
    item_ids: set[str] = set()
    for item in items:
        item_id = identifier(item["id"])
        workspace_id = identifier(item["workspaceId"])
        if item_id in item_ids:
            raise ValueError("Duplicate source item ID")
        item_ids.add(item_id)
        if workspace_id not in workspaces:
            raise ValueError("Inventory workspace has no classification observation")
        workspace = workspaces[workspace_id]
        item_type = item["type"]
        if not isinstance(item_type, str) or not item_type.strip():
            raise ValueError("Source item type is required")
        raw_capacity = item["capacityId"]
        item_capacity = (
            None if raw_capacity is None or raw_capacity == ""
            else identifier(raw_capacity)
        )
        workspace_capacity = workspace["capacity_id"]
        result.append({
            **workspace,
            "item_id": item_id, "item_name": item["name"], "item_type": item_type,
            "item_state": item["state"], "item_capacity_id": item_capacity,
            "item_deleted_flag": item["fuam_deleted"],
            "item_source_modified_at": item["fuam_modified_at"],
            "capacity_join_status": (
                "MissingWorkspace" if workspace["classification_status"] == "MissingWorkspace"
                else "ItemCapacityMissing" if item_capacity is None
                else "WorkspaceCapacityMissing" if workspace_capacity is None
                else "CurrentCapacityMatched" if item_capacity == workspace_capacity
                else "CurrentCapacityMismatch"
            ),
        })
    return result


def collect_classification(
    spark: "SparkSession", workspace_id: str, lakehouse_id: str, initial_json: str,
    source_schema: str = "",
) -> None:
    import notebookutils
    from pyspark.sql.types import (
        BooleanType, IntegerType, StringType, StructField, StructType, TimestampType,
    )

    workspace_id = identifier(workspace_id).lower()
    lakehouse_id = identifier(lakehouse_id).lower()
    initial = json.loads(initial_json)
    if not isinstance(initial, list) or any(not isinstance(row, dict) for row in initial):
        raise ValueError("initial_use_cases_json must be an array of case records")
    endpoint = notebookutils.conf.get("fs.defaultFS").split("@")[1].rstrip("/")
    root = f"abfss://{workspace_id}@{endpoint}/{lakehouse_id}/Tables"
    if source_schema:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", source_schema):
            raise ValueError("Invalid source Lakehouse schema")
        root += "/" + source_schema
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    run_id = str(uuid4())
    observed = datetime.now(timezone.utc)
    string, timestamp = StringType(), TimestampType()
    catalog_schema = StructType([
        StructField("use_case_id", string, False),
        StructField("use_case_name", string, False),
        StructField("tag_id", string, False),
        StructField("is_enabled", BooleanType(), False),
    ])
    hierarchy_fields = [
        StructField("root_domain_id", string, True),
        StructField("root_domain_name", string, True),
        StructField("subdomain_id", string, True),
        StructField("subdomain_name", string, True),
        StructField("domain_path_ids", string, True),
        StructField("hierarchy_depth", IntegerType(), True),
        StructField("domain_resolution_status", string, False),
    ]
    snapshot_schema = StructType([
        StructField("run_id", string, False),
        StructField("observed_at", timestamp, False),
        StructField("workspace_id", string, False),
        StructField("capacity_id", string, True),
        StructField("domain_id", string, True),
        StructField("workspace_deleted_flag", BooleanType(), True),
        StructField("source_modified_at", timestamp, True),
        StructField("classification_status", string, False),
        StructField("matched_case_count", IntegerType(), False),
        StructField("use_case_id", string, True),
        StructField("use_case_name", string, True),
    ] + hierarchy_fields)
    run_schema = StructType([
        StructField("run_id", string, False),
        StructField("started_at", timestamp, False),
        StructField("completed_at", timestamp, True),
        StructField("status", string, False),
        StructField("error_type", string, True),
        StructField("error_message", string, True),
        StructField("inventory_snapshot_count", IntegerType(), True),
        StructField("domain_snapshot_count", IntegerType(), True),
    ])
    run = {
        "run_id": run_id, "started_at": observed, "completed_at": None,
        "status": "Running", "error_type": None, "error_message": None,
        "inventory_snapshot_count": None, "domain_snapshot_count": None,
    }
    runs_table = "dbo.classification_runs"
    catalog_table = "dbo.use_cases"
    snapshot_table = "dbo.workspace_use_case_snapshots"
    catalog_snapshot_table = "dbo.use_case_catalog_snapshots"
    spark.createDataFrame([run], run_schema).write.format("delta").option(
        "mergeSchema", "true"
    ).mode("append").saveAsTable(
        runs_table
    )

    def finalize(
        status: str, error_type: str | None = None, error_message: str | None = None,
    ) -> None:
        from delta.tables import DeltaTable

        run.update(
            status=status, completed_at=datetime.now(timezone.utc),
            error_type=error_type, error_message=error_message,
        )
        DeltaTable.forName(spark, runs_table).alias("t").merge(
            spark.createDataFrame([run], run_schema).alias("s"), "t.run_id = s.run_id"
        ).whenMatchedUpdateAll().execute()

    try:
        tag_rows = spark.read.format("delta").load(root + "/tags").select(
            "tagId", "scope"
        ).collect()
        tags: dict[str, str] = {}
        for row in tag_rows:
            tag_id = identifier(row["tagId"])
            if tag_id in tags:
                raise ValueError("Duplicate source tag ID")
            tags[tag_id] = row["scope"]
        # Seeds are inserted only when the editable catalog does not yet exist.
        if not spark.catalog.tableExists(catalog_table):
            initial = validate_catalog(initial, tags)
            spark.createDataFrame(initial, catalog_schema).write.format("delta").mode(
                "errorifexists"
            ).saveAsTable(catalog_table)
        elif initial:
            raise ValueError("Catalog already exists; edit its rows explicitly, do not reseed")
        catalog = validate_catalog(
            [row.asDict() for row in spark.table(catalog_table).collect()], tags
        )
        enabled = {
            str(case["tag_id"]): case for case in catalog if case["is_enabled"]
        }
        domains = build_domain_index([
            row.asDict()
            for row in spark.read.format("delta").load(root + "/domains_flatten").select(
                "DomainId", "OriginalDomainName", "OriginalParentDomainId",
            ).collect()
        ])
        domain_schema = StructType([
            StructField("run_id", string, False),
            StructField("observed_at", timestamp, False),
            StructField("domain_id", string, False),
            StructField("domain_name", string, False),
            StructField("parent_domain_id", string, True),
        ] + hierarchy_fields)
        domain_snapshots = [
            {
                "run_id": run_id, "observed_at": observed, "domain_id": key,
                "domain_name": name, "parent_domain_id": parent,
                **resolve_domain(key, domains),
            }
            for key, (name, parent) in sorted(domains.items())
        ]
        domain_table = "dbo.domain_hierarchy_snapshots"
        run["domain_snapshot_count"] = len(domain_snapshots)
        spark.createDataFrame(domain_snapshots, domain_schema).write.format("delta").mode(
            "append"
        ).saveAsTable(domain_table)
        workspaces: dict[str, dict[str, object]] = {}
        for row in spark.read.format("delta").load(root + "/workspaces").select(
            "WorkspaceId", "CapacityId", "DomainId", "fuam_deleted", "fuam_modified_at"
        ).collect():
            key = identifier(row["WorkspaceId"])
            if key in workspaces:
                raise ValueError("Duplicate source workspace ID")
            workspaces[key] = row.asDict()
        associations: dict[str, list[str]] = {}
        for row in spark.read.format("delta").load(root + "/workspace_tags").select(
            "WorkspaceId", "tagId"
        ).collect():
            key, tag = identifier(row["WorkspaceId"]), identifier(row["tagId"])
            if tag not in tags:
                raise ValueError("Workspace association references a missing tag")
            associations.setdefault(key, []).append(tag)
        inventory = [
            row.asDict()
            for row in spark.read.format("delta").load(root + "/active_items").select(
                "id", "workspaceId", "name", "type", "state", "capacityId",
                "fuam_deleted", "fuam_modified_at",
            ).collect()
        ]
        inventory_keys = {identifier(row["workspaceId"]) for row in inventory}
        snapshots: list[dict[str, object]] = []
        for key in sorted(set(workspaces) | inventory_keys | set(associations)):
            workspace = workspaces.get(key)
            def optional_id(field: str) -> str | None:
                value = workspace[field] if workspace else None
                if value is None or (isinstance(value, str) and not value.strip()):
                    return None
                return identifier(value)

            domain_id = optional_id("DomainId")
            snapshots.append({
                "run_id": run_id, "observed_at": observed, "workspace_id": key,
                "capacity_id": optional_id("CapacityId"),
                "domain_id": domain_id,
                "workspace_deleted_flag": workspace["fuam_deleted"] if workspace else None,
                "source_modified_at": workspace["fuam_modified_at"] if workspace else None,
                **classify_workspace(workspace is not None, associations.get(key, []), enabled),
                **resolve_domain(domain_id, domains, workspace is not None),
            })
        items = inherit_item_inventory(inventory, snapshots)
        item_schema = StructType(snapshot_schema.fields + [
            StructField("item_id", string, False),
            StructField("item_name", string, True),
            StructField("item_type", string, False),
            StructField("item_state", string, True),
            StructField("item_capacity_id", string, True),
            StructField("item_deleted_flag", BooleanType(), True),
            StructField("item_source_modified_at", timestamp, True),
            StructField("capacity_join_status", string, False),
        ])
        item_table = "dbo.item_use_case_snapshots"
        run["inventory_snapshot_count"] = len(items)
        spark.createDataFrame(items, item_schema).write.format("delta").option(
            "mergeSchema", "true"
        ).mode(
            "append"
        ).saveAsTable(item_table)
        data = spark.createDataFrame(snapshots, snapshot_schema)
        data.write.format("delta").option("mergeSchema", "true").mode("append").saveAsTable(
            snapshot_table
        )
        from pyspark.sql import functions as f

        spark.createDataFrame(catalog, catalog_schema).withColumn(
            "run_id", f.lit(run_id)
        ).withColumn("observed_at", f.lit(observed)).write.format("delta").mode(
            "append"
        ).saveAsTable(catalog_snapshot_table)
        if spark.table(snapshot_table).where(f.col("run_id") == run_id).count() != len(snapshots):
            raise RuntimeError("Persisted workspace classification count mismatch")
        if spark.table(item_table).where(f.col("run_id") == run_id).count() != len(items):
            raise RuntimeError("Persisted item inventory count mismatch")
        if spark.table(domain_table).where(f.col("run_id") == run_id).count() != len(domains):
            raise RuntimeError("Persisted domain hierarchy count mismatch")
        finalize("Succeeded")
        print(f"Classification captured. Run ID: {run_id}. Workspace observations: {len(snapshots)}")
    except Exception as error:
        finalize("Failed", type(error).__name__, str(error))
        raise

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}

# CELL ********************
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    collect_classification(
        SparkSession.builder.getOrCreate(),
        source_workspace_id, source_lakehouse_id, initial_use_cases_json,
        source_table_schema,
    )

# METADATA ********************
# META {"language": "python", "language_group": "synapse_pyspark"}
