# 步一：只有参考答案的卷子 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 老师传几张参考答案图片和几张题目图片，得到一份「卷子」：每题有题干、标准答案、官方解答过程、知识点标签。**不碰答题卡。**

**Architecture:** 新增一条与 `①②③` 平行的轻链：`pages.py` 把图规范化 → `refread.py` 逐页问 VLM 要「题号 / 标准答案 / 解答过程」，**这份题号清单是权威的** → `stemread.py` 读题目图，按同一份题号清单把 `stem` 填进去 → ③c `kpmark.py` 用「题干 + 官方解答」挂知识点。现有的切题、解题、断言、动画一个都不进 —— **不碰 `segment.py` / `anchors.py` / `ingest.py`**。

**为什么需要 Ⓔ 读题干**：实测（见设计文档「探针结论」）参考答案**只有大题有详解**，1-13 题只有一个答案。一个孤零零的「D」推不出这道题考什么，没有题干的话 13 道题（含全部 8 道选择题）挂不上知识点。

**Tech Stack:** Python 3.14 + psycopg 3 + Postgres；视觉模型走 claude CLI（`mathvlm.ask_raw`，经 `clishim` 中转）；FastAPI multipart；React + TypeScript；pytest。

## Global Constraints

- **`stem` 由 Ⓔ 填，Ⓐ 一律留空。** 两步分工写死：Ⓐ 只写 `ref_answer` / `ref_solution`，Ⓔ 只写 `stem`。谁都不许拿对方那份数据冒充自己那一列。老师没传题目图时 `stem` 就是空的，页面明说「这道题的题干没读出来」，**不拿解答过程冒充题干**。
- **认不出的题整条丢掉，不留半条。** 错的标准答案会让做对的学生被判错，凭空造出一个假的薄弱知识点 —— 那是这个功能唯一的产出。
- **题号必须是图上真实认出来的**，不许按顺序编。小问写成 `12(1)`。
- **`stage_of` 必须按 `source_kind` 分支。** 期一加 ③c 那一格已经踩过一次一模一样的坑：不分支的话，`solutions`/`specs`/`scenes` 恒为 0 的卷子会永远显示「未完成」、进度带永远转。
- **知识点挂不上就留空**，页面明说，不塞最接近的一个（期一已定，`kpmark.keep` 已实现）。
- 所有新模块放 `pipeline/`，测试放 `tests/`，注释与输出一律中文。
- `import api` 需要 `web/dist` 存在。

## 本期不做

答题卡（步二）、薄弱知识点与建议（步三）、AI 讲解、动画。

## 已经有的（不要重做）

| 已有 | 在哪 |
|---|---|
| 词表 154 条 + `kp.resolve` | `pipeline/kp.py`、`kp_seed.json` |
| `questions.kps` / `ref_answer` / `ref_answer_src` 三列 | `schema.sql` |
| `store.put_kps` / `put_ref_answer` | `store.py` |
| ③c 整卷知识点标注 | `pipeline/kpmark.py` |
| `pages.py` 一批文件 → 规范化页面图 | `pipeline/pages.py` |
| `grade.judge` 判等（54 条测试） | `pipeline/grade.py` |
| `mathvlm.crop` / `loads_lenient` | `pipeline/mathvlm.py` |

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `pipeline/schema.sql` | `papers.source_kind`、`questions.ref_solution` | 1 |
| `pipeline/store.py` | `create_answers_paper` / `put_answer_question` / `source_kind_of` | 1 |
| `pipeline/mathvlm.py` | 抽出 `ask_raw`（对象/数组参数化） | 2 |
| `pipeline/refread.py` | Ⓐ 参考答案图 → 题号/标准答案/解答过程 | 2 |
| `pipeline/stemread.py` | Ⓔ 题目图 → 按题号填 `stem`（**不切题、不裁图**） | 2b |
| `pipeline/api.py` | `stage_of` 分支、上传入口、`paper()` 带出新字段 | 3, 5 |
| `pipeline/kpmark.py` | 输入改成「题干 + 官方解答」，两样有一样就能挂 | 4 |
| `web/src/types.ts` `api.ts` | 类型与接口 | 5, 6 |
| `web/src/components/QuestionCard.tsx` `PaperView.tsx` `Upload.tsx` | 页面 | 6 |

---

### Task 1: 两个新列与建卷

**Files:**
- Modify: `pipeline/schema.sql`（末尾追加）
- Modify: `pipeline/store.py`
- Create: `tests/test_store_answers_only.py`

**Interfaces:**
- Produces:
  - `store.create_answers_paper(name, owner_id=None) -> int` — 建一条 `source_kind='answers_only'` 的 `papers`，返回 id
  - `store.put_answer_question(paper_name, n, ref_answer, ref_solution) -> int` — upsert 一道题，返回 question_id
  - `store.source_kind_of(name) -> str | None`
  - `store.put_page_asset(paper_name, local_path, rel_path) -> None` — 把一页图挂到卷子上
  - `store.get_paper()` 返回的每题多出 `ref_solution`

- [ ] **Step 1: 加两列**

在 `pipeline/schema.sql` 末尾追加：

```sql
-- ---------------------------------------------------------------- 只有参考答案的卷子
-- pdf          走 ①②③ 的完整试卷
-- answers_only 老师只传了参考答案：stem 留空，不进 ③④⑤
--
-- **stage_of 必须按它分支**：answers_only 的卷子 solutions/specs/scenes 恒为 0，
-- 不分支的话进度带永远转、done 永远是 false。期一加 ③c 那一格踩过一次一样的坑
ALTER TABLE papers ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'pdf';

-- 参考答案里的解答过程。ref_answer 是最终答案，这一列是过程。
-- 分两列而不是一列：判对错拿前者，「怎么提升」展示后者，混在一起两边都不好用
ALTER TABLE questions ADD COLUMN IF NOT EXISTS ref_solution text;
```

