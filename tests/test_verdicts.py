# -*- coding: utf-8 -*-
"""
判定的值域**全项目只有一份**，而且报错文案是拼出来的、不是抄的。

`verdict` 的取值原来抄在四处：`store._VERDICTS`、`schema.sql` 的注释、
`set_teacher_verdict` 的报错文案、`list_sheets` 那句 `='wrong'` 的汇总。
加一个值只改一处，后果全是静默的 —— 老师改不出「半对」（白名单挡下来），
而列表里的「错 N 道」把 `partial` 漏掉，一张 8 道半对的卡显示「错 2 道」。

和 `modes.py` 是同一个病、同一个治法（阶段清单抄三份，两次事故都是抄漏一份）。
"""
import pytest

import verdicts


def test_五个判定值():
    assert verdicts.VERDICTS == ("right", "partial", "wrong", "blank", "unsure")


def test_判定来源五个值():
    assert verdicts.VERDICT_BY == ("teacher_score", "teacher_mark", "code",
                                   "model", "teacher")


def test_不认识的判定当场抛():
    with pytest.raises(ValueError, match="right/partial/wrong/blank/unsure"):
        verdicts.check("parital")


def test_报错文案是拼出来的不是抄的():
    """
    抄一份文案，加值的时候必然漏改它 —— 那时候报错本身会说谎，
    而看报错的人正在排查「为什么写不进去」。
    """
    try:
        verdicts.check("xxx")
    except ValueError as e:
        for v in verdicts.VERDICTS:
            assert v in str(e)
    else:
        pytest.fail("没抛")


def test_不认识的来源也当场抛():
    with pytest.raises(ValueError, match="teacher_score"):
        verdicts.check_by("teacher_scores")


def test_check回它本身好写成赋值():
    assert verdicts.check("partial") == "partial"


# ---------------------------------------------------------------- 由分数推判定
#
# 这是判定的第一优先级，排在红勾红叉前面。实测 12(3)：标准答案 AB、学生只写了
# A、老师**打了红勾**，给的却是 1分(满分2分) —— 双选题「选对但不全得一半」。
# 红勾在这里的意思是「这行判过了」，不是「全对」。

def test_满分是对():
    assert verdicts.of_score(3, 3) == "right"


def test_零分是错():
    assert verdicts.of_score(0, 3) == "wrong"


def test_一半是半对():
    assert verdicts.of_score(1, 2) == "partial"


def test_小数分数也判得出来():
    """实测 15 题是 7.5分(满分12分)"""
    assert verdicts.of_score(7.5, 12) == "partial"


def test_分数不全就推不出来():
    assert verdicts.of_score(None, 3) is None
    assert verdicts.of_score(1, None) is None


def test_满分是零的题推不出来():
    """满分 0 分的行多半是读错了，不许拿它去除"""
    assert verdicts.of_score(0, 0) is None


def test_得分超过满分算对不算半对():
    """加分题或者读串了。判成 partial 会让它进薄弱统计，那是反的"""
    assert verdicts.of_score(4, 3) == "right"


def test_进统计的只有三档():
    """blank / unsure 分子分母都不进 —— 它们不是「答错了」"""
    assert verdicts.COUNTED == ("right", "partial", "wrong")
    assert "blank" not in verdicts.COUNTED and "unsure" not in verdicts.COUNTED
