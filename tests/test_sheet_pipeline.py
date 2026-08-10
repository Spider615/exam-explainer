# -*- coding: utf-8 -*-
"""
答题卡整条链：Ⓢ 抠图 → Ⓑ 读批改 → Ⓒ 判定 → 落库。

**模型全打桩。** 桩喂进去的是探针在真材料上读出来的东西（第 1 页那 18 条），
所以这里验的是「接线对不对」，不是「模型准不准」—— 后者归 Task 10 的实跑。
"""
import numpy as np
import pytest
from PIL import Image

import sheetread
import store
from pipeline import api


@pytest.fixture
def owner(conn):
    conn.execute("INSERT INTO users (id, email) VALUES (90501, 'pl@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    return 90501


def _screenshot(tmp_path, name="s.png"):
    """一张「手机截图」：上下压暗、中间一条亮的、亮带中间一道缝"""
    a = np.full((600, 400), 30, dtype=np.uint8)
    a[200:400, :] = 250
    a[200:400, 198:202] = 40
    p = tmp_path / name
    Image.fromarray(a, mode="L").convert("RGB").save(p)
    return str(p)


# 探针在真材料上读出来的（第 1 页，节选）。桩就用它，别编。
FAKE_A = [
    {"n": "9", "y": 0.49, "answer": "不变 / 17190", "mark": "right", "conf": "high"},
    {"n": "11", "y": 0.568, "answer": "BIL / MQ", "mark": "wrong", "conf": "high"},
    {"n": "12(1)", "y": 0.638, "answer": "170 / B", "mark": "half", "conf": "high"},
    {"n": "12(3)", "y": 0.718, "answer": "A", "mark": "right", "conf": "high"},
]
FAKE_B = [
    {"n": "9", "got": 3, "full": 3, "conf": "high"},
    {"n": "11", "got": 0, "full": 3, "conf": "high"},
    {"n": "12(1)", "got": 1, "full": 2, "conf": "high"},
    # ★ 全场最要紧的一条：老师打了勾，只给了 1 分（满分 2 分）
    {"n": "12(3)", "got": 1, "full": 2, "conf": "high"},
]
FAKE_C = {"total": 5}


@pytest.fixture
def fake_model(monkeypatch):
    """按提示词分辨这是哪一遍。Ⓑc 要 object，其余要 array"""
    calls = []

    def ask(img, prompt, want="object", timeout=240, backend=None):
        calls.append(prompt[:12])
        if want == "object":
            return dict(FAKE_C)
        if "一整页" in prompt:
            return [dict(r) for r in FAKE_A]
        return [dict(r) for r in FAKE_B]

    monkeypatch.setattr(sheetread.mathvlm, "ask_raw", ask)
    return calls


def _paper(name, owner, ns=(9, 11, 1201, 1202, 1203)):
    store.create_answers_paper(name, owner)
    for n in ns:
        store.put_answer_question(name, n, "标准%d" % n, None)


# ---------------------------------------------------------------- 整条链

def test_跑完一份卡逐题落库(db, owner, tmp_path, fake_model):
    _paper("链用卷", owner)
    sid = store.create_sheet("链用卷", "张三", owner)
    jid = "p" + "0" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用卷", sid, [_screenshot(tmp_path)], owner)
    assert api.JOBS[jid]["state"] == "done", api.JOBS[jid].get("err")
    rows = {r["n"]: r for r in store.sheet_answers(sid)}
    assert set(rows) == {9, 11, 1201, 1203}


def test_半对没有被判成全对(db, owner, tmp_path, fake_model):
    """
    12(3)：老师打了红勾、给 1分(满分2分)。只看勾叉会判成 right ——
    这道题会被记成掌握了，而它正是这轮探针推翻原设计的那个例子。
    """
    _paper("链用半对卷", owner)
    sid = store.create_sheet("链用半对卷", "张三", owner)
    jid = "p" + "1" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用半对卷", sid, [_screenshot(tmp_path)], owner)
    r = {x["n"]: x for x in store.sheet_answers(sid)}[1203]
    assert r["verdict"] == "partial"
    assert r["verdict_by"] == "teacher_score"
    assert float(r["score_got"]) == 1 and float(r["score_full"]) == 2


def test_分数和判过的标记都落了库(db, owner, tmp_path, fake_model):
    _paper("链用分数卷", owner)
    sid = store.create_sheet("链用分数卷", "张三", owner)
    jid = "p" + "2" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用分数卷", sid, [_screenshot(tmp_path)], owner)
    for r in store.sheet_answers(sid):
        assert r["scored_at"] is not None, "Ⓑb 判过的行要标出来"
    assert float(store.list_sheets("链用分数卷")[0]["total"]) == 5


def test_每次子调用都落了一行(db, owner, tmp_path, fake_model):
    """
    没有这个的话，「Ⓑb 第 2 页整遍失败」和「这几道题本来就读不出」
    在页面上完全同形。
    """
    _paper("链用记账卷", owner)
    sid = store.create_sheet("链用记账卷", "张三", owner)
    jid = "p" + "3" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用记账卷", sid, [_screenshot(tmp_path)], owner)
    reads = store.sheet_reads(sid)
    assert reads["calls"], "一次子调用都没记"
    assert {c["pass"] for c in reads["calls"]} >= {"Ⓑa", "Ⓑb", "Ⓑc"}
    assert all("seconds" in c for c in reads["calls"])


def test_对总分的结果也落库(db, owner, tmp_path, fake_model):
    _paper("链用总分卷", owner)
    sid = store.create_sheet("链用总分卷", "张三", owner)
    jid = "p" + "4" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用总分卷", sid, [_screenshot(tmp_path)], owner)
    reads = store.sheet_reads(sid)
    assert "checksum" in reads and isinstance(reads["checksum"][0], bool)


# ---------------------------------------------------------------- 闸门与告警

def test_题号一个都对不上就停下来(db, owner, tmp_path, fake_model):
    """
    这几张图多半不是这份卷子的答题卡。继续读只会把剩下几页的调用也花掉，
    换一份全是 unsure 的报告。
    """
    _paper("链用不对卷", owner, ns=(50, 51))
    sid = store.create_sheet("链用不对卷", "张三", owner)
    jid = "p" + "5" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用不对卷", sid,
                           [_screenshot(tmp_path, "a.png"),
                            _screenshot(tmp_path, "b.png")], owner)
    reads = store.sheet_reads(sid)
    assert reads.get("aborted"), "该停没停"
    # 只该跑第 1 页 —— 第 2 页的调用一次都不该发生
    assert {c["page"] for c in reads["calls"]} == {1}


