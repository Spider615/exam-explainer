# -*- coding: utf-8 -*-
"""
Ⓒ 判定：优先看分数、题号按**大题集合**绑、互校只报不改。

题号绑定那一段是这一轮最隐蔽的一条
----------------------------------
按 `n = 主题号*100 + 小问号`：

| | 答题卡印的 | 算出来的 n | 参考答案 | 算出来的 n |
|---|---|---|---|---|
| 13 题 | (1)(2)**(4)(5)** | 1301 1302 **1304 1305** | (1)(2)(3)(4) | 1301 1302 1303 1304 |

`1301`、`1302`、**`1304`** 三条都**精确等于**一个已存在的题号。
设计里那道「不许猜一个最近的题号安上去」的防线**拦不住它** ——
这是精确相等，不是猜。而卡上的 (4) 实际对应答案的 (3)（按满分序列 2/1/2/1 核实过）。

后果：页面「你写的 X / 标准答案 Y」那一栏拿的是**另一小问**的答案；
互校要么冒一条查无实据的不一致、要么两边碰巧一样而全线沉默；
步三的丢分还会算到错的知识点上。
"""
import sheetverdict


KNOWN = [1301, 1302, 1303, 1304]          # 参考答案：13(1)(2)(3)(4)


# ---------------------------------------------------------------- 题号绑定

def test_集合相等就逐条绑():
    rows, warn = sheetverdict.bind([{"n": n} for n in (1301, 1302, 1303, 1304)],
                                   KNOWN)
    assert [r["bind"] for r in rows] == [1301, 1302, 1303, 1304]
    assert warn == []


def test_集合不等时整道大题一条都不绑():
    """
    **本文件的主角。** 1301/1302/1304 三条精确命中已有题号，逐条绑的话
    这三条全绑到错的题上，只有 1305 挂不上 —— 而页面只会说「有 1 条挂不上」。
    """
    rows, warn = sheetverdict.bind([{"n": n} for n in (1301, 1302, 1304, 1305)],
                                   KNOWN)
    assert all(r["bind"] is None for r in rows), \
        "编号错位时，整道大题一条都不许绑"
    assert len(warn) == 1 and warn[0]["main"] == 13
    assert warn[0]["kind"] == "mismatch"


def test_对不上的告警要把两边都说出来():
    """只说「对不上」，老师不知道该去看什么"""
    _, warn = sheetverdict.bind([{"n": n} for n in (1301, 1302, 1304, 1305)],
                                KNOWN)
    why = warn[0]["why"]
    assert "(1)(2)(4)(5)" in why and "(1)(2)(3)(4)" in why


def test_别的大题不受牵连():
    rows, _ = sheetverdict.bind([{"n": 1201}, {"n": 1301}, {"n": 1305}],
                                [1201, 1301, 1302])
    got = {r["n"]: r["bind"] for r in rows}
    assert got[1201] == 1201, "12 题自己是对得上的，不该被 13 题连累"
    assert got[1301] is None and got[1305] is None


def test_整数题号照常绑():
    rows, warn = sheetverdict.bind([{"n": 9}, {"n": 11}], [9, 11])
    assert [r["bind"] for r in rows] == [9, 11] and warn == []


def test_卷子里压根没有的大题单独报():
    """学生多写了一道，或者题号读错了。挂不上就是挂不上"""
    rows, warn = sheetverdict.bind([{"n": 99}], [9, 11])
    assert rows[0]["bind"] is None
    assert warn and warn[0]["main"] == 99


def test_少读一个小问时能绑的还是绑上():
    """
    答题卡上只有 (1)(2)(3)，参考答案有 (1)(2)(3)(4)。

    **这一条初版判成「整题不绑」，被 2026-08-10 的端到端实跑推翻了。**
    当时的理由是「少一条就说明两边编号体系未必是一回事」—— 听着像那么回事，
    实跑出来的代价却是：14/15/16 三道大题共 39 分全都挂不上标准答案和知识点，
    而那恰恰是诊断最该覆盖的部分。

    真正的判据是**方向**：卡上的题号**都在**答案里（真子集）说明只是漏读了，
    能绑的绑上、少的点名报出来；卡上**多出**一个答案里没有的，才说明编号体系
    不是一回事（见下面 13 题那条）。
    """
    rows, warn = sheetverdict.bind([{"n": n} for n in (1301, 1302, 1303)], KNOWN)
    assert [r["bind"] for r in rows] == [1301, 1302, 1303]
    assert len(warn) == 1 and warn[0]["kind"] == "missing"


