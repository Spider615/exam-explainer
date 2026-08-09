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
  - `needs_cut(im) -> (bool, why)`　要不要**裁掉 app 边框**，以及为什么
  - `seam_x(im, band) -> (x, why) | (None, why)`　两页中缝在哪；找不到回 None
  - `cut(files, outdir, verbose=True) -> [{"path", "src", "crop_mode", "why",
    "band", "band_frac", "contrast", "seam"}]`

**这一步一次模型都不调。** 不调的理由不是省钱，是失败要看得见：几何框可以当场
用宽高比和亮度检查，模型给的框错了没有判据。

**两条判据必须拆开，不许耦合。**「要不要裁掉 app 边框」和「要不要劈成左右两页」
是两件独立的事：一张**已经裁干净的双页答题卡**不需要裁边框，但**仍然要劈成两页**。
把劈页写在裁剪那条分支里，这种图会被当成单页整张送进 Ⓑ —— 而两页一起喂正是探针
里最差的一档（整个选择题区漏掉）。所以 `seam_x` 无条件跑，判据是「中缝那一列显著
暗于两侧、且位置在中点附近」，和这张图是不是截图无关。

**每张图走了哪条分支要当一等数据带出去**（`crop_mode` ∈ `cropped` /
`whole_page` / `failed`，连同亮带区间、占比、亮度差、中缝位置）。后面要落库，
页面在逐题原图上方据此明说「这张是按整页读的，没找到答题卡边界」——
不说的话，「切歪了」和「本来就长这样」在页面上完全同形。

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
    x, _ = sheetcut.seam_x(im, (0, 300))
    assert abs(x - 200) <= 3


def test_没有中缝就不劈():
    """单页答题卡：整张均匀，中点附近没有显著暗列"""
    a = np.full((300, 400), 250, dtype=np.uint8)
    im = Image.fromarray(a, mode="L").convert("RGB")
    x, why = sheetcut.seam_x(im, (0, 300))
    assert x is None
    assert "中缝" in why


def test_干净的双页答题卡不裁边框但仍要劈成两页():
    """
    **两条判据必须独立。** 这张图不需要裁 app 边框（亮度差很小），
    但它确确实实是两页并排 —— 把劈页写进裁剪那条分支的话，它会被当成单页
    整张送进 Ⓑ，而两页一起喂正是探针里最差的一档（整个选择题区漏掉）。
    """
    a = np.full((300, 400), 249, dtype=np.uint8)
    a[:, 198:202] = 40
    im = Image.fromarray(a, mode="L").convert("RGB")
    ok, _ = sheetcut.needs_cut(im)
    assert not ok, "这张不该被判成手机截图"
    x, _ = sheetcut.seam_x(im, sheetcut.bright_band(im))
    assert x is not None, "不裁边框的图也要能找出中缝"
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
    """
    按行平均亮度找最长的连续亮段，回 `(top, bottom)`。

    **整张亮度没有起伏时回整张**（`(0, 高)`），不回 None。一张裁得干净、
    通篇白纸的答题卡就是这样：`max == min`，阈值法一行都选不出来。回 None 的话
    调用方会把它当成「没找到答题卡」而拒收 —— 那正好把最规矩的输入判成了坏输入。
    整张当一条带是对的：后面 `band_contrast` 会算出 0，`needs_cut` 据此说
    「整张都是答题卡，不裁」，一路都自洽。
    """
    g = np.asarray(im.convert("L"), dtype=np.float32)
    rows = g.mean(axis=1)
    if rows.max() - rows.min() < 1.0:
        return (0, len(rows))
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
    """要不要**裁掉 app 边框**，以及为什么。回 (bool, 一句人话)。

    只回答裁边框这一件事。**劈不劈成两页是另一条判据**（`seam_x`），
    两者独立 —— 见 `seam_x` 的说明。
    """
    band = bright_band(im)
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


SEAM_DROP = 40.0        # 中缝那一列要比两侧暗多少才算一道缝


def seam_x(im, band):
    """
    两页并排时中缝的 x，回 `(x, 一句人话)`；找不到回 `(None, 为什么)`。

    **和「要不要裁边框」无关，无条件跑。** 一张已经裁干净的双页答题卡不需要裁
    边框，但仍然要劈成两页 —— 把劈页写进裁剪那条分支的话，这种图会被当成单页
    整张送进 Ⓑ，而两页一起喂是探针里最差的一档（整个选择题区漏掉）。

    判据是「中点附近有一列显著暗于两侧」，单页答题卡自然找不到，回 None。
    """
    top, bot = band
    g = np.asarray(im.convert("L"), dtype=np.float32)[top:bot]
    cols = g.mean(axis=0)
    mid, w = len(cols) // 2, max(1, len(cols) // 6)
    lo, hi = max(0, mid - w), min(len(cols), mid + w)
    i = lo + int(np.argmin(cols[lo:hi]))
    # 两侧参照取这个窗口里的中位数：直接用全图均值会被大片空白拉高
    ref = float(np.median(cols[lo:hi]))
    drop = ref - float(cols[i])
    if drop < SEAM_DROP:
        return None, "没找到中缝（中点附近最暗的一列只比两侧暗 %.1f），当成单页" % drop
    return i, "中缝在 x=%d（比两侧暗 %.1f）" % (i, drop)


def cut(files, outdir, verbose=True):
    """
    一批原始图 → 一批答题卡页图，返回**逐页的记录**，不只是路径。

    每条记录带着这张图是怎么来的：`crop_mode`（`cropped` 手机截图裁出来的 /
    `whole_page` 整张原样用的）、亮带区间与占比、亮度差、中缝位置。

    **这些要落库、要上页面。** 页面在逐题原图上方据此明说「这张是按整页读的，
    没找到答题卡边界」—— 不说的话，「切歪了」和「本来就长这样」在页面上完全同形，
    而老师对着原图核对是这个功能唯一的红绿灯。

    不裁的图**原样进结果**，不是丢掉 —— 老师可能本来就传的是裁好的照片。
    """
    log = (lambda s: print(s, flush=True)) if verbose else (lambda *a, **k: None)
    os.makedirs(outdir, exist_ok=True)
    out = []

    def emit(img, src, mode, why, band, contrast, seam):
        dst = os.path.join(outdir, "s%02d.png" % len(out))
        img.convert("RGB").save(dst)
        out.append({"path": dst, "src": os.path.basename(src), "crop_mode": mode,
                    "why": why, "band": list(band), "contrast": round(contrast, 1),
                    "band_frac": round((band[1] - band[0]) / img.height, 3)
                    if mode == "whole_page" else None, "seam": seam})

    for f in files:
        im = Image.open(f)
        ok, why = needs_cut(im)
        log("── %s：%s" % (os.path.basename(f), why))
        if not ok and "没在这张图里找到答题卡" in why:
            raise ValueError("%s：%s" % (os.path.basename(f), why))
        band = bright_band(im)
        contrast = band_contrast(im, band)
        # 裁边框（可能不裁）
        page = im.crop((0, band[0], im.width, band[1])) if ok else im
        mode = "cropped" if ok else "whole_page"
        # 劈页：**独立判据，跟裁不裁无关**
        x, seam_why = seam_x(page, (0, page.height))
        log("   %s" % seam_why)
        if x is None:
            emit(page, f, mode, why + "；" + seam_why, (0, page.height), contrast, None)
        else:
            for left, right in ((0, x), (x, page.width)):
                emit(page.crop((left, 0, right, page.height)), f, mode,
                     why + "；" + seam_why, (0, page.height), contrast, x)
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

