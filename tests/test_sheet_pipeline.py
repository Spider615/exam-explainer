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


def test_小问编号错位时整题不绑(db, owner, tmp_path, fake_model):
    """
    答题卡上 12 题读出 (1)(3)，而参考答案只有 (1)(2) —— 卡上的 (3)
    **不在**参考答案里，说明两边编号体系不是一回事，(1) 的「精确相等」
    也不能信。整题不绑。

    （这条初版用的是「卡上少一条」当样本，而那种情况 2026-08-10 的实跑证明
    是**漏读**、不是错位，现在按 `kind="missing"` 处理、能绑的绑上。
    判据是**方向**：多出来的才是错位的证据。）
    """
    _paper("链用绑不上卷", owner, ns=(9, 11, 1201, 1202))
    sid = store.create_sheet("链用绑不上卷", "张三", owner)
    jid = "p" + "6" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用绑不上卷", sid, [_screenshot(tmp_path)], owner)
    rows = {r["n"]: r for r in store.sheet_answers(sid)}
    assert rows[1201]["question_id"] is None, "12 题的小问编号错位，不许绑"
    assert rows[9]["question_id"] is not None, "9 题自己对得上，不该受牵连"
    warns = store.sheet_reads(sid)["bindWarnings"]
    assert any(w["main"] == 12 and w["kind"] == "mismatch" for w in warns)


def test_少读一条小问时能绑的还是绑上(db, owner, tmp_path, fake_model):
    """
    卡上读出 12(1)(3)，参考答案有 12(1)(2)(3) —— 卡上的都在答案里，
    是**漏读**不是错位。一刀切「整题不绑」的代价，实跑里是 39 分的大题
    全都挂不上标准答案和知识点。
    """
    _paper("链用漏读卷", owner, ns=(9, 11, 1201, 1202, 1203))
    sid = store.create_sheet("链用漏读卷", "张三", owner)
    jid = "p" + "a" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "链用漏读卷", sid, [_screenshot(tmp_path)], owner)
    rows = {r["n"]: r for r in store.sheet_answers(sid)}
    assert rows[1201]["question_id"] is not None
    assert rows[1203]["question_id"] is not None
    warns = store.sheet_reads(sid)["bindWarnings"]
    assert any(w["main"] == 12 and w["kind"] == "missing" for w in warns)


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


def test_这一趟的结果要落在卡上(db, owner, tmp_path, fake_model):
    """
    跑完把卡标成 `done`。**任务表不算数** —— 它是进程内的 dict，重启就空，
    而「学生的答题卡」那张表要一直说得出这一份是什么状况。
    """
    _paper("状态落库卷", owner)
    sid = store.create_sheet("状态落库卷", "张三", owner)
    jid = "s" + "0" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}

    api.run_sheet_pipeline(jid, "状态落库卷", sid, [_screenshot(tmp_path)], owner)

    row = next(s for s in store.list_sheets("状态落库卷") if s["id"] == sid)
    assert row["state"] == "done"
    assert row["runSeconds"] is None


def test_失败要连原因一起落在卡上(db, owner, tmp_path, monkeypatch):
    """
    一条都没读出来 —— 卡上要留下**为什么**。只留一个「失败」的话，
    老师不知道该重传还是该等；而重启之后任务表里那句话就没了。
    """
    monkeypatch.setattr(sheetread.mathvlm, "ask_raw",
                        lambda *a, **k: [] if k.get("want") == "array" else {})
    _paper("状态落库失败卷", owner)
    sid = store.create_sheet("状态落库失败卷", "张三", owner)
    jid = "s" + "1" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}

    api.run_sheet_pipeline(jid, "状态落库失败卷", sid, [_screenshot(tmp_path)], owner)

    row = next(s for s in store.list_sheets("状态落库失败卷") if s["id"] == sid)
    assert row["state"] == "failed"
    assert "一道题都没读出来" in row["stateNote"]


def test_切图就失败也要落在卡上(db, owner, tmp_path, monkeypatch):
    """
    Ⓢ 挂了是**最该说清楚**的一种：图里根本没有答题卡，重传才有用。
    这一条走的是和上面那条不同的出口（`return`，不经过 Ⓑ），得单独钉。
    """
    monkeypatch.setattr(api.sheetcut, "cut",
                        lambda *a, **k: (_ for _ in ()).throw(
                            ValueError("没在这张图里找到答题卡")))
    _paper("状态落库切图卷", owner)
    sid = store.create_sheet("状态落库切图卷", "张三", owner)
    jid = "s" + "2" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}

    api.run_sheet_pipeline(jid, "状态落库切图卷", sid, [_screenshot(tmp_path)], owner)

    row = next(s for s in store.list_sheets("状态落库切图卷") if s["id"] == sid)
    assert row["state"] == "failed"
    assert "没在这张图里找到答题卡" in row["stateNote"]


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


