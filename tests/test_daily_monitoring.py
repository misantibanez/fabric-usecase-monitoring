import unittest
from datetime import date, datetime, timedelta, timezone

from notebooks.collect_daily_monitoring import (
    assumed_day, check_daily_totals, daily_policies, pending_days, report_yesterday,
)


class DailyMonitoringTests(unittest.TestCase):
    capacity = "11111111-1111-1111-1111-111111111111"
    policy = {"capacity_id": capacity, "sku": "F8", "source_utc_offset_minutes": -240}

    def test_initial_thirty_days_end_at_source_yesterday_not_host_yesterday(self):
        now = datetime(2026, 11, 24, 2, 30, tzinfo=timezone.utc)
        last = report_yesterday(now, -240)
        self.assertEqual(last, date(2026, 11, 22))
        planned = pending_days(last - timedelta(days=29), last, {})
        self.assertEqual(len(planned), 30)
        self.assertEqual(planned[0], date(2026, 10, 24))
        self.assertNotIn(date(2026, 11, 23), planned)
        with self.assertRaisesRegex(ValueError, "aware"):
            report_yesterday(now.replace(tzinfo=None), -240)

    def test_incremental_catches_up_holes_retries_missing_and_rechecks_three_days(self):
        first, last = date(2026, 10, 24), date(2026, 11, 24)
        completed = {
            first + timedelta(days=i): "SourceRowsObserved" for i in range(28)
        }
        completed[first + timedelta(days=1)] = "MissingSourceDay"
        del completed[first + timedelta(days=5)]
        planned = pending_days(first, last, completed)
        self.assertIn(first + timedelta(days=1), planned)
        self.assertIn(first + timedelta(days=5), planned)
        self.assertNotIn(first, planned)
        for day in (date(2026, 11, 22), date(2026, 11, 23), last):
            self.assertIn(day, planned)
        replay = pending_days(first, last, {day: "SourceRowsObserved" for day in pending_days(first, last, {})})
        self.assertEqual(replay, [last - timedelta(days=2), last - timedelta(days=1), last])

    def test_assumed_day_is_stable_full_source_day_without_fabricated_consumption(self):
        period, interval = assumed_day(self.policy, date(2026, 11, 22))
        self.assertEqual((period, interval), assumed_day(self.policy, date(2026, 11, 22)))
        self.assertEqual(period["window_start"], datetime(2026, 11, 22, 4))
        self.assertEqual(period["window_end"], datetime(2026, 11, 23, 4))
        self.assertEqual((interval["interval_end"] - interval["interval_start"]).total_seconds() * interval["sku_cu"], 691200)
        self.assertIn("NOT FOR BILLING", period["assumption_note"])
        self.assertNotIn("TotalCUs", period)
        self.assertNotIn("observed_cus", interval)

    def test_policy_rejects_unapproved_sku_invalid_offset_and_duplicate_capacity(self):
        self.assertEqual(daily_policies([self.policy]), [self.policy])
        for rows in (
            [], [self.policy, self.policy],
            [{**self.policy, "sku": "F64"}],
            [{**self.policy, "source_utc_offset_minutes": True}],
            [{**self.policy, "source_utc_offset_minutes": -900}],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                daily_policies(rows)

    def test_archive_conservation_preserves_unknowns_and_duplicate_source_rows(self):
        day = date(2026, 11, 22)
        unknown = {day: {"rows": 2, "cus": None, "null_cus": 2}}
        check_daily_totals(unknown, unknown)
        known = {day: {"rows": 3, "cus": 0.123456789, "null_cus": 1}}
        check_daily_totals(known, known)
        for changed in (
            {}, {day: {"rows": 1, "cus": None, "null_cus": 1}},
            {day: {"rows": 2, "cus": 0, "null_cus": 2}},
        ):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                check_daily_totals(unknown, changed)


if __name__ == "__main__":
    unittest.main()