- [ ] **Step 2: 写失败的测试**

`tests/test_store_answers_only.py`：

```python
# -*- coding: utf-8 -*-
import store


def test_建一份只有答案的卷子(db):
    pid = store.create_answers_paper("答案卷A", None)
    assert pid > 0
    assert store.source_kind_of("答案卷A") == "answers_only"
    p = store.get_paper("答案卷A")
    assert p["questions"] == [], "刚建出来是空的，题目由 Ⓐ 一条条写进去"


def test_写题与读回(db):
    store.create_answers_paper("答案卷B", None)
    qid = store.put_answer_question("答案卷B", 11, "2BIL / MP", "由安培力公式 F=BIL…")
    q = store.get_paper("答案卷B")["questions"][0]
    assert q["id"] == qid and q["n"] == 11
    assert q["ref_answer"] == "2BIL / MP"
    assert q["ref_solution"].startswith("由安培力")
    assert q["ref_answer_src"] == "answer_file"
    assert q["stem"] == "", "这条链没有题干，留空不编"


def test_重写同一题是覆盖(db):
    store.create_answers_paper("答案卷C", None)
    a = store.put_answer_question("答案卷C", 1, "D", "解法甲")
    b = store.put_answer_question("答案卷C", 1, "C", "解法乙")
    assert a == b, "id 要稳定 —— kps 挂在它上面"
    qs = store.get_paper("答案卷C")["questions"]
    assert len(qs) == 1 and qs[0]["ref_answer"] == "C"


def test_重写不冲掉知识点(db):
    """③c 挂完知识点之后重跑 Ⓐ，不该把标签冲没了 ——
    期一 publish 那次就是这个坑"""
    store.create_answers_paper("答案卷D", None)
    qid = store.put_answer_question("答案卷D", 1, "D", "解法")
    store.put_kps(qid, [{"code": "mag.ampere_force", "why": "用安培力公式"}])
    store.put_answer_question("答案卷D", 1, "D", "解法（改过）")
    q = store.get_paper("答案卷D")["questions"][0]
    assert q["kps"] == [{"code": "mag.ampere_force", "why": "用安培力公式"}]


def test_题号带小问也存得下(db):
    """12(1) 这种。n 是 int，小问要另想办法 —— 见实现里的说明"""
    store.create_answers_paper("答案卷E", None)
    store.put_answer_question("答案卷E", 1201, "170", "由变压器原理")
    q = store.get_paper("答案卷E")["questions"][0]
    assert q["n"] == 1201


def test_默认还是pdf(db, tmp_path):
    import json
    d = tmp_path / "普通卷"
    d.mkdir()
    (d / "questions.json").write_text(json.dumps({
        "source": "x.pdf", "sections": [], "warnings": [],
        "questions": [{"n": 1, "type": "单选题", "stem": "题干",
                       "options": [], "tables": [], "figures": []}]}, ensure_ascii=False),
        encoding="utf-8")
    store.publish(str(d), name="普通卷")
    assert store.source_kind_of("普通卷") == "pdf", "老卷子不能被改成 answers_only"


def test_不存在的卷子回None(db):
    assert store.source_kind_of("根本没有") is None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_store_answers_only.py -v`
Expected: FAIL，`AttributeError: module 'store' has no attribute 'create_answers_paper'`

- [ ] **Step 4: 写 store 函数**

在 `pipeline/store.py` 的 `put_ref_answer` 之后插入：

```python
def create_answers_paper(name, owner_id=None):
    """
    建一份**只有参考答案**的卷子。没有 questions.json，所以不走 publish。

    题目由 Ⓐ 一条条写进去（见 put_answer_question），`stem` 始终留空 ——
    这条链没有题干，不拿解答过程冒充它。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO papers (name, n_questions, source_kind, updated_at,
                                run_started_at, owner_id)
            VALUES (%s, 0, 'answers_only', now(), now(), %s)
            ON CONFLICT (name) DO UPDATE SET
              updated_at=now(), run_started_at=now(),
              owner_id=COALESCE(papers.owner_id, EXCLUDED.owner_id)
            RETURNING id""", (name, owner_id))
        pid = cur.fetchone()[0]
        c.commit()
        return pid


def source_kind_of(name):
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT source_kind FROM papers WHERE name=%s", (name,))
        r = cur.fetchone()
        return r[0] if r else None


def put_answer_question(paper_name, n, ref_answer, ref_solution):
    """
    写一道「只有答案」的题，返回 question_id。

    **按 (paper_id, n) upsert，且只更新这三样。** `kps` 不在更新列表里 ——
    ③c 挂完知识点之后重跑 Ⓐ，不能把标签冲没了（期一 publish 那次就是这个坑）。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO questions (paper_id, n, stem, ref_answer, ref_solution,
                                   ref_answer_src)
            SELECT p.id, %s, '', %s, %s, 'answer_file' FROM papers p WHERE p.name=%s
            ON CONFLICT (paper_id, n) DO UPDATE SET
              ref_answer=EXCLUDED.ref_answer,
              ref_solution=EXCLUDED.ref_solution,
              ref_answer_src=EXCLUDED.ref_answer_src
            RETURNING id""", (n, ref_answer, ref_solution, paper_name))
        row = cur.fetchone()
        if not row:
            raise ValueError("库里没有「%s」" % paper_name)
        cur.execute("""UPDATE papers SET n_questions=
                         (SELECT count(*) FROM questions q WHERE q.paper_id=papers.id),
                       updated_at=now()
                      WHERE name=%s""", (paper_name,))
        c.commit()
        return row[0]


def put_page_asset(paper_name, local_path, rel_path):
    """把一页图挂到卷子上。资产行的形状与 publish 里那段一致。"""
    row = put_asset(local_path, rel_path)
    with connect() as c:
        c.execute("""
            INSERT INTO assets (paper_id, kind, rel_path, sha256, bytes,
                                content_type, storage, object_key)
            SELECT p.id, %s,%s,%s,%s,%s,%s,%s FROM papers p WHERE p.name=%s
            ON CONFLICT (paper_id, rel_path) DO UPDATE SET
              sha256=EXCLUDED.sha256, bytes=EXCLUDED.bytes,
              content_type=EXCLUDED.content_type,
              storage=EXCLUDED.storage, object_key=EXCLUDED.object_key""",
            (row["kind"], row["rel_path"], row["sha256"], row["bytes"],
             row["content_type"], row["storage"], row["object_key"], paper_name))
        c.commit()
```

