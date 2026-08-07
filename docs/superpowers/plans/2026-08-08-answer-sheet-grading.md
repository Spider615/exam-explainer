# 期二：答题卡上传与自动阅卷 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 老师传几张学生答题卡照片，得到逐题「对 / 错 / 空白 / 判不了」，每一题都能对着原图切片核对，判错了能一键改判。

**Architecture:** 新增一条与试卷侧解耦的答题卡链：`pages.py`（一批文件 → 规范化页面图，试卷侧将来也用）→ `sheet.py` Ⓑ 整页读出每题作答 → `grade.py` Ⓒ 判对错（纯代码为主，判错的裁块复读一次）。判定结果进 `sheet_answers`，页面挂在试卷页下面。**不做诊断报告**（那是期三），本期交付的是「自动阅卷」，它自己就能用。

**Tech Stack:** Python 3.14 + psycopg 3 + Postgres；视觉模型走 claude CLI（`mathvlm.py` 现成那条路，经 `clishim` 中转）；Pillow 裁图；FastAPI multipart；React + TypeScript；pytest。

## Global Constraints

来自规格，**每个任务都隐含包含**：

- **`verdict` 只有四个值**：`right` / `wrong` / `blank` / `unsure`。判定条件不许有第五种解释。
- **`blank` 不是 `wrong`。** 空白不计入任何统计，报告里单独说。
- **`unsure` 不是 `wrong`。** 它是「系统没能力判」，把它混进错等于拿系统的无能去当学生的薄弱点。
- **`verdict_by` 必须落库并显示**（`code` / `model` / `teacher`）：同一个「错」，代码判的和模型判的可信度差一个量级。
- **老师改判写单独一列，不覆盖系统原判。** 读取一律走 `store` 里那一个函数，不让每个调用点各写一份。
- **不引 sympy。** 代码档只做不会静默出错的两件事：归一化字符串比、数值比。判不了就升级到模型，**不许猜**。
- **原图切片和判定一起落库**，不能推迟到「老师要看时再裁」。
- **判错的题一律裁块复读一次**，代价不对称：判错会凭空造出一个假的薄弱知识点。
- 所有新模块放 `pipeline/`，测试放 `tests/`，注释与输出一律中文。
- **`import api` 需要 `web/dist` 存在**（`api.py` 顶层把 StaticFiles 挂在 `/`）。

## 本期不做

诊断报告、薄弱知识点、提升建议（期三）；图片试卷（期四）；班级、学生表、成绩、过程分。

## 外部依赖：手写探针必须先跑

**本功能最大的风险是「VLM 到底认不认得准手写作答」，它在拿到真实样本之前完全验证不了。** Task 1 就是这个探针，它需要老师提供**一张真实的手写答题卡照片**。

探针不过（题号认错、作答认不出）→ 整条链要退回「老师先批改后再传」，那是完全不同的一条链，Task 5 之后全部作废。

**Task 2、3、4 不依赖探针结果**（页面图规范化、表结构、判对错的纯函数在哪条方案下都要），可以并行开工。**Task 5 之后必须等探针结论。**

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `pipeline/pages.py` | 一批文件（图片或 PDF）→ 规范化页面图 + 页序 | 2 |
| `pipeline/schema.sql` | `answer_sheets` / `sheet_answers` 两张表 | 3 |
| `pipeline/store.py` | 答题卡的增删查改；**唯一那个读判定的函数** | 3 |
| `pipeline/grade.py` | 判对错的归一化纯函数。**本期唯一能真正自动测的部分，要测厚** | 4 |
| `pipeline/mathvlm.py` | 抽出 `ask_raw`，让 `sheet.py` 复用同一条视觉通道 | 5 |
| `pipeline/sheet.py` | Ⓑ 整页读答案 + 裁块存 assets；Ⓒ 判对错 + 判错复读 | 5, 6 |
| `pipeline/api.py` | `/api/diagnose` 上传、改判端点、进度 | 7, 8, 10 |
| `web/src/api.ts` `types.ts` | 前端接口与类型 | 9 |
| `web/src/components/SheetPanel.tsx` | 答题卡列表 + 逐题对错 + 原图对照 + 改判 | 9 |
| `web/src/components/PaperView.tsx` | 挂上 `SheetPanel` | 9 |

---

### Task 1: 手写探针（外部依赖：真实答题卡样本）

**只跑 Ⓑ 那一步，不建表、不写页面。** 目的是在投入之前回答一个问题：VLM 认不认得准手写作答。

**Files:**
- Create: `pipeline/_probe_sheet.py`（一次性脚本，验证完就删）

**Interfaces:**
- Consumes: `mathvlm.CLI` / `mathvlm.MODEL` / `clishim.ensure()`
- Produces: 无（一次性）

- [ ] **Step 1: 拿到样本**

向老师要**一张真实的手写答题卡照片**（学生做过的，或自己在答题卡上手写几道题拍一张）。放到 `work/_probe/sheet01.jpg`。

**没有样本就停在这里，不要往下做。** 拿合成图（打印体、自己敲的文字）跑这个探针没有意义 —— 它要验的恰恰是手写。

- [ ] **Step 2: 写探针脚本**

`pipeline/_probe_sheet.py`：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性探针：VLM 认不认得准手写答题卡。验完就删。

    python pipeline/_probe_sheet.py work/_probe/sheet01.jpg
"""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clishim
import mathvlm

PROMPT = """这是一张学生的手写答题卡照片。上面只有题号和作答区，没有题干。

逐题读出学生**最终写下的作答**，输出 JSON 数组（不要代码块围栏、不要解释）：
[{"n": 3, "answer": "B", "conf": "high"}, ...]

四条硬规则：

1. **题号必须是图上真实认出来的**，绝对不许按顺序编。看到了作答但看不清是第几题，
   就写 `"n": null` 并在 `where` 里描述它的位置（「第二列上数第三格」）。
2. 认不出写的是什么，`answer` 写 `"unreadable"`。**认不出比猜错好** ——
   这些作答会拿去判学生对错，猜错一个就凭空造出一个假的薄弱知识点。
3. 该题空着没写，`answer` 写 `"blank"`。不许拿附近的字凑。
4. `conf` 是你自己的把握：high / medium / low。
"""


def main():
    img = os.path.abspath(sys.argv[1])
    r = subprocess.run([mathvlm.CLI, "-p", "--model", mathvlm.MODEL],
                       input=PROMPT + "\n图片：" + img,
                       capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, **clishim.ensure()))
    if r.returncode != 0:
        sys.exit("模型调用失败：" + (r.stderr or "")[-300:])
    m = re.search(r"\[.*\]", r.stdout, re.S)
    if not m:
        sys.exit("没有返回 JSON 数组：\n" + r.stdout[:800])
    rows = json.loads(m.group(0))
    print("读出 %d 条：" % len(rows))
    for x in rows:
        print("   n=%-5s answer=%-24r conf=%s %s"
              % (x.get("n"), x.get("answer"), x.get("conf"),
                 x.get("where") or ""))
    bad = [x for x in rows if x.get("n") is None]
    print("\n题号没认出来的：%d 条" % len(bad))
    print("认不出作答的：%d 条" % sum(1 for x in rows if x.get("answer") == "unreadable"))
    print("\n下一步：把上面每一条**对着照片逐条核对**，数出题号错几个、作答错几个。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 跑探针**

Run: `.venv/bin/python pipeline/_probe_sheet.py work/_probe/sheet01.jpg`

- [ ] **Step 4: 对着照片逐条核对，把结论写下来**

数三个数，写进 `docs/superpowers/plans/2026-08-08-answer-sheet-grading.md` 末尾的「探针结论」一节：

| 指标 | 数值 | 判据 |
|---|---|---|
| 题号认对的比例 | ?/? | **低于 95% 就不合格** —— 题号错等于把张三的答案判到李四的题上，比认错作答坏得多 |
| 作答认对的比例 | ?/? | 低于 85% 要考虑退方案 |
| 认不出时老实说 unreadable 的比例 | ?/? | **它比认对率更重要**：老实认输的错是可见的，硬猜的错是不可见的 |

**第三个数是关键。** 如果模型在看不清时倾向于编一个像样的答案而不是回 `unreadable`，那整个「自动阅卷 + 红绿灯」的设计前提就不成立 —— 因为红绿灯靠的正是它自己承认判不了。

- [ ] **Step 5: 决定继续还是换方案**

- 三个数都过 → 继续 Task 5
- 题号认不准 → 先试「让模型只读题号栏、不读作答」拆成两次调用；仍不行则退方案
- 老实认输率低 → 提示词里加更强的认输出口再试一次；仍不行则退回「老师先批改再传」

- [ ] **Step 6: 删掉探针脚本，提交结论**

```bash
rm pipeline/_probe_sheet.py
git add docs/superpowers/plans/2026-08-08-answer-sheet-grading.md
git commit -m "docs: 手写探针结论"
```

---

### Task 2: `pages.py` —— 一批文件 → 规范化页面图

**Files:**
- Create: `pipeline/pages.py`
- Create: `tests/test_pages.py`

**Interfaces:**
- Consumes: Pillow、`ingest.py` 的渲染方式
- Produces:
  - `pages.sort_key(filename: str) -> tuple` — 自然排序键（`IMG_2.jpg` 排在 `IMG_10.jpg` 前面）
  - `pages.exif_rotate(im) -> Image` — 按 EXIF 转正
  - `pages.normalize(paths: list[str], outdir: str, prefix: str = "p") -> list[dict]` — 返回 `[{"page": 1, "hires": 路径, "web": 路径, "sha256": str}]`

- [ ] **Step 1: 写失败的测试**

`tests/test_pages.py`：

```python
# -*- coding: utf-8 -*-
import os
from PIL import Image
import pages


def test_自然排序不按字典序():
    names = ["IMG_10.jpg", "IMG_2.jpg", "IMG_1.jpg"]
    assert sorted(names, key=pages.sort_key) == ["IMG_1.jpg", "IMG_2.jpg", "IMG_10.jpg"]


def test_同名不同扩展名也稳定():
    names = ["a2.png", "a10.png", "a1.png"]
    assert sorted(names, key=pages.sort_key) == ["a1.png", "a2.png", "a10.png"]


def test_没有数字的按名字排():
    names = ["b.jpg", "a.jpg"]
    assert sorted(names, key=pages.sort_key) == ["a.jpg", "b.jpg"]


def _make(tmp_path, name, size=(1200, 1600), orientation=None):
    p = tmp_path / name
    im = Image.new("RGB", size, (240, 240, 240))
    if orientation:
        exif = im.getexif()
        exif[274] = orientation          # 274 = Orientation
        im.save(p, exif=exif)
    else:
        im.save(p)
    return str(p)


def test_横过来的照片被转正(tmp_path):
    # orientation=6 表示「顺时针转 90 度才是正的」。不转正的话模型认不出题号
    src = _make(tmp_path, "x.jpg", size=(1600, 1200), orientation=6)
    out = tmp_path / "out"
    got = pages.normalize([src], str(out))
    with Image.open(got[0]["hires"]) as im:
        assert im.height > im.width, "EXIF 转正没生效"


def test_页序按文件名而不是传入顺序(tmp_path):
    a = _make(tmp_path, "IMG_10.jpg")
    b = _make(tmp_path, "IMG_2.jpg")
    got = pages.normalize([a, b], str(tmp_path / "out"))
    assert [g["page"] for g in got] == [1, 2]
    assert "IMG_2" in got[0]["src"] and "IMG_10" in got[1]["src"]


def test_出两档分辨率(tmp_path):
    src = _make(tmp_path, "a.jpg", size=(2400, 3200))
    got = pages.normalize([src], str(tmp_path / "out"))[0]
    with Image.open(got["hires"]) as hi, Image.open(got["web"]) as lo:
        assert lo.width < hi.width, "web 档应该更小：整页读用它，裁块复读用 hires"


def test_内容一样哈希就一样(tmp_path):
    a = _make(tmp_path, "a.jpg")
    b = _make(tmp_path, "b.jpg")          # 内容相同、名字不同
    g = pages.normalize([a, b], str(tmp_path / "out"))
    assert g[0]["sha256"] == g[1]["sha256"], "按内容哈希，重传同一张不该重复烧钱"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_pages.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'pages'`

- [ ] **Step 3: 写 `pipeline/pages.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pages.py —— 一批文件（图片或 PDF）→ 规范化页面图

三条链共用：试卷图、答案图、答题卡图，前半段完全一样。写三遍必然写歪。

两档分辨率
----------
`hires` 300dpi 供裁块复读（这时才需要看清笔画），`web` 150dpi 供整页读
（认出短答案和位置足够，token 省一半）。`mathvlm.py` 就是这个配比。

页序不靠拖拽靠对账
------------------
`IMG_001…` 通常就是拍摄顺序，先按文件名自然排。排错了**不会静默** ——
答题卡上认出的题号会乱序，Ⓑ 那一步会把它报出来。拖拽只是让老师**能**改，
对账才让老师**知道要**改；后者更值钱，先做后者。
"""
import hashlib, os, re, shutil, subprocess, sys

