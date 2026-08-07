# -*- coding: utf-8 -*-
"""
模型返回的 JSON 里夹着 LaTeX，两种坏法都要挡住。

第二种是实测踩到的、而且**不报错**的那种：`\\t` `\\f` `\\r` `\\b` 都是合法
JSON 转义，json.loads 会静默地把 `\\times` 变成 TAB+"imes"、把 `\\frac` 变成
FF+"rac"。公式坏了，页面上看起来还挺正常。
"""
import mathvlm


def test_正常json():
    assert mathvlm.loads_lenient('{"a": 1}') == {"a": 1}
    assert mathvlm.loads_lenient('[{"n": "1"}]') == [{"n": "1"}]


def test_漏转义的反斜杠补回来():
    # \d 不是合法 JSON 转义，json.loads 会直接报错
    got = mathvlm.loads_lenient(r'{"a": "$\dfrac{1}{2}$"}')
    assert got["a"] == r"$\dfrac{1}{2}$"


def test_times不许被吃成制表符():
    """实测第 13(2) 题就是这么坏的：`$8\\times10^{-12}$` 存进库变成了
    `$8<TAB>imes10^{-12}$`"""
    got = mathvlm.loads_lenient('{"a": "$8\\times10^{-12}$"}')
    assert got["a"] == r"$8\times10^{-12}$"
    assert "\t" not in got["a"]


def test_frac不许被吃成换页符():
    got = mathvlm.loads_lenient('{"a": "\\frac{1}{2}"}')
    assert got["a"] == r"\frac{1}{2}"
    assert "\f" not in got["a"]


def test_right和rho不许被吃成回车():
    got = mathvlm.loads_lenient('{"a": "\\right)", "b": "\\rho"}')
    assert got["a"] == r"\right)" and got["b"] == r"\rho"


def test_beta不许被吃成退格():
    assert mathvlm.loads_lenient('{"a": "\\beta"}')["a"] == r"\beta"


def test_数组和嵌套里也要修():
    got = mathvlm.loads_lenient('[{"s": ["\\theta", {"t": "\\text{cm}"}]}]')
    assert got[0]["s"][0] == r"\theta"
    assert got[0]["s"][1]["t"] == r"\text{cm}"


def test_换行不动():
    """`\\nu` 有，但解答过程里真正的换行也有。还原会把「解得\\nT=288K」
    弄成 `\\nT` —— 宁可漏修 \\nu 那一类，也不制造新的错"""
    got = mathvlm.loads_lenient('{"a": "解得\\nT=288K"}')
    assert got["a"] == "解得\nT=288K"


def test_非字符串原样不动():
    got = mathvlm.loads_lenient('{"n": 12, "ok": true, "x": null}')
    assert got == {"n": 12, "ok": True, "x": None}
