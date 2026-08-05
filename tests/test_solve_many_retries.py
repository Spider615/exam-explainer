import io
import json
import os
import socket
import unittest
import urllib.error
from unittest.mock import call, patch

from pipeline import solve
from pipeline.solve_attempt import Failure, ProcessResult


def question(number=1):
    return {
        "id": 100 + number,
        "n": number,
        "type": "选择题",
        "options": [],
        "figures": [],
    }


class SolveManyRetryTests(unittest.TestCase):
    def run_many(self, process_results, **kwargs):
        q = question()
        with (
            patch.object(solve, "RETRY_DELAY", 0),
            patch.object(solve, "OUTLINE_EVERY", 0),
            patch.object(solve.solve_attempt, "run_process", side_effect=process_results) as run,
            patch.object(solve.store, "clear_solution_failure") as clear,
            patch.object(solve.store, "put_solution_failure") as put_failure,
        ):
            result = solve.solve_many("paper", [q], jobs=1, **kwargs)
        return q, result, run, clear, put_failure

    def test_third_attempt_succeeds_and_does_not_persist_failure(self):
        transient = ProcessResult(
            False, failure=Failure("network", "无法连接模型服务", "文本模型")
        )
        q, result, run, clear, put_failure = self.run_many(
            [transient, transient, ProcessResult(True, value=(True, "已解出"))]
        )

        self.assertEqual([(1, "ok", "已解出")], result)
        self.assertEqual(3, run.call_count)
        clear.assert_called_once_with(q["id"])
        put_failure.assert_not_called()
        temporary_directories = [entry.args[2][2] for entry in run.call_args_list]
        self.assertEqual(3, len(set(temporary_directories)))
        self.assertTrue(all(not os.path.exists(path) for path in temporary_directories))

    def test_three_retryable_failures_persist_once(self):
        failure = Failure("provider", "模型服务返回 HTTP 503", "文本模型")
        q, result, run, clear, put_failure = self.run_many(
            [ProcessResult(False, failure=failure)] * 3
        )

        self.assertEqual(3, run.call_count)
        clear.assert_called_once_with(q["id"])
        put_failure.assert_called_once_with(
            q["id"], "provider", "模型服务返回 HTTP 503", 3, "文本模型"
        )
        self.assertEqual("fail", result[0][1])
        self.assertIn("模型服务返回 HTTP 503", result[0][2])
        self.assertIn("3", result[0][2])

    def test_nonretryable_configuration_failure_stops_after_one_attempt(self):
        failure = Failure(
            "configuration", "缺少视觉模型配置", "视觉模型", retryable=False
        )
        q, result, run, clear, put_failure = self.run_many(
            [ProcessResult(False, failure=failure)]
        )

        self.assertEqual(1, run.call_count)
        clear.assert_called_once_with(q["id"])
        put_failure.assert_called_once_with(
            q["id"], "configuration", "缺少视觉模型配置", 1, "视觉模型"
        )
        self.assertEqual("fail", result[0][1])

    def test_on_retry_fires_only_after_first_and_second_attempts(self):
        events = []
        failure = Failure("network", "无法连接模型服务", "文本模型")

        self.run_many(
            [ProcessResult(False, failure=failure)] * 3,
            on_retry=lambda q, number, got: events.append((q["n"], number, got)),
        )

        self.assertEqual([(1, 1, failure), (1, 2, failure)], events)

    def test_process_timeout_is_translated_before_retry_and_persistence(self):
        timeout = Failure(
            "timeout", "Solve attempt exceeded its deadline: secret", "process"
        )
        events = []
        q, result, run, clear, put_failure = self.run_many(
            [ProcessResult(False, failure=timeout)] * 3,
            on_retry=lambda q, number, got: events.append(got),
        )

        self.assertEqual(
            [("timeout", "完整解题超过 5 分钟", "完整解题", True)] * 2,
            [(got.kind, got.reason, got.stage, got.retryable) for got in events],
        )
        put_failure.assert_called_once_with(
            q["id"], "timeout", "完整解题超过 5 分钟", 3, "完整解题"
        )
        self.assertNotIn("secret", result[0][2])

    def test_unexpected_parent_exception_is_persisted_without_raw_text(self):
        q, result, run, clear, put_failure = self.run_many(
            [RuntimeError("database password secret")]
        )

        clear.assert_called_once_with(q["id"])
        put_failure.assert_called_once_with(
            q["id"], "internal", "完整解题发生内部错误", 1, "完整解题"
        )
        self.assertNotIn("secret", result[0][2])


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


class PostFailureTests(unittest.TestCase):
    def test_timeout_makes_exactly_one_request_and_preserves_stage(self):
        with patch.object(
            solve.urllib.request, "urlopen", side_effect=socket.timeout("secret")
        ) as urlopen:
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.post("https://user:pass@example.invalid", "secret-key", {}, "文本模型")

        self.assertEqual(1, urlopen.call_count)
        self.assertEqual("timeout", caught.exception.failure.kind)
        self.assertEqual("模型请求超过 5 分钟", caught.exception.failure.reason)
        self.assertEqual("文本模型", caught.exception.failure.stage)
        self.assertTrue(caught.exception.failure.retryable)
        self.assertNotIn("secret", str(caught.exception))

    def test_http_429_is_retryable_provider_and_401_is_configuration(self):
        cases = [
            (429, "provider", True),
            (401, "configuration", False),
        ]
        for code, kind, retryable in cases:
            with self.subTest(code=code):
                error = urllib.error.HTTPError(
                    "https://user:pass@example.invalid",
                    code,
                    "secret-status",
                    {"Authorization": "secret-key"},
                    io.BytesIO(b"secret response body"),
                )
                with patch.object(solve.urllib.request, "urlopen", side_effect=error):
                    with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                        solve.post("https://example.invalid", "secret-key", {}, "视觉模型")

                failure = caught.exception.failure
                self.assertEqual(kind, failure.kind)
                self.assertEqual("模型服务返回 HTTP %d" % code, failure.reason)
                self.assertEqual("视觉模型", failure.stage)
                self.assertEqual(retryable, failure.retryable)
                self.assertNotIn("secret", str(caught.exception))

    def test_invalid_json_or_answer_content_is_invalid_response(self):
        responses = [
            b"not json at all",
            json.dumps({"choices": [{"message": {"content": "not an answer"}}]}).encode(),
        ]
        for response in responses:
            with self.subTest(response=response):
                with patch.object(
                    solve.urllib.request, "urlopen", return_value=FakeResponse(response)
                ):
                    with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                        solve.post("https://example.invalid", "key", {}, "文本模型")

                failure = caught.exception.failure
                self.assertEqual("invalid_response", failure.kind)
                self.assertEqual("模型返回内容无法解析为答案", failure.reason)
                self.assertEqual("文本模型", failure.stage)
                self.assertTrue(failure.retryable)


if __name__ == "__main__":
    unittest.main()
