#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scenedecl.py —— 声明式场景 → figure.html + draw.js（**探针，不是正式链路**）

    python pipeline/scenedecl.py <decl.json> -o <工作目录>

在验一件事：把场景写成一份声明、由代码渲染，能不能过 ⑥，以及要多久。
背景与判据见 `docs/superpowers/specs/2026-08-08-scene-codegen-design.md`
的「后续方向的测量」一节 —— 9 种图元覆盖 99.5%，但场景组合不收敛，
所以走「声明式图元」而不是「模板库」。

声明长什么样
------------
```jsonc
{
  "viewBox": [0, 0, 560, 280],
  "period": 4.0,
  "readouts": ["v", "x", "P"],
  "parts": [
    {"id": "rail-t", "kind": "line", "x1": 40, "y1": 100, "x2": 520, "y2": 100},
    {"id": "field",  "kind": "field", "rect": [100, 90, 420, 100], "step": 40},
    {"id": "rod-a",  "kind": "bar", "x": 100, "y": [95, 185], "cls": "sr",
     "bind": {"x": "100 + x*390"}},
    {"id": "vArrow", "kind": "arrow", "x1": 0, "y1": 0, "x2": 0, "y2": 0,
     "bind": {"x1": "100+x*390", "x2": "100+x*390+30"}}
  ],
  "labels": [
    {"id": "lab-a", "text": "a", "of": "rod-a", "at": "above"},
    {"id": "lab-x", "text": "x",  "xy": [495, 225]}
  ]
}
```

`bind` 里的值是 **JS 表达式**，作用域里有 spec 的全部 `probe_keys`
（多情形时还有 `c1`、`c2`… 各自的对象），以及 `u` 和 `Math`。

