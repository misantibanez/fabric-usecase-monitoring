"""Resumable Fabric installation over existing FUAM sources."""
import base64
import hashlib
import json
import math
import re
import struct
import time
from datetime import date
from urllib.parse import quote, urlparse
from uuid import UUID


FABRIC = "https://api.fabric.microsoft.com/v1"
POWERBI = "https://api.powerbi.com/v1.0/myorg"
MARKER = "FabricUseCaseMonitoringInstaller:v1"
METRIC_SHORTCUT = "fuam_capacity_metrics_by_item_by_operation_by_day"
SOURCE_COLUMNS = {
    "tags": {"tagId", "scope"},
    "workspace_tags": {"WorkspaceId", "tagId"},
    "workspaces": {"WorkspaceId", "CapacityId", "DomainId", "fuam_deleted", "fuam_modified_at"},
    "domains_flatten": {"DomainId", "OriginalDomainName", "OriginalParentDomainId"},
    "active_items": {
        "id", "workspaceId", "name", "type", "state", "capacityId",
        "fuam_deleted", "fuam_modified_at",
    },
    "capacity_metrics_by_item_by_operation_by_day": {
        "CapacityId", "WorkspaceId", "ItemId", "Date", "ItemKind",
        "OperationName", "TotalCUs", "OperationCount",
    },
}
MONITORING_TABLES = [
    METRIC_SHORTCUT,
    "use_cases", "classification_runs", "workspace_use_case_snapshots",
    "use_case_catalog_snapshots", "item_use_case_snapshots", "domain_hierarchy_snapshots",
    "capacity_collection_runs", "capacity_state_snapshots", "capacity_system_events",
    "capacity_demo_periods", "capacity_demo_intervals", "capacity_demo_consumption",
    "capacity_estimate_periods", "capacity_estimate_intervals",
]


def uuid_text(value: str) -> str:
    parsed = UUID(value)
    if parsed.int == 0:
        raise ValueError("All-zero resource IDs are invalid")
    return str(parsed)


