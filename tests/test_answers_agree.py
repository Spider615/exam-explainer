# -*- coding: utf-8 -*-
import api


def test_选择题字母():
    assert api.answers_agree("BD", "bd") is True
    assert api.answers_agree("B D", "BD") is True
    assert api.answers_agree("BD", "DB") is True      # 集合相等
    assert api.answers_agree("BD", "BC") is False


def test_全角半角和标点():
    assert api.answers_agree("０．４ m", "0.4 m") is True
    assert api.answers_agree("0.4 m。", "0.4 m") is True


def test_比不了就回None():
    # **不许把「比不了」压成 False。** 压成 False 就是在页面上说
    # 「AI 和卷子对不上」，而事实是其中一边根本没有
    assert api.answers_agree(None, "BD") is None
    assert api.answers_agree("BD", None) is None
    assert api.answers_agree("", "BD") is None
    assert api.answers_agree("  ", "  ") is None


def test_分数与小数判等():
    # 分数转浮点是精确可验的，不是 sympy 那种会静默出错的符号推理。
    # 共用 grade.judge 之后这里跟阅卷口径一致 —— 两份判等逻辑迟早会漂，
    # 漂的后果是「页面说不一致、阅卷说一致」这种自相矛盾
    assert api.answers_agree("3/2", "1.5") is True


def test_仍然不做符号等价():
    # 这才是「不引 sympy」真正挡掉的东西：形式不同就报不同，让人去看
    assert api.answers_agree("mgh", "mgH") is False
    assert api.answers_agree(r"\frac{1}{2}mv^2", "0.5mv²") is False


def test_字母集合只对纯字母生效():
    # 「AB」和「BA」是同一个选择题答案；但「AB 两点」和「BA 两点」不是，
    # 后者带了别的字，不许按集合比
    assert api.answers_agree("AB 两点", "BA 两点") is False