HIRES_DPI = 300
WEB_SCALE = 0.5          # 150dpi

_NUM = re.compile(r"(\d+)")


def sort_key(name):
    """
    自然排序：`IMG_2` 排在 `IMG_10` 前面。

    按字典序排的话 `IMG_10` 会跑到 `IMG_2` 前面，页序错乱，而拍照的人
    绝对想不到是这个原因。
    """
    base = os.path.basename(name)
    return tuple((int(t) if t.isdigit() else t.lower())
                 for t in _NUM.split(base) if t != "")


def exif_rotate(im):
    """按 EXIF Orientation 转正。横过来的照片模型认不出题号。"""
    from PIL import Image, ImageOps
    return ImageOps.exif_transpose(im) or im


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pdf_to_pngs(pdf, outdir):
    """PDF → 逐页 PNG。用 pdftoppm（ingest.py 也是这条路）。"""
    stem = os.path.join(outdir, "_pdf")
    subprocess.run(["pdftoppm", "-png", "-r", str(HIRES_DPI), pdf, stem], check=True)
    return sorted((os.path.join(outdir, f) for f in os.listdir(outdir)
                   if f.startswith("_pdf") and f.endswith(".png")), key=sort_key)


def normalize(paths, outdir, prefix="p"):
    """
    一批文件 → `[{"page", "src", "hires", "web", "sha256"}]`，按页序。

    `paths` 里可以混着图片和一个 PDF。PDF 展开成多页，图片一张一页。
    """
    from PIL import Image
    os.makedirs(outdir, exist_ok=True)

    expanded = []
    for p in sorted(paths, key=sort_key):
        if p.lower().endswith(".pdf"):
            expanded += [(q, p) for q in _pdf_to_pngs(p, outdir)]
        else:
            expanded.append((p, p))

    out = []
    for i, (src, origin) in enumerate(expanded, 1):
        hi = os.path.join(outdir, "%s%02d.png" % (prefix, i))
        web = os.path.join(outdir, "%s%02d_web.png" % (prefix, i))
        with Image.open(src) as im:
            im = exif_rotate(im).convert("RGB")
            im.save(hi)
            im.resize((max(1, int(im.width * WEB_SCALE)),
                       max(1, int(im.height * WEB_SCALE))), Image.LANCZOS).save(web)
        out.append({"page": i, "src": origin, "hires": hi, "web": web,
                    "sha256": _sha(hi)})
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_pages.py -v`
Expected: `7 passed`

- [ ] **Step 5: 提交**

```bash
git add pipeline/pages.py tests/test_pages.py
git commit -m "feat: 加 pages.py —— 一批文件到规范化页面图

三条链（试卷图/答案图/答题卡图）前半段完全一样，写三遍必然写歪。

自然排序不能省：按字典序排的话 IMG_10 会跑到 IMG_2 前面，页序错乱，
而拍照的人绝对想不到是这个原因。

按内容哈希而不是文件名，重传同一张不重复烧钱 —— 跟 ②b 的缓存同源。"
```

---

### Task 3: 两张表与读写

**Files:**
- Modify: `pipeline/schema.sql`（文件末尾追加）
- Modify: `pipeline/store.py`
- Create: `tests/test_store_sheets.py`

**Interfaces:**
- Consumes: `papers` / `questions` / `assets`
- Produces:
  - `store.create_sheet(paper_name, student_label, owner_id) -> int`
  - `store.put_sheet_answer(sheet_id, n, **fields) -> None` — upsert，`fields` 见 SQL
  - `store.sheet_answers(sheet_id) -> list[dict]` — **每行带 `final_verdict`**
  - `store.set_teacher_verdict(sheet_id, n, verdict) -> None`
  - `store.list_sheets(paper_name) -> list[dict]`

- [ ] **Step 1: 建表**

在 `pipeline/schema.sql` 末尾追加：

```sql
-- ---------------------------------------------------------------- 期二：答题卡
-- 一份答题卡 = 一个学生的一次作答。
-- **不建 students 表**：范围定死单人、不做班级，学生就是老师随手填的一个标识。
-- 建了表就要配增删改查和「同一学生的历次考试」，那是另一个功能。
CREATE TABLE IF NOT EXISTS answer_sheets (
  id            bigserial PRIMARY KEY,
  paper_id      bigint NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  owner_id      bigint REFERENCES users(id) ON DELETE SET NULL,
  student_label text,
  n_pages       int NOT NULL DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now(),
  -- 老师改判会 touch 它。诊断过没过期，拿它跟 diagnoses.created_at 比 ——
  -- 跟 papers.assembled_at 判 out.html 旧没旧是同一个套路
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sheets_paper_idx ON answer_sheets (paper_id);

CREATE TABLE IF NOT EXISTS sheet_answers (
  id          bigserial PRIMARY KEY,
  sheet_id    bigint NOT NULL REFERENCES answer_sheets(id) ON DELETE CASCADE,
  -- **可空**：认出了题号但卷子里没这道题（串号、学生多写一道）。
  -- 挂不上就是挂不上，页面明说，不许猜一个最近的题号安上去
  question_id bigint REFERENCES questions(id) ON DELETE CASCADE,
  n           int  NOT NULL,
  raw_text    text,        -- 模型认出的最终作答，**原样**，不加工
  norm        text,        -- 归一化后的形式，判定拿它比
  crop_rel    text,        -- 原图切片的 assets.rel_path
  box         jsonb,
  page        int,
  read_conf   text,        -- 模型自称的把握 high/medium/low
  reread      boolean NOT NULL DEFAULT false,
  reread_raw  text,        -- 复读认出来的东西。两次都留着，页面标「复读后改判」

  -- **verdict_by 才是红绿灯** —— 同一个「错」，代码判的和模型判的
  -- 可信度差一个量级，页面必须分得出来
  verdict         text,    -- right | wrong | blank | unsure
  verdict_by      text,    -- code | model
  verdict_why     text,

  -- 老师改判**单独一列，不覆盖系统原判**。留着原判才看得出系统错在哪，
  -- 也才撤得回来。读取一律走 store.sheet_answers 里那一个 COALESCE，
  -- 不让每个调用点各写一份 —— api.ts 那次 401 广播就是这个教训
  teacher_verdict text,

  UNIQUE (sheet_id, n)
);
```

- [ ] **Step 2: 写失败的测试**

`tests/test_store_sheets.py`：

```python
# -*- coding: utf-8 -*-
import json
import store


def _paper(tmp_path, name, ns=(1, 2, 3)):
    d = tmp_path / name
    d.mkdir()
    (d / "questions.json").write_text(json.dumps({
        "source": "x.pdf", "sections": [], "warnings": [],
        "questions": [{"n": n, "type": "单选题", "stem": "第%d题" % n,
                       "options": [], "tables": [], "figures": []} for n in ns],
    }, ensure_ascii=False), encoding="utf-8")
    store.publish(str(d), name=name)
    return name


def test_建答题卡并写作答(db, tmp_path):
    name = _paper(tmp_path, "卡卷A")
    sid = store.create_sheet(name, "张三", None)
    qid = store.get_paper(name)["questions"][0]["id"]
    store.put_sheet_answer(sid, 1, question_id=qid, raw_text="B", norm="B",
                           verdict="right", verdict_by="code", verdict_why="字母集合相等")
    rows = store.sheet_answers(sid)
    assert len(rows) == 1
    assert rows[0]["n"] == 1 and rows[0]["raw_text"] == "B"
    assert rows[0]["final_verdict"] == "right"


def test_老师改判不覆盖原判(db, tmp_path):
    name = _paper(tmp_path, "卡卷B")
    sid = store.create_sheet(name, "李四", None)
    store.put_sheet_answer(sid, 1, raw_text="B", verdict="wrong", verdict_by="code")
    store.set_teacher_verdict(sid, 1, "right")
    r = store.sheet_answers(sid)[0]
    assert r["verdict"] == "wrong", "系统原判必须留着，否则看不出系统错在哪"
    assert r["teacher_verdict"] == "right"
    assert r["final_verdict"] == "right", "对外读到的应该是改判后的"


def test_改判能撤回(db, tmp_path):
    name = _paper(tmp_path, "卡卷C")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="code")
    store.set_teacher_verdict(sid, 1, "right")
    store.set_teacher_verdict(sid, 1, None)
    r = store.sheet_answers(sid)[0]
    assert r["teacher_verdict"] is None
    assert r["final_verdict"] == "wrong", "撤回后应该退回系统原判"


