# -*- coding: utf-8 -*-
"""
答题卡上传：两道零成本闸门、按卡存料、以及不许删掉带着作答的卷子。

**闸门要排在模型调用前面。** 这是这个仓库已经定过的规矩（④c 判「值不值得做
动画」只要 28 秒，所以挪到了要 6 分钟的 ④ 前面）。没有闸门的话，一份还没读
参考答案的卷子照样会把 Ⓑ 跑满 —— 十几次调用、二十来分钟，产出一份全是
`unsure` 的空报告，而那份报告看起来和「这孩子什么都不会」一模一样。

**路径要按卡分。** 一份卷子挂多份答题卡（一个学生一份），而 `stash.py` 现在
存的是卷子级的 `sheet/pNN.png`。第二个学生会就地覆盖第一个学生的原图，
而第一份诊断的 `crop_rel` 还指着那个路径 —— 页面上第一个学生的「原图切片」
显示的是**第二个学生**的作答。红绿灯指错了人，比没有红绿灯更糟。
"""
import pytest
from fastapi import HTTPException

import store
from pipeline import api


@pytest.fixture
def owner(conn):
    conn.execute("INSERT INTO users (id, email) VALUES (90401, 'su@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    return 90401


# ---------------------------------------------------------------- 闸门

def test_卷子还没读出题就拒收答题卡(db, owner):
    """
    零成本闸门。判据是 `questions = 0` —— 没有题号清单，Ⓑ 读出来的每一条都
    挂不上，整份报告只会是一片 `unsure`。
    """
    store.create_answers_paper("闸门用空卷", owner)
    with pytest.raises(HTTPException) as e:
        api.sheet_upload_gate("闸门用空卷", owner)
    assert e.value.status_code == 400
    assert "参考答案" in e.value.detail


def test_读出题了就放行(db, owner):
    store.create_answers_paper("闸门用好卷", owner)
    store.put_answer_question("闸门用好卷", 1, "A", None)
    api.sheet_upload_gate("闸门用好卷", owner)          # 不许抛


def test_卷子不存在就拒(db, owner):
    with pytest.raises(HTTPException) as e:
        api.sheet_upload_gate("闸门用没有的卷", owner)
    assert e.value.status_code == 404


def test_解析试卷不收答题卡(db, owner, conn):
    """
    答题卡挂在 `answers_only` 这条链上。往一份解析试卷上传答题卡是走错了门，
    要当场说清楚 —— 不说的话它会建出一份挂在 pdf 卷子上的卡，
    而那条链根本没有 Ⓐ 给的题号清单。
    """
    conn.execute("INSERT INTO papers (name, n_questions, source_kind, owner_id) "
                 "VALUES ('闸门用真题卷', 16, 'pdf', %s)", (owner,))
    conn.commit()
    with pytest.raises(HTTPException) as e:
        api.sheet_upload_gate("闸门用真题卷", owner)
    assert e.value.status_code == 400
    assert "解析试卷" in e.value.detail


def test_别人的卷子取不到(db, owner, conn):
    conn.execute("INSERT INTO users (id, email) VALUES (90499, 'su2@test.local') "
                 "ON CONFLICT (id) DO NOTHING")
    conn.commit()
    store.create_answers_paper("闸门用别人卷", 90499)
    with pytest.raises(HTTPException) as e:
        api.sheet_upload_gate("闸门用别人卷", owner)
    assert e.value.status_code == 404, "不能告诉他这个卷名被谁占了"


def test_正在跑的卷子不许再传(db, owner, monkeypatch):
    """
    两条链写同一个 `work/<卷名>/`，而且会把模型额度跑两遍。
    这道闸必须在后端 —— 前端那个「上传中禁用」刷新一下就绕过去了。
    """
    store.create_answers_paper("闸门用在跑卷", owner)
    store.put_answer_question("闸门用在跑卷", 1, "A", None)
    monkeypatch.setattr(api, "pipeline_running", lambda n, cmds=None: True)
    with pytest.raises(HTTPException) as e:
        api.sheet_upload_gate("闸门用在跑卷", owner)
    assert e.value.status_code == 409


# ---------------------------------------------------------------- 按卡存料

def _png(tmp_path, name):
    from PIL import Image
    p = tmp_path / name
    Image.new("RGB", (40, 60), (250, 250, 250)).save(p)
    return str(p)


def test_两份答题卡的原图互不覆盖(db, owner, tmp_path):
    store.create_answers_paper("存料用卷", owner)
    a = store.create_sheet("存料用卷", "张三", owner)
    b = store.create_sheet("存料用卷", "李四", owner)
    assert store.sheet_page_path(a, 1) != store.sheet_page_path(b, 1)
    assert "/%d/" % a in store.sheet_page_path(a, 1)


def test_存进去取得回来(db, owner, tmp_path):
    store.create_answers_paper("存料用取回卷", owner)
    sid = store.create_sheet("存料用取回卷", "张三", owner)
    store.put_sheet_pages("存料用取回卷", sid,
                          [_png(tmp_path, "a.png"), _png(tmp_path, "b.png")])
    assert store.sheet_pages(sid) == [store.sheet_page_path(sid, 1),
                                      store.sheet_page_path(sid, 2)]


def test_两份卡各存各的(db, owner, tmp_path):
    """第二份不许把第一份的资产行冲掉"""
    store.create_answers_paper("存料用两卡卷", owner)
    a = store.create_sheet("存料用两卡卷", "张三", owner)
    b = store.create_sheet("存料用两卡卷", "李四", owner)
    store.put_sheet_pages("存料用两卡卷", a, [_png(tmp_path, "a1.png")])
    store.put_sheet_pages("存料用两卡卷", b, [_png(tmp_path, "b1.png"),
                                            _png(tmp_path, "b2.png")])
    assert len(store.sheet_pages(a)) == 1
    assert len(store.sheet_pages(b)) == 2


def test_重传少页时上一次的残页会清掉(db, owner, tmp_path):
    """
    上次 3 页这次 2 页。不清的话上次的 p03 还在，Ⓑ 会把上一个学生
    （或上一次拍歪的那张）的第 3 页当成这次的读进来。
    """
    store.create_answers_paper("存料用重传卷", owner)
    sid = store.create_sheet("存料用重传卷", "张三", owner)
    store.put_sheet_pages("存料用重传卷", sid, [_png(tmp_path, "%d.png" % i)
                                              for i in range(3)])
    assert len(store.sheet_pages(sid)) == 3
    store.put_sheet_pages("存料用重传卷", sid, [_png(tmp_path, "x%d.png" % i)
                                              for i in range(2)])
    assert len(store.sheet_pages(sid)) == 2


def test_页数会记到卡上(db, owner, tmp_path):
    store.create_answers_paper("存料用页数卷", owner)
    sid = store.create_sheet("存料用页数卷", "张三", owner)
    store.put_sheet_pages("存料用页数卷", sid, [_png(tmp_path, "a.png")])
    assert store.list_sheets("存料用页数卷")[0]["nPages"] == 1


# ---------------------------------------------------------------- 删空壳

def test_带着作答的卷子不许被删空壳(db, owner):
    """
    Ⓐ 失败时删空壳的判据原来是「**这次新建的**」，不是「**现在还空着**」。
    学生的作答不可再生：参考答案能重读，那张已批改的答题卡老师未必还留着。
    """
    store.create_answers_paper("删空壳用卷", owner)
    sid = store.create_sheet("删空壳用卷", "张三", owner)
    store.put_sheet_answer(sid, 1, raw_text="B")
    assert not api.safe_to_delete_shell("删空壳用卷")


def test_只建了卡还没读出作答也不许删(db, owner):
    """
    卡建了就说明老师已经把答题卡传上来了，那批图也在库里。
    删卷会连它们一起带走，而重传要老师再找一次原件。
    """
    store.create_answers_paper("删空壳用建卡卷", owner)
    store.create_sheet("删空壳用建卡卷", "张三", owner)
    assert not api.safe_to_delete_shell("删空壳用建卡卷")


def test_真空壳可以删(db, owner):
    store.create_answers_paper("删空壳用真空卷", owner)
    assert api.safe_to_delete_shell("删空壳用真空卷")


def test_卷子不存在时当它可以删(db):
    """已经不在了，删一次是幂等的，不该在这里抛"""
    assert api.safe_to_delete_shell("删空壳用没有的卷")


# ---------------------------------------------------------------- Ⓢ 端到端
#
# 不调模型，纯几何 + 落库，几十毫秒。

def _screenshot(tmp_path, name):
    """造一张「手机截图」：上下压暗、中间一条亮的、亮带中间一道缝"""
    import numpy as np
    from PIL import Image
    a = np.full((600, 400), 30, dtype=np.uint8)
    a[200:400, :] = 250
    a[200:400, 198:202] = 40
    p = tmp_path / name
    Image.fromarray(a, mode="L").convert("RGB").save(p)
    return str(p)


def test_一张截图跑完存下两页(db, owner, tmp_path, monkeypatch):
    """
    只验 Ⓢ 那一段。**Ⓑ 要打桩** —— 这条测试原来写在 run_sheet_pipeline
    还只到 Ⓢ 的时候，等它扩到整条链，这里就顺着走进了 Ⓑ、真的去调了模型
    （全量从 9 秒变 175 秒）。现在 conftest 那道 `no_real_model` 会当场拦下来。
    """
    import sheetread
    monkeypatch.setattr(sheetread.mathvlm, "ask_raw",
                        lambda *a, **k: ([{"n": "1", "y": 0.5, "answer": "A",
                                           "mark": "right"}]
                                         if k.get("want") == "array" else {"total": 1}))
    store.create_answers_paper("Ⓢ用卷", owner)
    store.put_answer_question("Ⓢ用卷", 1, "A", None)
    sid = store.create_sheet("Ⓢ用卷", "张三", owner)
    jid = "t" + "0" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "Ⓢ用卷", sid, [_screenshot(tmp_path, "s.png")], owner)
    assert api.JOBS[jid]["state"] == "done", api.JOBS[jid].get("err")
    assert len(store.sheet_pages(sid)) == 2, "一张双页截图该切出两页"


