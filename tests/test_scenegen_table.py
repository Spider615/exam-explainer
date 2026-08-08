# -*- coding: utf-8 -*-
import json, subprocess
import scenegen

SPEC = {
    "id": "t1",
    "cases": [{"id": "c1", "label": "甲"}, {"id": "c2", "label": "乙"}],
    "sample_points": 5,
    "probe_keys": ["u", "x", "k"],
    "probe_key_meaning": {"u": "归一化过程进度", "x": "位移", "k": "常量"},
    "invariants": [],
    "reference": (
        "def probe(u, case):\n"
        "    k = 2.0\n"
        "    x = u * (1.0 if case == 'c1' else 2.0)\n"
        "    return {'u': u, 'x': x, 'k': k}\n"),
}


def test_表的形状():
    t = scenegen.table_of(SPEC)
    assert set(t) == {"c1", "c2"}
    assert set(t["c1"]) == {"u", "x", "k"}
    assert len(t["c1"]["x"]) == 5


def test_采样点是均匀的0到1():
    t = scenegen.table_of(SPEC)
    assert t["c1"]["u"] == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_不同case值不同():
    t = scenegen.table_of(SPEC)
    assert t["c1"]["x"][-1] == 1.0 and t["c2"]["x"][-1] == 2.0


def test_认得出常量列():
    """全程不变的量不该占读数面板的行"""
    assert scenegen.const_keys(scenegen.table_of(SPEC)) == {"k"}


def test_没有reference就说清楚不能走():
    ok, why = scenegen.can_codegen({**SPEC, "reference": ""})
    assert not ok and "reference" in why
    ok, why = scenegen.can_codegen(SPEC)
    assert ok, why


def test_reference跑不起来也说清楚():
    ok, why = scenegen.can_codegen({**SPEC, "reference": "def probe(u, case):\n    1/0\n"})
    assert not ok and "跑不起来" in why


def test_reference少给键也要挡下来():
    """probe_keys 里有的，表里必须都有 —— 少一个的话 L3 会报缺键，
    但那时候已经烧完一轮了，不如在生成期就挡住"""
    bad = {**SPEC, "reference": "def probe(u, case):\n    return {'u': u}\n"}
    ok, why = scenegen.can_codegen(bad)
    assert not ok and ("x" in why or "缺" in why)


def test_生成的probe跟表逐位相等():
    """拿 node 真跑一遍生成的 probe，和 Python 侧的表逐位比 —— 不是看着像对"""
    t = scenegen.table_of(SPEC)
    prog = scenegen.probe_js(SPEC, t) + """
var bad = 0, T2 = %s;
for (var c in T2) for (var k in T2[c]) for (var i = 0; i < T2[c][k].length; i++) {
  var u = i / (N - 1), got = probe(u, c)[k];
  if (got !== T2[c][k][i]) bad++;
}
console.log(bad === 0 ? "SAME" : "DIFF " + bad);
""" % json.dumps(t)
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert r.stdout.strip() == "SAME", r.stdout


def test_probeAll一次给全部case():
    t = scenegen.table_of(SPEC)
    prog = scenegen.probe_js(SPEC, t) + """
var m = probeAll(1.0);
console.log(JSON.stringify([Object.keys(m).sort(), m.c1.x, m.c2.x]));
"""
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert json.loads(r.stdout.strip()) == [["c1", "c2"], 1.0, 2.0]


def test_u越界不炸():
    t = scenegen.table_of(SPEC)
    prog = scenegen.probe_js(SPEC, t) + """
var a = probe(1.0, "c1"), b = probe(1.5, "c1"), c = probe(-0.3, "c1");
console.log([isFinite(a.x), isFinite(b.x), isFinite(c.x)].join(","));
"""
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "true,true,true", r.stdout + r.stderr[-200:]


def test_不认识的case退回第一个而不是崩():
    t = scenegen.table_of(SPEC)
    prog = scenegen.probe_js(SPEC, t) + """
console.log(isFinite(probe(0.5, "不存在的case").x) ? "ok" : "bad");
"""
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "ok", r.stdout + r.stderr[-200:]


def test_生成的js过node_check(tmp_path):
    js = scenegen.probe_js(SPEC, scenegen.table_of(SPEC))
    p = tmp_path / "t.js"
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-300:]


def test_不许出现ES6语法():
    js = scenegen.probe_js(SPEC, scenegen.table_of(SPEC))
    for bad in ("let ", "const ", "=>", "`"):
        assert bad not in js, "生成的骨架里有 ES6 语法：%r" % bad


def test_表不许被截断():
    """截断会破坏「采样点上逐位相等」，那是这次改动的全部价值"""
    spec = {**SPEC, "reference": "def probe(u, case):\n"
                                 "    return {'u': u, 'x': u/3.0, 'k': 2.0}\n"}
    js = scenegen.probe_js(spec, scenegen.table_of(spec))
    assert "0.3333333333333333" in js, "小数位被截掉了"
