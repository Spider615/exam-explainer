# -*- coding: utf-8 -*-
"""
⑤ 开工前的清单：哪些题要做、跳过的每一道要说得出原因。

为什么要「已经通过门禁的就跳过」
--------------------------------
原来 `scene.py <卷名>` 会把整卷候选题**全部重做一遍**，不管哪些已经有动画了。
一道题几分钟到几十分钟、走的是付费后端 —— 而「继续执行」这个按钮存在的意义
恰恰是**接着没做完的往下跑**，不是从头再来一遍。

数据不会丢（`put_scene` 的 WHERE 挡住了「失败覆盖成功」），丢的是时间和钱，
而且重做成功时会把一个已经人工看过的动画换成一个没人看过的。

例外只有一个：`--only N` 是人明确点名「这道重跑」（页面上那个按钮），
那当然不能跳。`--redo` 则是整卷强制重做，改完管线想全部重生成时用。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import scene


def spec_row(**kw):
    d = {"spec": {"id": "q1"}, "animatable": True, "why_not": "",
         "n_invariants": 8, "status": "approved", "worth": True, "worth_why": "值得"}
    d.update(kw)
    return d


QS = [{"n": n, "id": 100 + n} for n in (1, 2, 3)]


def plan(specs, done=(), **kw):
    """specs: {题号: spec 行或 None}"""
    return scene.plan(QS, lambda qid: specs.get(qid - 100), set(done), **kw)


def names(todo):
    return [q["n"] for q, _ in todo]


def why(skip, n):
    return next(w for k, w in skip if k == n)


def test_默认跳过已经通过门禁的题():
    todo, skip = plan({1: spec_row(), 2: spec_row(), 3: spec_row()}, done={1, 3})
    assert names(todo) == [2]
    assert "已经有通过门禁的动画" in why(skip, 1)


def test_only_点名的题不跳_哪怕已经有动画():
    """页面上「重跑这一题」走的就是这条 —— 人明确要求重做。"""
    todo, _ = plan({1: spec_row(), 2: spec_row(), 3: spec_row()},
                   done={1, 2, 3}, only={2})
    assert names(todo) == [2]


def test_redo_整卷强制重做():
    todo, _ = plan({1: spec_row(), 2: spec_row(), 3: spec_row()},
                   done={1, 2, 3}, redo=True)
    assert names(todo) == [1, 2, 3]


def test_全都做完了就没有要做的题():
    todo, skip = plan({1: spec_row(), 2: spec_row(), 3: spec_row()}, done={1, 2, 3})
    assert todo == []
    assert len(skip) == 3


def test_没有_spec_的题跳过():
    todo, skip = plan({1: None, 2: spec_row(), 3: spec_row()}, done={3})
    assert names(todo) == [2]
    assert "没有 spec" in why(skip, 1)


def test_四道闸门的顺序_便宜的在前():
    """
    一道题同时踩中多条时，报的原因要是**最先那道闸**。

    否则人看到「④c 判定不值得」，跑去改选题，其实它根本没有 spec。
    """
    todo, skip = plan({1: None, 2: spec_row(animatable=False, why_not="纯概念题"),
                       3: spec_row(status="draft")})
    assert todo == []
    assert "没有 spec" in why(skip, 1)
    assert "不适合做动画" in why(skip, 2)
    assert "自检未过" in why(skip, 3)


def test_已完成这条闸排在最前():
    """
    已经有动画的题，连「它 spec 什么状态」都不必去看 —— 那是白花的查询，
    而且报「④b 自检未过」会让人以为这道题没动画，其实它有。
    """
    _, skip = plan({1: spec_row(status="draft")}, done={1})
    assert "已经有通过门禁的动画" in why(skip, 1)


def test_allow_draft_放行没过自检的():
    todo, _ = plan({1: spec_row(status="draft")}, allow_draft=True)
    assert names(todo) == [1]


def test_worth_为假时默认不做_加_all_才做():
    assert plan({1: spec_row(worth=False, worth_why="太简单")})[0] == []
    assert names(plan({1: spec_row(worth=False)}, do_all=True)[0]) == [1]


def test_worth_还没判过时默认不做_但点名了就做():
    assert plan({1: spec_row(worth=None)})[0] == []
    assert names(plan({1: spec_row(worth=None)}, only={1})[0]) == [1]
