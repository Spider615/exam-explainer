# -*- coding: utf-8 -*-
"""
学生的作答**不可再生**。这个文件守着通往它的两条删除路径。

参考答案可以重读（材料还在磁盘上），学生那张已批改的答题卡老师未必还留着，
而上传的原件跑完就从 `_uploads` 清掉了。所以 `sheet_answers` 里的行、
原图切片（`crop_rel`）、以及 `teacher_verdict`（这条链上唯一的人工权威）
一旦没了就是真没了。

两条路径都不是假想的：

· `store.publish` 是**整卷替换**。答案卷的小问题号是 1201/1301 这种，
  PDF 链永远不会产出，于是那句 `DELETE ... WHERE n <> ALL(...)` 会把它们
  一次全删掉，`sheet_answers` 顺着外键跟着走。
· `refread.py` 读参考答案时，日志里直接教人跑 `store.drop_questions`
  去收拾读错的题号 —— 人照做就删了作答。

**「挂不上题」是这个设计里的正常状态，不是异常。** 实测答题卡第 13 题印的小问
编号是 (1)(2)(4)(5)，参考答案是 (1)(2)(3)(4)，本来就有对不上的。既然挂不上是
正常的，`question_id` 的外键就不该是 `ON DELETE CASCADE`（删掉整行），
该是 `ON DELETE SET NULL`（解绑，行留着）。
"""
import json
import os

import pytest

import store


def _sheet_with_answers(name, ns=(1301, 1302)):
    """一份答案卷 + 几道题 + 一份答题卡 + 每题一行作答。返回 (sheet_id, {n: qid})"""
    store.create_answers_paper(name, None)
    qids = {n: store.put_answer_question(name, n, "标准%d" % n, None) for n in ns}
    sid = store.create_sheet(name, "张三", None)
    for n in ns:
        store.put_sheet_answer(sid, n, question_id=qids[n], raw_text="学生写的%d" % n,
                               crop_rel="sheet/1/crop/%d.png" % n,
                               verdict="wrong", verdict_by="teacher_score")
        # 改判走它自己的入口（`teacher_verdict` 不在 `_SHEET_COLS` 白名单里，
        # 有意的：系统原判和老师改判必须分开写，才留得住原判）
        store.set_teacher_verdict(sid, n, "right")
    return sid, qids


# ---------------------------------------------------------------- 删题

def test_删题不许带走学生的作答(db):
    """
    `drop_questions` 删掉一道题之后，那道题上的学生作答必须**还在**，
    只是 `question_id` 解绑成 NULL —— 和「答题卡上有、参考答案里没有」
    那些题落在同一个状态上，页面本来就要处理它。
    """
    sid, _ = _sheet_with_answers("作答安全用删题卷")
    store.drop_questions("作答安全用删题卷", [1301])

    rows = {r["n"]: r for r in store.sheet_answers(sid)}
    assert 1301 in rows, "删一道题把学生的作答整行带走了 —— 那是不可再生的"
    assert rows[1301]["question_id"] is None, "题没了，绑定应该解开"
    assert rows[1301]["raw_text"] == "学生写的1301"
    assert rows[1301]["crop_rel"] == "sheet/1/crop/1301.png", "原图切片没了就没红绿灯了"


def test_删题不许带走老师的改判(db):
    """`teacher_verdict` 是这条链上唯一的人工权威，重跑一万遍也生不回来"""
    sid, _ = _sheet_with_answers("作答安全用改判卷")
    store.drop_questions("作答安全用改判卷", [1301])
    rows = {r["n"]: r for r in store.sheet_answers(sid)}
    assert rows[1301]["teacher_verdict"] == "right"
    assert rows[1301]["final_verdict"] == "right"


def test_删题会先说清楚要解绑多少条作答(db):
    """
    静默解绑和静默删除一样糟 —— 人跑这个函数是为了收拾读错的题号，
    他得知道这一刀会碰到多少条学生数据。
    """
    _sheet_with_answers("作答安全用告知卷", ns=(1301, 1302))
    got = store.drop_questions("作答安全用告知卷", [1301, 1302])
    assert got["questions"] == 2
    assert got["unbound_answers"] == 2


# ---------------------------------------------------------------- 整卷覆盖

def _workdir(tmp_path, ns):
    d = tmp_path / "w"
    d.mkdir()
    (d / "questions.json").write_text(json.dumps(
        {"source": "x.pdf", "sections": [], "warnings": [],
         "dropped_boilerplate": [],
         "questions": [{"n": n, "stem": "题%d" % n} for n in ns]},
        ensure_ascii=False), encoding="utf-8")
    return str(d)


def test_往答案卷上publish一份pdf当场抛(db, tmp_path):
    """
    这是 `create_answers_paper` 那道护栏的反方向。API 层已经会改名了，
    但命令行那条链（`run.py`）直接调 `publish`，绕过 API —— 底闸要在这里。
    """
    _sheet_with_answers("作答安全用覆盖卷")
    with pytest.raises(ValueError, match="答题卡"):
        store.publish(_workdir(tmp_path, [1, 2, 3]), name="作答安全用覆盖卷")


def test_抛了之后作答一条没少(db, tmp_path):
    sid, _ = _sheet_with_answers("作答安全用覆盖卷2")
    with pytest.raises(ValueError):
        store.publish(_workdir(tmp_path, [1, 2, 3]), name="作答安全用覆盖卷2")
    assert len(store.sheet_answers(sid)) == 2
    assert store.source_kind_of("作答安全用覆盖卷2") == "answers_only"


def test_解析试卷照常publish(db, tmp_path, conn):
    """底闸不能连正常的重新发布也一起拦下来"""
    conn.execute("INSERT INTO papers (name, n_questions, source_kind) "
                 "VALUES ('作答安全用正常卷', 3, 'pdf')")
    conn.commit()
    got = store.publish(_workdir(tmp_path, [1, 2, 3]), name="作答安全用正常卷")
    assert got["questions"] == 3
