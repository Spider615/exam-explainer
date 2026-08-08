#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scenegen.py —— 从 spec 生成场景骨架：数值表、probe、读数面板、figcaption

    python pipeline/scenegen.py <spec.json> -o <目录>

为什么有这个模块
----------------
⑤ 的 agent 原来要自己用 JS 重写一遍物理。实测门禁失败 47 次里 **L4 物理断言占
34 次** —— 而 spec 里早就躺着一份可执行的 `reference`，并且 ④b 已经用
`invariants` 验过它。agent 最容易出错的那部分，是在重抄一份已经写好、
已经验证过的东西。

所以：物理由代码从 `reference` 预计算成数值表，agent 只画图。

为什么查表不转译成 JS
---------------------
33 份有 `reference` 的 spec 里有 88 个 `if`、12 个 `for`、2 个 `while`、
58 个嵌套函数定义。把它转译成 JS 是个编译器项目，**而且转错了是静默的** ——
数值悄悄偏一点，门禁未必抓得到，页面上看起来一切正常。查表没有这个风险。

为什么全精度不截断
------------------
⑥ 的 L4 就在 `sample_points` 个点上采样，表也在这些点上生成，**逐位相等**。
截断到 9 位能省三成体积，但那条「逐位相等」就不成立了，而它正是这次改动的
全部价值。实测 gzip 后才 4–37KB，不值得。

没有 reference 的 spec 怎么办
-----------------------------
`can_codegen()` 挡下来，调用方**退回现有 agent 流程**，不是硬跑然后失败。
库里真正会进 ⑤ 的 21 份里只有 1 份没有（④b 要求它之前的遗留）。
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speccheck

# 读数面板的排版常量。来自 CONTRACT.md §1.5 的实测字宽表（`.n` 等宽类）：
# 盒高 12.6px、ASCII 字宽 6.62px、CJK 字宽 11.0px。行距取盒高 + 2px 余量。
LINE_H = 14.6
CH_ASCII = 6.62
CH_CJK = 11.0
PANEL_PAD = 6.0
PANEL_RIGHT = 548.0        # 右边界，与 CONTRACT §1.5 第 4 条一致
PANEL_TOP = 10.0
MAX_READOUTS = 4
DEFAULT_PERIOD = 6.0


def _w(s):
    """按实测字宽表算一段文字的宽度（用户单位）。"""
    return sum(CH_CJK if ord(c) > 0x2E7F else CH_ASCII for c in str(s))


# ---------------------------------------------------------------- 表
def table_of(spec):
    """`{case: {量名: [N 个采样值]}}`。直接用 ④b 那份现成的子进程跑法。"""
    return speccheck.run_reference(spec)


def const_keys(table):
    """
    全程不变的量。它们不该占读数面板的行 —— 一个恒等于 1 的 F 没有信息量。

    **要在所有 case 上都不变才算常量**：某个量在 c1 里是定值、在 c2 里会动，
    那它恰恰是这道题要对照的东西。
    """
    all_keys = set()
    for cols in table.values():
        all_keys |= set(cols)
    return {k for k in all_keys
            if all(cols.get(k) and max(cols[k]) == min(cols[k])
                   for cols in table.values())}


def can_codegen(spec):
    """
    这份 spec 能不能走代码生成。回 `(能不能, 为什么不能)`。

    挡下来的三种：没有 `reference`、`reference` 跑不起来、跑出来缺 `probe_keys`
    里的键。第三种尤其要在**生成期**挡 —— 放过去的话 ⑥ 的 L3 会报「probe 缺少
    键 x」，但那时候一轮已经烧完了。
    """
    if not (spec.get("reference") or "").strip():
        return (False, "spec 没有 reference，走不了代码生成")
    try:
        t = table_of(spec)
    except Exception as e:
        return (False, "reference 跑不起来：%s" % str(e)[:160])
    if not t:
        return (False, "reference 一个 case 都没跑出来")
    want = set(spec.get("probe_keys") or [])
    for cid, cols in t.items():
        miss = want - set(cols)
        if miss:
            return (False, "case %s 的 reference 缺 probe_keys 里的键：%s"
                           % (cid, "、".join(sorted(miss))))
    return (True, "")