def test_抠不出来就明说不硬跑(db, owner, tmp_path):
    """
    拿一张带着状态栏的图去读题号，读出来的东西没人能信 —— 所以宁可失败。
    失败要带 err_code，页面才画得出是哪一步挂的。
    """
    from PIL import Image
    p = tmp_path / "flat.png"
    # 亮带只占 4%：这不是答题卡
    import numpy as np
    a = np.full((500, 200), 30, dtype=np.uint8)
    a[480:500, :] = 250
    Image.fromarray(a, mode="L").convert("RGB").save(p)

    store.create_answers_paper("Ⓢ用坏卷", owner)
    store.put_answer_question("Ⓢ用坏卷", 1, "A", None)
    sid = store.create_sheet("Ⓢ用坏卷", "张三", owner)
    jid = "t" + "1" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "Ⓢ用坏卷", sid, [str(p)], owner)
    assert api.JOBS[jid]["state"] == "error"
    assert api.JOBS[jid]["err_code"] == "sheetcut"
    assert store.sheet_pages(sid) == []


def test_失败不删卡(db, owner, tmp_path):
    """卡里可能已经有上一次读出来的作答，而那是不可再生的"""
    from PIL import Image
    import numpy as np
    p = tmp_path / "flat2.png"
    a = np.full((500, 200), 30, dtype=np.uint8)
    a[480:500, :] = 250
    Image.fromarray(a, mode="L").convert("RGB").save(p)

    store.create_answers_paper("Ⓢ用保卡卷", owner)
    store.put_answer_question("Ⓢ用保卡卷", 1, "A", None)
    sid = store.create_sheet("Ⓢ用保卡卷", "张三", owner)
    store.put_sheet_answer(sid, 1, raw_text="上一次读出来的")
    jid = "t" + "2" * 11
    api.JOBS[jid] = {"state": "running", "log": [], "sheet": sid}
    api.run_sheet_pipeline(jid, "Ⓢ用保卡卷", sid, [str(p)], owner)
    assert store.list_sheets("Ⓢ用保卡卷")[0]["answers"] == 1


def test_答题卡的失败不占卷子的格子(db, owner):
    """
    `sheetcut` 这个代号**故意不在** `modes.SHEET.cell_of` 里。

    答题卡不占格子（见 modes._stage_of_sheet 的说明），它的失败挂在**卡**上 ——
    任务字典里带着 `sheet` 那个键，页面按卡画横幅。
    写进 cell_of 的话，那一格会在「没传答题卡」的卷子上永远灰着。
    """
    import modes
    assert "sheetcut" not in modes.SHEET.cell_of
    assert "sheetcut" not in modes.PAPER.cell_of
