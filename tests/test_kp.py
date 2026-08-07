# -*- coding: utf-8 -*-
import json, re
import kp


def test_词表自身合法():
    entries = json.load(open(kp.SEED, encoding="utf-8"))
    assert kp.validate(entries) == []


def test_每章都有知识点():
    entries = json.load(open(kp.SEED, encoding="utf-8"))
    got = {e["chapter"] for e in entries}
    assert got == set(kp.CHAPTERS), "缺章：%s" % (set(kp.CHAPTERS) - got)


def test_code_只用小写ascii():
    for code in kp.load():
        assert re.fullmatch(r"[a-z0-9_.]+", code), code


def test_按名字和别名都找得到():
    assert kp.resolve("dyn.newton2") == "dyn.newton2"
    assert kp.resolve("牛顿第二定律") == "dyn.newton2"
    assert kp.resolve("牛二") == "dyn.newton2"
    assert kp.resolve(" 牛顿第二定律 ") == "dyn.newton2"


def test_编出来的一律找不到():
    # **不做模糊匹配。** 「最接近的那个」会把错标签洗成看起来合理的标签
    assert kp.resolve("mech.newton_second_law") is None
    assert kp.resolve("牛顿第二定律的应用") is None
    assert kp.resolve("") is None
    assert kp.resolve(None) is None


def test_validate_抓得到重复的code():
    bad = [{"code": "a.b", "chapter": kp.CHAPTERS[0], "name": "甲", "aliases": []},
           {"code": "a.b", "chapter": kp.CHAPTERS[0], "name": "乙", "aliases": []}]
    assert any("重复" in p for p in kp.validate(bad))


def test_validate_抓得到野章名():
    bad = [{"code": "a.b", "chapter": "玄学", "name": "甲", "aliases": []}]
    assert any("章" in p for p in kp.validate(bad))