# ---------------------------------------------------------------- 详情端点

def test_详情端点把该给的都给了(db, owner, tmp_path, fake_model):
    """
    页面上「你写的 X / 标准答案 Y」要并排显示。让前端为了这一栏再拉一次整卷
    （一两兆）是不划算的，所以标准答案从卷子那边带过来。
    """
    _paper("详情用卷", owner)
    sid = store.create_sheet("详情用卷", "张三", owner)
    jid = "d" + "0" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "详情用卷", sid, [_screenshot(tmp_path)], owner)

    got = api.sheet_detail(sid, user={"id": owner})
    assert got["student"] == "张三" and got["paper"] == "详情用卷"
    r = {x["n"]: x for x in got["rows"]}
    assert r[9]["refAnswer"] == "标准9", "标准答案要跟着一起给"
    assert r[9]["verdict"] and r[9]["verdictBy"]


def test_分数下发成数不是字符串(db, owner, tmp_path, fake_model):
    """
    numeric 列回来是 Decimal，json 编不动、前端也不该处理它。
    不转的话页面上会出现 "1" 和 1 混用，比大小当场出错。
    """
    _paper("详情用数卷", owner)
    sid = store.create_sheet("详情用数卷", "张三", owner)
    jid = "d" + "1" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "详情用数卷", sid, [_screenshot(tmp_path)], owner)

    got = api.sheet_detail(sid, user={"id": owner})
    assert isinstance(got["total"], float)
    assert isinstance(got["lost"], float)
    for r in got["rows"]:
        assert r["scoreGot"] is None or isinstance(r["scoreGot"], float)


def test_详情端点带出这一次跑成什么样(db, owner, tmp_path, fake_model):
    """页面要按块说「Ⓑb 第 2 页那一遍没读成」，靠的就是这一份"""
    _paper("详情用记账卷", owner)
    sid = store.create_sheet("详情用记账卷", "张三", owner)
    jid = "d" + "2" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "详情用记账卷", sid, [_screenshot(tmp_path)], owner)

    got = api.sheet_detail(sid, user={"id": owner})
    assert got["reads"]["calls"]
    assert "checksum" in got["reads"]


def test_别人的答题卡看不到(db, owner, conn):
    conn.execute("INSERT INTO users (id, email) VALUES (90599, 'pl2@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    _paper("详情用别人卷", 90599)
    sid = store.create_sheet("详情用别人卷", "李四", 90599)
    with pytest.raises(Exception):
        api.sheet_detail(sid, user={"id": owner})


# ---------------------------------------------------------------- 图片 URL
#
# 2026-08-11 页面上四张答题卡原图全裂了。原因是拼 URL 时漏了路由里的 `/img/`
# 那一段：路由是 `/api/sheets/{sid}/img/{fn}`，拼出来的是 `/api/sheets/{sid}/{fn}`。
#
# **这类错单元测试原本照不到**：两边各自都「对」，只有拼在一起才错。
# 所以这几条**拿真实的路由表去核**，不是自己写一遍预期的字符串——
# 自己写一遍的话，改了路由这里照样绿。

def _routes():
    from pipeline import api
    return [r.path for r in api.app.routes if hasattr(r, "path")]


def test_原图的url对得上真实路由(db, owner, tmp_path, fake_model):
    import re
    _paper("URL用卷", owner)
    sid = store.create_sheet("URL用卷", "张三", owner)
    jid = "u" + "0" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "URL用卷", sid, [_screenshot(tmp_path)], owner)

    got = api.sheet_detail(sid, user={"id": owner})
    assert got["pages"], "该有原图"
    pats = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$")
            for p in _routes()]
    for url in got["pages"]:
        assert any(p.match(url) for p in pats), \
            "这个 URL 没有任何路由接得住：%s" % url