def test_改判会touch_updated_at(db, tmp_path):
    name = _paper(tmp_path, "卡卷D")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="code")
    before = store.list_sheets(name)[0]["updated_at"]
    store.set_teacher_verdict(sid, 1, "right")
    after = store.list_sheets(name)[0]["updated_at"]
    assert after > before, "诊断过没过期要靠它判"


def test_题号挂不上卷子也存得下(db, tmp_path):
    """认出了题号但卷子里没这道题。挂不上就是挂不上，不许安一个最近的"""
    name = _paper(tmp_path, "卡卷E", ns=(1, 2))
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 7, question_id=None, raw_text="C", verdict="unsure",
                           verdict_by="code", verdict_why="卷子里没有第7题")
    r = store.sheet_answers(sid)[0]
    assert r["question_id"] is None and r["n"] == 7


def test_同一题重写是覆盖不是追加(db, tmp_path):
    name = _paper(tmp_path, "卡卷F")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, raw_text="B", verdict="wrong", verdict_by="code")
    store.put_sheet_answer(sid, 1, raw_text="D", verdict="right", verdict_by="code")
    rows = store.sheet_answers(sid)
    assert len(rows) == 1 and rows[0]["raw_text"] == "D"


def test_删卷子会连答题卡一起删(db, tmp_path):
    name = _paper(tmp_path, "卡卷G")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, raw_text="B")
    store.delete_papers([name])
    assert store.sheet_answers(sid) == []
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_store_sheets.py -v`
Expected: FAIL，`AttributeError: module 'store' has no attribute 'create_sheet'`

- [ ] **Step 4: 写 store 函数**

在 `pipeline/store.py` 里 `put_ref_answer` 之后插入：

```python
# ---------------------------------------------------------------- 答题卡
# 允许写进 sheet_answers 的列。白名单而不是 **kwargs 直通 ——
# 拼错一个列名会静默写不进去，而阅卷结果错了页面上看不出来
_SHEET_COLS = ("question_id", "raw_text", "norm", "crop_rel", "box", "page",
               "read_conf", "reread", "reread_raw",
               "verdict", "verdict_by", "verdict_why")


def create_sheet(paper_name, student_label, owner_id, n_pages=0):
    """新建一份答题卡，返回 id。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""INSERT INTO answer_sheets (paper_id, owner_id, student_label, n_pages)
                       SELECT p.id, %s, %s, %s FROM papers p WHERE p.name=%s
                       RETURNING id""",
                    (owner_id, student_label, n_pages, paper_name))
        row = cur.fetchone()
        if not row:
            raise ValueError("库里没有「%s」" % paper_name)
        c.commit()
        return row[0]


def put_sheet_answer(sheet_id, n, **fields):
    """
    写一题的作答与判定。**按 (sheet_id, n) 覆盖，不追加** ——
    复读会把同一题再写一次，追加的话页面上会出现两行。
    """
    bad = set(fields) - set(_SHEET_COLS)
    if bad:
        raise ValueError("不认识的列：%s" % ", ".join(sorted(bad)))
    cols = [k for k in _SHEET_COLS if k in fields]
    vals = [json.dumps(fields[k], ensure_ascii=False) if k == "box" else fields[k]
            for k in cols]
    sets = ", ".join("%s=EXCLUDED.%s" % (k, k) for k in cols)
    with connect() as c:
        c.execute("""INSERT INTO sheet_answers (sheet_id, n%s)
                     VALUES (%%s, %%s%s)
                     ON CONFLICT (sheet_id, n) DO UPDATE SET %s"""
                  % ("".join(", " + k for k in cols),
                     "".join(", %s" for _ in cols),
                     sets or "n=EXCLUDED.n"),
                  [sheet_id, n] + vals)
        c.commit()


def sheet_answers(sheet_id):
    """
    一份答题卡的全部作答，按题号。

    **`final_verdict` 只在这里算一次。** 老师改判存在单独一列，对外读到的
    必须是改判后的结果 —— 让每个调用点各写一份 COALESCE，总会漏掉一个，
    漏掉的那个表现为「老师改了判，某个地方还显示旧结果」。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT id, question_id, n, raw_text, norm, crop_rel, box, page,
                              read_conf, reread, reread_raw,
                              verdict, verdict_by, verdict_why, teacher_verdict,
                              COALESCE(teacher_verdict, verdict) AS final_verdict
                         FROM sheet_answers WHERE sheet_id=%s ORDER BY n""",
                    (sheet_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def set_teacher_verdict(sheet_id, n, verdict):
    """
    老师改判。`verdict=None` 表示撤回改判，退回系统原判。

    **不碰 verdict 那一列。** 留着原判才看得出系统错在哪，也才撤得回来。
    """
    if verdict not in (None, "right", "wrong", "blank", "unsure"):
        raise ValueError("verdict 只能是 right/wrong/blank/unsure 或 None，"
                         "给的是 %r" % verdict)
    with connect() as c:
        c.execute("UPDATE sheet_answers SET teacher_verdict=%s WHERE sheet_id=%s AND n=%s",
                  (verdict, sheet_id, n))
        # 诊断过没过期靠它判，所以改判必须 touch
        c.execute("UPDATE answer_sheets SET updated_at=now() WHERE id=%s", (sheet_id,))
        c.commit()


def list_sheets(paper_name):
    """这份卷子下面的所有答题卡，新的在前。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT s.id, s.student_label, s.n_pages, s.created_at, s.updated_at,
                              (SELECT count(*) FROM sheet_answers a WHERE a.sheet_id=s.id),
                              (SELECT count(*) FROM sheet_answers a WHERE a.sheet_id=s.id
                                AND COALESCE(a.teacher_verdict, a.verdict)='wrong')
                         FROM answer_sheets s JOIN papers p ON p.id=s.paper_id
                        WHERE p.name=%s ORDER BY s.created_at DESC""", (paper_name,))
        return [{"id": r[0], "student": r[1], "nPages": r[2],
                 "created_at": r[3], "updated_at": r[4],
                 "answers": r[5], "wrong": r[6]} for r in cur.fetchall()]
```

- [ ] **Step 5: 灌 schema 并跑测试**

```bash
.venv/bin/python pipeline/store.py init
.venv/bin/pytest tests/test_store_sheets.py -v
```

Expected: `7 passed`

- [ ] **Step 6: 提交**

```bash
git add pipeline/schema.sql pipeline/store.py tests/test_store_sheets.py
git commit -m "feat: 加 answer_sheets / sheet_answers 两张表

老师改判写单独一列，不覆盖系统原判：留着原判才看得出系统错在哪，
也才撤得回来。final_verdict 的 COALESCE 只在 store.sheet_answers 里
算一次 —— 让每个调用点各写一份，总会漏掉一个，漏掉的那个表现为
「老师改了判，某个地方还显示旧结果」。

