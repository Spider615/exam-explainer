#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
segment.py —— 阶段② 题目切分

    python segment.py work/<name> [--strict]

读 doc.json，产出 questions.json：每题的序号、题型、分值、所属大题、
题干、选项、页码范围、以及归属到该题的插图。

它做什么、不做什么
------------------
**纯代码，无模型调用。** 只做版面和结构层面的切分，不理解题意。
凡是规则判不了的，宁可报 `warnings` 让人/模型来裁，也不猜。

三条核心规则
------------
1. **题目锚点交给 anchors.py**：多个互相独立的探测器各给一套候选，
   再用同一个与版式无关的结构打分器选最优。见该模块的说明。
   这里不再写死任何「题目长什么样」的规则。
2. **页眉页脚剔除**：同一 (x,y,w,h) 在半数以上页面重复出现的图片是
   版式元素（水印/二维码），不是插图。
3. **图文归属靠坐标**：把每张图的 (页, y) 落到相邻两个题目锚点之间。
   纯文本做不到这件事——这正是 ingest 必须保留坐标的原因。

自检
----
大题标题里的「本题共N小题」会被解析出来，与实际切出的题数比对；
对不上就进 warnings。这是最便宜的一道正确性防线。
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anchors as anchors_mod



# 大题标题的写法不统一：「本题共4小题」「:共10题」「共 8 题」都要认。
# 这条声明是打分器最强的外部证据，认不出来就只能靠弱先验，
# 实测导致江苏/海南两卷被「排版」候选抢走（15→9、19→13）。
SECTION_RE = re.compile(
    r"([一二三四五六七八九十]+)、\s*([^\n]{2,24}?)[（(:：]?\s*(?:本题)?共\s*(\d+)\s*[小]?[题道]")
# 坑：选项之间往往没有任何分隔符（"…697米B. 从O处…"），
# 所以不能要求前导空白。改为要求 A/B/C/D 四个匹配「连续且顺序正确」。
# 只用来当「切题边界」的大题标题：不要求带题数声明。
# 打分器用的 SECTION_RE 要求有「共N题」才算数（那是对账证据），
# 但边界不能只认带声明的那些 —— 否则「三、实验题」这种会被上一题的选项 D 吞掉。
SECTION_ANY = re.compile(r"[一二三四五六七八九十]+、\s*[^\n]{2,14}?题")

# 选项标记的写法有好几种，按「越具体越优先」逐级尝试。
# 关键规律：**选项标记用句点（A.），正文里引用某点用顿号（A、B两点）**。
# 只用最宽松的那条会被正文里的 `A、B两点`、`MA、MB` 打断，
# 实测河北卷第8题、北京卷第8题因此解析出 0 个选项。
OPTION_PATTERNS = [
    r"(?:^|[\s\u3000\u00a0])([ABCD])\s*[.．]\s*",   # 空白 + 字母 + 句点（最常见）
    r"([ABCD])\s*[.．]\s*",                          # 不要求前置空白
    r"(?:^|[\s\u3000\u00a0])([ABCD])\s*[、]\s*",   # 用顿号作选项标记的卷子
    r"([ABCD])\s*[.．、]\s*",                         # 兜底
]
OPTION_RES = [re.compile(x) for x in OPTION_PATTERNS]
OPTION_RE = OPTION_RES[-1]

# ---------------------------------------------------------------- 文本流
TABLE_MARK = "〔表%d〕"
FIG_MARK = "〔图%d〕"


def place_figures(doc, dropped):
    """
    给每张插图在文本流里插一个 `〔图N〕` 占位符。

    插图原本只是挂在题目末尾一股脑列出来，和原卷的图文位置对不上。
    有了占位符，图就能渲染回它在原文里的位置。

    插入点按纵向位置找：文本块已经是阅读顺序，找到第一个排在图下方的块，
    插在它前面。
    """
    figs, n = [], 0
    for pg in doc["pages"]:
        for im in pg.get("images", []):
            if im["file"] in dropped or im.get("y") is None:
                continue
            n += 1
            top = im["y"] + (im["h"] or 0)
            at = len(pg["spans"])
            for i, sp in enumerate(pg["spans"]):
                if sp.get("ok") and sp["y"] < top:
                    at = i
                    break
            pg["spans"].insert(at, {
                "text": " " + (FIG_MARK % n) + " ",
                "x": im["x"], "x1": im["x"] + (im["w"] or 0),
                "y": im["y"], "yt": top, "size": 10.5, "ok": True, "figure": n,
            })
            figs.append({"id": n, "page": pg["page"], "file": im["file"],
                         # 下游要靠这个框把题干切成「图之间的文字块」
                         "box": {"x0": im["x"], "y0": im["y"],
                                 "x1": im["x"] + (im["w"] or 0), "y1": top}})
    return figs