## Task 2: 数据模型 —— 分数列、`partial`、判据只留一份

**Files:**
- Modify: `pipeline/schema.sql`
- Create: `pipeline/verdicts.py`
- Modify: `pipeline/store.py`
- Test: `tests/test_verdicts.py`、`tests/test_sheet_scores.py`

**Interfaces:**
- Produces：`verdicts.VERDICTS` / `verdicts.VERDICT_BY` / `verdicts.check(v)` /
  `verdicts.check_by(b)`；`store.set_sheet_total(sheet_id, total)`；
  `sheet_answers` 多 6 列。

### 为什么值域要单独一个文件

`verdict` 的取值现在抄在**四处**：`store._VERDICTS`、`schema.sql` 的注释、
`set_teacher_verdict` 的报错文案、`list_sheets` 那句 `='wrong'` 的汇总。
加 `partial` 只改一处的后果是静默的 —— 老师改不出「半对」（白名单挡下来），
而列表里「错 N 道」会把 partial 漏掉。

这正是 `pipeline/modes.py` 那次的同一个病（阶段清单抄了三份，两次事故都是抄漏
一份），治法也一样：**只留一份，别处指过来**。

- [ ] **Step 1: 写会失败的测试**

```python
# -*- coding: utf-8 -*-
"""判定的值域只有一份，而且写入端真的会校验它。

抄四份的代价是静默的：老师改不出「半对」，列表里「错 N 道」漏掉 partial。
"""
import pytest

import store
import verdicts


def test_五个判定值():
    assert verdicts.VERDICTS == ("right", "partial", "wrong", "blank", "unsure")


def test_判定来源五个值():
    assert verdicts.VERDICT_BY == ("teacher_score", "teacher_mark", "code",
                                   "model", "teacher")


def test_不认识的判定当场抛():
    with pytest.raises(ValueError, match="right/partial/wrong/blank/unsure"):
        verdicts.check("parital")


def test_报错文案是拼出来的不是抄的():
    """抄一份文案，加值的时候必然漏改它 —— 那时候报错会说谎"""
    try:
        verdicts.check("xxx")
    except ValueError as e:
        for v in verdicts.VERDICTS:
            assert v in str(e)


def test_写入端认partial(db):
    store.create_answers_paper("值域用卷", None)
    qid = store.put_answer_question("值域用卷", 1203, "AB", None)
    sid = store.create_sheet("值域用卷", "张三", None)
    store.put_sheet_answer(sid, 1203, question_id=qid, raw_text="A",
                           verdict="partial", verdict_by="teacher_score",
                           score_got=1, score_full=2)
    assert store.sheet_answers(sid)[0]["verdict"] == "partial"


def test_写入端挡得住拼错的判定(db):
    store.create_answers_paper("值域用卷2", None)
    sid = store.create_sheet("值域用卷2", "张三", None)
    with pytest.raises(ValueError):
        store.put_sheet_answer(sid, 1, verdict="parital")


def test_老师改得出半对(db):
    store.create_answers_paper("值域用改判卷", None)
    sid = store.create_sheet("值域用改判卷", "张三", None)
    store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="teacher_score")
    store.set_teacher_verdict(sid, 1, "partial")
    assert store.sheet_answers(sid)[0]["final_verdict"] == "partial"


def test_列表里错题数不把半对漏掉(db):
    """
    `list_sheets` 原来数的是 `='wrong'`。加了 partial 之后，一张 8 道半对、
    2 道全错的卡会显示「错 2 道」—— 而它其实有 10 道没拿满分。
    """
    store.create_answers_paper("值域用列表卷", None)
    sid = store.create_sheet("值域用列表卷", "张三", None)
    for n in range(1, 9):
        store.put_sheet_answer(sid, n, verdict="partial", score_got=1, score_full=2)
    for n in (9, 10):
        store.put_sheet_answer(sid, n, verdict="wrong", score_got=0, score_full=2)
    row = store.list_sheets("值域用列表卷")[0]
    assert row["wrong"] == 2
    assert row["partial"] == 8
    assert row["lost"] == 8 * 1 + 2 * 2      # 丢分：8 道各丢 1，2 道各丢 2


def test_分数存得下小数(db):
    """
    实测有 `7.5分(满分12分)`、总分 `58.5`。存整数会**静默**截断成 7 和 58，
    而丢分率是拿它算的。
    """
    store.create_answers_paper("值域用小数卷", None)
    sid = store.create_sheet("值域用小数卷", "张三", None)
    store.put_sheet_answer(sid, 15, verdict="partial", score_got=7.5, score_full=12)
    store.set_sheet_total(sid, 58.5)
    assert float(store.sheet_answers(sid)[0]["score_got"]) == 7.5
    assert float(store.list_sheets("值域用小数卷")[0]["total"]) == 58.5


def test_没判过和没印分数分得开(db):
    """
    `score_got IS NULL` 同时能表示三件事：还没跑过 Ⓑb、跑过但这题没印分数、
    读出来是 0。第三件由 `0` 自己区分，前两件要靠 `scored_at` ——
    和 `questions.kps_at` 是同一个教训（不加这一列，答案卷永远到不了「已完成」）。
    """
    store.create_answers_paper("值域用判过卷", None)
    sid = store.create_sheet("值域用判过卷", "张三", None)
    store.put_sheet_answer(sid, 1, raw_text="A")                    # 还没跑 Ⓑb
    store.put_sheet_answer(sid, 2, raw_text="B", score_got=None, scored=True)
    rows = {r["n"]: r for r in store.sheet_answers(sid)}
    assert rows[1]["scored_at"] is None, "没跑过 Ⓑb"
    assert rows[2]["scored_at"] is not None, "跑过了，只是这题没印分数"
```