**小问怎么存**：`questions.n` 是 `int`，而参考答案里有 `12(1)` 这种。约定
**`n = 主题号 * 100 + 小问号`**（`12(1)` → `1201`，无小问的 `11` → `11`）。
理由：不改表结构、排序天然正确、页面显示时除以 100 还原。这个约定要写在
`refread.py` 的模块文档里，两处都能看见。

- [ ] **Step 5: 让 `get_paper` 带出 `ref_solution`**

在 `get_paper` 的 SELECT 列清单里，把

```python
                              kps, ref_answer, ref_answer_src,
```

改成

```python
                              kps, ref_answer, ref_answer_src, ref_solution,
```

- [ ] **Step 6: 灌 schema 并跑测试**

```bash
.venv/bin/python pipeline/store.py init
.venv/bin/pytest tests/test_store_answers_only.py -v
```

Expected: `7 passed`

- [ ] **Step 7: 提交**

```bash
git add pipeline/schema.sql pipeline/store.py tests/test_store_answers_only.py
git commit -m "feat: 支持只有参考答案的卷子（source_kind + ref_solution）

没有 questions.json 所以不走 publish，题目由 Ⓐ 一条条写进去，stem 始终
留空 —— 这条链没有题干，不拿解答过程冒充它。

put_answer_question 只更新三列，kps 不在里面：③c 挂完知识点之后重跑 Ⓐ，
不能把标签冲没了。期一 publish 那次就是这个坑，测试直接盯这一点。

小问按 n = 主题号*100 + 小问号 存（12(1) → 1201）：不改表结构、排序天然
正确、显示时除以 100 还原。"
```

---

### Task 2: Ⓐ 读参考答案

**Files:**
- Modify: `pipeline/mathvlm.py`（抽出 `ask_raw`）
- Create: `pipeline/refread.py`
- Create: `tests/test_refread.py`

**Interfaces:**
- Produces:
  - `mathvlm.ask_raw(img_path, prompt, want="object"|"array", timeout=240)`
  - `refread.qnum(s) -> int | None` — `"12(1)"` → `1201`，`"11"` → `11`，认不出 `None`
  - `refread.show_qnum(n) -> str` — `1201` → `"12(1)"`（页面显示用）
  - `refread.keep(rows) -> list[dict]` — 纯函数，过模型原始输出
  - `refread.read(paper_name, page_files, verbose=True) -> int` — 读+落库，返回写了几题

- [ ] **Step 1: 写失败的测试**

`tests/test_refread.py`：

```python
# -*- coding: utf-8 -*-
import refread


def test_题号带小问():
    assert refread.qnum("11") == 11
    assert refread.qnum("12(1)") == 1201
    assert refread.qnum("12（1）") == 1201, "全角括号也要认"
    assert refread.qnum(" 13 (4) ") == 1304
    assert refread.qnum(11) == 11


def test_认不出的题号回None():
    assert refread.qnum("十一") is None
    assert refread.qnum("") is None
    assert refread.qnum(None) is None
    assert refread.qnum("abc") is None


def test_题号能还原成显示形式():
    assert refread.show_qnum(11) == "11"
    assert refread.show_qnum(1201) == "12(1)"
    assert refread.show_qnum(1304) == "13(4)"


def test_排序天然正确():
    ns = [refread.qnum(x) for x in ["9", "12(1)", "11", "12(2)", "13(1)"]]
    assert sorted(ns) == [9, 11, 1201, 1202, 1301]


def test_正常一条():
    got = refread.keep([{"n": "11", "answer": "2BIL / MP",
                         "solution": "由安培力公式 F=BIL"}])
    assert got == [{"n": 11, "ref_answer": "2BIL / MP",
                    "ref_solution": "由安培力公式 F=BIL"}]


def test_没有标准答案的整条丢掉():
    """错的标准答案会让做对的学生被判错，凭空造出一个假的薄弱知识点。
    宁可少一道题"""
    assert refread.keep([{"n": "11", "answer": "", "solution": "有过程"}]) == []
    assert refread.keep([{"n": "11", "solution": "有过程"}]) == []


def test_没有解答过程仍然收():
    """选择题的参考答案就只有一个字母，没有过程。这是常态，不是缺陷"""
    got = refread.keep([{"n": "1", "answer": "D"}])
    assert got == [{"n": 1, "ref_answer": "D", "ref_solution": None}]


def test_题号认不出的整条丢掉():
    assert refread.keep([{"n": None, "answer": "D"}]) == []
    assert refread.keep([{"n": "十一", "answer": "D"}]) == []


def test_同题号后来的覆盖前面的():
    """跨页续写：同一题的解答分在两页上"""
    got = refread.keep([{"n": "16", "answer": "见解析", "solution": "第一段"},
                        {"n": "16", "answer": "见解析", "solution": "第二段"}])
    assert len(got) == 1
    assert got[0]["ref_solution"] == "第一段 第二段", "跨页要拼接不是覆盖"


def test_按题号排序():
    got = refread.keep([{"n": "13(1)", "answer": "BC"}, {"n": "9", "answer": "不变"},
                        {"n": "12(2)", "answer": "U1/n1=U2/n2"}])
    assert [g["n"] for g in got] == [9, 1202, 1301]


def test_烂数据不炸():
    got = refread.keep([None, "串", {"answer": "D"}, {"n": "1"},
                        {"n": "2", "answer": "C"}])
    assert [g["n"] for g in got] == [2]


def test_整个不是数组也不炸():
    assert refread.keep(None) == []
    assert refread.keep({"n": 1}) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_refread.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'refread'`

