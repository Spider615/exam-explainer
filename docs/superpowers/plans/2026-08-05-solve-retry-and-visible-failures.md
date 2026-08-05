# Solve Retry and Visible Failures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every stage③ question at most three isolated five-minute attempts, persist the final failure, and show that reason everywhere the UI currently says only “stopped” or “not generated.”

**Architecture:** A small `pipeline/solve_attempt.py` module owns process isolation, hard deadlines, retry counting, and safe error serialization. `solve.py` keeps the physics/model flow but delegates each complete `solve_one` attempt to that module; `store.py` persists a mutually exclusive `solution_failures` row. API progress treats success plus terminal failure as stage③ completion, while downstream stages continue to consume successes only.

**Tech Stack:** Python 3 standard library (`multiprocessing`, `unittest`), PostgreSQL/psycopg, FastAPI, React 18, TypeScript, Vite.

---

## File map

- Create `pipeline/solve_attempt.py`: isolated child execution, process-group termination, retry policy, safe structured failures.
- Create `tests/process_fixtures.py`: importable child targets used by spawn-based timeout tests.
- Create `tests/test_solve_attempt.py`: red/green tests for three attempts, non-retryable failures, and hard process termination.
- Create `tests/test_store_failures.py`: storage contract tests using mocked psycopg connections.
- Create `tests/test_solve_many_retries.py`: stage③ wiring tests without making model calls.
- Create `tests/test_progress.py`: pure stage/API status tests.
- Modify `pipeline/schema.sql`: add `solution_failures`.
- Modify `pipeline/store.py`: CRUD/query failure state, progress count, success/failure mutual exclusion.
- Modify `pipeline/solve.py`: remove nested HTTP retries, classify provider failures, run each full question through the isolated retry boundary.
- Modify `pipeline/api.py`: expose failure counts and per-question details; advance stage③ after all questions reach a terminal state.
- Modify `web/src/types.ts`: add `SolutionFailure` and count fields.
- Modify `web/src/components/PaperList.tsx`: show completed-with-failures in the library.
- Modify `web/src/components/PaperView.tsx`: poll failure count, show top summary, and distinguish failed answers in the overview.
- Modify `web/src/components/QuestionCard.tsx`: show the persisted reason in the failed question.
- Modify `web/src/styles.css`: style failure summary/card states.

The existing working tree already has user changes in `PaperView.tsx` and `styles.css`. Edit those files surgically and do not stage or commit them; backend and newly clean frontend files may be committed by exact path.

### Task 1: Isolated attempt runner and retry policy

**Files:**
- Create: `pipeline/solve_attempt.py`
- Create: `tests/__init__.py`
- Create: `tests/process_fixtures.py`
- Create: `tests/test_solve_attempt.py`

- [ ] **Step 1: Write failing retry-policy tests**

Create tests that describe “at most three total attempts,” eventual success, and early stop for local configuration failures:

```python
# tests/test_solve_attempt.py
import os
import tempfile
import time
import unittest

from pipeline.solve_attempt import Failure, ProcessResult, retry, run_process


class RetryTests(unittest.TestCase):
    def test_third_attempt_can_succeed(self):
        seen = []

        def attempt(n):
            seen.append(n)
            if n < 3:
                return ProcessResult(False, failure=Failure(
                    "timeout", "完整解题超过 5 分钟", "完整解题", True))
            return ProcessResult(True, value=(True, "ok"))

        got = retry(attempt, max_attempts=3, delay_s=0)
        self.assertTrue(got.ok)
        self.assertEqual([1, 2, 3], seen)
        self.assertEqual(3, got.attempts)

    def test_three_failures_are_terminal(self):
        got = retry(lambda _n: ProcessResult(False, failure=Failure(
            "network", "模型服务连接失败", "视觉模型", True)),
            max_attempts=3, delay_s=0)
        self.assertFalse(got.ok)
        self.assertEqual(3, got.attempts)
        self.assertEqual("network", got.failure.kind)

    def test_non_retryable_failure_stops_immediately(self):
        seen = []

        def attempt(n):
            seen.append(n)
            return ProcessResult(False, failure=Failure(
                "configuration", "缺少模型密钥", "配置", False))

        got = retry(attempt, max_attempts=3, delay_s=0)
        self.assertEqual([1], seen)
        self.assertEqual(1, got.attempts)


class ProcessDeadlineTests(unittest.TestCase):
    def test_timed_out_child_cannot_keep_running(self):
        with tempfile.TemporaryDirectory() as td:
            marker = os.path.join(td, "late-write")
            got = run_process("tests.process_fixtures", "late_write",
                              (marker, 0.25), timeout_s=0.05)
            self.assertFalse(got.ok)
            self.assertEqual("timeout", got.failure.kind)
            time.sleep(0.30)
            self.assertFalse(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
```

