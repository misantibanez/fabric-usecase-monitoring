import unittest

from notebooks.initialize_capacity_scenarios import validate_scenarios


class CapacityScenarioTests(unittest.TestCase):
    def scenario(self):
        return {
            "scenario_id": "estimate",
            "capacity_id": "11111111-1111-1111-1111-111111111111",
            "metric_date": "2026-01-01", "source_utc_offset_minutes": -210,
            "window_start": "2026-01-01T03:30:00Z",
            "window_end": "2026-01-02T03:30:00Z",
            "assumption_note": "Assume F8; continuity is unvalidated",
            "intervals": [{
                "interval_start": "2026-01-01T03:30:00Z",
                "interval_end": "2026-01-01T15:30:00Z",
                "state": "Active", "sku": "F8", "sku_cu": 8,
                "state_basis": "Observed transition; unvalidated continuity",
                "sku_basis": "Assumed F8",
            }],
        }

    def test_report_clock_alignment_does_not_fill_missing_intervals(self):
        periods, intervals = validate_scenarios([self.scenario()])
        self.assertEqual(periods[0]["window_start"].hour, 3)
        self.assertEqual(periods[0]["window_start"].minute, 30)
        self.assertEqual(len(intervals), 1)
        self.assertEqual(
            (intervals[0]["interval_end"] - intervals[0]["interval_start"]).total_seconds(),
            43200,
        )

    def test_partial_or_naive_report_days_are_rejected(self):
        for value in ("2026-01-02T00:00:00Z", "2026-01-02T03:30:00"):
            row = self.scenario()
            row["window_end"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_scenarios([row])
        row = self.scenario()
        row["source_utc_offset_minutes"] = True
        with self.assertRaises(ValueError):
            validate_scenarios([row])

    def test_duplicate_capacity_days_cannot_duplicate_real_consumption(self):
        other = self.scenario()
        other["scenario_id"] = "other-assumptions"
        with self.assertRaises(ValueError):
            validate_scenarios([self.scenario(), other])

    def test_unknown_state_and_sku_remain_explicit(self):
        row = self.scenario()
        row["intervals"][0].update(state="Unknown", sku=None, sku_cu=None)
        _, intervals = validate_scenarios([row])
        self.assertEqual(intervals[0]["state"], "Unknown")
        self.assertIsNone(intervals[0]["sku_cu"])

    def test_invalid_interval_or_sku_cannot_be_seeded(self):
        for changes in (
            {"interval_end": "2026-01-03T03:30:00Z"},
            {"interval_end": "2026-01-01T03:30:00Z"},
            {"sku": "F64"},
            {"sku_cu": 3, "sku": "F3"},
            {"state_basis": ""},
        ):
            row = self.scenario()
            row["intervals"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_scenarios([row])


if __name__ == "__main__":
    unittest.main()
