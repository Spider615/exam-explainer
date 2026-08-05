import datetime as dt
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import store


class FakeCursor:
    def __init__(self, rows=(), rowcounts=()):
        self.rows = list(rows)
        self.rowcounts = list(rowcounts)
        self.rowcount = 0
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.rowcount = self.rowcounts.pop(0) if self.rowcounts else 0

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class FakeConnection:
    def __init__(self, rows=(), rowcounts=()):
        self.cursor_obj = FakeCursor(rows, rowcounts)
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
        self.assertIn("SELECT id FROM questions", conn.calls[0][0])
        self.assertIn("FOR UPDATE", conn.calls[0][0])
        self.assertIn("DELETE FROM solutions", conn.calls[1][0])
        self.assertIn("INSERT INTO solution_failures", conn.calls[2][0])
        self.assertIn("ON CONFLICT (question_id) DO UPDATE", conn.calls[2][0])
        self.assertIn("updated_at=now()", conn.calls[2][0])
        self.assertEqual((7,), conn.calls[0][1])
        self.assertEqual(240, len(conn.calls[2][1][2]))

    def test_put_solution_clears_failure_in_the_same_commit(self):
        conn = FakeConnection()
        solution = {"answer": "A", "steps": [], "key_facts": [], "assumptions": [], "confidence": "high"}
        with patch.object(store, "connect", return_value=conn):
            store.put_solution(7, solution, "hash", "model")

        self.assertEqual(1, conn.commits)
        self.assertIn("SELECT id FROM questions", conn.calls[0][0])
        self.assertIn("FOR UPDATE", conn.calls[0][0])
        self.assertIn("INSERT INTO solutions", conn.calls[1][0])
        self.assertIn("DELETE FROM solution_failures", conn.calls[2][0])
        self.assertEqual((7,), conn.calls[2][1])

    def test_clear_solution_failure_updates_paper_only_when_failure_deleted(self):
        conn = FakeConnection(rows=[(7,)], rowcounts=[1, 1, 1, 1])
        with patch.object(store, "connect", return_value=conn):
            store.clear_solution_failure(7)

        self.assertEqual(1, conn.commits)
        self.assertIn("SELECT p.id", conn.calls[0][0])
        self.assertIn("JOIN questions q", conn.calls[0][0])
        self.assertIn("FOR UPDATE OF p", conn.calls[0][0])
        self.assertEqual((7,), conn.calls[0][1])
        self.assertIn("SELECT id FROM questions", conn.calls[1][0])
        self.assertIn("FOR UPDATE", conn.calls[1][0])
        self.assertIn("DELETE FROM solution_failures", conn.calls[2][0])
        self.assertIn("RETURNING question_id", conn.calls[2][0])
        self.assertEqual((7,), conn.calls[2][1])
        self.assertIn("UPDATE papers SET updated_at=clock_timestamp()", conn.calls[3][0])
        self.assertEqual((7,), conn.calls[3][1])
        self.assertEqual(1, conn.cursor_obj.rowcount)

    def test_clear_solution_failure_skips_paper_update_when_no_failure_exists(self):
        conn = FakeConnection(rows=[None], rowcounts=[1, 1, 0])
        with patch.object(store, "connect", return_value=conn):
            store.clear_solution_failure(7)

        self.assertEqual(1, conn.commits)
        self.assertEqual(3, len(conn.calls))
        self.assertIn("SELECT p.id", conn.calls[0][0])
        self.assertIn("FOR UPDATE OF p", conn.calls[0][0])
        self.assertIn("SELECT id FROM questions", conn.calls[1][0])
        self.assertIn("FOR UPDATE", conn.calls[1][0])
        self.assertIn("DELETE FROM solution_failures", conn.calls[2][0])
        self.assertIn("RETURNING question_id", conn.calls[2][0])
        self.assertEqual(0, conn.cursor_obj.rowcount)

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

    def test_progress_counts_labels_only_for_successful_solutions(self):
        now = dt.datetime(2026, 8, 5, 10, tzinfo=dt.timezone.utc)
        row = (1, 2, None, now, 2, 0, 1, 1, 0, 0,
               0, 0, 0, 0, 0, 0, 0, now, now)
        conn = FakeConnection([row])

        with patch.object(store, "connect", return_value=conn):
            result = store.progress("paper")

        query = " ".join(conn.calls[0][0].split())
        self.assertIn(
            "SELECT count(*) FROM solutions s "
            "JOIN questions q ON q.id=s.question_id "
            "WHERE q.paper_id=p.id AND q.label IS NOT NULL",
            query,
        )
        self.assertEqual(0, result["labels"])

    def test_assembled_data_timestamp_considers_solution_failures(self):
        now = dt.datetime(2026, 8, 5, 10, tzinfo=dt.timezone.utc)
        conn = FakeConnection([(None, None, now)])
        with patch.object(store, "connect", return_value=conn):
            result = store.assembled("paper")

        self.assertEqual(now.timestamp(), result["data_at"])
        self.assertIn("solution_failures", conn.calls[0][0])
        self.assertIn("max(f.updated_at)", conn.calls[0][0])


class QuestionGenerationLockTests(unittest.TestCase):
    def test_generation_lock_commits_acquire_before_body_and_unlock_after(self):
        conn = FakeConnection()
        events = []
        original_commit = conn.commit

        def commit():
            original_commit()
            events.append(("commit", conn.commits))

        conn.commit = commit
        with patch.object(store, "connect", return_value=conn) as connect:
            with store.question_generation_lock(17):
                events.append(("body", None))
                self.assertEqual(1, conn.commits)
                self.assertIn("pg_advisory_lock", conn.calls[0][0])
                self.assertEqual((17,), conn.calls[0][1])

        connect.assert_called_once_with()
        self.assertEqual(2, conn.commits)
        self.assertIn("pg_advisory_unlock", conn.calls[1][0])
        self.assertEqual((17,), conn.calls[1][1])
        self.assertEqual(
            [("commit", 1), ("body", None), ("commit", 2)], events
        )

    def test_generation_lock_unlocks_when_body_raises(self):
        conn = FakeConnection()
        with patch.object(store, "connect", return_value=conn):
            with self.assertRaisesRegex(RuntimeError, "body failed"):
                with store.question_generation_lock(23):
                    raise RuntimeError("body failed")

        self.assertEqual(2, conn.commits)
        self.assertIn("pg_advisory_lock", conn.calls[0][0])
        self.assertIn("pg_advisory_unlock", conn.calls[1][0])
        self.assertEqual((23,), conn.calls[1][1])


if __name__ == "__main__":
    unittest.main()
