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
