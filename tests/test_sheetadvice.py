# -*- coding: utf-8 -*-
"""
逐题建议：为什么错了、这个知识点该怎么提高。

**只给没拿满分的题生成。** 对的题不需要建议，而每多一道就多一份 token ——
便宜的筛子排在贵的前面，这是这个仓库定过的规矩。

**说不出具体的就别说。** 一句「要加强对该知识点的理解」比不说更糟：
它占着位置、看起来像有结论，实际什么都没说，而老师会因此以为看过了。
"""
import sheetadvice


ROWS = [
    {"n": 1, "verdict": "right", "answer": "D", "refAnswer": "D"},
    {"n": 6, "verdict": "wrong", "answer": "AC", "refAnswer": "BC",
     "kps": [{"name": "回旋加速器"}]},
    {"n": 1203, "verdict": "partial", "answer": "A", "refAnswer": "AB",
     "scoreGot": 1, "scoreFull": 2},
    {"n": 13, "verdict": "blank", "answer": "blank", "refAnswer": "D"},
    {"n": 14, "verdict": "unsure", "answer": "unreadable", "refAnswer": "x"},
]


def test_只挑没拿满分的题():
    assert [r["n"] for r in sheetadvice.pick(ROWS)] == [6, 1203]


def test_对的题不给建议():
    """每多一道就多一份 token，而它不需要建议"""
    assert all(r["verdict"] != "right" for r in sheetadvice.pick(ROWS))


def test_空着的题不给建议():
    """没作答就没有「为什么错」可说 —— 编一个出来就是编"""
    assert 13 not in [r["n"] for r in sheetadvice.pick(ROWS)]


def test_说不清的题不给建议():
    """连学生写了什么都没读出来，谈不上分析错因"""
    assert 14 not in [r["n"] for r in sheetadvice.pick(ROWS)]


def test_没有标准答案的题不给建议():
    """题号挂不上时没有标准答案可对，错因无从谈起"""
    rows = [{"n": 9, "verdict": "wrong", "answer": "x", "refAnswer": None}]
    assert sheetadvice.pick(rows) == []


def test_一道都不用给时不发调用():
    """全对的卡不该白花一次调用"""
    assert sheetadvice.pick([ROWS[0]]) == []


# ---------------------------------------------------------------- 组材料

def test_材料里有学生写的和标准答案():
    p = sheetadvice.payload_for([ROWS[1]])
    assert "AC" in p and "BC" in p and "第 6 题" in p


def test_材料里带上知识点():
    """建议要落到这个知识点上，不给它模型只能泛泛而谈"""
    assert "回旋加速器" in sheetadvice.payload_for([ROWS[1]])


def test_有官方解答就带上():
    """官方解答是这条链上最可信的材料，比模型自己重解一遍强"""
    r = dict(ROWS[1], refSolution="由 qvB=mv²/r 得…")
    assert "qvB" in sheetadvice.payload_for([r])


def test_半对的题要说明是半对():
    """「选对但不全」和「全错」的错因完全不同，不说的话模型会当成全错分析"""
    p = sheetadvice.payload_for([ROWS[2]])
    assert "1" in p and "2" in p


# ---------------------------------------------------------------- 收结果

def test_按题号收回来():
    got = sheetadvice.collect([{"n": "6", "why": "选了 A，漏了 B",
                                "fix": "把洛伦兹力方向单独练五道"}])
    assert got == {6: {"why": "选了 A，漏了 B", "fix": "把洛伦兹力方向单独练五道"}}


def test_小问题号也收得回来():
    got = sheetadvice.collect([{"n": "12(3)", "why": "只选了 A，标准答案是 AB",
                                "fix": "双选题先把四个选项逐个判一遍再落笔"}])
    assert 1203 in got


def test_空话要丢掉():
    """
    「加强理解」「多做练习」这种放到任何一道题上都成立的话 = 没说。
    它占着位置、看起来像有结论，而老师会因此以为看过了。
    """
    got = sheetadvice.collect([{"n": "6", "why": "对该知识点理解不到位",
                                "fix": "加强对该知识点的理解和练习"}])
    assert got == {}


def test_具体的留下():
    got = sheetadvice.collect([{"n": "6", "why": "选了 A（洛伦兹力方向judged反了），漏了 B",
                                "fix": "把左手定则在「负电荷」那一档单独练五道"}])
    assert 6 in got


def test_缺一半也留着另一半():
    """只说得出错因、说不出办法，也比两样都不说强"""
    got = sheetadvice.collect([{"n": "6", "why": "少选了 B，漏了动能定理那一步",
                                "fix": ""}])
    assert got[6]["why"] and not got[6].get("fix")


def test_粗心马虎这类一律当空话():
    """
    「粗心」是替学生编心理活动 —— 我们只有他写下来的东西，看不见他怎么想的。
    而且它对任何一道错题都成立。
    """
    got = sheetadvice.collect([{"n": "6", "why": "粗心，把 B 看成了 D", "fix": ""}])
    assert got == {}


def test_只有具体名词也算说了话():
    """不非得有数字 —— 点名一个具体的物理概念同样是可操作的"""
    got = sheetadvice.collect([{"n": "6", "why": "左手定则的方向judged反了",
                                "fix": ""}])
    assert 6 in got


def test_认不出的题号丢掉():
    assert sheetadvice.collect([{"n": None, "why": "x", "fix": "y"}]) == {}