- [ ] **Step 2: 跑一遍确认它失败**

```
.venv/bin/python -m pytest tests/test_verdicts.py -q
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'verdicts'`

- [ ] **Step 3: 建 `pipeline/verdicts.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verdicts.py —— 判定的值域，**全项目只有这一份**

`verdict` 的取值原来抄在四处：`store._VERDICTS`、`schema.sql` 的注释、
`set_teacher_verdict` 的报错文案、`list_sheets` 那句 `='wrong'` 的汇总。
加一个值只改一处，后果全是静默的 —— 老师改不出「半对」，而列表里的「错 N 道」
把 partial 漏掉，一张 8 道半对的卡显示「错 2 道」。

和 `modes.py` 是同一个病、同一个治法（阶段清单抄三份，两次事故都是抄漏一份）：
只留一份，别处指过来，报错文案由清单拼出来而不是再抄一遍。
"""

# 判定。**顺序有意义**：从「全对」到「说不清」，页面上按这个顺序排
VERDICTS = ("right", "partial", "wrong", "blank", "unsure")

#: 谁判的。可信度差一个量级，页面必须分得出来
#:   teacher_score  照卷子上印的得分判（优先，最可信）
#:   teacher_mark   照红勾红叉判（读不到得分时退回这条）
#:   code           grade.judge 判的（只用来互校，不当判据）
#:   model          模型判的
#:   teacher        老师在页面上改判的（最终）
VERDICT_BY = ("teacher_score", "teacher_mark", "code", "model", "teacher")

#: 进不进薄弱统计。blank / unsure 分子分母都不进 —— 它们不是「答错了」
COUNTED = ("right", "partial", "wrong")


def check(v):
    """校验一个判定值，不合法当场抛。回它本身，好写成 `x = check(x)`。"""
    if v not in VERDICTS:
        raise ValueError("verdict 只能是 %s，给的是 %r" % ("/".join(VERDICTS), v))
    return v


def check_by(b):
    if b not in VERDICT_BY:
        raise ValueError("verdict_by 只能是 %s，给的是 %r"
                         % ("/".join(VERDICT_BY), b))
    return b


def of_score(got, full):
    """
    由卷子上印的得分推判定。回 `verdict` 或 None（分数不全，推不出来）。

    **这是判定的第一优先级**，排在红勾红叉前面。实测 12(3) 老师打的是红勾、
    给的是 `1分(满分2分)` —— 标准答案 `AB`、学生只写了 `A`，双选题「选对但不全
    得一半」。红勾在这里的意思是「这行判过了」，不是「全对」。
    """
    if got is None or full is None or full <= 0:
        return None
    if got >= full:
        return "right"
    if got <= 0:
        return "wrong"
    return "partial"
```

- [ ] **Step 4: 改 `schema.sql`**

在末尾追加（照仓库惯例：`ADD COLUMN IF NOT EXISTS` + 幂等回填）：

```sql
-- ---------------------------------------------------------------- 步二：分数
-- 卷子上**印着**的分数。系统一分不算，只是把它转写下来（见设计文档「非目标」）。
--
-- **numeric 不是 int**：实测有 `7.5分(满分12分)`、总分 `58.5`。
-- 存整数会静默截断成 7 和 58，而薄弱知识点是按丢分率排的。
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS score_got   numeric;
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS score_full  numeric;
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS mark_raw    text;
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS teacher_red text;

-- Ⓑb **判过这一行**的时间。和 score_got 是两件事：score_got 为空只说明
-- 「这一行没有分数」，说不出到底是「还没跑过 Ⓑb」还是「跑过了，卷子上就没印」。
-- 与 questions.kps_at 完全同构 —— 那一列不加的时候，答案卷永远到不了「已完成」。
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS scored_at   timestamptz;

-- 卷子上印的总分。Ⓑc 单独读，用来对 Σscore_got。
ALTER TABLE answer_sheets ADD COLUMN IF NOT EXISTS total_score numeric;

-- 回填：已经有分数的行，整卡标成判过。
-- 判据是「这份答题卡里有任何一行有分数」——Ⓑb 是整卡跑的，有一行有分就说明
-- 它在这份卡上跑过，同一份里没分的那些也是判过的（卷子上就没印）。
-- 一行分数都没有的卡留空：那种情况分不出「跑过但全没印分」和「压根没跑」，
-- 宁可当成没跑（代价是多跑一次，反过来会把没跑过的说成跑完了）。
UPDATE sheet_answers a SET scored_at = now()
 WHERE a.scored_at IS NULL
   AND EXISTS (SELECT 1 FROM sheet_answers x
                WHERE x.sheet_id = a.sheet_id AND x.score_got IS NOT NULL);
```

- [ ] **Step 5: 改 `store.py`**

1. 删掉 `_VERDICTS`，改成 `import verdicts`，`set_teacher_verdict` 用
   `verdicts.check`（`None` 仍表示撤回改判）。
2. `_SHEET_COLS` 加 `score_got` / `score_full` / `mark_raw` / `teacher_red`。
3. `put_sheet_answer` 多一个 `scored=False` 参数 → 写 `scored_at=now()`；
   传了 `verdict` 时走 `verdicts.check`，传了 `verdict_by` 时走 `check_by`。
4. `list_sheets` 的汇总改成三个数：`wrong` / `partial` / `lost`
   （`lost = Σ(score_full - score_got)`，按**改判后**的判定算，
   和现有 `COALESCE(teacher_verdict, verdict)` 一个口径）。
5. 新增 `set_sheet_total(sheet_id, total)`。
6. `sheet_answers` 的投影补上新列。

- [ ] **Step 6: 跑测试 + 全量**

```
.venv/bin/python -m pytest tests/test_verdicts.py tests/test_sheet_scores.py -q
.venv/bin/python -m pytest tests/ -q
```
Expected: 新测试全过；全量比现在多出新增的条数，**不许有既有测试变红**。

- [ ] **Step 7: 提交**

```bash
git commit -m "feat: 分数进库，判定值域收成一份——加 partial 不再要改四处"
```

---

## Task 3: 答题卡的进度和失败要有自己的出口

**Files:**
- Modify: `pipeline/modes.py`（**只加注释，不加格子**）
- Modify: `pipeline/store.py`（`progress` 的 `lastChange`）
- Modify: `pipeline/api.py`（`/api/papers/{name}` 带一份 `sheets`）
- Test: `tests/test_sheet_progress.py`、`tests/test_stage_answers_only.py`

**排在 Ⓑ 之前。** 顺序反了的话，Ⓑ 做完你在页面上看不见它在跑，
只能靠翻日志判断 —— 而这正是这一轮要消灭的那种毛病。

