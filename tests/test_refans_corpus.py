# -*- coding: utf-8 -*-
"""
全语料反幻觉门禁。

库里这 22 份都是高考真题 PDF，本来就不带参考答案。所以 ②c 在它们身上的
**正确行为是一条都不抽**。抽出来任何东西都说明规则太松，会把正文里的
「1. 下列说法正确的是」当成答案。
"""
import glob, json, os
import pytest
import refans

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = sorted(glob.glob(os.path.join(ROOT, "work", "*", "doc.json")))

pytestmark = pytest.mark.skipif(not DOCS, reason="没有 work/ 语料")


def _text(path):
    d = json.load(open(path, encoding="utf-8"))
    return "\n".join(pg["text"] for pg in d["pages"])


@pytest.mark.parametrize("path", DOCS, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_不带答案的卷子一条都不许抽出来(path):
    # 题号取 1..25，比任何一份卷子的题数都多 —— 故意给最宽松的候选集，
    # 让规则在最容易误命中的条件下受检
    got = refans.extract(_text(path), list(range(1, 26)))
    assert got == {}, "从不带答案的卷子里抽出了 %d 条：%s" % (len(got), got)


def test_语料里确实没有参考答案段落():
    """这条是上面那批测试的前提。哪天语料换成带答案的卷子，
    这条会先红 —— 提醒去改上面的断言，而不是让上面静静地失去意义。"""
    for path in DOCS:
        assert refans.find_zone(_text(path)) is None, path
