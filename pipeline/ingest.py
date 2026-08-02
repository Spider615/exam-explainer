#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest.py —— 阶段① PDF 摄入

    python ingest.py <试卷.pdf> -o work/<name>

产出：
    work/<name>/doc.json          结构化文本 + 图片位置（后续阶段的唯一输入）
    work/<name>/img/pNN_kk.png    导出的内嵌插图（原分辨率线稿）
    work/<name>/page/pNN.png      整页渲染图（供人/模型核对版面）

设计要点
--------
1. **选择性 Unicode 规范化**。这类试卷 PDF 的文字层常把汉字编成"康熙部首"
   （U+2F00–U+2FDF）或"CJK 部首补充"（U+2E80–U+2EFF），肉眼看不出区别，
   但 '⾼考' != '高考'，任何关键词规则都会静默失效。
   这里只折叠这类兼容字形和兼容汉字，**保留全角标点**——全角逗号是正文
   排版的一部分，NFKC 会把它压成半角，破坏显示。
2. **保留坐标**。文本块和图片都带 (x, y, w, h)，切分阶段要靠纵向位置
   把插图归属到题目，光有纯文本做不到。
3. 本阶段**不做任何语义判断**，纯代码、可复现、无模型调用。
"""
import argparse, json, os, re, subprocess, sys, unicodedata

try:
    import pypdf
except ImportError:
    sys.exit("需要 pypdf：pip install pypdf")


# ---------------------------------------------------------------- 规范化
def _fold_char(ch):
    """把兼容字形折叠成标准汉字；全角标点原样保留。"""
    o = ord(ch)
    # 康熙部首 / CJK部首补充 / CJK兼容汉字 —— 这些必须折叠
    if 0x2E80 <= o <= 0x2EF3 or 0x2F00 <= o <= 0x2FD5 or \
       0xF900 <= o <= 0xFAFF or 0x3000 == o:
        n = unicodedata.normalize("NFKC", ch)
        return n if n else ch
    # 文字层里夹着 \x00 之类的控制符，会污染后续正则
    if o < 0x20 and ch not in "\n\t":
        return ""
    return ch


def normalize(text):
    return "".join(_fold_char(c) for c in text)


def normalization_report(raw):
    changed = {}
    for c in set(raw):
        f = _fold_char(c)
        if f != c:
            changed[c] = f
    return changed


# ---------------------------------------------------------------- 文本 + 坐标
def extract_with_plumber(pdf_path):
    """
    用 pdfplumber 逐**字符**取文本与几何。

    为什么不用 pypdf 的 visitor：它给的是文本块，而块的边界由 PDF 生成器决定，
    经常横跨分数线。实测山东卷把 `nmg·ω²·RH` 和分母 `5` 合并成了一个块
    `'nmg5ω²RH'` —— 块内没有逐字坐标，分子分母再也分不开。
    要还原公式，必须拿到每个字符自己的 x0/x1/基线/字号。

    字符再按「同基线 + 同字号 + 横向连续」聚成 run。
    这样聚出来的 run 天然不会跨越分数线（分子分母基线不同），
    正好是公式解析需要的原子。

    横线也一并由 pdfplumber 的 rects/lines 提供，比自己走内容流可靠。
    """
    import pdfplumber

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            H = float(page.height)
            chars = [c for c in page.chars if c.get("text") and c["text"].strip()]
            # 阅读顺序：先按行（基线聚类），行内按 x
            chars.sort(key=lambda c: (-round(float(c["y0"]), 1), float(c["x0"])))

            # 先按基线+字号+横向连续聚成 run。
            # 关键：run 不能横跨另一条基线上的字符。
            # `nmgω²RH` 里的上标 2 在排序中排在 nmgω 之前（它基线更高），
            # 若不挡住，nmgω 会直接和 RH 连成一个 run，上标被挤到末尾，
            # 还原出 `nmgωRH²` —— 平方跑到了错误的符号上。
            marks = sorted((float(c["x0"]), float(c["x1"]), float(c["y0"]))
                           for c in chars)

            def blocked(y, xa, xb):
                if xb - xa < 0.3:
                    return False
                for x0m, x1m, ym in marks:
                    if x0m >= xb:
                        break
                    if x1m > xa and abs(ym - y) >= 0.8:
                        return True
                return False

            runs, cur = [], None
            for c in chars:
                t = normalize(c["text"])
                if not t:
                    continue
                y0, x0, x1 = float(c["y0"]), float(c["x0"]), float(c["x1"])
                y1c = float(c["y1"])
                z = round(float(c.get("size") or 0), 2)
                if (cur and abs(cur["y"] - y0) < 0.8 and abs(cur["size"] - z) < 0.35
                        and -0.6 <= x0 - cur["x1"] <= max(1.2, z * 0.45)
                        and not blocked(y0, cur["x1"], x0)):
                    cur["text"] += t
                    cur["x1"] = x1
                    cur["yt"] = max(cur["yt"], y1c)
                else:
                    cur = {"text": t, "x": x0, "x1": x1, "y": y0, "yt": y1c,
                           "size": z, "ok": True}
                    runs.append(cur)

            rules, vrules = [], []
            for r in list(page.rects) + list(page.lines):
                x0, x1 = float(r["x0"]), float(r["x1"])
                y0, y1 = float(r["y0"]), float(r["y1"])
                if abs(y1 - y0) <= 2.5 and (x1 - x0) >= 4:
                    rules.append({"x": round(x0, 2), "y": round((y0 + y1) / 2, 2),
                                  "w": round(x1 - x0, 2), "t": round(abs(y1 - y0), 2)})
                elif abs(x1 - x0) <= 2.5 and (y1 - y0) >= 8:
                    # 竖线只用于识别表格 —— 公式里不会有竖线
                    vrules.append({"x": round((x0 + x1) / 2, 2), "y0": round(y0, 2),
                                   "y1": round(y1, 2)})

            # 这里**不排阅读顺序**：跨行的公式还没合并，
            # 此时排序只能在「分子行/分母行」之间二选一，必然把并列的选项串味。
            # 正确的次序是「先还原结构，再定顺序」——见 main() 里的调用点。
            for r in runs:
                r["x"] = round(r["x"], 2)
                r["x1"] = round(r["x1"], 2)
                r["y"] = round(r["y"], 2)
                r["yt"] = round(r.get("yt", r["y"]), 2)

            pages.append({
                "page": pno,
                "width": round(float(page.width), 2),
                "height": round(H, 2),
                "text": "".join(r["text"] for r in runs),
                "spans": runs,
                "rules": rules,
                "vrules": vrules,
                "tables": find_tables(vrules, rules),
            })
    return pages


def _reading_order(runs, rules):
    """
    run 级阅读顺序：先聚成「行」，行内按 x 排。

    不能在字符级按基线全局排序 —— 一排并列的选项里，
    四个分子的基线相同、四个分母的基线也相同，
    全局排序会把它们排成「所有分子…所有分母…」，四个选项彻底串味
    （实测出现过 `ππ30120ππ30120√√` 这种东西）。

    行的聚类先用紧容差，再**用分数线把上下两行粘起来**：
    一条横线若同时压着上下两行、且横向有交集，那这两行属于同一个公式，
    必须算作一行。这比放宽容差安全 —— 放宽容差会把相邻的正文行也并进来。
    """
    if not runs:
        return runs
    sizes = [r["size"] for r in runs if r["size"]]
    bs = max(sizes, key=sizes.count) if sizes else 10.5

    # 容差要能容下「相对分式居中而抬高的前缀」（如 30π 比 A. 高 6pt），
    # 但不能大到并进相邻正文行（行距约 1.7·字号）。同时限制整行高度防止串行。
    order = sorted(range(len(runs)), key=lambda i: (-runs[i]["y"], runs[i]["x"]))
    rows, cur = [], []
    for i in order:
        if cur:
            ys = [runs[j]["y"] for j in cur] + [runs[i]["y"]]
            if (abs(runs[cur[-1]]["y"] - runs[i]["y"]) > bs * 0.9
                    or max(ys) - min(ys) > bs * 1.15):
                rows.append(cur)
                cur = []
        cur.append(i)
    if cur:
        rows.append(cur)

    def covers(i, r, need=0.6):
        """run 与横线的横向重叠是否占它自身宽度的大部分。"""
        w = max(1e-6, runs[i]["x1"] - runs[i]["x"])
        ov = min(runs[i]["x1"], r["x"] + r["w"]) - max(runs[i]["x"], r["x"])
        return ov / w >= need

    merged = True
    while merged:
        merged = False
        for k in range(len(rows) - 1):
            a, b = rows[k], rows[k + 1]
            ya = min(runs[i]["y"] for i in a)
            yb = max(runs[i]["y"] for i in b)
            # 硬约束：只有挨得足够近的两行才可能属于同一个公式。
            # 不加这条的话，「中间有横线」会把相距 70pt 的两行也粘起来 ——
            # 实测把选项行和下一题的「单选题」标记行粘成一行，
            # 按 x 一排，标记就插进了选项 A 和 B 中间，把整道题的选项劈成两半。
            if ya - yb > bs * 2.6:
                continue
            # 只有「上下都压着实质内容」的横线才是分数线，才该粘。
            # 光看横线夹在两行之间不够：题干末行与选项行之间恰好有根号的上横线，
            # 那条线上方是正文长句（重叠占比极低），不该把两行并在一起。
            def linked(r):
                if not (yb - 1 <= r["y"] <= ya + 1):
                    return False
                below = any(covers(i, r) for i in b)
                if not below:
                    return False
                # ① 分数线：上下都压着实质内容
                if any(covers(i, r) for i in a):
                    return True
                # ② 根号上横线：上方没有内容，但左边紧挨着一个 √，
                #    被开方式在下一行。不认这一条的话，`30π√` 会和 `r/g` 分家。
                return any(runs[i]["text"].strip() in ("√", "∛", "∜")
                           and -2 <= r["x"] - runs[i]["x1"] <= 8 for i in a)

            # ③ 高字形跨行：大号根号的下沿会掉到基线以下很多，
            #    单看下沿会被分到另一行。它纵向盖住了哪几行，那几行就是一体的。
            tall = any(runs[i]["yt"] >= ya - 1 and runs[i]["y"] <= yb + 1
                       for i in a + b
                       if runs[i]["yt"] - runs[i]["y"] > bs * 1.4)
            glue = tall or any(linked(r) for r in rules)
            if glue:
                rows[k] = a + b
                del rows[k + 1]
                merged = True
                break

    # ── 分栏续行：多栏布局里换行的那一栏，续行属于本栏而不是"下一整行" ──
    # 选项常排成 4 栏，某一栏文字长了会换行（如 `A. B₂的方向向` / 次行 `上`）。
    # 按「整行 → 下一整行」读，续行会被甩到最后一栏后面，
    # 变成 A、B 都是 `B₂的方向向`，而 D 变成 `v₂=3m/s 上 下`。
    def order_col(c):
        """栏内次序：先按行聚类（容差同上），再行内按 x。
        直接按 (y, x) 排会拆散同一行 —— 下标的 y 比基线低，
        会被排到行尾，出现 `B 的方向向₂` 这种。"""
        cs = sorted(c, key=lambda i: -runs[i]["y"])
        out2, grp = [], []
        for i in cs:
            if grp and abs(runs[grp[0]]["y"] - runs[i]["y"]) > bs * 0.9:
                out2 += sorted(grp, key=lambda i: runs[i]["x"])
                grp = []
            grp.append(i)
        if grp:
            out2 += sorted(grp, key=lambda i: runs[i]["x"])
        return out2

    def columns_of(row):
        rs = sorted(row, key=lambda i: runs[i]["x"])
        cols, cur2 = [], [rs[0]]
        for i in rs[1:]:
            if runs[i]["x"] - runs[cur2[-1]]["x1"] > bs * 2.5:
                cols.append(cur2)
                cur2 = []
            cur2.append(i)
        cols.append(cur2)
        return cols

    col_rows = set()          # 只有「续行归并过」的行才按栏读
    k = 0
    while k < len(rows) - 1:
        cols = columns_of(rows[k])
        if len(cols) >= 2:
            bands = [(min(runs[i]["x"] for i in c) - bs,
                      max(runs[i]["x1"] for i in c) + bs) for c in cols]
            nxt = rows[k + 1]
            gap = (min(runs[i]["y"] for i in rows[k])
                   - max(runs[i]["y"] for i in nxt))
            fits = all(any(b0 <= runs[i]["x"] and runs[i]["x1"] <= b1
                           for b0, b1 in bands) for i in nxt)
            # 关键判据：**续行不会以选项字母开头**。
            # 选项常排成 2×2 网格（A B 一行、C D 一行），那是新的一行选项，
            # 不是续行；按栏读会得到 A、C、B、D，选项全乱。
            starts_option = any(re.match(r"[ABCD]\s*[.．、]", runs[i]["text"].lstrip())
                                for i in nxt)
            if (fits and not starts_option
                    and 0 < gap <= bs * 1.8 and len(nxt) < len(rows[k])):
                for i in nxt:                       # 续行按 x 归到所属栏
                    for c, (b0, b1) in zip(cols, bands):
                        if b0 <= runs[i]["x"] <= b1:
                            c.append(i)
                            break
                rows[k] = [i for c in cols for i in order_col(c)]
                col_rows.add(id(rows[k]))
                del rows[k + 1]
                continue
        k += 1

    # 粘行会把不相邻的行并到一起，行序不再保证自上而下 ——
    # 实测出现过「单选题」标记插进选项 A 和 B 之间，把一道题的选项劈成两半。
    # 这里按行的纵向位置重排，兜住这种情况。
    rows.sort(key=lambda row: -max(runs[i]["y"] for i in row))
    out = []
    for row in rows:
        # 只有续行归并过的行才按栏读。
        # 不加这个限制的话，任何多栏的行都会被按列读 —— 而选项通常是
        # **行主序**（A B 一行、C D 一行），按列读会得到 A、C、B、D，
        # 实测山东卷第10题因此四个选项全部错位。
        if id(row) in col_rows:
            out.extend(runs[i] for c in columns_of(row) for i in order_col(c))
        else:
            out.extend(runs[i] for i in sorted(row, key=lambda i: runs[i]["x"]))
    return out


def find_tables(vrules, rules):
    """
    框出表格区域。

    判据：**≥3 条竖线共享同一纵向区间**。公式里不会出现竖线，
    所以这一条几乎不会误判；而表格无论是全框线还是三线表，
    只要有列分隔就会留下竖线。

    返回每个表的外框 (x0, y0, x1, y1)。表格里的文字会被切分阶段
    从题干中摘出去 —— 二维的表塞进一维的题干只会变成乱码
    （实测江苏卷第11题：`ΔWh/E_f/(/10((1010^(−2)...`）。
    """
    if len(vrules) < 3:
        return []
    vs = sorted(vrules, key=lambda v: -v["y1"])
    groups, cur = [], [vs[0]]
    for v in vs[1:]:
        if any(min(v["y1"], u["y1"]) - max(v["y0"], u["y0"]) > 4 for u in cur):
            cur.append(v)
        else:
            groups.append(cur)
            cur = [v]
    groups.append(cur)

    out = []
    for g in groups:
        if len(g) < 3:
            continue
        y0 = min(v["y0"] for v in g)
        y1 = max(v["y1"] for v in g)
        x0 = min(v["x"] for v in g)
        x1 = max(v["x"] for v in g)
        # 把横跨该区间的横线也算进去，外框才完整
        hs = [r for r in rules if y0 - 3 <= r["y"] <= y1 + 3
              and r["x"] + r["w"] > x0 - 3 and r["x"] < x1 + 3]
        if hs:
            x0 = min([x0] + [r["x"] for r in hs])
            x1 = max([x1] + [r["x"] + r["w"] for r in hs])
        out.append({"x0": x0 - 2, "y0": y0 - 2, "x1": x1 + 2, "y1": y1 + 2})

    # 相邻的表格「行」要合并成整张表：每一行有自己的一组短竖线，
    # 上下两行只在边界处相接、并不重叠，所以按重叠分组会把一张表拆成好几行。
    out.sort(key=lambda t: -t["y1"])
    merged = True
    while merged:
        merged = False
        for i in range(len(out) - 1):
            a, b = out[i], out[i + 1]
            ov = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
            wide = min(a["x1"] - a["x0"], b["x1"] - b["x0"])
            if ov > wide * 0.8 and a["y0"] - b["y1"] < 6:
                a["y0"] = min(a["y0"], b["y0"])
                a["x0"] = min(a["x0"], b["x0"])
                a["x1"] = max(a["x1"], b["x1"])
                del out[i + 1]
                merged = True
                break
    return [{k: round(v, 2) for k, v in t.items()} for t in out]


def _insert_separators(runs):
    """
    换行或有明显横向间隙的地方补一个空格。

    pypdf 的 extract_text 会自动补空白，pdfplumber 不会 —— 直接首尾相接的话，
    「题型词」锚点探测器（要求标记前有空白）会大面积失效：
    实测 2025 年那批卷子从 15/20 题掉到 9/12 题。
    """
    prev = None
    for r in runs:
        if prev is not None:
            newline = abs(prev["y"] - r["y"]) > (r["size"] or 10.5) * 0.6
            gap = r["x"] - prev["x1"]
            if newline or gap > (r["size"] or 10.5) * 0.3:
                r["text"] = " " + r["text"]
        prev = r


# ---------------------------------------------------------------- 图片 + 坐标
def extract_page_images(page, pno, outdir):
    """
    导出内嵌图片并记录位置。

    位置来自内容流里的 `cm ... Do`：图片 XObject 被绘制在单位方阵上，
    所以当前变换矩阵 (a,b,c,d,e,f) 直接给出 (宽=a, 高=d, 左下=(e,f))。
    """
    from pypdf.generic import ContentStream, NameObject

    recs = []
    try:
        res = page.get("/Resources", {})
        xobjs = res.get("/XObject", {})
        xobjs = xobjs.get_object() if hasattr(xobjs, "get_object") else xobjs
    except Exception:
        xobjs = {}

    # 走一遍内容流，跟踪 CTM 栈，取每次 Do 时的矩阵
    placed = {}
    try:
        cs = ContentStream(page.get_contents(), page.pdf)
        ctm = [1, 0, 0, 1, 0, 0]
        stack = []
        for operands, op in cs.operations:
            if op == b"q":
                stack.append(list(ctm))
            elif op == b"Q":
                ctm = stack.pop() if stack else [1, 0, 0, 1, 0, 0]
            elif op == b"cm":
                m = [float(x) for x in operands]
                a, b, c, d, e, f = m
                A, B, C, D, E, F = ctm
                ctm = [a * A + b * C, a * B + b * D,
                       c * A + d * C, c * B + d * D,
                       e * A + f * C + E, e * B + f * D + F]
            elif op == b"Do":
                nm = str(operands[0])
                placed.setdefault(nm, []).append(list(ctm))
    except Exception as e:
        print("   [warn] 第%d页内容流解析失败，图片将无坐标：%s" % (pno, e))

    idx = 0
    for img in page.images:  # noqa: 见下方 extract_rules，两者共用同一次内容流解析
        idx += 1
        name = "p%02d_%02d.png" % (pno, idx)
        path = os.path.join(outdir, name)
        try:
            with open(path, "wb") as f:
                f.write(img.data)
        except Exception as e:
            print("   [warn] 导出 %s 失败：%s" % (name, e))
            continue
        key = "/" + img.name.split(".")[0] if not img.name.startswith("/") else img.name
        boxes = placed.get(key) or placed.get(img.name) or []
        box = boxes[0] if boxes else None
        recs.append({
            "file": "img/" + name,
            "xobject": img.name,
            "x": round(box[4], 2) if box else None,
            "y": round(box[5], 2) if box else None,
            "w": round(abs(box[0]), 2) if box else None,
            "h": round(abs(box[3]), 2) if box else None,
            "bytes": len(img.data),
        })
    return recs


# ---------------------------------------------------------------- 横线（分数线）
def extract_rules(page):
    """
    抽出页面上的**水平细线**。

    为什么需要：分式在 PDF 里不是一个字符，而是「分子在上、分母在下、
    中间画一条线」。纯文本抽取会把上下两行首尾相接，
    `Mm/r²` 就变成了 `Mmr2`、`√(r/g)` 变成 `√rg` —— 信息没丢，丢的是二维结构。
    有了这些线的坐标，就能把分子分母重新配对。

    两种画法都要认：
      · `x y w h re` + 填充  —— 细长矩形
      · `m … l` + 描边       —— 直线段
    """
    from pypdf.generic import ContentStream

    rules = []
    try:
        cs = ContentStream(page.get_contents(), page.pdf)
    except Exception:
        return rules

    ctm = [1, 0, 0, 1, 0, 0]
    stack, cur = [], []

    def apply(x, y):
        a, b, c, d, e, f = ctm
        return (a * x + c * y + e, b * x + d * y + f)

    def add(x0, y0, x1, y1, thick):
        if abs(y1 - y0) > 2.0:            # 不是水平线
            return
        if abs(x1 - x0) < 4.0:            # 太短，不像分数线
            return
        rules.append({"x": round(min(x0, x1), 2), "y": round((y0 + y1) / 2, 2),
                      "w": round(abs(x1 - x0), 2), "t": round(thick, 2)})

    for operands, op in cs.operations:
        try:
            if op == b"q":
                stack.append(list(ctm))
            elif op == b"Q":
                ctm = stack.pop() if stack else [1, 0, 0, 1, 0, 0]
            elif op == b"cm":
                a, b, c, d, e, f = [float(x) for x in operands]
                A, B, C, D, E, F = ctm
                ctm = [a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D,
                       e * A + f * C + E, e * B + f * D + F]
            elif op == b"re":
                x, y, w, h = [float(v) for v in operands]
                if abs(h) <= 2.5 and abs(w) >= 4:          # 细长矩形 = 线
                    p0 = apply(x, y)
                    p1 = apply(x + w, y)
                    add(p0[0], p0[1], p1[0], p1[1], abs(h))
            elif op == b"m":
                cur = [apply(float(operands[0]), float(operands[1]))]
            elif op == b"l":
                cur.append(apply(float(operands[0]), float(operands[1])))
            elif op in (b"S", b"s", b"f", b"F", b"f*", b"B", b"b"):
                if len(cur) >= 2:
                    for i in range(len(cur) - 1):
                        add(cur[i][0], cur[i][1], cur[i + 1][0], cur[i + 1][1], 0.6)
                cur = []
        except Exception:
            continue
    return rules


# ---------------------------------------------------------------- 整页渲染
def render_pages(pdf, outdir, dpi=110):
    exe = None
    for cand in ("pdftoppm", "/opt/homebrew/bin/pdftoppm", "/usr/local/bin/pdftoppm"):
        if subprocess.run(["which", cand], capture_output=True).returncode == 0 or os.path.exists(cand):
            exe = cand
            break
    if not exe:
        print("   [warn] 找不到 pdftoppm（brew install poppler），跳过整页渲染")
        return 0
    subprocess.run([exe, "-r", str(dpi), "-png", pdf, os.path.join(outdir, "p")],
                   capture_output=True)
    return len([f for f in os.listdir(outdir) if f.endswith(".png")])


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--dpi", type=int, default=110)
    a = ap.parse_args()

    imgdir = os.path.join(a.out, "img")
    pagedir = os.path.join(a.out, "page")
    for d in (a.out, imgdir, pagedir):
        os.makedirs(d, exist_ok=True)

    reader = pypdf.PdfReader(a.pdf)
    print("── 摄入 %s（%d 页）" % (os.path.basename(a.pdf), len(reader.pages)))

    raw_all = "".join(p.extract_text() or "" for p in reader.pages)
    changed = normalization_report(raw_all)
    if changed:
        sample = ", ".join("%s→%s" % (k, v) for k, v in list(changed.items())[:8])
        print("   规范化：折叠 %d 种兼容字形（%s ...）" % (len(changed), sample))
    else:
        print("   规范化：文字层干净，无兼容字形")

    pages = extract_with_plumber(a.pdf)
    total_img = 0
    for i, page in enumerate(reader.pages, 1):
        imgs = extract_page_images(page, i, imgdir)
        total_img += len(imgs)
        pages[i - 1]["images"] = imgs
    print("   文本：%d 页，共 %d 字符，%d 个文本块"
          % (len(pages), sum(len(p["text"]) for p in pages),
             sum(len(p["spans"]) for p in pages)))
    located = sum(1 for p in pages for im in p["images"] if im["x"] is not None)
    print("   插图：%d 张（%d 张取到坐标）" % (total_img, located))
    nrule = sum(len(p["rules"]) for p in pages)
    print("   水平细线：%d 条（分数线还原用）" % nrule)

    # 公式还原：把被压平的分式与上下标按坐标重新配对
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mathfix
    st = mathfix.fix_doc({"pages": pages})
    print("   公式还原：%d 处分式，%d 处上下标" % (st["frac"], st["script"]))

    # 结构还原完毕，跨行的公式已经是单个块了，现在才排阅读顺序
    for pg in pages:
        pg["spans"] = _reading_order(pg["spans"], pg["rules"])
        _insert_separators(pg["spans"])
        pg["text"] = "".join(x["text"] for x in pg["spans"])

    n = render_pages(a.pdf, pagedir, a.dpi)
    print("   整页渲染：%d 张 @%d dpi" % (n, a.dpi))

    doc = {
        "source": os.path.abspath(a.pdf),
        "n_pages": len(pages),
        "normalization": {k: v for k, v in changed.items()},
        "pages": pages,
    }
    dp = os.path.join(a.out, "doc.json")
    with open(dp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print("   → %s（%.1f KB）" % (dp, os.path.getsize(dp) / 1024))


if __name__ == "__main__":
    main()
