# -*- coding: utf-8 -*-
import kpmark

NS = {1, 2, 3}


def test_正常一条():
    rows = [{"n": 1, "kps": [{"code": "mom.conserve", "why": "碰后速度靠动量守恒"}]}]
    assert kpmark.keep(rows, NS) == {
        1: [{"code": "mom.conserve", "why": "碰后速度靠动量守恒"}]}


def test_编出来的code直接丢掉():
    rows = [{"n": 1, "kps": [{"code": "mom.动量守恒", "why": "x"},
                             {"code": "mom.conserve", "why": "y"}]}]
    assert kpmark.keep(rows, NS) == {1: [{"code": "mom.conserve", "why": "y"}]}


def test_按名字给的也认():
    # 模型有时会回名字而不是 code。kp.resolve 精确匹配得到，就收
    rows = [{"n": 2, "kps": [{"code": "牛顿第二定律", "why": "求加速度"}]}]
    assert kpmark.keep(rows, NS) == {2: [{"code": "dyn.newton2", "why": "求加速度"}]}


def test_最多三个():
    codes = ["kin.free_fall", "dyn.newton2", "mom.conserve", "energy.ke_theorem"]
    rows = [{"n": 1, "kps": [{"code": c, "why": "第%d个" % i}
                             for i, c in enumerate(codes)]}]
    got = kpmark.keep(rows, NS)[1]
    assert len(got) == 3
    assert [g["code"] for g in got] == codes[:3]


def test_重复的code只留一个():
    rows = [{"n": 1, "kps": [{"code": "mom.conserve", "why": "甲"},
                             {"code": "动量守恒定律", "why": "乙"}]}]
    assert kpmark.keep(rows, NS) == {1: [{"code": "mom.conserve", "why": "甲"}]}


def test_卷子里没有的题号丢掉():
    rows = [{"n": 99, "kps": [{"code": "mom.conserve", "why": "x"}]}]
    assert kpmark.keep(rows, NS) == {}


def test_why为空的丢掉():
    # why 是这道题的说明，不是知识点定义。给不出来就说明模型没在看这道题
    rows = [{"n": 1, "kps": [{"code": "mom.conserve", "why": "  "}]}]
    assert kpmark.keep(rows, NS) == {}


def test_一个都挂不上就不出现在结果里():
    rows = [{"n": 1, "kps": []}, {"n": 2, "kps": [{"code": "编的", "why": "x"}]}]
    assert kpmark.keep(rows, NS) == {}


def test_烂数据不炸():
    rows = [{"n": "甲", "kps": []}, {"kps": []}, {"n": 1}, {"n": 1, "kps": "不是数组"},
            {"n": 1, "kps": [None, "字符串", {"code": "mom.conserve", "why": "好的"}]}]
    assert kpmark.keep(rows, NS) == {1: [{"code": "mom.conserve", "why": "好的"}]}


def test_整个不是数组也不炸():
    assert kpmark.keep(None, NS) == {}
    assert kpmark.keep({"n": 1}, NS) == {}
