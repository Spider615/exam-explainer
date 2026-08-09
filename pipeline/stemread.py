#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stemread.py —— Ⓔ 原卷题目图 → 每道题的题干

    python pipeline/stemread.py <卷名> <图1|某.pdf> [图2 ...]

为什么非它不可
--------------
参考答案的版式是「选择题给一张答案表、填空题给答案、**只有大题才有详解**」。
实测老师那份 26 题的卷子：8 道有解答过程，另外 18 道只有一个 `D` / `BC` /
`170 / A`。而**一个孤零零的字母推不出这道题考什么** —— ③c 在这 18 道上必然
交白卷（实测 26 道只挂上 9 道）。

那个字母里真的不含「考什么」这个信息，换模型、换提示词都一样。要挂上知识点
就得有题干，这一步就是去把题干取回来。

题号清单以参考答案为准
----------------------
**Ⓔ 不定题号，只填题干。** 参考答案上的题号是这条链里最可靠的一份清单
（`refread` 的文件头写了理由），所以这里读出来的题号必须是那份清单的子集：
多出来的一律丢掉并告警 —— 多出来意味着读错了，而错的题干会把 ③c 引到
另一道题上去，比没有题干更糟。

这是白捡的对账，等价于原设计里「本题共 N 小题」那道防线。

小问怎么办
----------
原卷上是「12.（6分）（1）… （2）…」，而 Ⓐ 给出的清单里是 1201/1202/1203。
让模型去拆小问容易拆歪，所以约定：**模型给主题号就够，主题号的题干回填给
它下面所有小问**。它们本来就共用同一段题干（「如图所示，理想变压器…」），
分别写一份反而是假精确。模型如果自己给出了 `12(1)` 这种更细的，就用细的。

图怎么办：转写只描述，另外切一条原卷截图
----------------------------------------
提示词里明确要求「插图只用一句话描述，**不要**转写坐标刻度」—— 逐点转写一张
受力分析图，错了没人看得出来。可代价是转出来的题干**把图丢了**：物理题一句
「如图所示」之后什么都没有，人根本没法读。

所以另外切一条原卷截图（`cut_page` / `slices`），和转写的题干并排放。

设计文档当初否掉「裁插图」的理由是「裁图要坐标，硬做会引入一个**裁歪了
没人看得见**的错」。这里绕开的正是那五个字：

  · **只按题号横着切，不做紧贴插图的框** —— 模型只给一个数（题号那一行的
    高度），不是四个。切歪的后果是「多带一点上一道题」，不是「把图切掉一半」。
  · **切出来的图摆在转写的题干旁边** —— 图文对不上一眼就看得见，
    错不再是悄悄的。
  · **y 不随题号递增就整页不切** —— 位置读乱了的话每一条都会对错题号，
    宁可这一页没有图。
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mathvlm
import pages
import refread
import store

PROMPT = """这是一份物理试卷的**题目**（不是答案）。

逐题读出题干，输出 JSON 数组（不要代码块围栏、不要解释）：
[{"n": "6", "y": 0.42, "stem": "如图所示，两平行金属板间…（ ）",
  "options": ["A. 场强变大", "B. …"]}]

· `n` 题号。**必须是图上真实认出来的，不许按顺序编。** 分小问的题写主题号
  就行（写 "12"，不用写 "12(1)"）；只有当各小问的问法差别很大、必须分开时
  才写成 "12(1)"。
· `y` 这道题的**题号那一行**在整页上的相对高度，0 是页顶、1 是页底，两位小数。
  只要这一个数，**不要给框、不要给左右边界** —— 后面按它把整页横着切成一条一条，
  一道题一条。估偏一点没关系（顶多多带一点上一道题），但**必须按题号从上到下
  递增**。
· `stem` 题干**原样转写**，公式用 LaTeX。题干里的插图**只用一句话描述**
  （例如「图中两平行板水平放置，中间有一带电微粒」），**不要**去转写坐标、
  刻度、箭头位置。
· `options` 选择题的选项，没有就给空数组。

三条硬规则：

1. 认不出题号的**整条不要输出**。宁可少一道题，也不要把 A 题的题干安到 B 题上 ——
   那会把后续的知识点标注整个引偏。
2. 只读这张图上有的，**不要补全**、不要根据常识把没印出来的部分写出来。
3. 这是题目页。如果这一页上没有任何题目（封面、答题卡、参考答案、草稿页），
   输出空数组 `[]`。

页眉页脚、页码、水印、分数标注（「（6分）」）一律忽略。
"""