# ---------------------------------------------------------------- probe 骨架
def probe_js(spec, table):
    """
    骨架里 `CASES` / `N` / `T` / `probe` / `probeAll` 那一段。ES5。

    `probe` 在采样点上**逐位等于** `reference`；点之间线性插值。
    `u` 越界一律夹到 [0,1]，不认识的 case 退回第一个 —— 这两处宁可给一个
    有限数值，也不能抛异常：⑥ 的 L3 会把异常算成失败，而那是个假失败。
    """
    cases = [c["id"] for c in (spec.get("cases") or [{"id": "c1"}])]
    n = len(next(iter(table.values()))["u"]) if table and "u" in next(iter(table.values())) \
        else int(spec.get("sample_points") or 401)
    return (
        'var CASES = %s;\n'
        'var N = %d;\n'
        'var T = %s;\n'
        'function probe(u, cid) {\n'
        '  var col = T[cid] || T[CASES[0]];\n'
        '  if (!(u >= 0)) u = 0;\n'
        '  if (u > 1) u = 1;\n'
        '  var x = u * (N - 1), i = Math.floor(x), f = x - i;\n'
        '  if (i >= N - 1) { i = N - 2; f = 1; }\n'
        '  if (i < 0) { i = 0; f = 0; }\n'
        '  var r = {}, k;\n'
        '  for (k in col) r[k] = col[k][i] * (1 - f) + col[k][i + 1] * f;\n'
        '  return r;\n'
        '}\n'
        'function probeAll(u) {\n'
        '  var m = {}, i;\n'
        '  for (i = 0; i < CASES.length; i++) m[CASES[i]] = probe(u, CASES[i]);\n'
        '  return m;\n'
        '}\n'
        % (json.dumps(cases), n, json.dumps(table, separators=(",", ":")))
    )


# ---------------------------------------------------------------- 面板
def pick_readouts(spec, table, declared=None):
    """
    面板上显示哪些量。

    `declared` 是 `draw.js` 里的 `READOUTS` —— agent 知道这个场景在讲什么，
    这是它该定的。声明了不存在的键**当场抛**：放过去的话面板会多一行永远
    显示 undefined 的读数。

    没声明就自动挑，**按 `invariants[].report` 里的出现频次排序**：那些是 spec
    自己的断言点名要报告的量，按定义就是这道题最要紧的。按 `probe_keys` 的原始
    顺序取前几个不行 —— 实测 q1-gen2 会挑出 `Fx1/Fy1/Fx2` 三个分量，
    而这题真正要看的是合力 `Fres`（它在 report 里排第一）。

    两类一律排除：`u`（是进度不是物理量）、全程不变的常量列。
    """
    keys = list(spec.get("probe_keys") or [])
    if declared:
        bad = [k for k in declared if k not in keys]
        if bad:
            raise ValueError("READOUTS 里有 probe_keys 之外的键：%s" % "、".join(bad))
        return list(declared)[:MAX_READOUTS]

    skip = {"u"} | const_keys(table)
    cand = [k for k in keys if k not in skip]
    hits = {}
    for inv in (spec.get("invariants") or []):
        for tok in re.findall(r"[A-Za-z_]\w*", str(inv.get("report") or "")):
            if tok in cand:
                hits[tok] = hits.get(tok, 0) + 1
    # 上过 report 的按频次降序在前，没上过的按原顺序在后
    cand.sort(key=lambda k: (-hits.get(k, 0), keys.index(k)))
    return cand[:MAX_READOUTS]


def _label(spec, key):
    """标签取自 probe_key_meaning，截到 6 字；取不到就用键名。"""
    m = (spec.get("probe_key_meaning") or {}).get(key) or ""
    m = re.split(r"[，,（(=]", m)[0].strip()
    return (m[:6] if m else key)


def panel_svg(spec, keys, sid=None):
    """
    读数面板的 SVG 片段，回 `(片段, 矩形)`。

    **排版全由代码**：行距按 CONTRACT §1.5 的实测盒高算，不会压字。
    右上角对齐，宽度按最长标签 + 数值位宽算。
    """
    sid = sid or spec.get("id") or "s"
    labs = [_label(spec, k) for k in keys]
    lab_w = max([_w(x) for x in labs] or [0])
    val_w = _w("-000.00")
    w = PANEL_PAD * 2 + lab_w + 8 + val_w
    h = PANEL_PAD * 2 + LINE_H * max(1, len(keys))
    x = PANEL_RIGHT - w
    rows = []
    for i, (k, lab) in enumerate(zip(keys, labs)):
        y = PANEL_TOP + PANEL_PAD + LINE_H * (i + 0.75)
        rows.append('  <text class="u" x="%.1f" y="%.1f">%s</text>'
                    % (x + PANEL_PAD, y, lab))
        rows.append('  <text class="n" id="%s-ro-%s" x="%.1f" y="%.1f" '
                    'text-anchor="end">–</text>'
                    % (sid, k, x + w - PANEL_PAD, y))
    frag = ('<rect class="sh" x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
            'rx="2" fill="var(--panel)"/>\n%s'
            % (x, PANEL_TOP, w, h, "\n".join(rows)))
    return (frag, {"x": x, "y": PANEL_TOP, "w": w, "h": h})


