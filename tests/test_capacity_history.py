import unittest
from datetime import datetime, timedelta, timezone

from notebooks.collect_capacity_history import (
    decode_query_response, events_query, normalize_events, select_capacity,
)


class CapacityHistoryTests(unittest.TestCase):
    capacity = "11111111-1111-1111-1111-111111111111"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    def event(self, **changes):
        return {
            "CapacityId": self.capacity, "EventTime": "2026-01-01T12:00:00Z",
            "State": "Suspended", "Reason": "ManuallyPaused", "ActivationId": None,
            **changes,
        }

    def normalize(self, rows, run="first"):
        return normalize_events(
            rows, self.capacity, self.start, self.end, run, self.end
        )

    def test_event_identity_survives_rerun_and_timezone_serialization(self):
        first = self.normalize([self.event(), self.event()])[0]
        second = self.normalize(
            [self.event(EventTime="2026-01-01T07:00:00-05:00")], run="second"
        )[0]
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(first["availability_effect"], "INACTIVE")
        self.assertEqual(len(self.normalize([self.event(), self.event()])), 1)
        activation = self.normalize([self.event(ActivationId="different-activation")])[0]
        self.assertNotEqual(first["event_id"], activation["event_id"])

    def test_performance_active_event_does_not_resume_paused_capacity(self):
        event = self.normalize([self.event(State="Active", Reason="NotOverloaded")])[0]
        self.assertIsNone(event["availability_effect"])
        unknown = self.normalize([self.event(State="Active", Reason="NewReason")])[0]
        self.assertIsNone(unknown["availability_effect"])
        resumed = self.normalize([self.event(State="Active", Reason="ManuallyResumed")])[0]
        self.assertEqual(resumed["availability_effect"], "ACTIVE")

    def test_out_of_scope_or_malformed_events_fail_explicitly(self):
        for row in (
            self.event(EventTime=self.end.isoformat()),
            self.event(CapacityId="22222222-2222-2222-2222-222222222222"),
            self.event(EventTime="not-a-date"),
            self.event(Reason=""),
        ):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.normalize([row])
        with self.assertRaises(ValueError):
            self.normalize([self.event()] * 10001)
        self.assertEqual(self.normalize([]), [])

    def test_partial_or_invalid_query_response_is_not_empty_success(self):
        response = {"results": [{"tables": [{"rows": [{"[Reason]": "Created"}]}]}]}
        self.assertEqual(decode_query_response(response), [{"Reason": "Created"}])
        self.assertEqual(decode_query_response({"results": [{"tables": [{}]}]}), [])
        for payload in (
            {}, {"error": {"code": "Forbidden"}},
            {"results": [{"error": {"code": "Partial"}, "tables": [{}]}]},
            {"results": [{"tables": [{"rows": "invalid"}]}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                decode_query_response(payload)

    def test_missing_or_duplicate_capacity_is_not_inferred_deleted(self):
        row = {"id": self.capacity, "state": "Active", "sku": "F64"}
        self.assertEqual(select_capacity([row], self.capacity)["sku"], "F64")
        for rows in ([], [row, row], [{"id": self.capacity, "state": "Active"}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                select_capacity(rows, self.capacity)

    def test_dax_window_is_bounded_and_rejects_injection(self):
        query = events_query(self.capacity, self.start, self.end)
        self.assertIn(">= DATE(2026,1,1)+TIME(0,0,0)", query)
        self.assertIn("< DATE(2026,1,2)+TIME(0,0,0)", query)
        self.assertIn("TOPN(10001", query)
        with self.assertRaises(ValueError):
            events_query('invalid"} EVALUATE', self.start, self.end)
        with self.assertRaises(ValueError):
            events_query(self.capacity, self.start, self.start)


if __name__ == "__main__":
    unittest.main()