def is_body(s):
    """这个文本块算不算正文。页码残留（`5 / 10` 拆出来的 ` /`）只有符号和数字。"""
    return bool(re.search(r"[一-鿿A-Za-z]", s.get("text", "")))


def link_continuations(doc, tables):
    """
    认出**跨页续表**：一张表被页面截断，上半张贴在前页底部、下半张贴在次页顶部。

    实测江苏卷第11题、江西卷第11题都是这种表。分成两张各自渲染时，
    下半张没有表头——`0.120 0.140 0.160` 这样一行数字单独摆着，读者无从判断是什么量。

    判据只用版面事实，不看内容：相邻两页、左右边界对齐、
    上半张下方没有正文、下半张上方没有正文。四条全中才算续表。
    """
    pages = {p["page"]: p for p in doc["pages"]}
    for b in tables:
        # 前一页最靠下的那张表才可能被截断
        prev = [x for x in tables if x["page"] == b["page"] - 1]
        a = min(prev, key=lambda x: x["box"]["y0"]) if prev else None
        if not a:
            continue
        ba, bb = a["box"], b["box"]
        if abs(ba["x0"] - bb["x0"]) > 4 or abs(ba["x1"] - bb["x1"]) > 4:
            continue
        if any(is_body(s) and s.get("ok") and s["y"] < ba["y0"] - 2
               for s in pages[a["page"]]["spans"]):
            continue          # 上半张下面还有正文，说明它不是被页面截断的
        if any(is_body(s) and s.get("ok") and s["y"] > bb["y1"] + 2
               for s in pages[b["page"]]["spans"]):
            continue
        # 连跨三页时一律挂到最上面那张，合并只需处理一层
        b["cont_of"] = a.get("cont_of") or a["id"]


def merged_tables(tables):
    """
    把跨页续表拼成一张，返回**可直接渲染**的表列表。

    合并只在读取时做，不回写 questions.json —— 每张表的 `rows` 永远只是
    它自己那张裁图的转写结果。否则重跑一次 mathvlm，上半张会被它自己的
    裁图覆盖回两行，而下半张的数据已经被合并时删掉了，无声地少一行数据。

    列数对不上就不合并：宁可留两张各自完整的表，也不拼出一张错的。
    """
    by_id = {t["id"]: t for t in tables}
    cont = {}
    for t in tables:
        par = by_id.get(t.get("cont_of"))
        rows, prows = t.get("rows") or [], (par or {}).get("rows") or []
        if par is not None and rows and prows and len({len(r) for r in prows + rows}) == 1:
            cont.setdefault(par["id"], []).append(t)

    absorbed = {t["id"] for ts in cont.values() for t in ts}
    out = []
    for t in tables:
        if t["id"] in absorbed:
            continue
        parts = [t] + cont.get(t["id"], [])
        # 原卷截图要给全 —— 合并后只放上半张，读者就没法核对下半张是不是抄错了
        t = dict(t, images=[p["image"] for p in parts if p.get("image")])
        if len(parts) > 1:
            t["rows"] = [r for p in parts for r in p["rows"]]
        out.append(t)
    return out


def merge_warnings(tables):
    """跨页续表没能合并时的说明。只报事实，不猜原因。"""
    msgs = []
    for t in tables:
        par = next((x for x in tables if x["id"] == t.get("cont_of")), None)
        if par is None:
            continue
        rows, prows = t.get("rows") or [], par.get("rows") or []
        if not rows or not prows:
            msgs.append("表%d 是表%d 的跨页下半张，但有一半没转写出内容"
                        % (t["id"], par["id"]))
        elif len({len(r) for r in prows + rows}) > 1:
            msgs.append("表%d 是表%d 的跨页下半张，列数 %s 对不上 %s，未合并"
                        % (t["id"], par["id"],
                           sorted({len(r) for r in rows}), sorted({len(r) for r in prows})))
    return msgs