put_sheet_answer 用列白名单而不是 kwargs 直通：拼错一个列名会静默
写不进去，而阅卷结果错了页面上看不出来。"
```

---

### Task 4: `grade.py` —— 判对错的归一化

**这是本期唯一能真正自动测的部分，要测厚。**

**Files:**
- Create: `pipeline/grade.py`
- Create: `tests/test_grade.py`
- Modify: `pipeline/api.py`（`answers_agree` 改用同一套数值解析）
- Modify: `tests/test_answers_agree.py`（跟着改一条断言）

**Interfaces:**
- Consumes: 无
- Produces:
  - `grade.norm_text(s) -> str` — NFKC + 去空白去标点 + 大写
  - `grade.as_choice(s) -> str | None` — 纯 A-D 字母时回排序去重后的字母串
  - `grade.as_number(s) -> tuple[float, str] | None` — `(值, 单位)`；支持分数、科学计数、带单位
  - `grade.norm_expr(s) -> str` — LaTeX 归一化
  - `grade.split_blanks(s) -> list[str]` — 多空答案按 `/` 拆
  - `grade.judge(student, ref) -> tuple[str | None, str]` — `('right'|'wrong', 理由)` 或 `(None, 为什么判不了)`

- [ ] **Step 1: 写失败的测试**

`tests/test_grade.py`：

```python
# -*- coding: utf-8 -*-
import grade


# ---------------------------------------------------------------- 选择题
def test_选择题字母集合():
    assert grade.as_choice("BD") == "BD"
    assert grade.as_choice("db") == "BD"
    assert grade.as_choice("B D") == "BD"
    assert grade.as_choice("B、D") == "BD"
    assert grade.as_choice("BBD") == "BD", "重复的字母去掉"


def test_不是选择题就回None():
    assert grade.as_choice("0.4 m") is None
    assert grade.as_choice("E") is None, "只认 A-D"
    assert grade.as_choice("") is None


def test_判选择题():
    assert grade.judge("BD", "DB")[0] == "right"
    assert grade.judge("B", "BD")[0] == "wrong"


# ---------------------------------------------------------------- 数值
def test_数值带单位():
    assert grade.as_number("1.5 m/s") == (1.5, "M/S")
    assert grade.as_number("1.5m/s") == (1.5, "M/S")
    assert grade.as_number("0.40") == (0.4, "")


def test_分数和科学计数():
    assert grade.as_number("3/2")[0] == 1.5
    assert grade.as_number("1.6e-19 C")[0] == 1.6e-19
    assert grade.as_number("1.6×10^-19 C")[0] == 1.6e-19


def test_判数值():
    assert grade.judge("0.40 m", "0.4 m")[0] == "right"
    assert grade.judge("0.5 m", "0.4 m")[0] == "wrong"
    assert grade.judge("3/2", "1.5")[0] == "right"


def test_单位对不上不判错而是判不了():
    """「1.5 m/s」和「1.5 米每秒」很可能是同一个答案。判错会让做对的
    学生凭空多一个薄弱知识点 —— 宁可交给模型。"""
    v, why = grade.judge("1.5 m/s", "1.5 米每秒")
    assert v is None and "单位" in why


# ---------------------------------------------------------------- 表达式
def test_latex归一化():
    assert grade.norm_expr(r"\dfrac{1}{2}mv^2") == grade.norm_expr(r"\frac{1}{2}mv^{2}")
    assert grade.norm_expr("a·b") == grade.norm_expr(r"a\cdot b")


def test_判表达式():
    assert grade.judge(r"\dfrac{1}{2}mv^2", r"\frac{1}{2} m v^{2}")[0] == "right"


# ---------------------------------------------------------------- 多空
def test_多空按空比():
    assert grade.split_blanks("小于 / 等于 / 小于") == ["小于", "等于", "小于"]
    assert grade.judge("小于/等于/小于", "小于 / 等于 / 小于")[0] == "right"
    assert grade.judge("小于/大于/小于", "小于 / 等于 / 小于")[0] == "wrong"


def test_空数对不上是判不了():
    v, why = grade.judge("小于/等于", "小于 / 等于 / 小于")
    assert v is None and "空" in why


# ---------------------------------------------------------------- 判不了
def test_形式差得远就交给模型():
    v, why = grade.judge("见解析", "0.4 m")
    assert v is None


def test_有一边为空一律判不了():
    assert grade.judge("", "BD")[0] is None
    assert grade.judge("BD", None)[0] is None


def test_绝不静默判等():
    """代码档只做不会静默出错的事。sympy 那类符号等价一律不做 ——
    翻车的样子是「静默给出一个错误的等价判断」，页面上一切正常"""
    v, _ = grade.judge("mgh", "mgH")
    assert v == "wrong", "大小写不同就是不同，不许猜它们是一回事"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_grade.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'grade'`

- [ ] **Step 3: 写 `pipeline/grade.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grade.py —— 判对错的归一化

**纯函数，不碰网络也不碰库。** 本期所有的判定正确性都在这里，所以它必须
能单独测，而且要测厚。

只做不会静默出错的两件事
------------------------
归一化字符串比、数值比。它们要么明确相等要么明确不等，没有第三种。

**不引 sympy。** 它解析带单位带下标的中文物理题 LaTeX 容易翻车，而翻车的
样子是「静默给出一个错误的等价判断」—— 学生答对的题被判错，凭空造出一个
薄弱知识点，页面上一切看起来正常。