# ---------------------------------------------------------------- 判定

def test_满分是对():
    assert sheetverdict.decide({"got": 3, "full": 3})[:2] == ("right", "teacher_score")


def test_零分是错():
    assert sheetverdict.decide({"got": 0, "full": 3, "answer": "BIL"})[:2] \
        == ("wrong", "teacher_score")


def test_一半是半对():
    """标准答案 AB、学生写 A、老师打勾给 1分(满分2分)"""
    assert sheetverdict.decide({"got": 1, "full": 2})[:2] == ("partial", "teacher_score")


def test_分数优先于勾叉():
    """
    12(3) 老师打的是**红勾**，给的是 1分(满分2分)。只看勾叉会判成 right ——
    那道题会被记成掌握了，而它恰恰是这轮探针推翻原设计的那个例子。
    """
    got = sheetverdict.decide({"got": 1, "full": 2, "mark": "right"})
    assert got[:2] == ("partial", "teacher_score")


def test_读不到分数就退回勾叉():
    assert sheetverdict.decide({"mark": "right"})[:2] == ("right", "teacher_mark")


def test_勾上带叉是半对():
    assert sheetverdict.decide({"mark": "half"})[:2] == ("partial", "teacher_mark")


def test_勾叉也没有就是说不清():
    assert sheetverdict.decide({})[0] == "unsure"
    assert sheetverdict.decide({"mark": "none"})[0] == "unsure"


def test_作答读不出来一律说不清不许说空白():
    """
    「没读出来」被渲染成「学生没作答」是最坏的一种：老师读到「这孩子没写」，
    而事实是「读不出来」；这些题还会从薄弱统计里整个消失（blank 分子分母都不进），
    而错题正是这个功能唯一的产出。
    """
    assert sheetverdict.decide({"answer": "unreadable"})[0] == "unsure"
    assert sheetverdict.decide({"answer": "unreadable", "mark": "none"})[0] == "unsure"


def test_读不出来但有分数时以分数为准():
    """分数是老师给的，比「这一栏我没转写出来」可信得多"""
    assert sheetverdict.decide({"answer": "unreadable", "got": 0, "full": 2})[0] \
        == "wrong"


def test_明确空着才是空白():
    assert sheetverdict.decide({"answer": "blank", "got": 0, "full": 2})[0] == "blank"


def test_判定要说得出为什么():
    """页面上 verdict_by 要显示，而理由决定老师信不信它"""
    assert "1" in sheetverdict.decide({"got": 1, "full": 2})[2]


# ---------------------------------------------------------------- 互校

def test_系统和老师一致就不报():
    assert sheetverdict.crosscheck({"answer": "AC", "verdict": "wrong"}, "BC") is None


def test_不一致要报():
    got = sheetverdict.crosscheck({"answer": "BC", "verdict": "wrong"}, "BC")
    assert got and "老师" in got


def test_半对不算不一致():
    """
    `grade.judge("A", "AB")` 回 wrong，老师给的是 partial —— 这不是矛盾，
    是代码档判等本来就没有「部分对」这一档。算成异常的话，每道双选半对题
    都会冒一条假警告，真正的异常会被淹掉。
    """
    assert sheetverdict.crosscheck({"answer": "A", "verdict": "partial"}, "AB") is None


def test_判不了不算异常():
    """`grade.judge` 回 None 是常态（长解答题）"""
    assert sheetverdict.crosscheck(
        {"answer": "由动量定理得…", "verdict": "partial"}, "3mg") is None


def test_说不清的题不互校():
    """两边有一边说不清，比出来的结论没有意义"""
    assert sheetverdict.crosscheck({"answer": "AC", "verdict": "unsure"}, "BC") is None


def test_没有标准答案就不互校():
    assert sheetverdict.crosscheck({"answer": "AC", "verdict": "wrong"}, None) is None


def test_老师红笔写的和参考答案对不上也要报():
    """
    实测题 6 老师红笔写了 BC、题 8 写了 AC。这是白捡的第三份对照：
    它跟参考答案对不上，说明 Ⓐ 那一栏抽错了。同样只报，不改数据。
    """
    got = sheetverdict.crosscheck({"answer": "AC", "verdict": "wrong",
                                   "red": "BD"}, "BC")
    assert got and "红笔" in got