### 这一条是「进度永远走不到头」那次事故的镜像版

两个方向都会撒谎，所以两个方向都要写死：

| 做法 | 后果 |
|---|---|
| 往 `modes.SHEET` **加**格子（Ⓢ/Ⓑ/Ⓒ） | 没传答题卡的答案卷永远 `code != "done"` —— 整批退回「未完成」。连锁：`failure_note` 复活旧失败、`resume_gate` 的 done 闸失效 |
| **不加**格子，也不给答题卡别的出口 | `_stage_of_sheet` 在 ③c 完成后直接 `return "done"`，Ⓑ 跑多久这份卷子都写「已完成」；`store.progress` 的 `GREATEST` 不含答题卡两张表，`lastChange` 纹丝不动、`busy` 必然翻假（Ⓑa 实测一页 235 秒 > 180 秒的 idle 阈值），页面进度区整块不渲染 |

**结论：不加格子，答题卡走它自己的出口。** 理由和 `stemread` 不占格同源 ——
答题卡是选填的，给它一格要么永远灰着（读作卡住了）、要么打勾（撒谎说读过了）。

- [ ] **Step 1: 写会失败的测试**

```python
# -*- coding: utf-8 -*-
"""答题卡的进度和失败必须有它自己的出口，而且不许拖累卷子本身的进度。

两个方向都会撒谎：加格子 → 没传答题卡的卷子整批退回「未完成」；
不加格子又不给别的出口 → Ⓑ 跑十分钟页面上写「已完成」。
"""
import modes
import store


BASE = {"questions": 26, "solutions": 0, "labels": 0, "kps": 26, "kpsJudged": 26,
        "judged": 0, "worth": 0, "specsWorth": 0, "specs": 0, "drafts": 0,
        "sceneTried": 0, "ready": 0, "assembledFresh": False,
        "sourceKind": "answers_only"}


def test_没有答题卡的答案卷仍然是完成():
    """答题卡是选填的。因为「还没传答题卡」就把卷子判成没跑完，是撒谎"""
    assert modes.of("answers_only").stage_of(BASE)[0] == "done"


def test_有答题卡但一题没读的答案卷也仍然是完成():
    """卷子本身的进度说的是**参考答案侧**跑完没有，跟答题卡读到哪无关"""
    pg = dict(BASE, sheets=1, sheetAnswers=0)
    assert modes.of("answers_only").stage_of(pg)[0] == "done"


def test_答题卡不占格子():
    assert modes.SHEET.cells == ["refread", "kpmark"]


def test_stage_of不许硬取答题卡的键():
    """
    新分支一律 `pg.get`。`tests/test_stage_answers_only.py` 的 BASE 里一个
    sheet 键都没有，硬取会 KeyError，让 `/api/papers` 整个 500。
    """
    modes.of("answers_only").stage_of(BASE)      # 不带 sheet 键，不许抛


def test_落一条作答会让lastChange前移(db):
    """
    `store.progress` 的 GREATEST 原来只含 papers/solutions/specs/scenes。
    不含答题卡两张表的话，Ⓑ 边读边落库，`lastChange` 纹丝不动 ——
    前端拿它当重载 key，逐题结果落了库页面一条都不出现。
    """
    store.create_answers_paper("进度用卷", None)
    store.put_answer_question("进度用卷", 1, "A", None)
    before = store.progress("进度用卷")["lastChange"]
    sid = store.create_sheet("进度用卷", "张三", None)
    store.put_sheet_answer(sid, 1, raw_text="B")
    after = store.progress("进度用卷")["lastChange"]
    assert after > before


def test_刚落过作答的卷子是busy(db):
    """
    `busy` 是 `idle < 180`，而 Ⓑa 实测一页要 235 秒。不把答题卡算进
    `lastChange` 的话，Ⓑ 跑到第二页时 `busy` 已经翻假，页面上那块
    `pg.busy || !pg.done` 的进度区整块消失。
    """
    store.create_answers_paper("进度用busy卷", None)
    sid = store.create_sheet("进度用busy卷", "张三", None)
    store.put_sheet_answer(sid, 1, raw_text="B")
    assert store.progress("进度用busy卷")["busy"] is True


def test_卷子详情带出它的答题卡列表(db):
    """页面要按卡画进度和失败，卡的清单得跟着卷子一起下发"""
    store.create_answers_paper("进度用列表卷", None)
    sid = store.create_sheet("进度用列表卷", "张三", None)
    store.put_sheet_answer(sid, 1, raw_text="B")
    from pipeline import api
    got = api.paper("进度用列表卷")
    assert [s["id"] for s in got["sheets"]] == [sid]
    assert got["sheets"][0]["student"] == "张三"
```

- [ ] **Step 2: 跑一遍确认它失败** → `lastChange`、`busy`、`sheets` 三条红。

- [ ] **Step 3: 实现**

1. `modes.py`：`_stage_of_sheet` 顶上加一段注释，写明**为什么不加格子**、
   以及答题卡的出口在哪（指到 `/api/papers/{name}` 的 `sheets`）。
   函数体不动 —— 这一条的正确实现就是「什么都不做，并且把理由写下来」。
2. `store.progress`：`GREATEST` 里并进
   `(SELECT max(s.updated_at) FROM answer_sheets s WHERE s.paper_id=p.id)`
   和 `sheet_answers` 的最新时间；`put_sheet_answer` 要 `touch`
   `answer_sheets.updated_at`（现在只有 `set_teacher_verdict` 会 touch）。
3. `api.paper()`：结果里加 `"sheets": store.list_sheets(name)`
   （**只对 `answers_only` 的卷子查**，解析试卷不必多一次查询）。

- [ ] **Step 4: 跑测试 + 全量** → 全绿，尤其 `tests/test_stage_answers_only.py` 不许红。

- [ ] **Step 5: 提交**

```bash
git commit -m "feat: 答题卡的进度走自己的出口——不加格子，也不让它在卷子上撒谎"
```

---

## Task 4: 上传入口 + 两道零成本闸门 + 按卡存料

**Files:**
- Modify: `pipeline/stash.py`（按 `sheet_id` 存）
- Modify: `pipeline/api.py`（`POST /api/answer-sheets`、资产路由、删空壳判据）
- Modify: `pipeline/store.py`（`sheet_owner` 已有；补按卡清页）
- Test: `tests/test_sheet_upload.py`、`tests/test_sheet_assets.py`

