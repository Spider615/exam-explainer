# -*- coding: utf-8 -*-
"""
题面内容哈希：题没变就不必重解。

为什么要把「哪张图是哪个选项」也算进去
--------------------------------------
原来只哈希**插图字节**。于是修好了「图形选项题的选项配图」之后，同样四张图从
题干挪到 A/B/C/D 名下 —— 字节集合一个没变，哈希也就没变，`solution_fresh` 判
「题面未变」，**这类改进永远传不下去**。而这恰恰是最要紧的一次改动：模型原来
拿到的是「题干插图1..4」，只能靠数数猜哪张对应哪个选项。

只给**有选项配图**的题加这一段
------------------------------
`q_source_hash` 一变，全库每道题都会被判 stale，等于整库重解 —— 几个小时加一
大笔额度。而「哪张图属于哪个选项」这个绑定只有在真有选项配图时才存在：题干图
的位置信息本来就由**顺序**表达（题干插图1..N），而顺序早就在哈希里了。
所以标签只对选项图生效，没有选项图的题哈希逐字节不变。
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import solve

Q = {"stem": "某同学绘制了四幅静电场的电场线分布图，其中可能正确的是（ ）",
     "options": [{"key": k, "text": ""} for k in "ABCD"], "tables": []}
FIGS = [b"\x89PNG-a", b"\x89PNG-b", b"\x89PNG-c", b"\x89PNG-d"]


def old_hash(q, figs):
    """改动之前那版，逐字抄过来当基准 —— 不能靠记忆说「没变」。"""
    h = hashlib.sha256()
    h.update((q.get("stem_latex") or q.get("stem") or "").encode())
    for o in q.get("options") or []:
        h.update((o.get("key", "") + (o.get("latex") or o.get("text") or "")).encode())
    for t in q.get("tables") or []:
        h.update(json.dumps(t.get("rows") or [], ensure_ascii=False).encode())
    for b in figs:
        h.update(hashlib.sha256(b).digest())
    return h.hexdigest()


def test_没有选项配图时哈希逐字不变():
    """
    **这条是整个改动的安全绳。** 它一红就意味着全库每道题都会被判「题面变了」，
    下一次跑 ③ 会把整个库重解一遍。
    """
    labels = ["题干插图1", "题干插图2", "题干插图3", "题干插图4"]
    assert solve.q_source_hash(Q, FIGS, labels) == old_hash(Q, FIGS)


def test_不传标签时也和老版一致():
    assert solve.q_source_hash(Q, FIGS) == old_hash(Q, FIGS)


def test_图从题干挪到选项_哈希要变():
    """这正是修好选项配图之后发生的事。不变的话改进传不下去。"""
    stem = solve.q_source_hash(Q, FIGS, ["题干插图1", "题干插图2", "题干插图3", "题干插图4"])
    opt = solve.q_source_hash(Q, FIGS, ["选项A", "选项B", "选项C", "选项D"])
    assert stem != opt


def test_同样的图换个字母_哈希要变():
    """A、B 两张图对调 —— 字节集合一样，但这是**另一道题**。"""
    ab = solve.q_source_hash(Q, FIGS, ["选项A", "选项B", "选项C", "选项D"])
    ba = solve.q_source_hash(Q, [FIGS[1], FIGS[0]] + FIGS[2:],
                             ["选项A", "选项B", "选项C", "选项D"])
    assert ab != ba


def test_字母和图都没变_哈希不变():
    a = solve.q_source_hash(Q, FIGS, ["选项A", "选项B", "选项C", "选项D"])
    b = solve.q_source_hash(Q, list(FIGS), ["选项A", "选项B", "选项C", "选项D"])
    assert a == b


def test_标签个数对不上时不许静默错配():
    """
    标签和图是一一对应的，对不上说明调用方写错了 —— 宁可抛，也不能按位置
    硬凑出一个「看着像对的」哈希。
    """
    import pytest
    with pytest.raises(ValueError):
        solve.q_source_hash(Q, FIGS, ["选项A", "选项B"])