判不了就说判不了
----------------
`judge` 回 `(None, 原因)` 表示代码档下不了结论，交给模型档。**绝不猜。**
判错的代价是不对称的：判对了没人受损，判错了会凭空造出一个假的薄弱知识点，
而薄弱知识点是这个功能唯一的产出。
"""
import re, unicodedata

_PUNCT = re.compile(r"[\s。，、；：．,;:!？?（）()【】\[\]]+")
_CHOICE = re.compile(r"[A-D]+")
# 数值 + 单位：`1.5`、`3/2`、`1.6e-19`、`1.6×10^-19`
_NUM = re.compile(r"""^\s*
    (?P<sign>[-+])?\s*
    (?: (?P<a>\d+(?:\.\d+)?)\s*(?:[×xX*]\s*10\s*\^?\s*(?P<exp>[-+]?\d+))
      | (?P<b>\d+(?:\.\d+)?)\s*[eE]\s*(?P<exp2>[-+]?\d+)
      | (?P<num>\d+(?:\.\d+)?)\s*/\s*(?P<den>\d+(?:\.\d+)?)
      | (?P<c>\d+(?:\.\d+)?) )
    \s*(?P<unit>.*)$""", re.X)

_SUBSUP = {"₀": "_0", "₁": "_1", "₂": "_2", "₃": "_3", "₄": "_4",
           "⁰": "^0", "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4"}


def norm_text(s):
    """NFKC 折全角、去空白与标点、转大写。"""
    if s is None:
        return ""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", str(s)).strip().upper())


def as_choice(s):
    """纯 A-D 字母时回排序去重后的字母串，否则 None。"""
    t = norm_text(s)
    if not t or not _CHOICE.fullmatch(t):
        return None
    return "".join(sorted(set(t)))


def as_number(s):
    """`(值, 大写单位)`，解析不了回 None。分数、科学计数都认。"""
    if s is None:
        return None
    t = unicodedata.normalize("NFKC", str(s)).strip()
    m = _NUM.match(t)
    if not m:
        return None
    g = m.groupdict()
    if g["a"] is not None:
        v = float(g["a"]) * (10.0 ** int(g["exp"]))
    elif g["b"] is not None:
        v = float(g["b"]) * (10.0 ** int(g["exp2"]))
    elif g["num"] is not None:
        den = float(g["den"])
        if den == 0:
            return None
        v = float(g["num"]) / den
    else:
        v = float(g["c"])
    if g["sign"] == "-":
        v = -v
    return (v, _PUNCT.sub("", (g["unit"] or "").upper()))


def norm_expr(s):
    """LaTeX 归一化：去空白、`\\dfrac`→`\\frac`、`·`→`\\cdot`、上下标统一。"""
    t = unicodedata.normalize("NFC", str(s or ""))
    for k, v in _SUBSUP.items():
        t = t.replace(k, v)
    t = t.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    t = t.replace("·", "\\cdot").replace("×", "\\times")
    t = re.sub(r"\^\{([^{}])\}", r"^\1", t)     # ^{2} → ^2
    t = re.sub(r"_\{([^{}])\}", r"_\1", t)
    return re.sub(r"\s+", "", t)


def split_blanks(s):
    """多空答案按 `/` 拆。`小于 / 等于 / 小于` → 三个空。"""
    return [x.strip() for x in re.split(r"\s*/\s*", str(s or "")) if x.strip()]


def _same_number(a, b):
    """相对误差 1e-6 内算相等。`0.40` 和 `0.4` 是同一个答案。"""
    if a[1] != b[1]:
        return None                       # 单位对不上，代码档不下结论
    x, y = a[0], b[0]
    if x == y:
        return True
    return abs(x - y) <= 1e-6 * max(abs(x), abs(y), 1e-12)


def judge(student, ref):
    """
    代码档判定。回 `('right'|'wrong', 理由)`，或 `(None, 为什么判不了)`。

    判不了不是失败，是**明确地把结论交出去**。绝不猜。
    """
    if not str(student or "").strip() or not str(ref or "").strip():
        return (None, "有一边没有内容，判不了")

    # 多空：先按空拆。空数对不上就判不了 —— 可能是分隔符不统一，不是学生错
    sb, rb = split_blanks(student), split_blanks(ref)
    if len(rb) > 1 or len(sb) > 1:
        if len(sb) != len(rb):
            return (None, "空的个数对不上（学生 %d 个、标准答案 %d 个），判不了"
                          % (len(sb), len(rb)))
        whys = []
        for i, (a, b) in enumerate(zip(sb, rb), 1):
            v, w = judge(a, b)
            if v is None:
                return (None, "第 %d 空判不了：%s" % (i, w))
            if v == "wrong":
                return ("wrong", "第 %d 空不对（%s ≠ %s）" % (i, a, b))
            whys.append(w)
        return ("right", "%d 个空全对" % len(rb))

    # 选择题
    ca, cb = as_choice(student), as_choice(ref)
    if ca is not None and cb is not None:
        return ("right", "选项集合相等") if ca == cb else \
               ("wrong", "选了 %s，标准答案 %s" % (ca, cb))

    # 数值
    na, nb = as_number(student), as_number(ref)
    if na is not None and nb is not None:
        same = _same_number(na, nb)
        if same is None:
            return (None, "单位对不上（%s vs %s），判不了" % (na[1] or "无", nb[1] or "无"))
        return ("right", "数值相等") if same else \
               ("wrong", "%g 不等于 %g" % (na[0], nb[0]))

    # 表达式 / 纯文字：归一化后完全相同才算对
    ea, eb = norm_expr(student), norm_expr(ref)
    if ea == eb:
        return ("right", "归一化后完全相同")
    ta, tb = norm_text(student), norm_text(ref)
    if ta == tb:
        return ("right", "文字归一化后相同")
    # 两边都短且都是纯文字（「小于」「等于」这种），可以放心判不等
    if len(ta) <= 6 and len(tb) <= 6 and ta.isalpha() is False and tb.isalpha() is False:
        return ("wrong", "「%s」不是「%s」" % (student, ref))
    if len(ea) <= 40 and len(eb) <= 40:
        return ("wrong", "归一化后不同：%s ≠ %s" % (ea, eb))
    return (None, "形式差得远，代码判不了")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_grade.py -v`
Expected: `15 passed`

- [ ] **Step 5: 让 `answers_agree` 用同一套数值解析**

期一那个 `answers_agree`（卷子答案 vs AI 答案的红绿灯）自己写了一份归一化，跟 `grade.py` 重了一份。**两份判等逻辑迟早会漂**，改成复用。

在 `pipeline/api.py` 里，把 `answers_agree` 整个函数体换成：

```python
def answers_agree(a, b):
    """
    卷子上的标准答案与 ③ 的 AI 答案是不是一回事。

    **任一边为空回 None，不是 False。** 「比不了」和「对不上」在页面上是
    两句完全不同的话：前者是缺数据，后者是有一方错了。压成 False 等于
    在没有任何证据的情况下指认 AI 解错了。

    判据跟阅卷共用 `grade.judge` —— 两份判等逻辑迟早会漂，而漂的后果是
    「页面说不一致、阅卷说一致」这种自相矛盾。
    """
    v, _ = grade.judge(a, b)
    return None if v is None else (v == "right")
```

并在 `api.py` 的 import 区加 `import grade`；`_PUNCT` 那个常量如果没有别的用处就删掉。

- [ ] **Step 6: 跟着改一条断言**

`tests/test_answers_agree.py` 里 `test_不做数值等价` 现在的期望反了 —— 共用 `grade` 之后 `3/2` 和 `1.5` 会判等，而这是**对的**：分数转浮点是精确可验的，不是 sympy 那种会静默出错的符号推理。把它换成：

```python
def test_分数与小数判等():
    # 分数转浮点是精确可验的，不是 sympy 那种会静默出错的符号推理。
    # 共用 grade.judge 之后这里跟阅卷口径一致 —— 两份判等逻辑迟早会漂
    assert api.answers_agree("3/2", "1.5") is True
```

- [ ] **Step 7: 全量跑一遍**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全绿

- [ ] **Step 8: 提交**

```bash
git add pipeline/grade.py pipeline/api.py tests/test_grade.py tests/test_answers_agree.py
git commit -m "feat: 加 grade.py 判对错的归一化，并让 answers_agree 复用

本期唯一能真正自动测的部分，所以测得厚：选择题字母集合、数值+单位、
分数与科学计数、LaTeX 归一化、多空按空比。

三处刻意判不了而不是判错（回 None 交给模型）：单位对不上、空的个数
对不上、形式差得远。判错的代价不对称 —— 判对了没人受损，判错了会
凭空造出一个假的薄弱知识点，而那是这个功能唯一的产出。

answers_agree 原来自己写了一份归一化，跟 grade 重了一份。两份判等
逻辑迟早会漂，漂的后果是「页面说不一致、阅卷说一致」。"
```

---

### Task 5: Ⓑ 读答案（依赖 Task 1 探针结论）

**Files:**
- Modify: `pipeline/mathvlm.py`（抽出 `ask_raw`，`ask_model` 改为调它）
- Create: `pipeline/sheet.py`
- Create: `tests/test_sheet_parse.py`

**Interfaces:**
- Consumes: `mathvlm.ask_raw`、`mathvlm.crop`、`pages.normalize`、`store.put_asset`
- Produces:
  - `mathvlm.ask_raw(img_path, prompt, want="object"|"array", timeout=240) -> dict|list`
  - `sheet.parse_rows(rows, paper_ns) -> list[dict]` — 纯函数，过模型原始输出
  - `sheet.read_sheet(sheet_id, paper_name, page_files) -> int` — 读+裁+落库，返回读到几题

- [ ] **Step 1: 写失败的测试（只测纯函数）**

`tests/test_sheet_parse.py`：

```python
# -*- coding: utf-8 -*-
import sheet

NS = [1, 2, 3]


def test_正常一条():
    got = sheet.parse_rows([{"n": 1, "answer": "B", "conf": "high",
                             "box": [0, 0, 10, 10]}], NS)
    assert got[0]["n"] == 1 and got[0]["raw_text"] == "B"
    assert got[0]["read_conf"] == "high" and got[0]["blank"] is False


def test_空白和认不出分得开():
    got = {r["n"]: r for r in sheet.parse_rows(
        [{"n": 1, "answer": "blank"}, {"n": 2, "answer": "unreadable"}], NS)}
    assert got[1]["blank"] is True and got[1]["unreadable"] is False
    assert got[2]["unreadable"] is True and got[2]["blank"] is False


def test_题号没认出来的留着不丢():
    """n=null 是防串题的主要手段，必须留痕让老师看见"""
    got = sheet.parse_rows([{"n": None, "answer": "C", "where": "第二列第三格"}], NS)
    assert len(got) == 1 and got[0]["n"] is None
    assert "第二列第三格" in (got[0]["where"] or "")


def test_卷子里没有的题号也留着():
    got = sheet.parse_rows([{"n": 7, "answer": "C"}], NS)
    assert got[0]["n"] == 7 and got[0]["in_paper"] is False


def test_同题号多页按页序拼():
    got = sheet.parse_rows([{"n": 3, "answer": "先求v", "page": 1},
                            {"n": 3, "answer": "再代入", "page": 2}], NS)
    assert len(got) == 1
    assert got[0]["raw_text"] == "先求v 再代入"
    assert got[0]["page"] == 1, "box 与页取第一处"


def test_烂数据不炸():
    got = sheet.parse_rows([None, "串", {"answer": "B"}, {"n": "甲", "answer": "B"},
                            {"n": 1, "answer": "B"}], NS)
    assert [r["n"] for r in got] == [1]


def test_作答原样保留不加工():
    got = sheet.parse_rows([{"n": 1, "answer": "  BD  "}], NS)
    assert got[0]["raw_text"] == "BD", "只去首尾空白"
    got = sheet.parse_rows([{"n": 1, "answer": "0．40ｍ"}], NS)
    assert got[0]["raw_text"] == "0．40ｍ", "全角原样留着，归一化是 grade 的事"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_sheet_parse.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'sheet'`

- [ ] **Step 3: 从 mathvlm 抽出 `ask_raw`**

在 `pipeline/mathvlm.py` 里，把现有的 `ask_model` 换成下面两个函数（**行为不变**，只是把「要对象还是要数组」参数化，好让答题卡复用同一条视觉通道）：

```python
def ask_raw(img_path, prompt, want="object", timeout=240):
    """
    调视觉模型读一张图，返回解析后的 JSON。

    `want="array"` 时找 `[...]`，否则找 `{...}`。答题卡那条链要的是数组，
    这里参数化一下，免得两处各写一份调用与容错。
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

- [ ] **Step 4: 跑一遍 ②b 的既有卷子，确认没跑坏**

```bash
.venv/bin/python pipeline/mathvlm.py work/2025年高考北京卷物理真题
```

Expected: 全部命中缓存、0 次模型调用、无报错。**这一步是为了证明抽函数没改坏行为**，不是为了产出。

