#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mathfix.py —— 把被压平的公式按版面坐标递归还原

问题
----
PDF 的文字层是一维的，公式是二维的。抽取时上下两行被首尾相接：

    F ∝ Mm/r²    →  'F ∝Mmr2'
    30π√(r/g)    →  '30π√rg'
    30π√(g/r)    →  '30π√gr'     ← 与上面只差字母顺序，选项 A、B 无法区分

这不是排版难看，是**语义信息丢失**。

信息其实都还在版面里
--------------------
分式   = 分子在上、分母在下、中间一条横线
根号   = √ 字形 + 一条上横线，被覆盖的部分是被开方式
上下标 = 字号变小 + 基线偏移

ingest 保留了每个文本块的 (x, y, 字号)，也抽出了全部水平细线，够用了。

关键判别
--------
横线有两种，靠**上下有没有内容**区分，非常干净：

    上下都有内容  →  分数线
    只有下方有    →  根号上横线（或上划线）

结构
----
公式是递归的（指数里能套分式，分式里能套根号），所以解析也必须递归：

    parse(区域)：
      1. 找覆盖本区大部分宽度、且上下都有内容的横线 → 分式，
         对分子区与分母区分别递归
      2. 遇到 √ → 找它右邻的上横线，对被覆盖区域递归
      3. 字号偏小且基线偏移 → 上标/下标，对该组递归
      4. 都不是 → 从左到右直接拼接

先按「靠横线连通」把页面切成若干**公式区域**，只对这些区域递归；
正文完全不碰——没有横线也没有小字号的地方，解析结果就是原文。

