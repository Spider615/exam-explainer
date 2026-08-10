# -*- coding: utf-8 -*-
"""
卷子上印的分数进库，以及 `partial` 真的能一路走到底。

系统一分不算 —— 每小问的「X分(满分Y分)」和总分都印在答题卡上，Ⓑ 只是把它们
**转写**下来。转写下来的分数有三个用处：判「半对」、按丢分排薄弱点、
拿 Σ得分对总分查有没有读串。
"""
import store


def _card(name, student="张三"):
    store.create_answers_paper(name, None)
    return store.create_sheet(name, student, None)


def test_写入端认partial(db):
    store.create_answers_paper("分数用卷", None)
    qid = store.put_answer_question("分数用卷", 1203, "AB", None)
    sid = store.create_sheet("分数用卷", "张三", None)
    store.put_sheet_answer(sid, 1203, question_id=qid, raw_text="A",
                           verdict="partial", verdict_by="teacher_score",
                           score_got=1, score_full=2)
    r = store.sheet_answers(sid)[0]
    assert r["verdict"] == "partial" and r["verdict_by"] == "teacher_score"


def test_写入端挡得住拼错的判定(db):
    sid = _card("分数用拼错卷")
    try:
        store.put_sheet_answer(sid, 1, verdict="parital")
    except ValueError as e:
        assert "partial" in str(e)
    else:
        raise AssertionError("拼错的判定写进去了")


def test_写入端挡得住拼错的来源(db):
    sid = _card("分数用来源卷")
    try:
        store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="teacher_scores")
    except ValueError as e:
        assert "teacher_score" in str(e)
    else:
        raise AssertionError("拼错的来源写进去了")


def test_老师改得出半对(db):
    """
    `partial` 在白名单里 —— 加这个值之前，老师根本改不出「半对」。

    改判成半对**必须同时给分数**（半对是几分推不出来，猜一个就是编数据），
    这条规矩在 `tests/test_sheet_regrade.py` 里单独守着。
    """
    sid = _card("分数用改判卷")
    store.put_sheet_answer(sid, 1, verdict="wrong", verdict_by="teacher_score",
                           score_got=0, score_full=2)
    store.set_teacher_verdict(sid, 1, "partial", score_got=1)
    r = store.sheet_answers(sid)[0]
    assert r["final_verdict"] == "partial" and float(r["final_score_got"]) == 1


def test_分数存得下小数(db):
    """
    实测有 `7.5分(满分12分)`、总分 `58.5`。存整数会**静默**截断成 7 和 58，
    而薄弱知识点是按丢分率排的 —— 分母错了整个榜单都是错的。
    """
    sid = _card("分数用小数卷")
    store.put_sheet_answer(sid, 15, verdict="partial", score_got=7.5, score_full=12)
    store.set_sheet_total(sid, 58.5)
    r = store.sheet_answers(sid)[0]
    assert float(r["score_got"]) == 7.5 and float(r["score_full"]) == 12
    assert float(store.list_sheets("分数用小数卷")[0]["total"]) == 58.5


def test_列表里错题数不把半对漏掉(db):
    """
    `list_sheets` 原来数的是 `='wrong'`。加了 partial 之后，一张 8 道半对、
    2 道全错的卡会显示「错 2 道」—— 而它其实有 10 道没拿满分。
    """
    sid = _card("分数用列表卷")
    for n in range(1, 9):
        store.put_sheet_answer(sid, n, verdict="partial", score_got=1, score_full=2)
    for n in (9, 10):
        store.put_sheet_answer(sid, n, verdict="wrong", score_got=0, score_full=2)
    row = store.list_sheets("分数用列表卷")[0]
    assert row["wrong"] == 2
    assert row["partial"] == 8
    assert float(row["lost"]) == 8 * 1 + 2 * 2


def test_丢分按改判后的算(db):
    """
    和 `final_verdict` 一个口径。老师把一道 0/2 改判成对，这 2 分就不该再算丢。
    """
    sid = _card("分数用改判丢分卷")
    store.put_sheet_answer(sid, 1, verdict="wrong", score_got=0, score_full=2)
    store.put_sheet_answer(sid, 2, verdict="wrong", score_got=0, score_full=3)
    assert float(store.list_sheets("分数用改判丢分卷")[0]["lost"]) == 5
    store.set_teacher_verdict(sid, 1, "right")
    assert float(store.list_sheets("分数用改判丢分卷")[0]["lost"]) == 3


def test_空白和说不清不进丢分(db):
    """它们不是「答错了」，分子分母都不进"""
    sid = _card("分数用空白卷")
    store.put_sheet_answer(sid, 1, verdict="blank", score_got=0, score_full=2)
    store.put_sheet_answer(sid, 2, verdict="unsure", score_got=0, score_full=3)
    store.put_sheet_answer(sid, 3, verdict="wrong", score_got=0, score_full=1)
    assert float(store.list_sheets("分数用空白卷")[0]["lost"]) == 1


def test_没判过和没印分数分得开(db):
    """
    `score_got IS NULL` 同时能表示三件事：还没跑过 Ⓑb、跑过但这题没印分数、
    读出来是 0。第三件由 `0` 自己区分，前两件靠 `scored_at` ——
    和 `questions.kps_at` 完全同构（不加那一列的时候，答案卷永远到不了「已完成」）。
    """
    sid = _card("分数用判过卷")
    store.put_sheet_answer(sid, 1, raw_text="A")
    store.put_sheet_answer(sid, 2, raw_text="B", scored=True)
    rows = {r["n"]: r for r in store.sheet_answers(sid)}
    assert rows[1]["scored_at"] is None, "没跑过 Ⓑb"
    assert rows[2]["scored_at"] is not None, "跑过了，只是这题没印分数"


def test_重跑不许把分数冲掉(db):
    """
    `put_sheet_answer` 是「只更新这次给了的列」。Ⓒ 那一步只写 verdict，
    不该顺手把 Ⓑb 读出来的分数抹成 NULL。
    """
    sid = _card("分数用重跑卷")
    store.put_sheet_answer(sid, 1, raw_text="A", score_got=1, score_full=2, scored=True)
    store.put_sheet_answer(sid, 1, verdict="partial", verdict_by="teacher_score")
    r = store.sheet_answers(sid)[0]
    assert float(r["score_got"]) == 1 and float(r["score_full"]) == 2
    assert r["raw_text"] == "A"


def test_老师红笔写的正确答案存得下(db):
    """实测题 6 老师写了 BC、题 8 写了 AC —— 白捡的第三份对照"""
    sid = _card("分数用红笔卷")
    store.put_sheet_answer(sid, 6, raw_text="AC", teacher_red="BC", mark_raw="✗")
    r = store.sheet_answers(sid)[0]
    assert r["teacher_red"] == "BC" and r["mark_raw"] == "✗"