- [ ] **Step 5: 写 `pipeline/sheet.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sheet.py —— 答题卡：Ⓑ 读答案

    python pipeline/sheet.py <卷名> <答题卡id> <图1> [图2 ...]

整页图进，`[{题号, 框, 最终作答, 把握}]` 出，随即按框裁出小图落库。

为什么当场裁图
--------------
原图切片是这个功能**唯一的红绿灯** —— 老师一眼能校对系统判得对不对。
推迟到「老师要看时再裁」的话，页面图可能已经被清理了。它必须和判定
一起落库。

给模型一个明确的认输出口
------------------------
提示词上那几条从 `solve.py` 的经验来：它记着「DeepSeek 老老实实回
NEED_FIGURE 而不是编一个读起来合理的答案」。**给模型一个明确的认输出口，
比反复叮嘱别猜有用得多。**
"""
import argparse, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mathvlm
import pages
import store

PROMPT = """这是一张学生的手写答题卡照片。上面只有题号和作答区，没有题干。

逐题读出学生**最终写下的作答**，输出 JSON 数组（不要代码块围栏、不要解释）：
[{"n": 3, "answer": "B", "conf": "high", "box": [x0, y0, x1, y1]}, ...]

`box` 是这条作答在图上的像素框（左上角为原点）。

四条硬规则：

1. **题号必须是图上真实认出来的**，绝对不许按顺序编。看到了作答但看不清
   是第几题，就写 `"n": null` 并在 `"where"` 里描述它的位置。
2. 认不出写的是什么，`answer` 写 `"unreadable"`。**认不出比猜错好** ——
   这些作答会拿去判学生对错，猜错一个就凭空造出一个假的薄弱知识点。
3. 该题空着没写，`answer` 写 `"blank"`。不许拿附近的字凑。
4. `conf` 是你自己的把握：high / medium / low。

作答**原样转写**，不要改写、不要润色、不要补全单位。
"""


def parse_rows(rows, paper_ns):
    """
    把模型的原始输出过成可以入库的形状。**纯函数**，所有正确性判断在这里。

    同一题号在多页出现按页序拼接（跨页大题），`box` 与 `page` 取第一处。
    题号没认出来的（n=null）和卷子里没有的都**留着不丢** —— 它们是防串题
    的主要证据，必须让老师看见。
    """
    valid, by_n, loose = set(paper_ns), {}, []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        ans = str(r.get("answer") or "").strip()
        item = {"raw_text": ans, "read_conf": r.get("conf"),
                "box": r.get("box"), "page": r.get("page") or 1,
                "where": r.get("where"),
                "blank": ans == "blank", "unreadable": ans == "unreadable"}
        n = r.get("n")
        if n is None:
            loose.append({**item, "n": None, "in_paper": False})
            continue
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if n in by_n:
            prev = by_n[n]
            # 跨页续写：拼接文本，框与页留第一处
            if ans and not prev["blank"] and not prev["unreadable"]:
                prev["raw_text"] = (prev["raw_text"] + " " + ans).strip()
            continue
        by_n[n] = {**item, "n": n, "in_paper": n in valid}
    return [by_n[k] for k in sorted(by_n)] + loose


def read_sheet(sheet_id, paper_name, page_files, verbose=True):
    """整页读 + 裁块落库，返回读到几题。"""
    log = print if verbose else (lambda *a, **k: None)
    paper = store.get_paper(paper_name)
    if not paper:
        raise ValueError("库里没有「%s」" % paper_name)
    qid_of = {q["n"]: q["id"] for q in paper["questions"]}

    work = os.path.join(ROOT, "work", "_sheets", str(sheet_id))
    pgs = pages.normalize(page_files, work, prefix="page")
    store.set_sheet_pages(sheet_id, len(pgs))

    raw = []
    for pg in pgs:
        got = mathvlm.ask_raw(pg["web"], PROMPT, want="array", timeout=300)
        for r in (got if isinstance(got, list) else []):
            if isinstance(r, dict):
                r.setdefault("page", pg["page"])
        raw += got if isinstance(got, list) else []

    rows = parse_rows(raw, list(qid_of))
    if not rows:
        raise RuntimeError("这张答题卡上一道题都没读出来。多半是拍歪了或传错了文件，"
                           "请重拍后再试。")

    by_page = {p["page"]: p for p in pgs}
    for r in rows:
        crop_rel = None
        if r.get("box") and r["page"] in by_page:
            dst = os.path.join(work, "q%s.png" % (r["n"] if r["n"] is not None
                                                  else "x%d" % len(rows)))
            _crop_box(by_page[r["page"]]["hires"], r["box"], dst)
            crop_rel = "sheets/%d/%s" % (sheet_id, os.path.basename(dst))
            store.put_asset(dst, crop_rel, paper_name=paper_name)
        store.put_sheet_answer(
            sheet_id, r["n"] if r["n"] is not None else -len(rows),
            question_id=qid_of.get(r["n"]), raw_text=r["raw_text"],
            crop_rel=crop_rel, box=r.get("box"), page=r["page"],
            read_conf=r.get("read_conf"))
        log("   第%s题 %s%s" % (r["n"] if r["n"] is not None else "?",
                               r["raw_text"][:30],
                               "" if r["in_paper"] else "  ⚠ 卷子里没有这道题"))
    log("── 读出 %d 题" % len(rows))
    return len(rows)


def _crop_box(page_png, box, dst):
    """按像素框裁。box 是模型给的 [x0,y0,x1,y1]，可能越界，夹一下。"""
    from PIL import Image
    x0, y0, x1, y1 = [int(v) for v in box]
    with Image.open(page_png) as im:
        # web 档给的框，hires 是它的 1/WEB_SCALE 倍
        k = 1.0 / pages.WEB_SCALE
        im.crop((max(0, int(x0 * k)), max(0, int(y0 * k)),
                 min(im.width, int(x1 * k)), min(im.height, int(y1 * k)))).save(dst)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("sheet_id", type=int)
    ap.add_argument("images", nargs="+")
    a = ap.parse_args()
    read_sheet(a.sheet_id, a.paper, a.images)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

同时在 `store.py` 里补一个小函数（`read_sheet` 用得到）：

```python
def set_sheet_pages(sheet_id, n):
    with connect() as c:
        c.execute("UPDATE answer_sheets SET n_pages=%s WHERE id=%s", (n, sheet_id))
        c.commit()
```

并让 `put_asset` 接受 `paper_name`（它现在按 `paper_id` 写；答题卡切片挂在所属卷子上，`rel_path` 用 `sheets/<id>/...` 前缀，`UNIQUE (paper_id, rel_path)` 仍成立）。**改之前先读一遍 `put_asset` 现有签名**，按它的实际形状接上，不要照抄这里的调用。

- [ ] **Step 6: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_sheet_parse.py -v`
Expected: `7 passed`

- [ ] **Step 7: 拿探针那张真图端到端跑一次**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'pipeline'); import store
print(store.create_sheet('2025年高考北京卷物理真题','探针学生',None))"
.venv/bin/python pipeline/sheet.py 2025年高考北京卷物理真题 <上面打印的id> work/_probe/sheet01.jpg
```

Expected: 逐题打印题号与作答，末尾「读出 N 题」。**再打开 `work/_sheets/<id>/` 逐张看裁出来的小图对不对** —— 裁歪了这个功能唯一的红绿灯就废了。

- [ ] **Step 8: 提交**

```bash
git add pipeline/sheet.py pipeline/mathvlm.py pipeline/store.py tests/test_sheet_parse.py
git commit -m "feat: 加 Ⓑ 读答案，与 ②b 共用同一条视觉通道

从 mathvlm 抽出 ask_raw（对象/数组参数化），行为不变，免得两处各写
一份调用与容错。抽完跑了一遍北京卷确认全命中缓存、没跑坏。

当场裁图不推迟：原图切片是这个功能唯一的红绿灯，页面图可能已经被
清理，它必须和判定一起落库。

题号没认出来的（n=null）和卷子里没有的都留着不丢 —— 它们是防串题的
主要证据，必须让老师看见。"
```

---

### Task 6: Ⓒ 判对错 + 判错复读

**Files:**
- Modify: `pipeline/sheet.py`（加 `grade_sheet` 与复读）
- Create: `tests/test_sheet_grade.py`

**Interfaces:**
- Consumes: `grade.judge`、`store.sheet_answers`、`mathvlm.ask_raw`
- Produces:
  - `sheet.decide(row, ref_answer, ref_src) -> tuple[verdict, by, why]` — 纯函数
  - `sheet.needs_reread(row) -> bool` — 纯函数
  - `sheet.grade_sheet(sheet_id, paper_name) -> dict` — 计数

- [ ] **Step 1: 写失败的测试**

`tests/test_sheet_grade.py`：

```python
# -*- coding: utf-8 -*-
import sheet


def R(**kw):
    base = dict(n=1, raw_text="B", blank=False, unreadable=False,
                read_conf="high", in_paper=True)
    return {**base, **kw}


def test_代码判对():
    v, by, why = sheet.decide(R(raw_text="BD"), "DB", "paper")
    assert (v, by) == ("right", "code")


def test_代码判错():
    v, by, why = sheet.decide(R(raw_text="B"), "BD", "paper")
    assert (v, by) == ("wrong", "code")


def test_空白不是错():
    v, by, why = sheet.decide(R(blank=True, raw_text="blank"), "BD", "paper")
    assert v == "blank", "卷子最后几道空白多半是时间不够而不是不会"


def test_认不出是判不了不是错():
    v, by, why = sheet.decide(R(unreadable=True, raw_text="unreadable"), "BD", "paper")
    assert v == "unsure"


def test_卷子没答案是判不了且要说清楚是谁的问题():
    v, by, why = sheet.decide(R(raw_text="B"), None, "none")
    assert v == "unsure"
    assert "卷子" in why, "得让老师看出这不是学生的问题"


def test_题号挂不上卷子也是判不了():
    v, by, why = sheet.decide(R(n=7, in_paper=False), None, None)
    assert v == "unsure"


def test_代码判不了就交给模型档():
    v, by, why = sheet.decide(R(raw_text="见解析，先由动量守恒求出碰后速度再代入动能定理"),
                              "0.4 m", "paper")
    assert v is None, "None 表示要升级到模型，不是判不了"


# ---------------------------------------------------------------- 复读
def test_判错的要复读():
    assert sheet.needs_reread({"verdict": "wrong", "read_conf": "high",
                               "in_paper": True}) is True


def test_认不出的要复读():
    assert sheet.needs_reread({"verdict": "unsure", "unreadable": True,
                               "read_conf": "high", "in_paper": True}) is True


def test_把握低的要复读():
    assert sheet.needs_reread({"verdict": "right", "read_conf": "low",
                               "in_paper": True}) is True


def test_题号挂不上的要复读():
    assert sheet.needs_reread({"verdict": "unsure", "read_conf": "high",
                               "in_paper": False}) is True


