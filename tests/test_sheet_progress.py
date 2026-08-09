# -*- coding: utf-8 -*-
"""
答题卡的进度和失败必须有**它自己的**出口，而且不许拖累卷子本身的进度。

这是「进度永远走不到头」那次事故的镜像版 —— **两个方向都会撒谎**：

| 做法 | 后果 |
|---|---|
| 往 `modes.SHEET` **加**格子 | 没传答题卡的答案卷永远 `code != "done"`，整批退回「未完成」；连锁：`failure_note` 复活旧失败、`resume_gate` 的 done 闸失效 |
| **不加**格子，也不给答题卡别的出口 | `_stage_of_sheet` 在 ③c 完成后直接 `return "done"`，Ⓑ 跑多久卷子都写「已完成」；`store.progress` 的 `GREATEST` 不含答题卡两张表，`lastChange` 纹丝不动、`busy` 必然翻假（Ⓑa 实测一页 235 秒 > 180 秒的 idle 阈值），页面进度区整块不渲染 |

**结论：不加格子，答题卡走它自己的出口。** 理由和 `stemread` 不占格同源 ——
答题卡是选填的，给它一格要么永远灰着（读作卡住了）、要么打勾（撒谎说读过了）。
"""
import modes
import store

BASE = {"questions": 26, "solutions": 0, "labels": 0, "kps": 26, "kpsJudged": 26,
        "judged": 0, "worth": 0, "specsWorth": 0, "specs": 0, "drafts": 0,
        "sceneTried": 0, "ready": 0, "assembledFresh": False,
        "sourceKind": "answers_only"}


def test_没有答题卡的答案卷仍然是完成():
    """答题卡是选填的。因为「还没传答题卡」就把卷子判成没跑完，是撒谎"""
    assert modes.of("answers_only").stage_of(BASE)[0] == "done"


def test_有答题卡但一题没读的答案卷也仍然是完成():
    """卷子本身的进度说的是**参考答案侧**跑完没有，跟答题卡读到哪无关"""
    pg = dict(BASE, sheets=1, sheetAnswers=0)
    assert modes.of("answers_only").stage_of(pg)[0] == "done"


def test_答题卡不占格子():
    assert modes.SHEET.cells == ["refread", "kpmark"]


def test_stage_of不许硬取答题卡的键():
    """
    新分支一律 `pg.get`。`tests/test_stage_answers_only.py` 的 BASE 里一个
    sheet 键都没有，硬取会 KeyError，让 `/api/papers` 整个 500。
    """
    modes.of("answers_only").stage_of(BASE)          # 不带 sheet 键，不许抛


# ---------------------------------------------------------------- 卷子的进度要跟着答题卡动

def _paper_with_q(name):
    store.create_answers_paper(name, None)
    store.put_answer_question(name, 1, "A", None)


def test_落一条作答会让lastChange前移(db):
    """
    `store.progress` 的 `GREATEST` 原来只含 papers/solutions/specs/scenes。
    不含答题卡两张表的话，Ⓑ 边读边落库，`lastChange` 纹丝不动 ——
    而前端拿它当重载 key，逐题结果落了库页面一条都不出现。
    """
    _paper_with_q("进度用卷")
    before = store.progress("进度用卷")["lastChange"]
    sid = store.create_sheet("进度用卷", "张三", None)
    store.put_sheet_answer(sid, 1, raw_text="B")
    assert store.progress("进度用卷")["lastChange"] > before


def test_刚落过作答的卷子是busy(db):
    """
    `busy` 是 `idle < 180`，而 Ⓑa 实测一页要 235 秒。不把答题卡算进
    `lastChange` 的话，Ⓑ 跑到第二页时 `busy` 已经翻假，页面上那块
    `pg.busy || !pg.done` 的进度区整块消失 —— 人分不出「在跑」和「挂了」。
    """
    _paper_with_q("进度用busy卷")
    sid = store.create_sheet("进度用busy卷", "张三", None)
    store.put_sheet_answer(sid, 1, raw_text="B")
    assert store.progress("进度用busy卷")["busy"] is True


def test_新建一份空答题卡也算动过(db):
    """
    建卡到读出第一题之间隔着 Ⓢ 和 Ⓑa 的第一次调用（实测四分钟往上）。
    这一段不算「动过」的话，页面在最容易让人以为卡死的那几分钟里恰好是静的。
    """
    _paper_with_q("进度用建卡卷")
    before = store.progress("进度用建卡卷")["lastChange"]
    store.create_sheet("进度用建卡卷", "张三", None)
    assert store.progress("进度用建卡卷")["lastChange"] > before


def test_答题卡的动静不影响解析试卷(db, tmp_path):
    """加的那两个子查询不能让 pdf 卷子的 lastChange 变成别的东西"""
    d = tmp_path / "pdf卷"
    d.mkdir()
    (d / "questions.json").write_text(
        '{"source":"x.pdf","sections":[],"warnings":[],"dropped_boilerplate":[],'
        '"questions":[{"n":1,"stem":"题1"}]}', encoding="utf-8")
    store.publish(str(d), name="进度用pdf卷")
    a = store.progress("进度用pdf卷")["lastChange"]
    b = store.progress("进度用pdf卷")["lastChange"]
    assert a == b


# ---------------------------------------------------------------- 卷子详情要带出答题卡

def test_卷子详情带出它的答题卡列表(db, conn):
    """页面要按卡画进度和失败，卡的清单得跟着卷子一起下发"""
    from pipeline import api
    conn.execute("INSERT INTO users (id, email) VALUES (90301, 'sp@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    store.create_answers_paper("进度用列表卷", 90301)
    store.put_answer_question("进度用列表卷", 1, "A", None)
    sid = store.create_sheet("进度用列表卷", "张三", 90301)
    store.put_sheet_answer(sid, 1, raw_text="B")
    got = api.paper("进度用列表卷", user={"id": 90301})
    assert [s["id"] for s in got["sheets"]] == [sid]
    assert got["sheets"][0]["student"] == "张三"


def test_解析试卷不带sheets那一栏(db, tmp_path, conn):
    """解析试卷压根没有答题卡这回事，不必为它多查一次库"""
    from pipeline import api
    conn.execute("INSERT INTO users (id, email) VALUES (90302, 'sp2@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    d = tmp_path / "pdf卷2"
    d.mkdir()
    (d / "questions.json").write_text(
        '{"source":"x.pdf","sections":[],"warnings":[],"dropped_boilerplate":[],'
        '"questions":[{"n":1,"stem":"题1"}]}', encoding="utf-8")
    store.publish(str(d), name="进度用pdf卷2", owner_id=90302)
    assert api.paper("进度用pdf卷2", user={"id": 90302}).get("sheets") is None
