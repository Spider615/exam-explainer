#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
anchors.py —— 通用题目锚点探测

问题
----
每份卷子的排版都不一样：有的用「单选题 (4分)」标记，有的用裸「单选题」，
有的用阿拉伯题号「1.」，有的什么标记都没有、只靠字号和缩进区分。
为每种排版写一条规则，就等于每来一份新卷子改一次代码——那不是产品。

思路
----
不要去猜「题目长什么样」，而是用**所有卷子都成立的结构性质**来判断切得对不对：

  · 一份卷子是一串题，题在版面上占连续的纵向区间；
  · 大题标题通常声明了题数（「本题共4小题」），可以对账；
  · 题干长度有合理分布——切出一堆几个字的碎片，一定是切错了；
  · 锚点应大致铺满全文，而不是挤在某一页。

于是做法变成：**若干个互相独立的探测器各自给出一套候选锚点，
再用同一个与版式无关的打分器选出最合理的那套。**

加一种新排版，通常不需要动代码——三个探测器里总有一个会命中；
真需要时也只是加一个探测器，而不是在既有正则上叠补丁。

三个探测器
----------
D1 题型词   「单选题/多选题/实验题…」，可带或不带分值
D2 阿拉伯题号  行首 `N.` `N、`，且必须从 1 开始逐 1 递增（这条自校验极强）
D3 排版信号   字号 + 左边距 + 前置纵向间距构成的重复模式，完全不看文字内容
"""
import re

TYPE_WORDS = ("单选题", "多选题", "填空题", "实验题", "计算题", "解答题",
              "作图题", "论述题", "简答题", "综合题")


# ---------------------------------------------------------------- 探测器
def d1_type_words(text, flow, doc):
    """题型词。带分值的写法更具体，单独作为一个候选返回。"""
    alt = "|".join(TYPE_WORDS)
    out = []
    for name, pat, pg in (
            ("题型词+分值", r"(%s)\s*[（(](\d+)分[)）]" % alt, 2),
            # 不要求前置空白：公式线性化后会出现 `E_k /单选题` 这种紧邻，
            # 加了这条约束会静默漏掉一批锚点（实测 15 题只认出 9 题）。
            # 中文正文里出现「单选题」本就极罕见，大题标题由「、」过滤挡住。
            ("题型词", r"(%s)" % alt, None)):
        ms = []
        for m in re.finditer(pat, text):
            # 「一、单选题」这类大题标题不是题目锚点
            head = text[max(0, m.start(1) - 3):m.start(1)]
            if "、" in head or "，" in head:
                continue                     # 「一、单选题」是大题标题，不是题目锚点
            ms.append({"pos": m.start(1), "end": m.end(),
                       "type": m.group(1),
                       "points": int(m.group(pg)) if pg else None})
        if ms:
            out.append((name, ms))
    return out


def d2_arabic(text, flow, doc):
    """
    阿拉伯题号。只认「从 1 开始、逐 1 递增」的那条链——
    这一条自校验非常强：正文里的数字凑不出一条完整递增链。
    """
    cand = [(m.start(1), int(m.group(1)), m.end())
            for m in re.finditer(r"(?:^|[\s　 ])(\d{1,2})\s*[.．、]", text)]
    best = []
    for i in range(len(cand)):
        if cand[i][1] != 1:
            continue
        chain, want = [cand[i]], 2
        for j in range(i + 1, len(cand)):
            if cand[j][1] == want:
                chain.append(cand[j])
                want += 1
        if len(chain) > len(best):
            best = chain
    if len(best) < 4:
        return []
    return [("阿拉伯题号", [{"pos": p, "end": e, "type": None, "points": None}
                            for p, _, e in best])]


def d3_typography(text, flow, doc):
    """
    排版信号：完全不看文字内容，只看「字号 + 左边距 + 前置纵向间距」。

    题目首行在版面上通常是同一种打扮：同样的字号、同样的左边距、
    前面留一段比行距大得多的空白。把符合同一种打扮的行聚成一类，
    每一类就是一套候选锚点。
    """
    marks = []
    prev = None
    for f in flow:
        if not f["ok"]:
            continue
        gap = None
        if prev and prev["page"] == f["page"]:
            gap = prev["y"] - f["y"]          # PDF y 向上，往下读 gap 为正
        marks.append({"pos": f["start"], "end": f["end"], "x": f["x"],
                      "size": f.get("size", 0), "gap": gap})
        prev = f
    if len(marks) < 8:
        return []

    gaps = sorted(m["gap"] for m in marks if m["gap"] is not None and m["gap"] > 0)
    if not gaps:
        return []
    line_h = gaps[len(gaps) // 2]             # 中位数近似行距
    groups = {}
    for m in marks:
        if m["gap"] is None or m["gap"] < line_h * 1.6:
            continue                          # 不是「前面有明显留白」的行
        key = (round(m["size"], 1), round(m["x"] / 6) * 6)
        groups.setdefault(key, []).append(m)

    out = []
    for key, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(g) < 5:
            continue
        out.append(("排版 字号%.1f/左%d" % key,
                    [{"pos": m["pos"], "end": m["end"], "type": None, "points": None}
                     for m in g]))
        if len(out) >= 3:                     # 只保留最主流的几种打扮
            break
    return out


DETECTORS = (d1_type_words, d2_arabic, d3_typography)


# ---------------------------------------------------------------- 打分
def score(anchors, text, declared_total):
    """
    与版式完全无关的结构打分。分数越高越可信。

    返回 (分数, 说明)。这是整套设计的重心——探测器可以很脏，
    只要打分器足够挑剔，脏候选就会被淘汰。
    """
    n = len(anchors)
    if n == 0:
        return -1e9, "无锚点"

    segs = []
    for i, a in enumerate(anchors):
        end = anchors[i + 1]["pos"] if i + 1 < n else len(text)
        segs.append(max(0, end - a["end"]))
    segs_sorted = sorted(segs)
    med = segs_sorted[n // 2]
    tiny = sum(1 for s in segs if s < 25)

    s = 0.0
    notes = []

    # 1) 与大题声明的题数对账 —— 最强的一条外部证据
    if declared_total:
        d = abs(n - declared_total)
        s -= d * 12
        notes.append("切出%d/声明%d" % (n, declared_total))
    else:
        notes.append("切出%d题" % n)

    # 2) 题干长度：中位数越长越像真题目，碎片越多越可疑。
    #    上限压得比第一版低——否则「更少更长的段落」会无脑占优，
    #    在缺少「本题共N小题」声明的卷子上直接把切分压成 9 段。
    s += min(med, 300) / 150.0
    s -= tiny * 8
    notes.append("中位%d字" % med)
    if tiny:
        notes.append("碎片%d" % tiny)

    # 2b) 题目长度先验：一道题通常 150–400 字，据此估计题数。
    #     这是弱先验，权重很小，只在没有声明题数时起作用。
    exp_n = len(text) / 300.0
    s -= abs(n - exp_n) * (0.15 if declared_total else 0.8)

    # 2c) 均匀度：同一份卷子的题目长度是同一量级；
    #     锚点认错东西时，段落长度会极不均匀。
    mean = sum(segs) / n
    if mean > 0:
        var = sum((x - mean) ** 2 for x in segs) / n
        cv = (var ** 0.5) / mean
        s -= min(cv, 3.0) * 2.0
        notes.append("离散%.2f" % cv)

    # 3) 覆盖度：锚点应铺满全文，挤在一处说明认错了东西
    span = anchors[-1]["pos"] - anchors[0]["pos"]
    cover = span / max(1, len(text))
    s += cover * 6
    if cover < 0.4:
        s -= 15
    notes.append("覆盖%.0f%%" % (cover * 100))

    # 4) 题数落在常识区间
    if not (4 <= n <= 60):
        s -= 25
        notes.append("题数异常")

    # 5) 结构分持平时，选信息量更大的那套（能顺带带出题型/分值的）。
    #    权重刻意压得很小，只用来打破平局，不能盖过结构证据。
    if all(a.get("type") for a in anchors):
        s += 0.3
    else:
        # 不带任何语义标签的候选（纯排版信号）只能当最后兜底。
        # D3 至今没有一次判对过——它赢的每一次都是错的，
        # 所以必须让它只在别的探测器全哑火时才可能出线。
        s -= 4.0
    if all(a.get("points") is not None for a in anchors):
        s += 0.5
        notes.append("带分值")

    return s, "，".join(notes)


def detect(text, flow, doc, declared_total):
    """跑全部探测器，返回 (最佳锚点, 方案名, 说明, 全部候选的排名表)。"""
    cands = []
    for det in DETECTORS:
        try:
            for name, anchors in det(text, flow, doc):
                anchors.sort(key=lambda a: a["pos"])
                sc, why = score(anchors, text, declared_total)
                cands.append((sc, name, anchors, why))
        except Exception as e:
            cands.append((-1e9, det.__name__, [], "探测器异常：%s" % e))
    cands.sort(key=lambda c: -c[0])
    if not cands or cands[0][0] < -1e8:
        return None, None, None, cands
    sc, name, anchors, why = cands[0]
    return anchors, name, why, cands


def confidence(anchors, text, declared_total):
    """
    代码路径够不够自信？不够就该升级到模型通道。

    刻意设计成**偏保守**：宁可多花一次模型调用，也不要把切错的结果发出去。
    切错一道题的边界，下游的解题和配图会全部跟着错，而且看起来很正常。
    """
    if not anchors:
        return False, "没有锚点"
    n = len(anchors)
    segs = [max(0, (anchors[i + 1]["pos"] if i + 1 < n else len(text)) - anchors[i]["end"])
            for i in range(n)]
    tiny = sum(1 for x in segs if x < 25)
    cover = (anchors[-1]["pos"] - anchors[0]["pos"]) / max(1, len(text))

    if tiny:
        return False, "有 %d 段题干短于 25 字，疑似切碎" % tiny
    if cover < 0.6:
        return False, "锚点只覆盖全文 %.0f%%，疑似漏切" % (cover * 100)
    if declared_total:
        if n != declared_total:
            return False, "切出 %d 题与大题声明 %d 题不符" % (n, declared_total)
        return True, "题数与声明一致、无碎片、覆盖 %.0f%%" % (cover * 100)
    # 没有声明可对账时，只能靠弱先验，标准放严一些
    exp = len(text) / 300.0
    if not (exp * 0.5 <= n <= exp * 2.0):
        return False, "切出 %d 题偏离字数先验（约 %.0f 题）" % (n, exp)
    return True, "无声明可对账，但题数、碎片、覆盖率均在合理范围"
