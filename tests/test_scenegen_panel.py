# -*- coding: utf-8 -*-
import json, re, subprocess
import scenegen
from test_scenegen_table import SPEC

FULL = {**SPEC, "title": "演示位移随进度变化",
        "units": "位移x：m；u为无量纲进度",
        "disclosures": [
            {"why": "w1", "must_contain": "当前位移x的数值"},
            {"why": "w2", "must_contain":
                "本题原题未给出任何数值，画面中的 m,k 均为便于演示设定的示例参数，非原题条件"},
        ]}


# ---------------------------------------------------------------- 显示哪些量
def test_声明了就用声明的():
    assert scenegen.pick_readouts(FULL, scenegen.table_of(FULL), ["x"]) == ["x"]


def test_没声明就自动挑():
    """排除 u（是进度不是物理量）和全程不变的常量列"""
    got = scenegen.pick_readouts(FULL, scenegen.table_of(FULL))
    assert "u" not in got and "k" not in got and "x" in got


def test_声明了不存在的键要当场炸():
    """放过去的话面板会多一行永远显示 undefined 的读数"""
    try:
        scenegen.pick_readouts(FULL, scenegen.table_of(FULL), ["nope"])
    except ValueError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("READOUTS 里有 probe_keys 之外的键，必须当场失败")


def test_最多四行():
    keys = list("abcdefgh")
    spec = {**FULL, "probe_keys": keys}
    tbl = {"c1": {k: [float(i) for i in range(5)] for k in keys}}
    assert len(scenegen.pick_readouts(spec, tbl)) <= 4


def test_只在某个case里不变的量不算常量():
    """它恰恰是这道题要对照的东西"""
    tbl = {"c1": {"a": [1.0] * 5, "b": [1.0] * 5},
           "c2": {"a": [1.0] * 5, "b": [0.0, 1, 2, 3, 4.0]}}
    assert scenegen.const_keys(tbl) == {"a"}


# ---------------------------------------------------------------- figcaption
def test_caption包含全部must_contain原文():
    """L1 查的是原文在不在产物里。拼进去就必然在 —— 这是 L1 恒真的做法"""
    cap = scenegen.caption(FULL)
    for d in FULL["disclosures"]:
        assert d["must_contain"] in cap


def test_caption不改写不截断():
    long = FULL["disclosures"][1]["must_contain"]
    assert long in scenegen.caption(FULL), "长句截了 L1 就不认了"


def test_没有disclosures也不炸():
    assert isinstance(scenegen.caption({"id": "x"}), str)


# ---------------------------------------------------------------- 面板
def test_面板给出矩形():
    frag, rect = scenegen.panel_svg(FULL, ["x"])
    for k in ("x", "y", "w", "h"):
        assert isinstance(rect[k], (int, float))
    assert rect["w"] > 0 and rect["h"] > 0


def test_面板不越右边界():
    """CONTRACT §1.5 第 4 条：右边界 548"""
    frag, rect = scenegen.panel_svg(FULL, ["x", "u", "k"])
    assert rect["x"] + rect["w"] <= scenegen.PANEL_RIGHT + 0.01


def test_每个读数一行且带稳定id():
    frag, rect = scenegen.panel_svg(FULL, ["x", "u"], sid="t1")
    assert re.search(r'id="t1-ro-x"', frag) and re.search(r'id="t1-ro-u"', frag)


def test_行距不小于盒高():
    """CONTRACT §1.5：行距按盒高算不是按字号算。代码排就不该压字"""
    frag, rect = scenegen.panel_svg(FULL, ["x", "u", "k"])
    ys = sorted(float(m) for m in re.findall(r'<text[^>]*\by="([\d.]+)"', frag))
    gaps = [round(b - a, 3) for a, b in zip(ys, ys[1:]) if b - a > 0.01]
    assert gaps and min(gaps) >= scenegen.LINE_H - 0.01, gaps


def test_读数在矩形里():
    frag, rect = scenegen.panel_svg(FULL, ["x", "u"])
    xs = [float(m) for m in re.findall(r'<text[^>]*\bx="([\d.]+)"', frag)]
    ys = [float(m) for m in re.findall(r'<text[^>]*\by="([\d.]+)"', frag)]
    assert min(xs) >= rect["x"] - 0.01 and max(xs) <= rect["x"] + rect["w"] + 0.01
    assert min(ys) >= rect["y"] - 0.01 and max(ys) <= rect["y"] + rect["h"] + 0.01


# ---------------------------------------------------------------- 完整骨架
def test_骨架四样齐全():
    sk = scenegen.skeleton(FULL)
    assert set(sk) >= {"js", "panel", "caption", "rect", "readouts"}
    assert "@@DRAW@@" in sk["js"], "必须留出给 draw.js 的插入点"
    for name in ("probe", "probeAll", "updatePanel", "seek", "duration", "cases"):
        assert name in sk["js"], name


def test_骨架过node_check(tmp_path):
    sk = scenegen.skeleton(FULL)
    p = tmp_path / "s.js"
    p.write_text("window.Scenes={};\n" + sk["js"], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]


def test_骨架没有drawFrame也不炸(tmp_path):
    """agent 还没写 draw.js 时，骨架自己要能装载 —— 否则第一轮连报错都看不清"""
    sk = scenegen.skeleton(FULL)
    prog = ("var window={Scenes:{}};\n" + sk["js"] +
            "var fake={querySelector:function(){return {querySelector:function(){return null;}};}};\n"
            "var api=window.Scenes['t1'](fake);\n"
            "api.step(1.0); api.reset(); api.seek(0.5);\n"
            "console.log([typeof api.probe, api.duration, api.cases.join('|')].join(','));\n")
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert r.stdout.strip() == "function,6,c1|c2", r.stdout


def test_骨架不许有ES6():
    js = scenegen.skeleton(FULL)["js"]
    for bad in ("let ", "const ", "=>", "`"):
        assert bad not in js, "骨架里有 ES6 语法：%r" % bad


def test_按invariants的report排序():
    """report 里点名的量是 spec 自己的断言要报告的，按定义就是最要紧的。
    实测：按 probe_keys 原顺序取前 4 个，q1-gen2 会挑出 Fx1/Fy1/Fx2 三个分量，
    而这题真正要看的是合力 Fres"""
    spec = {**FULL,
            "probe_keys": ["u", "x", "k", "big"],
            "invariants": [{"report": "big[0]"}, {"report": "abs(big[-1])"},
                           {"report": "x[0]"}],
            "reference": ("def probe(u, case):\n"
                          "    return {'u': u, 'x': u, 'k': 2.0, 'big': u*3}\n")}
    got = scenegen.pick_readouts(spec, scenegen.table_of(spec))
    assert got[0] == "big", got
    assert got[1] == "x", got


def test_没有invariants也能挑():
    spec = {**FULL, "invariants": []}
    got = scenegen.pick_readouts(spec, scenegen.table_of(spec))
    assert "x" in got and "u" not in got
