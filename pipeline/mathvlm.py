#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mathvlm.py —— 阶段②b：用视觉模型把含公式的选项还原成 LaTeX

    python mathvlm.py work/<name> [--force] [--limit N]

为什么需要它
------------
从 PDF 矢量数据反推公式的二维结构（哪是分子、哪是分母、根号盖住哪一段），
本质是「PDF 数学公式识别」，是个有专门研究领域的难题。
纯几何规则做到约 85% 就到顶了，剩下的都是**几何上无法区分**的歧义 ——
例如上下堆叠的两个选项，A 的分母和 C 的根号上横线只差 9pt，
任何基于距离的判据都会串味。

更要命的是失败模式：
  · 裁图裁歪了 —— 一眼看得出
  · 结构解析错了 —— `√rg` 和 `√(r/g)` 长得都像对的，看不出来
对给学生看的产品，后者不可接受。

做法
----
**裁得宽松一点，让模型同时做版面分析和公式识别。**
精确裁出每个公式又会掉回版面分析的坑；裁整个选项块，
让模型输出 `{key, latex}` 数组，反而更稳
（实测 2×2 列主序布局，几何解析全错，模型一次全对）。

  1. 用已有的逐字符坐标算出「选项块」外框
  2. 从 300dpi 页面渲染图上裁下来，降到 150dpi 存 PNG
  3. 按**图片内容哈希**查缓存；未命中才调模型
  4. 模型返回每个选项的 LaTeX，写回 questions.json

原图始终保留 —— 既是兜底，也是「对照原卷」的依据。
模型也会错，但错了必须能被看见。
"""
import argparse, base64, hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import segment      # 「什么算正文」这条判据两边必须一致，不能各写一份
import clishim      # 让 CLI 走中转的 key 而不是订阅

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = next((p for p in ("/opt/homebrew/bin/claude",
                        os.path.expanduser("~/.nvm/versions/node/v25.2.1/bin/claude"),
                        "/usr/local/bin/claude") if os.path.exists(p)), None)
MODEL = os.environ.get("EXAM_VLM_MODEL", "claude-sonnet-5")
DPI = 300
SCALE = 0.5          # 存图时降到 150dpi：模型看得清，token 省一半


FRAG_PROMPT = """这是一道中文物理题里的一小段文字（版面片段，可能不是完整句子）。

逐字转写，输出 JSON（不要代码块围栏、不要解释）：
{"stem":"..."}

要求：
- 中文、标点、单位一律照抄，不要改写、不要润色、不要补全、不要省略。
- 数学部分用 `$...$` 包成行内公式：分式 \\dfrac{}{}，根号 \\sqrt{}，上下标 ^{} _{}。
  单个变量（如 v、t、R）也包进 $ $。
- 图片里有多少字就转写多少字，**一个字都不能漏**。
- 看不清的地方用 ? 占位，不要猜。
"""


STEM_PROMPT = """这是一道中文物理题的题干截图（不含选项）。

逐字转写成文本，输出 JSON（不要代码块围栏、不要解释）：
{"stem":"..."}

要求：
- 中文、标点、单位一律照抄，不要改写、不要润色、不要补全。
- 数学部分用 `$...$` 包成行内公式：分式 \\dfrac{}{}，根号 \\sqrt{}，上下标 ^{} _{}。
  单个变量（如 v、t、R）也包进 $ $。
- **遇到插图不要描述内容**，整张图写成 `〔图〕` 一个占位符，保持它在原文中的位置。__FIG_HINT__
- **遇到表格不要转写表格内容**，整张表原样写成 `〔表〕` 一个占位符
  （表格由另一条流程单独处理）。__TABLE_HINT__
- 看不清的地方用 ? 占位，不要猜。
"""


TABLE_PROMPT = """这是一道中文物理题里的表格截图。

转写成 JSON（不要代码块围栏、不要解释）：
{"caption":"表名或空串","rows":[["单元格","单元格"],["...","..."]]}

要求：
- rows 第一行是表头。每行的单元格数量必须一致。
- 单元格里的数学部分用 `$...$` 包成行内公式（分式 \\dfrac{}{}，上下标 ^{} _{}）。
- 数值、单位一律照抄，不要换算、不要补零、不要改精度。
- 空单元格写成空串。看不清的写 ?，不要猜。
"""


PROMPT = """这是一道中文物理题的选项区截图。