**Interfaces:**
- `POST /api/answer-sheets`　form: `paper`（卷名）、`student`（学生标识）、`files[]`
- `GET /api/sheets/{id}/img/{fn}`　按卡鉴权取原图与切片
- 资产路径：`sheet/<sheet_id>/pNN.png`、`sheet/<sheet_id>/crop/<n>.png`
- 新增：
  - `store.sheet_page_path(sheet_id, page) -> str`　这一页的 `rel_path`
  - `store.put_sheet_pages(sheet_id, names) -> int`　整卡替换页清单，**多余的旧页连
    `assets` 行一起删**
  - `store.sheet_pages(sheet_id) -> [rel_path]`
  - `api.safe_to_delete_shell(name) -> bool`　这份卷子还能不能当空壳删掉

### 三件必须在这个任务里做完的事

**（一）路径按卡分。** 现在 `stash.py` 存的是卷子级的 `sheet/pNN.png`，
而一份卷子可以挂**多份**答题卡（`answer_sheets` 本来就是一对多）。第二个学生的
答题卡会就地覆盖第一个学生的 `sheet/p01.png`，而第一份的 `crop_rel` 还指着那个
路径 —— 页面上第一个学生的「原图切片」显示的是第二个学生的作答。
**红绿灯指错了人，比没有红绿灯更糟。**

顺序也要调：现在是先 `stash` 后建卡，得改成**先建 `answer_sheets` 行拿到 id，
再按 id 存料**。每次收料先把该 `sheet_id` 目录下的旧页连同 `assets` 行删干净
再写 —— 上次传 3 页这次传 2 页的话，上次的 `p03.png` 会被当成这次的读进来。

**（二）资产路由要认 `sheet/` 前缀。** 现有路由只有 `page/{n}`、`mathimg/{fn}`、
`img/{fn}` 三条，前缀写死，`sheet/` 开头的一条都取不出来 —— 切片会 404。
按卡鉴权，`store.sheet_owner` 已经现成。

**（三）贵调用前面加一道零成本闸门。** 这份卷子 `questions` 数为 0 时**当场拒**
（400，「参考答案还没读出来，先把它读完再传答题卡」）。没有这道闸，一份还没读
参考答案的卷子照样会把 Ⓑ 跑满 —— 十几次模型调用、二十来分钟，产出一份全是
`unsure` 的空报告。**便宜的筛子要排在贵的前面**，这是这个仓库里 ④c 挪到 ④ 前面
时已经定过的规矩。

### 顺带修一条既有的删空壳判据

`run_answer_pipeline` 里 Ⓐ 失败时删空壳的判据是「**这次新建的**」（`created`），
不是「**现在还空着**」。步二给答题卡开了独立入口之后，会出现这样的顺序：
建卷 → 传答题卡（落了 `sheet_answers`）→ 重跑 Ⓐ 且失败 → 按 `created` 判断
不会删（因为不是这次新建的），**但如果老师是在同一次里重建卷子的就会删**。
判据改成「删之前再查一次：这份卷子有没有 `answer_sheets`」，有就不删、
只报错并把卷子留着让人自己收拾。

- [ ] **Step 1: 写会失败的测试**

```python
# -*- coding: utf-8 -*-
"""答题卡上传：两道闸门、按卡存料、以及不许删掉带着作答的卷子。"""
import io

import pytest

import store
from pipeline import api


def test_卷子还没读出题就拒收答题卡(db, client, login):
    """
    **零成本闸门。** 没有它，一份还没读参考答案的卷子照样会把 Ⓑ 跑满 ——
    十几次模型调用、二十来分钟，产出一份全是 unsure 的空报告。
    """
    store.create_answers_paper("闸门用空卷", login["id"])
    r = client.post("/api/answer-sheets",
                    data={"paper": "闸门用空卷", "student": "张三"},
                    files=[("files", ("a.png", io.BytesIO(b"\\x89PNG"), "image/png"))])
    assert r.status_code == 400
    assert "参考答案" in r.json()["detail"]


def test_被拒的那次一个模型调用都没发生(db, client, login, no_model):
    """闸门在**发调用之前**。挡在后面等于没挡"""
    store.create_answers_paper("闸门用空卷2", login["id"])
    client.post("/api/answer-sheets",
                data={"paper": "闸门用空卷2", "student": "张三"},
                files=[("files", ("a.png", io.BytesIO(b"\\x89PNG"), "image/png"))])
    assert no_model.calls == 0


def test_两份答题卡的原图互不覆盖(db, tmp_path):
    """
    第一个学生的切片被第二个学生覆盖掉的话，页面上第一份诊断的「原图切片」
    显示的是别人的作答 —— 而对着原图核对是这个功能唯一的红绿灯。
    """
    store.create_answers_paper("存料用卷", None)
    a = store.create_sheet("存料用卷", "张三", None)
    b = store.create_sheet("存料用卷", "李四", None)
    pa = store.sheet_page_path(a, 1)
    pb = store.sheet_page_path(b, 1)
    assert pa != pb
    assert str(a) in pa and str(b) in pb


def test_重传少页时上一次的残页会清掉(db):
    """上次 3 页这次 2 页，上次的 p03 还在的话会被当成这次的读进来"""
    store.create_answers_paper("存料用重传卷", None)
    sid = store.create_sheet("存料用重传卷", "张三", None)
    store.put_sheet_pages(sid, ["p01", "p02", "p03"])
    store.put_sheet_pages(sid, ["p01", "p02"])
    assert len(store.sheet_pages(sid)) == 2


def test_带着作答的卷子不许被删空壳(db):
    """
    Ⓐ 失败时删空壳的判据要从「这次新建的」换成「现在还空着」——
    学生的作答不可再生。
    """
    store.create_answers_paper("删空壳用卷", None)
    sid = store.create_sheet("删空壳用卷", "张三", None)
    store.put_sheet_answer(sid, 1, raw_text="B")
    assert not api.safe_to_delete_shell("删空壳用卷")


def test_真空壳可以删(db):
    store.create_answers_paper("删空壳用真空卷", None)
    assert api.safe_to_delete_shell("删空壳用真空卷")


def test_答题卡的图取得出来(db, client, login):
    """资产路由原来只认 page/mathimg/img 三个前缀，sheet/ 一条都取不出来"""
    store.create_answers_paper("资产用卷", login["id"])
    sid = store.create_sheet("资产用卷", "张三", login["id"])
    store.put_sheet_pages(sid, ["p01"])
    r = client.get("/api/sheets/%d/img/p01.png" % sid)
    assert r.status_code in (200, 404)          # 有图就 200，图没落盘就 404
    assert r.status_code != 405, "这条路由压根不存在"


def test_别人的答题卡取不到(db, client, login):
    store.create_answers_paper("资产用别人卷", 90201)
    sid = store.create_sheet("资产用别人卷", "张三", 90201)
    r = client.get("/api/sheets/%d/img/p01.png" % sid)
    assert r.status_code in (403, 404)
```

