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
