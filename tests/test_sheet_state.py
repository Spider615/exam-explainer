# -*- coding: utf-8 -*-
"""
一份答题卡**这一趟跑成什么样**，得能从库里问出来。

在这之前 `list_sheets` 只给 id/学生/页数/总分/读出/错/半对/丢分 ——
一份正在跑的卡、一份跑挂了的卡、一份跑完了什么都没读出来的卡，在那张表里
**长得一模一样**（都是「读出 0」）。设计文档里写着「答题卡的进度和失败按卡画、
一卡一条」，而数据里根本没有可画的东西。

2026-08-15 撞上的就是这个：一份卡读了二十几分钟，卷子页顶上有进度（那是任务表
给的），而「学生的答题卡」那张表里那一行**一个字都没说**。任务表还是进程内的
dict，重启就空 —— 于是重启之后连那点进度也没了，那一行变成永久的沉默。

四种状态，各有各的下一步：

  running  在跑        —— 等着就行，别重传
  failed   没跑成      —— **要给出原因**，多半该换图重传
  empty    没读出作答  —— 卡建出来了但一条作答都没有（老数据、或者建完就断电）
  done     好了        —— 数字自己会说话，不用再挂一个牌子

**「停了」不靠猜时长。** 驱动整条链的是进程内的一个线程，进程没了它就没了；
所以后端每次起来的时候，库里还标着 running 的必然是**上一个进程留下的孤儿** ——
这是个确定判据，不用「超过 N 分钟没动静就算死」那种阈值。阈值这条路走不通：
那次实跑里最慢的一次子调用是 442 秒，定短了会把正常跑着的卡说成死了。
"""
import pytest

import store


@pytest.fixture
def owner(conn):
    conn.execute("INSERT INTO users (id, email) VALUES (90602, 'st@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    return 90602


def _one(paper, sheet_id):
    return next(s for s in store.list_sheets(paper) if s["id"] == sheet_id)


def _answered(sid):
    store.put_sheet_answer(sid, 1, scored=True, score_got=3, score_full=3,
                           verdict="right", verdict_by="code")


def test_建出来就算在跑(db, owner):
    """建卡和起线程是同一个动作，中间没有第三种状态。"""
    store.create_answers_paper("状态新建卷", owner)
    sid = store.create_sheet("状态新建卷", "张三", owner)

    assert _one("状态新建卷", sid)["state"] == "running"


def test_没跑成要带上原因(db, owner):
    """
    只标一个「失败」不够。老师看完要决定「重传」还是「等」，
    而这两件事的代价差很远 —— 原因是唯一能让他判断的东西。
    """
    store.create_answers_paper("状态失败卷", owner)
    sid = store.create_sheet("状态失败卷", "李四", owner)

    store.set_sheet_run(sid, "error", "没在这张图里找到答题卡")

    row = _one("状态失败卷", sid)
    assert row["state"] == "failed"
    assert row["stateNote"] == "没在这张图里找到答题卡"


def test_跑完了一条作答都没有不算好了(db, owner):
    """说成 done 的话，点进去是一屏「0 分丢了 · 逐题合计对得上」。"""
    store.create_answers_paper("状态空卷", owner)
    sid = store.create_sheet("状态空卷", "王五", owner)

    store.set_sheet_run(sid, "done")

    assert _one("状态空卷", sid)["state"] == "empty"


def test_跑完且有作答才是好了(db, owner):
    store.create_answers_paper("状态好卷", owner)
    sid = store.create_sheet("状态好卷", "赵六", owner)
    _answered(sid)

    store.set_sheet_run(sid, "done")

    assert _one("状态好卷", sid)["state"] == "done"


def test_老数据按手上有什么判(db, owner):
    """
    `status` 是这次才加的列，老数据全是 NULL。**不能一律当成在跑** ——
    那样一开页面，历史上每一份卡都在转圈。有作答就是 done，没有就是 empty。
    """
    store.create_answers_paper("状态老卷", owner)
    sid = store.create_sheet("状态老卷", "老数据", owner)
    _answered(sid)
    with store.connect() as c:
        c.execute("UPDATE answer_sheets SET status=NULL WHERE id=%s", (sid,))
        c.commit()

    assert _one("状态老卷", sid)["state"] == "done"


def test_重启把孤儿扫掉(db, owner):
    """
    后端重启：库里还标着 running 的都是上一个进程留下的孤儿 ——
    驱动那条链的线程随进程没了，没人会再来改这一行。
    **原因要说人话**，「后端重启了」是老师看得懂、也知道该怎么办的。
    """
    store.create_answers_paper("状态孤儿卷", owner)
    alive = store.create_sheet("状态孤儿卷", "重启前在跑", owner)
    done = store.create_sheet("状态孤儿卷", "重启前跑完了", owner)
    _answered(done)
    store.set_sheet_run(done, "done")

    n = store.sweep_running_sheets()

    assert n >= 1
    orphan = _one("状态孤儿卷", alive)
    assert orphan["state"] == "failed"
    assert "重启" in orphan["stateNote"]
    # 扫描只认 running —— 跑完的那份不能被牵连
    assert _one("状态孤儿卷", done)["state"] == "done"


def test_在跑的卡要说已经跑了多久(db, owner):
    """
    光说「在跑」不够。一页三四分钟、四页起步，老师真正想知道的是「还要多久」；
    给出已经跑了多久，他自己就能判断这是正常还是不正常 ——
    而这恰恰是 2026-08-15 那次他没有、于是只能来问的东西。
    """
    store.create_answers_paper("状态计时卷", owner)
    sid = store.create_sheet("状态计时卷", "计时", owner)

    row = _one("状态计时卷", sid)
    assert row["runSeconds"] is not None
    assert row["runSeconds"] >= 0


def test_跑完的卡不报时长(db, owner):
    """
    跑完了就别再挂一个秒表 —— 那一栏是给「还要等多久」用的。
    留着的话，一份三天前跑完的卡会显示「已跑 4300 分钟」。
    """
    store.create_answers_paper("状态跑完计时卷", owner)
    sid = store.create_sheet("状态跑完计时卷", "跑完", owner)
    _answered(sid)
    store.set_sheet_run(sid, "done")

    assert _one("状态跑完计时卷", sid)["runSeconds"] is None