- [ ] **Step 2: 跑一遍确认失败**（`client` / `login` / `no_model` 三个 fixture
      要先加进 `tests/conftest.py`，照 `tests/test_answer_upload.py` 现有的写法）

- [ ] **Step 3: 实现**，按上面三件事 + 删空壳判据。

- [ ] **Step 4: 跑测试 + 全量**

- [ ] **Step 5: 提交**

```bash
git commit -m "feat: 答题卡上传入口——按卡存料、贵调用前加零成本闸门"
```

---

## Task 5: `sheetread.py` —— Ⓑa 定位 / Ⓑb 补细节 / Ⓑc 读总分

**Files:**
- Create: `pipeline/sheetread.py`
- Test: `tests/test_sheetread.py`

**Interfaces:**
- `strips(marks, height, min_h=72, pad=0.05) -> [(题号列表, 上, 下)]`
- `merge(a_rows, b_rows) -> (合并后的行, 冲突列表)`
- `checksum(rows, total) -> (ok, 一句人话)`
- `read(paper_name, sheet_id, page_files, verbose=True)`

### 三段提示词，各管各的（数字见设计文档文末探针表）

| | 喂什么 | 出什么 | 实测 |
|---|---|---|---|
| Ⓑa | 整页原分辨率 | `{n, y, answer, mark, conf}` | 作答 10/10、符号 10/10、y 严格递增 |
| Ⓑb | 按 y 切条、放大 3× | `{n, filled, got, full, red, conf}` | 填涂 8/8、得分 8/8 |
| Ⓑc | 左上角总分那一小块、放大 3× | `{total}` | 待测 |

**Ⓑa 的提示词里不许提选择题的填涂。** 实测同一张图两次：不提的时候 8 道全
`unreadable` + `conf: low`，一个都没编；写了「填涂式的选择题也要」之后答了
6/8，错的两条里有一条把老师红笔写的正确答案当成了学生的作答。
**逼模型回答会把诚实的弃权变成自信的错误。**

**Ⓑc 必须是单独一次调用、单独一块裁图，且与 Ⓑb 的任一裁条不重叠。**
总分和逐题得分同源的话，「Σ得分对总分」就成了自证，那条校验一分钱的价值都没有。

- [ ] **Step 1: 写会失败的测试**

```python
# -*- coding: utf-8 -*-
"""Ⓑ 的三段纯函数：切条、合并、对总分。模型调用不在这里测。"""
import sheetread


# ---------------------------------------------------------------- 切条

def test_按y切成条():
    got = sheetread.strips([(9, 0.49), (10, 0.53), (11, 0.568)], 750)
    assert [ns for ns, _, _ in got] == [[9], [10], [11]]


def test_挨太近的题合并成一条():
    """
    实测选择题 8 道的 y 只差 0.013（750px 上约 10px）。一题一条的话每条才 10px，
    `stemread.slices` 那条「太薄的条跳过」会把 1-7 全丢掉；合并之后 1-8 并成
    一条约 100px，放大 3× 正好就是拿了 8/8 那个裁法。
    """
    marks = [(n, 0.355 + i * 0.013) for i, n in enumerate(range(1, 9))]
    got = sheetread.strips(marks + [(9, 0.49)], 750)
    assert got[0][0] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert got[1][0] == [9]


def test_条与条允许重叠():
    """
    得分标注印在作答行的**上方**，pad 不够会把标注切给上一条
    （实测第 11 题那条里带着 12(1) 的「1分(满分1分)」）。
    重叠在这里无害：Ⓑb 的提示词写明了这一条要读哪几道题。
    """
    got = sheetread.strips([(9, 0.49), (10, 0.53)], 750)
    assert got[1][1] < got[0][2], "第二条的上边应该落在第一条里面"


def test_y不递增就整页不切():
    """位置读乱了，切出来每一条都对不上题号 —— 宁可这一页不切"""
    assert sheetread.strips([(9, 0.7), (10, 0.3)], 750) == []


# ---------------------------------------------------------------- 合并

def test_两遍逐字段取非空():
    rows, clash = sheetread.merge(
        [{"n": 9, "answer": "不变 / 17190", "mark": "right"}],
        [{"n": 9, "got": 3, "full": 3}])
    assert rows[0]["answer"] == "不变 / 17190" and rows[0]["got"] == 3
    assert clash == []


def test_先到先得是错的():
    """
    实测踩过：同一题两条记录，一条有 got/full 一条没有，按先到先得合并
    **把有分数的那条丢了**。
    """
    rows, _ = sheetread.merge([{"n": 11, "mark": "wrong"}],
                              [{"n": 11, "got": 0, "full": 3}])
    assert rows[0]["got"] == 0 and rows[0]["full"] == 3


def test_两边都非空且不等要记冲突():
    _, clash = sheetread.merge([{"n": 9, "answer": "17190"}],
                               [{"n": 9, "answer": "17180"}])
    assert len(clash) == 1 and clash[0]["n"] == 9


def test_读不出来不算冲突():
    """
    `unreadable`/`blank` 是**读取状态**，不是作答内容。选择题上 Ⓑa 必然回
    `unreadable`、Ⓑb 回 8/8 —— 按「两边不等就记冲突」的话，8 道选择题每一道
    都会冒一条假警告，而**永远亮着的警告等于没有警告**。
    """
    rows, clash = sheetread.merge([{"n": 1, "answer": "unreadable"}],
                                  [{"n": 1, "filled": "D"}])
    assert rows[0]["answer"] == "D"
    assert clash == []


def test_第二遍冒出第一遍没有的题号要报出来():
    """
    那说明切条切歪了。

    （函数名里不许写 `Ⓑ` —— 带圈字母不是 Python 合法标识符，
    仓库 STATUS 的「踩过的坑」第 6 条记着这一条。）
    """
    _, clash = sheetread.merge([{"n": 9}], [{"n": 9}, {"n": 99}])
    assert any(c["n"] == 99 and "只有 Ⓑb" in c["why"] for c in clash)


# ---------------------------------------------------------------- 对总分

def test_加起来对得上就过():
    rows = [{"n": 9, "got": 3}, {"n": 11, "got": 0}, {"n": 15, "got": 7.5}]
    ok, _ = sheetread.checksum(rows, 10.5)
    assert ok


def test_对不上要说出来():
    ok, why = sheetread.checksum([{"n": 9, "got": 3}], 10.5)
    assert not ok and "10.5" in why and "3" in why


def test_没读到总分就跳过这条校验():
    ok, why = sheetread.checksum([{"n": 9, "got": 3}], None)
    assert ok and "没读到总分" in why


def test_对调两题的得分它查不出来():
    """
    **这条测的是判据的边界，不是缺陷。** Σ 对调换天然免疫，
    把它当成「读串的防线」会让人以为有防线而其实没有。
    读串靠另外三条：两遍对账、题号清单对账、满分对账。
    """
    a = [{"n": 9, "got": 3}, {"n": 10, "got": 1}]
    b = [{"n": 9, "got": 1}, {"n": 10, "got": 3}]
    assert sheetread.checksum(a, 4)[0] and sheetread.checksum(b, 4)[0]
```