- [ ] **Step 3: 从 mathvlm 抽出 `ask_raw`**

在 `pipeline/mathvlm.py` 里，把现有的 `ask_model` 换成下面两个（**行为不变**，只是把「要对象还是要数组」参数化）：

```python
def ask_raw(img_path, prompt, want="object", timeout=240):
    """
    调视觉模型读一张图，返回解析后的 JSON。

    `want="array"` 时找 `[...]`，否则找 `{...}`。参考答案那条链要的是数组，
    参数化一下，免得两处各写一份调用与容错。
    """
    if not CLI:
        raise RuntimeError("找不到 claude 可执行文件；视觉通道不可用")
    r = subprocess.run([CLI, "-p", "--model", MODEL],
                       input=prompt + "\n图片：" + os.path.abspath(img_path),
                       capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, **clishim.ensure()))
    if r.returncode != 0:
        raise RuntimeError("模型调用失败：%s" % (r.stderr or "")[-200:])
    pat = r"\[.*\]" if want == "array" else r"\{.*\}"
    m = re.search(pat, r.stdout, re.S)
    if not m:
        raise RuntimeError("没有返回 JSON：" + r.stdout[:300])
    return loads_lenient(m.group(0))


def ask_model(img_path, prompt=None):
    return ask_raw(img_path, prompt or PROMPT, want="object")
```

- [ ] **Step 4: 确认没把 ②b 改坏**

```bash
.venv/bin/python pipeline/mathvlm.py work/2025年高考北京卷物理真题
```

Expected: 全部命中缓存、0 次模型调用、无报错。**这一步不是为了产出，是为了证明抽函数没改坏行为。**

- [ ] **Step 5: 写 `pipeline/refread.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refread.py —— Ⓐ 参考答案图 → 题号 / 标准答案 / 解答过程

    python pipeline/refread.py <卷名> <图1> [图2 ...]

老师手上常常只有参考答案，没有题目。参考答案是印刷体、版面干净，比答题卡
好读得多；而且里面**直接写着法则名字**（「由盖-吕萨克定律」「E=BLv₀」），
拿它挂知识点比拿题干还准。

认不出就整条丢掉
----------------
一道错的标准答案，会让所有做对这道题的学生都被判错，凭空造出一个假的
薄弱知识点 —— 而薄弱知识点是这整个功能唯一的产出。宁可少一道题。

小问怎么编号
------------
`questions.n` 是 int，而参考答案里有 `12(1)` 这种。约定
**`n = 主题号 * 100 + 小问号`**（`12(1)` → `1201`，无小问的 `11` → `11`）。
不改表结构、排序天然正确、显示时 `show_qnum` 还原。
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mathvlm
import pages
import store

PROMPT = """这是一份物理试卷的**参考答案**（印刷体）。

逐题读出三样东西，输出 JSON 数组（不要代码块围栏、不要解释）：
[{"n": "11", "answer": "2BIL / MP", "solution": "由安培力公式 F=BIL…"}, ...]

· `n` 题号。有小问的写成 "12(1)"。**必须是图上真实认出来的，不许按顺序编。**
· `answer` 这一题的**最终答案**（选项字母、数值、表达式）。多空用 " / " 隔开。
· `solution` 解答过程，原样转写，公式用 LaTeX。选择题通常没有过程，留空即可。

两条硬规则：

1. 认不出题号或认不出最终答案的，**整条不要输出**。宁可少一道题，
   也不要一条错的标准答案 —— 它会让做对的学生被判错。
2. 只读这张图上有的，**不要补全**、不要根据常识推断没印出来的答案。

页眉页脚、页码、水印一律忽略。
"""

_QN = re.compile(r"^\s*(\d{1,2})\s*(?:[（(]\s*(\d{1,2})\s*[）)])?\s*$")


def qnum(s):
    """`"12(1)"` → 1201，`"11"` → 11。认不出回 None。"""
    if s is None:
        return None
    m = _QN.match(str(s).replace("（", "(").replace("）", ")"))
    if not m:
        return None
    main = int(m.group(1))
    return main * 100 + int(m.group(2)) if m.group(2) else main


def show_qnum(n):
    """1201 → `"12(1)"`，11 → `"11"`。页面显示用。"""
    return "%d(%d)" % (n // 100, n % 100) if n >= 100 else str(n)


def keep(rows):
    """
    把模型的原始输出过成可以入库的形状。**纯函数**，正确性判断全在这里。

    同一题号出现多次按页序**拼接** solution（跨页续写），不是覆盖。
    """
    out = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        n = qnum(r.get("n"))
        ans = str(r.get("answer") or "").strip()
        if n is None or not ans:
            continue                      # 认不出就整条丢掉
        sol = str(r.get("solution") or "").strip() or None
        if n in out:
            prev = out[n]["ref_solution"]
            out[n]["ref_solution"] = (prev + " " + sol).strip() if prev and sol \
                                     else (prev or sol)
            continue
        out[n] = {"n": n, "ref_answer": ans, "ref_solution": sol}
    return [out[k] for k in sorted(out)]


def read(paper_name, page_files, verbose=True):
    """读一批参考答案图，写进库，返回写了几题。"""
    log = print if verbose else (lambda *a, **k: None)
    work = os.path.join(ROOT, "work", paper_name)
    pgs = pages.normalize(page_files, os.path.join(work, "page"), prefix="p")

    raw = []
    for pg in pgs:
        got = mathvlm.ask_raw(pg["web"], PROMPT, want="array", timeout=600)
        raw += got if isinstance(got, list) else []
        store.put_page_asset(paper_name, pg["web"],
                             "page/p%02d.png" % pg["page"])
        log("   第%d页 读到 %d 条" % (pg["page"], len(got) if isinstance(got, list) else 0))

    rows = keep(raw)
    if not rows:
        raise RuntimeError("这几张图里一道题的答案都没读出来。多半不是参考答案，"
                           "或者拍得太糊 —— 请换清楚一点的图。")
    for r in rows:
        store.put_answer_question(paper_name, r["n"], r["ref_answer"],
                                  r["ref_solution"])
        log("   第%-7s %s%s" % (show_qnum(r["n"]) + "题", r["ref_answer"][:40],
                                "" if r["ref_solution"] else "   （无解答过程）"))
    log("── 参考答案 %s：写入 %d 题" % (paper_name, len(rows)))
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("images", nargs="+")
    a = ap.parse_args()
    read(a.paper, a.images)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_refread.py -v`
