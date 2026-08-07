# -*- coding: utf-8 -*-
"""
阶段判定。带圈数字（③）不是 Python 合法标识符字符，所以函数名里写「三c」。
"""
import api

BASE = dict(questions=16, solutions=16, labels=16, kps=16, judged=16, worth=6,
            specs=6, specsWorth=6, drafts=0, ready=6, sceneTried=6,
            assembledFresh=True)


def test_知识点没挂完就停在三c():
    code, label, short, cur, total = api.stage_of({**BASE, "kps": 9})
    assert code == "kpmark"
    assert label == "③c 知识点"
    assert (cur, total) == (9, 16)


def test_三c排在三b之后():
    """目录还没生成时，先报 ③b，不能跳到 ③c"""
    code, *_ = api.stage_of({**BASE, "labels": 3, "kps": 0})
    assert code == "outline"


def test_三c排在四c之前():
    code, *_ = api.stage_of({**BASE, "kps": 9, "judged": 0})
    assert code == "kpmark"


def test_解题没完仍然先报三():
    code, *_ = api.stage_of({**BASE, "solutions": 4, "kps": 0})
    assert code == "solve"


def test_都跑完了就是done():
    assert api.stage_of(BASE)[0] == "done"
