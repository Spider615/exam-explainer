# 答题卡步二实施计划：Ⓢ 抠图 → Ⓑ 读批改 → Ⓒ 判定 → 上传与改判

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 老师把已批改的答题卡传进「答题卡诊断」模式，页面上出现逐题「学生写了什么 ·
老师给了几分 · 对/半对/错」，每一题挨着原图切片，互校不一致的地方显式标出来。

**Architecture:** 四步纯管线，接在已有的「参考答案侧」后面，**不碰**参考答案那条链。
Ⓢ 是纯几何（不调模型），Ⓑ 是重叠横条 + 视觉模型，Ⓒ 是纯函数（不调模型），
落库走已经建好的 `answer_sheets` / `sheet_answers` 两张表。

**Tech Stack:** Python 3.14 / FastAPI / psycopg3 / Postgres / Pillow + numpy /
pytest；前端 React 18 + TypeScript + Vite（**本轮不引入前端测试框架**）。

**设计文档：** `docs/superpowers/specs/2026-08-06-answer-sheet-diagnosis-design.md`
（2026-08-10 按探针结论改过 —— Ⓢ/Ⓑ/Ⓒ/Ⓓ 四节和文末「探针结论（2026-08-10）」
是本计划的事实依据，数字都在那里）

## Global Constraints

- **失败必须看得见。** 静默地给出一个看着像对的错结果，比明着失败糟得多。
  每一步「读不出来」都要有一个页面上说得出口的表达，不许留白、不许塞占位。
- **一任务一 commit。** 测试先行：先写会失败的测试，跑一遍确认它失败，再实现。
- **不许 `git add web/dist/`**（在 `.gitignore` 里），不许提交 `.env`、`work/`。
- **真库只读一律 `EXAM_READONLY=1`**，任何探查都不许改数据。
- **分数一律 `numeric`，不许 `int`。** 实测有 `7.5分(满分12分)`、总分 `58.5`，
  存整数会静默截断，而丢分率是拿它算的。
- **`verdict` 五个值**：`right` / `partial` / `wrong` / `blank` / `unsure`。
  `partial` 是本轮新增的。
- **`verdict_by` 五个值**：`teacher_score`（照卷子上印的分数判，优先）/
  `teacher_mark`（照红勾红叉判）/ `code`（`grade.judge`）/ `model` / `teacher`（老师改判）。
- **学生的作答不可再生。** `sheet_answers` 以 `ON DELETE CASCADE` 挂在 `questions` 上，
  `questions` 挂在 `papers` 上。任何删除路径都要先问「这会不会带走学生的作答」。
- **模型调用一律走 `mathvlm.ask_raw`**，不要新写一份 HTTP 调用。
- **裁小块可以放大，整页不许放大。** 整页放大 2× 实测会把「读不出来」变成「编一个」
  （选择题 1-4 全答 A，真值 D C C B）。

## 本期不做

- **Ⓓ 诊断报告**（薄弱知识点 + 提升建议）—— 那是步三，另出计划。
  本期交付「逐题对错 + 原图对照 + 互校告警 + 改判」，**不依赖诊断也成立**。
- 班级、学生账号、跨学生比较、排名。
- 读手写推导过程（只认每题的最终作答）。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `pipeline/sheetcut.py` **新建** | Ⓢ：手机截图 → 答题卡页图。纯几何，不调模型 |
| `pipeline/sheetread.py` **新建** | Ⓑ：页图 → 逐题 `{n, answer, mark, got, full, red}`。切条、调模型、合并 |
| `pipeline/verdict.py` **新建** | Ⓒ：纯函数。由分数/符号推 `verdict`，与 `grade.judge` 互校 |
| `pipeline/schema.sql` 改 | 5 个新列 + 回填 |
| `pipeline/store.py` 改 | `_SHEET_COLS` / `_VERDICTS` 加值；总分读写；按卷名列答题卡 |
| `pipeline/api.py` 改 | 上传入口、读取端点、改判端点、`run_sheet_pipeline` |
| `web/src/components/SheetDetail.tsx` **新建** | 一份答题卡的详情页 |
| `web/src/components/SheetUpload.tsx` 改 | 多一个「传已批改答题卡」的入口 |
| `web/src/components/SheetView.tsx` 改 | 卷子详情页上列出它的答题卡 |
| `web/src/{api,types}.ts` 改 | 新端点与新类型 |