def fold_tables(doc):
    """
    把每张表格里的文字换成一个占位符。

    表是二维的，硬塞进一维的题干只会变成乱码
    （实测江苏卷第11题：`ΔWh/E_f/(/10((1010^(−2)_(−2)^(−3)mJJ))) 0.984.002.94`）。
    这里把表内文字整体摘掉，只留 `〔表N〕`，表的内容另行交给视觉模型转写。

    返回 [{id, page, box}]，供下游裁图。
    """
    tables = []
    for pg in doc["pages"]:
        for t in pg.get("tables", []):
            tid = len(tables) + 1
            # 表名（「表1」「表2」）在框线之外，不带上就会留在题干里
            # 和相邻的公式块粘成乱码（实测 `表16.007.45 W测/2`）。
            cap = [s for s in pg["spans"]
                   if s.get("ok") and t["x0"] - 20 <= s["x"] <= t["x1"] + 20
                   and t["y1"] < s["y"] <= t["y1"] + 26
                   and re.match(r"^\s*表\s*\d", s["text"])]
            if cap:
                t["y1"] = max(t["y1"], max(c["y"] + c.get("size", 11) for c in cap))
            inside = [s for s in pg["spans"]
                      if s.get("ok") and t["x0"] <= s["x"] <= t["x1"]
                      and t["y0"] <= s["y"] <= t["y1"]]
            if len(inside) < 3:
                continue          # 框里没几个字，多半不是真表格
            tables.append({"id": tid, "page": pg["page"], "box": t,
                           "_pg": pg, "_inside": inside})

    link_continuations(doc, tables)

    for rec in tables:
        pg, inside, t = rec.pop("_pg"), rec.pop("_inside"), rec["box"]
        keep, placed = [], False
        for s in pg["spans"]:
            if s in inside:
                if not placed:
                    # 续表不留可见占位符——它和上半张之间不该再插一个记号。
                    # 但记号本身要留着：题目归属靠它带的 table 字段，
                    # 摘干净了这张表就归不到任何一道题，也就不会被转写。
                    keep.append({"text": " " if rec.get("cont_of")
                                 else " " + (TABLE_MARK % rec["id"]) + " ",
                                 "x": t["x0"], "x1": t["x1"],
                                 "y": t["y1"], "yt": t["y1"],
                                 "size": s.get("size", 10.5), "ok": True,
                                 "table": rec["id"]})
                    placed = True
            else:
                keep.append(s)
        pg["spans"] = keep
    return tables


def build_flow(doc):
    """把所有页的文本块按阅读顺序拼成一条带坐标的字符流。"""
    flow, offset = [], 0
    buf = []
    for p in doc["pages"]:
        for s in p["spans"]:
            t = s["text"]
            if not t:
                continue
            flow.append({"start": offset, "end": offset + len(t),
                         "page": p["page"], "y": s["y"], "x": s["x"],
                         "ok": s.get("ok", True), "mathml": s.get("mathml"),
                         "table": s.get("table"), "figure": s.get("figure")})
            buf.append(t)
            offset += len(t)
    return "".join(buf), flow


def locate(flow, pos):
    """
    字符偏移 → (页码, y)

    题型标记那一行的 tm 是退化单位阵，自身没有有效坐标（ok=False），
    所以命中无效块时向后找第一个有坐标的块——题干紧跟标记，
    用题干首行的位置代表这道题的起点是准确的。
    """
    if not flow:
        return (None, None)
    lo, hi = 0, len(flow) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if flow[mid]["end"] <= pos:
            lo = mid + 1
        else:
            hi = mid
    i = lo
    while i < len(flow) and not flow[i]["ok"]:
        i += 1
    if i >= len(flow):                      # 尾部全无效，退回向前找
        i = lo
        while i >= 0 and not flow[i]["ok"]:
            i -= 1
        if i < 0:
            return (flow[lo]["page"], flow[lo]["y"])
    return (flow[i]["page"], flow[i]["y"])


