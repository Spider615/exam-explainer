import io
import http.client
import json
import os
import socket
import subprocess
import tempfile
import unittest
import urllib.error
from contextlib import contextmanager, nullcontext
from unittest.mock import patch

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
            patch.object(
                solve.store, "question_generation_lock", return_value=nullcontext()
            ),
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

    def test_persistence_error_is_not_retried_or_rewritten(self):
        q = question()
        failure = Failure("provider", "模型服务返回 HTTP 503", "文本模型")
        with (
            patch.object(solve, "RETRY_DELAY", 0),
            patch.object(solve, "OUTLINE_EVERY", 0),
            patch.object(
                solve.store, "question_generation_lock", return_value=nullcontext()
            ),
            patch.object(
                solve.solve_attempt,
                "run_process",
                return_value=ProcessResult(False, failure=failure),
            ),
            patch.object(solve.store, "clear_solution_failure"),
            patch.object(
                solve.store,
                "put_solution_failure",
                side_effect=RuntimeError("storage unavailable"),
            ) as put_failure,
        ):
            with self.assertRaisesRegex(RuntimeError, "storage unavailable"):
                solve.solve_many("paper", [q], jobs=1)

        put_failure.assert_called_once_with(
            q["id"], "provider", "模型服务返回 HTTP 503", 3, "文本模型"
        )

    def test_one_terminal_failure_does_not_stop_another_question(self):
        first, second = question(1), question(2)
        failure = Failure("provider", "模型服务返回 HTTP 503", "文本模型")
        results = [ProcessResult(False, failure=failure)] * 3 + [
            ProcessResult(True, value=(True, "第二题成功"))
        ]
        with (
            patch.object(solve, "RETRY_DELAY", 0),
            patch.object(solve, "OUTLINE_EVERY", 0),
            patch.object(
                solve.store, "question_generation_lock", return_value=nullcontext()
            ),
            patch.object(solve.solve_attempt, "run_process", side_effect=results),
            patch.object(solve.store, "clear_solution_failure"),
            patch.object(solve.store, "put_solution_failure") as put_failure,
        ):
            result = solve.solve_many("paper", [first, second], jobs=1)

        self.assertEqual("fail", result[0][1])
        self.assertEqual((2, "ok", "第二题成功"), result[1])
        put_failure.assert_called_once_with(
            first["id"], "provider", "模型服务返回 HTTP 503", 3, "文本模型"
        )


class AttemptBoundaryTests(unittest.TestCase):
    def test_generation_lock_covers_clear_and_process_attempt(self):
        events = []

        @contextmanager
        def generation_lock(qid):
            events.append(("lock", qid))
            try:
                yield
            finally:
                events.append(("unlock", qid))

        def clear(qid):
            events.append(("clear", qid))

        def run_process(*_args, **_kwargs):
            events.append(("process", None))
            return ProcessResult(True, value=(True, "done"))

        q = question()
        with (
            patch.object(solve.store, "question_generation_lock", generation_lock),
            patch.object(solve.store, "clear_solution_failure", side_effect=clear),
            patch.object(solve.solve_attempt, "run_process", side_effect=run_process),
            patch.object(solve, "RETRY_DELAY", 0),
        ):
            result = solve.attempt_question("paper", q, False, False)

        self.assertTrue(result.ok)
        self.assertEqual(
            [("lock", q["id"]), ("clear", q["id"]), ("process", None),
             ("unlock", q["id"])],
            events,
        )

    def test_real_process_can_import_solve_module(self):
        result = solve.solve_attempt.run_process(
            "solve", "key_answer", (" A ",), timeout_s=5
        )

        self.assertTrue(result.ok, result.failure)
        self.assertEqual("a", result.value)


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def read(self):
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


