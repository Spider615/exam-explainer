import unittest
from unittest.mock import patch

from pipeline import api
from pipeline.api import stage_of


def progress(**changes):
    base = dict(
        questions=15,
        solutions=14,
        solutionFailures=0,
        labels=14,
        judged=14,
        specsWorth=0,
        worth=0,
        drafts=0,
        specs=0,
        approved=0,
        sceneTried=0,
        ready=0,
        assembledFresh=True,
        busy=False,
        elapsedSeconds=12,
    )
    base.update(changes)
    return base


def question(number):
    return {
        "n": number,
        "type": "single",
        "points": 4,
        "section": "一、选择题",
        "pages": [1],
        "stem": "题干 %d" % number,
        "options": [],
        "figures": [],
    }


def solution():
    return {
        "answer": "A",
        "short_answer": "A",
        "steps": ["step"],
        "assumptions": [],
        "confidence": "high",
        "model": "test-model",
        "n_invariants": 0,
        "spec_status": None,
        "animatable": None,
        "why_not": None,
        "worth": None,
        "worth_why": None,
        "scene_passed": None,
        "scene_rounds": None,
    }


class StageProgressTests(unittest.TestCase):
    def test_unresolved_question_stays_in_solve(self):
        code, _label, _short, cur, total = stage_of(progress())

        self.assertEqual("solve", code)
        self.assertEqual((14, 15), (cur, total))

    def test_terminal_failure_finishes_solve_stage(self):
        code, _label, _short, _cur, _total = stage_of(
            progress(solutionFailures=1)
        )

        self.assertEqual("done", code)

    def test_all_failed_paper_needs_no_outline_labels(self):
        code, _label, _short, _cur, _total = stage_of(
            progress(
                questions=2,
                solutions=0,
                solutionFailures=2,
                labels=0,
                judged=0,
            )
        )

        self.assertEqual("done", code)

    def test_outline_denominator_uses_successes_only(self):
        code, _label, _short, cur, total = stage_of(
            progress(solutionFailures=1, labels=13)
        )

        self.assertEqual("outline", code)
        self.assertEqual((13, 14), (cur, total))

    def test_pick_denominator_uses_successes_only(self):
        code, _label, _short, cur, total = stage_of(
            progress(solutionFailures=1, judged=13)
        )

        self.assertEqual("pick", code)
        self.assertEqual((13, 14), (cur, total))


class PaperApiFailureTests(unittest.TestCase):
    def test_paper_serializes_question_failure_and_coverage(self):
        failure = {
            "kind": "timeout",
            "reason": "完整解题超过 5 分钟",
            "attempts": 3,
            "stage": "完整解题",
            "updated_at": "2026-08-05T09:30:00+00:00",
        }
        paper_data = {
            "sections": ["一、选择题"],
            "warnings": [],
            "questions": [question(1), question(2)],
        }

        with (
            patch.object(api, "mine", return_value="paper"),
            patch.object(api.store, "get_paper", return_value=paper_data),
            patch.object(api, "scenes_for", return_value={}),
            patch.object(api.store, "paper_solutions", return_value={1: solution()}),
            patch.object(
                api.store, "paper_solution_failures", return_value={2: failure}
            ) as get_failures,
            patch.object(
                api.store,
                "assembled",
                return_value={"path": None, "at": None, "fresh": False},
            ),
            patch.object(api, "active_job_for", return_value=None),
            patch.object(api.os.path, "exists", return_value=False),
        ):
            result = api.paper("paper", user={"id": 7})

        get_failures.assert_called_once_with("paper")
        by_number = {item["n"]: item for item in result["questions"]}
        self.assertIsNone(by_number[1]["solutionFailure"])
        self.assertEqual(
            {
                "kind": "timeout",
                "reason": "完整解题超过 5 分钟",
                "attempts": 3,
                "stage": "完整解题",
                "updatedAt": "2026-08-05T09:30:00+00:00",
            },
            by_number[2]["solutionFailure"],
        )
        self.assertEqual(
            {"solved": 1, "failed": 1, "total": 2}, result["coverage"]
        )

    def test_paper_list_exposes_failure_count_and_can_be_done(self):
        pg = progress(solutionFailures=1)
        rows = [{"name": "paper"}]

        with (
            patch.object(api.store, "list_papers", return_value=rows),
            patch.object(api, "running_cmds", return_value=[]),
            patch.object(api, "scenes_for", return_value={}),
            patch.object(api.store, "progress", return_value=pg),
            patch.object(api, "pipeline_running", return_value=False),
            patch.object(api, "active_job_for", return_value=None),
            patch.object(api, "failed_job_for", return_value=None),
        ):
            result = api.papers(user={"id": 7})

        nested = result[0]["progress"]
        self.assertEqual(1, nested["solutionFailures"])
        self.assertTrue(nested["done"])
        self.assertEqual("done", nested["code"])


if __name__ == "__main__":
    unittest.main()
