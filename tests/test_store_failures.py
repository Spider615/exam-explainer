import datetime as dt
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import store


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class FakeConnection:
    def __init__(self, rows=()):
        self.cursor_obj = FakeCursor(rows)
        self.calls = self.cursor_obj.calls
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_obj

    def execute(self, sql, params=None):
        self.cursor_obj.execute(sql, params)

    def commit(self):
        self.commits += 1


class SolutionFailureSchemaTests(unittest.TestCase):
    def test_schema_defines_idempotent_cascading_solution_failures(self):
        schema = Path(store.ROOT, "pipeline", "schema.sql").read_text(encoding="utf-8")
        section = schema.split("CREATE TABLE IF NOT EXISTS solution_failures", 1)[1].split(";", 1)[0]
        normalized = " ".join(section.split())

        self.assertIn("question_id bigint PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE", normalized)
        for column in ("kind text NOT NULL", "reason text NOT NULL", "attempts int NOT NULL",
                       "stage text NOT NULL", "created_at timestamptz NOT NULL DEFAULT now()",
                       "updated_at timestamptz NOT NULL DEFAULT now()"):
            self.assertIn(column, normalized)


class SolutionFailureStoreTests(unittest.TestCase):
    def test_put_solution_failure_replaces_solution_then_upserts_once(self):
        conn = FakeConnection()
        with patch.object(store, "connect", return_value=conn):
            store.put_solution_failure(7, "timeout", "x" * 300, 3, "solve")

        self.assertEqual(1, conn.commits)
        self.assertIn("DELETE FROM solutions", conn.calls[0][0])
        self.assertIn("INSERT INTO solution_failures", conn.calls[1][0])
        self.assertIn("ON CONFLICT (question_id) DO UPDATE", conn.calls[1][0])
        self.assertIn("updated_at=now()", conn.calls[1][0])
        self.assertEqual((7,), conn.calls[0][1])
        self.assertEqual(240, len(conn.calls[1][1][2]))

    def test_put_solution_clears_failure_in_the_same_commit(self):
        conn = FakeConnection()
        solution = {"answer": "A", "steps": [], "key_facts": [], "assumptions": [], "confidence": "high"}
        with patch.object(store, "connect", return_value=conn):
            store.put_solution(7, solution, "hash", "model")

        self.assertEqual(1, conn.commits)
        self.assertIn("INSERT INTO solutions", conn.calls[0][0])
        self.assertIn("DELETE FROM solution_failures", conn.calls[1][0])
        self.assertEqual((7,), conn.calls[1][1])

    def test_clear_solution_failure_deletes_and_commits(self):
        conn = FakeConnection()
        with patch.object(store, "connect", return_value=conn):
            store.clear_solution_failure(7)

        self.assertEqual(1, conn.commits)
        self.assertIn("DELETE FROM solution_failures", conn.calls[0][0])
        self.assertEqual((7,), conn.calls[0][1])

    def test_paper_solution_failures_maps_rows_with_iso_timestamp(self):
        changed = dt.datetime(2026, 8, 5, 9, 30, tzinfo=dt.timezone.utc)
        conn = FakeConnection([(2, "timeout", "provider stalled", 3, "solve", changed)])
        with patch.object(store, "connect", return_value=conn):
            failures = store.paper_solution_failures("paper")

        self.assertEqual({2: {"kind": "timeout", "reason": "provider stalled", "attempts": 3,
                              "stage": "solve", "updated_at": changed.isoformat()}}, failures)
        self.assertIn("JOIN papers", conn.calls[0][0])
        self.assertIn("ORDER BY q.n", conn.calls[0][0])

    def test_progress_reports_failure_count_and_uses_failure_timestamp(self):
        now = dt.datetime(2026, 8, 5, 10, tzinfo=dt.timezone.utc)
        last = now - dt.timedelta(seconds=10)
        row = (1, 4, None, now - dt.timedelta(seconds=30), 4, 2, 1, 2, 0, 0,
               0, 0, 0, 0, 0, 0, 0, last, now)
        conn = FakeConnection([row])
        with patch.object(store, "connect", return_value=conn):
            result = store.progress("paper")

        self.assertEqual(2, result["solutionFailures"])
        self.assertEqual(last.timestamp(), result["lastChange"])
        self.assertIn("solution_failures", conn.calls[0][0])
        self.assertIn("max(f.updated_at)", conn.calls[0][0])

    def test_assembled_data_timestamp_considers_solution_failures(self):
        now = dt.datetime(2026, 8, 5, 10, tzinfo=dt.timezone.utc)
        conn = FakeConnection([(None, None, now)])
        with patch.object(store, "connect", return_value=conn):
            result = store.assembled("paper")

        self.assertEqual(now.timestamp(), result["data_at"])
        self.assertIn("solution_failures", conn.calls[0][0])
        self.assertIn("max(f.updated_at)", conn.calls[0][0])


if __name__ == "__main__":
    unittest.main()
