import unittest
from unittest.mock import Mock, patch

from notebooks.classify_use_cases import (
    build_domain_index, classify_workspace, collect_classification,
    inherit_item_inventory, resolve_domain, validate_catalog,
)


class UseCaseClassificationTests(unittest.TestCase):
    first = "11111111-1111-1111-1111-111111111111"
    second = "22222222-2222-2222-2222-222222222222"
    tag = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    other = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    def cases(self):
        return [
            {"use_case_id": self.first, "use_case_name": "Example",
             "tag_id": self.tag, "is_enabled": True},
            {"use_case_id": self.second, "use_case_name": "Another",
             "tag_id": self.other, "is_enabled": True},
        ]

    def enabled(self, cases=None):
        rows = validate_catalog(
            self.cases() if cases is None else cases,
            {self.tag.upper(): "Domain", self.other.upper(): "Domain"},
        )
        return {case["tag_id"]: case for case in rows if case["is_enabled"]}

    def test_descriptive_and_repeated_tags_do_not_duplicate_assignment(self):
        result = classify_workspace(True, [self.tag, self.tag, self.first], self.enabled())
        self.assertEqual(result["classification_status"], "Assigned")
        self.assertEqual(result["use_case_id"], self.first)
        self.assertEqual(result["matched_case_count"], 1)

    def test_missing_disabled_and_multiple_matches_are_explicit(self):
        enabled = self.enabled()
        self.assertEqual(classify_workspace(True, [], enabled)["classification_status"],
                         "Unclassified")
        result = classify_workspace(True, [self.tag, self.other], enabled)
        self.assertEqual(result["classification_status"], "Ambiguous")
        self.assertEqual(result["matched_case_count"], 2)
        self.assertIsNone(result["use_case_id"])
        rows = self.cases()
        rows[0]["is_enabled"] = False
        self.assertEqual(
            classify_workspace(True, [self.tag], self.enabled(rows))["classification_status"],
            "Unclassified",
        )
        self.assertEqual(
            classify_workspace(False, [self.tag], enabled)["classification_status"],
            "MissingWorkspace",
        )

    def test_tag_names_do_not_collide_and_reassignment_does_not_mutate_prior_result(self):
        rows = self.cases()
        rows[1]["use_case_name"] = rows[0]["use_case_name"]
        enabled = self.enabled(rows)
        old = classify_workspace(True, [self.tag], enabled)
        new = classify_workspace(True, [self.other], enabled)
        self.assertNotEqual(old["use_case_id"], new["use_case_id"])
        self.assertEqual(old["use_case_id"], self.first)
        self.assertEqual(classify_workspace(True, [self.tag], enabled), old)

    def test_invalid_catalog_fails_instead_of_silently_unclassifying(self):
        for change in (
            {"tag_id": self.tag}, {"use_case_id": self.first},
            {"use_case_name": ""}, {"is_enabled": "true"}, {"tag_id": self.first},
        ):
            rows = self.cases()
            rows[1].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.enabled(rows)
        with self.assertRaises(ValueError):
            validate_catalog(self.cases(), {self.tag.upper(): "Tenant", self.other.upper(): "Domain"})

    def test_spark_reads_canonical_resource_ids_without_changing_matching_ids(self):
        spark = Mock()
        spark.read.format.return_value.load.side_effect = RuntimeError("Stop at source read")
        utilities = Mock()
        utilities.conf.get.return_value = "abfss://example@onelake.dfs.fabric.microsoft.com/"
        modules = {
            "notebookutils": utilities,
            "pyspark.sql.types": Mock(),
            "delta.tables": Mock(),
        }
        with patch.dict("sys.modules", modules), self.assertRaisesRegex(
            RuntimeError, "Stop at source read",
        ):
            collect_classification(spark, self.tag.upper(), self.other.upper(), "[]")
        spark.read.format.return_value.load.assert_called_once_with(
            f"abfss://{self.tag}@onelake.dfs.fabric.microsoft.com/{self.other}/Tables/tags"
        )
        self.assertEqual(self.enabled()[self.tag.upper()]["tag_id"], self.tag.upper())

    def item(self, item_id=None, workspace_id=None, item_type="Notebook"):
        return {
            "id": item_id or self.first, "workspaceId": workspace_id or self.tag,
            "name": "Example item", "type": item_type, "state": "Active",
            "capacityId": self.other, "fuam_deleted": False, "fuam_modified_at": None,
        }

    def workspace(self, workspace_id=None, status="Assigned"):
        return {
            "workspace_id": (workspace_id or self.tag).upper(),
            "capacity_id": self.other.upper(), "domain_id": None,
            "classification_status": status,
            "matched_case_count": 1 if status == "Assigned" else 2 if status == "Ambiguous" else 0,
            "use_case_id": self.first if status == "Assigned" else None,
            "use_case_name": "Example" if status == "Assigned" else None,
        }

    def test_inventory_inherits_workspace_case_without_metrics_or_item_tags(self):
        items = [self.item(), self.item(self.second, item_type="VariableLibrary")]
        items[0]["tagId"] = self.other
        items[1]["fuam_deleted"] = True
        snapshots = [self.workspace()]
        before = dict(snapshots[0])
        inherited = inherit_item_inventory(items, snapshots)
        self.assertEqual(len(inherited), 2)
        self.assertEqual([row["use_case_id"] for row in inherited], [self.first, self.first])
        self.assertEqual(inherited[1]["item_type"], "VariableLibrary")
        self.assertTrue(inherited[1]["item_deleted_flag"])
        self.assertEqual(snapshots[0], before)

    def test_inventory_preserves_unresolved_states_and_capacity_mismatch(self):
        for status in ("Unclassified", "Ambiguous", "MissingWorkspace"):
            workspace = self.workspace(status=status)
            if status == "MissingWorkspace":
                workspace["capacity_id"] = None
            row = inherit_item_inventory([self.item()], [workspace])[0]
            self.assertEqual(row["classification_status"], status)
            self.assertIsNone(row["use_case_id"])
        workspace = self.workspace()
        workspace["capacity_id"] = self.first
        row = inherit_item_inventory([self.item()], [workspace])[0]
        self.assertEqual(row["capacity_join_status"], "CurrentCapacityMismatch")
        self.assertEqual(row["item_capacity_id"], self.other.upper())
        self.assertEqual(row["capacity_id"], self.first)

    def test_inventory_rejects_duplicate_ids_and_absent_workspace_observations(self):
        with self.assertRaisesRegex(ValueError, "Duplicate source item"):
            inherit_item_inventory([self.item(), self.item()], [self.workspace()])
        with self.assertRaisesRegex(ValueError, "no classification observation"):
            inherit_item_inventory([self.item()], [])

    def test_domain_resolution_uses_parent_ids_even_when_names_collide(self):
        domains = build_domain_index([
            {"DomainId": self.first, "OriginalDomainName": "Same name",
             "OriginalParentDomainId": None},
            {"DomainId": self.second, "OriginalDomainName": "Same name",
             "OriginalParentDomainId": ""},
            {"DomainId": self.tag, "OriginalDomainName": "Subdomain",
             "OriginalParentDomainId": self.first},
            {"DomainId": self.other, "OriginalDomainName": "Subdomain",
             "OriginalParentDomainId": self.second},
        ])
        root = resolve_domain(self.first, domains)
        self.assertEqual(root["hierarchy_depth"], 0)
        self.assertIsNone(root["subdomain_id"])
        leaf = resolve_domain(self.tag, domains)
        self.assertEqual(leaf["root_domain_id"], self.first)
        self.assertEqual(leaf["subdomain_id"], self.tag.upper())
        self.assertEqual(leaf["domain_path_ids"], '["' + self.first + '", "' + self.tag.upper() + '"]')
        self.assertNotEqual(leaf["root_domain_id"], resolve_domain(self.other, domains)["root_domain_id"])
        inherited = inherit_item_inventory(
            [self.item()], [{**self.workspace(), **leaf}],
        )
        self.assertEqual(inherited[0]["root_domain_id"], leaf["root_domain_id"])
        self.assertEqual(inherited[0]["subdomain_id"], leaf["subdomain_id"])

    def test_domain_gaps_and_cycles_do_not_infer_a_root(self):
        domains = {self.tag.upper(): ("Example", self.first)}
        for domain, exists, status in (
            (None, True, "NoDomain"), (None, False, "MissingWorkspace"),
            (self.other, True, "DomainNotFound"),
            (self.tag, True, "ParentDomainNotFound"),
        ):
            result = resolve_domain(domain, domains, exists)
            self.assertEqual(result["domain_resolution_status"], status)
            self.assertIsNone(result["root_domain_id"])
        domains[self.first] = ("Cycle", self.tag.upper())
        self.assertEqual(resolve_domain(self.tag, domains)["domain_resolution_status"], "HierarchyCycle")
        with self.assertRaisesRegex(ValueError, "Duplicate source domain"):
            build_domain_index([
                {"DomainId": self.first, "OriginalDomainName": "First", "OriginalParentDomainId": None},
                {"DomainId": self.first, "OriginalDomainName": "Other", "OriginalParentDomainId": None},
            ])


if __name__ == "__main__":
    unittest.main()
