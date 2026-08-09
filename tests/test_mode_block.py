# -*- coding: utf-8 -*-
"""
两个进度端点都要带上「这是哪个模式、这排格子现在什么样」。

/progress 是每 3 秒轮询的那个，所以「产物在不在」也要在这里算得出来 ——
交给前端去凑的话，前端就又有逻辑了。
"""
from unittest.mock import patch

from pipeline import api

PDF = dict(questions=16, labels=16, kps=16, solutions=16, solutionFailures=0,
           judged=16, worth=6, specs=6, specsWorth=6, approved=6, drafts=0,
           ready=6, sceneTried=6, scenes=6, assembled=True, assembledFresh=True,
           busy=False, elapsedSeconds=12, sourceKind="pdf")

SHEET = dict(questions=26, labels=0, kps=26, solutions=0, solutionFailures=0,
             judged=0, worth=0, specs=0, specsWorth=0, approved=0, drafts=0,
             ready=0, sceneTried=0, scenes=0, assembled=False,
             assembledFresh=False, busy=False, elapsedSeconds=9,
             sourceKind="answers_only")


def test_解析试卷给六格():
    m = api.mode_block(PDF, "某卷", "done", None,
                       artifacts={"scene": True, "assemble": True})
    assert m["code"] == "paper" and m["label"] == "解析试卷"
    assert [c["code"] for c in m["stages"]] == [
        "ingest", "segment", "solve", "spec", "scene", "assemble"]
    assert {c["state"] for c in m["stages"]} == {"done"}


def test_答题卡给两格():
    m = api.mode_block(SHEET, "某答案卷", "kpmark", None, artifacts={})
    assert m["code"] == "sheet" and m["label"] == "答题卡诊断"
    assert [c["code"] for c in m["stages"]] == ["refread", "kpmark"]
    assert [c["state"] for c in m["stages"]] == ["done", "now"]


def test_不给artifacts时自己去查产物():
    """/progress 那条路没有 paper.stages 可用，得自己算"""
    with (
        patch.object(api.store, "assembled",
                     return_value={"path": "/x/out.html", "at": 1, "fresh": True}),
        patch.object(api.os.path, "exists", return_value=True),
    ):
        m = api.mode_block({**PDF, "scenes": 0}, "某卷", "done", None)
    by = {c["code"]: c["state"] for c in m["stages"]}
    assert by["scene"] == "empty", "一个动画都没做出来，不能画成「⑤ 做完了」"
    assert by["assemble"] == "done"


def test_答题卡模式不去查产物():
    """它没有 ⑤ 和 ⑦，白查一次库"""
    with patch.object(api.store, "assembled") as asm:
        api.mode_block(SHEET, "某答案卷", "done", None)
    asm.assert_not_called()