def test_判对且把握高的不复读():
    assert sheet.needs_reread({"verdict": "right", "read_conf": "high",
                               "in_paper": True}) is False


def test_空白的不复读():
    """空白就是空白，复读一次也还是空白，纯烧钱"""
    assert sheet.needs_reread({"verdict": "blank", "read_conf": "high",
                               "in_paper": True}) is False


def test_复读只跑一次():
    assert sheet.needs_reread({"verdict": "wrong", "read_conf": "high",
                               "in_paper": True, "reread": True}) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_sheet_grade.py -v`
Expected: FAIL，`AttributeError: module 'sheet' has no attribute 'decide'`

- [ ] **Step 3: 在 `sheet.py` 里加判定**

```python
import grade

REREAD_PROMPT = """这是一张学生答题卡上**某一道题**的作答区放大图。

只回答一件事：学生在这里最终写下的是什么。输出 JSON（不要围栏、不要解释）：
{"answer": "...", "conf": "high|medium|low"}

认不出就写 `"answer": "unreadable"`，空着就写 `"blank"`。
**认不出比猜错好** —— 这个结果会拿去判学生对错。
"""


def decide(row, ref_answer, ref_src):
    """
    判一题。回 `(verdict, verdict_by, why)`；`verdict=None` 表示代码档判不了，
    要升级到模型档。

    四个值的边界不许有第五种解释：
      blank   学生没写          —— 卷子最后几道空白多半是时间不够而不是不会
      unsure  系统没能力判      —— 把它混进「错」等于拿系统的无能当学生的薄弱点
      right/wrong  真的判出来了
    """
    if row.get("blank"):
        return ("blank", "code", "这道题没有作答")
    if not row.get("in_paper", True):
        return ("unsure", "code", "答题卡上的第 %s 题在这份卷子里不存在，挂不上" % row["n"])
    if row.get("unreadable"):
        return ("unsure", "code", "作答认不出来，不猜")
    if ref_src == "none" or not ref_answer:
        return ("unsure", "code",
                "这份卷子里没有这道题的标准答案 —— 是卷子没给，不是学生的问题")
    v, why = grade.judge(row.get("raw_text"), ref_answer)
    return (v, "code", why) if v else (None, None, why)


def needs_reread(row):
    """
    要不要裁块复读一次。

    代价不对称：判对了没人受损；**判错了会凭空造出一个假的薄弱知识点**，
    而薄弱知识点是这个功能唯一的产出。错题通常是少数，复读很便宜。

    只跑一次 —— 复读后仍认不出就维持 unsure。读不出来是事实，说出来比
    反复烧钱强。
    """
    if row.get("reread"):
        return False
    if row.get("verdict") == "blank":
        return False                      # 复读一次还是空白，纯烧钱
    return (row.get("verdict") == "wrong"
            or row.get("unreadable")
            or row.get("verdict") == "unsure" and not row.get("in_paper", True)
            or not row.get("in_paper", True)
            or row.get("read_conf") == "low")
```

`grade_sheet(sheet_id, paper_name)` 的流程（逐条实现，每条都在上面的纯函数里判完）：

1. 读 `store.sheet_answers(sheet_id)` 与 `store.get_paper(paper_name)` 的 `ref_answer` / `ref_answer_src`
2. 对每题调 `decide`。回 `None` 的走模型档：把标准答案与学生作答一起问一次「**这两个是不是同一个答案**」（不问对错），`verdict_by='model'`
3. 写回 `store.put_sheet_answer(...)`
4. 对 `needs_reread` 为真的题：用 `crop_rel` 对应的 hires 切片调 `mathvlm.ask_raw(..., REREAD_PROMPT)`，把 `reread_raw` 写回，**两次结果都留着**，重新 `decide` 一次，`reread=True`
5. 返回 `{"right": n, "wrong": n, "blank": n, "unsure": n, "reread": n}`

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_sheet_grade.py -v`
Expected: `13 passed`

- [ ] **Step 5: 端到端判一次**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'pipeline'); import sheet
print(sheet.grade_sheet(<sheet_id>, '2025年高考北京卷物理真题'))"
```

Expected: 因为北京卷没有标准答案（`ref_answer_src='none'`），**应该全部是 `unsure`**，且 `why` 里写着「是卷子没给，不是学生的问题」。这本身就是一条验证：**没有标准答案时系统不许判任何人错。**

- [ ] **Step 6: 提交**

```bash
git add pipeline/sheet.py tests/test_sheet_grade.py
git commit -m "feat: 加 Ⓒ 判对错与判错复读

四个 verdict 的边界写死在纯函数 decide 里，测得厚：空白不是错、
认不出不是错、卷子没答案不是学生的问题、题号挂不上也不是。

判错的一律复读一次。代价不对称：判对了没人受损，判错了会凭空造出
一个假的薄弱知识点，而那是这个功能唯一的产出。空白的不复读 ——
复读一次还是空白，纯烧钱。

北京卷实跑：没有标准答案，全部 unsure，一个人都没判错。"
```

---

### Task 7: `/api/diagnose` 上传入口

**Files:**
- Modify: `pipeline/api.py`
- Create: `tests/test_diagnose_gate.py`

**Interfaces:**
- Produces:
  - `POST /api/diagnose` — multipart：`paper[]`（可空，见下）、`answer[]`（可选）、`sheet[]`（必填）、`student`、`paper_name`（用已有卷子时给）
  - 返回 `{job, paper, sheet}`；撞名回 **409 带已有卷子的摘要**

- [ ] **Step 1: 写失败的测试（只测纯判据）**

`tests/test_diagnose_gate.py`：

```python
# -*- coding: utf-8 -*-
import api
import pytest


def test_只收pdf和图片():
    assert api.sheet_kind("a.jpg") == "image"
    assert api.sheet_kind("a.JPEG") == "image"
    assert api.sheet_kind("a.png") == "image"
    assert api.sheet_kind("a.pdf") == "pdf"
    assert api.sheet_kind("a.docx") is None
    assert api.sheet_kind("a") is None


def test_本期题目侧只收pdf():
    """图片试卷是第四期。上传界面上那一格先明写「暂只支持 PDF」，
    不做成一个点了没反应的入口"""
    ok, why = api.check_paper_files(["a.pdf"])
    assert ok
    ok, why = api.check_paper_files(["a.jpg", "b.jpg"])
    assert not ok and "第四期" in why


def test_答题卡必须有():
    ok, why = api.check_sheet_files([])
    assert not ok and "答题卡" in why


def test_答题卡可以多张():
    ok, _ = api.check_sheet_files(["1.jpg", "2.jpg", "3.jpg"])
    assert ok
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_diagnose_gate.py -v`
Expected: FAIL，`AttributeError: module 'api' has no attribute 'sheet_kind'`

- [ ] **Step 3: 实现判据与端点**

在 `pipeline/api.py` 里加：

```python
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic")


def sheet_kind(fn):
    """按扩展名分类。认不出回 None —— 当场 400，不进管线再失败。"""
    f = (fn or "").lower()
    if f.endswith(".pdf"):
        return "pdf"
    return "image" if f.endswith(IMG_EXT) else None


def check_paper_files(names):
    """题目侧本期只收 PDF。图片试卷是第四期的事。"""
    if not names:
        return (True, "")            # 空表示用已有的卷子
    kinds = {sheet_kind(n) for n in names}
    if None in kinds:
        return (False, "题目文件里有不认识的格式，只收 PDF 和图片")
    if kinds != {"pdf"} or len(names) != 1:
        return (False, "本期题目侧只支持一份 PDF；拍照传卷子在第四期")
    return (True, "")


def check_sheet_files(names):
    if not names:
        return (False, "没有答题卡文件。至少要传一张")
    if any(sheet_kind(n) is None for n in names):
        return (False, "答题卡里有不认识的格式，只收 PDF 和图片")
    return (True, "")
```

端点 `POST /api/diagnose` 的三条闸：

1. 文件格式不对 → **400**，当场拒，把上面那句 `why` 原样回给前端
2. 传了新卷子但卷名已存在 → **409**，`detail` 里带**已有卷子的摘要**（哪天传的、多少题），前端据此给两个出口：「用已有的这份」（改传 `paper_name`，跳过试卷段）和「这是另一份卷子」（后端 `store.free_name` 加后缀另建）
3. 同卷同学生已经在跑 → **409**，复用 `CLAIMS` 那道闸

后台任务两段：**试卷段**（给了 `paper[]` 才跑：现有 `run_pipeline` 那一串）→ **答题卡段**（`store.create_sheet` → `sheet.read_sheet` → `sheet.grade_sheet`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_diagnose_gate.py -v`
Expected: `4 passed`

- [ ] **Step 5: 用 curl 走一遍三条闸**

```bash
# 需要一个会话 cookie，见 Task 9 Step 6 的做法
curl -s -X POST localhost:8712/api/diagnose -b "ee_session=$TOK" \
  -F "sheet=@bad.docx"                     # 期望 400
curl -s -X POST localhost:8712/api/diagnose -b "ee_session=$TOK" \
  -F "paper=@已存在的卷子.pdf" -F "sheet=@s.jpg"   # 期望 409，detail 里带摘要
```

- [ ] **Step 6: 提交**

```bash
git add pipeline/api.py tests/test_diagnose_gate.py
git commit -m "feat: 加 /api/diagnose 一次传完的入口

撞名不自动复用：老师传第二个学生时卷名必然撞，那道 409 会把他挡在
门外什么也做不了；但反过来自动认成同一份卷子也不行 —— 两份不同的
卷子重名，会静默拿错答案去判一个学生。所以 409 带上已有卷子的摘要，
让老师选。

题目侧本期只收 PDF，图片试卷是第四期。上传界面上那一格明写出来，
不做成一个点了没反应的入口。"
```

