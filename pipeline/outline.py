#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
outline.py —— 阶段③b 整卷目录：短标题与短答案

    python pipeline/outline.py <卷名> [--force]

产出两样东西，都是给**导航**用的，不是给阅读用的：

  · `label`        2-5 字，点出这道题讲的是什么（「火星车」「简谐横波」「双棒导轨」）
  · `short_answer` 压到一行的答案（`D` / `92/56` / `0.4 m`）

为什么单独一步、而不是让 ③ 顺带产出
----------------------------------
③ 是逐题独立解的，一题一次调用。让它顺带写标题有两个坏处：已经解过的
22 卷全都补不上（要 `--force` 重跑，一卷半小时），而且每题各写各的，
同一卷里「小火车」和「木块在传送带上」这种粗细不一的标题会混在一起。

这里是**整卷一次调用**：模型同时看得见 16 道题，能把标题的粒度对齐；
已经解过的卷子跑一次就补全。代价是多一个步骤、多一次调用。

为什么短答案不能用代码截
------------------------
`answer` 那一栏是给人读的完整版 —— 第15题是「(1) α=30°，U_MN=3mv₀²/2q；
(2) N点横坐标为…；(3) B₁=…」一长串三问。截前 20 个字得到的是
「(1) α=30°，U_MN=3mv…」，既不完整也不好看。多空题更没法切：
「小于 / 等于 / 小于」这种要按空分组，分隔符在原文里根本不统一。

缺了不编
--------
模型没给某题的标题就留 NULL，页面上目录那一行显示题号和答案，不显示标题。
比编一个「某同学」这种从题干头部抽出来的假标题强。

不是只在 ③ 之后跑一次
---------------------
「答案速览」和左边的目录读的就是这一步的产出。它原来只排在 ③ 全解完之后，
于是 ③ 跑的那二三十分钟里，**已经解出来的题在速览里也全写着「尚未生成」**——
明明解完好几道了。现在 `solve.py` 每解完几题就回头调一次 `refresh()`：
一次调用几十秒、几分钱，换的是这段时间里速览一直在长。
"""
import argparse, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

for _l in (open(os.path.join(ROOT, ".env"), encoding="utf-8")
           if os.path.exists(os.path.join(ROOT, ".env")) else []):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# 纯文本的压缩任务，DeepSeek 够用而且便宜。它没有视觉通道，但这一步不看图 ——
# 题干文字和 ③ 给的答案已经足够写出标题。
KEY = os.environ.get("EXAM_OUTLINE_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
BASE = os.environ.get("EXAM_OUTLINE_BASE") or os.environ.get("DEEPSEEK_BASE_URL",
                                                             "https://api.deepseek.com/v1")
MODEL = os.environ.get("EXAM_OUTLINE_MODEL") or os.environ.get("DEEPSEEK_MODEL",
                                                               "deepseek-v4-pro")

PROMPT = """给一份物理试卷做目录。下面是整卷每道题的题号、题型、题干和标准答案。

对**每一道题**给出两样东西：

1. `label`：2-5 个汉字，点出这道题的**物理情境或对象**，让人扫一眼就知道是哪道题。
   好的：火星车、简谐横波、双棒导轨、拉格朗日点、气体循环、质谱仪、离心测速器
   坏的：某同学、如图所示、一道题、物理题、运动学（太泛，说的是知识点不是情境）

2. `short`：把答案压到**一行**，用于速览表格。
   · 选择题 → 只写选项字母，如 `D`、`BD`
   · 多空填空 → 各空用 ` / ` 隔开，如 `小于 / 等于 / 小于`、`92 / 56`
   · 计算/解答 → 只写最终结果，带单位，如 `0.4 m`、`40 Hz`、`(√3+1)v₁`；
     多问的题各问用 ` · ` 隔开，写不下就只写最关键的一问
   · 答案本身缺失或看不懂 → 给空字符串 ""，**不要编**

