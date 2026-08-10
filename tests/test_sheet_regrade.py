# -*- coding: utf-8 -*-
"""
老师改判。**改判定和改分数必须一起**，否则页面自相矛盾。

只写 `teacher_verdict` 不动分数列的话，页面会显示「对 · 0 分（满分 3 分）」——
而步三的薄弱知识点是按丢分率排的，那条改判**完全无效**：这个知识点照样
背着 3 分的丢分挂在榜首。

存法和 `final_verdict` 同一个规矩：改判存**单独一列**（`teacher_score_got`），
不覆盖系统原判 —— 留着原判才看得出系统错在哪，也才撤得回来；
而对外读到的必须是改判后的结果，`COALESCE` **只在 `store.sheet_answers`
那一个地方做**，让每个调用点各写一份总会漏掉一个。
"""
import pytest

import store
from pipeline import api


@pytest.fixture
def owner(conn):
    conn.execute("INSERT INTO users (id, email) VALUES (90601, 'rg@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    return 90601


def _card(name, owner):
    store.create_answers_paper(name, owner)
    store.put_answer_question(name, 11, "2BIL", None)
    sid = store.create_sheet(name, "张三", owner)
    store.put_sheet_answer(sid, 11, raw_text="BIL", verdict="wrong",
                           verdict_by="teacher_score", score_got=0, score_full=3,
                           scored=True)
    return sid


# ---------------------------------------------------------------- 分数要跟着改

def test_改判成对时分数也跟着改(db, owner):
    """
    不跟着改的话页面会写「对 · 0 分（满分 3 分）」—— 自相矛盾，
    而且步三按丢分排的时候这条改判完全无效。
    """
    sid = _card("改判用卷", owner)
    store.set_teacher_verdict(sid, 11, "right", score_got=3)
    r = store.sheet_answers(sid)[0]
    assert r["final_verdict"] == "right"
    assert float(r["final_score_got"]) == 3


def test_不给分数时按判定推一个(db, owner):
    """
    老师在页面上点「改判为对」，不该逼他再填一次分数。
    对 = 满分、错 = 0 分，半对说不出来所以必须显式给。
    """
    sid = _card("改判用推分卷", owner)
    store.set_teacher_verdict(sid, 11, "right")
    assert float(store.sheet_answers(sid)[0]["final_score_got"]) == 3


def test_改判成半对必须显式给分(db, owner):
    """半对是几分推不出来 —— 猜一个就是编数据"""
    sid = _card("改判用半对卷", owner)
    with pytest.raises(ValueError, match="半对"):
        store.set_teacher_verdict(sid, 11, "partial")
    store.set_teacher_verdict(sid, 11, "partial", score_got=1.5)
    assert float(store.sheet_answers(sid)[0]["final_score_got"]) == 1.5


def test_系统原判留着没被覆盖(db, owner):
    """留着原判才看得出系统错在哪，也才撤得回来"""
    sid = _card("改判用留底卷", owner)
    store.set_teacher_verdict(sid, 11, "right", score_got=3)
    r = store.sheet_answers(sid)[0]
    assert r["verdict"] == "wrong" and float(r["score_got"]) == 0


def test_撤回改判退回系统原判(db, owner):
    sid = _card("改判用撤回卷", owner)
    store.set_teacher_verdict(sid, 11, "right", score_got=3)
    store.set_teacher_verdict(sid, 11, None)
    r = store.sheet_answers(sid)[0]
    assert r["final_verdict"] == "wrong"
    assert float(r["final_score_got"]) == 0


def test_丢分跟着改判走(db, owner):
    """薄弱知识点按丢分排，改判不影响它的话这个功能就是坏的"""
    sid = _card("改判用丢分卷", owner)
    assert float(store.list_sheets("改判用丢分卷")[0]["lost"]) == 3
    store.set_teacher_verdict(sid, 11, "right", score_got=3)
    assert float(store.list_sheets("改判用丢分卷")[0]["lost"]) == 0


# ---------------------------------------------------------------- 命中 0 行

def test_改一个不存在的题号当场抛(db, owner):
    """
    静默成功最坏：老师以为改好了，页面刷新回来还是老样子，
    而他不会怀疑是「那道题号根本不在这份卡上」。
    """
    sid = _card("改判用没这题卷", owner)
    with pytest.raises(ValueError, match="没有第"):
        store.set_teacher_verdict(sid, 99, "right", score_got=1)


def test_没改成就不许把诊断标为过期(db, owner):
    """`updated_at` 是「诊断过没过期」的判据，改失败了不该动它"""
    sid = _card("改判用过期卷", owner)
    before = store.list_sheets("改判用过期卷")[0]["updated_at"]
    with pytest.raises(ValueError):
        store.set_teacher_verdict(sid, 99, "right", score_got=1)
    assert store.list_sheets("改判用过期卷")[0]["updated_at"] == before


# ---------------------------------------------------------------- 端点

def test_端点改得动(db, owner):
    sid = _card("改判用端点卷", owner)
    api.regrade(sid, 11, body={"verdict": "right"}, user={"id": owner})
    assert store.sheet_answers(sid)[0]["final_verdict"] == "right"


def test_别人的卡改不动(db, owner, conn):
    conn.execute("INSERT INTO users (id, email) VALUES (90699, 'rg2@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    sid = _card("改判用别人卷", 90699)
    with pytest.raises(Exception):
        api.regrade(sid, 11, body={"verdict": "right"}, user={"id": owner})


def test_端点认得出野的判定(db, owner):
    sid = _card("改判用野值卷", owner)
    with pytest.raises(Exception):
        api.regrade(sid, 11, body={"verdict": "对"}, user={"id": owner})


def test_端点下发改判后的分数不是原分(db, owner):
    """
    **这一条就是本任务的全部意义。** 下发原分的话，老师改判成「对」之后
    页面还写着「对 · 0 分（满分 3 分）」—— 自相矛盾，而且他会以为没改成。
    """
    sid = _card("改判用下发卷", owner)
    api.regrade(sid, 11, body={"verdict": "right"}, user={"id": owner})
    r = api.sheet_detail(sid, user={"id": owner})["rows"][0]
    assert r["verdict"] == "right"
    assert r["scoreGot"] == 3.0, "下发的该是改判后的分数"
    # 原判也要给出来，老师才知道自己改掉了什么，而且撤得回来
    assert r["sysVerdict"] == "wrong" and r["sysScoreGot"] == 0.0


def test_没改判时下发的就是系统判的(db, owner):
    sid = _card("改判用没改卷", owner)
    r = api.sheet_detail(sid, user={"id": owner})["rows"][0]
    assert r["verdict"] == "wrong" and r["scoreGot"] == 0.0
    assert r["teacherVerdict"] is None
