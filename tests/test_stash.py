# -*- coding: utf-8 -*-
"""
原卷和答题卡：这一轮读不了，但现在就收下。

老师手上是三样东西，没理由让他为此分三次传。用得上的现在读，用不上的先存着 ——
等 Ⓔ 读题干、步二读答题卡做好，料已经在库里。
"""
import pytest

import stash
import store


def _png(path, size=(40, 56)):
    from PIL import Image
    Image.new("RGB", size, "white").save(path)
    return str(path)


@pytest.fixture
def 一份答案卷(db):
    store.create_answers_paper("收材料用的卷", None)
    yield "收材料用的卷"
    with store.connect() as c:
        c.execute("DELETE FROM papers WHERE name='收材料用的卷'")
        c.commit()


def _kinds(name):
    with store.connect() as c:
        return dict(c.execute(
            "SELECT a.kind, count(*) FROM assets a JOIN papers p ON p.id=a.paper_id "
            "WHERE p.name=%s GROUP BY a.kind", (name,)).fetchall())


def test_原卷存进stem那一类(一份答案卷, tmp_path):
    n = stash.stash(一份答案卷, [_png(tmp_path / "1.png"), _png(tmp_path / "2.png")],
                    "stem", verbose=False)
    assert n == 2
    assert _kinds(一份答案卷) == {"stem": 2}


def test_答题卡存进sheet那一类(一份答案卷, tmp_path):
    stash.stash(一份答案卷, [_png(tmp_path / "a.png")], "sheet", verbose=False)
    assert _kinds(一份答案卷) == {"sheet": 1}


def test_两类各存各的互不覆盖(一份答案卷, tmp_path):
    """
    两类都用 pNN 编号，如果前缀没分开，第二类会把第一类顶掉
    （assets 的唯一键是 paper_id + rel_path）
    """
    stash.stash(一份答案卷, [_png(tmp_path / "1.png")], "stem", verbose=False)
    stash.stash(一份答案卷, [_png(tmp_path / "1.png")], "sheet", verbose=False)
    assert _kinds(一份答案卷) == {"stem": 1, "sheet": 1}


def test_一个文件都没有不算失败(一份答案卷):
    """这两栏是选填的，空着是正常路径，不是错误"""
    assert stash.stash(一份答案卷, [], "stem", verbose=False) == 0
    assert _kinds(一份答案卷) == {}


def test_不收参考答案那一类(一份答案卷, tmp_path):
    """
    参考答案由 refread（Ⓐ）边读边存。让这里也能存的话，同一批图会被存两遍，
    而且谁存的说不清
    """
    with pytest.raises(ValueError, match="不认识的分类"):
        stash.stash(一份答案卷, [_png(tmp_path / "1.png")], "page", verbose=False)


def test_重传同一批不会翻倍(一份答案卷, tmp_path):
    """
    rel_path 按页号定，同一页重传就是覆盖 —— 不然传两次就有两份，
    而页数是下游判断「有没有材料」的依据
    """
    f = [_png(tmp_path / "1.png"), _png(tmp_path / "2.png")]
    stash.stash(一份答案卷, f, "stem", verbose=False)
    stash.stash(一份答案卷, f, "stem", verbose=False)
    assert _kinds(一份答案卷) == {"stem": 2}
