import base64
import json
import unittest
from unittest.mock import Mock, patch

from scripts.build_install_notebook import build_install_notebook, PACKAGE_PATHS
from scripts.install_monitoring import (
    Api, Installer, choose_connection, definition, notebook_document,
    validate_config, verify_conservation,
)


WS = "11111111-1111-1111-1111-111111111111"
MODEL = "22222222-2222-2222-2222-222222222222"
CONFIG = {
    "metric_sources": [{"capacity_id": MODEL, "workspace_id": WS, "model_id": MODEL}],
}


class InstallerTests(unittest.TestCase):
    def installer(self, api=None):
        api = api or Mock()
        api.timeout = 10
        return Installer(api, validate_config(CONFIG, WS), {}, Mock(), Mock(), Mock())

    def test_cross_workspace_source_and_duplicate_capacity_validation(self):
        config = validate_config({**CONFIG, "source_workspace_id": MODEL}, WS)
        self.assertEqual(config["workspace_id"], WS)
        self.assertEqual(config["source_workspace_id"], MODEL)
        with self.assertRaisesRegex(ValueError, "Duplicate capacity"):
            validate_config({**CONFIG, "metric_sources": CONFIG["metric_sources"] * 2}, WS)
        with self.assertRaises(ValueError):
            validate_config({**CONFIG, "prefix": "unsafe]; DROP VIEW dbo.x--"}, WS)

    def test_package_is_self_contained_and_preserves_parameter_cells(self):
        document = build_install_notebook()
        namespace = {"__name__": "installed_package"}
        implementation = "".join(document["cells"][2]["source"])
        for marker in ("# CELL ", "# METADATA ", "# PARAMETERS CELL "):
            self.assertNotIn(marker, implementation)
        for cell in document["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), "installer-cell", "exec")
        exec(implementation, namespace)
        self.assertTrue(set(PACKAGE_PATHS) <= namespace["PACKAGE_FILES"].keys())
        self.assertTrue(callable(namespace["build_model"]))
        self.assertTrue(callable(namespace["build_report"]))
        self.assertEqual(document["cells"][1]["metadata"]["tags"], ["parameters"])
        source = namespace["PACKAGE_FILES"]["notebooks/classify_use_cases.py"]
        child = notebook_document(source, WS, {"id": MODEL, "displayName": "Synthetic"}, {"source_lakehouse_id": WS})
        self.assertEqual(child["metadata"]["dependencies"]["lakehouse"]["default_lakehouse"], MODEL)
        self.assertEqual(child["cells"][0]["metadata"]["tags"], ["parameters"])
        for cell in child["cells"]:
            compile("".join(cell["source"]), "collector-cell", "exec")
        encoded = definition({"notebook-content.ipynb": json.dumps(child)}, "ipynb")
        self.assertEqual(json.loads(base64.b64decode(encoded["parts"][0]["payload"])), child)

    def test_name_collision_and_ambiguous_submission_never_recreate(self):
        installer = self.installer()
        installer.api.listing.return_value = [{"id": MODEL, "displayName": "Same", "type": "SemanticModel"}]
        with self.assertRaisesRegex(RuntimeError, "Name collision"):
            installer.item("Same", "SemanticModel", "semanticModels", {})
        installer.api.request.assert_not_called()
        installer.state["pending"]["create:Same"] = {"status": "Submitting"}
        with self.assertRaisesRegex(RuntimeError, "Ambiguous submission"):
            installer.item("Same", "SemanticModel", "semanticModels", {})
        installer.api.request.assert_not_called()

    def test_completed_creation_is_reused_on_sequential_rerun(self):
        installer = self.installer()
        created = {"id": MODEL, "displayName": "Synthetic", "type": "SemanticModel"}
        response = Mock(status_code=201)
        response.json.return_value = created
        installer.api.request.return_value = response
        installer.api.listing.return_value = []
        first = installer.item("Synthetic", "SemanticModel", "semanticModels", {})
        body = installer.api.request.call_args.args[2]
        installer.api.listing.return_value = [{**created, "description": body["description"]}]
        second = installer.item("Synthetic", "SemanticModel", "semanticModels", {})
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(installer.api.request.call_count, 1)

    def test_lakehouse_rerun_ignores_its_same_named_sql_endpoint(self):
        installer = self.installer()
        created = {"id": MODEL, "displayName": "Synthetic", "type": "Lakehouse"}
        response = Mock(status_code=201)
        response.json.return_value = created
        installer.api.request.return_value = response
        installer.api.listing.return_value = []
        installer.item("Synthetic", "Lakehouse", "lakehouses", {})
        description = installer.api.request.call_args.args[2]["description"]
        installer.api.listing.return_value = [
            {**created, "description": description},
            {"id": WS, "displayName": "Synthetic", "type": "SQLEndpoint"},
        ]
        self.assertEqual(installer.item("Synthetic", "Lakehouse", "lakehouses", {})["id"], MODEL)
        self.assertEqual(installer.api.request.call_count, 1)

    def test_pending_creation_and_job_follow_receipts_without_new_submission(self):
        installer = self.installer()
        installer.state["pending"]["create:Synthetic"] = {"operation": MODEL}
        installer.api.listing.return_value = []
        with self.assertRaisesRegex(RuntimeError, "not yet visible"):
            installer.item("Synthetic", "SemanticModel", "semanticModels", {})
        installer.api.operation.assert_called_once_with(MODEL)
        installer.api.request.assert_not_called()
        installer.state["pending"]["history"] = {"location": "https://api.fabric.microsoft.com/v1/jobs/existing"}
        installer.api.get.return_value = {"status": "Completed"}
        installer.job("history", MODEL)
        installer.api.request.assert_not_called()
        self.assertNotIn("history", installer.state["pending"])

    def test_no_matching_or_ambiguous_connection_blocks_without_credentials(self):
        details = {"type": "SQL", "path": "synthetic;database"}
        connection = {"id": MODEL, "connectionDetails": details, "connectivityType": "ShareableCloud"}
        for candidates in ([], [connection, connection], [{**connection, "connectionDetails": {"type": "SQL", "path": "other"}}]):
            with self.assertRaisesRegex(RuntimeError, "SQL_CONNECTION_REQUIRED"):
                choose_connection([{"connectionDetails": details}], candidates)
        result = choose_connection([{"connectionDetails": details}], [connection], MODEL)
        self.assertEqual(result[0]["connectionBinding"]["id"], MODEL)

    def test_binding_waits_for_visibility_without_repeating_submission(self):
        installer = self.installer()
        details = {"type": "SQL", "path": "synthetic;database"}
        reference = {"connectivityType": "Automatic", "connectionDetails": details}
        connection = {"id": MODEL, "connectivityType": "ShareableCloud", "connectionDetails": details}
        installer.api.listing.side_effect = [
            [reference], [connection], [reference], [connection],
        ]
        installer.bind(MODEL)
        installer.api.request.assert_called_once_with(
            "POST", f"/workspaces/{WS}/semanticModels/{MODEL}/bindConnection",
            {"connectionBinding": connection},
        )
        installer.api.sleep.assert_called_once_with(5)

    def test_existing_binding_is_verified_without_rebinding(self):
        installer = self.installer()
        connection = {"id": MODEL, "connectivityType": "ShareableCloud",
                      "connectionDetails": {"type": "SQL", "path": "synthetic;database"}}
        installer.api.listing.side_effect = [[connection], [connection]]
        installer.bind(MODEL)
        installer.api.request.assert_not_called()
        installer.api.sleep.assert_not_called()

    def test_binding_visibility_timeout_does_not_resubmit_or_claim_success(self):
        installer = self.installer()
        details = {"type": "SQL", "path": "synthetic;database"}
        reference = {"connectivityType": "Automatic", "connectionDetails": details}
        connection = {"id": MODEL, "connectivityType": "ShareableCloud", "connectionDetails": details}
        installer.api.listing.side_effect = (
            lambda path: [connection] if path == "/connections" else [reference]
        )
        with patch("scripts.install_monitoring.time.monotonic", side_effect=[0, 0, 60]):
            with self.assertRaisesRegex(RuntimeError, "verification timed out"):
                installer.bind(MODEL)
        self.assertEqual(installer.api.request.call_count, 1)

    def test_cross_workspace_shortcut_is_reused_but_never_retargeted(self):
        from scripts.install_monitoring import METRIC_SHORTCUT
        installer = self.installer()
        installer.config["source_workspace_id"] = MODEL
        existing = {"path": "/Tables/dbo", "name": METRIC_SHORTCUT, "target": {
            "oneLake": {"workspaceId": MODEL, "itemId": MODEL, "path": "Tables/metrics"},
        }}
        installer.api.listing.return_value = [existing]
        installer.shortcut(WS, MODEL, "Tables/metrics")
        installer.api.request.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "different source"):
            installer.shortcut(WS, MODEL, "Tables/other")
        installer.api.request.assert_not_called()

    def test_known_failed_refresh_stops_without_automatic_retry(self):
        installer = self.installer()
        receipt = f"https://api.powerbi.com/v1.0/myorg/groups/{WS}/datasets/{MODEL}/refreshes/{MODEL}"
        installer.state["pending"]["refresh"] = {"location": receipt}
        installer.api.get.return_value = {"status": "Failed"}
        with self.assertRaisesRegex(RuntimeError, "MODEL_REFRESH_FAILED"):
            installer.refresh_model(MODEL, "refresh")
        installer.api.request.assert_not_called()
        self.assertEqual(installer.state["last_failed_refresh"], receipt)
        self.assertNotIn("refresh", installer.state["pending"])

    def test_regional_refresh_receipt_uses_canonical_host_without_resubmission(self):
        path = f"/v1.0/myorg/groups/{WS}/datasets/{MODEL}/refreshes/{MODEL}"
        regional = "https://wabi-west-us3-a-primary-redirect.analysis.windows.net" + path
        for resume in (False, True):
            with self.subTest(resume=resume):
                installer = self.installer()
                installer.api.get.return_value = {"status": "Completed"}
                if resume:
                    installer.state["pending"]["refresh"] = {"location": regional}
                else:
                    installer.api.request.return_value = Mock(status_code=202, headers={"Location": regional})
                installer.refresh_model(MODEL, "refresh")
                installer.api.get.assert_called_once_with("https://api.powerbi.com" + path)
                self.assertEqual(installer.api.request.call_count, 0 if resume else 1)

    def test_refresh_receipt_rejects_other_model_and_untrusted_hosts(self):
        path = f"/v1.0/myorg/groups/{WS}/datasets/{MODEL}/refreshes/{MODEL}"
        for receipt in (
            "https://untrusted.example" + path,
            "https://api.powerbi.com" + path.replace(f"/datasets/{MODEL}", f"/datasets/{WS}"),
        ):
            with self.subTest(receipt=receipt):
                installer = self.installer()
                installer.state["pending"]["refresh"] = {"location": receipt}
                installer.api.get.return_value = {"status": "Completed"}
                with self.assertRaisesRegex(RuntimeError, "Invalid semantic-model refresh receipt"):
                    installer.refresh_model(MODEL, "refresh")
                installer.api.request.assert_not_called()
                installer.api.get.assert_not_called()

    def test_api_pagination_and_host_validation(self):
        session = Mock()
        first, second = Mock(status_code=200), Mock(status_code=200)
        first.json.return_value = {"value": [{"id": 1}], "continuationToken": "a/b"}
        second.json.return_value = {"value": [{"id": 2}]}
        session.request.side_effect = [first, second]
        api = Api(session, lambda: "synthetic-not-a-token", sleep=lambda _: None)
        self.assertEqual(api.listing("/connections"), [{"id": 1}, {"id": 2}])
        self.assertIn("continuationToken=a%2Fb", session.request.call_args.args[1])
        self.assertEqual(session.request.call_args.kwargs["headers"]["x-ms-fabric-skill"], "semantic-model-authoring")
        with self.assertRaises(ValueError):
            api.get("https://untrusted.example/receipt")
        self.assertEqual(session.request.call_count, 2)

    def test_partial_dax_results_are_not_success(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"results": [{"error": {"message": "partial"}, "tables": [{"rows": []}]}]}
        session.request.return_value = response
        api = Api(session, lambda: "synthetic-not-a-token")
        with self.assertRaisesRegex(RuntimeError, "partial"):
            api.execute_query(WS, MODEL, "EVALUATE ROW(\"Synthetic\",1)")

    def test_conservation_preserves_nulls_and_rejects_duplicate_rows(self):
        row = {"SourceRows": 10, "JoinedRows": 10, "EstimatedRows": 10,
               "SourceCUs": None, "JoinedCUs": None, "EstimatedCUs": None}
        verify_conservation(row)
        with self.assertRaisesRegex(RuntimeError, "Unknown"):
            verify_conservation({**row, "EstimatedCUs": 0})
        with self.assertRaisesRegex(RuntimeError, "duplicated"):
            verify_conservation({**row, "EstimatedRows": 20})
        verify_conservation({**row, "SourceCUs": 1000.00000001, "JoinedCUs": 1000.00000001, "EstimatedCUs": 1000.0000000101})

    def test_sql_timeout_is_set_on_connection_not_native_cursor(self):
        class NativeCursor:
            __slots__ = ()
            description = None

            def execute(self, _query):
                return self

            def nextset(self):
                return False

        connection = Mock()
        connection.cursor.return_value = NativeCursor()
        installer = self.installer()
        installer.connect_sql.return_value = connection
        self.assertEqual(installer.sql({"connectionString": "synthetic"}, "Synthetic", "SELECT 1"), [])
        self.assertEqual(connection.timeout, 180)
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