Expected: `12 passed`

- [ ] **Step 7: 拿老师给的真实材料端到端跑一次**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'pipeline'); import store
print(store.create_answers_paper('2025-2026高二物理期末', None))"
.venv/bin/python pipeline/refread.py 2025-2026高二物理期末 \
  "/Users/jerry/Desktop/试卷+答题卡/20260807-234414.jpeg" \
  "/Users/jerry/Desktop/试卷+答题卡/20260807-234417.jpeg" \
  "/Users/jerry/Desktop/试卷+答题卡/20260807-234420.jpeg" \
  "/Users/jerry/Desktop/试卷+答题卡/20260807-234423.jpeg"
```

**拿设计文档里那张真值表逐条核对**（设计文档「材料长什么样」一节）：

| 题 | 标准答案 |
|---|---|
| 1-4 | D、C、C、B |
| 5-8 | AC、BC、BC、AC |
| 9 | 不变 / 17190 |
| 10 | 调制 / 0.047 |
| 11 | 2BIL / MP |
| 12(1) | 170、A |
| 13(1) | BC |

**1-8 和 11 这几条错一条就算不合格** —— 它们是选择题和填空，形式简单，
读不准说明这一步不可靠。

- [ ] **Step 8: 提交**

```bash
git add pipeline/refread.py pipeline/mathvlm.py tests/test_refread.py
git commit -m "feat: 加 Ⓐ 读参考答案

老师手上常常只有参考答案没有题目。参考答案是印刷体、版面干净，而且里面
直接写着法则名字（「由盖-吕萨克定律」「E=BLv₀」），拿它挂知识点比拿题干还准。

认不出就整条丢掉：一道错的标准答案会让所有做对这题的学生都被判错，凭空
造出一个假的薄弱知识点 —— 而那是这整个功能唯一的产出。宁可少一道题。

小问按 n = 主题号*100 + 小问号 存，不改表结构、排序天然正确。

从 mathvlm 抽出 ask_raw（对象/数组参数化），抽完跑了一遍北京卷确认全命中
缓存、没跑坏。"
```

---

### Task 2b: Ⓔ 读题干

**Files:**
- Create: `pipeline/stemread.py`
- Create: `tests/test_stemread.py`

**Interfaces:**
- Consumes: `mathvlm.ask_raw`、`pages.normalize`、`refread.qnum` / `show_qnum`、`store`
- Produces:
  - `stemread.keep(rows, known_ns) -> tuple[list[dict], list[int]]` — 纯函数，回 `(收下的, 多出来的题号)`
  - `stemread.read(paper_name, page_files, verbose=True) -> tuple[int, int]` — `(填了几题, 卷子共几题)`
  - `store.put_stem(paper_name, n, stem) -> None`

- [ ] **Step 1: 写失败的测试**

`tests/test_stemread.py`：

```python
# -*- coding: utf-8 -*-
import stemread

KNOWN = {1, 6, 11, 1201, 1401}


def test_正常一条():
    got, extra = stemread.keep([{"n": "6", "stem": "如图所示，两平行金属板…"}], KNOWN)
    assert got == [{"n": 6, "stem": "如图所示，两平行金属板…"}]
    assert extra == []


def test_题号不在清单里就丢掉并报出来():
    """参考答案上的题号是权威的。多出来的说明读错了 ——
    这是白捡的对账，等价于原设计里「本题共 N 小题」那道防线"""
    got, extra = stemread.keep([{"n": "99", "stem": "读错的东西"}], KNOWN)
    assert got == [] and extra == [99]


def test_小问的题干也认():
    got, _ = stemread.keep([{"n": "12(1)", "stem": "求原副线圈匝数比"}], KNOWN)
    assert got[0]["n"] == 1201


def test_题干为空的丢掉():
    got, extra = stemread.keep([{"n": "1", "stem": "  "}], KNOWN)
    assert got == [] and extra == []


def test_选项拼进题干():
    """选项是题干的一部分。挂知识点时「A. 电场强度增大」这种话很有信息量"""
    got, _ = stemread.keep([{"n": "1", "stem": "下列说法正确的是（ ）",
                             "options": ["A. 甲", "B. 乙"]}], KNOWN)
    assert "A. 甲" in got[0]["stem"] and "B. 乙" in got[0]["stem"]


def test_同题号跨页拼接():
    got, _ = stemread.keep([{"n": "11", "stem": "前半段"},
                            {"n": "11", "stem": "后半段"}], KNOWN)
    assert len(got) == 1 and got[0]["stem"] == "前半段 后半段"