def test_小问编号对不上时整题不绑(db, owner, tmp_path, fake_model):
    """
    答题卡上 12 题只有 (1)(3)，参考答案有 (1)(2)(3)。
    1201/1203 都精确命中已有题号，逐条绑会绑上——而两边的编号体系未必是一回事。
    """
    _paper("链用绑不上卷", owner, ns=(9, 11, 1201, 1202, 1203))
    sid = store.create_sheet("链用绑不上卷", "张三", owner)
    jid = "p" + "6" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用绑不上卷", sid, [_screenshot(tmp_path)], owner)
    rows = {r["n"]: r for r in store.sheet_answers(sid)}
    assert rows[1201]["question_id"] is None, "12 题的小问集合对不上，不许绑"
    assert rows[9]["question_id"] is not None, "9 题自己对得上，不该受牵连"
    assert any(w["main"] == 12 for w in store.sheet_reads(sid)["bindWarnings"])


def test_模型整遍失败要和读不出来分得开(db, owner, tmp_path, monkeypatch):
    """
    Ⓑa 报了 N 条而 Ⓑb 一条都没回 —— 那不是「这些题没有分数」，是那一遍挂了。
    """
    def ask(img, prompt, want="object", timeout=240, backend=None):
        if want == "object":
            return {"total": None}
        if "一整页" in prompt:
            return [dict(r) for r in FAKE_A]
        raise RuntimeError("方舟超时")

    monkeypatch.setattr(sheetread.mathvlm, "ask_raw", ask)
    _paper("链用整遍挂卷", owner)
    sid = store.create_sheet("链用整遍挂卷", "张三", owner)
    jid = "p" + "7" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用整遍挂卷", sid, [_screenshot(tmp_path)], owner)
    reads = store.sheet_reads(sid)
    assert any(c["pass"] == "Ⓑb" and not c["ok"] for c in reads["calls"])
    assert any("整遍" in c["why"] for c in reads["clashes"])


def test_一条都没读出来算失败(db, owner, tmp_path, monkeypatch):
    """读不出任何东西就得老实失败，不能留一份空卡装作跑完了"""
    monkeypatch.setattr(sheetread.mathvlm, "ask_raw",
                        lambda *a, **k: [] if k.get("want") == "array" else {})
    _paper("链用全空卷", owner)
    sid = store.create_sheet("链用全空卷", "张三", owner)
    jid = "p" + "8" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用全空卷", sid, [_screenshot(tmp_path)], owner)
    assert api.JOBS[jid]["state"] == "error"
    assert api.JOBS[jid]["err_code"] == "sheetread"


def test_失败也不删已有的作答(db, owner, tmp_path, monkeypatch):
    monkeypatch.setattr(sheetread.mathvlm, "ask_raw",
                        lambda *a, **k: [] if k.get("want") == "array" else {})
    _paper("链用保作答卷", owner)
    sid = store.create_sheet("链用保作答卷", "张三", owner)
    store.put_sheet_answer(sid, 9, raw_text="上一次读出来的")
    jid = "p" + "9" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用保作答卷", sid, [_screenshot(tmp_path)], owner)
    assert store.sheet_answers(sid)[0]["raw_text"] == "上一次读出来的"
