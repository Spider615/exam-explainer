# -*- coding: utf-8 -*-
import refans

DOC = """一、单项选择题
1. 下列说法正确的是（ ）
A. 甲   B. 乙   C. 丙   D. 丁
2. 关于动量守恒，下列说法正确的是（ ）
A. 甲   B. 乙

参考答案
1. B
2. AC
3. 0.4 m/s，方向水平向右
"""


def test_找得到参考答案区():
    i = refans.find_zone(DOC)
    assert i is not None
    assert DOC[i:].startswith("参考答案")


def test_没有答案区就回None():
    assert refans.find_zone("一、单项选择题\n1. 下列说法正确的是（ ）\n") is None
    # 题干里的「答案」不算 —— 这是 22 卷语料里唯一出现「答案」的地方
    assert refans.find_zone("1. 计算结果，答案保留两位有效数字。") is None


def test_按题号切开():
    got = refans.split_answers(DOC[refans.find_zone(DOC):], [1, 2, 3])
    assert got == {1: "B", 2: "AC", 3: "0.4 m/s，方向水平向右"}


def test_只认卷子里有的题号():
    zone = "参考答案\n1. B\n7. 编出来的\n"
    assert refans.split_answers(zone, [1, 2]) == {1: "B"}


def test_题号顺序乱了也不猜():
    """答案区里题号必须**递增**。乱序多半是把正文当成了答案区，
    这时宁可一条都不给，也不能把错位的答案安到题上 —— 那会让做对的
    学生被判错，凭空造出一个假的薄弱知识点。"""
    zone = "参考答案\n3. C\n1. B\n2. A\n"
    assert refans.split_answers(zone, [1, 2, 3]) == {}


def test_多种题号写法():
    for zone in ("参考答案\n1．B\n2．AC\n", "参考答案\n1、B\n2、AC\n",
                 "参考答案\n【1】B\n【2】AC\n", "参考答案\n第1题 B\n第2题 AC\n"):
        assert refans.split_answers(zone, [1, 2]) == {1: "B", 2: "AC"}, zone


def test_答案跨行也收得全():
    zone = "参考答案\n1. B\n2. 见解析：\n先由动量守恒求出 v，再代入动能定理\n3. C\n"
    got = refans.split_answers(zone, [1, 2, 3])
    assert got[2] == "见解析： 先由动量守恒求出 v，再代入动能定理"


def test_extract串起来():
    assert refans.extract(DOC, [1, 2, 3]) == {1: "B", 2: "AC",
                                              3: "0.4 m/s，方向水平向右"}
    assert refans.extract("没有答案区的卷子\n1. 题干\n", [1]) == {}