**为什么 Ⓒ 单独一个文件**：它是纯函数、没有 IO、判据密集，是这条链上唯一能被
测厚的一段。混进 `sheetread.py` 会被模型调用的桩淹掉。

---

## Task 1: `sheetcut.py` —— 从手机截图里抠出答题卡（Ⓢ）

**Files:**
- Create: `pipeline/sheetcut.py`
- Test: `tests/test_sheetcut.py`

**Interfaces:**
- Consumes: `pages.normalize`（已有）
- Produces:
  - `bright_band(im) -> (top, bottom) | None`
  - `band_contrast(im, band) -> float`　带内平均亮度 − 带外平均亮度
  - `needs_cut(im) -> (bool, why)`　要不要裁，以及为什么
  - `split_pages(im, band) -> int`　两页之间那道缝的 x
  - `cut(files, outdir, verbose=True) -> [页图路径]`

**这一步一次模型都不调。** 不调的理由不是省钱，是失败要看得见：几何框可以当场
用宽高比和亮度检查，模型给的框错了没有判据。

- [ ] **Step 1: 写会失败的测试**

```python
# -*- coding: utf-8 -*-
"""Ⓢ 抠答题卡：判据是「亮度差 ≥ 60 且 带高 < 60%」的合取，两条缺一不可。

这两条不是拍脑袋来的，是 10 张真实材料实测出来的（见设计文档 Ⓢ 那节的表）：
手机截图亮度差 187/189、带高 32%；整页扫描亮度差 0.3~5.0；已裁干净的答题卡
亮度差 1.0~8.2。唯一一张亮度差 222 的整页扫描是被顶上一条黑边骗的，
它的带高占了 99%，被第二条挡下。

**只看带高会错**：已裁干净的答题卡右半页大片空白，最亮带只占 48%。
这是设计的第一版判据，被材料当场证伪 —— 下面 test_干净的答题卡不许再裁 守的就是它。
"""
import numpy as np
from PIL import Image

import sheetcut


def _img(rows):
    """rows 是每一行的灰度值，造一张 200 宽的图"""
    a = np.repeat(np.array(rows, dtype=np.uint8)[:, None], 200, axis=1)
    return Image.fromarray(a, mode="L").convert("RGB")


def test_截图里的亮带找得出来():
    im = _img([30] * 100 + [250] * 300 + [30] * 100)
    assert sheetcut.bright_band(im) == (100, 400)


def test_亮带的亮度差算得对():
    im = _img([30] * 100 + [250] * 300 + [30] * 100)
    band = sheetcut.bright_band(im)
    assert sheetcut.band_contrast(im, band) == 220.0


def test_手机截图要裁():
    im = _img([30] * 100 + [250] * 150 + [30] * 250)   # 差 220，带高 30%
    ok, why = sheetcut.needs_cut(im)
    assert ok, why


def test_整页扫描不裁():
    """整页都是白纸，亮度差接近 0"""
    im = _img([248] * 200 + [250] * 300)
    ok, why = sheetcut.needs_cut(im)
    assert not ok
    assert "亮度差" in why


def test_干净的答题卡不许再裁():
    """
    **这条守的是被证伪的那一版判据。** 一张已经裁干净的答题卡，页内亮度不均匀
    （右半页空白、左半页写满），最亮带只占 48% —— 按「带高 < 60% 就裁」会把
    干净的卷子再切一刀。它的亮度差很小，第一条挡得住。
    """
    im = _img([246] * 260 + [251] * 240)               # 差 5，带高 48%
    ok, why = sheetcut.needs_cut(im)
    assert not ok, why


def test_黑边骗不过带高那条():
    """
    整页扫描顶上一条黑边就能造出 200+ 的亮度差。但它的亮带占了全图 99%，
    第二条判据挡下来。真实材料 20260807-234423.jpeg 就是这样。
    """
    im = _img([25] * 12 + [248] * 1428)                # 差 223，带高 99%
    ok, why = sheetcut.needs_cut(im)
    assert not ok
    assert "亮带占了 99%" in why


def test_亮带太扁就是没找到():
    im = _img([30] * 480 + [250] * 20)                 # 带高 4%
    ok, why = sheetcut.needs_cut(im)
    assert not ok
    assert "没在这张图里找到答题卡" in why


def test_两页之间的缝找得出来():
    """两页并排，中间一道暗缝"""
    a = np.full((300, 400), 250, dtype=np.uint8)
    a[:, 198:202] = 40
    im = Image.fromarray(a, mode="L").convert("RGB")
    assert abs(sheetcut.split_pages(im, (0, 300)) - 200) <= 3
```

