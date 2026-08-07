# -*- coding: utf-8 -*-
import json
import store


def _make_work(tmp_path, name="测试卷", ns=(1, 2)):
    """造一个最小的构建产物目录，够 publish 用。"""
    d = tmp_path / name
    d.mkdir()
    (d / "questions.json").write_text(json.dumps({
        "source": "x.pdf", "sections": [], "warnings": [],
        "questions": [{"n": n, "type": "单选题", "stem": "第%d题题干" % n,
                       "options": [], "tables": [], "figures": []} for n in ns],
    }, ensure_ascii=False), encoding="utf-8")
    return str(d)


def test_写得进去也读得回来(db, tmp_path):
    work = _make_work(tmp_path, "kps卷A")
    store.publish(work, name="kps卷A")
    paper = store.get_paper("kps卷A")
    q1 = paper["questions"][0]
    assert q1["kps"] == []
    assert q1["ref_answer"] is None
    assert q1["ref_answer_src"] is None

    store.put_kps(q1["id"], [{"code": "mom.conserve", "why": "用动量守恒求碰后速度"}])
    store.put_ref_answer(q1["id"], "BD", "paper")

    q1 = store.get_paper("kps卷A")["questions"][0]
    assert q1["kps"] == [{"code": "mom.conserve", "why": "用动量守恒求碰后速度"}]
    assert q1["ref_answer"] == "BD"
    assert q1["ref_answer_src"] == "paper"


def test_重新发布不冲掉这三列(db, tmp_path):
    """label 已经有过这个先例：publish 的 upsert 只更新它列出来的列。
    新列一旦被列进 DO UPDATE SET，重跑一次 ② 就把 ③c 的产出全冲没了。"""
    work = _make_work(tmp_path, "kps卷B")
    store.publish(work, name="kps卷B")
    qid = store.get_paper("kps卷B")["questions"][0]["id"]
    store.put_kps(qid, [{"code": "kin.free_fall", "why": "自由落体求时间"}])
    store.put_ref_answer(qid, "0.4 m", "paper")

    store.publish(work, name="kps卷B")          # 再发布一次

    q1 = store.get_paper("kps卷B")["questions"][0]
    assert q1["id"] == qid, "重新发布不该换 id"
    assert q1["kps"] == [{"code": "kin.free_fall", "why": "自由落体求时间"}]
    assert q1["ref_answer"] == "0.4 m"


def test_抽不到答案记成none(db, tmp_path):
    work = _make_work(tmp_path, "kps卷C")
    store.publish(work, name="kps卷C")
    qid = store.get_paper("kps卷C")["questions"][0]["id"]
    store.put_ref_answer(qid, None, "none")
    q1 = store.get_paper("kps卷C")["questions"][0]
    assert q1["ref_answer"] is None
    assert q1["ref_answer_src"] == "none", "抽不到也要留痕，不能是 NULL"


def test_野的src当场拒绝(db, tmp_path):
    work = _make_work(tmp_path, "kps卷D")
    store.publish(work, name="kps卷D")
    qid = store.get_paper("kps卷D")["questions"][0]["id"]
    try:
        store.put_ref_answer(qid, "B", "guessed")
    except ValueError as e:
        assert "paper/answer_file/none" in str(e)
    else:
        raise AssertionError("野的 src 应该当场抛，不能悄悄写进库")