Use an importable spawn target:

```python
# tests/process_fixtures.py
import time

from pipeline.solve_attempt import SolveFailure


def late_write(path, delay):
    time.sleep(delay)
    with open(path, "w", encoding="utf-8") as f:
        f.write("child survived")
    return "late"


def fail_configuration():
    raise SolveFailure("configuration", "缺少模型密钥", "配置", retryable=False)
```

- [ ] **Step 2: Run the tests and verify the red state**

Run:

```bash
python -m unittest tests.test_solve_attempt -v
```

Expected: import failure because `pipeline.solve_attempt` does not exist.

- [ ] **Step 3: Implement the minimal attempt module**

Implement these public contracts in `pipeline/solve_attempt.py`:

```python
from dataclasses import asdict, dataclass
import importlib
import multiprocessing
import os
import signal
import time


@dataclass(frozen=True)
class Failure:
    kind: str
    reason: str
    stage: str
    retryable: bool = True


@dataclass(frozen=True)
class ProcessResult:
    ok: bool
    value: object = None
    failure: Failure | None = None


@dataclass(frozen=True)
class RetryResult(ProcessResult):
    attempts: int = 0


class SolveFailure(RuntimeError):
    def __init__(self, kind, reason, stage, retryable=True):
        super().__init__(reason)
        self.failure = Failure(kind, reason[:240], stage, retryable)


def _as_failure(exc):
    if isinstance(exc, SolveFailure):
        return exc.failure
    text = " ".join(str(exc).split())[:240] or type(exc).__name__
    return Failure("internal", "解题过程异常：" + text, "完整解题", True)


def _child(conn, module_name, function_name, args):
    try:
        if hasattr(os, "setsid"):
            os.setsid()
        fn = getattr(importlib.import_module(module_name), function_name)
        conn.send((True, fn(*args)))
    except BaseException as exc:
        conn.send((False, asdict(_as_failure(exc))))
    finally:
        conn.close()


def _stop(proc):
    if not proc.is_alive():
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (AttributeError, ProcessLookupError, PermissionError):
        proc.terminate()
    proc.join(1)
    if proc.is_alive():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (AttributeError, ProcessLookupError, PermissionError):
            proc.kill()
        proc.join(1)


def run_process(module_name, function_name, args, timeout_s):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child,
                       args=(child, module_name, function_name, args))
    proc.start()
    child.close()
    if not parent.poll(timeout_s):
        _stop(proc)
        parent.close()
        return ProcessResult(False, failure=Failure(
            "timeout", "完整解题超过 5 分钟", "完整解题", True))
    try:
        ok, payload = parent.recv()
    except EOFError:
        ok = False
        payload = asdict(Failure(
            "internal", "解题子进程异常退出", "完整解题", True))
    parent.close()
    proc.join(1)
    if proc.is_alive():
        _stop(proc)
    if ok:
        return ProcessResult(True, value=payload)
    return ProcessResult(False, failure=Failure(**payload))


def retry(attempt, max_attempts=3, delay_s=3, on_retry=None):
    last = None
    for number in range(1, max_attempts + 1):
        result = attempt(number)
        if result.ok:
            return RetryResult(True, value=result.value, attempts=number)
        last = result.failure
        if not last.retryable or number == max_attempts:
            return RetryResult(False, failure=last, attempts=number)
        if on_retry:
            on_retry(number, last)
        if delay_s:
            time.sleep(delay_s)
    raise AssertionError("retry loop ended without a result")
```

- [ ] **Step 4: Run tests and verify green**

Run:

```bash
python -m unittest tests.test_solve_attempt -v
```

Expected: 4 tests pass and no marker file is written after the timeout.

- [ ] **Step 5: Commit the isolated unit**

```bash
git add pipeline/solve_attempt.py tests/__init__.py tests/process_fixtures.py tests/test_solve_attempt.py
git commit -m "feat: add isolated solve attempt retries"
```

### Task 2: Persist terminal question failures