class PostFailureTests(unittest.TestCase):
    @staticmethod
    def response_for(answer):
        content = json.dumps(answer, ensure_ascii=False)
        return json.dumps(
            {"choices": [{"message": {"content": content}}]}, ensure_ascii=False
        ).encode()

    def test_bad_endpoint_key_or_payload_is_safe_configuration_without_request(self):
        cases = [
            ("", "secret-key", {}, "empty base"),
            ("https://example.invalid", "", {}, "empty key"),
            ("secret://credential", "secret-key", {}, "invalid base"),
            ("https://secret host.invalid", "secret-key", {}, "whitespace base"),
            ("https://example.invalid", "secret-key", {"bad": object()}, "payload"),
        ]
        for base, key, payload, label in cases:
            with self.subTest(label=label):
                with patch.object(solve.urllib.request, "urlopen") as urlopen:
                    with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                        solve.post(base, key, payload, "文本模型")

                failure = caught.exception.failure
                self.assertEqual("configuration", failure.kind)
                self.assertEqual("文本模型", failure.stage)
                self.assertFalse(failure.retryable)
                self.assertNotIn("secret", failure.reason)
                urlopen.assert_not_called()

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

    def test_http_rejects_invalid_answer_schema(self):
        invalid = [
            {},
            {"answer": "  "},
            {"answer": "A", "steps": "not-a-list"},
            {"answer": "A", "key_facts": ["ok", 3]},
            {"answer": "A", "confidence": "certain"},
        ]
        for answer in invalid:
            with self.subTest(answer=answer):
                response = FakeResponse(self.response_for(answer))
                with patch.object(solve.urllib.request, "urlopen", return_value=response):
                    with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                        solve.post("https://example.invalid", "key", {}, "文本模型")

                self.assertEqual("invalid_response", caught.exception.failure.kind)
                self.assertEqual("文本模型", caught.exception.failure.stage)
                self.assertTrue(caught.exception.failure.retryable)

    def test_http_accepts_minimal_answer_and_need_figure(self):
        for answer in ({"answer": "A"}, {"answer": solve.NEED_FIGURE}):
            with self.subTest(answer=answer):
                response = FakeResponse(self.response_for(answer))
                with patch.object(solve.urllib.request, "urlopen", return_value=response):
                    got = solve.post(
                        "https://example.invalid", "key", {}, "文本模型"
                    )

                self.assertEqual(answer, got)

    def test_response_body_transport_failures_are_network_errors(self):
        errors = [
            ConnectionResetError("secret reset"),
            http.client.IncompleteRead(b"secret partial", 100),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with patch.object(
                    solve.urllib.request, "urlopen", return_value=FakeResponse(error)
                ):
                    with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                        solve.post("https://example.invalid", "key", {}, "视觉模型")

                failure = caught.exception.failure
                self.assertEqual("network", failure.kind)
                self.assertEqual("无法连接模型服务", failure.reason)
                self.assertEqual("视觉模型", failure.stage)
                self.assertTrue(failure.retryable)
                self.assertNotIn("secret", str(caught.exception))

    def test_http_timeout_reason_uses_effective_setting(self):
        with (
            patch.object(solve, "HTTP_TIMEOUT", 7),
            patch.object(solve.urllib.request, "urlopen", side_effect=socket.timeout()),
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.post("https://example.invalid", "key", {}, "文本模型")

        self.assertEqual("模型请求超过 7 秒", caught.exception.failure.reason)


class BackendConfigurationTests(unittest.TestCase):
    def test_doubao_requires_base_as_well_as_key(self):
        with (
            patch.object(solve, "VISION", "doubao"),
            patch.object(solve, "ARK_KEY", "secret-key"),
            patch.object(solve, "ARK_BASE", ""),
            patch.object(solve, "ask_doubao") as ask_doubao,
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask_vision("question", [])

        failure = caught.exception.failure
        self.assertEqual("configuration", failure.kind)
        self.assertEqual("视觉模型", failure.stage)
        self.assertFalse(failure.retryable)
        self.assertNotIn("secret", failure.reason)
        ask_doubao.assert_not_called()

    def test_subscription_requires_available_cli(self):
        with (
            patch.object(solve, "VISION", "subscription"),
            patch.object(solve.cliask, "available", return_value=False),
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask_vision("question", [])

        self.assertEqual("configuration", caught.exception.failure.kind)
        self.assertEqual("视觉模型", caught.exception.failure.stage)
        self.assertFalse(caught.exception.failure.retryable)

    def test_legacy_backend_requires_configured_cli(self):
        with patch.object(solve, "CLI", None):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask("question", [])

        self.assertEqual("configuration", caught.exception.failure.kind)
        self.assertEqual("视觉模型", caught.exception.failure.stage)
        self.assertFalse(caught.exception.failure.retryable)

    def test_missing_optional_deepseek_key_uses_visual_fallback(self):
        q = question()
        q.update({"pages": [1, 1], "stem": "题干"})
        answer = {
            "answer": "A",
            "steps": [],
            "key_facts": [],
            "assumptions": [],
            "unreadable": [],
            "confidence": "high",
        }
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(solve, "BACKEND", "deepseek-first"),
                patch.object(solve, "DS_KEY", ""),
                patch.object(solve.store, "find_page", return_value=object()),
                patch.object(solve.store, "read_asset", return_value=b"image"),
                patch.object(solve.store, "solution_fresh", return_value=False),
                patch.object(solve.store, "put_solution") as put_solution,
                patch.object(solve, "ask_deepseek") as ask_deepseek,
                patch.object(solve, "ask_vision", return_value=(answer, "vision-model")) as visual,
            ):
                fresh, _ = solve.solve_one("paper", q, directory)

        self.assertTrue(fresh)
        ask_deepseek.assert_not_called()
        visual.assert_called_once()
        put_solution.assert_called_once()


class CliFailureTests(unittest.TestCase):
    def assert_safe_failure(self, caught, kind):
        failure = caught.exception.failure
        self.assertEqual(kind, failure.kind)
        self.assertEqual("视觉模型", failure.stage)
        self.assertNotIn("secret", failure.reason)

    def test_subscription_timeout_is_safe_timeout(self):
        with patch.object(
            solve.cliask,
            "ask",
            side_effect=subprocess.TimeoutExpired("secret-command", 1800),
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask_subscription("question", [])

        self.assert_safe_failure(caught, "timeout")
        self.assertTrue(caught.exception.failure.retryable)

    def test_subscription_execution_failure_is_safe_provider_failure(self):
        with patch.object(
            solve.cliask, "ask", side_effect=RuntimeError("secret provider output")
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask_subscription("question", [])

        self.assert_safe_failure(caught, "provider")
        self.assertTrue(caught.exception.failure.retryable)

    def test_subscription_auth_failure_is_nonretryable_configuration(self):
        with patch.object(
            solve.cliask,
            "ask",
            side_effect=RuntimeError("HTTP 401 authentication secret credential"),
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask_subscription("question", [])

        self.assert_safe_failure(caught, "configuration")
        self.assertFalse(caught.exception.failure.retryable)

    def test_subscription_invalid_answer_is_safe_invalid_response(self):
        with patch.object(solve.cliask, "ask", return_value="secret malformed answer"):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask_subscription("question", [])

        self.assert_safe_failure(caught, "invalid_response")
        self.assertTrue(caught.exception.failure.retryable)

    def test_subscription_validates_decoded_answer_schema(self):
        invalid = [
            {},
            {"answer": ""},
            {"answer": "A", "assumptions": {}},
            {"answer": "A", "confidence": "unknown"},
        ]
        for answer in invalid:
            with self.subTest(answer=answer):
                with patch.object(
                    solve.cliask, "ask", return_value=json.dumps(answer)
                ):
                    with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                        solve.ask_subscription("question", [])

                self.assert_safe_failure(caught, "invalid_response")

        with patch.object(
            solve.cliask, "ask", return_value=json.dumps({"answer": "A"})
        ):
            self.assertEqual(
                {"answer": "A"}, solve.ask_subscription("question", [])
            )

    def test_legacy_cli_timeout_is_safe_timeout(self):
        with (
            patch.object(solve, "CLI", "/secret/claude"),
            patch.object(
                solve.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("secret-command", 1800),
            ),
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask("question", [])

        self.assert_safe_failure(caught, "timeout")

    def test_legacy_cli_nonzero_exit_is_safe_provider_failure(self):
        completed = subprocess.CompletedProcess(
            ["/secret/claude"], 1, stdout="", stderr="secret provider output"
        )
        with (
            patch.object(solve, "CLI", "/secret/claude"),
            patch.object(solve.subprocess, "run", return_value=completed),
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask("question", [])

        self.assert_safe_failure(caught, "provider")

    def test_legacy_cli_auth_failure_is_nonretryable_configuration(self):
        completed = subprocess.CompletedProcess(
            ["/secret/claude"], 1, stdout="", stderr="billing balance secret"
        )
        with (
            patch.object(solve, "CLI", "/secret/claude"),
            patch.object(solve.subprocess, "run", return_value=completed),
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask("question", [])

        self.assert_safe_failure(caught, "configuration")
        self.assertFalse(caught.exception.failure.retryable)

    def test_legacy_cli_launch_configuration_failure_is_nonretryable(self):
        for error in (FileNotFoundError("secret path"), PermissionError("secret path")):
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(solve, "CLI", "/secret/claude"),
                    patch.object(solve.subprocess, "run", side_effect=error),
                ):
                    with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                        solve.ask("question", [])

                self.assert_safe_failure(caught, "configuration")
                self.assertFalse(caught.exception.failure.retryable)

    def test_legacy_cli_invalid_answer_is_safe_invalid_response(self):
        completed = subprocess.CompletedProcess(
            ["/secret/claude"], 0, stdout="secret malformed answer", stderr=""
        )
        with (
            patch.object(solve, "CLI", "/secret/claude"),
            patch.object(solve.subprocess, "run", return_value=completed),
        ):
            with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                solve.ask("question", [])

        self.assert_safe_failure(caught, "invalid_response")

    def test_legacy_cli_validates_decoded_answer_schema(self):
        for answer in ({}, {"answer": " "}, {"answer": "A", "unreadable": "bad"},
                       {"answer": "A", "confidence": "bad"}):
            with self.subTest(answer=answer):
                completed = subprocess.CompletedProcess(
                    ["/secret/claude"], 0, stdout=json.dumps(answer), stderr=""
                )
                with (
                    patch.object(solve, "CLI", "/secret/claude"),
                    patch.object(solve.subprocess, "run", return_value=completed),
                ):
                    with self.assertRaises(solve.solve_attempt.SolveFailure) as caught:
                        solve.ask("question", [])

                self.assert_safe_failure(caught, "invalid_response")

        completed = subprocess.CompletedProcess(
            ["/secret/claude"], 0, stdout=json.dumps({"answer": "A"}), stderr=""
        )
        with (
            patch.object(solve, "CLI", "/secret/claude"),
            patch.object(solve.subprocess, "run", return_value=completed),
        ):
            self.assertEqual({"answer": "A"}, solve.ask("question", []))


class EffectiveSettingsTests(unittest.TestCase):
    def test_positive_and_nonnegative_env_values_fall_back_safely(self):
        cases = [
            ("bad", 300, 1, 300),
            ("0", 300, 1, 300),
            ("-4", 3, 0, 3),
            ("0", 3, 0, 0),
            ("12", 3, 1, 12),
        ]
        for raw, default, minimum, expected in cases:
            with self.subTest(raw=raw, minimum=minimum):
                with patch.dict(os.environ, {"EXAM_TEST_SETTING": raw}):
                    self.assertEqual(
                        expected,
                        solve.env_int("EXAM_TEST_SETTING", default, minimum),
                    )

    def test_attempt_timeout_reason_uses_effective_setting(self):
        result = ProcessResult(
            False,
            failure=Failure("timeout", "generic", "process"),
        )
        with patch.object(solve, "ATTEMPT_TIMEOUT", 7):
            translated = solve._safe_attempt_result(result)

        self.assertEqual("完整解题超过 7 秒", translated.failure.reason)

    def test_hard_max_attempts_is_exactly_three(self):
        self.assertEqual(3, solve.MAX_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
