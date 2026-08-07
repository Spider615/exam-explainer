# -*- coding: utf-8 -*-
import json
import store


def _paper(tmp_path, name, ns=(1, 2, 3)):
    d = tmp_path / name
    d.mkdir()
    (d / "questions.json").write_text(json.dumps({
        "source": "x.pdf", "sections": [], "warnings": [],
        "questions": [{"n": n, "type": "单选题", "stem": "第%d题" % n,
                       "options": [], "tables": [], "figures": []} for n in ns],
    }, ensure_ascii=False), encoding="utf-8")
    store.publish(str(d), name=name)
    return name


def test_建答题卡并写作答(db, tmp_path):
    name = _paper(tmp_path, "卡卷A")
    sid = store.create_sheet(name, "张三", None)
    qid = store.get_paper(name)["questions"][0]["id"]
    store.put_sheet_answer(sid, 1, question_id=qid, raw_text="B", norm="B",
                           verdict="right", verdict_by="code", verdict_why="字母集合相等")
    rows = store.sheet_answers(sid)
    assert len(rows) == 1
    assert rows[0]["n"] == 1 and rows[0]["raw_text"] == "B"
    assert rows[0]["final_verdict"] == "right"


def test_老师改判不覆盖原判(db, tmp_path):
    name = _paper(tmp_path, "卡卷B")
    sid = store.create_sheet(name, "李四", None)
    store.put_sheet_answer(sid, 1, raw_text="B", verdict="wrong", verdict_by="code")
    store.set_teacher_verdict(sid, 1, "right")
    r = store.sheet_answers(sid)[0]
    assert r["verdict"] == "wrong", "系统原判必须留着，否则看不出系统错在哪"
    assert r["teacher_verdict"] == "right"
    assert r["final_verdict"] == "right", "对外读到的应该是改判后的"


def test_改判能撤回(db, tmp_path):
    name = _paper(tmp_path, "卡卷C")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="code")
    store.set_teacher_verdict(sid, 1, "right")
    store.set_teacher_verdict(sid, 1, None)
    r = store.sheet_answers(sid)[0]
    assert r["teacher_verdict"] is None
    assert r["final_verdict"] == "wrong", "撤回后应该退回系统原判"


def test_改判会touch_updated_at(db, tmp_path):
    name = _paper(tmp_path, "卡卷D")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="code")
    before = store.list_sheets(name)[0]["updated_at"]
    store.set_teacher_verdict(sid, 1, "right")
    after = store.list_sheets(name)[0]["updated_at"]
    assert after > before, "诊断过没过期要靠它判"


def test_野的verdict当场拒绝(db, tmp_path):
    name = _paper(tmp_path, "卡卷D2")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="code")
    try:
        store.set_teacher_verdict(sid, 1, "对")
    except ValueError as e:
        assert "right/wrong/blank/unsure" in str(e)
    else:
        raise AssertionError("第五个值应该当场抛，不能悄悄写进库")


def test_题号挂不上卷子也存得下(db, tmp_path):
    """认出了题号但卷子里没这道题。挂不上就是挂不上，不许安一个最近的"""
    name = _paper(tmp_path, "卡卷E", ns=(1, 2))
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 7, question_id=None, raw_text="C", verdict="unsure",
                           verdict_by="code", verdict_why="卷子里没有第7题")
    r = store.sheet_answers(sid)[0]
    assert r["question_id"] is None and r["n"] == 7


def test_同一题重写是覆盖不是追加(db, tmp_path):
    """复读会把同一题再写一次，追加的话页面上会出现两行"""
    name = _paper(tmp_path, "卡卷F")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, raw_text="B", verdict="wrong", verdict_by="code")
    store.put_sheet_answer(sid, 1, raw_text="D", verdict="right", verdict_by="code")
    rows = store.sheet_answers(sid)
    assert len(rows) == 1 and rows[0]["raw_text"] == "D"


def test_覆盖时没给的列不被冲掉(db, tmp_path):
    """复读只写 reread_raw 和 verdict，不该顺手把 crop_rel 抹成 NULL ——
    原图切片没了，这个功能唯一的红绿灯就废了"""
    name = _paper(tmp_path, "卡卷F2")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, raw_text="B", crop_rel="sheets/1/q1.png",
                           verdict="wrong", verdict_by="code")
    store.put_sheet_answer(sid, 1, reread_raw="D", reread=True,
                           verdict="right", verdict_by="code")
    r = store.sheet_answers(sid)[0]
    assert r["crop_rel"] == "sheets/1/q1.png"
    assert r["raw_text"] == "B", "第一次读出来的也要留着，两次都留"
    assert r["reread_raw"] == "D" and r["reread"] is True


def test_不认识的列当场拒绝(db, tmp_path):
    name = _paper(tmp_path, "卡卷F3")
    sid = store.create_sheet(name, None, None)
    try:
        store.put_sheet_answer(sid, 1, verdcit="right")     # 故意拼错
    except ValueError as e:
        assert "verdcit" in str(e)
    else:
        raise AssertionError("拼错列名会静默写不进去，而阅卷结果错了页面上看不出来")


def test_box存得进jsonb(db, tmp_path):
    name = _paper(tmp_path, "卡卷F4")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, box=[10, 20, 30, 40], page=2)
    r = store.sheet_answers(sid)[0]
    assert r["box"] == [10, 20, 30, 40] and r["page"] == 2


def test_列表带错题数(db, tmp_path):
    name = _paper(tmp_path, "卡卷H")
    sid = store.create_sheet(name, "王五", None)
    store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="code")
    store.put_sheet_answer(sid, 2, verdict="right", verdict_by="code")
    store.put_sheet_answer(sid, 3, verdict="right", verdict_by="code")
    store.set_teacher_verdict(sid, 1, "right")      # 老师改判后不该再算错
    s = store.list_sheets(name)[0]
    assert s["student"] == "王五" and s["answers"] == 3
    assert s["wrong"] == 0, "错题数要按改判后的算"


def test_建卡时卷子不存在就明说(db):
    try:
        store.create_sheet("根本没有这份卷子", None, None)
    except ValueError as e:
        assert "根本没有这份卷子" in str(e)
    else:
        raise AssertionError("卷子不存在应该当场抛")


def test_删卷子会连答题卡一起删(db, tmp_path):
    name = _paper(tmp_path, "卡卷G")
    sid = store.create_sheet(name, None, None)
    store.put_sheet_answer(sid, 1, raw_text="B")
    store.delete_papers([name])
    assert store.sheet_answers(sid) == []
