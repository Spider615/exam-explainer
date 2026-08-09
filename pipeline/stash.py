#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stash.py —— 收下一批原始材料，规范化成页面图存进库，**不读内容**

    python pipeline/stash.py <卷名> --kind stem <图1> [图2 ...]

为什么要有这一步
----------------
老师手上是三样东西：**原卷（题目）、答题卡、参考答案**。这一轮只有参考答案
那条链（Ⓐ）做好了 —— 但没理由让他为此分三次、隔几周传三回。三样一起交上来，
用得上的现在读，用不上的**先收着**；等 Ⓔ 读题干、步二读答题卡做好，料已经
在库里，不用回头找他要。

`pages.normalize` 本来就是三条链共用的前半段（EXIF 转正、按文件名自然排序、
两档分辨率、按内容哈希）—— 所以现在存下来的东西将来那两步直接能用，不是白存。

不猜
----
**这批是什么，由上传的人在页面上分好，不在这里认。** 让系统去猜的话，
认错一页参考答案的代价是那一页上的题悄悄没了 —— 而「悄悄」是这个项目
最不能接受的失败形状。三个上传框比一个聪明的分拣器可靠。

存在哪
------
`assets.kind` 是从 `rel_path` 的第一段推出来的（见 `store.put_asset`），
所以前缀就是分类：

    page/pNN.png    参考答案 —— 由 refread（Ⓐ）存，不归这里管
    stem/pNN.png    原卷题目 —— 等 Ⓔ 读题干
    sheet/pNN.png   答题卡   —— 等步二 Ⓢ 抠图 / Ⓑ 读批改
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pages
import store

# 能收哪几类。**`page`（参考答案）不在这里** —— 它由 refread 边读边存，
# 混进来的话同一批图会被存两遍，而且谁存的说不清
KINDS = {
    "stem": ("原卷题目", "等 Ⓔ 读题干"),
    "sheet": ("答题卡", "等步二读批改结果"),
}


def stash(paper_name, files, kind, verbose=True):
    """
    收下一批文件，规范化成页面图存进库，返回存了几页。

    一个文件都没有就回 0，不当失败 —— 这两栏本来就是选填的。
    """
    if kind not in KINDS:
        raise ValueError("不认识的分类 %r，只收 %s" % (kind, "/".join(KINDS)))
    log = ((lambda s: print(s, flush=True)) if verbose else (lambda *a, **k: None))
    if not files:
        return 0
    label, waiting = KINDS[kind]
    work = os.path.join(ROOT, "work", paper_name, kind)
    pgs = pages.normalize(files, work, prefix="p")
    for pg in pgs:
        store.put_page_asset(paper_name, pg["hires"], "%s/p%02d.png" % (kind, pg["page"]))
    # 说清楚「收下了但还没读」—— 不说的话，页面上看不到任何变化，
    # 人会以为传上去的东西丢了
    log("── %s %s：收下 %d 页，先存着（%s）" % (label, paper_name, len(pgs), waiting))
    return len(pgs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--kind", required=True, choices=sorted(KINDS))
    a = ap.parse_args()
    stash(a.paper, a.files, a.kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
