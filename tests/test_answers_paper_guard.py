# -*- coding: utf-8 -*-
"""
两个模式互不干扰，最硬的一条是：**谁也不能把对方的卷子就地改成自己的。**

create_answers_paper 的 ON CONFLICT DO UPDATE SET source_kind='answers_only'
不看原来是什么。今天它只被测试调所以没出事；一接上上传入口就成真了 ——
老师随手填了一个和自己某份高考真题一样的卷名，那份跑了一小时的解析试卷会
当场变成答题卡卷子：进度改走两格链，解法和动画还在库里却一格都不显示，
而且一句提示都没有。
"""
import pytest

import store
from pipeline import api


def test_新卷名建得起来(db):
    pid = store.create_answers_paper("护栏用新卷", None)
    assert pid
    assert store.source_kind_of("护栏用新卷") == "answers_only"


def test_重跑同一份答案卷不报错(db):
    store.create_answers_paper("护栏用重跑卷", None)
    store.create_answers_paper("护栏用重跑卷", None)
    assert store.source_kind_of("护栏用重跑卷") == "answers_only"


def test_撞上解析试卷当场抛(db, conn):
    conn.execute("INSERT INTO papers (name, n_questions, source_kind) "
                 "VALUES ('护栏用真题卷', 16, 'pdf')")
    conn.commit()
    with pytest.raises(ValueError, match="解析试卷"):
        store.create_answers_paper("护栏用真题卷", None)


def test_抛了之后那份试卷一个字没动(db, conn):
    conn.execute("INSERT INTO papers (name, n_questions, source_kind) "
                 "VALUES ('护栏用真题卷2', 16, 'pdf')")
    conn.commit()
    with pytest.raises(ValueError):
        store.create_answers_paper("护栏用真题卷2", None)
    assert store.source_kind_of("护栏用真题卷2") == "pdf"


# ---------------------------------------------------------------- 归属护栏
#
# 上面几条挡的是「模式」（source_kind），这几条挡的是「归属」（owner_id）——
# 原来的 WHERE 只查 source_kind = 'answers_only'，撞上一个还不存在的新卷名时，
# TOCTOU 窗口里两个账号都会走到这个 INSERT：先落库的那个成功，后落库的那个
# 撞上 ON CONFLICT，只挡 source_kind 的话第二个人的答案会悄悄写进第一个人的
# 卷子，而他自己从此 404 看不到自己传的东西。

def test_撞上别人的答题卡卷子当场抛(db, conn):
    """两个账号（都不是 NULL）在同一个新卷名上撞车 —— 后来的那个必须被挡住。"""
    conn.execute("INSERT INTO users (id, email) VALUES "
                 "(90001, 'guard-owner-a@test.local'), "
                 "(90002, 'guard-owner-b@test.local') ON CONFLICT (id) DO NOTHING")
    conn.commit()
    try:
        store.create_answers_paper("护栏用归属卷", 90001)
        with pytest.raises(ValueError, match="别人"):
            store.create_answers_paper("护栏用归属卷", 90002)
        # 撞车之后卷子还是第一个人的，没有被 COALESCE 悄悄改主
        assert store.paper_owner("护栏用归属卷") == (True, 90001)
    finally:
        with store.connect() as c:
            cur = c.cursor()
            cur.execute("DELETE FROM papers WHERE name = %s", ("护栏用归属卷",))
            cur.execute("DELETE FROM users WHERE id IN (90001, 90002)")
            c.commit()


def test_同一个账号重跑自己的答案卷不受归属闸门影响(db, conn):
    """归属闸门不能连自己重跑自己的卷子也一起拦下来 —— 那是这个函数本来就该放行的路。"""
    conn.execute("INSERT INTO users (id, email) VALUES "
                 "(90003, 'guard-owner-c@test.local') ON CONFLICT (id) DO NOTHING")
    conn.commit()
    try:
        store.create_answers_paper("护栏用自己重跑卷", 90003)
        store.create_answers_paper("护栏用自己重跑卷", 90003)
        assert store.paper_owner("护栏用自己重跑卷") == (True, 90003)
    finally:
        with store.connect() as c:
            cur = c.cursor()
            cur.execute("DELETE FROM papers WHERE name = %s", ("护栏用自己重跑卷",))
            cur.execute("DELETE FROM users WHERE id = 90003")
            c.commit()