def validate_config(config: dict, current_workspace: str) -> dict:
    result = dict(config)
    result["workspace_id"] = uuid_text(result.get("workspace_id") or current_workspace)
    result["source_workspace_id"] = uuid_text(
        result.get("source_workspace_id") or result["workspace_id"]
    )
    result["source_lakehouse_name"] = result.get("source_lakehouse_name", "FUAM_Lakehouse")
    result["prefix"] = result.get("prefix", "UseCaseMonitoring")
    for field in ("source_lakehouse_name", "prefix"):
        if not isinstance(result[field], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", result[field]):
            raise ValueError(f"{field} must be a simple Fabric/SQL identifier")
    sources = result.get("metric_sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("metric_sources requires a Capacity Metrics model mapping for each monitored capacity")
    seen = set()
    result["metric_sources"] = []
    for source in sources:
        entry = {name: uuid_text(source[name]) for name in ("capacity_id", "workspace_id", "model_id")}
        if entry["capacity_id"] in seen:
            raise ValueError("Duplicate capacity in metric_sources")
        seen.add(entry["capacity_id"])
        result["metric_sources"].append(entry)
    for field in ("initial_use_cases", "initial_estimates"):
        if not isinstance(result.get(field, []), list):
            raise ValueError(f"{field} must be a list")
        result[field] = result.get(field, [])
    policies = result.get("daily_policies", [])
    if not isinstance(policies, list):
        raise ValueError("daily_policies must be a list")
    result["daily_policies"] = []
    policy_capacities = set()
    for policy in policies:
        if not isinstance(policy, dict) or set(policy) != {"capacity_id", "sku", "source_utc_offset_minutes"}:
            raise ValueError("Daily policies require capacity_id, sku and source_utc_offset_minutes")
        entry = {**policy, "capacity_id": uuid_text(policy["capacity_id"])}
        offset = entry["source_utc_offset_minutes"]
        if entry["sku"] != "F8" or type(offset) is not int or not -720 <= offset <= 840:
            raise ValueError("Daily policies require explicitly assumed F8 active 24h and a valid integer source offset")
        if entry["capacity_id"] in policy_capacities:
            raise ValueError("Duplicate daily capacity policy")
        policy_capacities.add(entry["capacity_id"])
        result["daily_policies"].append(entry)
    if policies and (policy_capacities != seen or result["initial_estimates"]):
        raise ValueError("Daily mode requires exactly one policy per monitored capacity and initial_estimates=[]")
    if result.get("connection_id"):
        result["connection_id"] = uuid_text(result["connection_id"])
    else:
        result["connection_id"] = ""
    if result.get("focus_date"):
        date.fromisoformat(result["focus_date"])
    result["focus_date"] = result.get("focus_date", "")
    result["operation"] = result.get("operation", "install")
    if result["operation"] not in {"install", "refresh"}:
        raise ValueError("operation must be install or refresh")
    return result


def definition(parts: dict[str, str], format_name: str | None = None) -> dict:
    result = {"parts": [
        {"path": path, "payloadType": "InlineBase64",
         "payload": base64.b64encode(content.encode("utf-8")).decode("ascii")}
        for path, content in sorted(parts.items())
    ]}
    if format_name:
        result["format"] = format_name
    return result


def notebook_document(source: str, workspace: str, lakehouse: dict, parameters: dict) -> dict:
    marker = "# "
    sections = re.split(marker + r"CELL \*+\r?\n", source)
    if len(sections) != 3:
        raise ValueError("Unexpected collector source cell layout")
    implementation = sections[1].split(marker + "METADATA ", 1)[0]
    invocation = sections[2].split(marker + "METADATA ", 1)[0]
    defaults = "".join(f"{key} = {value!r}\n" for key, value in parameters.items())
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {
            "kernel_info": {"name": "synapse_pyspark"},
            "language_info": {"name": "python"},
            "dependencies": {"lakehouse": {
                "default_lakehouse": lakehouse["id"],
                "default_lakehouse_name": lakehouse["displayName"],
                "default_lakehouse_workspace_id": workspace,
                "known_lakehouses": [{"id": lakehouse["id"]}],
            }},
        },
        "cells": [
            {"cell_type": "code", "source": text.splitlines(keepends=True),
             "execution_count": None, "outputs": [],
             "metadata": {"tags": ["parameters"]} if index == 0 else {}}
            for index, text in enumerate((defaults, implementation, invocation))
        ],
    }


def choose_connection(references: list[dict], available: list[dict], requested_id: str = "") -> list[dict]:
    if not references:
        raise RuntimeError("The semantic model exposes no SQL connection references")
    bindings = []
    for reference in references:
        details = reference["connectionDetails"]
        matches = [
            candidate for candidate in available
            if candidate.get("connectionDetails") == details
            and candidate.get("connectivityType") in {
                "ShareableCloud", "PersonalCloud", "OnPremisesGateway", "VirtualNetworkGateway",
                "OnPremisesGatewayPersonal",
            }
            and (not requested_id or candidate["id"].lower() == requested_id.lower())
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "SQL_CONNECTION_REQUIRED: Configure/share an authorized SQL connection in "
                "Service matching this model's SQL server and database, then rerun this "
                "notebook with connection_id. No credentials were created or changed."
            )
        bindings.append({"connectionBinding": {
            "id": matches[0]["id"], "connectivityType": matches[0]["connectivityType"],
            "connectionDetails": details,
        }})
    return bindings


def verify_conservation(row: dict) -> None:
    if row["SourceRows"] != row["JoinedRows"] or row["SourceRows"] != row["EstimatedRows"]:
        raise RuntimeError("Metric rows were dropped or duplicated")
    for name in ("JoinedCUs", "EstimatedCUs"):
        left, right = row["SourceCUs"], row[name]
        if (left is None) != (right is None):
            raise RuntimeError("Unknown CU totals were converted into measured values")
        if left is not None and not math.isclose(
            float(left), float(right), rel_tol=1e-12, abs_tol=1e-8
        ):
            raise RuntimeError("Source CU conservation failed")


class Api:
    def __init__(self, session, get_token, sleep=time.sleep, timeout=1800):
        self.session, self.get_token, self.sleep, self.timeout = session, get_token, sleep, timeout

    def request(self, method: str, path: str, body: dict | None = None):
        url = path if path.startswith("https://") else FABRIC + path
        if urlparse(url).hostname not in {"api.fabric.microsoft.com", "api.powerbi.com"}:
            raise ValueError("Refusing to send credentials to a non-Fabric/Power BI host")
        for attempt in range(6):
            headers = {"Authorization": "Bearer " + self.get_token(), "Content-Type": "application/json"}
            if urlparse(url).hostname == "api.fabric.microsoft.com":
                headers["x-ms-fabric-skill"] = "semantic-model-authoring"
            response = self.session.request(method, url, json=body, headers=headers, timeout=90)
            if response.status_code != 429:
                break
            self.sleep(max(1, int(response.headers.get("Retry-After", "10"))))
        if response.status_code >= 400:
            code = response.json().get("errorCode", response.json().get("error", {}).get("code", "HTTP"))
            raise RuntimeError(f"{method} {urlparse(url).path} failed: {response.status_code} {code}")
        return response

    def get(self, path: str) -> dict:
        return self.request("GET", path).json()

    def listing(self, path: str) -> list[dict]:
        rows, tokens = [], set()
        while True:
            payload = self.get(path)
            if not isinstance(payload.get("value"), list):
                raise RuntimeError("Invalid paginated API result")
            rows.extend(payload["value"])
            token = payload.get("continuationToken")
            if not token:
                return rows
            if token in tokens:
                raise RuntimeError("Repeated API continuation token")
            tokens.add(token)
            path = path.split("?", 1)[0] + "?continuationToken=" + quote(token, safe="")

    def operation(self, operation_id: str, result: bool = True, delay: int = 5) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.sleep(max(1, delay))
            payload = self.get("/operations/" + uuid_text(operation_id))
            if payload["status"] == "Succeeded":
                return self.get("/operations/" + operation_id + "/result") if result else {}
            if payload["status"] in {"Failed", "Cancelled"}:
                raise RuntimeError(f"Fabric operation {operation_id} ended with {payload['status']}")
        raise TimeoutError(f"Operation {operation_id} is pending; resume its receipt, do not recreate")

    def execute_query(self, workspace: str, model: str, dax: str) -> list[dict]:
        payload = self.request(
            "POST", f"{POWERBI}/groups/{workspace}/datasets/{model}/executeQueries",
            {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}},
        ).json()
        if payload.get("error") or len(payload.get("results", [])) != 1:
            raise RuntimeError("DAX query failed or returned an invalid result")
        result = payload["results"][0]
        if result.get("error") or len(result.get("tables", [])) != 1:
            raise RuntimeError("DAX query returned partial/error results")
        table = result["tables"][0]
        if table.get("error"):
            raise RuntimeError("DAX table returned an error")
        return table.get("rows", [])


