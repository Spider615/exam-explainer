# -*- coding: utf-8 -*-
import os, re, subprocess, sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "harness"))
import build
from test_scenegen_table import SPEC

FULL = {**SPEC, "title": "演示", "invariants": [{"report": "x[0]"}],
        "disclosures": [{"why": "w", "must_contain": "当前位移x的数值"}]}

FIG = """<figure>
<svg viewBox="0 0 560 320" id="t1-svg">
  <line class="sk" id="t1-rod" x1="40" y1="200" x2="200" y2="200"/>
  <g id="__panel__"></g>
</svg>
<figcaption class="u">占位</figcaption>
</figure>"""

DRAW = """var PERIOD = 4.0;
var READOUTS = ["x"];
function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  svg.querySelector('#t1-rod').setAttribute('x2', 40 + p.x * 160);
}
function drawReset(svg) { }
"""


def _wd(tmp_path, fig=FIG, draw=DRAW, sid="t1"):
    d = tmp_path / sid
    d.mkdir(exist_ok=True)
    (d / (sid + ".figure.html")).write_text(fig, encoding="utf-8")
    (d / (sid + ".draw.js")).write_text(draw, encoding="utf-8")
    return str(d)


# ---------------------------------------------------------------- 正常路径
def test_拼得出来且过node_check(tmp_path):
    wd = _wd(tmp_path)
    probs = build.assemble(wd, "t1", FULL)
    assert probs == [], probs
    js = os.path.join(wd, "t1.js")
    assert os.path.exists(js)
    r = subprocess.run(["node", "--check", js], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]


def test_面板注入进去了(tmp_path):
    wd = _wd(tmp_path)
    build.assemble(wd, "t1", FULL)
    fig = open(os.path.join(wd, "t1.figure.html"), encoding="utf-8").read()
    assert 't1-ro-x' in fig, "面板的读数元素没进 figure"


def test_caption被换成生成的(tmp_path):
    wd = _wd(tmp_path)
    build.assemble(wd, "t1", FULL)
    fig = open(os.path.join(wd, "t1.figure.html"), encoding="utf-8").read()
    assert "当前位移x的数值" in fig and "占位" not in fig


def test_agent声明的PERIOD生效(tmp_path):
    """draw.js 里 var PERIOD = 4.0 要覆盖骨架的默认 6.0"""
    wd = _wd(tmp_path)
    build.assemble(wd, "t1", FULL)
    prog = ("var window={Scenes:{}};\n"
            + open(os.path.join(wd, "t1.js"), encoding="utf-8").read()
            + "var fake={querySelector:function(){return {querySelector:function(){"
              "return {setAttribute:function(){}};},setAttribute:function(){}};}};\n"
              "console.log(window.Scenes['t1'](fake).duration);\n")
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert r.stdout.strip() == "4", r.stdout


def test_声明的READOUTS生效(tmp_path):
    wd = _wd(tmp_path, draw=DRAW.replace('["x"]', '["k"]'))
    build.assemble(wd, "t1", FULL)
    fig = open(os.path.join(wd, "t1.figure.html"), encoding="utf-8").read()
    assert "t1-ro-k" in fig and "t1-ro-x" not in fig


# ---------------------------------------------------------------- 挡住的情况
def test_没有面板占位符要失败(tmp_path):
    wd = _wd(tmp_path, fig=FIG.replace('<g id="__panel__"></g>', ""))
    probs = build.assemble(wd, "t1", FULL)
    assert probs and any("__panel__" in p for p in probs)


def test_缺drawFrame要失败(tmp_path):
    wd = _wd(tmp_path, draw=DRAW.replace("function drawFrame", "function nope"))
    probs = build.assemble(wd, "t1", FULL)
    assert probs and any("drawFrame" in p for p in probs)


def test_缺drawReset要失败(tmp_path):
    wd = _wd(tmp_path, draw=DRAW.replace("function drawReset", "function nope2"))
    probs = build.assemble(wd, "t1", FULL)
    assert probs and any("drawReset" in p for p in probs)