def test_按题号排序():
    got, _ = stemread.keep([{"n": "11", "stem": "甲"}, {"n": "1", "stem": "乙"}], KNOWN)
    assert [g["n"] for g in got] == [1, 11]


def test_烂数据不炸():
    got, extra = stemread.keep([None, "串", {"stem": "没题号"}, {"n": "甲", "stem": "x"},
                                {"n": "1", "stem": "好的"}], KNOWN)
    assert [g["n"] for g in got] == [1] and extra == []


def test_整个不是数组也不炸():
    assert stemread.keep(None, KNOWN) == ([], [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_stemread.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'stemread'`

- [ ] **Step 3: 写 `pipeline/stemread.py`**

模块文档要写清三件事（照 `refread.py` 的风格）：

- **题号清单由 Ⓐ 给出，这里只填空。** 不切题、不用坐标、不碰 `anchors.py` ——
  参考答案上的题号是权威的，比从版面上猜可靠得多。
- **多出来的题号丢掉并告警。** 白捡的对账。
- **不裁插图。** 物理题常带图，但挂知识点用题干文字就够；要看图就看原页图。
  裁图要坐标，而这条链没有坐标 —— 硬做会引入一个「裁歪了没人看得见」的错。

提示词要点：给模型**已知的题号清单**，让它只读这些题；认不出的留空不编；
选项一并读出来（选项是题干的一部分，对挂知识点很有信息量）。

`keep(rows, known_ns)` 的规则见测试。`read()` 里：`pages.normalize` → 逐页
`mathvlm.ask_raw(..., want="array")` → `keep` → `store.put_stem`，
并把多出来的题号 `log` 出来。

`store.put_stem(paper_name, n, stem)`：只更新 `stem` 一列 —— **不能碰
`ref_answer` / `ref_solution` / `kps`**，它们是 Ⓐ 和 ③c 的产出。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_stemread.py -v`
Expected: `9 passed`

- [ ] **Step 5: 拿真材料跑一次**

老师传的题目图（**这一批目前还没有，要向老师要**）。跑完核对两件事：

1. **题号覆盖率**：Ⓐ 读出 20 题，Ⓔ 应该填上其中绝大多数。差得多说明读错了。
2. **多出来的题号必须是 0 条**。有的话说明模型在编题号，提示词要收紧。

- [ ] **Step 6: 提交**

---

### Task 3: `stage_of` 按 `source_kind` 分支

**这一步不做，页面会永远显示这份卷子「解题中 0/16」，进度带永远转。**
期一加 ③c 那一格已经踩过一次一模一样的坑。

**Files:**
- Modify: `pipeline/store.py`（`progress()` 带出 `sourceKind`）
- Modify: `pipeline/api.py`（`stage_of`）
- Modify: `web/src/types.ts`
- Create: `tests/test_stage_answers_only.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_stage_answers_only.py`：

```python
# -*- coding: utf-8 -*-
import api

BASE = dict(questions=16, labels=0, kps=16, solutions=0, judged=0, worth=0,
            specs=0, specsWorth=0, drafts=0, ready=0, sceneTried=0,
            assembledFresh=False, sourceKind="answers_only")


def test_只有答案的卷子挂上知识点就算完成():
    assert api.stage_of(BASE)[0] == "done", \
        "solutions/specs/scenes 恒为 0，不分支的话永远显示未完成"


def test_知识点没挂完停在三c():
    code, label, short, cur, total = api.stage_of({**BASE, "kps": 9})
    assert code == "kpmark" and (cur, total) == (9, 16)


def test_一道题都没有停在读答案():
    code, *_ = api.stage_of({**BASE, "questions": 0, "kps": 0})
    assert code == "refread"


def test_不要求目录():
    """③b 目录是给试卷页导航用的，只有答案的卷子没有题干可写标题"""
    assert api.stage_of({**BASE, "labels": 0})[0] == "done"


def test_pdf卷子不受影响():
    pdf = dict(questions=16, labels=16, kps=16, solutions=16, judged=16, worth=6,
               specs=6, specsWorth=6, drafts=0, ready=6, sceneTried=6,
               assembledFresh=True, sourceKind="pdf")
    assert api.stage_of(pdf)[0] == "done"
    assert api.stage_of({**pdf, "solutions": 4})[0] == "solve"


def test_没给sourceKind当pdf处理():
    """老数据没有这一列时的默认行为"""
    pdf = dict(questions=16, labels=16, kps=16, solutions=4, judged=0, worth=0,
               specs=0, specsWorth=0, drafts=0, ready=0, sceneTried=0,
               assembledFresh=False)
    assert api.stage_of(pdf)[0] == "solve"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_stage_answers_only.py -v`
Expected: FAIL

- [ ] **Step 3: `progress()` 带出 `sourceKind`**

在 `pipeline/store.py` 的 `progress()` 里，SELECT 的第一行

```python
            SELECT p.id, p.n_questions, p.assembled_at, p.run_started_at,
```

改成

```python
            SELECT p.id, p.n_questions, p.assembled_at, p.run_started_at, p.source_kind,
```

解包那一行 `(_pid, _nq, asm_at, started, n_q, ...)` 改成
`(_pid, _nq, asm_at, started, src_kind, n_q, ...)`，返回的字典里加

```python
            "sourceKind": src_kind,
```

**解包顺序错一位不报错，只是把某个计数换成了另一个。** 改完必须拿一份
真卷子验一眼（见 Step 6）。

- [ ] **Step 4: `stage_of` 分支**

在 `pipeline/api.py` 的 `stage_of` 里，函数体**最前面**插入：

```python
    # 只有参考答案的卷子：没有题干，进不了 ③④⑤⑦。终点是 ③c 挂完知识点。
    # 不分支的话 solutions/specs/scenes 恒为 0，进度带永远转、done 永远是 false
    if pg.get("sourceKind") == "answers_only":
        q = pg["questions"]
        if not q:
            return "refread", "Ⓐ 读参考答案", "读参考答案", 0, 1
        if pg.get("kps", 0) < q:
            return "kpmark", "③c 知识点", "标知识点", pg.get("kps", 0), q
        return "done", "完成", "已完成", 1, 1
```

- [ ] **Step 5: 前端类型**

`web/src/types.ts` 的 `Progress` 里加：

```ts
  /** 'pdf' | 'answers_only'。只有答案的卷子不跑 ③④⑤⑦，阶段条要少几格 */
  sourceKind?: string
```

`Paper` 里也加同一个字段。

- [ ] **Step 6: 跑测试 + 拿真卷子验解包顺序**

```bash
.venv/bin/pytest tests/test_stage_answers_only.py -v
.venv/bin/python -c "
import sys; sys.path.insert(0,'pipeline'); import store
for r in store.list_papers()[:3]:
    p = store.progress(r['name'])
    print('%-30s kind=%-12s q=%2d labels=%2d kps=%2d sol=%2d'
          % (r['name'][:28], p['sourceKind'], p['questions'], p['labels'],
             p['kps'], p['solutions']))"
```

Expected: 测试全过；真卷子的 `kind` 是 `pdf`，且 `labels`/`kps`/`sol` 三个数
与期一验过的一致（海南卷 `labels=19 kps=19 sol=19`）。**数错位了这里立刻看得出来。**

- [ ] **Step 7: 提交**

---

### Task 4: ③c 换输入 —— 没有题干时喂解答过程

**Files:**
- Modify: `pipeline/kpmark.py`
- Modify: `tests/test_kpmark.py`（加两条）

**Interfaces:**
- `kpmark.payload_for(paper, sols)` 改为在没有 `stem` 时用 `ref_solution`

- [ ] **Step 1: 加两条失败的测试**

在 `tests/test_kpmark.py` 末尾追加：

```python
def test_没有题干时喂解答过程():
    """只有参考答案的卷子没有题干。解答过程里直接写着法则名字，
    比题干更有信息量"""
    paper = {"questions": [{"n": 11, "stem": "", "type": None,
                            "ref_solution": "由安培力公式 F=BIL 得 F=2BIL"}]}
    p = kpmark.payload_for(paper, {})
    assert "安培力" in p
    assert "尚未解出" not in p, "有官方解答就不该说尚未解出"


def test_有题干时仍然优先用题干():
    paper = {"questions": [{"n": 1, "stem": "如图所示，物块…", "type": "单选题",
                            "ref_solution": "官方解答"}]}
    p = kpmark.payload_for(paper, {})
    assert "如图所示" in p
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_kpmark.py -v`
Expected: 新加的两条里至少一条 FAIL

- [ ] **Step 3: 改 `payload_for`**

把 `pipeline/kpmark.py` 的 `payload_for` 换成：

```python
def payload_for(paper, sols):
    """
    喂给模型的整卷摘要。

    优先级：题干 > 无题干。解法优先级：③ 的解法 > 官方参考解答 > 没有。

    只有参考答案的卷子没有题干，这时**官方解答过程就是全部信息** ——
    而它里面直接写着法则名字（「由盖-吕萨克定律」「E=BLv₀」），
    实测比题干更判得准这道题考什么。
    """
    parts = []
    for q in paper["questions"]:
        stem = re.sub(r"\s+", " ", (q.get("stem_latex") or q.get("stem") or "").strip())
        bits = ["【第%d题】%s" % (q["n"], q.get("type") or "")]
        if stem:
            bits.append("题干：" + stem[:260])
        s = sols.get(q["n"])
        if s and s.get("steps"):
            bits.append("解法：" + re.sub(r"\s+", " ", " ".join(s["steps"]))[:400])
        elif q.get("ref_solution"):
            bits.append("官方解答：" + re.sub(r"\s+", " ",
                                            q["ref_solution"])[:400])
        elif s and s.get("answer"):
            bits.append("答案：" + re.sub(r"\s+", " ", s["answer"])[:200])
        elif q.get("ref_answer"):
            bits.append("标准答案：" + str(q["ref_answer"])[:120])
        else:
            bits.append("解法：（尚未解出，只能看题干判断）")
        parts.append("\n".join(bits))
    return "\n\n".join(parts)
```

**题号显示**：`【第%d题】` 对 `1201` 会打成「第1201题」。改成用
`refread.show_qnum(q["n"])`，并在 `kpmark.py` 里 `import refread`。

- [ ] **Step 4: 跑测试确认通过 + 拿真卷子跑一次**

```bash
.venv/bin/pytest tests/test_kpmark.py -v
.venv/bin/python pipeline/kpmark.py 2025-2026高二物理期末
```

**人工看一眼**：第 11 题应该挂上「安培力」，第 14 题应该挂上「气体实验定律」
或「理想气体状态方程」，第 15 题「带电粒子在匀强磁场中的圆周运动」，
第 16 题「法拉第电磁感应定律」或「导体棒切割磁感线」。

- [ ] **Step 5: 提交**

---

### Task 5: 上传入口

**Files:**
- Modify: `pipeline/api.py`
- Modify: `web/src/api.ts`
- Create: `tests/test_answer_upload_gate.py`

**Interfaces:**
- `POST /api/answer-papers` — multipart：`file[]`（参考答案图或 PDF，必填）、`name`（可选）
- 返回 `{job, name}`；轮询 `getJob` 看进度

- [ ] **Step 1: 写失败的测试（只测纯判据）**

`tests/test_answer_upload_gate.py`：

```python
# -*- coding: utf-8 -*-
import api


def test_只收图片和pdf():
    ok, why = api.check_answer_files(["a.jpg", "b.png"])
    assert ok
    ok, why = api.check_answer_files(["a.pdf"])
    assert ok
    ok, why = api.check_answer_files(["a.docx"])
    assert not ok and "格式" in why


def test_一个文件都没有就明说():
    ok, why = api.check_answer_files([])
    assert not ok and "参考答案" in why


def test_张数有上限():
    ok, why = api.check_answer_files(["%d.jpg" % i for i in range(40)])
    assert not ok and "太多" in why
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现判据与端点**

```python
MAX_ANSWER_PAGES = 30


def check_answer_files(names):
    if not names:
        return (False, "没有参考答案文件。至少要传一张")
    if len(names) > MAX_ANSWER_PAGES:
        return (False, "一次最多 %d 张，你传了 %d 张 —— 太多了"
                       % (MAX_ANSWER_PAGES, len(names)))
    if any(sheet_kind(n) is None for n in names):
        return (False, "有不认识的文件格式，只收图片和 PDF")
    return (True, "")
```

（`sheet_kind` 在期二计划 Task 7 里定义过：按扩展名分 `pdf` / `image` / `None`。
本任务一并实现。）

端点两段：`store.create_answers_paper` → 后台任务跑 `refread.read` → `kpmark.mark`。
进度复用现有 `JOBS` 与 `run_step` 那套。

**卷名**：老师没填就用 `参考答案 YYYY-MM-DD`，撞名走 `store.free_name` 加后缀
（跟现有上传一致，不弹 409 —— 这条链一份材料就是一份新卷子，没有「复用已有卷子」
的语义）。

- [ ] **Step 4: 前端接口**

`web/src/api.ts`：

```ts
export function uploadAnswerPaper(files: File[], name?: string) {
  const fd = new FormData()
  files.forEach((f) => fd.append('file', f))
  if (name) fd.append('name', name)
  return fetch('/api/answer-papers', { ...CRED, method: 'POST', body: fd })
    .then(j<{ job: string; name: string }>)
}
```

- [ ] **Step 5: 用真材料走一遍端到端**

- [ ] **Step 6: 提交**

---

### Task 6: 页面

**Files:**
- Modify: `web/src/components/Upload.tsx`（多一个「只有参考答案」的投放区）
- Modify: `web/src/components/QuestionCard.tsx`（没有题干时的版面）
- Modify: `web/src/components/PaperView.tsx`（阶段条按 `sourceKind` 少几格）
- Modify: `web/src/types.ts`

四条硬约束：

- **没有题干时不留空白框。** 明写「这份卷子只有参考答案，没有题目」，
  并给出「对照原图」按钮 —— 原图切片是唯一的核对依据。
- **官方解答过程要显示**，而且要标明它是**官方的**，不是 AI 生成的 ——
  这是它比 AI 讲解更有价值的地方，不说出来就白费了。
- **知识点标签照旧**（期一已实现，不用改）。
- **阶段条按 `sourceKind` 收缩**：`answers_only` 只显示 Ⓐ 和 ③c 两格，
  不显示 ③④⑤⑦ —— 显示成灰色「不适用」也不行，那还是在暗示这份卷子少了什么。

- [ ] **Step 1: 改 `QuestionCard`：没有题干时的版面**
- [ ] **Step 2: 改 `PaperView`：阶段条收缩**
- [ ] **Step 3: 改 `Upload`：多一个投放区**
- [ ] **Step 4: `npx tsc --noEmit` + `npm run build`**
- [ ] **Step 5: 重启后端，无头 Chrome 验一遍页面真的渲出来了**

```bash
kill $(pgrep -f "uvicorn pipeline.api:app"); sleep 2
cd /Users/jerry/Desktop/product/exam-explainer && \
  .venv/bin/uvicorn pipeline.api:app --host 127.0.0.1 --port 8712 >> logs/api.log 2>&1 &
```

`index.html` 已经是 `no-cache`（期一 `ccdbd42`），不会再撞浏览器缓存。
但渲染仍要验 —— 做法见期二计划 Task 9 Step 6。

- [ ] **Step 6: 请老师肉眼看一眼**

**不能省。** 版面挤不挤、官方解答读不读得下去，只有人能判。

- [ ] **Step 7: 提交**

---

## 自检

**规格覆盖**

| 规格条目 | 落在哪 |
|---|---|
| Ⓐ 读参考答案，认不出整条丢掉 | Task 2 |
| Ⓔ 读题干，题号必须在 Ⓐ 的清单里 | Task 2b |
| 题号真实认出、小问编号 | Task 2（`qnum` / `show_qnum`） |
| ③c 从解答过程挂知识点 | Task 4 |
| `source_kind` / `ref_solution` 两列 | Task 1 |
| `stage_of` 按 `source_kind` 分支 | Task 3 |
| 上传入口 | Task 5 |
| 页面：没有题干时明说、官方解答标明出处 | Task 6 |

**本步不做**：答题卡（步二）、薄弱知识点与建议（步三）。

**三个会踩的坑，计划里都盯住了**

1. `put_answer_question` 冲掉 `kps` —— Task 1 有专门的测试，期一 `publish` 那次就是这个坑。
2. `stage_of` 不分支导致进度带永远转 —— Task 3 整个任务就是为它。
3. `progress()` 加一列必须同步改解包顺序 —— Task 3 Step 6 拿真卷子的三个计数验。

**一个新的外部依赖**：Task 2b 要老师的**题目图**，这批材料里还没有。Task 1/2/3
不依赖它，可以先做。

**一个悬着的事**：`qnum` 的 `主题号*100+小问号` 约定，遇到「第 100 题」会跟
「第 1 题第 0 小问」撞。高中物理卷不会有 100 题，但这个前提要写在模块文档里
（已写）。真撞了的话 `qnum` 会给出一个错的题号而不报错 —— 这是本步唯一一处
「错了不响」的地方。