**Files:**
- Modify: `pipeline/schema.sql`
- Modify: `pipeline/store.py:647-675`
- Modify: `pipeline/store.py:466-548`
- Create: `tests/test_store_failures.py`

- [ ] **Step 1: Write failing storage contract tests**

Use `unittest.mock` to verify SQL intent without depending on the developer database:

```python
# tests/test_store_failures.py
import unittest
from unittest.mock import MagicMock, patch

from pipeline import store


def fake_connection(rows=()):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value = conn
    conn.fetchall.return_value = list(rows)
    return conn


class FailureStoreTests(unittest.TestCase):
    def test_put_solution_failure_upserts_terminal_state(self):
        conn = fake_connection()
        with patch.object(store, "connect", return_value=conn):
            store.put_solution_failure(17, "timeout", "视觉模型超时", 3, "视觉模型")
        sql = "\n".join(str(c.args[0]) for c in conn.execute.call_args_list)
        self.assertIn("INSERT INTO solution_failures", sql)
        self.assertIn("ON CONFLICT", sql)
        conn.commit.assert_called_once()

    def test_success_deletes_old_failure_in_same_transaction(self):
        conn = fake_connection()
        data = {"answer": "A", "steps": [], "key_facts": [],
                "assumptions": [], "confidence": "high"}
        with patch.object(store, "connect", return_value=conn):
            store.put_solution(17, data, "sha", "model")
        sql = "\n".join(str(c.args[0]) for c in conn.execute.call_args_list)
        self.assertIn("INSERT INTO solutions", sql)
        self.assertIn("DELETE FROM solution_failures", sql)
        conn.commit.assert_called_once()

    def test_terminal_failure_deletes_old_solution_in_same_transaction(self):
        conn = fake_connection()
        with patch.object(store, "connect", return_value=conn):
            store.put_solution_failure(17, "timeout", "视觉模型超时", 3, "视觉模型")
        sql = "\n".join(str(c.args[0]) for c in conn.execute.call_args_list)
        self.assertIn("DELETE FROM solutions", sql)
        self.assertIn("INSERT INTO solution_failures", sql)
        conn.commit.assert_called_once()

    def test_paper_failures_are_keyed_by_question_number(self):
        conn = fake_connection([(15, "timeout", "视觉模型超时", 3,
                                 "视觉模型", "2026-08-05T12:00:00+08:00")])
        with patch.object(store, "connect", return_value=conn):
            got = store.paper_solution_failures("卷名")
        self.assertEqual("timeout", got[15]["kind"])
        self.assertEqual(3, got[15]["attempts"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the tests fail for missing store methods**

Run:

```bash
python -m unittest tests.test_store_failures -v
```

Expected: failures naming `put_solution_failure` and `paper_solution_failures`.

- [ ] **Step 3: Add the schema and storage methods**

Add to `pipeline/schema.sql` immediately after `solutions`:

```sql
CREATE TABLE IF NOT EXISTS solution_failures (
  question_id bigint PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  kind        text        NOT NULL,
  reason      text        NOT NULL,
  attempts    int         NOT NULL,
  stage       text        NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
```

Add focused store functions:

```python
def clear_solution_failure(qid):
    with connect() as c:
        c.execute("DELETE FROM solution_failures WHERE question_id=%s", (qid,))
        c.commit()


def put_solution_failure(qid, kind, reason, attempts, stage):
    with connect() as c:
        # 终态只能有一个：不让旧答案与本轮失败同时出现在页面和进度统计里。
        c.execute("DELETE FROM solutions WHERE question_id=%s", (qid,))
        c.execute("""
            INSERT INTO solution_failures (question_id, kind, reason, attempts, stage)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (question_id) DO UPDATE SET
              kind=EXCLUDED.kind, reason=EXCLUDED.reason,
              attempts=EXCLUDED.attempts, stage=EXCLUDED.stage, updated_at=now()
        """, (qid, kind, reason[:240], attempts, stage))
        c.commit()


def paper_solution_failures(name):
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT q.n, f.kind, f.reason, f.attempts, f.stage, f.updated_at
              FROM solution_failures f
              JOIN questions q ON q.id=f.question_id
              JOIN papers p ON p.id=q.paper_id
             WHERE p.name=%s
             ORDER BY q.n
        """, (name,))
        return {r[0]: {"kind": r[1], "reason": r[2], "attempts": r[3],
                       "stage": r[4], "updated_at": r[5].isoformat()
                       if hasattr(r[5], "isoformat") else str(r[5])}
                for r in cur.fetchall()}
```

In `put_solution`, execute this before its single `commit()`:

```python
c.execute("DELETE FROM solution_failures WHERE question_id=%s", (qid,))
```

Extend the `progress()` SELECT immediately after the solutions count:

```sql
(SELECT count(*) FROM solution_failures f
  JOIN questions q ON q.id=f.question_id
 WHERE q.paper_id=p.id),
```

Unpack it as `n_sol_fail` after `n_sol`, return it as:

```python
"solutionFailures": n_sol_fail,
```

Add this operand to the `GREATEST(...)` last-change expression in both `progress()` and `assembled()`:

```sql
COALESCE((SELECT max(f.updated_at) FROM solution_failures f
            JOIN questions q ON q.id=f.question_id
           WHERE q.paper_id=p.id), p.updated_at)
```

This makes a newly recorded failure invalidate an older assembled artifact.

- [ ] **Step 4: Run storage tests and syntax checks**

Run:

```bash
python -m unittest tests.test_store_failures -v
python -m py_compile pipeline/store.py
```

Expected: all storage tests pass and `py_compile` exits 0.

- [ ] **Step 5: Commit the persistence layer**

```bash
git add pipeline/schema.sql pipeline/store.py tests/test_store_failures.py
git commit -m "feat: persist terminal solve failures"
```

### Task 3: Wire stage③ through the three-attempt boundary

**Files:**
- Modify: `pipeline/solve.py:190-235`
- Modify: `pipeline/solve.py:448-485`
- Modify: `pipeline/api.py:321-351`
- Create: `tests/test_solve_many_retries.py`

- [ ] **Step 1: Write failing orchestration tests**

Patch the child runner so tests never call a model:

```python
# tests/test_solve_many_retries.py
import unittest
from unittest.mock import patch

from pipeline import solve
from pipeline.solve_attempt import Failure, ProcessResult


class SolveManyRetryTests(unittest.TestCase):
    def test_third_attempt_success_does_not_persist_failure(self):
        results = iter([
            ProcessResult(False, failure=Failure("timeout", "超时", "完整解题")),
            ProcessResult(False, failure=Failure("network", "断线", "视觉模型")),
            ProcessResult(True, value=(True, "答案 A")),
        ])
        q = {"id": 99, "n": 15}
        with patch.object(solve.solve_attempt, "run_process", side_effect=lambda *a, **k: next(results)), \
             patch.object(solve.store, "clear_solution_failure") as clear, \
             patch.object(solve.store, "put_solution_failure") as put:
            got = solve.solve_many("卷名", [q], jobs=1)
        self.assertEqual("ok", got[0][1])
        self.assertEqual(1, clear.call_count)
        put.assert_not_called()

    def test_three_failures_are_persisted_and_returned(self):
        failure = Failure("timeout", "完整解题超过 5 分钟", "完整解题")
        q = {"id": 99, "n": 15}
        with patch.object(solve.solve_attempt, "run_process",
                          return_value=ProcessResult(False, failure=failure)) as run, \
             patch.object(solve.store, "clear_solution_failure"), \
             patch.object(solve.store, "put_solution_failure") as put, \
             patch.object(solve.solve_attempt.time, "sleep"):
            got = solve.solve_many("卷名", [q], jobs=1)
        self.assertEqual(3, run.call_count)
        self.assertEqual("fail", got[0][1])
        put.assert_called_once_with(99, "timeout", failure.reason, 3, "完整解题")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify orchestration tests fail**

Run:

```bash
python -m unittest tests.test_solve_many_retries -v
```

Expected: failure because `solve_many` still calls `solve_one` directly.

- [ ] **Step 3: Make every question use the isolated retry runner**

Import `solve_attempt`, define explicit settings, and replace the direct `solve_one` call inside `solve_many.run`:

```python
ATTEMPT_TIMEOUT = int(os.environ.get("EXAM_SOLVE_ATTEMPT_TIMEOUT", "300"))
MAX_ATTEMPTS = int(os.environ.get("EXAM_SOLVE_ATTEMPTS", "3"))
RETRY_DELAY = int(os.environ.get("EXAM_SOLVE_RETRY_DELAY", "3"))


def attempt_question(name, q, force, crosscheck, on_retry=None):
    store.clear_solution_failure(q["id"])

    def attempt(_number):
        with tempfile.TemporaryDirectory() as tmp:
            return solve_attempt.run_process(
                "solve", "solve_one", (name, q, tmp, force, crosscheck),
                timeout_s=ATTEMPT_TIMEOUT)

    return solve_attempt.retry(attempt, MAX_ATTEMPTS, RETRY_DELAY, on_retry)
```

Use `attempt_question` in the worker. On terminal failure call:

```python
store.put_solution_failure(q["id"], result.failure.kind,
                           result.failure.reason, result.attempts,
                           result.failure.stage)
```

Return the existing `(question_number, "fail", note)` tuple so the rest of the pipeline remains compatible. Add an optional `on_retry(q, completed_attempt, failure)` callback to `solve_many`; in `api.solve_paper`, log messages such as `第15题 第1/3次失败：视觉模型请求超时；准备重试`.

- [ ] **Step 4: Remove multiplied retries and classify model errors**

Change `post` to make exactly one HTTP request per full-question attempt. Wrap errors in `solve_attempt.SolveFailure`:

```python
def post(base, key, payload, stage):
    try:
        request = urllib.request.Request(
            base + "/chat/completions", json.dumps(payload).encode(),
            {"Authorization": "Bearer " + key,
             "Content-Type": "application/json"})
        response = urllib.request.urlopen(request, timeout=HTTP_TIMEOUT).read()
        data = json.loads(response)
        return loads_json(data["choices"][0]["message"]["content"])
    except urllib.error.HTTPError as exc:
        retryable = exc.code == 429 or exc.code >= 500
        kind = "provider" if retryable else "configuration"
        raise solve_attempt.SolveFailure(
            kind, f"模型服务返回 HTTP {exc.code}", stage, retryable) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise solve_attempt.SolveFailure(
            "timeout", "模型请求超过 5 分钟", stage, True) from exc
    except urllib.error.URLError as exc:
        raise solve_attempt.SolveFailure(
            "network", "无法连接模型服务", stage, True) from exc
    except (json.JSONDecodeError, KeyError, RuntimeError) as exc:
        raise solve_attempt.SolveFailure(
            "invalid_response", "模型返回内容无法解析为答案", stage, True) from exc
```

Pass `文本模型` or `视觉模型` from each caller. Convert missing-key and missing-CLI checks to non-retryable `configuration` failures. Wrap subscription/CLI `TimeoutExpired` as retryable `timeout`. Remove `HTTP_TRIES` so the maximum remains three complete attempts, not three outer attempts multiplied by hidden inner retries.

- [ ] **Step 5: Run targeted and combined backend tests**

Run:

```bash
python -m unittest tests.test_solve_attempt tests.test_store_failures tests.test_solve_many_retries -v
python -m py_compile pipeline/solve.py pipeline/api.py
```

Expected: all tests pass; syntax checks exit 0.

- [ ] **Step 6: Commit stage③ wiring**

```bash
git add pipeline/solve.py pipeline/api.py tests/test_solve_many_retries.py
git commit -m "feat: retry timed-out question solves three times"
```

### Task 4: Advance progress with terminal failures and expose API details

**Files:**
- Modify: `pipeline/api.py:598-705`
- Modify: `pipeline/api.py:770-880`
- Create: `tests/test_progress.py`

- [ ] **Step 1: Write failing progress semantics tests**

```python
# tests/test_progress.py
import unittest

from pipeline.api import stage_of


def progress(**changes):
    base = dict(questions=15, solutions=14, solutionFailures=0, labels=15,
                judged=14, specsWorth=0, worth=0, drafts=0, specs=0,
                approved=0, sceneTried=0, ready=0, assembledFresh=True)
    base.update(changes)
    return base


class StageProgressTests(unittest.TestCase):
    def test_unresolved_question_stays_in_solve(self):
        self.assertEqual("solve", stage_of(progress())[0])

    def test_terminal_failure_finishes_solve_stage(self):
        code, _label, _short, _cur, _total = stage_of(
            progress(solutionFailures=1))
        self.assertEqual("done", code)

    def test_downstream_denominator_uses_successes_only(self):
        code, _label, _short, cur, total = stage_of(progress(
            solutionFailures=1, judged=13))
        self.assertEqual("pick", code)
        self.assertEqual((13, 14), (cur, total))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the new terminal-state test fails**

Run:

```bash
python -m unittest tests.test_progress -v
```

Expected: the failure-count case still returns `solve`.

- [ ] **Step 3: Update API stage and response contracts**

At the start of `stage_of` use:

```python
q, sol = pg["questions"], pg["solutions"]
terminal = sol + pg.get("solutionFailures", 0)
if terminal < q:
    return "solve", "③ 解题", "解题中", terminal, q
```

Keep every later denominator based on `sol`, not `terminal`.

In the full paper endpoint, load once:

```python
failures = store.paper_solution_failures(name)
```

For each question translate the store's snake-case timestamp to the frontend contract:

```python
failure = failures.get(x["n"])

"solutionFailure": failure and {
    "kind": failure["kind"],
    "reason": failure["reason"],
    "attempts": failure["attempts"],
    "stage": failure["stage"],
    "updatedAt": failure["updated_at"],
},
```

Return `coverage` as:

```python
"coverage": {"solved": len(sols), "failed": len(failures), "total": len(qs)}
```

The progress endpoint already spreads the store result. Add this field to the list summary’s nested progress object:

```python
"solutionFailures": pg["solutionFailures"],
```

A completed paper with failures remains `done=True`, with the nonzero failure count carried separately.

- [ ] **Step 4: Run API semantics tests**

Run:

```bash
python -m unittest tests.test_progress -v
python -m py_compile pipeline/api.py
```

Expected: 3 progress tests pass and syntax check exits 0.

- [ ] **Step 5: Commit API semantics**

```bash
git add pipeline/api.py tests/test_progress.py
git commit -m "feat: expose terminal question failures in paper APIs"
```

### Task 5: Show failures in the React UI

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/components/PaperList.tsx`
- Modify: `web/src/components/PaperView.tsx`
- Modify: `web/src/components/QuestionCard.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Establish a failing frontend build with the new contract**

Add the data types first and reference `q.solutionFailure` in `QuestionCard` before adding it to the `Question` interface. Run the build and confirm TypeScript reports that the property does not exist:

```bash
cd web && npm run build
```

Expected: `TS2339: Property 'solutionFailure' does not exist on type 'Question'`.

- [ ] **Step 2: Add exact TypeScript contracts**

Add:

```typescript
export interface SolutionFailure {
  kind: 'timeout' | 'network' | 'provider' | 'invalid_response' | 'configuration' | 'internal'
  reason: string
  attempts: number
  stage: string
  updatedAt: string
}
```

Add `solutionFailure: SolutionFailure | null` to `Question`, `failed: number` to `Paper.coverage`, and `solutionFailures: number` to both `Progress` and `PaperSummary.progress`.

- [ ] **Step 3: Render the per-question failure instead of “not generated”**

In `QuestionCard`, replace the missing-answer branch with three states:

```tsx
{q.solution ? <SolutionBody s={q.solution} />
  : q.solutionFailure ? (
    <div className="solve-fail">
      <b>生成失败</b>
      <span>{q.solutionFailure.reason}</span>
      <small>
        {q.solutionFailure.stage} · 已尝试 {q.solutionFailure.attempts} 次
      </small>
    </div>
  ) : (
    <div className="missing">
      <b>尚未生成</b><br />
      这道题还没跑过阶段③（解题）。
    </div>
  )}
```

- [ ] **Step 4: Show failure summaries and make polling refresh them**

In `PaperView`:

- Include `p.solutionFailures` in the polling `key`.
- Make `shortOf` return `{ text: '生成失败', kind: 'failed' }` before its `!solution` branch when `q.solutionFailure` exists.
- Give quick-answer failures a `failed` class.
- Compute `const failedQuestions = paper.questions.filter((q) => q.solutionFailure)`.
- Directly below the progress panel, render a persistent `.solve-fail-summary` with buttons that call the existing `jumpTo(q.n)` and show each reason.
- Show stage③ progress as successes plus terminal failures, while retaining a visible `失败 N` label.

The summary markup should follow this contract:

```tsx
{failedQuestions.length > 0 && (
  <div className="banner bad solve-fail-summary">
    <b>有 {failedQuestions.length} 道题生成失败</b>
    <ul>{failedQuestions.map((q) => (
      <li key={q.n}>
        <button onClick={() => jumpTo(q.n)}>第 {q.n} 题</button>
        <span>{q.solutionFailure!.reason}</span>
      </li>
    ))}</ul>
  </div>
)}
```

In `PaperList.Prog`, check `p.solutionFailures` before the plain completed case and return `已完成 · N题失败`. Do not reuse `p.failed`, which means the whole in-memory job crashed.

- [ ] **Step 5: Add focused styles**

Append styles using existing red tokens:

```css
.solve-fail{display:flex;flex-direction:column;gap:5px;padding:12px 14px;
  border:1px solid var(--red);border-left:3px solid var(--red);
  background:var(--red2);color:var(--red);font-size:13px}
.solve-fail small{font-family:var(--mono);color:var(--ink3)}
.solve-fail-summary ul{margin:8px 0 0;padding-left:18px}
.solve-fail-summary li{margin:4px 0}
.solve-fail-summary button{border:0;background:none;color:var(--red);
  padding:0 7px 0 0;text-decoration:underline;cursor:pointer;font:inherit}
.quick-a.failed{color:var(--red);font-size:11px;font-weight:600}
```

- [ ] **Step 6: Build the frontend**

Run:

```bash
cd web && npm run build
```

Expected: `tsc -b && vite build` exits 0 with no TypeScript errors.

- [ ] **Step 7: Preserve pre-existing working-tree changes**

Run:

```bash
git diff -- web/src/App.tsx web/src/api.ts web/src/components/PaperView.tsx web/src/components/Upload.tsx web/src/styles.css
```

Inspect that the existing upload/progress/login changes remain. Do not stage or commit `PaperView.tsx` or `styles.css`, because both were modified before this feature began. If committing the clean files, stage only:

```bash
git add web/src/types.ts web/src/components/PaperList.tsx web/src/components/QuestionCard.tsx
git commit -m "feat: show question solve failures"
```

### Task 6: Migrate, verify, and rerun the original failed question

**Files:**
- No source changes expected.

- [ ] **Step 1: Run the full local verification suite**

Run:

```bash
python -m unittest discover -s tests -v
python -m py_compile pipeline/solve_attempt.py pipeline/solve.py pipeline/store.py pipeline/api.py
cd web && npm run build
```

Expected: all unit tests pass, Python compilation exits 0, and Vite produces a successful build.

- [ ] **Step 2: Apply the idempotent schema migration**

Run from the repository root:

```bash
python pipeline/store.py init
```

Expected: exit 0; rerunning is safe because the table uses `CREATE TABLE IF NOT EXISTS`.

- [ ] **Step 3: Verify the current database starts with question 15 unresolved**

Run this read-only check and confirm it prints `questions 15`, `solutions 14`, and no key `15` in `solution_keys`:

```bash
python -c "from pipeline import store; n='2024年高考江西卷物理真题'; p=store.progress(n); s=store.paper_solutions(n); print('questions', p['questions']); print('solutions', p['solutions']); print('solution_keys', sorted(s))"
```

- [ ] **Step 4: Run a controlled stage③ retry for question 15**

Run:

```bash
python pipeline/solve.py '2024年高考江西卷物理真题' --only 15 -j 1 --force
```

Expected: either the answer succeeds within at most three attempts, or the command ends with one persisted, normalized failure after three attempts. It must not remain silently unresolved.

- [ ] **Step 5: Verify the persisted terminal state**

Run:

```bash
python -c "from pipeline import store; n='2024年高考江西卷物理真题'; s=store.paper_solutions(n); f=store.paper_solution_failures(n); p=store.progress(n); assert (15 in s) != (15 in f); assert 15 in s or f[15]['attempts'] in (1,3); assert p['solutions'] + p['solutionFailures'] == 15; print({'q15_solution': 15 in s, 'q15_failure': f.get(15), 'progress': (p['solutions'] + p['solutionFailures'], p['questions'])})"
```

Expected: the assertion passes and exactly one of these is true for question 15:

- A solution exists and no failure row exists.
- A failure exists with `attempts == 3` (or `1` only for a non-retryable configuration problem) and no solution row exists.

Also verify stage③ progress is 15/15 terminal questions.

- [ ] **Step 6: Verify the browser-facing responses**

With the local API/Web app running, open the paper detail page and confirm:

- The list does not say “③ 解题 · 已停止 14/15”.
- If question 15 failed, the library, top summary, answer overview, and question card all show the reason.
- If question 15 succeeded, no stale failure warning appears.
- Reloading the page preserves the same state.

- [ ] **Step 7: Final diff and status audit**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Expected: no whitespace errors; pre-existing unrelated files remain present and unchanged in scope. Report any intentionally uncommitted overlapping frontend files in the handoff.
