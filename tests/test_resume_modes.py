# -*- coding: utf-8 -*-
"""
「继续执行」也要按模式走。

现在它不看 source_kind，对一份答案卷点下去会去跑 solve/spec/scene ——
那条链根本没有题干，跑出来的东西没有意义，还要烧一份额度。
"""
from pipeline import api


def test_解析试卷仍然跑原来那三段():
    got = [how for _, how, _ in api.resume_steps_for("pdf")]
    assert got == ["refans.py", "@solve", "@finish"]


def test_答题卡只跑读答案和知识点():
    got = [how for _, how, _ in api.resume_steps_for("answers_only")]
    assert got == ["@skip", "kpmark.py"], "Ⓐ 续跑跳过（图早收掉了），只补 ③c"


def test_答题卡不许跑解题断言动画():
    got = [how for _, how, _ in api.resume_steps_for("answers_only")]
    for forbidden in ("@solve", "@finish", "solve.py", "spec.py", "scene.py"):
        assert forbidden not in got


def test_分发不靠显示名():
    """显示名是给人看的，改一个字就把分发改坏 —— 而那种坏法一声不响"""
    for kind in ("pdf", "answers_only"):
        for label, how, _ in api.resume_steps_for(kind):
            assert how.startswith("@") or how.endswith(".py"), (kind, label, how)


def test_没给source_kind当解析试卷():
    assert api.resume_steps_for(None) == api.resume_steps_for("pdf")
