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


# 上面五条全在测 resume_steps_for —— 一个返回静态表的纯函数，本身不会被生产环境调用。
# 真正会跑的是 api.resume_paper（/resume 端点起线程调它），它那段 if/elif 分发一条
# 测试都没有：有人把它改坏（重新硬编码回老的三行、或者顺序弄乱让 kpmark.py 掉进
# @solve 那一支），上面五条一条都不会红。下面几条直接调 resume_paper 打桩验证。
from unittest.mock import Mock, patch


def test_答题卡续跑不许触碰解题和收尾():
    """
    分发一旦改坏（比如有人把这段重新硬编码回老的三行，或者 if/elif 顺序乱了让
    kpmark.py 掉进 @solve 那一支），答题卡续跑就会真的去跑解题/收尾 —— 那条链
    根本没有题干，跑出来的东西没有意义，还要白烧一份模型额度。
    """
    jid = "resume-paper-answers-only"
    api.JOBS[jid] = {"log": []}
    try:
        with patch.object(api, "run_step") as run_step, \
             patch.object(api, "solve_paper") as solve_paper, \
             patch.object(api, "finish_paper") as finish_paper, \
             patch.object(api, "job_log"):
            api.resume_paper(jid, "卷子", "answers_only")

        solve_paper.assert_not_called()
        finish_paper.assert_not_called()
        run_step.assert_called_once()
        (_jid, _label, cmd), kwargs = run_step.call_args
        assert cmd[-2].endswith("kpmark.py"), cmd
    finally:
        del api.JOBS[jid]


def test_解析试卷续跑先解题后收尾且脚本对得上():
    """
    三段顺序若被打乱（比如收尾提前跑，题目还没解出来），④ 写断言和 ⑤ 生成场景
    会对着空的解题结果跑，白白烧一份额度还什么都产不出来。这里同时钉住「跑的是
    哪个脚本、超时给多少」和「solve 必须先于 finish」，不是只看两个都被调过。
    """
    jid = "resume-paper-pdf"
    api.JOBS[jid] = {"log": []}
    manager = Mock()
    try:
        with patch.object(api, "run_step") as run_step, \
             patch.object(api, "solve_paper") as solve_paper, \
             patch.object(api, "finish_paper") as finish_paper, \
             patch.object(api, "job_log"):
            manager.attach_mock(run_step, "run_step")
            manager.attach_mock(solve_paper, "solve_paper")
            manager.attach_mock(finish_paper, "finish_paper")

            api.resume_paper(jid, "卷子", "pdf")

        run_step.assert_called_once()
        (_jid, _label, cmd), kwargs = run_step.call_args
        assert cmd[-2].endswith("refans.py"), cmd
        assert kwargs.get("timeout") == 120

        solve_paper.assert_called_once_with(jid, "卷子")
        finish_paper.assert_called_once_with(jid, "卷子")

        order = [c[0] for c in manager.mock_calls]
        assert order.index("solve_paper") < order.index("finish_paper")
    finally:
        del api.JOBS[jid]


def test_答题卡续跑不会真的把读参考答案那步交给run_step():
    """
    Ⓐ 那一行在表里是 @skip，只该落一条日志；上传时的原图早就收掉了，一旦分发
    把它错判成脚本去真的执行，run_step 就会真的起一个子进程 —— 轻则跑一个不
    存在的脚本报错，重则被人「顺手修好」成对上 refread.py，对着空目录重读，
    答案全错位。这里钉死：这个模式下 run_step 从头到尾只跑过一次，且从没跑过
    refread.py。
    """
    jid = "resume-paper-answers-only-skip-check"
    api.JOBS[jid] = {"log": []}
    try:
        with patch.object(api, "run_step") as run_step, \
             patch.object(api, "solve_paper"), \
             patch.object(api, "finish_paper"), \
             patch.object(api, "job_log"):
            api.resume_paper(jid, "卷子", "answers_only")

        calls = run_step.call_args_list
        assert len(calls) == 1, calls
        assert not any("refread.py" in str(c.args[2]) for c in calls), calls
    finally:
        del api.JOBS[jid]