def test_切片的url也对得上(db, owner):
    """
    切片的文件名里**不许有斜杠** —— 取图的路由是 `/img/{fn}`，
    多一段路径就没有路由接得住。这是 2026-08-11 图全裂的另一半。
    """
    import re
    _paper("URL用切片卷", owner)
    sid = store.create_sheet("URL用切片卷", "张三", owner)
    store.put_sheet_answer(sid, 9, raw_text="x",
                           crop_rel="sheet/%d/cp01-228.png" % sid)
    got = api.sheet_detail(sid, user={"id": owner})
    url = got["rows"][0]["crop"]
    pats = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$")
            for p in _routes()]
    assert any(p.match(url) for p in pats), "这个 URL 没有路由接得住：%s" % url


def test_逐题都挂上了原图切片(db, owner, tmp_path, fake_model):
    """
    **设计里管这个叫「老师一眼能校对的唯一红绿灯」。** 页面早就留了位置，
    但管线一直没往里填（`crop_rel` 从来没被写过），于是每一行都显示
    「这道题没有原图切片」—— 一个写好了却永远走不到的分支。
    """
    _paper("切片用卷", owner)
    sid = store.create_sheet("切片用卷", "张三", owner)
    jid = "c" + "0" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "切片用卷", sid, [_screenshot(tmp_path)], owner)
    rows = store.sheet_answers(sid)
    assert rows, "没读出题"
    assert all(r["crop_rel"] for r in rows), \
        "每道题都该挂上它所在那一条切片：%s" % [(r["n"], r["crop_rel"]) for r in rows]
    assert all("/" not in r["crop_rel"].split("/", 2)[-1] for r in rows), \
        "切片文件名里不许有斜杠，否则取图的路由接不住"


def test_详情端点带出同一份卷子的其他答题卡(db, owner):
    """
    一份卷子可以挂多份卡（一个学生一份，或者同一批图重跑几遍）。库里点卷名
    现在直接落到其中一份 —— 页面必须说得出**你在看谁**、还要能切过去。

    这一趟 `list_sheets` 本来就查了整份名单（只用了其中一行取摘要），
    兄弟卡是白捡的，不该为了一个切换器再拉一次整卷（一两兆）。
    """
    _paper("兄弟卡卷", owner)
    a = store.create_sheet("兄弟卡卷", "张三", owner)
    b = store.create_sheet("兄弟卡卷", "李四", owner)
    store.put_sheet_answer(a, 9, raw_text="x")

    got = api.sheet_detail(b, user={"id": owner})
    sib = {s["id"]: s for s in got["siblings"]}
    assert set(sib) == {a, b}, "自己也要在名单里 —— 切换器要显示当前是哪一份"
    assert sib[a]["student"] == "张三"
    # 读出几题要给：真实数据里学生名常常是空的，只靠名字分不出哪份是哪份
    assert sib[a]["answers"] == 1 and sib[b]["answers"] == 0


# ---------------------------------------------------------------- 落地端点
#
# `#/sheet/<卷名>` 这个地址现在的含义是「给我看这份卷子的诊断结果」——
# 书签、刷新、老地址 `#/p/<名>`、上传卡上那个「去看这份卷子 →」全落在它上面。
# 前端手上只有卷名时，得有一处能问出「该打开哪一份卡」。
#
# **不能拿整卷端点去问**：那是一两兆的载荷，为一次跳转拉它不划算。

def test_落地端点给出该打开哪一份卡和全部名单(db, owner):
    _paper("落地用卷", owner)
    a = store.create_sheet("落地用卷", "张三", owner)
    store.put_sheet_answer(a, 9, raw_text="x")
    got = api.paper_sheets("落地用卷", user={"id": owner})
    assert got["landing"] == a
    assert [s["id"] for s in got["sheets"]] == [a]


def test_落地端点跳过跑坏的空卡(db, owner):
    """
    和列表那条规则**必须是同一条**：跑坏的空卡建出来就删不掉、`created_at`
    最新永远排第一，落在它上面是一屏「0 分丢了 · 逐题合计对得上」。
    """
    _paper("落地跳空卡卷", owner)
    good = store.create_sheet("落地跳空卡卷", "张三", owner)
    store.put_sheet_answer(good, 9, raw_text="x")
    store.create_sheet("落地跳空卡卷", None, owner)          # 跑坏的
    got = api.paper_sheets("落地跳空卡卷", user={"id": owner})
    assert got["landing"] == good
    assert len(got["sheets"]) == 2, "名单照实给，空卡也在里面"


