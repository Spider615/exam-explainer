# -*- coding: utf-8 -*-
"""
整卷读回要带上 `sourceKind`。

页面靠它把**解析试卷**和**答题卡诊断**分开。这两个是两个功能：
前者只讲题，后者才判学生对错。判卷的话术（「这道题会记『判不了』，不算错」）
出现在一份普通高考真题上是错的 —— 那份卷子根本没有学生答案要判。

原来 `sourceKind` 只在 `progress()` 里有，而进度是轮询回来的、还带延迟，
拿它决定一句话显不显示会闪。整卷本来就该知道自己是哪种卷子。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import store


def _paper(conn, name, kind):
    conn.execute("INSERT INTO papers (name, source_kind) VALUES (%s, %s)", (name, kind))
    conn.commit()


def test_普通试卷回_pdf(conn):
    _paper(conn, "卷甲", "pdf")
    assert store.get_paper("卷甲")["sourceKind"] == "pdf"


def test_答案卷回_answers_only(conn):
    _paper(conn, "卷乙", "answers_only")
    assert store.get_paper("卷乙")["sourceKind"] == "answers_only"


def test_没有这份卷子仍然回_None(conn):
    assert store.get_paper("查无此卷") is None


def test_老数据没写_source_kind_时按普通试卷算(conn):
    """建库早于这一列的卷子不能因此掉进判卷那条分支。"""
    conn.execute("INSERT INTO papers (name) VALUES (%s)", ("卷丙",))
    conn.commit()
    assert store.get_paper("卷丙")["sourceKind"] == "pdf"
