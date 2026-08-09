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