---

### Task 8: 改判端点

**Files:**
- Modify: `pipeline/api.py`
- Modify: `web/src/api.ts`

**Interfaces:**
- Produces:
  - `GET /api/papers/{name}/sheets` → `[{id, student, answers, wrong, createdAt, updatedAt}]`
  - `GET /api/sheets/{sid}` → `{paper, student, answers: [...]}`，每题带 `finalVerdict` / `verdict` / `verdictBy` / `teacherVerdict` / `cropUrl` / `refAnswer`
  - `POST /api/sheets/{sid}/answers/{n}/verdict` body `{verdict: string | null}` → 改判 / 撤回

- [ ] **Step 1: 加三个端点**

三条要点：

- **归属检查照 `mine()` 那套**：答题卡挂在卷子上，卷子不是你的就 404。不存在和不是你的给同一个回答。
- **`finalVerdict` 只从 `store.sheet_answers` 拿**，API 层不再算一次 COALESCE。
- **改判只接受五个值**（四个 verdict + `null` 撤回），别的 400。

- [ ] **Step 2: 前端接口**

`web/src/api.ts` 末尾加：

```ts
export const listSheets = (paper: string) =>
  fetch(`/api/papers/${encodeURIComponent(paper)}/sheets`, CRED).then(j<SheetBrief[]>)

export const getSheet = (sid: number) =>
  fetch(`/api/sheets/${sid}`, CRED).then(j<Sheet>)

/** verdict 传 null 表示撤回改判，退回系统原判 */
export const setVerdict = (sid: number, n: number, verdict: string | null) =>
  post(`/api/sheets/${sid}/answers/${n}/verdict`, { verdict }).then(j<{ ok: boolean }>)

export function uploadDiagnose(f: {
  paper?: File; answer?: File[]; sheet: File[]; student?: string; paperName?: string
}) {
  const fd = new FormData()
  if (f.paper) fd.append('paper', f.paper)
  f.answer?.forEach((x) => fd.append('answer', x))
  f.sheet.forEach((x) => fd.append('sheet', x))
  if (f.student) fd.append('student', f.student)
  if (f.paperName) fd.append('paper_name', f.paperName)
  return fetch('/api/diagnose', { ...CRED, method: 'POST', body: fd })
    .then(j<{ job: string; paper: string; sheet: number }>)
}
```

- [ ] **Step 3: 手工验一遍改判与撤回**

```bash
curl -s -X POST localhost:8712/api/sheets/1/answers/1/verdict \
  -b "ee_session=$TOK" -H 'Content-Type: application/json' -d '{"verdict":"right"}'
# 再查一次，确认 verdict 仍是原判、teacherVerdict 是 right、finalVerdict 是 right
curl -s -X POST localhost:8712/api/sheets/1/answers/1/verdict \
  -b "ee_session=$TOK" -H 'Content-Type: application/json' -d '{"verdict":null}'
# 确认 finalVerdict 退回系统原判
```

- [ ] **Step 4: 提交**

```bash
git add pipeline/api.py web/src/api.ts
git commit -m "feat: 答题卡列表、详情与改判端点

finalVerdict 只从 store.sheet_answers 拿，API 层不再算第二次 COALESCE ——
两份算法迟早会漂，漂的后果是「老师改了判，某个地方还显示旧结果」。"
```

---

### Task 9: 页面

**Files:**
- Create: `web/src/components/SheetPanel.tsx`
- Modify: `web/src/components/PaperView.tsx`
- Modify: `web/src/types.ts`
- Modify: `web/src/styles.css`

四条硬约束（**任何一条没做到，这个任务就不算完成**）：

- **原图切片必须挨着判定，不能藏进二级页面。** 老师一眼能校对是这个功能唯一的红绿灯，藏一层等于没有。
- **`verdictBy` 要显示**（代码判定 / 推断判定 / 老师改判）。
- **`blank` 和 `unsure` 要分开显示**，不能都画成灰的。前者是学生没写，后者是系统没能力判。
- **判错默认展开，判对默认折叠。** 老师要看的是错题。

版面：

```
张三 · 2025年高考北京卷物理真题                    [重新阅卷]

逐题  1 ✓  2 ✓  3 ✗  4 ✓  5 —  6 ✗  7 ？ …
      ┌──────────┐  认出的作答：B
      │ 原图切片  │  卷子上的答案：C
      │（学生手写）│  判定：错 · 代码判定 · 复读后改判
      └──────────┘  [改判为对]

有 3 道题空白，未计入（第14、15、16题）
有 2 道题判不了（卷子里没有标准答案）
判定由 AI 生成，未经人工审核 —— 逐题原图就在上面，请对照
```

- [ ] **Step 1: 写 `SheetPanel.tsx`**（组件代码按上面的版面实现；类型从 Task 8 的接口来）
- [ ] **Step 2: 挂进 `PaperView`**（试卷页底部一块「学生答题卡」）
- [ ] **Step 3: `npx tsc --noEmit` 通过**
- [ ] **Step 4: `npm run build`**
- [ ] **Step 5: 重启后端**

```bash
kill $(pgrep -f "uvicorn pipeline.api:app") ; sleep 2
cd /Users/jerry/Desktop/product/exam-explainer && \
  .venv/bin/uvicorn pipeline.api:app --host 127.0.0.1 --port 8712 >> logs/api.log 2>&1 &
```

- [ ] **Step 6: 无头验一遍页面真的渲出来了**

`index.html` 已经是 `no-cache`（期一那个修复），所以不会再撞缓存。但**渲染仍要验**：

```bash
TOK=$(.venv/bin/python -c "
import sys, secrets; sys.path.insert(0,'pipeline')
import api, store
_, o = store.paper_owner('2025年高考北京卷物理真题')
t = secrets.token_urlsafe(32); store.create_session(o, api.token_hash(t), days=1); print(t)")
cat > web/dist/_probe.html <<EOF
<!doctype html><meta charset=utf-8><script>
document.cookie="ee_session=$TOK; path=/";
location.replace("/#/p/"+encodeURIComponent("2025年高考北京卷物理真题"));
</script>
EOF
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --virtual-time-budget=20000 \
  --dump-dom "http://localhost:8712/_probe.html" 2>/dev/null | grep -c "学生答题卡"
rm web/dist/_probe.html
```

Expected: `1` 或更多。跑完把那个临时会话注销掉。

- [ ] **Step 7: 请老师肉眼看一眼**

**这一步不能省。** 版面挤不挤、原图切片看不看得清、改判按钮好不好点，只有人能判。

- [ ] **Step 8: 提交**

---

### Task 10: 进度与失败

**Files:**
- Modify: `pipeline/api.py`
- Modify: `pipeline/store.py`

- [ ] **Step 1: 答题卡链的四步进度**

照 `stage_of` 那套**从库里反推**，不加 `state` 列：有没有页面图 → 有没有 `sheet_answers` → 有没有 `verdict` → （期三才有）有没有 `diagnoses`。

- [ ] **Step 2: 失败按规格那张表处理**

| 情况 | 处理 |
|---|---|
| 传的不是 PDF/图片 | 400，当场拒（Task 7 已做） |
| 整页读回来一道题都没有 | **失败**，提示重拍（Task 5 已做） |
| 卷子 16 题只认出 9 题 | **不失败**，警告「有 7 道题没在答题卡上找到」并列出题号 |
| 认出的题号卷子里没有 | **不失败**，`question_id` 留空，单独列出来 |
| 没有标准答案 | 该题 `unsure`，写明是卷子没给 |

- [ ] **Step 3: 改判后标记诊断过期**

`answer_sheets.updated_at` 已经在改判时 touch 了（Task 3）。期三的诊断拿它跟 `diagnoses.created_at` 比。**本期只需保证这一列是准的**，页面上暂不显示。

- [ ] **Step 4: 全量测试 + 提交**

---

## 自检

**规格覆盖**

| 规格条目 | 落在哪 |
|---|---|
| Ⓐ 摄入：EXIF 转正、文件名排序、双分辨率、内容哈希 | Task 2 |
| Ⓑ 整页读、认输出口、题号必须真实认出、当场裁块 | Task 5 |
| Ⓒ 四个 verdict、代码档三种、模型档只问等价、判错复读 | Task 4, 6 |
| 不引 sympy | Task 4（`grade.py` 模块文档 + 测试） |
| `answer_sheets` / `sheet_answers`、改判单独一列 | Task 3 |
| 一次传完、撞名 409 带摘要 | Task 7 |
| 页面四条硬约束 | Task 9 |
| 失败处理表 | Task 10 |

**本期有意不做**：`diagnoses` 与薄弱知识点（期三）、图片试卷（期四）、答案文件单独上传的抽取（`ref_answer_src='answer_file'` 这个值在期一就留好了，Task 7 只把文件收下来，抽取逻辑等期四的 `imgdoc` 一起做）。

**三个会踩的坑，计划里都盯住了**

1. `put_asset` 的现有签名可能跟 Task 5 里的调用对不上 —— 计划里明写了「先读一遍再接」。
2. 复读用的是 hires 切片，而 `box` 是模型在 web 档上给的，**坐标要乘 `1/WEB_SCALE`**（Task 5 的 `_crop_box`）。
3. 从 `mathvlm` 抽 `ask_raw` 会动到一个已经在跑的模块 —— Task 5 Step 4 专门跑一遍北京卷确认没跑坏。

**一个悬着的事**：Task 1 的手写探针没有真实样本就开不了工，而它挡着 Task 5 之后的全部内容。Task 2/3/4 可以先做。

## 探针结论

（Task 1 跑完后填这里）