不做的事
--------
不猜。配不上对的原样保留。宁可留一处压平，也不要造出一个假公式。
"""
import collections

SUP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
SUB = str.maketrans("0123456789+-=()aeioxnmpst",
                    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒₓₙₘₚₛₜ")
RADICALS = ("√", "∛", "∜")
MAX_DEPTH = 8


# ---------------------------------------------------------------- 基础
def body_size(spans):
    c = collections.Counter(round(s.get("size", 0), 1) for s in spans
                            if s.get("ok") and s.get("size"))
    return c.most_common(1)[0][0] if c else 14.0


def _w(text, size):
    """粗估宽度：CJK 约一个字号，ASCII 约半个。没有精确字宽表，够用。"""
    return sum(size if ord(ch) > 0x2E80 else size * 0.5 for ch in text)


def _atoms(spans, bs):
    out = []
    for i, s in enumerate(spans):
        if not s.get("ok") or not s["text"].strip():
            continue
        z = s.get("size") or bs
        # x1 由 pdfplumber 逐字符量出，比按字号估算准得多；
        # 缺失时才退回估算（老数据兼容）。
        x1 = s.get("x1")
        if x1 is None:
            x1 = s["x"] + _w(s["text"], z)
        out.append({"i": i, "text": s["text"], "x0": s["x"], "x1": x1,
                    "y": s["y"], "yt": s.get("yt", s["y"] + z), "size": z})
    return out


def _wrap(t):
    """已整体带括号、或只有一个字符时不再套括号。"""
    t = t.strip()
    if len(t) <= 1:
        return t
    if t[0] == "(" and t[-1] == ")":
        depth = 0
        for k, ch in enumerate(t):
            depth += (ch == "(") - (ch == ")")
            if depth == 0 and k < len(t) - 1:
                break
        else:
            return t
    return "(" + t + ")"


def _near(a, r, bs, k=3.0):
    """原子是否贴着这条横线。

    分式的分子分母就在横线上下一两个字高之内；即使分子本身又是个分式，
    也不过再多一层。隔了一整行的东西（比如上下堆叠的另一个选项）
    绝不可能属于同一个分式 —— 不加这条限制，
    A 选项的式子会把 C 选项的式子吸成自己的分母。"""
    return abs(a["y"] - r["y"]) <= bs * k


def _xov(a, x0, x1, need=0.6):
    """
    原子与 [x0,x1] 的横向重叠是否占它自身宽度的大部分。

    不能用「完全落在区间内」：字宽是估算的，分子里稍宽一点的块就会被判出局，
    于是整条分式判定失败、退化成按 x 从左到右拼接 —— 分母 5 居中，
    正好被插进分子中间，变成 `2nmg5ω²RH`（分母凭空消失）。

    也不能用「中心落在区间内」：正文长句的中心可能恰好落进一条短横线的跨度，
    整句会被当成分子。

    重叠占比同时挡住这两种：长句重叠率极低，宽一点的分子重叠率仍接近 1。
    """
    w = max(1e-6, a["x1"] - a["x0"])
    ov = min(a["x1"], x1) - max(a["x0"], x0)
    return ov / w >= need


def _translatable(t, table):
    return t and all(ord(c) in table for c in t)


# ---------------------------------------------------------------- 递归解析
def _baseline(seq, bs):
    """本区主基线：正文字号的原子里出现最多的那个 y。"""
    c = collections.Counter(round(a["y"], 1) for a in seq if a["size"] >= bs * 0.86)
    if not c:
        c = collections.Counter(round(a["y"], 1) for a in seq)
    return c.most_common(1)[0][0]


def parse(atoms, rules, bs, depth=0):
    """
    把一个区域内的原子还原成**结构树**。

    产出树而不是直接拼字符串，是为了同一份结构能出两种形态：
      · to_text()   线性文本，给切分/检索/喂给解题模型用
      · to_mathml() MathML，给页面渲染 —— 分子在上、分母在下，和原卷一样

    节点：("t", 文本) ("row", [子节点]) ("frac", 分子, 分母)
          ("sqrt", 被开方式) ("sup", 指数) ("sub", 角标)

    算法是**单元式**的，不是一遍线性扫描：
    先把区域切成左右排列的「单元」（根号单元 / 分式单元 / 散原子），
    每个单元内部递归，最后按 x 从左到右拼起来。

    第一版只在「某条横线覆盖本区 50% 以上宽度」时才当分式处理，
    其余情况直接按 x 平铺 —— 一个选项里有多个并列分式时
    （`E_k1/E_k2 = r₂/r₁, T₁/T₂ = √(...)`），没有哪条线能覆盖 50%，
    于是分子分母被打散、等号和逗号挤到末尾，整条式子面目全非。
    """
    if not atoms:
        return ("row", [])
    if depth >= MAX_DEPTH:
        return ("row", [("t", a["text"]) for a in sorted(atoms, key=lambda a: a["x0"])])

    ax0 = min(a["x0"] for a in atoms)
    ax1 = max(a["x1"] for a in atoms)
    span_w = max(1.0, ax1 - ax0)

    # ---- 整区就是一个分式：横线几乎横贯全区，且上下都有内容 ----
    for r in sorted(rules, key=lambda r: -r["w"]):
        rx0, rx1 = r["x"], r["x"] + r["w"]
        if r["w"] < span_w * 0.75:
            break
        up = [a for a in atoms if a["y"] > r["y"] + 0.5 and _xov(a, rx0, rx1)
              and _near(a, r, bs)]
        dn = [a for a in atoms if a["y"] < r["y"] - 0.5 and _xov(a, rx0, rx1)
              and _near(a, r, bs)]
        if up and dn and len(up) + len(dn) == len(atoms):
            rest = [x for x in rules if x is not r]
            num = parse(up, [x for x in rest if x["y"] > r["y"]], bs, depth + 1)
            den = parse(dn, [x for x in rest if x["y"] < r["y"]], bs, depth + 1)
            if to_text(num).strip() and to_text(den).strip():
                return ("frac", num, den)

    # ---- 切单元 ----
    done, units = set(), []          # units: (x排序键, 节点)

    # ① 根号：√ + 它右邻的上横线（上方无内容）。最外层，优先切。
    for a in sorted(atoms, key=lambda a: a["x0"]):
        if a["text"].strip() not in RADICALS or a["i"] in done:
            continue
        ol = None
        for r in rules:
            if r["x"] < a["x1"] - 4 or r["x"] > a["x1"] + 8:
                continue
            if r["y"] <= a["y"]:
                continue
            if any(x["y"] > r["y"] and -10 <= x["x"] - a["x1"] <= 10 for x in rules):
                continue                 # 这个 √ 上方还有更高的线，那条才是上横线
            if ol is None or r["w"] > ol["w"]:
                ol = r
        if not ol:
            continue
        rx0, rx1 = ol["x"], ol["x"] + ol["w"]
        rad = [b for b in atoms if b["i"] != a["i"] and b["i"] not in done
               and b["y"] < ol["y"] and _xov(b, rx0, rx1) and _near(b, ol, bs, 3.5)]
        if not rad:
            continue
        sub = [x for x in rules if x is not ol and x["y"] < ol["y"]
               and x["x"] >= rx0 - 2 and x["x"] + x["w"] <= rx1 + 2]
        units.append((a["x0"], ("sqrt", parse(rad, sub, bs, depth + 1))))
        done.add(a["i"])
        done.update(b["i"] for b in rad)

    # ② 分式：剩下的横线，上下都有未消耗的内容
    for r in sorted(rules, key=lambda r: -r["w"]):
        rx0, rx1 = r["x"], r["x"] + r["w"]
        up = [a for a in atoms if a["i"] not in done
              and a["y"] > r["y"] + 0.5 and _xov(a, rx0, rx1) and _near(a, r, bs)]
        dn = [a for a in atoms if a["i"] not in done
              and a["y"] < r["y"] - 0.5 and _xov(a, rx0, rx1) and _near(a, r, bs)]
        if not up or not dn:
            continue
        inner = [x for x in rules
                 if x is not r and x["x"] >= rx0 - 2 and x["x"] + x["w"] <= rx1 + 2]
        num = parse(up, [x for x in inner if x["y"] > r["y"]], bs, depth + 1)
        den = parse(dn, [x for x in inner if x["y"] < r["y"]], bs, depth + 1)
        if not (to_text(num).strip() and to_text(den).strip()):
            continue
        units.append((rx0, ("frac", num, den)))
        done.update(a["i"] for a in up + dn)

    # ③ 剩下的散原子：上下标或普通字符
    loose = sorted((a for a in atoms if a["i"] not in done), key=lambda a: a["x0"])
    base = _baseline(loose or sorted(atoms, key=lambda a: a["x0"]), bs)
    k = 0
    while k < len(loose):
        a = loose[k]
        if a["size"] < bs * 0.86 and abs(a["y"] - base) > a["size"] * 0.12:
            up = a["y"] > base
            grp = [a]
            j = k + 1
            while j < len(loose):
                b = loose[j]
                if (b["size"] < bs * 0.86 and (b["y"] > base) == up
                        and b["x0"] - grp[-1]["x1"] < bs * 0.5):
                    grp.append(b)
                    j += 1
                else:
                    break
            inner = parse(grp, [], bs, depth + 1)
            if up and to_text(inner).strip() in ("∘", "◦", "º"):
                units.append((a["x0"], ("t", "°")))
            else:
                units.append((a["x0"], ("sup" if up else "sub", inner)))
            k = j
            continue
        units.append((a["x0"], ("t", a["text"])))
        k += 1

    units.sort(key=lambda u: u[0])
    return ("row", [n for _, n in units])


# ---------------------------------------------------------------- 序列化
def to_text(node):
    """线性文本：给切分、检索、以及后续喂给解题模型用。"""
    k = node[0]
    if k == "t":
        return node[1]
    if k == "row":
        return "".join(to_text(c) for c in node[1])
    if k == "frac":
        return _wrap(to_text(node[1])) + "/" + _wrap(to_text(node[2]))
    if k == "sqrt":
        return "\u221a" + _wrap(to_text(node[1]))
    inner = to_text(node[1])
    table = SUP if k == "sup" else SUB
    if _translatable(inner, table):
        return inner.translate(table)
    return ("^" if k == "sup" else "_") + _wrap(inner)


_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def _esc(t):
    return "".join(_ESC.get(c, c) for c in t)


def _tokens(t):
    """把一段文本切成 MathML 记号：数字 <mn>、字母 <mi>、其余 <mo>。"""
    out, buf, kind = [], "", None

    def flush():
        nonlocal buf, kind
        if buf:
            out.append("<m%s>%s</m%s>" % (kind, _esc(buf), kind))
            buf = ""

    for ch in t:
        if ch.isdigit() or ch == ".":
            k = "n"
        elif ch.isalpha() or ord(ch) > 0x2E80 or ch in "\u03b1\u03b2\u03b3\u03b8\u03bb\u03bc\u03c0\u03c1\u03c3\u03c9\u03a9\u0394":
            k = "i"
        elif ch.isspace():
            flush()
            continue
        else:
            k = "o"
        if k != kind:
            flush()
            kind = k
        buf += ch
    flush()
    return "".join(out)


def to_mathml(node):
    """
    MathML：分子在上、分母在下，和原卷长得一样。
    现代浏览器（Chrome 109+/Safari/Firefox）原生支持，不需要引任何库。
    """
    return "<math>" + _ml(node) + "</math>"


def _ml(node):
    k = node[0]
    if k == "t":
        return _tokens(node[1])
    if k == "frac":
        return "<mfrac><mrow>%s</mrow><mrow>%s</mrow></mfrac>" % (_ml(node[1]), _ml(node[2]))
    if k == "sqrt":
        return "<msqrt><mrow>%s</mrow></msqrt>" % _ml(node[1])
    if k in ("sup", "sub"):
        # 上下标必须依附于一个基元。这里单独出现时用空基元兜底，
        # 正常情况会在 row 里和左邻的基元配对。
        tag = "msup" if k == "sup" else "msub"
        return "<%s><mrow></mrow><mrow>%s</mrow></%s>" % (tag, _ml(node[1]), tag)
    # row：把 sup/sub 与它左边的基元配对成 msup/msub
    parts, kids = [], list(node[1])
    i = 0
    while i < len(kids):
        c = kids[i]
        if c[0] in ("sup", "sub") and parts:
            tag = "msup" if c[0] == "sup" else "msub"
            parts[-1] = "<%s><mrow>%s</mrow><mrow>%s</mrow></%s>" % (
                tag, parts[-1], _ml(c[1]), tag)
        else:
            parts.append(_ml(c))
        i += 1
    return "".join(parts)


def classify_rules(atoms, rules, bs):
    """
    把横线分成「根号上横线」和「分数线」两类，返回 (上横线→√ 的映射)。

    这一步必须是确定性的，不能靠「上方有没有内容」的窗口判断：
    上下堆叠的两个选项挨得很近时（实测 A 的分母离 C 的上横线只有 9pt），
    窗口一定会串味，于是 C 的上横线把 A 的分母当成了自己的分子，
    两个选项被并成一个假分式（A 吞掉 C，C、D 变空）。

    确定的判据是：**根号上横线的左端紧挨着一个 √，
    而且是这个 √ 上方最高的那条线**（更低的那条是它内部的分数线）。
    """
    overline = {}
    for a in atoms:
        if a["text"].strip() not in RADICALS:
            continue
        cand = [r for r in rules
                if -10 <= r["x"] - a["x1"] <= 10 and 0 < r["y"] - a["y"] <= bs * 4.5]
        if cand:
            top = max(cand, key=lambda r: r["y"])
            overline[id(top)] = a
    return overline


# ---------------------------------------------------------------- 区域划分
def _regions(atoms, rules, bs, overline):
    """
    把页面切成若干「公式区域」：靠横线连通的原子聚成一团。

    只对这些区域跑递归解析，正文完全不碰——这样解析器再激进也改不坏散文。
    """
    seeds = []
    for r in rules:
        rx0, rx1 = r["x"], r["x"] + r["w"]
        win = bs * 1.6
        is_over = id(r) in overline
        above = [] if is_over else [a for a in atoms if _xov(a, rx0, rx1, need=0.55)
                                    and 0.5 < a["y"] - r["y"] <= win]
        below = [a for a in atoms if _xov(a, rx0, rx1, need=0.55)
                 and 0.5 < r["y"] - a["y"] <= win]
        # 横线的归属内容按**类型**定，不能一律上下都取：
        #   上下都有 → 分数线，两侧都属于它
        #   只有下方 → 根号上横线（或上划线），只有下方属于它
        # 不区分的话，下一行选项的上横线会向上吃到上一行选项的分母，
        # 两个选项的区域连通、合并成一个假分式
        # （实测山东卷第8题的 A 把 C 吸成了自己的分母，C、D 直接变空）。
        near = above + below
        if not near:
            continue
        # 根号的 √ 字形在上横线的**左边**，且可能远在下方（字形不拉伸时，
        # 它的顶端只到分母一带）。不拉进来的话，还原出的 √r/g 会丢括号。
        if is_over:
            near.append(overline[id(r)])
        if len(near) >= 2:
            seeds.append({"ids": {a["i"] for a in near}, "rules": [r]})

    merged = True
    while merged:                       # 嵌套分式会产生多条相交的横线，合并之
        merged = False
        for i in range(len(seeds)):
            for j in range(i + 1, len(seeds)):
                if seeds[i]["ids"] & seeds[j]["ids"]:
                    seeds[i]["ids"] |= seeds[j]["ids"]
                    seeds[i]["rules"] += seeds[j]["rules"]
                    del seeds[j]
                    merged = True
                    break
            if merged:
                break

    # 把紧邻右侧的上下标拉进来：指数常常跟在括号或分式右边
    byid = {a["i"]: a for a in atoms}
    for s in seeds:
        for _ in range(3):
            x1 = max(byid[i]["x1"] for i in s["ids"])
            # 必须落在本区已有原子的**同一基线**上，不能只看整体纵向范围：
            # 上下堆叠的两个选项 x 范围完全重合，只按范围拉的话，
            # 下面那个选项的下标会被上面那个吸走，两个区域连通、并成假分式。
            add = {a["i"] for a in atoms
                   if a["i"] not in s["ids"] and a["size"] < bs * 0.86
                   and -1.0 <= a["x0"] - x1 <= bs * 0.6
                   and any(abs(a["y"] - byid[i]["y"]) <= bs * 0.9 for i in s["ids"])}
            if not add:
                break
            s["ids"] |= add
    return seeds


# ---------------------------------------------------------------- 页面级
def _outside_scripts(outside, bs, stat):
    """
    区域之外的孤立上下标：`v1` → `v₁`、`r2` → `r²`。

    必须先按行聚类再按 x 排序——上标的 y 比基线高，
    纯按 y 排会把它排到基线**前面**，往左找基线必然落空。
    """
    idx = sorted(outside, key=lambda a: -a["y"])
    lines, cur = [], []
    for a in idx:
        if cur and abs(cur[0]["y"] - a["y"]) > bs * 0.5:
            lines.append(cur)
            cur = []
        cur.append(a)
    if cur:
        lines.append(cur)

    res = {}
    for ln in lines:
        row = sorted(ln, key=lambda a: a["x0"])
        for k, a in enumerate(row):
            if a["size"] >= bs * 0.86 or not a["text"].strip():
                continue
            base = next((b for b in row[max(0, k - 3):k][::-1]
                         if b["size"] >= bs * 0.9), None)
            if base is None:
                continue
            gap = a["x0"] - base["x1"]
            if gap > bs * 0.6 or gap < -bs * 0.9:
                continue
            dy, t = a["y"] - base["y"], a["text"].strip()
            if dy > a["size"] * 0.12:
                res[a["i"]] = (t.translate(SUP) if _translatable(t, SUP)
                               else "^" + _wrap(t))
                stat["script"] += 1
            elif dy < -a["size"] * 0.12:
                res[a["i"]] = (t.translate(SUB) if _translatable(t, SUB)
                               else "_" + _wrap(t))
                stat["script"] += 1
    return res


def _has_2d(node):
    """只有真含二维结构（分式/根号/上下标）才值得出 MathML；纯文本不必。"""
    k = node[0]
    if k in ("frac", "sqrt", "sup", "sub"):
        return True
    if k == "row":
        return any(_has_2d(c) for c in node[1])
    return False


def fix_page(spans, rules, bs=None):
    live = [dict(s) for s in spans]
    bs = bs or body_size(live)
    rules = list(rules or [])
    atoms = _atoms(live, bs)
    stat = {"frac": 0, "script": 0, "radical": 0, "region": 0}
    if not atoms:
        return live, stat
    byid = {a["i"]: a for a in atoms}

    replace, consumed = {}, set()
    overline = classify_rules(atoms, rules, bs)
    for s in _regions(atoms, rules, bs, overline):
        grp = sorted((byid[i] for i in s["ids"]), key=lambda a: a["x0"])
        gx0, gx1 = min(a["x0"] for a in grp) - 2, max(a["x1"] for a in grp) + 2
        gy0, gy1 = min(a["y"] for a in grp) - bs, max(a["y"] for a in grp) + bs
        rs = [r for r in rules
              if r["x"] >= gx0 - 2 and r["x"] + r["w"] <= gx1 + 2 and gy0 <= r["y"] <= gy1]
        tree = parse(grp, rs, bs)
        txt = to_text(tree)
        if not txt.strip():
            continue
        has2d = _has_2d(tree)
        replace[min(a["i"] for a in grp)] = (
            txt, to_mathml(tree) if has2d else None,
            {"x": min(a["x0"] for a in grp), "x1": max(a["x1"] for a in grp),
             # 纵向取整组中位，近似数学轴，和周围正文基线大致对齐
             "y": sorted(a["y"] for a in grp)[len(grp) // 2],
             "yt": max(a["y"] + a["size"] for a in grp)})
        consumed.update(a["i"] for a in grp)
        stat["region"] += 1
        stat["frac"] += txt.count("/")
        stat["radical"] += sum(txt.count(ch) for ch in RADICALS)

    for i, t in _outside_scripts([a for a in atoms if a["i"] not in consumed],
                                 bs, stat).items():
        live[i]["text"] = t

    out = []
    for i, s in enumerate(live):
        if i in replace:
            txt, ml, geo = replace[i]
            blk = {"text": txt, "x": geo["x"], "x1": geo["x1"],
                   "y": geo["y"], "yt": geo["yt"],
                   "ok": True, "size": bs, "math": "expr"}
            if ml:
                blk["mathml"] = ml
            out.append(blk)
        elif i not in consumed:
            out.append(s)
    return out, stat


def fix_doc(doc):
    tot = {"frac": 0, "script": 0, "radical": 0, "region": 0}
    for p in doc["pages"]:
        fixed, st = fix_page(p["spans"], p.get("rules"))
        p["spans"] = fixed
        for k in tot:
            tot[k] += st[k]
    return tot
