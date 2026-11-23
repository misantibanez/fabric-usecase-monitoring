import unittest
from unittest.mock import Mock, patch

from notebooks.classify_use_cases import (
    classify_workspace, collect_classification, validate_catalog,
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


if __name__ == "__main__":
    unittest.main()
