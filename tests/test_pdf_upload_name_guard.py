# -*- coding: utf-8 -*-
"""
PDF 上传撞上一份**答题卡卷子**时必须改名 —— 这是 `create_answers_paper`
那道护栏的反方向，两边都要有。

为什么这条比它的反方向更狠
--------------------------
`store.publish` 是**整卷替换**：删光 `questions` 再插一遍。而答案卷值钱的东西
全挂在 `questions` 上 —— `ref_answer`（标准答案）、`ref_solution`（官方解答过程）、
`kps`（知识点）；步二上线之后，学生的作答（`sheet_answers`）还以
`ON DELETE CASCADE` 挂在它下面，**那是不可再生的**：参考答案可以重读，
学生那张已批改的答题卡老师未必还留着。

上传那段原本的判据是「撞上**别人**的卷子才改名，自己的算重传、当重跑」。
这条对 PDF 链成立（重跑一遍 ①②③ 得到的还是同一份卷子），对答案卷**不成立**：
PDF 链根本不是它的上游，跑一遍不是重跑，是覆盖。老师手上有一份
`2025-2026高二物理期末` 的答案卷，随手把同名的题目 PDF 也传进解析试卷那一栏，
参考答案、官方解答、知识点、学生作答当场全没，**而且一句提示都没有**。
"""
import pytest

import store
from pipeline import api


@pytest.fixture
def uid(conn):
    conn.execute("INSERT INTO users (id, email) VALUES "
                 "(90101, 'pdfguard@test.local') ON CONFLICT (id) DO NOTHING")
    conn.commit()
    yield 90101
    with store.connect() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM papers WHERE owner_id = 90101")
        cur.execute("DELETE FROM users WHERE id = 90101")
        c.commit()


def test_没人占的卷名原样用(db, uid):
    assert api.upload_name_for("上传护栏用新卷", uid, {}) == "上传护栏用新卷"


def _pdf_paper(conn, name, owner):
    conn.execute("INSERT INTO papers (name, n_questions, source_kind, owner_id) "
                 "VALUES (%s, 16, 'pdf', %s)", (name, owner))
    conn.commit()


def test_自己的解析试卷算重跑不改名(db, uid, conn):
    """这条是原有行为，不能被这次改动误伤 —— 重传同一份 PDF 就是重跑"""
    _pdf_paper(conn, "上传护栏用真题卷", uid)
    assert api.upload_name_for("上传护栏用真题卷", uid, {}) == "上传护栏用真题卷"


def test_撞上自己的答题卡卷子必须改名(db, uid):
    """
    **本文件的主角。** 不改名的话，run_pipeline 跑完 publish 会把这份答案卷的
    questions 整批删掉重插 —— 参考答案、官方解答、知识点全没，
    学生的作答顺着 ON DELETE CASCADE 一起走。
    """
    store.create_answers_paper("上传护栏用答案卷", uid)
    got = api.upload_name_for("上传护栏用答案卷", uid, {})
    assert got != "上传护栏用答案卷", "撞上自己的答题卡卷子时没有改名，publish 会覆盖它"
    assert got == "上传护栏用答案卷 (2)"


def test_改名之后那份答案卷一个字没动(db, uid):
    store.create_answers_paper("上传护栏用答案卷2", uid)
    api.upload_name_for("上传护栏用答案卷2", uid, {})
    assert store.source_kind_of("上传护栏用答案卷2") == "answers_only"
    assert store.paper_owner("上传护栏用答案卷2") == (True, uid)


def test_撞上别人的卷子照旧改名(db, uid, conn):
    conn.execute("INSERT INTO users (id, email) VALUES "
                 "(90102, 'pdfguard-b@test.local') ON CONFLICT (id) DO NOTHING")
    conn.commit()
    try:
        _pdf_paper(conn, "上传护栏用别人卷", 90102)
        assert api.upload_name_for("上传护栏用别人卷", uid, {}) == "上传护栏用别人卷 (2)"
    finally:
        with store.connect() as c:
            cur = c.cursor()
            cur.execute("DELETE FROM papers WHERE owner_id = 90102")
            cur.execute("DELETE FROM users WHERE id = 90102")
            c.commit()


def test_还没入库但已经被别人开跑的名字也算占了(db, uid):
    """CLAIMS 那几分钟的窗口 —— 卷子跑完 ①②②b 才 publish，在那之前库里查不到"""
    assert api.upload_name_for("上传护栏用开跑卷", uid,
                               {"上传护栏用开跑卷": 90999}) == "上传护栏用开跑卷 (2)"


def test_自己开跑的名字不算占了(db, uid):
    assert api.upload_name_for("上传护栏用自己开跑卷", uid,
                               {"上传护栏用自己开跑卷": uid}) == "上传护栏用自己开跑卷"