def test_老师红笔写的和参考答案一致就不报():
    assert sheetverdict.crosscheck({"answer": "AC", "verdict": "wrong",
                                    "red": "BC"}, "BC") is None


# ---------------------------------------------------------------- 粒度不同 ≠ 编号错位
#
# 2026-08-10 端到端实跑逼出来的。第一版规则「小问集合不相等 → 整题不绑」一刀切，
# 把三种完全不同的情况判成了同一种：
#
#   13 题  卡上 (1)(2)(4)(5)、答案 (1)(2)(3)(4)  → **编号错位**，该整题不绑
#   14 题  卡上是**一整块**、答案拆成 (1)(2)(3)  → **粒度不同**，该绑到整题
#   16 题  卡上 (1)(2)、答案 (1)(2)(3)          → **漏读一条**，能绑的该绑上
#
# 一刀切的代价是实打实的：14/15/16 三道大题共 39 分全都挂不上标准答案和知识点，
# 而那恰恰是诊断最该覆盖的部分。

def test_答题卡是整题而答案拆小问时绑到整题():
    """
    大题的答题卡上就是一整块（学生自由书写，没有分小问的答题线），
    参考答案却拆成 (1)(2)(3)。这是**粒度不同**，不是编号错位。
    """
    rows, warn = sheetverdict.bind([{"n": 14}], [1401, 1402, 1403])
    assert rows[0]["bind"] is None, "没有哪一个小问单独对应它"
    assert rows[0]["bindMain"] == 14, "但它整题对得上，标准答案和知识点该按整题给"
    assert not any(w.get("kind") == "mismatch" for w in warn), \
        "粒度不同不是错位，不该报成「编号对不上」"


def test_卡上少读了一条时能绑的绑上():
    """
    卡上 (1)(2)、答案 (1)(2)(3) —— 卡上这些**都在**答案里，是真子集，
    说明只是第 3 条没读到。前两条绑上是安全的。
    """
    rows, warn = sheetverdict.bind([{"n": 1601}, {"n": 1602}],
                                   [1601, 1602, 1603])
    assert [r["bind"] for r in rows] == [1601, 1602]
    assert any(w["main"] == 16 and "16(3)" in w["why"] for w in warn), \
        "少了哪一条要点名说出来"


def test_卡上多出一个答案里没有的就整题不绑():
    """
    13 题：卡上 (1)(2)(4)(5)，答案 (1)(2)(3)(4)。**(5) 不在答案里** ——
    这说明两边的编号体系不是一回事，那么 1301/1302/1304 的「精确相等」
    也不能信（卡上的 (4) 其实是答案的 (3)）。
    """
    rows, warn = sheetverdict.bind(
        [{"n": n} for n in (1301, 1302, 1304, 1305)], [1301, 1302, 1303, 1304])
    assert all(r["bind"] is None for r in rows)
    assert all(r["bindMain"] is None for r in rows)
    assert any(w["main"] == 13 and w.get("kind") == "mismatch" for w in warn)


def test_错位和漏读的告警要分得出来():
    """两句话该说的下一步不一样：一个是「请你认」，一个是「重传更清楚的图」"""
    _, a = sheetverdict.bind([{"n": n} for n in (1301, 1302, 1304, 1305)],
                             [1301, 1302, 1303, 1304])
    _, b = sheetverdict.bind([{"n": 1601}, {"n": 1602}], [1601, 1602, 1603])
    assert a[0]["kind"] == "mismatch" and b[0]["kind"] == "missing"


def test_整题和小问同时出现时按小问算():
    """卡上既有 14 又有 14(1)，那不是粒度问题，是读串了"""
    rows, warn = sheetverdict.bind([{"n": 14}, {"n": 1401}], [1401, 1402, 1403])
    assert all(r["bind"] is None for r in rows)
    assert any(w.get("kind") == "mismatch" for w in warn)


def test_单题不受粒度规则影响():
    """第 9 题两边都是整题，正常绑"""
    rows, warn = sheetverdict.bind([{"n": 9}], [9, 11])
    assert rows[0]["bind"] == 9 and rows[0]["bindMain"] is None and warn == []
