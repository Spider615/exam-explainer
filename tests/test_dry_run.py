# -*- coding: utf-8 -*-
"""
`--dry-run`：只出清单，不调模型、不写库。

`EXAM_READONLY=1` 挡住了写库（由 Postgres 拒），但**挡不住烧额度** ——
⑤ 照样会起沙箱跑几十分钟、④c 照样会调模型。而「我只想看看它打算做哪几道题」
恰恰是最常见的需求，也正是两次手滑的场景。

判据抽在 `plan()` / `candidates()` 里，`--dry-run` 就是「跑判据，打清单，退出」。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import scene


def test_场景清单判据是纯函数():
    """
    `plan()` 只吃数据、只回数据 —— 不调模型、不碰库、不写盘。
    `--dry-run` 能成立全靠这一点。
    """
    qs = [{"n": 1, "id": 101}, {"n": 2, "id": 102}]
    row = {"spec": {"id": "q1"}, "animatable": True, "why_not": "", "n_invariants": 8,
           "status": "approved", "worth": True, "worth_why": ""}
    todo, skip = scene.plan(qs, lambda qid: row, {1})
    assert [q["n"] for q, _ in todo] == [2]
    assert skip[0][0] == 1


def test_场景有_dry_run_这个开关():
    ap = scene.build_argparser()
    a = ap.parse_args(["某卷", "--dry-run"])
    assert a.dry_run is True
    assert ap.parse_args(["某卷"]).dry_run is False


def test_dry_run_的帮助里要说清楚它不花钱():
    ap = scene.build_argparser()
    txt = ap.format_help()
    assert "--dry-run" in txt
    assert "不调模型" in txt
