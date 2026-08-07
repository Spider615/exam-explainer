# -*- coding: utf-8 -*-
import refread


# ---------------------------------------------------------------- 题号
def test_题号带小问():
    assert refread.qnum("11") == 11
    assert refread.qnum("12(1)") == 1201
    assert refread.qnum("12（1）") == 1201, "全角括号也要认"
    assert refread.qnum(" 13 (4) ") == 1304
    assert refread.qnum(11) == 11


def test_认不出的题号回None():
    assert refread.qnum("十一") is None
    assert refread.qnum("") is None
    assert refread.qnum(None) is None
    assert refread.qnum("abc") is None
    assert refread.qnum("12(1)(2)") is None, "编不出来的形式不许硬解"


def test_题号能还原成显示形式():
    assert refread.show_qnum(11) == "11"
    assert refread.show_qnum(1201) == "12(1)"
    assert refread.show_qnum(1304) == "13(4)"


def test_排序天然正确():
    ns = [refread.qnum(x) for x in ["9", "12(1)", "11", "12(2)", "13(1)"]]
    assert sorted(ns) == [9, 11, 1201, 1202, 1301]


# ---------------------------------------------------------------- keep
def test_正常一条():
    got = refread.keep([{"n": "11", "answer": "2BIL / MP",
                         "solution": "由安培力公式 F=BIL"}])
    assert got == [{"n": 11, "ref_answer": "2BIL / MP",
                    "ref_solution": "由安培力公式 F=BIL"}]


def test_没有标准答案的整条丢掉():
    """一道错的标准答案会让所有做对这题的学生被判错，凭空造出一个假的
    薄弱知识点。宁可少一道题"""
    assert refread.keep([{"n": "11", "answer": "", "solution": "有过程"}]) == []
    assert refread.keep([{"n": "11", "solution": "有过程"}]) == []


def test_没有解答过程仍然收():
    """选择题的参考答案就只有一个字母，没有过程。实测 1-13 题全是这样，
    这是常态不是缺陷"""
    got = refread.keep([{"n": "1", "answer": "D"}])
    assert got == [{"n": 1, "ref_answer": "D", "ref_solution": None}]


def test_题号认不出的整条丢掉():
    assert refread.keep([{"n": None, "answer": "D"}]) == []
    assert refread.keep([{"n": "十一", "answer": "D"}]) == []


def test_跨页的解答要拼接不是覆盖():
    got = refread.keep([{"n": "16", "answer": "见解析", "solution": "第一段"},
                        {"n": "16", "answer": "见解析", "solution": "第二段"}])
    assert len(got) == 1
    assert got[0]["ref_solution"] == "第一段 第二段"


def test_跨页时先有过程后没有也不丢():
    got = refread.keep([{"n": "16", "answer": "见解析", "solution": "第一段"},
                        {"n": "16", "answer": "见解析"}])
    assert got[0]["ref_solution"] == "第一段"


def test_按题号排序():
    got = refread.keep([{"n": "13(1)", "answer": "BC"}, {"n": "9", "answer": "不变"},
                        {"n": "12(2)", "answer": "U1/n1=U2/n2"}])
    assert [g["n"] for g in got] == [9, 1202, 1301]


def test_烂数据不炸():
    got = refread.keep([None, "串", {"answer": "D"}, {"n": "1"},
                        {"n": "2", "answer": "C"}])
    assert [g["n"] for g in got] == [2]


def test_整个不是数组也不炸():
    assert refread.keep(None) == []
    assert refread.keep({"n": 1}) == []


def test_答案原样保留只去首尾空白():
    got = refread.keep([{"n": "1", "answer": "  8×10^-12  "}])
    assert got[0]["ref_answer"] == "8×10^-12"


# ---------------------------------------------------------------- 真材料回归
def test_老师那份材料第一页的真值():
    """这 20 条是 2026-08-08 拿老师给的参考答案实测出来、并人工逐题核对过的。
    keep 的过滤规则改坏了，这条会红"""
    rows = [
        {"n": "1", "answer": "D"}, {"n": "2", "answer": "C"},
        {"n": "3", "answer": "C"}, {"n": "4", "answer": "B"},
        {"n": "5", "answer": "AC"}, {"n": "6", "answer": "BC"},
        {"n": "7", "answer": "BC"}, {"n": "8", "answer": "AC"},
        {"n": "9", "answer": "不变 / 17190"}, {"n": "10", "answer": "调制 / 0.047"},
        {"n": "11", "answer": "2BIL / MP"},
        {"n": "12(1)", "answer": "170 / A"}, {"n": "12(2)", "answer": "U₁/n₁ = U₂/n₂"},
        {"n": "12(3)", "answer": "AB"},
        {"n": "13(1)", "answer": "BC"}, {"n": "13(2)", "answer": "8×10^-12"},
        {"n": "13(3)", "answer": "6.3×10^-10"}, {"n": "13(4)", "answer": "D"},
        {"n": "14(1)", "answer": "p₁ = 1.2×10^5 Pa", "solution": "物块静止时，受力平衡"},
        {"n": "14(2)", "answer": "h₁ = 50 cm", "solution": "等温变化，由玻意耳定律"},
    ]
    got = refread.keep(rows)
    assert len(got) == 20, "一条都不许丢"
    by_n = {g["n"]: g for g in got}
    assert by_n[11]["ref_answer"] == "2BIL / MP"
    assert by_n[1201]["ref_answer"] == "170 / A"
    assert by_n[1302]["ref_answer"] == "8×10^-12"
    assert by_n[1401]["ref_solution"].startswith("物块静止")
    assert by_n[1]["ref_solution"] is None, "选择题没有解答过程"


# ---------------------------------------------------------------- 跨页上下文
def test_主题号提取():
    assert refread.main_of(11) == 11
    assert refread.main_of(1201) == 12
    assert refread.main_of(1604) == 16


def test_上一页读到第几题():
    """参考答案常常从半道题开始翻页，页首只剩一个光秃秃的「(3)」。
    实测不给上下文时 14(3)、15(3)、16(3) 三条全丢了"""
    assert refread.last_main_of([{"n": "13(4)"}, {"n": "14(1)"}, {"n": "14(2)"}]) == 14


def test_取最大而不是最后一条():
    """模型的输出顺序不保证与版面一致"""
    assert refread.last_main_of([{"n": "16(2)"}, {"n": "15(1)"}]) == 16


def test_一条都认不出就没有上下文():
    assert refread.last_main_of([]) is None
    assert refread.last_main_of([{"n": "十一"}, None, "串"]) is None