class Installer:
    def __init__(self, api: Api, config: dict, files: dict[str, str], spark, fs, connect_sql):
        self.api, self.config, self.files = api, config, files
        self.spark, self.fs, self.connect_sql = spark, fs, connect_sql
        self.workspace = config["workspace_id"]
        identity = {key: config[key] for key in ("workspace_id", "source_workspace_id", "source_lakehouse_name", "prefix", "metric_sources")}
        if config["daily_policies"]:
            identity["daily_policies"] = config["daily_policies"]
        self.owner = MARKER + ":" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        self.package = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        self.state = {"owner": self.owner, "package": self.package, "pending": {}, "done": [], "items": {}}
        self.state_path = ""

    def save(self) -> None:
        if self.state_path:
            self.fs.put(self.state_path, json.dumps(self.state), True)

    def item(self, name: str, kind: str, endpoint: str, payload: dict) -> dict:
        key = "create:" + name
        pending = self.state["pending"].get(key)
        if pending:
            if not pending.get("operation"):
                raise RuntimeError(f"Ambiguous submission for {name}; inspect workspace/receipt before clearing pending state")
            self.api.operation(pending["operation"])
        items = self.api.listing(f"/workspaces/{self.workspace}/items")
        matches = [
            item for item in items if item["displayName"].casefold() == name.casefold()
            and not (kind == "Lakehouse" and item["type"] == "SQLEndpoint")
        ]
        signature = self.owner + ":" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
        if matches:
            if len(matches) != 1 or matches[0]["type"] != kind or matches[0].get("description") != signature:
                raise RuntimeError(f"Name collision or incompatible package: {name}. Existing items will not be adopted/overwritten")
            item = matches[0]
        else:
            if pending:
                raise RuntimeError(f"Completed creation of {name} is not yet visible; rerun later, do not recreate")
            self.state["pending"][key] = {"status": "Submitting"}
            self.save()
            response = self.api.request("POST", f"/workspaces/{self.workspace}/{endpoint}",
                                        {"displayName": name, "description": signature, **payload})
            if response.status_code == 202:
                operation_id = response.headers.get("x-ms-operation-id")
                if not operation_id:
                    raise RuntimeError("Missing creation receipt; do not resubmit")
                self.state["pending"][key] = {"operation": operation_id}
                self.save()
                print(f"Creating {kind}: {name}; operation {operation_id}")
                item = self.api.operation(operation_id, delay=int(response.headers.get("Retry-After", "5")))
            else:
                item = response.json()
            if not item.get("id"):
                raise RuntimeError("Creation response has no resource ID; inspect receipt before rerun")
        self.state["pending"].pop(key, None)
        self.state["items"][name] = item["id"]
        self.save()
        return item

    def checkpoint(self, key: str, action) -> None:
        if key not in self.state["done"]:
            print("Installation step: " + key)
            action()
            self.state["done"].append(key)
            self.save()

    def shortcut(self, lakehouse_id: str, source_id: str, source_path: str) -> None:
        path = f"/workspaces/{self.workspace}/items/{lakehouse_id}/shortcuts"
        expected = {
            "workspaceId": self.config["source_workspace_id"],
            "itemId": source_id, "path": source_path,
        }
        matches = [row for row in self.api.listing(path)
                   if row["path"].strip("/") == "Tables/dbo" and row["name"] == METRIC_SHORTCUT]
        if matches:
            if len(matches) != 1 or matches[0]["target"].get("oneLake") != expected:
                raise RuntimeError("The monitoring metric shortcut points to a different source; it will not be overwritten")
            return
        self.api.request("POST", path + "?shortcutConflictPolicy=Abort", {
            "path": "Tables/dbo", "name": METRIC_SHORTCUT, "target": {"oneLake": expected},
        })
        actual = [row for row in self.api.listing(path)
                  if row["path"].strip("/") == "Tables/dbo" and row["name"] == METRIC_SHORTCUT]
        if len(actual) != 1 or actual[0]["target"].get("oneLake") != expected:
            raise RuntimeError("Monitoring metric shortcut verification failed")

    def job(self, key: str, notebook_id: str) -> None:
        pending = self.state["pending"].get(key)
        if pending:
            location = pending.get("location")
            if not location:
                raise RuntimeError(f"Ambiguous job submission {key}; inspect notebook jobs before clearing pending state")
        else:
            active = self.api.listing(f"/workspaces/{self.workspace}/items/{notebook_id}/jobs/instances")
            if any(job["status"] in {"NotStarted", "InProgress"} for job in active):
                raise RuntimeError("An existing collector job is active; wait before rerunning the installer")
            self.state["pending"][key] = {"status": "Submitting"}
            self.save()
            response = self.api.request(
                "POST", f"/workspaces/{self.workspace}/items/{notebook_id}/jobs/Execute/instances",
                {"executionData": {"compute": "Spark"}},
            )
            location = response.headers.get("Location")
            if response.status_code != 202 or not location:
                raise RuntimeError("Missing notebook job receipt; do not resubmit")
            self.state["pending"][key] = {"location": location}
            self.save()
            self.api.sleep(max(1, int(response.headers.get("Retry-After", "15"))))
        print(f"Following notebook job: {location}")
        deadline = time.monotonic() + self.api.timeout
        while time.monotonic() < deadline:
            result = self.api.get(location)
            if result["status"] == "Completed":
                if result.get("failureReason"):
                    raise RuntimeError(f"Notebook job {key} returned a failure reason")
                self.state["pending"].pop(key, None)
                self.save()
                return
            if result["status"] in {"Failed", "Cancelled", "Deduped"}:
                self.state["last_failed_job"] = {"key": key, "location": location}
                self.state["pending"].pop(key, None)
                self.save()
                raise RuntimeError(f"Notebook job {key} ended with {result['status']}; inspect its run ledger before retry")
            self.api.sleep(15)
        raise TimeoutError(f"Notebook job is pending: {location}. Rerun to follow the same receipt")

    def metadata(self, lakehouse: dict) -> dict:
        deadline = time.monotonic() + self.api.timeout
        while time.monotonic() < deadline:
            result = self.api.get(f"/workspaces/{self.workspace}/lakehouses/{lakehouse['id']}")
            endpoint = result["properties"]["sqlEndpointProperties"]
            if endpoint is None:
                self.api.sleep(10)
                continue
            if endpoint["provisioningStatus"] == "Success":
                return endpoint
            if endpoint["provisioningStatus"] == "Failed":
                raise RuntimeError("SQL endpoint provisioning failed")
            self.api.sleep(10)
        raise TimeoutError("SQL endpoint provisioning pending; rerun later")

    def sync(self, endpoint: dict) -> None:
        key = "metadata_sync"
        pending = self.state["pending"].get(key)
        if pending:
            if not pending.get("operation"):
                raise RuntimeError("Ambiguous metadata sync; inspect receipt before retry")
            self.api.operation(pending["operation"], result=False)
        else:
            self.state["pending"][key] = {"status": "Submitting"}
            self.save()
            response = self.api.request(
                "POST", f"/workspaces/{self.workspace}/sqlEndpoints/{endpoint['id']}/refreshMetadata",
                {"recreateTables": False},
            )
            if response.status_code == 202:
                operation_id = response.headers.get("x-ms-operation-id")
                if not operation_id:
                    raise RuntimeError("Missing metadata sync receipt")
                self.state["pending"][key] = {"operation": operation_id}
                self.save()
                self.api.operation(operation_id, result=False,
                                   delay=int(response.headers.get("Retry-After", "5")))
        self.state["pending"].pop(key, None)
        self.save()

    def sql(self, endpoint: dict, database: str, query: str) -> list[list[dict]]:
        connection = self.connect_sql(endpoint["connectionString"], database)
        try:
            connection.timeout = 180
            cursor = connection.cursor()
            results = []
            for batch in re.split(r"(?im)^\s*GO\s*$", query):
                if not batch.strip():
                    continue
                cursor.execute(batch)
                while True:
                    if cursor.description:
                        columns = [column[0] for column in cursor.description]
                        results.append([dict(zip(columns, row)) for row in cursor.fetchall()])
                    if not cursor.nextset():
                        break
            return results
        finally:
            connection.close()

    def refresh_model(self, model_id: str, key: str) -> None:
        base = f"{POWERBI}/groups/{self.workspace}/datasets/{model_id}/refreshes"
        pending = self.state["pending"].get(key)
        if pending:
            if not pending.get("location"):
                raise RuntimeError("Ambiguous refresh submission; inspect model refresh history before clearing state")
            location = pending["location"]
        else:
            self.state["pending"][key] = {"status": "Submitting"}
            self.save()
            response = self.api.request("POST", base, {"type": "Full", "commitMode": "transactional", "retryCount": 0})
            location = response.headers.get("Location")
            if response.status_code != 202 or not location:
                raise RuntimeError("Missing semantic-model refresh receipt; do not retry")
            self.state["pending"][key] = {"location": location}
            self.save()
            self.api.sleep(max(1, int(response.headers.get("Retry-After", "10"))))
        receipt = re.fullmatch(
            r"https://(?:api\.powerbi\.com|wabi-[a-z0-9-]+\.analysis\.windows\.net)"
            + re.escape(base.removeprefix("https://api.powerbi.com")) + r"/([0-9a-fA-F-]{36})",
            location,
        )
        if not receipt:
            raise RuntimeError("Invalid semantic-model refresh receipt; inspect refresh history, do not resubmit")
        location = base + "/" + uuid_text(receipt[1])
        self.state["pending"][key]["location"] = location
        self.save()
        deadline = time.monotonic() + self.api.timeout
        while time.monotonic() < deadline:
            payload = self.api.get(location)
            if payload["status"] == "Completed":
                self.state["pending"].pop(key, None)
                self.save()
                return
            if payload["status"] in {"Failed", "Cancelled", "Disabled"}:
                self.state["last_failed_refresh"] = location
                self.state["pending"].pop(key, None)
                self.save()
                raise RuntimeError(
                    "MODEL_REFRESH_FAILED: Inspect refresh history and configure the SQL "
                    "connection/credentials in Service if required. No automatic retry; "
                    f"receipt: {location}"
                )
            self.api.sleep(10)
        raise TimeoutError(f"Refresh pending: {location}. Rerun to follow the same receipt")

    def bind(self, model_id: str) -> None:
        path = f"/workspaces/{self.workspace}/items/{model_id}/connections"
        references = self.api.listing(path)
        bindings = choose_connection(references, self.api.listing("/connections"), self.config["connection_id"])
        expected = {(row["connectionBinding"]["id"], json.dumps(row["connectionBinding"]["connectionDetails"], sort_keys=True)) for row in bindings}
        actual = {(row.get("id"), json.dumps(row["connectionDetails"], sort_keys=True)) for row in references}
        if expected <= actual:
            return
        for binding in bindings:
            target = binding["connectionBinding"]
            if (target["id"], json.dumps(target["connectionDetails"], sort_keys=True)) not in actual:
                self.api.request("POST", f"/workspaces/{self.workspace}/semanticModels/{model_id}/bindConnection", binding)
        deadline = time.monotonic() + min(self.api.timeout, 60)
        while True:
            verified = self.api.listing(path)
            actual = {(row.get("id"), json.dumps(row["connectionDetails"], sort_keys=True)) for row in verified}
            if expected <= actual:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("SQL connection binding verification timed out; inspect model settings, then rerun to recheck")
            self.api.sleep(5)

    def validate_sql(self, endpoint: dict, database: str) -> None:
        source = "dbo." + ("monitoring_daily_metrics" if self.config["daily_policies"] else METRIC_SHORTCUT)
        query = f"""
        SELECT
          (SELECT COUNT_BIG(*) FROM {source}) SourceRows,
          (SELECT COUNT_BIG(*) FROM dbo.vw_item_consumption_preview) JoinedRows,
          (SELECT SUM(metric_row_count) FROM dbo.vw_use_case_capacity_estimate) EstimatedRows,
          (SELECT SUM(TotalCUs) FROM {source}) SourceCUs,
          (SELECT SUM(source_total_cus) FROM dbo.vw_item_consumption_preview) JoinedCUs,
          (SELECT SUM(observed_total_cus) FROM dbo.vw_use_case_capacity_estimate) EstimatedCUs;
        SELECT COUNT_BIG(*) AS DuplicateInventory FROM (
          SELECT item_id FROM dbo.vw_latest_item_use_case_inventory
          GROUP BY item_id HAVING COUNT_BIG(*)>1
        ) d;
        SELECT COUNT_BIG(*) AS InventoryItems FROM dbo.vw_latest_item_use_case_inventory;
        """
        results = self.sql(endpoint, database, query)
        verify_conservation(results[0][0])
        if results[1][0]["DuplicateInventory"] != 0:
            raise RuntimeError("Duplicate latest inventory identities")
        if results[0][0]["SourceRows"] == 0:
            raise RuntimeError("FUAM source has no consumption; installation cannot claim a real-data result")
        self.state["validated_metric_rows"] = results[0][0]["SourceRows"]
        self.state["validated_inventory_items"] = results[2][0]["InventoryItems"]
        if self.config["daily_policies"]:
            daily = self.sql(endpoint, database, """
                SELECT COUNT_BIG(*) AS CoverageDays,
                    SUM(CASE WHEN source_status='MissingSourceDay' THEN 1 ELSE 0 END) AS MissingSourceDays,
                    SUM(CASE WHEN in_rolling_window=1 THEN 1 ELSE 0 END) AS RollingDays,
                    SUM(CASE WHEN in_rolling_window=1 AND source_status='MissingSourceDay' THEN 1 ELSE 0 END) AS RollingMissingSourceDays,
                    SUM(CASE WHEN estimate_status<>'ScenarioReady' OR scenario_available_cus IS NULL THEN 1 ELSE 0 END) AS InvalidAssumptions
                FROM dbo.vw_monitoring_daily_coverage;
                SELECT COUNT_BIG(*) AS InvalidKeys FROM (
                    SELECT capacity_id,metric_date FROM dbo.monitoring_daily_periods
                    GROUP BY capacity_id,metric_date HAVING COUNT_BIG(*)<>1
                ) d;
            """)
            coverage = daily[0][0]
            if (coverage["RollingDays"] != 30 * len(self.config["daily_policies"])
                    or coverage["InvalidAssumptions"] != 0 or daily[1][0]["InvalidKeys"] != 0):
                raise RuntimeError("Daily calendar, uniqueness or explicit availability policy validation failed")
            self.state["daily_coverage"] = coverage
        self.save()

    def validate_model(self, model_id: str) -> None:
        rows = self.api.execute_query(self.workspace, model_id, self.files["scripts/validate_monitoring_model.dax"])
        if len(rows) != 12:
            raise RuntimeError("Missing or extra synthetic demo outputs")
        for row in rows:
            expected, actual = row.get("[ExpectedRatio]"), row.get("[ActualRatio]")
            if (expected is None) != (actual is None) or (
                expected is not None and not math.isclose(float(expected), float(actual), rel_tol=1e-10, abs_tol=1e-10)
            ):
                raise RuntimeError("Demo measure validation failed")
        health = self.api.execute_query(self.workspace, model_id,
            'EVALUATE ROW("MetricRows",[Observed Metric Rows],"Inventory",[Inventory Items])')
        if len(health) != 1 or not health[0].get("[MetricRows]") or not health[0].get("[Inventory]"):
            raise RuntimeError("The refreshed model has no actual consumption/inventory")
        if health[0]["[MetricRows]"] != self.state["validated_metric_rows"] or health[0]["[Inventory]"] != self.state["validated_inventory_items"]:
            raise RuntimeError("Imported model counts do not match validated SQL sources; check concurrent FUAM changes")
        if self.config["daily_policies"]:
            check = self.api.execute_query(self.workspace, model_id,
                'EVALUATE ROW("Missing",[Missing Source Days],"RollingMissing",'
                'CALCULATE([Missing Source Days],\'Date\'[In Rolling Window]=1),'
                '"RollingRatio",CALCULATE([Estimated Capacity Usage],\'Date\'[In Rolling Window]=1))')
            expected = self.state["daily_coverage"]
            if (len(check) != 1 or check[0]["[Missing]"] != expected["MissingSourceDays"]
                    or check[0]["[RollingMissing]"] != expected["RollingMissingSourceDays"]
                    or (expected["RollingMissingSourceDays"] > 0 and check[0]["[RollingRatio]"] is not None)):
                raise RuntimeError("Daily model does not preserve missing-source-day coverage/blank period percentages")

    def run(self, build_model, build_report) -> dict:
        source_workspace = self.config["source_workspace_id"]
        sources = self.api.listing(f"/workspaces/{source_workspace}/items")
        candidates = [item for item in sources if item["type"] == "Lakehouse" and item["displayName"] == self.config["source_lakehouse_name"]]
        if len(candidates) != 1:
            raise RuntimeError("FUAM Lakehouse is absent/ambiguous; this installer does not install FUAM")
        source = candidates[0]
        source_metadata = self.api.get(f"/workspaces/{source_workspace}/lakehouses/{source['id']}")
        source_schema = source_metadata["properties"].get("defaultSchema", "")
        if source_schema and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", source_schema):
            raise ValueError("Unsupported source schema identifier")
        source_tables_path = "Tables" + ("/" + source_schema if source_schema else "")
        root = f"abfss://{source_workspace}@onelake.dfs.fabric.microsoft.com/{source['id']}/{source_tables_path}"
        for table, columns in SOURCE_COLUMNS.items():
            frame = self.spark.read.format("delta").load(root + "/" + table)
            if columns - set(frame.columns):
                raise RuntimeError(f"FUAM source schema mismatch: {table}")
            if table in {"active_items", "capacity_metrics_by_item_by_operation_by_day"} and not frame.take(1):
                raise RuntimeError(f"FUAM source is empty: {table}")
        for entry in self.config["metric_sources"]:
            health = self.api.execute_query(entry["workspace_id"], entry["model_id"],
                f'EVALUATE ROW("CapacityMatches",CALCULATE(COUNTROWS(\'Capacities\'),'
                f'TREATAS({{"{entry["capacity_id"].upper()}"}},\'Capacities\'[Capacity Id])))')
            if len(health) != 1 or health[0].get("[CapacityMatches]") != 1:
                raise RuntimeError("Capacity Metrics model does not uniquely contain its configured capacity")
            if self.config["daily_policies"]:
                parameters = self.api.get(f"{POWERBI}/groups/{entry['workspace_id']}/datasets/{entry['model_id']}/parameters")
                offsets = [row["currentValue"] for row in parameters["value"] if row["name"] == "UTC_offset"]
                policy = next(row for row in self.config["daily_policies"] if row["capacity_id"] == entry["capacity_id"])
                if len(offsets) != 1 or float(offsets[0]) * 60 != policy["source_utc_offset_minutes"]:
                    raise RuntimeError("Daily policy offset does not match the Capacity Metrics UTC_offset parameter")
        prefix = self.config["prefix"]
        lakehouse = self.item(prefix + "_Lakehouse", "Lakehouse", "lakehouses",
                              {"creationPayload": {"enableSchemas": True}})
        self.state_path = f"abfss://{self.workspace}@onelake.dfs.fabric.microsoft.com/{lakehouse['id']}/Files/usecase-monitoring-install/state.json"
        self.fs.mkdirs(self.state_path.rsplit("/", 1)[0])
        if self.fs.exists(self.state_path):
            saved = json.loads(self.fs.head(self.state_path, 1048576))
            if saved["owner"] != self.owner:
                raise RuntimeError("Installation identity/package changed; use a new prefix or an explicitly reviewed upgrade")
            if saved["package"] != self.package:
                if saved["done"] or saved["pending"] or len(saved["items"]) > 1:
                    raise RuntimeError("Installed package changed; use a new prefix or an explicitly reviewed upgrade")
                saved["package"] = self.package
            self.state = saved
        self.save()
        endpoint = self.metadata(lakehouse)
        database = lakehouse["displayName"].lower()
        self.state["sql"] = {"server": endpoint["connectionString"], "database": database}
        self.save()
        self.sql(endpoint, database, "SELECT DB_NAME() AS DatabaseName")
        self.shortcut(lakehouse["id"], source["id"],
                      source_tables_path + "/capacity_metrics_by_item_by_operation_by_day")
        children = []
        for index, entry in enumerate(self.config["metric_sources"]):
            doc = notebook_document(self.files["notebooks/collect_capacity_history.py"], self.workspace, lakehouse, {
                "metric_workspace": entry["workspace_id"], "metric_dataset": entry["model_id"],
                "capacity_id": entry["capacity_id"], "history_window_days": 14,
            })
            item = self.item(f"{prefix}_CapacityHistory_{index + 1}", "Notebook", "notebooks",
                             {"definition": definition({"notebook-content.ipynb": json.dumps(doc)}, "ipynb")})
            children.append((f"history:{index + 1}", item["id"]))
        initial = json.dumps(self.config["initial_use_cases"])
        classification_source = self.files["notebooks/classify_use_cases.py"].replace(
            "source_lakehouse_id, initial_use_cases_json,",
            "source_lakehouse_id, '[]' if SparkSession.builder.getOrCreate().catalog.tableExists('dbo.use_cases') else initial_use_cases_json,",
        )
        for suffix, filename, parameters in [
            ("Classification", "notebooks/classify_use_cases.py", {
                "source_workspace_id": source_workspace, "source_lakehouse_id": source["id"],
                "source_table_schema": source_schema,
                "initial_use_cases_json": initial,
            }),
            ("Scenarios", "notebooks/initialize_capacity_scenarios.py", {
                "initial_estimates_json": json.dumps(self.config["initial_estimates"]),
            }),
        ]:
            content = classification_source if suffix == "Classification" else self.files[filename]
            doc = notebook_document(content, self.workspace, lakehouse, parameters)
            item = self.item(prefix + "_" + suffix, "Notebook", "notebooks",
                             {"definition": definition({"notebook-content.ipynb": json.dumps(doc)}, "ipynb")})
            children.append((suffix.lower(), item["id"]))
        daily = bool(self.config["daily_policies"])
        if daily:
            doc = notebook_document(self.files["notebooks/collect_daily_monitoring.py"], self.workspace, lakehouse, {
                "source_metrics_path": root + "/capacity_metrics_by_item_by_operation_by_day",
                "daily_policies_json": json.dumps(self.config["daily_policies"]),
            })
            item = self.item(prefix + "_Daily", "Notebook", "notebooks",
                             {"definition": definition({"notebook-content.ipynb": json.dumps(doc)}, "ipynb")})
            children.append(("daily", item["id"]))
        for key, notebook_id in children:
            self.checkpoint(key, lambda key=key, notebook_id=notebook_id: self.job(key, notebook_id))
        self.sync(endpoint)
        tables = self.sql(endpoint, database, "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='dbo'")[0]
        required_tables = MONITORING_TABLES + (
            ["monitoring_daily_metrics", "monitoring_daily_periods", "monitoring_daily_state"] if daily else []
        )
        if set(required_tables) - {row["TABLE_NAME"] for row in tables}:
            raise RuntimeError("SQL metadata is missing monitoring tables; rerun after synchronization")
        def views():
            filenames = ["create_consumption_preview_views.sql", "create_capacity_scenario_views.sql"]
            if daily:
                filenames.append("create_daily_monitoring_views.sql")
            for filename in filenames:
                sql = self.files["scripts/" + filename].replace(
                    "FUAM_Lakehouse.dbo.capacity_metrics_by_item_by_operation_by_day",
                    "dbo." + ("monitoring_daily_metrics" if daily else METRIC_SHORTCUT),
                )
                self.sql(endpoint, database, sql)
        self.checkpoint("views", views)
        self.validate_sql(endpoint, database)
        model_parts = build_model(endpoint["connectionString"], database, daily=True) if daily else build_model(endpoint["connectionString"], database)
        model = self.item(prefix + "_SM", "SemanticModel", "semanticModels",
                          {"definition": definition(model_parts)})
        self.state["model_id"] = model["id"]
        self.save()
        focus_date = self.state.get("focus_date") or self.config["focus_date"]
        if not focus_date:
            rows = self.sql(endpoint, database,
                            "SELECT MAX(CAST(metric_date AS date)) AS FocusDate FROM "
                            + ("dbo.monitoring_daily_periods" if daily else "dbo.vw_use_case_capacity_estimate"))[0]
            focus_date = rows[0]["FocusDate"].isoformat()
        self.state["focus_date"] = focus_date
        self.save()
        report_parts = build_report(model["id"], focus_date, daily=True) if daily else build_report(model["id"], focus_date)
        report = self.item(prefix + "_Report", "Report", "reports",
                           {"definition": definition(report_parts, "PBIR")})
        self.state["report_url"] = f"https://app.powerbi.com/groups/{self.workspace}/reports/{report['id']}/Estimated"
        self.save()
        print("Report created (not ready until successful refresh): " + self.state["report_url"])
        print(f"Required SQL connection: Server={endpoint['connectionString']}; Database={database}")
        self.bind(model["id"])
        self.checkpoint("initial_model_refresh", lambda: self.refresh_model(model["id"], "initial_model_refresh"))
        if self.config["operation"] == "refresh":
            for key, notebook_id in children:
                self.job("refresh:" + key, notebook_id)
            self.sync(endpoint)
            self.validate_sql(endpoint, database)
            self.refresh_model(model["id"], "manual_model_refresh")
        self.validate_model(model["id"])
        self.state["status"] = "ReadyEstimatedNotForBilling"
        self.save()
        print("VERIFIED: real-data conservation, synthetic model outcomes and initial Import refresh.")
        print("ESTIMATED / NOT FOR BILLING. No automatic schedule or permissions were changed.")
        print(self.state["report_url"])
        return self.state


