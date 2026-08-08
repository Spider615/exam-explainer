#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py —— 把 agent 写的两个文件和代码生成的骨架拼成 ⑥ 要验的产物

    python3 harness/build.py <id> [-d 工作目录]

    读：  <id>.figure.html   agent 画的场景（必须留 <g id="__panel__"></g>）
          <id>.draw.js       agent 写的 PERIOD / READOUTS / drawFrame / drawReset
    写：  <id>.figure.html   面板与 figcaption 已注入
          <id>.js            骨架 + draw.js

为什么要这一步
--------------
物理与读数面板由 `pipeline/scenegen.py` 从 spec 生成，agent 只画图。
两边得有人拼起来，而且**拼装本身要能挡住 agent 绕过骨架**：
它在 `draw.js` 里自己定义一个 `probe`，就把代码生成的那份覆盖了，
L4 恒真的保证当场作废。所以这里逐个检查，不是叮嘱。

幂等
----
agent 每一轮都会跑这个命令。面板注入到 `<g id="__panel__">` 的**内容**里
（先清空再写），figcaption 整段替换 —— 连跑 N 次结果相同。
不幂等的话面板会一层层叠，而那种画面 agent 自己也看不懂。

面板侵入检查的边界
------------------
这里只查带显式坐标属性的图元（`x/y/cx/cy/x1/y1/x2/y2`）落没落进面板矩形。
`<path d="…">` 查不了 —— 要精确判得进浏览器拿 `getBBox()`，那是 ⑥ 的活。
所以这条是**便宜的粗筛**，不是完备判据；漏掉的由目检兜。
"""
import argparse, json, os, re, sys

HARNESS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HARNESS)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import scenegen                                    # noqa: E402

PANEL_SLOT = "__panel__"
# draw.js 只准定义这四样。别的名字撞上骨架就会覆盖它
ALLOWED_DEFS = {"PERIOD", "READOUTS", "drawFrame", "drawReset"}
# 这些名字被 agent 定义或赋值 = 想绕过骨架，一律挡下
FORBIDDEN = ("probe", "probeAll", "updatePanel", "render", "T", "N", "CASES",
             "panelEls", "PANEL_RECT")

_COORD = re.compile(r'\b(?:x|y|cx|cy|x1|y1|x2|y2)\s*=\s*"(-?[\d.]+)"')
_TAG = re.compile(r"<(line|circle|rect|ellipse|text|polyline|polygon|image|use)\b[^>]*>",
                  re.I)


def _read(wd, name):
    p = os.path.join(wd, name)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else None


def _declared_readouts(draw):
    m = re.search(r"\bvar\s+READOUTS\s*=\s*(\[[^\]]*\])", draw)
    if not m:
        return None
    try:
        return [str(x) for x in json.loads(m.group(1).replace("'", '"'))]
    except Exception:
        return None


def _declared_period(draw):
    """回 (值, 有没有写)。写了但不是正数由调用方报错 —— 那和「没写」是两回事。"""
    m = re.search(r"\bvar\s+PERIOD\s*=\s*(-?[\d.]+)", draw)
    if not m:
        return (None, False)
    try:
        return (float(m.group(1)), True)
    except ValueError:
        return (None, True)


def _forbidden_defs(draw):
    """agent 有没有定义/赋值那些属于骨架的名字。"""
    hit = []
    for name in FORBIDDEN:
        pat = (r"(?:\bfunction\s+%s\s*\(|\bvar\s+%s\b|(?:^|\n)\s*%s\s*=[^=])"
               % (name, name, name))
        if re.search(pat, draw):
            hit.append(name)
    return hit


_PANEL_G = re.compile(r'<g\b[^>]*\bid="%s"[^>]*>.*?</g>' % PANEL_SLOT, re.S)


def _strip_panel(fig):
    """
    把面板组的内容整段挖掉。

    **不挖的话第二次跑就会误报**：面板自己的 rect 和 text 当然落在面板矩形里，
    于是「幂等」和「侵入检查」互相打架 —— 这个 bug 是幂等测试逮到的。
    """
    return _PANEL_G.sub("", fig)


def _intrude(fig, rect):
    """有没有图元的坐标落进面板矩形。见模块开头「面板侵入检查的边界」。"""
    fig = _strip_panel(fig)
    x0, y0 = rect["x"], rect["y"]
    x1, y1 = x0 + rect["w"], y0 + rect["h"]
    bad = []
    for m in _TAG.finditer(fig):
        tag = m.group(0)
        if 'id="%s"' % PANEL_SLOT in tag:
            continue
        xs = [float(v) for v in _COORD.findall(tag)]
        # 成对取 (x, y)：属性顺序不保证，但落进矩形的点用任一配对都能发现
        for i in range(0, len(xs) - 1, 2):
            if x0 <= xs[i] <= x1 and y0 <= xs[i + 1] <= y1:
                bad.append(tag[:70])
                break
    return bad


def _inject_panel(fig, frag):
    """把面板写进 <g id="__panel__">…</g> 的内容里（先清空）。幂等。"""
    pat = re.compile(r'(<g\b[^>]*\bid="%s"[^>]*>)(.*?)(</g>)' % PANEL_SLOT, re.S)
    if pat.search(fig):
        return pat.sub(lambda m: m.group(1) + "\n" + frag + "\n" + m.group(3), fig, count=1)
    # 自闭合写法 <g id="__panel__"/>
    pat2 = re.compile(r'<g\b([^>]*\bid="%s"[^>]*)/>' % PANEL_SLOT)
    if pat2.search(fig):
        return pat2.sub(lambda m: "<g%s>\n%s\n</g>" % (m.group(1), frag), fig, count=1)
    return None


def _inject_caption(fig, text):
    """整段替换 figcaption 的内容。没有就在 </figure> 前补一个。幂等。"""
    pat = re.compile(r"(<figcaption\b[^>]*>)(.*?)(</figcaption>)", re.S)
    if pat.search(fig):
        return pat.sub(lambda m: m.group(1) + text + m.group(3), fig, count=1)
    if "</figure>" in fig:
        return fig.replace("</figure>",
                           '<figcaption class="u">%s</figcaption>\n</figure>' % text, 1)
    return fig + '\n<figcaption class="u">%s</figcaption>\n' % text


def assemble(wd, sid, spec):
    """
    拼装并检查。回问题列表，空表示成功。**有任何问题就不写文件** ——
    半成品会让下一轮的门禁报出一堆与真正病因无关的错。
    """
    probs = []
    ok, why = scenegen.can_codegen(spec)
    if not ok:
        return ["这份 spec 走不了代码生成：%s" % why]

    fig = _read(wd, sid + ".figure.html")
    draw = _read(wd, sid + ".draw.js")
    if fig is None:
        probs.append("缺 %s.figure.html" % sid)
    if draw is None:
        probs.append("缺 %s.draw.js" % sid)
    if probs:
        return probs

    for fn in ("drawFrame", "drawReset"):
        if not re.search(r"\bfunction\s+%s\s*\(" % fn, draw):
            probs.append("%s.draw.js 里没有 function %s(...) —— 骨架会调用它"
                         % (sid, fn))
    bad = _forbidden_defs(draw)
    if bad:
        probs.append("%s.draw.js 里定义了属于骨架的名字：%s。"
                     "物理与面板由代码生成，你写了会把它们覆盖掉"
                     % (sid, "、".join(bad)))

    period, has_period = _declared_period(draw)
    if has_period and not (period and period > 0):
        probs.append("%s.draw.js 的 PERIOD 必须是正数（现在是 %r）" % (sid, period))

    declared = _declared_readouts(draw)
    try:
        sk = scenegen.skeleton(spec, declared)
    except ValueError as e:
        probs.append(str(e))
        return probs

    if PANEL_SLOT not in fig:
        probs.append('%s.figure.html 里必须留一个 <g id="%s"></g> 给读数面板'
                     % (sid, PANEL_SLOT))
        return probs

    intr = _intrude(fig, sk["rect"])
    if intr:
        probs.append("有 %d 个图元画进了面板矩形 %s（那块是禁区）：%s"
                     % (len(intr), json.dumps(sk["rect"]), intr[0]))

    if probs:
        return probs

    fig2 = _inject_panel(fig, sk["panel"])
    if fig2 is None:
        return ['%s.figure.html 里的 <g id="%s"> 写法认不出来' % (sid, PANEL_SLOT)]
    fig2 = _inject_caption(fig2, sk["caption"])

    js = sk["js"].replace("/* @@DRAW@@ */", draw.strip())
    open(os.path.join(wd, sid + ".figure.html"), "w", encoding="utf-8").write(fig2)
    open(os.path.join(wd, sid + ".js"), "w", encoding="utf-8").write(js)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sid")
    ap.add_argument("-d", "--dir", default=".")
    ap.add_argument("-s", "--spec", default=None,
                    help="spec 路径；默认 <repo>/specs/<id>.spec.json")
    a = ap.parse_args()
    sp = a.spec or os.path.join(ROOT, "specs", a.sid + ".spec.json")
    if not os.path.exists(sp):
        print("找不到 spec：%s" % sp)
        return 2
    spec = json.load(open(sp, encoding="utf-8"))
    probs = assemble(a.dir, a.sid, spec)
    if probs:
        print("✗ 拼装失败：")
        for p in probs:
            print("   ·", p)
        return 1
    print("✓ 拼装完成：%s.figure.html + %s.js" % (a.sid, a.sid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
