# -*- coding: utf-8 -*-
"""
两个模式各有各的库，互相看不见对方的卷子。

列头也不一样：解析试卷是「插图/动画/告警」，答题卡是「带解答/挂知识点」——
所以 list_papers 要多给两个数。
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

import store
from pipeline import api


@pytest.fixture
def 两种卷子各一份(db):
    store.create_answers_paper("列表用答案卷", None)
    store.put_answer_question("列表用答案卷", 1, "D", None)
    store.put_answer_question("列表用答案卷", 11, "2BIL / MP", "由安培力公式")
    yield


def test_list_papers带上模式和两个数(两种卷子各一份):
    row = [r for r in store.list_papers() if r["name"] == "列表用答案卷"][0]
    assert row["sourceKind"] == "answers_only"
    assert row["n"] == 2
    assert row["withSolution"] == 1, "只有第 11 题有解答过程"
    assert row["kps"] == 0, "还没跑 ③c"


ROWS = [
    {"name": "高考真题", "n": 16, "warnings": 0, "figures": 3, "mtime": 1.0,
     "sourceKind": "pdf", "withSolution": 0, "kps": 16},
    {"name": "期末答案", "n": 26, "warnings": 0, "figures": 0, "mtime": 2.0,
     "sourceKind": "answers_only", "withSolution": 3, "kps": 24},
]


def _papers(mode):
    with (
        patch.object(api.store, "list_papers", return_value=[dict(r) for r in ROWS]),
        patch.object(api, "running_cmds", return_value=[]),
        patch.object(api, "scenes_for", return_value={}),
        patch.object(api.store, "progress", return_value=None),
    ):
        return api.papers(user={"id": 7}, mode=mode)


def test_只要解析试卷():
    assert [r["name"] for r in _papers("paper")] == ["高考真题"]


def test_只要答题卡():
    assert [r["name"] for r in _papers("sheet")] == ["期末答案"]


def test_不给mode就全给():
    """命令行和运维要的是「全都要」"""
    assert len(_papers(None)) == 2


def test_没见过的mode值不许静默返回空():
    """
    空列表会被读成「你一份卷子都没有」，那是撒谎。

    **必须是 HTTPException 且 400**，不能只断言 Exception —— `Exception`
    连 `KeyError` / `AttributeError` 都算通过，把 mode 校验重构成一个没接住
    的 500 照样绿；而 500 和 400 在前端是两种完全不同的话：400 是「你传错了」，
    500 是「后端炸了」。
    """
    with pytest.raises(HTTPException) as e:
        _papers("不存在的模式")
    assert e.value.status_code == 400