# ---------------------------------------------------------------- 图片
def drop_boilerplate(doc):
    """剔除页眉页脚：同一位置同一尺寸在半数以上页面重复出现。"""
    seen = {}
    for p in doc["pages"]:
        for im in p["images"]:
            if im["x"] is None:
                continue
            key = (im["x"], im["y"], im["w"], im["h"])
            seen.setdefault(key, set()).add(p["page"])
    n_pages = len(doc["pages"])
    boiler = {k for k, pgs in seen.items() if len(pgs) > n_pages / 2}

    kept, dropped = [], []
    for p in doc["pages"]:
        for im in p["images"]:
            rec = dict(im, page=p["page"])
            key = (im["x"], im["y"], im["w"], im["h"])
            (dropped if key in boiler else kept).append(rec)
    return kept, dropped


def after(a, b):
    """(页,y) 排序：页小在前；同页 y 大在前（PDF 的 y 向上）。"""
    if a[0] != b[0]:
        return a[0] > b[0]
    return a[1] < b[1]


# ---------------------------------------------------------------- 题干清洗
def group_option_figures(figs, n_options):
    """
    把「一行 N 个并排的小图」识别为选项配图。

    判据全是几何的：同页、y 几乎相同、尺寸相近、个数等于选项数。
    第4题就是这种——p02_03~06 同在 y≈297、都是 99×62、x 均匀分布，
    它们是 A/B/C/D 四个选项的图，不是题干图。混在一起会让下游把选项图
    当成情境图去还原，属于会直接画错的那类错误。
    """
    if n_options < 2 or len(figs) < n_options:
        return figs, []
    by_row = {}
    for f in figs:
        if f["y"] is None:
            continue
        by_row.setdefault((f["page"], round(f["y"] / 12.0)), []).append(f)
    for key, row in by_row.items():
        if len(row) != n_options:
            continue
        ws = [f["w"] for f in row if f["w"]]
        hs = [f["h"] for f in row if f["h"]]
        if len(ws) != len(row):
            continue
        if max(ws) - min(ws) > 0.25 * max(ws) or max(hs) - min(hs) > 0.3 * max(hs):
            continue
        row.sort(key=lambda f: f["x"])
        rest = [f for f in figs if f not in row]
        return rest, row
    return figs, []


# 公式被压平的痕迹：字母紧跟多位数字、右括号后跟数字（分式/根号的指数被拍平）
FLAT_RE = re.compile(r"[A-Za-zΩωπρμ]\s?\d{2,}|\]\d+|\d+[A-Za-z]{1,2}\d+")


def text_quality(stem, options):
    """
    判断这道题的文字层是否可用。返回 (等级, 原因, 证据)。

    要分清两件长得很像但性质不同的事：
      · 选项本来就是图片（第4题）—— 文本为空是正常的，不是缺陷；
      · 公式被文字层拍平（第8题 ω=[G(M+m)2R3 ]12）—— 真的丢了信息，
        分式和上下标不可恢复，必须退回页面图像。
    """
    txt = stem + " " + " ".join(o["text"] for o in options)
    hits = FLAT_RE.findall(txt)
    empty = [o for o in options if not o["text"].strip()]
    if options and all(o.get("figure") for o in options) and len(empty) >= len(options) - 1:
        return ("ok", "图片选项", [])
    if len(hits) >= 4:
        return ("degraded", "公式被压平", hits[:8])
    if options and len(empty) >= len(options) - 1:
        return ("degraded", "选项文本缺失且无配图", hits[:8])
    if hits:
        return ("suspect", "疑似上下标丢失", hits[:8])
    return ("ok", "", [])


