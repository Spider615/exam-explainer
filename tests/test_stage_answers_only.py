# -*- coding: utf-8 -*-
"""
只有参考答案的卷子，进度怎么算。

不分支的话 solutions/specs/scenes 恒为 0，页面会永远显示「解题中 0/16」、
进度带永远转、done 永远是 false。**期一加 ③c 那一格已经踩过一次一模一样的坑。**
"""
import api

# 一份跑完了的 answers_only 卷子：有题、挂满知识点，其余一律 0
BASE = dict(questions=16, labels=0, kps=16, solutions=0, judged=0, worth=0,
            specs=0, specsWorth=0, drafts=0, ready=0, sceneTried=0,
            assembledFresh=False, sourceKind="answers_only")


def test_挂上知识点就算完成():
    assert api.stage_of(BASE)[0] == "done"


def test_知识点没挂完停在三c():
    code, label, short, cur, total = api.stage_of({**BASE, "kps": 9})
    assert code == "kpmark" and label == "③c 知识点"
    assert (cur, total) == (9, 16)


def test_一道题都没有停在读答案():
    code, label, *_ = api.stage_of({**BASE, "questions": 0, "kps": 0})
    assert code == "refread"


def test_不要求目录():
    """③b 目录是给试卷页导航用的，这条链不跑它"""
    assert api.stage_of({**BASE, "labels": 0})[0] == "done"


def test_不要求解题断言动画装配():
    for k in ("solutions", "specs", "sceneTried", "assembledFresh"):
        assert api.stage_of(BASE)[0] == "done", k


# ---------------------------------------------------------------- 别把 pdf 卷弄坏
PDF = dict(questions=16, labels=16, kps=16, solutions=16, judged=16, worth=6,
           specs=6, specsWorth=6, drafts=0, ready=6, sceneTried=6,
           assembledFresh=True, sourceKind="pdf")


def test_pdf卷子跑完仍是done():
    assert api.stage_of(PDF)[0] == "done"


def test_pdf卷子该停哪还停哪():
    assert api.stage_of({**PDF, "solutions": 4})[0] == "solve"
    assert api.stage_of({**PDF, "labels": 3})[0] == "outline"
    assert api.stage_of({**PDF, "kps": 9})[0] == "kpmark"
    assert api.stage_of({**PDF, "assembledFresh": False})[0] == "assemble"


def test_没给sourceKind当pdf处理():
    """老数据、或调用方忘了带这一列时的默认行为"""
    p = {k: v for k, v in PDF.items() if k != "sourceKind"}
    assert api.stage_of({**p, "solutions": 4})[0] == "solve"