def test_draw里定义probe要失败(tmp_path):
    """agent 想绕过骨架自己写物理，必须当场挡住 —— 靠门禁不靠嘱咐"""
    for name in ("probe", "probeAll", "updatePanel", "render"):
        wd = _wd(tmp_path, draw=DRAW + "\nfunction %s(a,b){return {};}\n" % name,
                 sid="t1")
        probs = build.assemble(wd, "t1", FULL)
        assert probs and any(name in p for p in probs), (name, probs)


def test_draw里给probe赋值也要失败(tmp_path):
    wd = _wd(tmp_path, draw=DRAW + "\nprobe = function(){return {};};\n")
    probs = build.assemble(wd, "t1", FULL)
    assert probs and any("probe" in p for p in probs)


def test_READOUTS有野键要失败(tmp_path):
    wd = _wd(tmp_path, draw=DRAW.replace('["x"]', '["nope"]'))
    probs = build.assemble(wd, "t1", FULL)
    assert probs and any("nope" in p for p in probs)


def test_PERIOD缺了用默认不失败(tmp_path):
    wd = _wd(tmp_path, draw=DRAW.replace("var PERIOD = 4.0;\n", ""))
    probs = build.assemble(wd, "t1", FULL)
    assert probs == [], probs


def test_PERIOD不是正数要失败(tmp_path):
    for bad in ("0", "-2", "0.0"):
        wd = _wd(tmp_path, draw=DRAW.replace("4.0", bad))
        probs = build.assemble(wd, "t1", FULL)
        assert probs and any("PERIOD" in p for p in probs), (bad, probs)


def test_图元侵进面板矩形要失败(tmp_path):
    """光靠提示词不够。面板矩形是禁区，代码来查"""
    sk_rect = build.scenegen.skeleton(FULL)["rect"]
    cx = sk_rect["x"] + sk_rect["w"] / 2
    cy = sk_rect["y"] + sk_rect["h"] / 2
    bad = FIG.replace('<g id="__panel__"></g>',
                      '<circle id="t1-bad" cx="%.1f" cy="%.1f" r="4"/>\n'
                      '  <g id="__panel__"></g>' % (cx, cy))
    wd = _wd(tmp_path, fig=bad)
    probs = build.assemble(wd, "t1", FULL)
    assert probs and any("面板" in p for p in probs), probs


def test_面板外的图元不误伤(tmp_path):
    wd = _wd(tmp_path)
    assert build.assemble(wd, "t1", FULL) == []


def test_没有reference的spec不许硬跑(tmp_path):
    wd = _wd(tmp_path)
    probs = build.assemble(wd, "t1", {**FULL, "reference": ""})
    assert probs and any("reference" in p for p in probs)


# ---------------------------------------------------------------- 幂等
def test_连跑两次结果一样(tmp_path):
    """agent 每一轮都会跑 build，不幂等的话面板会一层层叠"""
    wd = _wd(tmp_path)
    assert build.assemble(wd, "t1", FULL) == []
    a_fig = open(os.path.join(wd, "t1.figure.html"), encoding="utf-8").read()
    a_js = open(os.path.join(wd, "t1.js"), encoding="utf-8").read()
    assert build.assemble(wd, "t1", FULL) == []
    b_fig = open(os.path.join(wd, "t1.figure.html"), encoding="utf-8").read()
    b_js = open(os.path.join(wd, "t1.js"), encoding="utf-8").read()
    assert a_fig == b_fig and a_js == b_js


def test_跑三次面板也只有一份(tmp_path):
    wd = _wd(tmp_path)
    for _ in range(3):
        build.assemble(wd, "t1", FULL)
    fig = open(os.path.join(wd, "t1.figure.html"), encoding="utf-8").read()
    assert fig.count('id="t1-ro-x"') == 1
    assert fig.count("当前位移x的数值") == 1
