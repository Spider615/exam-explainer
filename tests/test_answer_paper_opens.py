# -*- coding: utf-8 -*-
"""
答案卷的详情页打不打得开。**这条必须走真库，不许打桩。**

2026-08-09 实测：`GET /api/papers/<答案卷>` 一直是 500 —— `store.get_paper` 里
`q.update(q.pop("layout") or {})`，答案卷的 layout 是**空对象** `{}`（这一列
是 `NOT NULL DEFAULT '{}'`，`put_answer_question` 的 INSERT 里没有它，拿到的
就是默认值），于是 `figures` / `fig_marks` 两个键根本不存在——缺的是**键**，
不是「值是 None」，而 `api.paper` 那句 `x["figures"]` 是硬取。

**这个洞躲过了所有测试，原因很具体**：这个端点现有的测试全是打桩的，而人手写的
桩返回值键是齐的。打桩测不出「库里真实存在的那种行长什么样」—— 所以这一条走真库。
"""
import pytest

import store
from pipeline import api


@pytest.fixture
def 一份答案卷(db):
    # papers.owner_id 有外键指向 users(id)（schema.sql）——
    # 光传个 7 不先把这行 users 种进去，create_answers_paper 会在这一步就被
    # ForeignKeyViolation 挡住，根本轮不到 Step 0 要暴露的那个 KeyError。
    # 这里手动种一行，好让 brief 里写的 owner_id=7 / user={"id": 7} 保持原样。
    with store.connect() as c:
        c.cursor().execute(
            "INSERT INTO users (id, email) VALUES (7, 'answer-paper-opens@test.local') "
            "ON CONFLICT (id) DO NOTHING")
        c.commit()
    store.create_answers_paper("能不能打开的答案卷", 7)
    store.put_answer_question("能不能打开的答案卷", 1, "D", None)
    store.put_answer_question("能不能打开的答案卷", 11, "2BIL / MP", "由安培力公式 F=BIL")
    yield "能不能打开的答案卷"
    # **自己收尾。** conftest 的 db fixture 是 session 级的，整个 pytest 进程
    # 共用一个库、不回滚 —— 留在这里的 users 行会让 store.create_user 里
    # 「第一个账号认领所有无主卷子」那段（判据是 count(*) FROM users == 1）
    # 在将来某条用例上**静默跳过**，不报错、不好查。
    with store.connect() as c:
        c.cursor().execute("DELETE FROM users WHERE id = 7")
        c.commit()


def test_答案卷的详情页打得开(一份答案卷):
    got = api.paper(一份答案卷, user={"id": 7})
    assert [q["n"] for q in got["questions"]] == [1, 11]


def test_没有插图的题给空列表不是报错(一份答案卷):
    """答案卷没有版面信息，figures/figMarks 该是空列表，不该让整个端点挂掉"""
    for q in api.paper(一份答案卷, user={"id": 7})["questions"]:
        assert q["figures"] == [] and q["figMarks"] == []


def test_答案卷走的是答题卡模式(一份答案卷):
    assert api.paper(一份答案卷, user={"id": 7})["mode"]["code"] == "sheet"
