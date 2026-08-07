#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refans.py —— 阶段②c 标准答案抽取

    python pipeline/refans.py <卷名>

从卷子自带的「参考答案」段落里，按题号切出每道题的标准答案。

纯代码，不调模型
----------------
这一步的产出会拿去判学生的对错。模型抽错一道，做对这道题的学生就被判错，
凭空造出一个假的薄弱知识点，而页面上一切看起来都正常。所以这里只做
**不会静默出错**的事：找得到答案区就按题号切，找不到就明说找不到。

抽不到不是失败
--------------
库里 22 份高考真题**一份都没有参考答案段落** —— 真题 PDF 本来就不带答案。
所以「一题都没抽到」是这类卷子的正常结果，记 ref_answer_src='none'，
下游一律判 unsure（不算学生错）。

一条都不给，也不给错的
----------------------
答案区里的题号必须递增。乱序多半意味着把正文当成了答案区，这时宁可整片
放弃 —— 错位的答案安到题上，比没有答案坏得多。
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

# 答案区的起点。标题词必须**独占一行**（后面只允许跟冒号和空白），否则题干里的
# 「答案保留两位有效数字」这类写法会被当成答案区起点 —— 那是 22 卷语料里
# 「答案」二字唯一出现的地方。宁可漏认一种版式，也不能误认正文。
ZONE_RE = re.compile(r"(?:^|\n)[ \t]*(参考答案|答案与解析|参考解答|答案速查|"
                     r"试题答案|答案详解)[ \t]*[:：]?[ \t]*(?=\n|$)")

# 题号的几种写法：`1.` `1．` `1、` `【1】` `第1题`
NUM_RE = re.compile(r"(?:^|\n)[ \t]*(?:第[ \t]*(\d{1,2})[ \t]*题|【[ \t]*(\d{1,2})[ \t]*】|"
                    r"(\d{1,2})[ \t]*[.．、])[ \t]*")


def find_zone(text):
    """参考答案区的起始下标（指向标题词本身）。找不到回 None。"""
    m = ZONE_RE.search(text)
    return m.start(1) if m else None


def split_answers(zone_text, numbers):
    """
    把答案区按题号切成 {题号: 答案原文}。

    `numbers` 是这份卷子真实的题号列表 —— 只认里面有的。**边界用的是下一个
    题号标记（不管它认不认识）**：卷子里没有的题号照样是一条分界线，否则
    第 1 题的答案会把后面那段串号的内容一起吞进来。

    认出来的题号必须**严格递增**，否则整片放弃（见模块开头）。
    """
    valid = set(numbers)
    hits = []
    for m in NUM_RE.finditer(zone_text):
        n = int(next(g for g in m.groups() if g))
        hits.append((n, m.start(), m.end()))
    picked = [h[0] for h in hits if h[0] in valid]
    if not picked:
        return {}
    if any(b <= a for a, b in zip(picked, picked[1:])):
        return {}          # 题号没有严格递增：这多半不是答案区

    out = {}
    for i, (n, _s, body) in enumerate(hits):
        if n not in valid:
            continue
        end = hits[i + 1][1] if i + 1 < len(hits) else len(zone_text)
        ans = re.sub(r"\s+", " ", zone_text[body:end]).strip()
        if ans:
            out[n] = ans
    return out


def extract(doc_text, numbers):
    """整卷全文 → {题号: 标准答案}。没有答案区就回空字典。"""
    i = find_zone(doc_text)
    return split_answers(doc_text[i:], numbers) if i is not None else {}


def doc_text(name):
    """读构建产物里的整卷文本。没有 doc.json 就回 None。"""
    p = os.path.join(ROOT, "work", name, "doc.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    return "\n".join(pg["text"] for pg in d["pages"])


def run(name, verbose=True):
    """跑一次 ②c，返回 (抽到几题, 总题数)。"""
    log = print if verbose else (lambda *a, **k: None)
    paper = store.get_paper(name)
    if not paper:
        log("库里没有「%s」" % name)
        return (0, 0)
    qs = paper["questions"]
    txt = doc_text(name)
    if txt is None:
        log("── 标准答案 %s：没有 doc.json（构建产物已清理），跳过" % name)
        return (0, len(qs))

    got = extract(txt, [q["n"] for q in qs])
    for q in qs:
        if q["n"] in got:
            store.put_ref_answer(q["id"], got[q["n"]][:400], "paper")
        else:
            # 抽不到也要写一行。「抽不到」和「还没跑过 ②c」是两句不同的话
            store.put_ref_answer(q["id"], None, "none")
    log("── 标准答案 %s：抽到 %d / %d 题" % (name, len(got), len(qs)))
    if not got:
        log("   这份卷子里没有参考答案段落。这些题在判对错时一律记 unsure，"
            "不算学生错 —— 是卷子没给答案，不是学生的问题。")
    return (len(got), len(qs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    a = ap.parse_args()
    run(os.path.basename(os.path.normpath(a.paper)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