只输出 JSON 数组，不要代码块围栏、不要解释：
[{"n": 1, "label": "火星车", "short": "D"}, ...]

必须覆盖下面出现的每一个题号，一个都不能少。
"""


def payload_for(paper, sols):
    parts = []
    for q in paper["questions"]:
        stem = (q.get("stem_latex") or q.get("stem") or "").strip()
        stem = re.sub(r"\s+", " ", stem)[:220]
        bits = ["【第%d题】%s" % (q["n"], q.get("type") or "")]
        bits.append("题干：" + stem)
        s = sols.get(q["n"])
        if s and s.get("answer"):
            bits.append("答案：" + re.sub(r"\s+", " ", s["answer"])[:260])
        else:
            bits.append("答案：（尚未解出）")
        parts.append("\n".join(bits))
    return "\n\n".join(parts)


def ask(payload, tries=3):
    body = json.dumps({"model": MODEL, "max_tokens": 8000, "temperature": 0,
                       "messages": [{"role": "user", "content": payload}]}).encode()
    last = None
    for k in range(tries):
        try:
            r = urllib.request.Request(BASE + "/chat/completions", body,
                                       {"Authorization": "Bearer " + KEY,
                                        "Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(r, timeout=300).read())
            txt = d["choices"][0]["message"]["content"]
            m = re.search(r"\[.*\]", txt, re.S)
            if not m:
                raise ValueError("没有返回 JSON 数组：" + txt[:160])
            return json.loads(m.group(0))
        except Exception as e:
            last = e
            if k == tries - 1:
                raise
    raise last


def refresh(name, force=False, verbose=True):
    """
    跑一次 ③b，返回写了几题（-1 = 没跑成，跳过时为 0）。

    ③ 中途也会调它（见模块开头），所以**没解出来的题不是错误状态**：
    payload 里那些题写的是「答案：（尚未解出）」，模型照样能从题干写出 label，
    只是 short 会是空的。等它们解出来，下一次刷新再补上。
    """
    log = print if verbose else (lambda *a, **k: None)
    paper = store.get_paper(name)
    if not paper:
        log("库里没有「%s」" % name)
        return -1
    if not KEY:
        log("没有 DEEPSEEK_API_KEY（或 EXAM_OUTLINE_KEY），跳过 ③b")
        return -1
    if not store.outline_missing(name) and not force:
        log("── 目录 %s：%d 题都有标题与短答案，跳过" % (name, len(paper["questions"])))
        return 0

    sols = store.paper_solutions(name)
    rows = ask(PROMPT + "\n\n" + payload_for(paper, sols))

    by_n = {q["n"]: q["id"] for q in paper["questions"]}
    got = skipped = 0
    for r in rows:
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if n not in by_n:
            continue
        label = (r.get("label") or "").strip()[:12] or None
        short = (r.get("short") or "").strip()[:60] or None
        if not label and not short:
            skipped += 1
            continue
        store.put_outline(by_n[n], label, short)
        got += 1
        log("   第%2d题 %-8s %s" % (n, label or "（无标题）", short or ""))

    miss = [q["n"] for q in paper["questions"] if q["n"] not in {int(r["n"]) for r in rows
                                                                if str(r.get("n", "")).isdigit()}]
    log("── 目录 %s（%s）" % (name, MODEL))
    log("   写入 %d 题，模型给了空值 %d 题" % (got, skipped))
    if miss:
        # 缺了就说缺了。页面上这些题的目录行只有题号，没有标题 —— 不拿占位内容充数
        log("   ⚠ 模型漏了 %d 题：%s（这些题目录里只显示题号）"
            % (len(miss), "、".join("第%d题" % n for n in miss)))
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--force", action="store_true", help="已经有标题的题也重写")
    a = ap.parse_args()
    name = os.path.basename(os.path.normpath(a.paper))
    return 1 if refresh(name, a.force) < 0 else 0


if __name__ == "__main__":
    sys.exit(main())