- [ ] **Step 2: 跑一遍确认失败**
- [ ] **Step 3: 实现 `sheetread.py`**（三段提示词 + 上面四个纯函数 +
      每次子调用把 `(页, 哪一遍, 成败, 耗时, 条数)` 落一行，见 Task 6 的失败可见性）
- [ ] **Step 4: 跑测试**
- [ ] **Step 5: 登记四处** —— `PIPE_RE` 加 `sheetread|sheetcut`（**顺手把
      `stemread` 也补进去**，现在漏着）、`api.py` 的 `step_code` 表加
      `("Ⓑ 读批改", "sheetread", "sheetread.py", 3600)`、`modes.SHEET.cell_of`
      加映射、`tests/test_modes.py:243` 那个写死的代号集合同一次提交改。
      **四处漏哪一处都是静默的。**
- [ ] **Step 6: 提交**

---

## Task 6: `verdict.py` —— Ⓒ 判定、题号绑定、互校

**Files:**
- Create: `pipeline/sheetverdict.py`
- Test: `tests/test_sheetverdict.py`

**Interfaces:**
- `bind(sheet_rows, known_ns) -> (绑好的行, 整题级告警列表)`
- `decide(row) -> (verdict, verdict_by, why)`
- `crosscheck(row, ref_answer) -> 异常 | None`

### 题号绑定必须**按大题的小问集合**比，不能逐条比

这是这一轮最隐蔽的一条。按 `n = 主题号*100 + 小问号`：

| | 答题卡印的 | 算出来的 `n` | 参考答案 | 算出来的 `n` |
|---|---|---|---|---|
| 13 题 | (1)(2)**(4)(5)** | 1301 1302 **1304 1305** | (1)(2)(3)(4) | 1301 1302 1303 1304 |

`1301`、`1302`、**`1304`** 三条都**精确等于**一个已存在的 `question_id`。
那道「不许猜一个最近的题号安上去」的防线**拦不住它** —— 这是精确相等，不是猜。
而卡上的 (4) 实际对应答案的 (3)（设计文档已按满分序列 2/1/2/1 核实过）。

后果：页面「你写的 X / 标准答案 Y」那一栏拿的是**另一小问**的答案；互校要么冒
一条查无实据的不一致、要么两边碰巧一样而全线沉默；步三的丢分还会算到错的知识点上。

**规矩：某道大题的小问编号集合与参考答案不完全相等时，这道大题下所有小问一律
不绑 `question_id`，整题单独列出来请老师认。** 只有集合完全相等才逐条绑。

- [ ] **Step 1: 写会失败的测试**

```python
# -*- coding: utf-8 -*-
"""Ⓒ 判定：优先看分数、题号按大题集合绑、互校只报不改。"""
import sheetverdict


# ---------------------------------------------------------------- 题号绑定

KNOWN = [1301, 1302, 1303, 1304]          # 参考答案：13(1)(2)(3)(4)


def test_集合相等就逐条绑():
    rows, warn = sheetverdict.bind(
        [{"n": n} for n in (1301, 1302, 1303, 1304)], KNOWN)
    assert all(r["question_id_n"] == r["n"] for r in rows)
    assert warn == []


def test_集合不等时整道大题一条都不绑():
    """
    **本文件的主角。** 答题卡印的是 (1)(2)(4)(5)，参考答案是 (1)(2)(3)(4)。
    1301/1302/1304 三条精确命中已有题号，而卡上的 (4) 其实是答案的 (3) ——
    逐条绑的话这三条全绑到错的题上，只有 1305 挂不上。
    「不许猜一个最近的题号」那条拦不住精确相等。
    """
    rows, warn = sheetverdict.bind(
        [{"n": n} for n in (1301, 1302, 1304, 1305)], KNOWN)
    assert all(r["question_id_n"] is None for r in rows), \
        "小问编号对不上时，整道大题一条都不许绑"
    assert len(warn) == 1
    assert warn[0]["main"] == 13
    assert "(1)(2)(4)(5)" in warn[0]["why"] or "1305" in warn[0]["why"]


def test_别的大题不受牵连():
    rows, _ = sheetverdict.bind(
        [{"n": 1201}, {"n": 1301}, {"n": 1305}], [1201, 1301, 1302])
    got = {r["n"]: r["question_id_n"] for r in rows}
    assert got[1201] == 1201, "12 题自己是对得上的，不该被 13 题连累"
    assert got[1301] is None and got[1305] is None


def test_整数题号照常绑():
    rows, warn = sheetverdict.bind([{"n": 9}, {"n": 11}], [9, 11])
    assert [r["question_id_n"] for r in rows] == [9, 11] and warn == []


# ---------------------------------------------------------------- 判定

def test_满分是对():
    assert sheetverdict.decide({"got": 3, "full": 3})[:2] == ("right", "teacher_score")


def test_零分是错():
    assert sheetverdict.decide({"got": 0, "full": 3, "answer": "BIL"})[:2] \
        == ("wrong", "teacher_score")


def test_一半是半对():
    """标准答案 AB、学生写 A、老师打勾给 1分(满分2分)"""
    assert sheetverdict.decide({"got": 1, "full": 2})[:2] == ("partial", "teacher_score")


def test_读不到分数就退回勾叉():
    assert sheetverdict.decide({"mark": "right"})[:2] == ("right", "teacher_mark")


def test_勾叉也没有就是说不清():
    assert sheetverdict.decide({})[0] == "unsure"


def test_作答读不出来一律说不清不许说空白():
    """
    「没读出来」被渲染成「学生没作答」是最坏的一种：老师读到「这孩子没写」，
    而事实是「读不出来」，这些题还会从薄弱统计里整个消失（blank 分子分母都不进），
    错题正是这个功能唯一的产出。
    """
    assert sheetverdict.decide({"answer": "unreadable"})[0] == "unsure"
    assert sheetverdict.decide({"answer": "unreadable", "mark": "none"})[0] == "unsure"


def test_明确空着才是空白():
    assert sheetverdict.decide({"answer": "blank", "got": 0, "full": 2})[0] == "blank"


# ---------------------------------------------------------------- 互校

def test_系统和老师一致就不报():
    assert sheetverdict.crosscheck({"answer": "AC", "verdict": "wrong"}, "BC") is None


def test_不一致要报():
    got = sheetverdict.crosscheck({"answer": "BC", "verdict": "wrong"}, "BC")
    assert got and "老师" in got


def test_半对不算不一致():
    """
    `grade.judge("A", "AB")` 回 wrong，老师给的是 partial —— 这不是矛盾，
    是代码档判等本来就没有「部分对」这一档。算成异常的话，每道双选半对题都会
    冒一条假警告，真正的异常会被淹掉。
    """
    assert sheetverdict.crosscheck({"answer": "A", "verdict": "partial"}, "AB") is None


def test_判不了不算异常():
    """`grade.judge` 回 None 是常态（长解答题）"""
    assert sheetverdict.crosscheck(
        {"answer": "由动量定理得…", "verdict": "partial"}, "…") is None
```