def test_落地端点和列表给的是同一份卡(db, owner):
    """
    两处各算一遍「该落到哪一份」，迟早会有一处先改。这条把它们钉在一起 ——
    对不上的话，从库里点和从书签进会打开**不同的学生**。
    """
    _paper("落地一致卷", owner)
    a = store.create_sheet("落地一致卷", "张三", owner)
    b = store.create_sheet("落地一致卷", "李四", owner)
    for sid in (a, b):
        store.put_sheet_answer(sid, 9, raw_text="x")
    store.create_sheet("落地一致卷", None, owner)             # 跑坏的，最新
    row = [r for r in store.list_papers(owner) if r["name"] == "落地一致卷"][0]
    got = api.paper_sheets("落地一致卷", user={"id": owner})
    assert got["landing"] == row["latestSheet"] == b


def test_一份卡都没有时不给落地目标(db, owner):
    """没有能看的诊断结果 → 前端留在卷子页，那里有 Ⓐ 的进度和上传入口"""
    _paper("落地无卡卷", owner)
    got = api.paper_sheets("落地无卡卷", user={"id": owner})
    assert got["landing"] is None and got["sheets"] == []


def test_别人的卷子问不到落地目标(db, owner, conn):
    conn.execute("INSERT INTO users (id, email) VALUES (90598, 'ld@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    _paper("落地别人卷", 90598)
    with pytest.raises(Exception):
        api.paper_sheets("落地别人卷", user={"id": owner})


# ---------------------------------------------------------------- 题干要跟着下发
#
# 「这道题问的是什么」原来只在**卷子页**上（一道大题一张卡，题干 + 原卷截图 +
# 标准答案 + 知识点）。而答题卡库点进去现在直接落到诊断页，那一层不再是必经之路 ——
# 老师看着「第 6 题 错」却不知道第 6 题在考什么。题干必须跟着逐题结果一起给。
#
# 用户原话：「只不过这里需要有一个地方显示题目是啥就行了」。

def test_详情端点带出题干和原卷截图(db, owner):
    """
    **原卷截图和题干两样都要。**

    Ⓔ 的提示词明确要求「插图只用一句话描述、不要转写坐标刻度」，所以转写的
    题干**把图丢了** —— 物理题一句「如图所示」之后什么都没有。截图是唯一的图。
    """
    _paper("详情用题干卷", owner)
    store.put_stem("详情用题干卷", 9, "第 9 题：如图所示，导体棒…")
    store.put_stem_image("详情用题干卷", 9, "mathimg/stem-q0009.png")
    sid = store.create_sheet("详情用题干卷", "张三", owner)
    # question_id 就是「挂上题了」——不绑的话这一行是「挂不上题」，本来就没有题干
    store.put_sheet_answer(sid, 9, raw_text="不变 / 17190",
                           question_id=store.question_ids("详情用题干卷")[9])

    r = api.sheet_detail(sid, user={"id": owner})["rows"][0]
    assert r["stem"] == "第 9 题：如图所示，导体棒…"
    assert r["stemImage"], "原卷截图要跟着给——题干把图丢了，截图是唯一的图"


def test_题干截图的url对得上真实路由(db, owner):
    """
    **拿真实的路由表核，不是自己再写一遍预期的字符串。**

    2026-08-11 答题卡原图全裂就是这么来的：拼 URL 的地方和路由各自看都「对」，
    只有拼在一起才错。自己写一遍预期字符串的话，改了路由这里照样绿。
    """
    import re
    _paper("题干URL卷", owner)
    store.put_stem_image("题干URL卷", 9, "mathimg/stem-q0009.png")
    sid = store.create_sheet("题干URL卷", "张三", owner)
    store.put_sheet_answer(sid, 9, raw_text="x",
                           question_id=store.question_ids("题干URL卷")[9])

    url = api.sheet_detail(sid, user={"id": owner})["rows"][0]["stemImage"]
    pats = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$")
            for p in _routes()]
    assert any(p.match(url) for p in pats), "这个 URL 没有路由接得住：%s" % url


def test_挂不上题的那几条没有题干(db, owner):
    """
    挂不上题 = 没绑到卷子上任何一道题，**自然就没有题干**。

    这里要的是 `None`，不是空字符串、更不是「随便找一道最近的题的题干」——
    错的题干比没有题干糟得多：老师会照着它判这道题该不该错。
    """
    _paper("挂不上题干卷", owner)
    sid = store.create_sheet("挂不上题干卷", "张三", owner)
    store.put_sheet_answer(sid, 1305, raw_text="3 m/s")     # 参考答案里没有 13(5)

    r = api.sheet_detail(sid, user={"id": owner})["rows"][0]
    assert r["bound"] is False
    assert r["stem"] is None and r["stemImage"] is None


