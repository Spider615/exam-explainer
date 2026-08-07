#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refread.py —— Ⓐ 参考答案图 → 题号 / 标准答案 / 解答过程

    python pipeline/refread.py <卷名> <图1> [图2 ...]

老师手上常常只有参考答案和答题卡，没有电子版试卷。参考答案是印刷体、版面
干净，比答题卡好读得多，**它上面的题号是这条链里最可靠的一份清单** ——
Ⓔ 读题干、Ⓑ 读答题卡都拿它对账。

认不出就整条丢掉
----------------
一道错的标准答案，会让所有做对这道题的学生都被判错，凭空造出一个假的
薄弱知识点 —— 而薄弱知识点是这整个功能唯一的产出。宁可少一道题。

只有大题有详解，这是常态
------------------------
2026-08-08 实测：参考答案的版式是选择题给一张答案表、填空题给答案、
**只有大题才有解答过程**。所以 `ref_solution` 大面积为 NULL 不是缺陷。
正因为如此才需要 Ⓔ 读题干 —— 一个孤零零的「D」推不出这道题考什么。

小问怎么编号
------------
`questions.n` 是 int，而参考答案里有 `12(1)` 这种。约定
**`n = 主题号 * 100 + 小问号`**（`12(1)` → `1201`，无小问的 `11` → `11`）。
不改表结构、排序天然正确、显示时 `show_qnum` 还原。
**前提是题号不超过 99** —— 高中物理卷不会有 100 题，但这个前提写在这里。
"""
import argparse, os, re, sys

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
    """`"12(1)"` → 1201，`"11"` → 11。认不出回 None，**不硬解**。"""
    if s is None:
        return None
    m = _QN.match(str(s).replace("（", "(").replace("）", ")"))
    if not m:
        return None
    main = int(m.group(1))
    return main * 100 + int(m.group(2)) if m.group(2) else main


def show_qnum(n):
    """1201 → `"12(1)"`，11 → `"11"`。页面与日志显示用。"""
    return "%d(%d)" % (n // 100, n % 100) if n >= 100 else str(n)


def keep(rows):
    """
    把模型的原始输出过成可以入库的形状。**纯函数**，正确性判断全在这里。

    同一题号出现多次按页序**拼接** `solution`（跨页续写），不是覆盖。
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
            out[n]["ref_solution"] = ((prev + " " + sol).strip() if prev and sol
                                      else (prev or sol))
            continue
        out[n] = {"n": n, "ref_answer": ans, "ref_solution": sol}
    return [out[k] for k in sorted(out)]


def read(paper_name, page_files, verbose=True):
    """
    读一批参考答案图，写进库，返回写了几题。

    **一页失败不拖垮整批。** 一页要一分钟上下，四页就是好几分钟；最后一页
    超时就把前三页的结果一起丢掉，代价太大。失败的页记下来、照实报出来，
    只有**一页都没成**才算失败。
    """
    # flush 不能省：这个函数从 API 那条链上是当子进程跑的，print 走管道是块
    # 缓冲，不 flush 的话跑五分钟外面一个字都看不到，跟卡死分不出来
    log = ((lambda s: print(s, flush=True)) if verbose else (lambda *a, **k: None))
    work = os.path.join(ROOT, "work", paper_name)
    pgs = pages.normalize(page_files, os.path.join(work, "page"), prefix="p")

    raw, failed = [], []
    for pg in pgs:
        # 送 hires 而不是 web：实测 1080×1441 比 540×720 还快，而且更清楚。
        # 但**绝不放大**（见 mathvlm.ask_raw 的说明）
        try:
            got = mathvlm.ask_raw(pg["hires"], PROMPT, want="array", timeout=600)
        except Exception as e:
            failed.append(pg["page"])
            log("   第%d页 ✗ 没读成：%s" % (pg["page"], str(e)[:120]))
            continue
        got = got if isinstance(got, list) else []
        raw += got
        store.put_page_asset(paper_name, pg["hires"], "page/p%02d.png" % pg["page"])
        log("   第%d页 读到 %d 条" % (pg["page"], len(got)))

    rows = keep(raw)
    if not rows:
        raise RuntimeError("这几张图里一道题的答案都没读出来。多半不是参考答案，"
                           "或者拍得太糊 —— 请换清楚一点的图。")
    n_sol = 0
    for r in rows:
        store.put_answer_question(paper_name, r["n"], r["ref_answer"],
                                  r["ref_solution"])
        n_sol += bool(r["ref_solution"])
        log("   第%-8s %s%s" % (show_qnum(r["n"]) + "题", r["ref_answer"][:44],
                                "" if r["ref_solution"] else "   （无解答过程）"))
    log("── 参考答案 %s：写入 %d 题，其中 %d 题带解答过程" % (paper_name, len(rows), n_sol))
    if n_sol < len(rows):
        # 缺了就说缺了。这些题只能靠 Ⓔ 读来的题干挂知识点
        log("   %d 题只有答案没有过程 —— 它们要靠题目图（Ⓔ）才挂得上知识点"
            % (len(rows) - n_sol))
    if failed:
        # 失败的页必须报出来。悄悄少几页的话，缺的那几道题看起来就像
        # 「这份卷子本来就没有」，没人能发现
        log("   ⚠ 有 %d 页没读成（第 %s 页），这几页上的题全缺了，请重传"
            % (len(failed), "、".join(map(str, failed))))
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
