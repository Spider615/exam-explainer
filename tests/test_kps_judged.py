# -*- coding: utf-8 -*-
"""
「③c 判过这道题」和「③c 给这道题挂上了标签」是两件事。

参考答案那条链上，只有一个字母答案（`D` / `BC`）的题**永远挂不上** ——
判不出考什么不是 bug，是那个字母里真的不含这个信息。可是只要把「挂上几道」
当分子，这份卷子就永远到不了「已完成」，页面上永远写着「已停止」。

用户两次问「为啥停止了」。而仓库自己在 `stage_of` 的注释里早就记过同一个
教训：「⑤ 的分子必须是『试过几道』而不是『绿灯几道』—— 有一道怎么都过不了
门禁的话，按绿灯数算就永远差一个，永远显示在跑」。
"""
import pytest

import modes
import store

SHEET = dict(questions=26, labels=0, kps=9, solutions=0, judged=0, worth=0,
             specs=0, specsWorth=0, drafts=0, ready=0, sceneTried=0,
             assembledFresh=False, sourceKind="answers_only")


def test_挂不上但判过了就算做完():
    """26 道判了 26 道、只挂上 9 道 —— 这是**做完了**，不是停住了"""
    assert modes.of("answers_only").stage_of({**SHEET, "kpsJudged": 26})[0] == "done"


def test_还没判完的才叫没做完():
    code, label, short, cur, total = modes.of("answers_only").stage_of(
        {**SHEET, "kpsJudged": 10})
    assert code == "kpmark"
    assert (cur, total) == (10, 26), "分子要报判过几道，不是挂上几道"


def test_一道都没判过时不是done():
    assert modes.of("answers_only").stage_of({**SHEET, "kpsJudged": 0})[0] == "kpmark"


def test_解析试卷那条链同一个口径():
    """
    那条链上也可能有怎么都挂不上的题。按「挂上几道」算的话，一份跑完的卷子
    会卡在 ③c 上，④⑤⑦ 永远轮不到
    """
    pdf = dict(questions=16, labels=16, kps=14, solutions=16, solutionFailures=0,
               judged=16, worth=6, specs=6, specsWorth=6, approved=6, drafts=0,
               ready=6, sceneTried=6, assembledFresh=True, sourceKind="pdf")
    assert modes.of("pdf").stage_of({**pdf, "kpsJudged": 16})[0] == "done"
    assert modes.of("pdf").stage_of({**pdf, "kpsJudged": 9})[0] == "kpmark"


def test_没有这个键时退回旧口径():
    """
    打桩的进度字典（test_stage_of.py 那些）没有这个键。退不回去的话，
    那几份「不许改」的测试会集体红，而它们是「没碰坏解析试卷那条链」的凭据
    """
    assert modes.of("answers_only").stage_of(SHEET)[0] == "kpmark"
    assert modes.of("answers_only").stage_of({**SHEET, "kps": 26})[0] == "done"


# ---------------------------------------------------------------- 库那一侧
@pytest.fixture
def 一份判过的卷子(db):
    store.create_answers_paper("判过没挂上的卷", None)
    qid_a = store.put_answer_question("判过没挂上的卷", 1, "D", None)
    qid_b = store.put_answer_question("判过没挂上的卷", 11, "2BIL / MP", "由安培力公式")
    yield "判过没挂上的卷", qid_a, qid_b
    with store.connect() as c:
        c.execute("DELETE FROM papers WHERE name='判过没挂上的卷'")
        c.commit()


def test_写空标签也算判过(一份判过的卷子):
    """
    「判过、但一个都挂不上」要落一笔，否则它和「还没判过」在库里长得一样
    """
    name, qid_a, qid_b = 一份判过的卷子
    assert store.progress(name)["kpsJudged"] == 0
    store.put_kps(qid_a, [])
    assert store.progress(name)["kpsJudged"] == 1
    assert store.progress(name)["kps"] == 0, "空标签不算挂上"


def test_挂上标签的两个数都涨(一份判过的卷子):
    name, qid_a, qid_b = 一份判过的卷子
    store.put_kps(qid_b, [{"code": "3.2.1", "why": "安培力"}])
    pg = store.progress(name)
    assert (pg["kps"], pg["kpsJudged"]) == (1, 1)


def test_两道都判过之后这份卷子就完成了(一份判过的卷子):
    """挂上 1 道、判过 2 道 —— 该是「已完成」，不是「已停止」"""
    name, qid_a, qid_b = 一份判过的卷子
    store.put_kps(qid_a, [])
    store.put_kps(qid_b, [{"code": "3.2.1", "why": "安培力"}])
    pg = store.progress(name)
    assert modes.of(pg["sourceKind"]).stage_of(pg)[0] == "done"
