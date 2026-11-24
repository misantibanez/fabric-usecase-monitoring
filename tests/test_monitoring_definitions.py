import json
import unittest

from scripts.build_monitoring_model import build_model, classification_key
from scripts.build_monitoring_report import build_report


class MonitoringDefinitionTests(unittest.TestCase):
    def test_sql_classification_identity_preserves_nulls_without_invalid_delimiters(self):
        expression = classification_key()
        self.assertIn("COALESCE(use_case_id,'~'),'|',COALESCE(root_domain_id,'~')", expression)
        parts = build_model("synthetic.example", "SyntheticDatabase")
        for path, content in parts.items():
            if path.startswith("definition/tables/"):
                source = content.split("\t\tsource = ", 1)[1]
                self.assertEqual(len(source.strip().splitlines()), 1)
                self.assertNotIn("COALESCE(use_case_id,'|'", source)

    def test_report_queries_reference_actual_model_objects(self):
        model = build_model("synthetic.example", "SyntheticDatabase")
        report = build_report("11111111-1111-1111-1111-111111111111", "2026-01-01")
        for path, text in report.items():
            if not path.endswith("/visual.json"):
                continue
            visual = json.loads(text)["visual"]
            for role in visual["query"]["queryState"].values():
                for projection in role["projections"]:
                    kind, reference = next(iter(projection["field"].items()))
                    table = reference["Expression"]["SourceRef"]["Entity"]
                    content = model[f"definition/tables/{table}.tmdl"]
                    declaration = "measure" if kind == "Measure" else "column"
                    self.assertIn(f"{declaration} '{reference['Property']}'", content, path)

    def test_missing_availability_does_not_create_nonexistent_visual_combinations(self):
        model = build_model("synthetic.example", "SyntheticDatabase")
        availability = model["definition/tables/Availability.tmdl"]
        self.assertIn("IF(COUNTROWS('Availability')>0,COALESCE(", availability)
        self.assertIn(",0),BLANK())", availability)
        self.assertIn("SELECT DISTINCT metric_capacity_id AS capacity_id", availability)
        relationships = model["definition/relationships.tmdl"]
        self.assertNotIn("relationship 'Availability Classification'", relationships)

    def test_daily_model_uses_expected_calendar_and_blocks_partial_period_percentages(self):
        model = build_model("synthetic.example", "SyntheticDatabase", daily=True)
        self.assertIn("dbo.vw_monitoring_daily_coverage", model["definition/tables/Availability.tmdl"])
        self.assertIn('="MissingSourceDay"', model["definition/tables/Availability.tmdl"])
        self.assertIn("IF([Missing Source Days]>0,BLANK(),", model["definition/tables/Consumption.tmdl"])
        calendar = model["definition/tables/Date.tmdl"]
        self.assertIn("MIN(first_day)", calendar)
        self.assertIn("MAX(window_end_day)", calendar)
        self.assertIn("Date.AddDays(Last,-30)", calendar)
        report = build_report("11111111-1111-1111-1111-111111111111", "2026-01-01", daily=True)
        page = json.loads(report["definition/pages/Estimated/page.json"])
        rule = page["filterConfig"]["filters"][0]
        self.assertEqual(rule["field"]["Column"]["Property"], "In Rolling Window")
        self.assertNotIn("2026-01-01", json.dumps(rule))
        for path, text in report.items():
            if not path.endswith("/visual.json"):
                continue
            for role in json.loads(text)["visual"]["query"]["queryState"].values():
                for projection in role["projections"]:
                    kind, reference = next(iter(projection["field"].items()))
                    table = reference["Expression"]["SourceRef"]["Entity"]
                    declaration = "measure" if kind == "Measure" else "column"
                    self.assertIn(f"{declaration} '{reference['Property']}'", model[f"definition/tables/{table}.tmdl"])

if __name__ == "__main__":
    unittest.main()
