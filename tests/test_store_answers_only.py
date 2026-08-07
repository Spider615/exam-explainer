# -*- coding: utf-8 -*-
import json
import store


def test_建一份只有答案的卷子(db):
    pid = store.create_answers_paper("答案卷A", None)
    assert pid > 0
    assert store.source_kind_of("答案卷A") == "answers_only"
    p = store.get_paper("答案卷A")
    assert p["questions"] == [], "刚建出来是空的，题目由 Ⓐ 一条条写进去"


def test_写题与读回(db):
    store.create_answers_paper("答案卷B", None)
    qid = store.put_answer_question("答案卷B", 11, "2BIL / MP", "由安培力公式 F=BIL…")
    q = store.get_paper("答案卷B")["questions"][0]
    assert q["id"] == qid and q["n"] == 11
    assert q["ref_answer"] == "2BIL / MP"
    assert q["ref_solution"].startswith("由安培力")
    assert q["ref_answer_src"] == "answer_file"
    assert q["stem"] == "", "Ⓐ 不写题干，那是 Ⓔ 的事"


def test_重写同一题是覆盖(db):
    store.create_answers_paper("答案卷C", None)
    a = store.put_answer_question("答案卷C", 1, "D", "解法甲")
    b = store.put_answer_question("答案卷C", 1, "C", "解法乙")
    assert a == b, "id 要稳定 —— kps 挂在它上面"
    qs = store.get_paper("答案卷C")["questions"]
    assert len(qs) == 1 and qs[0]["ref_answer"] == "C"


def test_重写不冲掉知识点(db):
    """③c 挂完知识点之后重跑 Ⓐ，不该把标签冲没了 ——
    期一 publish 那次就是这个坑"""
    store.create_answers_paper("答案卷D", None)
    qid = store.put_answer_question("答案卷D", 1, "D", "解法")
    store.put_kps(qid, [{"code": "mag.ampere_force", "why": "用安培力公式"}])
    store.put_answer_question("答案卷D", 1, "D", "解法（改过）")
    q = store.get_paper("答案卷D")["questions"][0]
    assert q["kps"] == [{"code": "mag.ampere_force", "why": "用安培力公式"}]


def test_读答案那步不冲掉题干(db):
    """两步分工写死：Ⓐ 只写答案，Ⓔ 只写题干，谁都不许碰对方那一列"""
    store.create_answers_paper("答案卷D2", None)
    store.put_answer_question("答案卷D2", 1, "D", "解法")
    store.put_stem("答案卷D2", 1, "如图所示，物块沿斜面下滑（　）")
    store.put_answer_question("答案卷D2", 1, "C", "解法（改过）")
    q = store.get_paper("答案卷D2")["questions"][0]
    assert q["stem"].startswith("如图所示")
    assert q["ref_answer"] == "C"


def test_读题干那步不冲掉答案(db):
    store.create_answers_paper("答案卷D3", None)
    qid = store.put_answer_question("答案卷D3", 1, "D", "官方解法")
    store.put_kps(qid, [{"code": "kin.free_fall", "why": "自由落体"}])
    store.put_stem("答案卷D3", 1, "题干")
    q = store.get_paper("答案卷D3")["questions"][0]
    assert q["ref_answer"] == "D" and q["ref_solution"] == "官方解法"
    assert q["kps"] == [{"code": "kin.free_fall", "why": "自由落体"}]


def test_题号带小问也存得下(db):
    """12(1) 按 n = 主题号*100 + 小问号 存"""
    store.create_answers_paper("答案卷E", None)
    store.put_answer_question("答案卷E", 1201, "170", "由变压器原理")
    q = store.get_paper("答案卷E")["questions"][0]
    assert q["n"] == 1201


def test_题数跟着涨(db):
    store.create_answers_paper("答案卷E2", None)
    for n in (1, 2, 1201):
        store.put_answer_question("答案卷E2", n, "D", None)
    assert len(store.get_paper("答案卷E2")["questions"]) == 3
    assert store.progress("答案卷E2")["questions"] == 3


def test_卷子不存在就明说(db):
    try:
        store.put_answer_question("根本没有这份卷子", 1, "D", None)
    except ValueError as e:
        assert "根本没有这份卷子" in str(e)
    else:
        raise AssertionError("卷子不存在应该当场抛")


def test_默认还是pdf(db, tmp_path):
    d = tmp_path / "普通卷"
    d.mkdir()
    (d / "questions.json").write_text(json.dumps({
        "source": "x.pdf", "sections": [], "warnings": [],
        "questions": [{"n": 1, "type": "单选题", "stem": "题干",
                       "options": [], "tables": [], "figures": []}]}, ensure_ascii=False),
        encoding="utf-8")
    store.publish(str(d), name="普通卷")
    assert store.source_kind_of("普通卷") == "pdf", "老卷子不能被改成 answers_only"


def test_不存在的卷子回None(db):
    assert store.source_kind_of("根本没有") is None


def test_能手动删读错的题号(db):
    store.create_answers_paper("答案卷F", None)
    for n in (15, 1501, 1502):
        store.put_answer_question("答案卷F", n, "x", None)
    assert store.drop_questions("答案卷F", [15]) == 1
    ns = [q["n"] for q in store.get_paper("答案卷F")["questions"]]
    assert ns == [1501, 1502]
    assert store.progress("答案卷F")["questions"] == 2, "题数要跟着降"


def test_删不存在的题号不炸(db):
    store.create_answers_paper("答案卷G", None)
    store.put_answer_question("答案卷G", 1, "D", None)
    assert store.drop_questions("答案卷G", [99]) == 0
