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


# ---------------------------------------------------------------- 直接进诊断页
#
# 老师在答题卡库点一行卷名，要**直接落到那份卡的诊断结果页**，不再先进一层
# 「卷子页」。那一跳需要卡号，而列表接口原来只给卷子层面的数 ——
# 前端手上没有 sheet id，只能先进卷子页再点一次。
#
# 用户原话：「点击进去之后，就直接显示[诊断页]这个页面就行了，没必要中间还有一层」。

def _卷(name):
    """一份空的答题卡模式卷子。**卷名每个测试独一份** —— 这个库是会话级的，
    跨测试不回滚（仓库里所有测试都靠不重名来隔离）"""
    store.create_answers_paper(name, None)
    store.put_answer_question(name, 1, "D", None)


def test_列表带出答题卡份数与最新那份的号(db):
    _卷("库带卡号卷")
    s1 = store.create_sheet("库带卡号卷", "张三", None)
    s2 = store.create_sheet("库带卡号卷", "李四", None)
    # 两份都得有作答 —— 落地目标只挑有作答的那些（见下一条测试）
    store.put_sheet_answer(s1, 1, raw_text="A")
    store.put_sheet_answer(s2, 1, raw_text="B")
    row = [r for r in store.list_papers() if r["name"] == "库带卡号卷"][0]
    assert row["sheets"] == 2
    assert row["latestSheet"] == s2, "最新那份（按建卡时间倒序，同一秒时按 id）"
    assert s1 != s2


def test_一份卡都没有时给的是零和None(db):
    """
    **0 份不能写成「最新那份是 0 号」。** 页面靠 `latestSheet` 是不是 null 决定
    点进去落到哪一屏 —— 给个 0 的话，它会跳向一份不存在的卡，
    落地是一句「没有这份答题卡」。
    """
    _卷("库无卡卷")
    row = [r for r in store.list_papers() if r["name"] == "库无卡卷"][0]
    assert row["sheets"] == 0
    assert row["latestSheet"] is None


def test_跑坏的空卡不能当落地目标(db):
    """
    **这条是阻断级的。**

    `run_sheet_pipeline` 有两条软失败是 `return` 不是 `raise`（Ⓢ 抠不出答题卡、
    一道题都没读出来），而卡在失败之前就已经建好了；全仓又没有任何删卡路径。
    于是那张 0 行的空卡 `created_at` 最新、**永远排第一**。

    照「最新那份」跳的话，这份卷子从此每一次点进去都落在它上面 —— 而那一屏
    会显示「0 分丢了 · 逐题合计对得上」，还是绿的。一份一个字都没读出来的卡，
    页面在说它分数都对得上。

    所以落地目标是「最新的**有作答的**那份」。一份都没有就退回卷子页
    （和「0 份卡」同一条分支）。
    """
    _卷("库空卡卷")
    good = store.create_sheet("库空卡卷", "张三", None)
    store.put_sheet_answer(good, 1, raw_text="D")
    store.create_sheet("库空卡卷", None, None)          # 跑坏的，一行都没有

    row = [r for r in store.list_papers() if r["name"] == "库空卡卷"][0]
    assert row["sheets"] == 2, "份数照实说，两份就是两份"
    assert row["latestSheet"] == good, "落地目标要跳过那张空卡"


def test_全是空卡时不给落地目标(db):
    """一份有作答的都没有 → 回卷子页，那里有 Ⓐ 的进度和重传入口"""
    _卷("库全空卡卷")
    store.create_sheet("库全空卡卷", None, None)
    row = [r for r in store.list_papers() if r["name"] == "库全空卡卷"][0]
    assert row["sheets"] == 1
    assert row["latestSheet"] is None


def test_别的卷子的卡不算在这一行上(db):
    """子查询忘了 where 的话，两份卷子会互相把对方的卡数算进来"""
    _卷("库计数甲卷")
    _卷("库计数乙卷")
    store.create_sheet("库计数乙卷", "王五", None)
    rows = {r["name"]: r for r in store.list_papers()}
    assert rows["库计数甲卷"]["sheets"] == 0
    assert rows["库计数乙卷"]["sheets"] == 1


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