def panel_js(spec, keys, sid=None):
    """面板的引用与更新。多 case 时取第一个 case 的值 —— 面板是概览，不是对照表。"""
    sid = sid or spec.get("id") or "s"
    refs = ",\n".join('    "%s": svg.querySelector("#%s-ro-%s")' % (k, sid, k)
                      for k in keys)
    return (
        'var panelEls = {\n%s\n};\n'
        'var panelCase = CASES[0];\n'
        'function updatePanel(ps) {\n'
        '  var p = ps[panelCase] || ps[CASES[0]], k, el, v;\n'
        '  for (k in panelEls) {\n'
        '    el = panelEls[k];\n'
        '    if (!el) continue;\n'
        '    v = p[k];\n'
        '    el.textContent = (typeof v === "number" && isFinite(v))\n'
        '      ? (Math.abs(v) >= 1000 || (v !== 0 && Math.abs(v) < 0.01)\n'
        '          ? v.toExponential(2) : v.toFixed(2))\n'
        '      : "–";\n'
        '  }\n'
        '}\n' % refs)


def caption(spec):
    """
    figcaption 的内容：标题 + **全部 `must_contain` 原文**。

    L1 查的是这些原文在不在产物里，拼进去就必然在 —— **这才是 L1 恒真的做法**。
    实测 99 条 `must_contain` 中位 26 字、51% 超过 24 字，塞不进 SVG 读数面板；
    figcaption 是纯文本、CSS 自动换行，长短不影响版面，也不进 L5 的文字盒计算。

    **原文照抄，不改写不截断** —— 改一个字 L1 就不认了。
    """
    parts = []
    if spec.get("title"):
        parts.append(str(spec["title"]).strip().rstrip("。"))
    for d in (spec.get("disclosures") or []):
        s = (d.get("must_contain") or "").strip()
        if s:
            parts.append(s)
    return "。".join(parts) + ("。" if parts else "")


# ---------------------------------------------------------------- 完整骨架
SKEL = """window.Scenes["%(sid)s"] = function (fig) {
  var svg = fig.querySelector('svg');

  /* ===== 以下到 @@DRAW@@ 由 pipeline/scenegen.py 生成，不要手改 ===== */
%(probe)s
%(panel)s
  var PANEL_RECT = %(rect)s;

  /* @@DRAW@@ */

  var PERIOD = (typeof PERIOD === "number" && PERIOD > 0) ? PERIOD : %(period).1f;
  function render(u) {
    var ps = probeAll(u);
    updatePanel(ps);
    if (typeof drawFrame === "function") drawFrame(ps, u, svg);
  }
  return {
    step: function (t) { render((t %% PERIOD) / PERIOD); },
    reset: function () { if (typeof drawReset === "function") drawReset(svg); },
    probe: probe,
    /* 下面三样是给宿主做时间轴用的。老场景没有，宿主要检测再用 */
    duration: PERIOD,
    cases: CASES,
    seek: function (u) {
      if (typeof drawReset === "function") drawReset(svg);
      render(u < 0 ? 0 : (u > 1 ? 1 : u));
    },
    /* 多 case 场景：drawFrame 本来就同时拿到所有 case（画面上一起画），
       所以能切的是**面板显示哪一个的读数**，不是切画面 */
    setCase: function (cid) {
      for (var i = 0; i < CASES.length; i++) if (CASES[i] === cid) panelCase = cid;
      return panelCase;
    },
    currentCase: function () { return panelCase; }
  };
};
"""


def _indent(s, n=2):
    return "\n".join((" " * n + ln) if ln.strip() else ln for ln in s.splitlines())


def skeleton(spec, declared_readouts=None):
    """
    一次产出四样：骨架 JS、面板 SVG 片段、figcaption、面板矩形。

    骨架里留 `/* @@DRAW@@ */`，`harness/build.py` 把 agent 的 `draw.js` 插在那里。
    """
    sid = spec.get("id") or "s"
    t = table_of(spec)
    keys = pick_readouts(spec, t, declared_readouts)
    frag, rect = panel_svg(spec, keys, sid)
    js = SKEL % {
        "sid": sid,
        "probe": _indent(probe_js(spec, t)),
        "panel": _indent(panel_js(spec, keys, sid)),
        "rect": json.dumps(rect),
        "period": DEFAULT_PERIOD,
    }
    return {"js": js, "panel": frag, "caption": caption(spec),
            "rect": rect, "readouts": keys}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    ok, why = can_codegen(spec)
    if not ok:
        print("✗ 走不了代码生成：%s" % why)
        return 1
    sk = skeleton(spec)
    os.makedirs(a.out, exist_ok=True)
    sid = spec["id"]
    open(os.path.join(a.out, sid + ".skel.js"), "w", encoding="utf-8").write(sk["js"])
    open(os.path.join(a.out, sid + ".panel.svg"), "w", encoding="utf-8").write(sk["panel"])
    open(os.path.join(a.out, sid + ".caption.txt"), "w", encoding="utf-8").write(sk["caption"])
    print("✓ %s：读数 %s，面板矩形 %s" % (sid, "、".join(sk["readouts"]), sk["rect"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
