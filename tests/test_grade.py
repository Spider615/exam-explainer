# -*- coding: utf-8 -*-
import grade


# ---------------------------------------------------------------- 选择题
def test_选择题字母集合():
    assert grade.as_choice("BD") == "BD"
    assert grade.as_choice("db") == "BD"
    assert grade.as_choice("B D") == "BD"
    assert grade.as_choice("B、D") == "BD"
    assert grade.as_choice("BBD") == "BD", "重复的字母去掉"


def test_不是选择题就回None():
    assert grade.as_choice("0.4 m") is None
    assert grade.as_choice("E") is None, "只认 A-D"
    assert grade.as_choice("") is None
    assert grade.as_choice(None) is None


def test_判选择题():
    assert grade.judge("BD", "DB")[0] == "right"
    assert grade.judge("B", "BD")[0] == "wrong"
    assert grade.judge("ac", "AC")[0] == "right"


# ---------------------------------------------------------------- 数值
def test_数值带单位():
    assert grade.as_number("1.5 m/s") == (1.5, "m/s")
    assert grade.as_number("1.5m/s") == (1.5, "m/s")
    assert grade.as_number("0.40") == (0.4, "")


def test_分数和科学计数():
    assert grade.as_number("3/2")[0] == 1.5
    assert grade.as_number("1.6e-19 C")[0] == 1.6e-19
    assert grade.as_number("1.6×10^-19 C")[0] == 1.6e-19
    assert grade.as_number("-2.5 m")[0] == -2.5


def test_不是数值就回None():
    assert grade.as_number("见解析") is None
    assert grade.as_number("") is None
    assert grade.as_number("3/0") is None, "除零不许炸也不许给个假值"


def test_判数值():
    assert grade.judge("0.40 m", "0.4 m")[0] == "right"
    assert grade.judge("0.5 m", "0.4 m")[0] == "wrong"
    assert grade.judge("3/2", "1.5")[0] == "right"


def test_单位对不上不判错而是判不了():
    """「1.5 m/s」和「1.5 米每秒」很可能是同一个答案。判错会让做对的
    学生凭空多一个薄弱知识点 —— 宁可交给模型"""
    v, why = grade.judge("1.5 m/s", "1.5 米每秒")
    assert v is None and "单位" in why


# ---------------------------------------------------------------- 表达式
def test_latex归一化():
    assert grade.norm_expr(r"\dfrac{1}{2}mv^2") == grade.norm_expr(r"\frac{1}{2}mv^{2}")
    assert grade.norm_expr("a·b") == grade.norm_expr(r"a\cdot b")
    assert grade.norm_expr("v₀") == grade.norm_expr("v_0")


def test_判表达式():
    assert grade.judge(r"\dfrac{1}{2}mv^2", r"\frac{1}{2} m v^{2}")[0] == "right"


def test_大小写有意义不许抹掉():
    """m 是质量、M 是另一个质量或兆。抹掉大小写就是静默判等 ——
    学生答对的题被判错，或答错的被判对，页面上一切看起来正常"""
    assert grade.judge("mgh", "mgH")[0] == "wrong"
    assert grade.judge("2mv", "2Mv")[0] == "wrong"


# ---------------------------------------------------------------- 多空
def test_多空按空比():
    assert grade.split_blanks("小于 / 等于 / 小于") == ["小于", "等于", "小于"]
    assert grade.judge("小于/等于/小于", "小于 / 等于 / 小于")[0] == "right"
    assert grade.judge("小于/大于/小于", "小于 / 等于 / 小于")[0] == "wrong"


def test_多空里混数值():
    assert grade.judge("92 / 56", "92/56")[0] == "right"
    assert grade.judge("92 / 57", "92/56")[0] == "wrong"


def test_空数对不上是判不了():
    v, why = grade.judge("小于/等于", "小于 / 等于 / 小于")
    assert v is None and "空" in why


# ---------------------------------------------------------------- 判不了
def test_长答案交给模型():
    v, why = grade.judge(
        "由动量守恒 mv0=(m+M)v，再由动能定理求得 v=mv0/(m+M)，方向水平向右",
        "0.4 m/s")
    assert v is None, "形式差得远，代码档不该下结论"


def test_长度悬殊也交给模型():
    v, _ = grade.judge("B", "选 B，因为小球做匀速圆周运动")
    assert v is None


def test_两边都短就敢判不等():
    assert grade.judge("小于", "大于")[0] == "wrong"
    assert grade.judge("0.5", "0.4")[0] == "wrong"


def test_有一边为空一律判不了():
    assert grade.judge("", "BD")[0] is None
    assert grade.judge("BD", None)[0] is None
    assert grade.judge("   ", "  ")[0] is None


def test_判不了时理由不能是空话():
    for a, b in [("", "BD"), ("1.5 m/s", "1.5 米每秒"), ("小于/等于", "小于/等于/小于")]:
        v, why = grade.judge(a, b)
        assert v is None and len(why) >= 4, "判不了必须说清楚为什么"


# ---------------------------------------------------------------- 单位白名单
# 白名单是个收紧点：卡太紧会把正常答案判成「判不了」，卡太松就退回
# 「2mv 和 2Mv 判等」那个静默错误。两边都要有东西兜着
import pytest


@pytest.mark.parametrize("s,unit", [
    ("0.4 m", "m"), ("1.5 m/s", "m/s"), ("9.8 m/s^2", "m/s^2"), ("2 kg", "kg"),
    ("5 N", "N"), ("10 J", "J"), ("60 W", "W"), ("220 V", "V"), ("0.5 A", "A"),
    ("1.6e-19 C", "C"), ("0.2 T", "T"), ("300 K", "K"), ("50 Hz", "Hz"),
    ("101 Pa", "Pa"), ("13.6 eV", "eV"), ("2 mol", "mol"), ("1.5 rad", "rad"),
    ("25 °C", "°C"), ("30 %", "%"), ("3 cm", "cm"), ("5 mm", "mm"),
    ("2 km", "km"), ("10 g", "g"), ("0.1 s", "s"), ("2 h", "h"),
    ("1.2 N/kg", "N/kg"), ("4 m/s2", "m/s2"), ("3 L", "L"), ("5 min", "min"),
    ("2.5 ms", "ms"),
])
def test_常见单位都认得(s, unit):
    assert grade.as_number(s) == (pytest.approx(float(s.split()[0])), unit)


@pytest.mark.parametrize("s", ["2mv", "3mgh", "5xyz", "2ab", "4πr"])
def test_表达式尾巴不许当单位(s):
    """不拒绝的话，2mv 会被读成「数值 2 + 单位 mv」，于是 2mv 和 2Mv 判等 ——
    一个静默的错误等价判断，正是这里最怕的"""
    assert grade.as_number(s) is None