def test_在跑判定认得出读参考答案():
    """
    PIPE_RE 里没有 refread —— 于是「这份卷子在跑吗」对答题卡链永远答 false，
    上传闸门等于漏的，同一份能同时跑两条
    """
    cmd = "12345 /x/.venv/bin/python /x/pipeline/refread.py 期末卷 a.png b.png"
    assert api.PIPE_RE.search(cmd)
    assert api.pipeline_running("期末卷", cmds=[cmd])


def test_在跑判定不会把别的卷子也算进来():
    cmd = "12345 /x/.venv/bin/python /x/pipeline/refread.py 期末卷 a.png"
    assert not api.pipeline_running("期末卷 (2)", cmds=[cmd])


def test_多个空格也不会让短卷名撞上长卷名():
    """
    边界不能只靠「free_name 只加一个空格」这个别处维持的约定。
    `\\s+(?!\\()` 会回溯少吃一个空格、把 lookahead 落到空格上而匹配成功 ——
    那正是 docstring 里警告过的那次误判（三天前停了的卷子画着呼吸点写「正在跑」）
    """
    cmd = "1 /x/.venv/bin/python /x/pipeline/solve.py 期末卷  (2) -x"
    assert not api.pipeline_running("期末卷", cmds=[cmd])


def test_在跑判定认得出读题干():
    """
    `stemread` 一直漏在 PIPE_RE 外面。Ⓔ 一页要一分钟上下，那几分钟里
    「这份卷子在跑吗」一律答 false —— 上传闸门是漏的，同一份能同时跑两条。
    """
    cmd = "12345 /x/.venv/bin/python /x/pipeline/stemread.py 期末卷 a.png b.png"
    assert api.PIPE_RE.search(cmd)
    assert api.pipeline_running("期末卷", cmds=[cmd])


def test_在跑判定认得出读答题卡():
    cmd = ("12345 /x/.venv/bin/python /x/pipeline/sheetread.py 期末卷 "
           "--sheet 3 a.png b.png")
    assert api.PIPE_RE.search(cmd)
    assert api.pipeline_running("期末卷", cmds=[cmd])


def test_每个管线脚本都登记进了在跑判定():
    """
    **门禁。** 漏登记一个脚本的后果是静默的：那一步跑的那几分钟里
    `pipeline_running` 一律答 false，上传闸门形同虚设，同一份卷子能同时跑两条，
    两条链写同一个 work 目录、把模型额度跑两遍。

    判据是「pipeline/ 下所有带 `if __name__ == '__main__'` 的脚本」——
    有 main 的就是能被 run_step 单独拉起来的，就该在这张表里。
    """
    import os
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "pipeline")
    runnable = set()
    for fn in os.listdir(d):
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(d, fn), encoding="utf-8").read()
        if "__main__" in src:
            runnable.add(fn[:-3])
    # 这几个有 main 但**不是管线步骤**，不该进 PIPE_RE：
    #   run/store         编排器、库层（api.py 不在此列 —— 它走 uvicorn，没有 main）
    #   arkshim/clishim/cliask  模型垫片
    #   mailer/kp/pages   工具
    #   scenedecl/scenegen      ⑤ 的代码生成器，由 scene.py 在进程内调
    #   stash/sheetcut    在 api 进程内调，不起子进程，撞不上并跑
    NOT_PIPELINE = {"run", "store", "arkshim", "clishim", "cliask",
                    "mailer", "kp", "pages", "scenedecl", "scenegen",
                    "stash", "sheetcut"}
    stale = sorted(NOT_PIPELINE - runnable)
    assert not stale, (
        "排除名单里这几个已经没有 main 了：%s。留着会让这张表慢慢腐烂成"
        "一张谁也不敢动的名单，删掉它们。" % "、".join(stale))
    missing = sorted(runnable - NOT_PIPELINE - {
        m for m in runnable
        if api.PIPE_RE.search("pipeline/%s.py" % m)})
    assert not missing, (
        "这些脚本能被单独拉起来，但 PIPE_RE 认不出它们：%s。\n"
        "后果不是报错，是它们跑的那几分钟里上传闸门是漏的。\n"
        "确认不是管线步骤的话，加进上面那个 NOT_PIPELINE 集合并说明理由。"
        % "、".join(missing))