def fabric_sql_connector(server: str, database: str):
    import notebookutils
    import pyodbc

    driver = "ODBC Driver 18 for SQL Server"
    if driver not in pyodbc.drivers():
        raise RuntimeError("Fabric runtime requires ODBC Driver 18 for SQL Server; no system drivers are installed by this notebook")
    if not re.fullmatch(r"[A-Za-z0-9.-]+\.datawarehouse\.fabric\.microsoft\.com", server):
        raise ValueError("Invalid Fabric SQL hostname")
    token = notebookutils.credentials.getToken("https://database.windows.net/")
    encoded = token.encode("utf-16-le")
    return pyodbc.connect(
        f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Encrypt=yes;TrustServerCertificate=no;",
        attrs_before={1256: struct.pack("<I", len(encoded)) + encoded}, autocommit=True, timeout=30,
    )


def install_in_fabric(config: dict, files: dict[str, str], build_model, build_report) -> dict:
    import notebookutils
    import requests
    from pyspark.sql import SparkSession

    config = validate_config(config, notebookutils.runtime.context["currentWorkspaceId"])
    api = Api(requests.Session(), lambda: notebookutils.credentials.getToken("pbi"))
    installer = Installer(api, config, files, SparkSession.builder.getOrCreate(), notebookutils.fs, fabric_sql_connector)
    try:
        return installer.run(build_model, build_report)
    except Exception as error:
        installer.state["status"] = "Blocked"
        installer.state["error_type"] = type(error).__name__
        installer.save()
        print("INSTALLATION BLOCKED. Resources/evidence were retained; no rollback/deletion was attempted.")
        if installer.state_path:
            print("Resume state: " + installer.state_path)
        raise