def clean_stem(raw):
    """清洗题干。注意页脚的孤立「/」会跟到题干尾部（每页都有一个），
    不清掉的话下游会把它误认成分式的残缺一侧 —— 实测 328 题里有 90 题中招。"""
    s = re.sub(r"[ \t]+", " ", raw)
    s = re.sub(r"\n{2,}", "\n", s)
    s = re.sub(r"^\s*/\s*$", "", s, flags=re.M)          # 整行只有 "/"
    # 换行/分栏处补的空格夹在两个汉字之间时是多余的（如「方向向 上」）
    s = re.sub(r"(?<=[\u4e00-\u9fff])[ \u3000]+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"\s*/\s*$", "", s)                       # 结尾的页脚 "/"
    s = re.sub(r"^\s*/\s*", "", s)                       # 开头的页脚 "/"
    return s.strip()


def split_options(stem):
    """
    把 A. B. C. D. 四个选项从题干里分出来。

    只认「四个匹配在序列里连续出现且恰为 A,B,C,D」的那一组——
    这样 "A点" "图A" 这类正文里的字母不会误伤（它们不会凑出连续的 ABCD）。
    凑不齐就整块留作题干，交给下游判，不猜。
    """
    # 四个连续标记只要是 ABCD 的**任意排列**就算数，切完再按字母归位。
    # 选项常排成 2×2，而字母可能是按列往下排的（左列 A、B，右列 C、D），
    # 文本顺序就成了 A、C、B、D；硬要求顺序连续会整题解析不出选项。
    quad = None
    for rx in OPTION_RES:
        ms = list(rx.finditer(stem))
        for i in range(len(ms) - 3):
            if sorted(ms[i + k].group(1) for k in range(4)) == list("ABCD"):
                quad = ms[i:i + 4]
                break
        if quad:
            break
    if not quad:
        return stem, []
    body = stem[:quad[0].start()].strip()
    opts = []
    for i, m in enumerate(quad):
        b = m.end()
        e = quad[i + 1].start() if i < 3 else len(stem)
        txt = re.sub(r"\s*/\s*$", "", stem[b:e].strip()).strip()
        txt = re.sub(r"(?<=[\u4e00-\u9fff])[ \u3000]+(?=[\u4e00-\u9fff])", "", txt)
        opts.append({"key": m.group(1), "text": txt})
    opts.sort(key=lambda o: o["key"])       # 版面若是按列排的，这里归位
    return body, opts


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--strict", action="store_true", help="有 warning 就非零退出")
    ap.add_argument("--llm", choices=["auto", "never", "always"], default="auto",
                    help="代码路径不自信时是否升级到模型通道（默认 auto）")
    a = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    doc = json.load(open(os.path.join(a.workdir, "doc.json"), encoding="utf-8"))
    _kept0, _drop0 = drop_boilerplate(doc)
    figmarks = place_figures(doc, {im["file"] for im in _drop0})
    tables = fold_tables(doc)
    text, flow = build_flow(doc)
    warnings = []

    # --- 大题（章节）---
    sections = []
    for m in SECTION_RE.finditer(text):
        sections.append({"label": m.group(1), "title": m.group(2).strip(),
                         "declared": int(m.group(3)), "pos": m.start()})
    # 兜底：有些卷子章节行被拆散，退而求其次全文扫
    if not sections:
        for m in re.finditer(r"([一二三四五六七八九十]+)、([^（(\n]{2,20})[（(]本题共(\d+)", text):
            sections.append({"label": m.group(1), "title": m.group(2).strip(),
                             "declared": int(m.group(3)), "pos": m.start()})

    # --- 通用锚点探测：多探测器 + 版式无关的结构打分 ---
    declared_total = sum(x["declared"] for x in sections)
    marks, plan, why, ranking = anchors_mod.detect(text, flow, doc, declared_total)
    if marks is None:
        print("✗ 所有探测器都没能切开这份卷子：")
        for sc, name, _, w in ranking[:6]:
            print("    %-22s %s" % (name, w))
        sys.exit("  这份卷子的结构超出了当前三个探测器的能力，需要人工确认。")
    print("   锚点方案：%s（%s）" % (plan, why))
    for sc, name, _, w in ranking[1:4]:
        print("     · 落选 %-22s %s" % (name, w))

    # --- 不自信就升级到模型通道；模型的方案同样要过结构门禁 ---
    conf, creason = anchors_mod.confidence(marks, text, declared_total)
    print("   代码路径自信度：%s（%s）" % ("够" if conf else "不够", creason))
    if a.llm == "always" or (a.llm == "auto" and not conf):
        try:
            import llm_segment
            lanc, note, hit = llm_segment.plan_anchors(
                doc, text, flow, sections, ranking,
                cache_dir=os.path.join(a.workdir, "_cache"))
            lsc, lwhy = anchors_mod.score(lanc, text, declared_total)
            lconf, lreason = anchors_mod.confidence(lanc, text, declared_total)
            print("   ↑ 升级模型通道：%s" % note)
            print("     复核：score=%.1f（%s）自信度%s（%s）"
                  % (lsc, lwhy, "够" if lconf else "不够", lreason))
            csc, _ = anchors_mod.score(marks, text, declared_total)
            if lconf and lsc >= csc:
                marks, plan = lanc, "模型方案"
                print("     → 采用模型方案")
            else:
                warnings.append("模型方案未通过结构门禁（%s），仍用代码方案；切分可能不准" % lreason)
                print("     → 不采用，保留代码方案")
        except Exception as e:
            warnings.append("模型通道不可用：%s；切分可能不准" % e)
            print("   ↑ 模型通道失败：%s" % e)
    elif a.llm == "never" and not conf:
        warnings.append("代码路径自信度不够（%s）且已禁用模型通道，切分可能不准" % creason)

    kept_imgs, dropped_imgs = drop_boilerplate(doc)

    questions = []
    for i, m in enumerate(marks):
        beg = m["end"]
        end = marks[i + 1]["pos"] if i + 1 < len(marks) else len(text)
        # 大题标题也是硬边界：否则本大题最后一题的末选项会把
        # 「二、多项选择题（本题共4小题…」整段吞进去。
        for sm in SECTION_ANY.finditer(text):
            if beg < sm.start() < end:
                end = sm.start()
                break
        stem_raw = clean_stem(text[beg:end])
        body, opts = split_options(stem_raw)

        p0 = locate(flow, m["pos"])
        # 图片归属的上界：下一题锚点的位置。不能用本题内容的尾页——
        # 那会把同一页上属于下一题的图也吞进来（实测导致 18 张变 25 张、出现重复归属）。
        p1 = (locate(flow, marks[i + 1]["pos"]) if i + 1 < len(marks)
              else (doc["n_pages"] + 1, 1e9))
        # 显示用的页码区间是另一回事：按本题实际内容跨越的页取 min/max。
        # 用「下一题锚点前一个字符」会多算一页，因为页脚和次页页眉的文本块夹在中间。
        span_pages = [f["page"] for f in flow
                      if f["ok"] and f["start"] >= m["pos"] and f["end"] <= end]
        show_pages = ([min(span_pages), max(span_pages)] if span_pages
                      else [p0[0], p0[0]])
        # 每题在各页上的纵向边界。下游要靠它把「本题的选项区」从整页里框出来，
        # 没有它就只能全页找选项字母，同一页上的几道题会互相串。
        ybounds = {}
        for f in flow:
            if f["ok"] and m["pos"] <= f["start"] and f["end"] <= end:
                b = ybounds.setdefault(str(f["page"]), [f["y"], f["y"]])
                b[0] = min(b[0], f["y"])
                b[1] = max(b[1], f["y"])

        mine = []
        for im in kept_imgs:
            pos = (im["page"], im["y"])
            if after(pos, p0) and (i + 1 == len(marks) or after(p1, pos)):
                mine.append(im)
        stem_figs, opt_figs = group_option_figures(mine, len(opts))
        if opt_figs:
            for k, f in enumerate(opt_figs):
                if k < len(opts):
                    opts[k]["figure"] = f["file"]

        # 公式的 MathML：按线性文本在题干/选项里回查位置。
        # 不用字符偏移对齐，因为 clean_stem 会改动空白导致偏移错位；
        # 公式的线性文本足够独特，直接 find 更稳。
        maths = []
        for f in flow:
            if not f.get("mathml") or not (m["pos"] <= f["start"] and f["end"] <= end):
                continue
            lit = text[f["start"]:f["end"]]
            maths.append({"text": lit, "mathml": f["mathml"]})

        def locate_math(target):
            segs, cur = [], 0
            for mm in maths:
                k = target.find(mm["text"], cur)
                if k < 0:
                    continue
                segs.append({"s": k, "e": k + len(mm["text"]), "mathml": mm["mathml"]})
                cur = k + len(mm["text"])
            return segs

        stem_math = locate_math(body)
        for o in opts:
            o["math"] = locate_math(o["text"])

        # 本题里出现的表格
        qtables = sorted({f["table"] for f in flow
                          if f.get("table") and m["pos"] <= f["start"] and f["end"] <= end})
        qfigs = sorted({f["figure"] for f in flow
                        if f.get("figure") and m["pos"] <= f["start"] and f["end"] <= end})

        qual, qreason, flat_hits = text_quality(body, opts)

        sec = None
        for s in sections:
            if s["pos"] < m["pos"]:
                sec = s
        questions.append({
            "n": i + 1,
            "type": m.get("type") or "题目",
            "points": m.get("points"),
            "section": (sec["label"] + "、" + sec["title"]) if sec else None,
            "pages": show_pages,
            "y_bounds": ybounds,
            "tables": [t for t in tables if t["id"] in qtables],
            "fig_marks": [f for f in figmarks if f["id"] in qfigs],
            "y_range": [p0[1], p1[1]],
            "stem": body,
            "stem_math": stem_math,
            "options": opts,
            "figures": [f["file"] for f in stem_figs],
            "option_figures": [f["file"] for f in opt_figs],
            "text_quality": qual,
            "quality_reason": qreason,
            "flattened": flat_hits,
            "n_chars": len(body),
        })

    # --- 自检 ---
    for s in sections:
        got = sum(1 for q in questions if q["section"] and q["section"].startswith(s["label"] + "、"))
        if got != s["declared"]:
            warnings.append("大题「%s、%s」声明 %d 小题，实际切出 %d 题"
                            % (s["label"], s["title"], s["declared"], got))
    for q in questions:
        if q["n_chars"] < 20:
            warnings.append("第%d题题干只有 %d 字，可能切断了" % (q["n"], q["n_chars"]))
        if q["type"] in ("单选题", "多选题") and len(q["options"]) != 4:
            warnings.append("第%d题是%s但只解析出 %d 个选项" % (q["n"], q["type"], len(q["options"])))
    assigned = set()
    for q in questions:
        assigned.update(q["figures"])
        assigned.update(q["option_figures"])
    # 归属唯一性：一张图只能属于一道题。
    # 这条自检抓到过真实回归——改页码区间时顺手把图片边界也改了，
    # 导致同一页上属于下一题的图被上一题吞掉，18 张变 25 张。
    seen_fig = {}
    for q in questions:
        for f in q["figures"] + q["option_figures"]:
            seen_fig.setdefault(f, []).append(q["n"])
    dup = {f: ns for f, ns in seen_fig.items() if len(ns) > 1}
    if dup:
        warnings.append("有 %d 张插图被重复归属到多道题：%s"
                        % (len(dup), "；".join("%s→第%s题" % (f.split("/")[-1],
                                                            "、".join(map(str, ns)))
                                               for f, ns in list(dup.items())[:4])))

    orphan = [im["file"] for im in kept_imgs if im["file"] not in assigned]
    if orphan:
        warnings.append("有 %d 张插图没能归属到任何题目：%s" % (len(orphan), ", ".join(orphan)))
    for q in questions:
        if q["text_quality"] == "degraded":
            ev = ("：" + "、".join(q["flattened"][:3])) if q["flattened"] else ""
            warnings.append("第%d题文字层不可直接使用（%s%s），需退回页面图像"
                            % (q["n"], q["quality_reason"], ev))

    # --- 输出 ---
    out = {
        "source": doc["source"],
        "n_questions": len(questions),
        "sections": [{k: v for k, v in s.items() if k != "pos"} for s in sections],
        "dropped_boilerplate": sorted({im["file"] for im in dropped_imgs}),
        "warnings": warnings,
        "questions": questions,
    }
    qp = os.path.join(a.workdir, "questions.json")
    json.dump(out, open(qp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("── 切分 %s" % a.workdir)
    for s in out["sections"]:
        print("   %s、%s  声明 %d 题" % (s["label"], s["title"], s["declared"]))
    print("   切出 %d 题；插图 %d 张已归属，%d 张判为页眉页脚剔除"
          % (len(questions), sum(len(q["figures"]) for q in questions),
             len(set(im["file"] for im in dropped_imgs))))
    QMARK = {"ok": "  ", "suspect": " ?", "degraded": " ✗"}
    for q in questions:
        print("   第%2d题 %s %5s  p%d-%d  %3d字  选项%d  题干图%d  选项图%d  文字层%s%s"
              % (q["n"], q["type"],
                 ("%d分" % q["points"]) if q["points"] is not None else "—",
                 q["pages"][0], q["pages"][1],
                 q["n_chars"], len(q["options"]), len(q["figures"]),
                 len(q["option_figures"]),
                 q["text_quality"] + ("/" + q["quality_reason"] if q["quality_reason"] else ""),
                 QMARK[q["text_quality"]]))
    if warnings:
        print("   ⚠ %d 条告警：" % len(warnings))
        for w in warnings:
            print("     · " + w)
    else:
        print("   ✓ 无告警")
    print("   → %s" % qp)
    if warnings and a.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