标签为什么单独一类
------------------
实测 41 个场景 2118 个图元里，**文字标签占 47.5%**，而它正是压字问题的来源。
声明里只说「这个标签属于哪个零件、放它哪一边」，**坐标由渲染器算，
并且自动避让** —— 这是这条路线相对「让模型自己摆坐标」的全部意义。
"""
import argparse, json, math, os, re, sys

# 与 CONTRACT §1.5 的实测字宽表一致
CH_ASCII, CH_CJK, BOX_H = 6.0, 13.1, 14.9
LABEL_GAP = 6.0            # 标签与被标注对象之间留多少
NUDGE = 4.0                # 一次避让挪多远
MAX_NUDGE = 12             # 最多挪几次，挪不开就认了并报出来

CLS = {"line": "sk", "bar": "sk", "arrow": "sa", "rect": "sh",
       "circle": "fk", "arc": "sc", "poly": "sk"}


def _w(s):
    return sum(CH_CJK if ord(c) > 0x2E7F else CH_ASCII for c in str(s))


# ---------------------------------------------------------------- 图元 → 静态 SVG
def _svg_part(sid, p):
    k, i = p["kind"], "%s-%s" % (sid, p["id"])
    cls = p.get("cls") or CLS.get(k, "sk")
    if k in ("line", "arrow"):
        mk = ' marker-end="url(#%s)"' % ("aa" if cls == "sa" else "ak") if k == "arrow" else ""
        return ('  <line id="%s" class="%s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"%s/>'
                % (i, cls, p.get("x1", 0), p.get("y1", 0), p.get("x2", 0), p.get("y2", 0), mk))
    if k == "bar":
        y0, y1 = p.get("y", [0, 10])
        return ('  <line id="%s" class="%s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke-width="4"/>' % (i, cls, p.get("x", 0), y0, p.get("x", 0), y1))
    if k == "rect":
        x, y, w, h = p.get("rect", [0, 0, 10, 10])
        return ('  <rect id="%s" class="%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                % (i, cls, x, y, w, h))
    if k == "circle":
        return ('  <circle id="%s" class="%s" cx="%.1f" cy="%.1f" r="%.1f"/>'
                % (i, cls, p.get("cx", 0), p.get("cy", 0), p.get("r", 4)))
    if k == "arc":
        return '  <path id="%s" class="%s" d="%s" fill="none"/>' % (i, cls, p.get("d", "M0,0"))
    if k == "poly":
        pts = " ".join("%.1f,%.1f" % tuple(q) for q in p.get("points", [[0, 0]]))
        return '  <polyline id="%s" class="%s" points="%s" fill="none"/>' % (i, cls, pts)
    if k == "field":
        x, y, w, h = p["rect"]
        st = p.get("step", 40)
        sym = p.get("symbol", "×")
        cells = []
        yy = y + st / 2
        while yy < y + h:
            xx = x + st / 2
            while xx < x + w:
                cells.append('    <text x="%.1f" y="%.1f" font-size="16">%s</text>'
                             % (xx, yy, sym))
                xx += st
            yy += st
        return '  <g id="%s" class="sh">\n%s\n  </g>' % (i, "\n".join(cells))
    raise ValueError("不认识的图元 kind=%r" % k)


# ---------------------------------------------------------------- 标签自动摆位
def _anchor_xy(parts, of, at):
    """被标注零件的锚点。认不出就回 None，由调用方报错。"""
    p = next((q for q in parts if q["id"] == of), None)
    if p is None:
        return None
    k = p["kind"]
    if k in ("line", "arrow"):
        cx = (p.get("x1", 0) + p.get("x2", 0)) / 2.0
        cy = (p.get("y1", 0) + p.get("y2", 0)) / 2.0
        top, bot = min(p.get("y1", 0), p.get("y2", 0)), max(p.get("y1", 0), p.get("y2", 0))
        left, right = min(p.get("x1", 0), p.get("x2", 0)), max(p.get("x1", 0), p.get("x2", 0))
    elif k == "bar":
        cx = p.get("x", 0); y0, y1 = p.get("y", [0, 10])
        cy = (y0 + y1) / 2.0; top, bot, left, right = min(y0, y1), max(y0, y1), cx, cx
    elif k in ("rect", "field"):
        x, y, w, h = p["rect"]
        cx, cy, top, bot, left, right = x + w / 2, y + h / 2, y, y + h, x, x + w
    elif k == "circle":
        cx, cy = p.get("cx", 0), p.get("cy", 0)
        r = p.get("r", 4); top, bot, left, right = cy - r, cy + r, cx - r, cx + r
    else:
        return None
    return {"above": (cx, top - LABEL_GAP), "below": (cx, bot + BOX_H),
            "left": (left - LABEL_GAP, cy + 4), "right": (right + LABEL_GAP, cy + 4),
            "center": (cx, cy + 4)}.get(at, (cx, cy))


def _box(x, y, text, anchor):
    w, h = _w(text), BOX_H
    x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
    return [x0, y - h * 0.78, x0 + w, y + h * 0.22]


def _hit(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def place_labels(sid, parts, labels):
    """
    给每个标签算坐标，并**逐个避开已经放好的**。

    这是这条路线的核心：模型只说「标签 a 属于 rod-a、放上面」，
    压不压字由代码保证。挪不开的会报出来 —— 报出来比默默压着强。
    """
    placed, out, warn = [], [], []
    for L in labels:
        anchor = L.get("anchor", "middle")
        if "xy" in L:
            x, y = L["xy"]
        else:
            xy = _anchor_xy(parts, L.get("of"), L.get("at", "above"))
            if xy is None:
                raise ValueError("标签 %r 挂在不存在的零件 %r 上" % (L["id"], L.get("of")))
            x, y = xy
        dy = 0
        for _ in range(MAX_NUDGE):
            b = _box(x, y + dy, L["text"], anchor)
            if not any(_hit(b, q) for q in placed):
                break
            dy += NUDGE if L.get("at") != "above" else -NUDGE
        else:
            warn.append(L["id"])
        placed.append(_box(x, y + dy, L["text"], anchor))
        out.append((L, x, y + dy, anchor))
    return out, warn


# ---------------------------------------------------------------- 渲染
_IDENT = re.compile(r"(?<![.\w$])([A-Za-z_]\w*)")


def qualify(expr, keys, cases):
    """
    把裸的物理量名补成 `p.xxx`。

    **模型写 `xHand` 而不是 `p.xHand` 是可预期的**（实测第一次就这么写的），
    而这错在渲染期无声、在浏览器里才炸成 ReferenceError。
    与其反复叮嘱写法，不如让渲染器直接吸收 —— 这是「靠门禁不靠嘱咐」的
    另一种形态：不是挡住它，是让它写错也没关系。

    只补**确实是 probe_keys 里的名字**，且前面没有 `.`（`c1.x` 不动）。
    """
    ok = set(keys) - set(cases) - {"p", "u", "Math", "ps"}

    def sub(m):
        return "p." + m.group(1) if m.group(1) in ok else m.group(1)
    return _IDENT.sub(sub, str(expr))


def render(decl, sid, keys=None):
    """回 `(figure.html, draw.js, 摆不开的标签)`。**纯函数，不写盘。**"""
    parts, labels = decl.get("parts", []), decl.get("labels", [])
    vb = decl.get("viewBox", [0, 0, 560, 280])

    body = [_svg_part(sid, p) for p in parts]
    laid, warn = place_labels(sid, parts, labels)
    for L, x, y, anchor in laid:
        body.append('  <text id="%s-%s" class="%s" x="%.1f" y="%.1f" text-anchor="%s">%s</text>'
                    % (sid, L["id"], L.get("cls", "u"), x, y, anchor, L["text"]))
    body.append('  <g id="%s-panel"></g>' % sid)

    fig = ('<figure data-scene="%s"><svg viewBox="%s" role="img" aria-label="%s">\n%s\n</svg>\n'
           '<figcaption>占位</figcaption></figure>\n'
           % (sid, " ".join(str(v) for v in vb),
              decl.get("aria", "物理动画场景"), "\n".join(body)))

    # ---- draw.js：每个 bind 变成一次 setAttribute ----
    keys = list(keys or decl.get("keys") or [])
    cases = list(decl.get("use_cases") or [])
    lines = ["var PERIOD = %s;" % decl.get("period", 6.0),
             "var READOUTS = %s;" % json.dumps(decl.get("readouts", [])),
             "", "function drawFrame(ps, u, svg) {",
             "  var p = ps[CASES[0]], el;"]
    for cid in decl.get("use_cases", []):
        lines.append("  var %s = ps['%s'];" % (cid, cid))
    for p in parts + labels:
        b = p.get("bind") or {}
        if not b:
            continue
        lines.append("  el = svg.querySelector('#%s-%s');" % (sid, p["id"]))
        lines.append("  if (el) {")
        for attr, expr in b.items():
            e = qualify(expr, keys, cases)
            if attr == "text":
                lines.append("    el.textContent = %s;" % e)
            else:
                lines.append("    el.setAttribute('%s', %s);" % (attr, e))
        lines.append("  }")
    lines += ["}", "", "function drawReset(svg) { drawFrame(probeAll(0), 0, svg); }", ""]
    return fig, "\n".join(lines), warn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("decl")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("-s", "--spec", default=None,
                    help="spec 路径，用来把裸的物理量名补成 p.xxx")
    a = ap.parse_args()
    decl = json.load(open(a.decl, encoding="utf-8"))
    sid = decl["id"]
    keys = None
    if a.spec and os.path.exists(a.spec):
        keys = json.load(open(a.spec, encoding="utf-8")).get("probe_keys")
    fig, js, warn = render(decl, sid, keys)
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, sid + ".figure.html"), "w", encoding="utf-8").write(fig)
    open(os.path.join(a.out, sid + ".draw.js"), "w", encoding="utf-8").write(js)
    print("✓ 渲染完成：%s（%d 个零件、%d 个标签）" % (sid, len(decl.get("parts", [])),
                                                len(decl.get("labels", []))))
    if warn:
        print("  ⚠ 这几个标签挪 %d 次仍与别人重叠：%s" % (MAX_NUDGE, "、".join(warn)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