- [ ] **Step 2: 跑一遍确认它失败**

```
cd /Users/jerry/Desktop/product/exam-explainer
.venv/bin/python -m pytest tests/test_sheetcut.py -q
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'sheetcut'`

- [ ] **Step 3: 实现 `pipeline/sheetcut.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sheetcut.py —— Ⓢ：从手机截图里抠出答题卡

    python pipeline/sheetcut.py <卷名> <图1> [图2 ...] --out work/<卷名>/sheet

材料是某考试报告 app 的截图：顶上状态栏和标题栏、底下「我的错题」按钮，
答题卡本身只占中间一条**亮带**，其余部分被 app 压暗了。

**这一步一次模型都不调。** 不是为了省钱 —— 是因为这一步的失败必须看得见：
几何切出来的框可以当场用亮度和宽高比检查，模型给的框错了没有判据。

判据（10 张真实材料实测，见设计文档 Ⓢ 那节）
--------------------------------------------
    要裁 ⟺ 亮度差 ≥ 60  且  带高 < 整图的 60%

两条缺一不可：只看带高，会把一张已经裁干净、页内亮度不均匀（右半页空白）的
答题卡再切一刀（实测那张最亮带只占 48%）；只看亮度差，整页扫描顶上一条黑边
就能造出 222 的差（实测 20260807-234423.jpeg）。
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pages

# 判据的两个阈值。改这两个数之前先看 tests/test_sheetcut.py 里那两条
# 「不许再裁」的测试 —— 它们记着这两条各自单独用会怎么错
MIN_CONTRAST = 60.0     # 带内比带外亮多少才算「这是被压暗的截图」
MAX_BAND_FRAC = 0.60    # 亮带占整图多少以上就当「本来就是整页」
MIN_BAND_FRAC = 0.10    # 亮带比这还扁就是根本没找到


def bright_band(im):
    """按行平均亮度找最长的连续亮段，回 (top, bottom)，找不到回 None。"""
    g = np.asarray(im.convert("L"), dtype=np.float32)
    rows = g.mean(axis=1)
    thr = (rows.max() + rows.min()) / 2
    best = cur = None
    for y, on in enumerate(rows > thr):
        if on:
            cur = (cur[0], y + 1) if cur else (y, y + 1)
            if not best or cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        else:
            cur = None
    return best


def band_contrast(im, band):
    """带内平均亮度 − 带外平均亮度。带外为空时回 0（整张都是带）。"""
    g = np.asarray(im.convert("L"), dtype=np.float32)
    rows = g.mean(axis=1)
    top, bot = band
    mask = np.ones(len(rows), bool)
    mask[top:bot] = False
    if not mask.any():
        return 0.0
    return float(rows[top:bot].mean() - rows[mask].mean())


def needs_cut(im):
    """要不要裁，以及为什么。回 (bool, 一句人话)。"""
    band = bright_band(im)
    if not band:
        return False, "没在这张图里找到答题卡 —— 整张亮度没有起伏"
    frac = (band[1] - band[0]) / im.height
    if frac < MIN_BAND_FRAC:
        return False, ("没在这张图里找到答题卡 —— 最亮的一条只占 %.0f%%，太扁了"
                       % (frac * 100))
    c = band_contrast(im, band)
    if c < MIN_CONTRAST:
        return False, ("整张都是答题卡，不裁 —— 带内外亮度差只有 %.1f，"
                       "说明没有被压暗的边框" % c)
    if frac >= MAX_BAND_FRAC:
        return False, ("整张都是答题卡，不裁 —— 亮带占了 %.0f%%，"
                       "那条亮度差多半来自边上一条黑边" % (frac * 100))
    return True, "手机截图，裁中间那条（亮度差 %.1f，占 %.0f%%）" % (c, frac * 100)


def split_pages(im, band):
    """两页并排时，中间那道暗缝的 x。在左右中点附近 ±1/6 宽里找最暗的一列。"""
    top, bot = band
    g = np.asarray(im.convert("L"), dtype=np.float32)[top:bot]
    cols = g.mean(axis=0)
    mid, w = len(cols) // 2, len(cols) // 6
    lo = max(0, mid - w)
    return lo + int(np.argmin(cols[lo:mid + w]))


def cut(files, outdir, verbose=True):
    """
    一批原始图 → 一批答题卡页图（每页一个文件），返回路径列表。

    不裁的图**原样进结果**，不是丢掉 —— 老师可能本来就传的是裁好的照片。
    """
    log = (lambda s: print(s, flush=True)) if verbose else (lambda *a, **k: None)
    os.makedirs(outdir, exist_ok=True)
    out = []
    for f in files:
        im = Image.open(f)
        ok, why = needs_cut(im)
        log("── %s：%s" % (os.path.basename(f), why))
        if not ok:
            if "没在这张图里找到答题卡" in why:
                raise ValueError("%s：%s" % (os.path.basename(f), why))
            dst = os.path.join(outdir, "s%02d.png" % len(out))
            im.convert("RGB").save(dst)
            out.append(dst)
            continue
        band = bright_band(im)
        strip = im.crop((0, band[0], im.width, band[1]))
        x = split_pages(im, band)
        for left, right in ((0, x), (x, strip.width)):
            dst = os.path.join(outdir, "s%02d.png" % len(out))
            strip.crop((left, 0, right, strip.height)).convert("RGB").save(dst)
            out.append(dst)
        log("   切成两页（缝在 x=%d）" % x)
    log("── Ⓢ 共得到 %d 页答题卡" % len(out))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cut(a.files, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

```
.venv/bin/python -m pytest tests/test_sheetcut.py -q
```
Expected: 8 passed

- [ ] **Step 5: 拿真材料跑一遍（不进测试，人工看一眼）**

```
.venv/bin/python pipeline/sheetcut.py 探针 \
  ~/Desktop/试卷+答题卡/20260807-2343{47,08}.jpeg \
  ~/Desktop/试卷+答题卡/20260807-2344{14,17,20,23}.jpeg \
  --out /tmp/sheetcut-check
```
Expected: 两张截图各切成 2 页（缝在 x≈540），4 张参考答案各「整张都是答题卡，不裁」，
共 8 个文件。**打开 `/tmp/sheetcut-check/s00.png` 看一眼**，应该是答题卡第 1 页
（左上角 58.5、选择题填涂区、9–13 题），上下没有状态栏和按钮。

- [ ] **Step 6: 提交**

```bash
git add pipeline/sheetcut.py tests/test_sheetcut.py
git commit -m "feat: Ⓢ 从手机截图里抠出答题卡——纯几何，两条判据合取"
```

---

（Task 2 起在下一节，等对抗性检查的结论落定后补齐）