# 开头连着几页读不出题就停。理由同 refread：喂错材料时别一页页啃下去
BLANK_PAGES_LIMIT = 3


def flatten(row):
    """
    一条模型输出 → `(题号, 题干文本)`。**纯函数**，认不出回 `(None, None)`。

    选项并进题干：`put_stem` 只有一列，而 ③c 要的是「这道题在问什么」——
    选项本身就是题意的一部分（「下列四幅电场线图哪个正确」离了选项什么都不是）。
    """
    if not isinstance(row, dict):
        return None, None
    n = refread.qnum(row.get("n"))
    stem = str(row.get("stem") or "").strip()
    if n is None or not stem:
        return None, None
    opts = [str(o).strip() for o in (row.get("options") or []) if str(o).strip()]
    return n, ("\n".join([stem] + opts) if opts else stem)


def slices(marks, height, pad=0.012):
    """
    这一页上每道题切成一条横的。**纯函数**，返回 `[(题号, 上, 下)]`（像素）。

    `marks` 是 `[(题号, y)]`，`y` 是题号那一行的相对高度（0~1）。

    **只按题号切横条，不做紧贴的框。** 设计文档当初否掉「裁插图」的理由是
    「裁图要坐标，硬做会引入一个『裁歪了没人看得见』的错」—— 那条顾虑在这里
    不成立，因为：模型只给一个数（不是四个），切歪的后果是「多带一点上一道题」
    而不是「把图切掉一半」；而且截图会摆在转写的题干旁边，对不上一眼就看得见。

    上边留一点余量（`pad`）：`y` 指的是题号那一行，不留的话题号本身会被切掉半行。
    最后一道切到页底 —— 它下面就是页脚，带上无所谓。

    **y 不按题号递增就整页不切**（回空）。那说明模型把位置读乱了，而位置乱了
    切出来的每一条都对不上题号 —— 宁可这一页没有图，也不要 26 张错的图。
    """
    marks = [(n, y) for n, y in marks if isinstance(y, (int, float)) and 0 <= y <= 1]
    if not marks:
        return []
    if [n for n, _ in marks] != sorted(n for n, _ in marks):
        return []                       # 题号本身没排好，谈不上切
    if any(b <= a for (_, a), (_, b) in zip(marks, marks[1:])):
        return []                       # y 没有随题号递增
    out = []
    for i, (n, y) in enumerate(marks):
        top = max(0, int((y - pad) * height))
        bottom = int(marks[i + 1][1] * height) if i + 1 < len(marks) else height
        if bottom - top >= 24:          # 太薄的条说明位置估崩了，跳过这一条
            out.append((n, top, bottom))
    return out


def spread(got, known):
    """
    把读到的题干配到**参考答案给出的那份题号清单**上。**纯函数。**

    `got` 是 {题号: 题干}（题号可能是主题号 12，也可能是小问 1201），
    `known` 是 Ⓐ 写进库的那些题号。返回 {已知题号: 题干} 与一串告警。

    三件事在这里做完：
      · 主题号的题干**回填给它下面所有小问** —— 它们共用同一段题干
      · 小问自己有更细的题干时，细的优先
      · 清单里没有的题号**丢掉并告警** —— 多出来意味着读错了，
        而错的题干会把 ③c 引到另一道题上，比没有题干更糟
    """
    out, extra = {}, []
    for n in sorted(got):
        if n in known:
            out[n] = got[n]                      # 直接命中
            continue
        subs = sorted(x for x in known if x >= 100 and refread.main_of(x) == n)
        if subs:
            for s in subs:                       # 主题号 → 回填给所有小问
                out.setdefault(s, got[n])
            continue
        extra.append(n)
    # 小问自己给的题干优先于回填来的
    for n in sorted(got):
        if n in known:
            out[n] = got[n]
    warn = []
    if extra:
        warn.append("这些题号参考答案里没有，已丢掉：%s（多半是读错了）"
                    % "、".join(refread.show_qnum(n) for n in extra))
    return out, warn