- [ ] **Step 2–5:** 确认失败 → 实现 → 跑测试 → 提交。

---

---

> **Task 7–9 的详略和前面不一样，这是有意的，但要说清楚。**
>
> Task 1–6 每一步都带着会失败的完整测试代码 —— 那六个任务里全是**判据**
> （切不切、绑不绑、判 right 还是 partial），判据写错了是静默的，所以要把
> 测试先钉死。
>
> Task 7–9 是接线和版面：它们的形状取决于 Task 1–6 落地后的真实签名，
> 现在把代码写死，等做到那里多半已经对不上、反而误导实施的人。
> 所以这三个任务给的是**契约 + 验收标准**，逐步骤的测试代码在动手前补齐 ——
> 补的时候照 Task 1–6 的样子写，规矩不变：**先写会失败的测试**。

## Task 7: 落库 + 接进管线

**Files:** `pipeline/api.py`（`run_sheet_pipeline`）、`pipeline/store.py`

Ⓢ → Ⓑa → Ⓑb → Ⓑc → Ⓒ → 落库，一份答题卡一条链，走 `run_step`（**Ⓢ 是纯代码
也要显式 `JOBS.update(err_code="sheetcut")`**，否则它挂了一格都不红）。

**中途闸门**：第一页读完后，能挂上 Ⓐ 清单的题号为 0 条就停下来报
「这几张图多半不是这份卷子的答题卡」，不要把剩下几页读完。判据和
`refread.BLANK_PAGES_LIMIT` 同构，照抄。

**每次子调用落一行**（页 × 哪一遍 × 成败 × 耗时 × 条数）。没有这个的话，
「Ⓑb 第 2 页整遍失败」和「这几道题本来就读不出」在库里和页面上完全同形。
覆盖率对账：Ⓑa 报出 N 条题号而 Ⓑb 回 0 条时一律当**整遍失败**，
不许走逐题降级那条路。

---

## Task 8: 页面 —— 答题卡列表与详情

**Files:** `web/src/components/SheetDetail.tsx`（新建）、`SheetView.tsx`、
`SheetUpload.tsx`、`api.ts`、`types.ts`、`styles.css`

按设计文档「页面」那节的版面和**六条硬约束**做。逐题速览里
**「半对」用 `◐`，不混进 ✓ 也不混进 ✗**。

每张卡自己画进度和失败横幅（数据来自 Task 3 的 `sheets`）。
Ⓢ 走了哪条分支要在逐题原图上方明说（「这张按整页读的，没找到答题卡边界」）。

收尾：`SheetView` 的页脚跟着实际有没有答题卡变；`fact` 格加上答题卡侧的数；
进度条的 `bar` 分支改成按 `stageCode` 查一张表，**缺口径时不画条**而不是画个假的。

---

## Task 9: 改判

**Files:** `pipeline/api.py`、`pipeline/store.py`、`web/src/components/SheetDetail.tsx`

两件事必须一起做，否则页面会自相矛盾：

1. **改判要连分数一起改。** 只写 `teacher_verdict` 不动分数列的话，页面会显示
   「对 · 0 分（满分 3 分）」，而步三的丢分率完全无视改判。
   做法：`set_teacher_verdict` 多收一个 `score_got`，另存 `teacher_score_got` 一列；
   对外读取一律 `COALESCE(teacher_score_got, score_got)`，**只在
   `store.sheet_answers` 那一个地方 COALESCE**（和 `final_verdict` 同一个规矩 ——
   让每个调用点各写一份，总会漏掉一个）。
2. **`set_teacher_verdict` 命中 0 行要抛。** 现在改一个不存在的题号会静默成功，
   还顺手把诊断标为过期。检查 `rowcount`，为 0 就抛，API 层转 404。

---

## Task 10: 拿真材料端到端跑一遍

不写测试，人工验收。材料：`~/Desktop/试卷+答题卡/` 那 2 张已批改答题卡截图，
卷子用库里已有的 `2025-2026高二物理期末`（26 题，参考答案真值表验过）。

**逐条对下面这张真值表**（我逐格看原图读出来的，并且用总分对过账：
逐题得分加起来正好等于卷子上印的 58.5）：

| 题 | 学生写的 | 标准答案 | 得分 | 该判 |
|---|---|---|---|---|
| 1–4 | D C C B | D C C B | 16/16 | 全 `right` |
| 5 | AC | AC | 6/6 | `right` |
| 6 | AC | BC | 0/6 | `wrong`（老师红笔写了 `BC`） |
| 7 | BC | BC | 6/6 | `right` |
| 8 | D | AC | 0/6 | `wrong`（老师红笔写了 `AC`） |
| 9 | 不变 / 17190 | 同 | 3/3 | `right` |
| 11 | BIL / MQ | 2BIL / MP | 0/3 | `wrong` |
| 12(1) | 170 / B | 170 / A | 1/2 | `partial` |
| **12(3)** | **A** | **AB** | **1/2** | **`partial`** ← 老师打的是**红勾** |
| 13(1) | AC | BC | 0/2 | `wrong` |
| 13(3) | 空 | 6.3×10⁻¹⁰ | 0/2 | `blank` |
| 14 / 15 / 16 | — | — | 11/11、7.5/12、0/16 | `right`／`partial`／`wrong` |
| | | | **Σ = 58.5** | |

**验收四条：**

1. Σ 得分 = 58.5，页面上不报「对不上总分」
2. 12(3) 判成 `partial`，不是 `right`
3. 第 13 题四条小问**一条都没绑上** `question_id`，页面单独列出「小问编号对不上」
4. 逐题原图切片点开是对的那道题

**跑完把结论写进 `docs/superpowers/STATUS.md`。**
