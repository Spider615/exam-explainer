# -*- coding: utf-8 -*-
"""
③c 送给模型的那段材料，两条链不一样。

2026-08-09 端到端实跑抓到的：答题卡那条链送过去的是 26 段只有题号的空白
（没有题干、没有 ③ 的解法），模型挂上 0 题。而它手上明明有标准答案和
官方解答过程 —— 只是 payload_for 没读。
"""
import kpmark


def _q(n, **kw):
    q = {"n": n, "type": "选择题", "stem": "", "stem_latex": None,
         "ref_answer": None, "ref_solution": None}
    q.update(kw)
    return q


def _sol(**kw):
    s = {"steps": [], "answer": ""}
    s.update(kw)
    return s


# ---------------------------------------------------------------- 解析试卷不许变
PDF = {"sourceKind": "pdf",
       "questions": [_q(1, stem="一个物块沿斜面下滑", ref_answer="D")]}


def test_解析试卷那条链一个字不变():
    """
    它现在送的是「题干 + ③ 的解法」。ref_answer 在 pdf 卷上也有（②d 抽的），
    但**不许**因为这次改动被塞进去 —— 那会悄悄改掉解析试卷的 ③c 输入，
    而这一轮的第一条规矩就是那条链一个字不动
    """
    got = kpmark.payload_for(PDF, {1: _sol(steps=["受力分析", "动能定理"])})
    assert "题干：一个物块沿斜面下滑" in got
    assert "解法：受力分析 动能定理" in got
    assert "D" not in got, "标准答案不该出现在解析试卷那条链的输入里"


def test_解析试卷没解出来时照旧那句话():
    got = kpmark.payload_for(PDF, {})
    assert "解法：（尚未解出，只能看题干判断）" in got


# ---------------------------------------------------------------- 答题卡这条链
SHEET = {"sourceKind": "answers_only", "questions": [
    _q(11, type="", ref_answer="2BIL / MP", ref_solution="由安培力公式 F=BIL，导轨两侧各一根"),
    _q(1, type="", ref_answer="D"),
]}


def test_答题卡把标准答案和官方解答送进去():
    got = kpmark.payload_for(SHEET, {})
    assert "2BIL / MP" in got
    assert "由安培力公式" in got


def test_只有答案没有过程的题也要送进去():
    """
    参考答案的版式就是只有大题给详解。18/26 题只有一个孤零零的答案 ——
    少送这一部分的话，这些题会跟实测那次一样一个都挂不上
    """
    got = kpmark.payload_for(SHEET, {})
    assert "【第1题】" in got and "D" in got


def test_答题卡不再送出一段空白():
    """实测那次送过去的是「题干：\\n解法：（尚未解出）」，模型什么都挂不上"""
    got = kpmark.payload_for(SHEET, {})
    assert "尚未解出" not in got


def test_题干有了也要一起送():
    """
    Ⓔ 读题干将来会把 stem 填上。设计文档：「两样有一样就能挂」——
    有了题干不该把官方解答挤掉，两样都该在
    """
    p = {"sourceKind": "answers_only",
         "questions": [_q(11, stem="如图，两平行导轨…",
                          ref_answer="2BIL / MP", ref_solution="由安培力公式")]}
    got = kpmark.payload_for(p, {})
    assert "如图，两平行导轨" in got and "由安培力公式" in got