def cut_page(paper_name, hires, marks, outdir):
    """
    把这一页按题号切成一条一条存起来，返回 `{题号: 资产路径}`。

    **只负责切和存，判在 `slices` 里**（那是纯函数，能单独测）。

    存进 `mathimg/`：那条路由本来就是「原卷截图，给人核对用」，复用它，
    前端 `stemImage` 那一路一个字都不用改。
    """
    from PIL import Image
    out = {}
    with Image.open(hires) as im:
        cuts = slices(marks, im.height)
        if not cuts:
            return out
        os.makedirs(outdir, exist_ok=True)
        for n, top, bottom in cuts:
            path = os.path.join(outdir, "q%04d.png" % n)
            im.crop((0, top, im.width, bottom)).save(path)
            rel = "mathimg/stem-q%04d.png" % n
            store.put_page_asset(paper_name, path, rel)
            out[n] = rel
    return out


def read(paper_name, page_files, verbose=True):
    """
    读一批原卷图，按 Ⓐ 的题号清单把题干填进库，返回填了几题。

    **一页失败不拖垮整批**（同 refread）：失败的页记下来照实报，
    只有一页都没成才算失败。
    """
    log = ((lambda s: print(s, flush=True)) if verbose else (lambda *a, **k: None))
    paper = store.get_paper(paper_name)
    if not paper:
        raise RuntimeError("库里没有「%s」—— 先传参考答案，题号清单以它为准" % paper_name)
    known = {q["n"] for q in paper["questions"]}
    if not known:
        raise RuntimeError("「%s」里一道题都没有 —— 先把参考答案读出来，"
                           "题号清单以它为准" % paper_name)

    work = os.path.join(ROOT, "work", paper_name, "stem")
    pgs = pages.normalize(page_files, work, prefix="p")
    # 分母先报出来，页面上那条进度条要靠它（同 refread，措辞里「共 N 页」要留着）
    log("── 共 %d 页要读（一页一分钟上下）" % len(pgs))

    got, shots, failed, blank = {}, {}, [], 0
    for pg in pgs:
        try:
            rows = mathvlm.ask_raw(pg["hires"], PROMPT, want="array", timeout=600)
        except Exception as e:
            failed.append(pg["page"])
            log("   第%d页 ✗ 没读成：%s" % (pg["page"], str(e)[:120]))
            continue
        page_got, marks = {}, []
        for r in (rows if isinstance(rows, list) else []):
            n, stem = flatten(r)
            if n is not None and n not in page_got:
                page_got[n] = stem                # 同一页同一题号，取先出现的
                marks.append((n, r.get("y")))
        got.update(page_got)
        store.put_page_asset(paper_name, pg["hires"], "stem/p%02d.png" % pg["page"])
        cut = cut_page(paper_name, pg["hires"], marks, os.path.join(work, "cut"))
        shots.update(cut)
        log("   第%d页 读到 %d 道题%s"
            % (pg["page"], len(page_got),
               "，切出 %d 张题目截图" % len(cut) if cut
               else "（这一页没切出截图 —— 位置读乱了，宁可不给图）"))

        # 开头连着几页一道题都读不出来 —— 多半喂错了材料（把参考答案或答题卡
        # 放进了「原卷」那一栏），别再往下啃。理由与 refread 那道闸相同
        if not got:
            blank += 1
            if blank >= BLANK_PAGES_LIMIT:
                raise RuntimeError(
                    "前 %d 页一道题都没读出来，停下来了 —— 再往下读也是白花时间。\n"
                    "   这一栏要的是**原卷**（印着题目的那份试卷），"
                    "不是参考答案、也不是答题卡。" % blank)

    fit, warns = spread(got, known)
    for w in warns:
        log("   ⚠ %s" % w)
    if not fit:
        raise RuntimeError("这几张图里没有一道题能对上参考答案的题号清单。"
                           "多半传的不是这份卷子的原卷。")

    # 截图按同一套规则配到题号上（主题号的图回填给它下面所有小问）
    fit_shot, _ = spread(shots, known)
    for n in sorted(fit):
        store.put_stem(paper_name, n, fit[n])
    for n in sorted(fit_shot):
        store.put_stem_image(paper_name, n, fit_shot[n])
    log("── 题干 %s：填上 %d / %d 题，其中 %d 题有原卷截图"
        % (paper_name, len(fit), len(known), len(fit_shot)))
    miss = sorted(known - set(fit))
    if miss:
        # 缺了就说缺了。这些题仍然只能靠答案挂知识点，多半挂不上
        log("   ⚠ 还有 %d 题没有题干：%s"
            % (len(miss), "、".join(refread.show_qnum(n) for n in miss)))
    if failed:
        log("   ⚠ 有 %d 页没读成（第 %s 页），这几页上的题全缺了，请重传"
            % (len(failed), "、".join(map(str, failed))))
    return len(fit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    read(a.paper, a.files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