识别其中每一个选项，输出 JSON（不要代码块围栏、不要任何解释）：
{"options":[{"key":"A","latex":"..."}]}

要求：
- key 是选项字母。注意选项可能排成两行两列，**字母可能是按列往下排的**
  （左列 A、B，右列 C、D），以图上实际标注的字母为准。
- latex 用行内数学写法：分式用 \\dfrac{}{}，根号用 \\sqrt{}，上下标用 ^{} _{}。
- 选项里的纯中文/纯文字部分直接写成文字，不要硬套数学环境。
- 逐字照抄，不要化简、不要改写、不要补全你认为缺失的内容。
- 看不清的地方用 ? 占位，不要猜。
"""


def find_option_block(page, qspans, bs):  # qspans 必须只含本题的文本块
    """
    从题目所在页的文本块里，框出「选项区」。

    以选项字母（A. B. C. D.）的位置为锚，纵向扩出两个字高
    —— 分式的分子分母会在字母的上下方。
    """
    marks = [s for s in qspans
             if s.get("ok") and re.fullmatch(r"[ABCD]\s*[.．、]", s["text"].strip())]
    if len(marks) < 4:
        return None
    ys = [m["y"] for m in marks]
    lo, hi = min(ys) - bs * 2.2, max(ys) + bs * 2.2
    x0 = min(m["x"] for m in marks) - 6

    xs = [s for s in qspans if lo <= s["y"] <= hi and s["x"] >= x0 - 2]
    rs = [r for r in page.get("rules", []) if lo <= r["y"] <= hi and r["x"] >= x0 - 2]
    if not xs:
        return None
    x1 = max([s.get("x1", s["x"] + bs) for s in xs] + [r["x"] + r["w"] for r in rs]) + 6
    y0 = min([s["y"] for s in xs] + [r["y"] for r in rs]) - bs * 0.5
    y1 = max([s["y"] + s.get("size", bs) for s in xs] + [r["y"] for r in rs]) + bs * 0.4
    return (x0, y0, x1, y1)


def find_stem_block(page, qspans, bs):
    """
    框出「题干区」：本题范围内、第一个选项字母之上的部分。

    下边界要用**最高那个选项字母的基线**，不能用选项块的外框 ——
    外框为了容纳分子分母向上扩了两个字高，会盖住题干的最后一行，
    裁出来的图少一行，模型转写就跟着少一句。
    """
    marks = [s for s in qspans
             if re.fullmatch(r"[ABCD]\s*[.．、]", s["text"].strip())]
    lo = (max(m["y"] for m in marks) + bs * 0.6) if marks else -1e9
    xs = [s for s in qspans if s["y"] > lo]
    rs = [r for r in page.get("rules", []) if r["y"] > lo]
    if len(xs) < 3:
        return None
    x0 = min(s["x"] for s in xs) - 5
    x1 = max(s.get("x1", s["x"] + bs) for s in xs) + 5
    rs = [r for r in rs if x0 <= r["x"] <= x1 and r["y"] <= max(s["y"] for s in xs) + bs]
    y0 = min([s["y"] for s in xs] + [r["y"] for r in rs]) - bs * 0.5
    y1 = max([s["y"] + s.get("size", bs) for s in xs] + [r["y"] for r in rs]) + bs * 0.4
    return (x0, y0, x1, y1)


def cjk_only(t):
    return "".join(c for c in t if "\u4e00" <= c <= "\u9fff")


def render_page(pdf, pno, out_png):
    if os.path.exists(out_png):
        return out_png
    pre = out_png[:-4]
    subprocess.run(["pdftoppm", "-r", str(DPI), "-png", "-f", str(pno), "-l", str(pno),
                    pdf, pre], capture_output=True)
    for cand in ("%s-%02d.png" % (pre, pno), "%s-%d.png" % (pre, pno),
                 "%s-%03d.png" % (pre, pno)):
        if os.path.exists(cand):
            os.rename(cand, out_png)
            break
    return out_png if os.path.exists(out_png) else None


def crop(page_png, box, page_h, dst):
    from PIL import Image
    k = DPI / 72.0
    x0, y0, x1, y1 = box
    im = Image.open(page_png)
    c = im.crop((max(0, int(x0 * k)), max(0, int((page_h - y1) * k)),
                 min(im.width, int(x1 * k)), min(im.height, int((page_h - y0) * k))))
    if SCALE != 1:
        c = c.resize((max(1, int(c.width * SCALE)), max(1, int(c.height * SCALE))),
                     Image.LANCZOS)
    c.save(dst)
    return dst


# JSON 里合法、但在 LaTeX 里几乎必然是命令前缀的那几个转义。
# 模型写 `"$8\times10^{-12}$"`，`\t` 是合法 JSON 转义，json.loads 会**静默地**
# 把它变成一个真制表符，于是 `\times` 变成 TAB+"imes" —— 公式坏了而且看不见。
# 这几个字符在物理答案里从来不是有意为之，还原回去是安全的。
#
# **`\n` 不在其中**：`\nu`/`\neq` 有，但解答过程里真正的换行也有，还原会把
# 「解得\nT=288K」弄成 `\nT`。宁可漏修 `\nu` 那一类，也不制造新的错。
_CTRL_BACK = {"\t": "\\t", "\f": "\\f", "\b": "\\b", "\r": "\\r"}


def _unctrl(o):
    """把 JSON 吃掉的 LaTeX 反斜杠还原回来。见 _CTRL_BACK 的说明。"""
    if isinstance(o, str):
        for ch, back in _CTRL_BACK.items():
            o = o.replace(ch, back)
        return o
    if isinstance(o, list):
        return [_unctrl(x) for x in o]
    if isinstance(o, dict):
        return {k: _unctrl(v) for k, v in o.items()}
    return o


def loads_lenient(txt):
    """
    容错解析模型返回的 JSON。

    做两件事：

    1. 把**不是合法 JSON 转义**的孤立反斜杠补成 `\\`（模型漏转义时的
       Invalid-escape 错误）。别的一概不动 —— 不能为了解析成功去猜内容。
    2. 把 `\\t` `\\f` `\\b` `\\r` 这几个**合法但几乎必然是 LaTeX 命令前缀**的
       转义还原回去。它们不会报错，只会静默地把 `\\times`/`\\frac`/`\\right`
       变成控制字符 —— 实测第 13(2)、13(3)、14(1) 题就是这么坏的。
    """
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        d = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', txt))
    return _unctrl(d)


def ask_raw(img_path, prompt, want="object", timeout=240):
    """
    调视觉模型读一张图，返回解析后的 JSON。

    `want="array"` 时找 `[...]`，否则找 `{...}`。参考答案与答题卡那两条链要的
    是数组，这里参数化一下，免得几处各写一份调用与容错。

    **不要送放大过的图。** 实测同一页 1080×1441 只要 57 秒，放大到 1620×2208
    之后 600 秒都回不来。要看清细节就裁小一块，别整张放大。
    """
    if not CLI:
        raise RuntimeError("找不到 claude 可执行文件；视觉通道不可用")
    r = subprocess.run([CLI, "-p", "--model", MODEL],
                       input=prompt + "\n图片：" + os.path.abspath(img_path),
                       capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, **clishim.ensure()))
    if r.returncode != 0:
        raise RuntimeError("模型调用失败：%s" % (r.stderr or "")[-200:])
    m = re.search(r"\[.*\]" if want == "array" else r"\{.*\}", r.stdout, re.S)
    if not m:
        raise RuntimeError("模型没有返回 JSON：%s" % r.stdout[:200])
    return loads_lenient(m.group(0))


def ask_model(img_path, prompt=None):
    return ask_raw(img_path, prompt or PROMPT, want="object")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--force", action="store_true", help="忽略缓存重新识别")
    ap.add_argument("--limit", type=int, default=0, help="最多处理几道题（调试用）")
    ap.add_argument("--dry-run", action="store_true",
                    help="照常裁图查缓存，但不调模型、不写回；只报要花多少次调用")
    a = ap.parse_args()

    need = []
    if a.dry_run:
        # 裁图、算哈希、查缓存全都照跑，只把「真去调模型」那一步换成抛异常 ——
        # 各处的 except 会退回几何抽取继续往下走，于是一趟就能数清
        # 真正要花的调用次数。dry-run 不写回 questions.json。
        def _count(img_path, prompt=None):
            need.append(img_path)
            raise RuntimeError("dry-run：未命中缓存")
        globals()["ask_model"] = _count

    doc = json.load(open(os.path.join(a.workdir, "doc.json"), encoding="utf-8"))
    qs = json.load(open(os.path.join(a.workdir, "questions.json"), encoding="utf-8"))
    pdf = doc["source"]
    cache_dir = os.path.join(ROOT, "work", "_mathcache")
    img_dir = os.path.join(a.workdir, "mathimg")
    tmp_dir = os.path.join(a.workdir, "_hires")
    for d in (cache_dir, img_dir, tmp_dir):
        os.makedirs(d, exist_ok=True)

    pages = {p["page"]: p for p in doc["pages"]}
    sizes = [s.get("size", 0) for p in doc["pages"] for s in p["spans"] if s.get("size")]
    bs = max(set(sizes), key=sizes.count) if sizes else 10.5

    done = hit = miss = skip = fail = 0
    for q in qs["questions"]:
        if a.limit and done >= a.limit:
            break
        if len(q.get("options", [])) != 4 and not q.get("tables"):
            skip += 1
            continue
        # 选项通常落在题目的最后一页；跨页题不能一律取首页
        qpages = [n for n in range(q["pages"][0], q["pages"][1] + 1)
                  if str(n) in (q.get("y_bounds") or {}) and n in pages]
        if not qpages:
            skip += 1
            continue

        def marks_on(n):
            b = q["y_bounds"][str(n)]
            return [s for s in pages[n]["spans"]
                    if s.get("ok") and b[0] - 2 <= s["y"] <= b[1] + 2
                    and re.fullmatch(r"[ABCD]\s*[.．、]", s["text"].strip())]

        pno = next((n for n in reversed(qpages) if len(marks_on(n)) >= 4), qpages[0])
        page = pages[pno]
        # 只处理「区域内有横线」的题：没有分数线/根号就没有二维结构，
        # 几何解析已经够用，没必要花一次模型调用。
        yb = q["y_bounds"][str(pno)]
        # 只在本题的纵向范围内找选项 —— 否则同一页上的几道题会互相串，
        # 实测第 1、2、3 题拿到了同一份选项。
        qspans = [s for s in page["spans"]
                  if s.get("ok") and yb[0] - 2 <= s["y"] <= yb[1] + 2]
        box = find_option_block(page, qspans, bs)
        has_opt_math = bool(box) and any(
            box[1] <= r["y"] <= box[3] and box[0] <= r["x"] <= box[2]
            for r in page.get("rules", []))
        if not has_opt_math and not q.get("tables"):
            skip += 1
            continue

        big = render_page(pdf, pno, os.path.join(tmp_dir, "p%02d.png" % pno))
        if not big:
            fail += 1
            continue

        def run_block_on(page_png, page_h, box, tag, prompt=None):
            """裁一块 → 查缓存 → 未命中才调模型。返回 (数据, 是否命中缓存, 图路径)。"""
            dst = os.path.join(img_dir, "q%02d%s.png" % (q["n"], tag))
            crop(page_png, box, page_h, dst)
            h = hashlib.sha256(open(dst, "rb").read()).hexdigest()[:16]
            cp = os.path.join(cache_dir, h + ".json")
            if os.path.exists(cp) and not a.force:
                return json.load(open(cp, encoding="utf-8")), True, dst
            d = ask_model(dst, prompt)
            json.dump(d, open(cp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            return d, False, dst

        def run_block(box, tag, prompt=None):
            return run_block_on(big, page["height"], box, tag, prompt)

        # ---- 选项区 ----
        by, cached = {}, False
        if has_opt_math:
            try:
                data, cached, raw = run_block(box, "")
                hit += cached
                miss += (not cached)
                by = {o.get("key"): o.get("latex", "") for o in data.get("options", [])}
                for o in q["options"]:
                    if by.get(o["key"]):
                        o["latex"] = by[o["key"]]
                q["option_image"] = "mathimg/q%02d.png" % q["n"]
            except Exception as e:
                print("   ✗ 第%d题 选项 %s" % (q["n"], e))
                fail += 1

        # ---- 题干：按图/表切成纯文字块，**逐块**转写 ----
        # 整页丢给模型转写它会漏 —— 江苏卷第11题占大半页、图文表混排，
        # 一次要求模型准确复现十几个元素的顺序和数量，实测漏掉了 (2)(3) 两个小问。
        # 关键改动：**图和表不交给模型**。它们的位置我自己知道，
        # 占位符由代码直接插入，模型只负责转写纯文字块 ——
        # 这样「数图表」这类错误从根上消失。
        need_stem = bool(q.get("stem_math")) or bool(q.get("tables"))
        parts, simg, blocks_bad = [], None, []
        for n in qpages:
            b = q["y_bounds"][str(n)]
            pg = pages[n]
            band = [s2 for s2 in pg["spans"]
                    if s2.get("ok") and b[0] - 2 <= s2["y"] <= b[1] + 2]
            if n == pno:
                mk = marks_on(n)
                # 必须 ≥4 个才算「本题的选项区」。题干里常有
                # `A.①②③④ B.④②③①` 这种小问备选答案，只有三个字母；
                # 拿它当选项区去截断，会把它下方的整段题干砍掉
                # （实测江苏卷第11题的第(3)问就是这么丢的）。
                if len(mk) >= 4:
                    lo = max(m["y"] for m in mk) + bs * 0.6
                    band = [s2 for s2 in band if s2["y"] > lo]
            if len(band) < 3:
                continue

            # 本页的「障碍物」：图与表。它们把文字切成若干块。
            obs = []
            for t in q.get("tables", []):
                if t["page"] == n:
                    # 跨页续表照样是障碍物（不能把表里的数字当正文转写），
                    # 但不出占位符——它会并进上半张，题干里只该有一个记号。
                    obs.append((t["box"]["y0"], t["box"]["y1"],
                                None if t.get("cont_of") else "〔表%d〕" % t["id"]))
            for f in q.get("fig_marks", []):
                if f["page"] == n and f.get("box"):
                    obs.append((f["box"]["y0"], f["box"]["y1"], "〔图%d〕" % f["id"]))
            obs.sort(key=lambda o: -o[1])

            bx0 = min(s2["x"] for s2 in band) - 5
            bx1 = max(s2.get("x1", s2["x"] + bs) for s2 in band) + 5
            top = max(s2["y"] + s2.get("size", bs) for s2 in band) + bs * 0.4
            bot = min(s2["y"] for s2 in band) - bs * 0.5

            bigp = (big if n == pno else
                    render_page(pdf, n, os.path.join(tmp_dir, "p%02d.png" % n)))
            if not bigp:
                continue

            seq, cursor, k = [], top, 0
            for oy0, oy1, mark in obs + [(bot, bot, None)]:
                if cursor - oy1 > bs * 0.6:        # 障碍物之上还有文字
                    seq.append(("text", oy1, cursor))
                if mark:
                    seq.append(("mark", mark, None))
                cursor = min(cursor, oy0)

            for kind, aa, bb in seq:
                if kind == "mark":
                    parts.append(" " + aa + " ")
                    continue
                k += 1
                inner = [s2 for s2 in band if aa <= s2["y"] <= bb]
                # 整块都不是正文就别转写。页脚「5 / 9」拆出来的碎块会落在
                # 表格下方自成一块，转写出来就是题干里凭空多出一个 `5/9`。
                if not any(segment.is_body(s2) for s2 in inner):
                    continue
                if not need_stem and not any(
                        aa <= r["y"] <= bb and bx0 <= r["x"] <= bx1
                        for r in pg.get("rules", [])):
                    # 这一块没有二维结构，几何抽取就够了，省一次调用。
                    # 拼接不能加空格：文本块自带该有的前导空白，
                    # 而中文常常一字一块，`" ".join` 会拼出「如 图 所 示」。
                    parts.append("".join(s2["text"] for s2 in inner))
                    continue
                try:
                    sd, sc, spath = run_block_on(bigp, pg["height"],
                                                 (bx0, aa - bs * 0.4, bx1, bb + bs * 0.3),
                                                 "s%db%d" % (n, k), FRAG_PROMPT)
                    hit += sc
                    miss += (not sc)
                    txt = (sd.get("stem") or "").strip()
                    src = cjk_only("".join(s2["text"] for s2 in inner))
                    got = cjk_only(txt)
                    if src and len(got) < len(src) * 0.8:
                        blocks_bad.append("p%d 第%d块只转写了 %.0f%%"
                                          % (n, k, len(got) / len(src) * 100))
                    if txt:
                        parts.append(txt)
                    simg = simg or "mathimg/q%02ds%db%d.png" % (q["n"], n, k)
                except Exception as e:
                    print("   ✗ 第%d题 p%d块%d %s" % (q["n"], n, k, e))
                    parts.append("".join(s2["text"] for s2 in inner))

        if parts:
            new = " ".join(x for x in parts if x).strip()
            # 题号是可选的：题型标记那一行有时不带阿拉伯数字，
            # 只写「单选题（4分）」，用 \d+ 就剥不掉，会留在题干开头。
            new = re.sub(r"^\s*\d*\s*(单选题|多选题|填空题|实验题|计算题|解答题|"
                         r"作图题|论述题|综合题)\s*[（(]?\s*\d*\s*分?\s*[)）]?\s*", "", new)
            a1, a2 = cjk_only(new), cjk_only(q["stem"])
            same = len(set(a1) & set(a2)) / max(1, len(set(a2)))
            ratio = len(a1) / max(1, len(a2))
            for kk in ("stem_latex", "stem_vlm_rejected", "stem_low_conf"):
                q.pop(kk, None)
            q["stem_latex"] = new
            if blocks_bad:
                q["stem_low_conf"] = "有块转写不全（%s），请对照原卷核对" % "；".join(blocks_bad)
            elif ratio < 0.85:
                q["stem_low_conf"] = ("转写只有原抽取的 %.0f%% 长，可能漏抄，"
                                      "请对照原卷核对" % (ratio * 100))
            elif same < 0.75:
                q["stem_low_conf"] = "与原抽取的中文重合度 %.0f%%，请对照原卷核对" % (same * 100)
            q["stem_image"] = simg

        # ---- 表格 ----
        for t in q.get("tables", []):
            if t["page"] != pno:
                bigp = render_page(pdf, t["page"],
                                   os.path.join(tmp_dir, "p%02d.png" % t["page"]))
                ph = pages[t["page"]]["height"]
            else:
                bigp, ph = big, page["height"]
            if not bigp:
                continue
            b = t["box"]
            dst = os.path.join(img_dir, "q%02dt%d.png" % (q["n"], t["id"]))
            crop(bigp, (b["x0"], b["y0"], b["x1"], b["y1"]), ph, dst)
            hh = hashlib.sha256(open(dst, "rb").read()).hexdigest()[:16]
            cp = os.path.join(cache_dir, hh + ".json")
            try:
                if os.path.exists(cp) and not a.force:
                    td = json.load(open(cp, encoding="utf-8"))
                    hit += 1
                else:
                    td = ask_model(dst, TABLE_PROMPT)
                    json.dump(td, open(cp, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
                    miss += 1
                t["caption"] = td.get("caption", "")
                t["rows"] = td.get("rows", [])
                t["image"] = "mathimg/q%02dt%d.png" % (q["n"], t["id"])
            except Exception as e:
                print("   ✗ 第%d题 表%d %s" % (q["n"], t["id"], e))

        # 表名会同时落到两处：它在表框之内（VLM 转写进 caption），
        # 而上一块的裁图为了不切掉字的下沿又向下多留了半个字高，把它一起带进了题干。
        # 以 caption 为准，删掉题干里紧挨占位符的那一份。
        for t in q.get("tables", []):
            cap = (t.get("caption") or "").strip()
            if cap and q.get("stem_latex"):
                q["stem_latex"] = re.sub(
                    r"\s*%s\s*(〔表%d〕)" % (re.escape(cap), t["id"]),
                    r" \1", q["stem_latex"])

        for w in segment.merge_warnings(q.get("tables", [])):
            print("   ✗ 第%d题 %s" % (q["n"], w))

        done += 1
        print("   第%2d题 %s%s%s  %s" % (
            q["n"], "缓存" if cached else "识别",
            " +题干" if q.get("stem_latex") else "",
            " +表%d" % len(q["tables"]) if q.get("tables") else "",
            " | ".join("%s:%s" % (k, v[:22]) for k, v in sorted(by.items()))))

    if a.dry_run:
        print("── 试算 %s" % a.workdir)
        print("   %d 题要处理，缓存命中 %d 次，还需调用模型 %d 次" % (done, hit, len(need)))
        return

    json.dump(qs, open(os.path.join(a.workdir, "questions.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("── 公式识别 %s" % a.workdir)
    print("   处理 %d 题（缓存 %d / 新识别 %d），跳过 %d，失败 %d"
          % (done, hit, miss, skip, fail))


if __name__ == "__main__":
    main()