# ---------------------------------------------------------------- 一次传完就出结果
#
# 原来传答题卡只是「收下存着」，老师得再进卷子、用另一个上传框传一次才真跑 ——
# 一次上传被拆成两处入口、两次等待。用户原话：「现在这个交互方式太差了」。

def test_三栏一起传时答题卡也跟着分析(db, owner, tmp_path, fake_model, monkeypatch):
    """传参考答案的同时传了答题卡 → 一条链跑到底，直接有逐题对错"""
    monkeypatch.setattr(api, "run_step", lambda *a, **k: True)
    store.create_answers_paper("一次跑完卷", owner)
    for n in (9, 11, 1201, 1202, 1203):
        store.put_answer_question("一次跑完卷", n, "标准%d" % n, None)

    jid = "o" + "0" * 11
    api.JOBS[jid] = {"state": "running", "log": []}
    api.run_answer_pipeline(jid, ["ref.png"], "一次跑完卷", owner, False,
                            extra=[("stem", []),
                                   ("sheet", [_screenshot(tmp_path)])])
    assert api.JOBS[jid]["state"] == "done", api.JOBS[jid].get("err")
    sid = api.JOBS[jid]["sheet"]
    assert sid, "该建出一份答题卡"
    assert store.sheet_answers(sid), "该有逐题结果，不能只是收下存着"


def test_答题卡跑挂了不许把任务报成完成(db, owner, tmp_path, monkeypatch):
    """
    **`run_sheet_pipeline` 的软失败会被无条件盖成 done。**

    它那两条失败分支（Ⓢ 抠不出答题卡、一道题都没读出来）是 `return` 不是
    `raise`，写完 `state="error"` 就回来了；外层紧接着一句无条件的
    `JOBS[jid].update(state="done")` 把它盖掉 —— 于是一次彻底失败的分析，
    在上传卡上显示「完成」，而库里留着一张 0 行的空卡。

    这正是「不许用 UI 掩盖失败」那条规矩要挡的东西。
    """
    monkeypatch.setattr(api, "run_step", lambda *a, **k: True)
    store.create_answers_paper("跑挂了卷", owner)
    store.put_answer_question("跑挂了卷", 9, "标准9", None)

    # Ⓢ 抠不出答题卡：喂一张纯黑图，`sheetcut` 找不到亮带
    black = tmp_path / "black.png"
    Image.fromarray(np.zeros((600, 400), dtype=np.uint8), mode="L").convert(
        "RGB").save(black)

    jid = "f" + "0" * 11
    api.JOBS[jid] = {"state": "running", "log": []}
    api.run_answer_pipeline(jid, ["ref.png"], "跑挂了卷", owner, False,
                            extra=[("stem", []), ("sheet", [str(black)])])
    assert api.JOBS[jid]["state"] == "error", \
        "答题卡那一步挂了，整趟任务就不是「完成」：%s" % api.JOBS[jid].get("err")


def test_没传答题卡时不建空卡(db, owner, monkeypatch):
    """答题卡那一栏是选填的，没传就不该冒出一份空卡"""
    monkeypatch.setattr(api, "run_step", lambda *a, **k: True)
    store.create_answers_paper("没答题卡卷", owner)
    store.put_answer_question("没答题卡卷", 9, "A", None)
    jid = "o" + "1" * 11
    api.JOBS[jid] = {"state": "running", "log": []}
    api.run_answer_pipeline(jid, ["ref.png"], "没答题卡卷", owner, False,
                            extra=[("stem", []), ("sheet", [])])
    assert api.JOBS[jid]["state"] == "done"
    assert api.JOBS[jid]["sheet"] is None
    assert store.list_sheets("没答题卡卷") == []


def test_任务里带着卡号好让页面直接跳过去(db, owner, tmp_path, fake_model, monkeypatch):
    """传完落在结果页，而不是让人再自己找一遍"""
    monkeypatch.setattr(api, "run_step", lambda *a, **k: True)
    store.create_answers_paper("跳转用卷", owner)
    store.put_answer_question("跳转用卷", 9, "A", None)
    jid = "o" + "2" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "owner_id": owner}
    api.run_answer_pipeline(jid, ["ref.png"], "跳转用卷", owner, False,
                            extra=[("stem", []),
                                   ("sheet", [_screenshot(tmp_path)])])
    assert api.job(jid, user={"id": owner})["sheet"] == api.JOBS[jid]["sheet"]
