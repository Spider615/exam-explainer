#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assemble.py —— 阶段⑦ 装配成页

    python assemble.py <卷名> -o out.html [--scenes runs]

输入
----
库                            阶段② 的产物（必需，`store.publish` 之后才有）
work/<name>/explain.json      阶段③④ 的产物（可选，暂缺时整页只有原题）
runs/<id>/<id>.figure.html    阶段⑤ 通过门禁的场景（可选，按 bind.json 绑定）

产出一个**自包含**的 HTML：插图 base64 内嵌、无外链、无 webfont、
公式已在服务端渲染好（页面不跑 JS 也能看），可以直接丢进 CDN 或作为 Artifact 发布。

和 Web 应用是同一份数据
----------------------
读库，不读 `work/<卷名>/questions.json`。两条渲染路径读不同的东西，
迟早会各说各话 —— 这份页面曾经把 `〔表1〕` 原样打印出来，
而同一时刻 Web 上表格渲染得好好的。

题干里的 `〔图N〕`/`〔表N〕` 占位符要就地换回真正的图和表；
有视觉模型转写的题干（`stem_latex`，含 `$...$` 行内公式）就优先用它。

原则
----
- 纯代码，无模型调用。
- **有什么装什么**：没有讲解就只出原题，没有动画就退回原始插图。
  绝不为了页面好看而编内容——缺失必须在页面上显式可见。
"""
import argparse, base64, html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import segment          # 跨页表的合并规则只写一份
import store            # 和 Web 读同一份数据

KATEX = os.path.join(ROOT, "web", "node_modules", "katex")

CSS = """
:root{
  --paper:#F2F4F7; --panel:#FFF; --stem:#FAFBFC;
  --ink:#15191F; --ink2:#5A6472; --ink3:#8A94A3;
  --line:#C9D2DE; --hair:#E4E9F0;
  --acc:#2B5490; --acc2:#E9EFF8;
  --cy:#0C8CAE; --cy2:#E2F2F6;
  --red:#AE3B2B; --red2:#FBEBE7;
  --cjk:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
  --math:"Times New Roman",Georgia,serif;
  --song:"Songti SC",SimSun,serif;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#12151A; --panel:#191D24; --stem:#1D222A;
  --ink:#E7EAEF; --ink2:#9BA5B4; --ink3:#6E7887;
  --line:#333B47; --hair:#252B34;
  --acc:#82A9E4; --acc2:#1B2532; --cy:#46C0D8; --cy2:#132630;
  --red:#EC806B; --red2:#2E1D19;
}}
:root[data-theme=dark]{
  --paper:#12151A; --panel:#191D24; --stem:#1D222A;
  --ink:#E7EAEF; --ink2:#9BA5B4; --ink3:#6E7887;
  --line:#333B47; --hair:#252B34;
  --acc:#82A9E4; --acc2:#1B2532; --cy:#46C0D8; --cy2:#132630;
  --red:#EC806B; --red2:#2E1D19;
}
:root[data-theme=light]{
  --paper:#F2F4F7; --panel:#FFF; --stem:#FAFBFC;
  --ink:#15191F; --ink2:#5A6472; --ink3:#8A94A3;
  --line:#C9D2DE; --hair:#E4E9F0;
  --acc:#2B5490; --acc2:#E9EFF8; --cy:#0C8CAE; --cy2:#E2F2F6;
  --red:#AE3B2B; --red2:#FBEBE7;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--cjk);
     font-size:15px;line-height:1.7;-webkit-text-size-adjust:100%}
.wrap{max-width:940px;margin:0 auto;padding:0 20px 60px}
.masthead{border-bottom:2px solid var(--ink);padding:34px 0 14px;margin-bottom:8px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.22em;
         text-transform:uppercase;color:var(--acc);margin:0 0 10px}
h1{font-family:var(--song);font-size:30px;line-height:1.25;margin:0;
   text-wrap:balance;font-weight:600}
.sub{color:var(--ink2);margin:10px 0 0;max-width:60ch;font-size:14px}
.facts{display:flex;flex-wrap:wrap;gap:26px;margin:18px 0 0;padding:14px 0 0;
       border-top:1px solid var(--hair)}
.fact b{display:block;font-family:var(--mono);font-size:19px;
        font-variant-numeric:tabular-nums;color:var(--ink)}
.fact span{font-size:11px;letter-spacing:.1em;color:var(--ink3)}
.note{background:var(--acc2);border-left:3px solid var(--acc);padding:11px 14px;
      margin:22px 0 0;font-size:13.5px;color:var(--ink2);border-radius:0 3px 3px 0}
.note b{color:var(--acc)}
.sec{margin:38px 0 16px;display:flex;align-items:baseline;gap:12px;
     border-bottom:1px solid var(--ink);padding-bottom:7px}
.sec h2{font-family:var(--song);font-size:19px;margin:0;font-weight:600}
.sec span{font-size:12px;color:var(--ink3);font-family:var(--mono)}
.q{background:var(--panel);border:1px solid var(--line);border-radius:4px;
   margin-bottom:20px;overflow:hidden}
.qhd{display:flex;align-items:center;gap:10px;padding:12px 16px;
     border-bottom:1px solid var(--hair);flex-wrap:wrap}
.qnum{font-family:var(--mono);font-size:21px;font-weight:600;color:var(--acc);
      font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.chip{font-size:11px;padding:2px 8px;border-radius:2px;border:1px solid var(--line);
      color:var(--ink2);letter-spacing:.06em;white-space:nowrap}
.chip.t{border-color:var(--acc);color:var(--acc);background:var(--acc2)}
.chip.w{border-color:var(--red);color:var(--red);background:var(--red2)}
.chip.g{border-color:var(--cy);color:var(--cy);background:var(--cy2)}
.qbd{padding:14px 16px 16px}
.stem{font-family:var(--song);font-size:15.5px;line-height:1.95;background:var(--stem);
      border:1px solid var(--hair);border-left:3px solid var(--line);
      padding:13px 15px;border-radius:0 3px 3px 0;margin:0 0 14px}
.opts{list-style:none;margin:0 0 14px;padding:0;display:grid;gap:6px}
.opts li{display:flex;gap:9px;align-items:flex-start;font-size:14.5px}
.opts em{font-style:normal;font-family:var(--mono);color:var(--acc);font-weight:600}
.opts img{max-width:200px;height:auto;border:1px solid var(--hair);border-radius:3px;
          background:#fff}
figure{margin:0 0 14px;border:1px solid var(--hair);border-radius:3px;overflow:hidden;
       background:var(--panel)}
figure img{display:block;width:100%;height:auto;background:#fff;margin:0 auto}
figure svg{display:block;width:100%;height:auto}
figcaption{font-size:11.5px;color:var(--ink3);padding:6px 12px;
           border-top:1px solid var(--hair);letter-spacing:.04em}
.lbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;
     color:var(--ink3);margin:18px 0 8px;font-weight:600}
.missing{border:1px dashed var(--line);border-radius:3px;padding:14px;
         color:var(--ink3);font-size:13px;text-align:center;background:var(--stem)}
.missing b{color:var(--ink2)}
.warn{background:var(--red2);border-left:3px solid var(--red);padding:9px 13px;
      margin:0 0 14px;font-size:13px;color:var(--red);border-radius:0 3px 3px 0}
/* 题干里就地插回的图与表。〔图N〕〔表N〕 占位符替换到这里 */
.inlinefig{margin:12px auto;border:none;background:none}
.inlinefig img{border:1px solid var(--hair);border-radius:3px}
.qtable{margin:12px 0;border:1px solid var(--hair);border-radius:3px;overflow:hidden}
.qtable-cap{border-top:none;border-bottom:1px solid var(--hair);text-align:center;
            font-family:var(--cjk);color:var(--ink2)}
.qtable-scroll{overflow-x:auto}
.qtable table{border-collapse:collapse;width:100%;font-size:13.5px}
.qtable th,.qtable td{border:1px solid var(--hair);padding:6px 10px;text-align:center;
                      white-space:nowrap}
.qtable th{background:var(--stem);font-weight:600;color:var(--ink2)}
.tbl-missing{font-family:var(--mono);font-size:12px;color:var(--red);
             background:var(--red2);padding:1px 5px;border-radius:2px}
details.raw{margin:8px 0 0;font-size:12px;color:var(--ink3)}
details.raw summary{cursor:pointer;font-family:var(--mono);font-size:11px;
                    letter-spacing:.08em}
details.raw img{display:block;max-width:100%;margin:8px 0 0;border:1px solid var(--hair);
                border-radius:3px;background:#fff}
/* 模型解法。可信度标记必须和结论同框，不能折叠 —— 讲解最擅长掩盖错误 */
.sol{border:1px solid var(--line);border-radius:4px;padding:12px 14px;background:var(--stem)}
.sol-hd{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:0 0 11px}
.sol-ans{display:flex;gap:10px;align-items:baseline;margin:0 0 11px;padding:8px 11px;
         background:var(--panel);border-left:3px solid var(--acc);border-radius:0 3px 3px 0}
.sol-ans-lbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;
             color:var(--ink3);flex:none}
.sol-steps{margin:0;padding-left:1.35em;font-size:14px;line-height:1.9;color:var(--ink2)}
.sol-steps li{margin:0 0 5px}
.sol-asm{margin:13px 0 0;padding:10px 12px;border:1px dashed var(--line);border-radius:3px;
         font-size:13px;color:var(--ink2)}
.sol-asm b{display:block;font-size:11.5px;letter-spacing:.06em;color:var(--red);margin:0 0 6px}
.sol-asm ul{margin:0;padding-left:1.2em;line-height:1.75}
.sol-asm p{margin:8px 0 0;font-size:12px;color:var(--ink3)}
/* 版面解析器生成的 MathML（没过视觉模型的题走这条）。
   浏览器原生支持，不需要引任何库 —— 和 Web 前端保持同一套样式 */
.mathml{display:inline-block;vertical-align:middle;margin:0 .15em}
.mathml math{font-family:var(--math);font-size:1.05em;math-style:normal;font-style:italic}
.mathml mn,.mathml mo{font-style:normal}
.stem:has(.mathml){line-height:2.35}   /* 行内出现分式后要给行距留出高度 */
.opts li:has(.mathml){align-items:center;line-height:2.1}
/* KaTeX 渲染失败时不静默吞掉 —— 原样显示 LaTeX，看得见才改得动 */
.texfail{font-family:var(--mono);font-size:12.5px;color:var(--red);background:var(--red2);
         padding:0 4px;border-radius:2px}
.katex{font-size:1.02em}
svg text{font-family:var(--math);font-size:13px;fill:var(--ink);font-style:italic}
svg text.u{font-family:var(--cjk);font-style:normal;font-size:11.5px;fill:var(--ink2)}
svg text.n{font-family:var(--mono);font-style:normal;font-size:11px;fill:var(--ink2)}
svg text.a{fill:var(--acc)}svg text.r{fill:var(--red)}svg text.c{fill:var(--cy)}
.sk{stroke:var(--ink);fill:none;stroke-width:1.6;stroke-linejoin:round;stroke-linecap:round}
.sh{stroke:var(--line);fill:none;stroke-width:1}
.sa{stroke:var(--acc);fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.sr{stroke:var(--red);fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.sc{stroke:var(--cy);fill:none;stroke-width:1.5;stroke-dasharray:5 4}
.fk{fill:var(--ink)}.fa{fill:var(--acc)}.fr{fill:var(--red)}.fc{fill:var(--cy)}
.wash-a{fill:var(--acc);opacity:.13}.wash-r{fill:var(--red);opacity:.14}
.wash-c{fill:var(--cy);opacity:.16}
.ctlbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:7px 12px;
        border-top:1px solid var(--hair)}
.ctl{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11.5px;color:var(--ink2)}
.btn{font-family:var(--cjk);font-size:11.5px;line-height:1;padding:5px 10px;border-radius:3px;
     border:1px solid var(--line);background:var(--panel);color:var(--ink2);cursor:pointer}
.btn:hover{border-color:var(--acc);color:var(--acc)}
.btn:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.btn[aria-pressed=true]{border-color:var(--acc);color:var(--acc);background:var(--acc2)}
.livebadge{font-family:var(--mono);font-size:10px;letter-spacing:.18em;color:var(--red)}
input[type=range]{width:118px}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);
       font-size:12px;color:var(--ink3)}
@media (max-width:640px){.wrap{padding:0 14px 40px}h1{font-size:23px}}
"""

DEFS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<marker id="ak" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--ink)"/></marker>
<marker id="aa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--acc)"/></marker>
<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--red)"/></marker>
<marker id="ac" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--cy)"/></marker>
</defs></svg>"""


_IMG_CACHE = {}


def datauri(raw, maxw=1100, tag=""):
    """
    内嵌图片。原卷线稿常有 2600px 宽，直接 base64 会把页面撑到几 MB。
    这里降采样到可读上限并做调色板量化——线稿只有黑白灰，256 色足够，
    体积能降一个量级而肉眼无损。
    """
    key = (hash(raw), maxw)
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    out = raw
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        if im.width > maxw:
            im = im.resize((maxw, max(1, round(im.height * maxw / im.width))),
                           Image.LANCZOS)
        if im.mode not in ("P", "L"):
            im = im.convert("RGB").quantize(colors=64, method=Image.MEDIANCUT)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        if buf.tell() < len(raw):
            out = buf.getvalue()
    except Exception as e:
        print("   [warn] 压缩 %s 失败，用原图：%s" % (tag, e))
    uri = "data:image/png;base64," + base64.b64encode(out).decode()
    _IMG_CACHE[key] = uri
    return uri


def esc(s):
    return html.escape(s or "")


# ---------------------------------------------------------------- 公式
def render_tex(items):
    """
    把一批 LaTeX 片段交给 KaTeX **在服务端**渲染成 HTML。

    不把 katex.min.js 塞进页面：那样页面得跑 JS 才看得到公式，
    而这份产物的用途之一是丢进 CDN 当静态页。服务端渲染完只需要嵌 CSS 和字体。

    渲染失败**不静默吞掉** —— 返回 None，调用方原样显示 LaTeX 源码。
    内容来自视觉模型对截图的识别，看得见才改得动。
    """
    if not items:
        return {}
    if not os.path.isdir(KATEX):
        print("   [warn] 找不到 %s（cd web && npm install），公式将以源码显示" % KATEX)
        return {}
    script = """
const katex = require(process.argv[1]);
const src = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {};
for (const t of src) {
  try { out[t] = katex.renderToString(t, {throwOnError:false, strict:false,
                                          displayMode:false, output:'html'}); }
  catch (e) { out[t] = null; }
}
process.stdout.write(JSON.stringify(out));
"""
    uniq = sorted(set(items))
    try:
        r = subprocess.run(["node", "-e", script, KATEX],
                           input=json.dumps(uniq), capture_output=True,
                           text=True, timeout=120)
        if r.returncode != 0:
            print("   [warn] KaTeX 渲染失败，公式将以源码显示：%s" % (r.stderr or "")[-160:])
            return {}
        return {k: v for k, v in json.loads(r.stdout).items() if v}
    except Exception as e:
        print("   [warn] 调不起 node，公式将以源码显示：%s" % e)
        return {}


def katex_css():
    """
    katex.min.css，字体换成 data URI。

    只嵌 woff2 并**删掉 woff/ttf 回退** —— 留着就是外链，而这份页面
    要求无外链；何况 woff2 是 2016 年以后所有浏览器都认的格式。
    20 个 woff2 合计 296 KB，相对整页几 MB 的插图可以接受。
    """
    p = os.path.join(KATEX, "dist", "katex.min.css")
    if not os.path.exists(p):
        return ""
    css = open(p, encoding="utf-8").read()
    used = set()

    def sub(m):
        fn = m.group(1)
        fp = os.path.join(KATEX, "dist", "fonts", fn)
        if not os.path.exists(fp):
            return m.group(0)
        used.add(fn)
        b = base64.b64encode(open(fp, "rb").read()).decode()
        return "url(data:font/woff2;base64,%s) format(\"woff2\")" % b

    css = re.sub(r"url\(fonts/([\w.-]+\.woff2)\)\s*format\(\"woff2\"\)", sub, css)
    # 干掉剩下的 woff/ttf 外链引用
    css = re.sub(r",\s*url\(fonts/[\w.-]+\.(?:woff|ttf)\)\s*format\(\"(?:woff|truetype)\"\)",
                 "", css)
    return css


TEX = re.compile(r"\$([^$]+)\$")


def tex_spans(t):
    """题干/单元格里的 `$...$` 片段。"""
    return TEX.findall(t or "")


def with_math(t, tex):
    """把 `$...$` 换成渲染好的 HTML，其余部分转义。"""
    out, last = [], 0
    for m in TEX.finditer(t or ""):
        out.append(esc(t[last:m.start()]))
        s = m.group(1)
        out.append(tex.get(s) or '<code class="texfail">%s</code>' % esc(s))
        last = m.end()
    out.append(esc((t or "")[last:]))
    return "".join(out).replace("\n", "<br>")


def with_mathml(t, segs):
    """
    没过视觉模型的题走这条路：把版面解析器生成的 MathML 按 `[s, e)` 字符区间贴回原文。

    不用它的话，`E_(k1)>E_(k2)` 这种兜底写法会原样印在页面上 ——
    而同一道题在 Web 上是渲染好的。两个渲染器读同一份数据却给出不同结果，
    正是这次「收编」要消灭的东西。

    MathML 是代码生成的（不是模型写的、也不是用户输入），只含
    mfrac/msqrt/msup/msub/mi/mn/mo，内容已转义，可以直接插进页面。
    """
    t = t or ""
    if not segs:
        return esc(t).replace("\n", "<br>")
    out, cur = [], 0
    for m in sorted(segs, key=lambda x: x["s"]):
        if m["s"] < cur:
            continue                      # 区间重叠，跳过后来的
        if m["s"] > cur:
            out.append(esc(t[cur:m["s"]]))
        out.append('<span class="mathml">%s</span>' % m["mathml"])
        cur = m["e"]
    out.append(esc(t[cur:]))
    return "".join(out).replace("\n", "<br>")


PLACEHOLDER = re.compile(r"(〔[图表]\d+〕)")


def table_html(t, tex, asset):
    """一张表。首行当表头。跨页表已在 merged_tables 里拼成一张。"""
    out = ['<figure class="qtable">']
    if t.get("caption"):
        out.append('<figcaption class="qtable-cap">%s</figcaption>' % esc(t["caption"]))
    out.append('<div class="qtable-scroll"><table><tbody>')
    for i, row in enumerate(t.get("rows") or []):
        cell = "th" if i == 0 else "td"
        out.append("<tr>%s</tr>" % "".join(
            "<%s>%s</%s>" % (cell, with_math(c, tex), cell) for c in row))
    out.append("</tbody></table></div>")
    # 「对照原卷」：模型也会错，错了必须能被看见。跨页表有两张原图，都要给
    imgs = [asset(i) for i in (t.get("images") or [])]
    imgs = [x for x in imgs if x]
    if imgs:
        out.append('<details class="raw"><summary>对照原卷表格</summary>%s</details>'
                   % "".join('<img src="%s" alt="原卷表格">' % datauri(b, 900, "table")
                             for b in imgs))
    out.append("</figure>")
    return "".join(out)


def rich_html(body, q, tex, asset, geo, col_w, use_tex=False, segs=None, maxw=1100):
    """
    一段夹带图、表、公式的正文。

    `〔图N〕`/`〔表N〕` 换成真正的图和表；`$...$` 用 KaTeX 渲染好的结果；
    没过视觉模型的走 MathML。**占位符找不到对应的图/表时原样显示并标红**，
    不能悄悄抹掉 —— 抹掉之后页面看起来完好，实际少了一张图。

    题干和选项都要走这里：占位符不只出现在题干里，「选项本身就是图片」
    那类题（实测浙江、江苏、广东等 7 卷）的占位符落在选项文本中，
    只处理题干的话它们会以 `〔图8〕` 四个字原样印在页面上。
    """
    # MathML 的 [s, e) 是按整段正文算的，而下面要按占位符把正文切开，
    # 所以得一路记着偏移量，把落在本块里的区间重新对齐到块内坐标
    segs = segs or []
    figs = {f["id"]: f for f in (q.get("fig_marks") or [])}
    tabs = {t["id"]: t for t in segment.merged_tables(q.get("tables") or [])}
    out, pos = [], 0
    for chunk in PLACEHOLDER.split(body or ""):
        start, pos = pos, pos + len(chunk)   # 无论走哪个分支，偏移都得往前走
        m = re.fullmatch(r"〔图(\d+)〕", chunk)
        if m:
            f = figs.get(int(m.group(1)))
            raw = asset(f["file"]) if f else None
            if not raw:
                out.append('<span class="tbl-missing">%s</span>' % esc(chunk))
                continue
            w = geo.get(f["file"], (col_w, 0))[0]
            pct = max(18.0, min(100.0, w / col_w * 100.0))
            out.append('<figure class="inlinefig"><img style="width:%.0f%%" src="%s" '
                       'alt="第%d题插图"></figure>'
                       % (pct, datauri(raw, maxw, f["file"]), q["n"]))
            continue
        m = re.fullmatch(r"〔表(\d+)〕", chunk)
        if m:
            t = tabs.get(int(m.group(1)))
            # 跨页续表的占位符不该出现在题干里；真出现了要看得见
            out.append(table_html(t, tex, asset) if t and t.get("rows")
                       else '<span class="tbl-missing">%s</span>' % esc(chunk))
            continue
        if not chunk:
            continue
        if use_tex:
            out.append(with_math(chunk, tex))
        else:
            local = [{"s": s["s"] - start, "e": s["e"] - start, "mathml": s["mathml"]}
                     for s in segs if start <= s["s"] and s["e"] <= pos]
            out.append(with_mathml(chunk, local))
    return "".join(out)


CONF = {"high": ("模型自评 高", "chip"),
        "medium": ("模型自评 中 · 建议核对", "chip w"),
        "low": ("模型自评 低 · 需人工复核", "chip w")}


def solution_html(s, tex):
    """
    一段模型给出的解法。

    重点不是把讲解排得好看，而是**让读者知道这段东西有多可信**。
    可视化和讲解最擅长掩盖错误：一段条理清晰的推导讲错了，读者会信。
    所以三样必须和结论同框，不折叠、不省略：它是模型生成的、模型的置信度、
    以及它自己补上的题面没给的前提。

    最后一条尤其关键 —— 阶段④ 的物理断言就架在这些假设上。假设错了，
    断言会「错得自洽」，门禁全绿而物理是错的。读者看得见假设才有机会发现。
    """
    if not s:
        return ('<div class="missing"><b>尚未生成</b><br>'
                '这道题还没跑过阶段③（解题）。</div>')
    lab, cls = CONF.get(s.get("confidence"), CONF["low"])
    n_inv = s.get("n_invariants") or 0
    chips = ['<span class="chip t">模型生成 · 未经人审</span>',
             '<span class="%s">%s</span>' % (cls, lab),
             '<span class="chip">%s</span>' % (
                 ("%d 条物理断言%s" % (n_inv, " · 断言本身待人审"
                                    if s.get("spec_status") == "draft" else ""))
                 if n_inv else "无断言 · 未被检验")]
    if s.get("scene_passed"):
        chips.append('<span class="chip g">动画 · 已过门禁（%d 轮）</span>'
                     % (s.get("scene_rounds") or 0))
    if s.get("animatable") is False:
        chips.append('<span class="chip" title="%s">不适合做动画</span>'
                     % esc(s.get("why_not") or ""))
    out = ['<div class="sol"><div class="sol-hd">%s</div>' % "".join(chips)]
    if s.get("answer"):
        out.append('<div class="sol-ans"><span class="sol-ans-lbl">答案</span>'
                   '<span>%s</span></div>' % with_math(s["answer"], tex))
    out.append('<ol class="sol-steps">%s</ol>'
               % "".join("<li>%s</li>" % with_math(x, tex) for x in (s.get("steps") or [])))
    if s.get("assumptions"):
        out.append('<div class="sol-asm"><b>解题时自行补充的前提（题面未给出）</b><ul>%s</ul>'
                   '<p>这些不是题目条件，是模型自己补的。结论正确与否取决于它们成不成立。</p></div>'
                   % "".join("<li>%s</li>" % with_math(x, tex) for x in s["assumptions"]))
    out.append("</div>")
    return "".join(out)


def stem_html(q, tex, asset, geo, col_w):
    """题干。有 `stem_latex`（视觉模型逐块转写版）就用它，否则退回几何抽取的 `stem`。"""
    use_tex = bool(q.get("stem_latex"))
    return rich_html(q.get("stem_latex") or q.get("stem") or "", q, tex, asset,
                     geo, col_w, use_tex=use_tex,
                     segs=None if use_tex else q.get("stem_math"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper", help="卷名（也接受 work/<卷名> 这样的路径，取其末段）")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--scenes", default=os.path.join(ROOT, "runs"),
                    help="通过门禁的场景目录，按 bind.json 绑定")
    ap.add_argument("--title", default=None)
    a = ap.parse_args()

    name = os.path.basename(os.path.normpath(a.paper))
    qs = store.get_paper(name)
    if not qs:
        print("库里没有「%s」。先跑 store.publish —— work/<卷名>/ 只是构建产物，"
              "没发布就不算数。" % name)
        return 1
    workdir = os.path.join(ROOT, "work", name)

    def asset(rel):
        """按卷内相对路径取资产字节。存本地还是存 MinIO 由 store 决定。"""
        row = store.find_asset(name, rel)
        return store.read_asset(row, name) if row else None

    # 原卷里每张图的版面宽度：用来还原它在纸上的相对大小，
    # 否则一张 75pt 宽的竖长图会被铺成整屏。doc.json 是构建产物、不入库，
    # 取不到就按满宽渲染。
    geo, col_w = {}, 476.0
    dj = os.path.join(workdir, "doc.json")
    if os.path.exists(dj):
        _doc = json.load(open(dj, encoding="utf-8"))
        for _p in _doc["pages"]:
            for _im in _p["images"]:
                if _im.get("w"):
                    geo[_im["file"]] = (_im["w"], _im["h"])
    # 解法从库里来。以前读 work/<卷名>/explain.json —— 那个文件从来没被生成过，
    # 于是页面上 359 题的「解题思路」全是「尚未生成」，而阶段③ 的结果就躺在库里
    explain = store.paper_solutions(name)

    # --- 收集可用场景 ---
    #
    # ⚠ 题号不是全局唯一键。第一版按 q<N> 裸匹配，结果把福建卷的「斜面测μ」
    # 动画挂到了重庆卷第12题（变压器实验）上——场景本身通过了全部门禁，
    # 只是被绑错了题。这是本产品最危险的一类错误：一段看起来经过验证的动画，
    # 配在完全不相干的题目上，读者反而更容易信。
    #
    # 所以改成 fail-closed：场景目录必须有 bind.json 声明它属于哪份卷子的第几题，
    # 卷子 id 对不上就拒绝装配，并且在页面上显式报告被拒了多少个。
    paper_id = name
    scenes, scene_js, rejected = {}, [], []

    # 先取库里 `scenes` 表登记的 —— 阶段⑤ 的产出。绑定是 question_id，天然精确，
    # 不需要 bind.json；`passed` 是门禁的裁决。只扫文件系统的话，
    # ⑤ 产出的场景（目录名带 -genN、也不写 bind.json）永远不会出现在页面上。
    for n, sid in store.paper_scenes(name).items():
        sd = os.path.join(a.scenes, sid)
        fp, jp = os.path.join(sd, sid + ".figure.html"), os.path.join(sd, sid + ".js")
        if os.path.exists(fp) and os.path.exists(jp):
            scenes[n] = open(fp, encoding="utf-8").read()
            scene_js.append(open(jp, encoding="utf-8").read())

    if os.path.isdir(a.scenes):
        for d in sorted(os.listdir(a.scenes)):
            m = re.fullmatch(r"q(\d+)", d)
            if not m:
                continue
            sd = os.path.join(a.scenes, d)
            fp, jp = os.path.join(sd, d + ".figure.html"), os.path.join(sd, d + ".js")
            bp = os.path.join(sd, "bind.json")
            if not (os.path.exists(fp) and os.path.exists(jp)):
                continue
            if not os.path.exists(bp):
                rejected.append("%s 没有 bind.json，无法确认它属于哪份卷子" % d)
                continue
            bind = json.load(open(bp, encoding="utf-8"))
            if bind.get("paper") != paper_id:
                rejected.append("%s 属于「%s」，不是本卷「%s」"
                                % (d, bind.get("paper"), paper_id))
                continue
            n = int(bind.get("n", m.group(1)))
            tgt = next((x for x in qs["questions"] if x["n"] == n), None)
            if tgt is None:
                rejected.append("%s 声明绑第%d题，但本卷没有这一题" % (d, n))
                continue
            # 内容层面的软校验：题干开头对不上就不装，宁可少一个动画
            ex = re.sub(r"\s", "", bind.get("stem_excerpt", ""))[:16]
            if ex and ex not in re.sub(r"\s", "", tgt["stem"]):
                rejected.append("%s 声明绑第%d题，但题干开头对不上（可能卷子改版了）" % (d, n))
                continue
            scenes[n] = open(fp, encoding="utf-8").read()
            scene_js.append(open(jp, encoding="utf-8").read())

    runtime = open(os.path.join(ROOT, "harness", "_runtime.js"), encoding="utf-8").read()

    title = a.title or name
    n_fig = sum(len(q["figures"]) + len(q.get("option_figures") or [])
                for q in qs["questions"])

    # 一次性把整卷的 LaTeX 交给 KaTeX：node 起一次就够，别每条公式起一个进程
    want = []
    for q in qs["questions"]:
        want += tex_spans(q.get("stem_latex"))
        for o in q["options"]:
            want += tex_spans(o.get("latex") and "$%s$" % o["latex"] or "")
        for t in segment.merged_tables(q.get("tables") or []):
            for row in t.get("rows") or []:
                for cell in row:
                    want += tex_spans(cell)
        s = explain.get(q["n"])
        if s:
            for x in [s.get("answer") or ""] + (s.get("steps") or []) \
                     + (s.get("assumptions") or []):
                want += tex_spans(x)
    tex = render_tex(want)
    n_tex_bad = len(set(want)) - len(tex)

    body = []
    cur_sec = None
    for q in qs["questions"]:
        if q["section"] != cur_sec:
            cur_sec = q["section"]
            if cur_sec:
                lab, _, tt = cur_sec.partition("、")
                cnt = sum(1 for x in qs["questions"] if x["section"] == cur_sec)
                body.append('<div class="sec"><h2>%s、%s</h2><span>%d 题</span></div>'
                            % (esc(lab), esc(tt), cnt))

        # 分值不是每张卷子都标（实验题常常只在大题标题里写总分），没有就不显示
        chips = ['<span class="chip t">%s</span>' % esc(q["type"])]
        if q.get("points"):
            chips.append('<span class="chip">%d 分</span>' % q["points"])
        if q["n"] in scenes:
            chips.append('<span class="chip g">动画 · 已过门禁</span>')
        if q["text_quality"] == "degraded":
            chips.append('<span class="chip w">文字层不可用</span>')
        body.append('<article class="q" id="q%d"><div class="qhd">'
                    '<span class="qnum">%02d</span>%s</div><div class="qbd">'
                    % (q["n"], q["n"], "".join(chips)))

        if q["text_quality"] == "degraded":
            body.append('<div class="warn">这道题的文字层%s，'
                        '下面的题干与选项可能有信息丢失，请以原卷图片为准。</div>'
                        % esc(q["quality_reason"]))

        body.append('<div class="stem">%s</div>' % stem_html(q, tex, asset, geo, col_w))

        # 场景优先，退回原图。
        # 题干里已经按 〔图N〕 就地插过的图不再重复放一遍 —— 以前没有占位符，
        # 只能把整题的图统统堆在题干后面。
        placed = {f["file"] for f in (q.get("fig_marks") or [])} \
            if q.get("stem_latex") or "〔图" in (q.get("stem") or "") else set()
        if q["n"] in scenes:
            body.append(scenes[q["n"]])
        else:
            for f in q["figures"]:
                if f in placed:
                    continue
                raw = asset(f)
                if raw:
                    w = geo.get(f, (col_w, 0))[0]
                    pct = max(18.0, min(100.0, w / col_w * 100.0))
                    body.append('<figure><img style="width:%.0f%%" src="%s" alt="第%d题插图"></figure>'
                                % (pct, datauri(raw, 1100, f), q["n"]))

        if q["options"]:
            body.append('<ul class="opts">')
            for o in q["options"]:
                # 阶段②b 识别出的 LaTeX 优先；它是从原卷截图还原的二维结构，
                # 而 text 是被拍平过的一维文本。没有 LaTeX 就退回版面解析器的 MathML。
                # 选项里也可能有 〔图N〕 —— 「选项本身就是图片」那类题就是这样
                inner = (with_math("$%s$" % o["latex"], tex) if o.get("latex")
                         else rich_html(o["text"], q, tex, asset, geo, col_w,
                                        segs=o.get("math"), maxw=600))
                if o.get("figure"):
                    raw = asset(o["figure"])
                    if raw:
                        inner += '<img src="%s" alt="选项%s">' % (
                            datauri(raw, 600, o["figure"]), o["key"])
                body.append("<li><em>%s</em><span>%s</span></li>" % (o["key"], inner))
            body.append("</ul>")
            oi = q.get("option_image")
            if oi and asset(oi):
                body.append('<details class="raw"><summary>对照原卷选项</summary>'
                            '<img src="%s" alt="原卷选项区"></details>'
                            % datauri(asset(oi), 900, oi))
        if q.get("stem_low_conf"):
            body.append('<div class="warn">%s</div>' % esc(q["stem_low_conf"]))

        body.append('<div class="lbl">解题思路</div>')
        body.append(solution_html(explain.get(q["n"]), tex))
        body.append("</div></article>")

    if rejected:
        print("   ⚠ 拒绝装配 %d 个场景（绑定不符）：" % len(rejected))
        for r in rejected:
            print("     · " + r)

    warn_html = ""
    if rejected:
        warn_html += ('<div class="note"><b>拒绝装配 %d 个动画场景</b>　'
                      % len(rejected)) + esc("；".join(rejected)) + \
                     "　—— 场景按 bind.json 绑定到具体卷子，题号对上也不够。</div>"
    if qs.get("warnings"):
        warn_html = ('<div class="note"><b>切分告警 %d 条</b>　'
                     % len(qs["warnings"])) + esc("；".join(qs["warnings"])) + "</div>"

    page = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title><style>%s</style><style>%s</style></head><body>%s
<div class="wrap">
<header class="masthead">
<p class="eyebrow">exam-explainer · 管线产物</p>
<h1>%s</h1>
<p class="sub">本页由 <code>ingest → segment → assemble</code> 全自动生成，无人工编辑。
插图为原卷内嵌线稿，动画场景来自已通过五层门禁的实现。</p>
<div class="facts">
<div class="fact"><b>%d</b><span>题目</span></div>
<div class="fact"><b>%d</b><span>插图</span></div>
<div class="fact"><b>%d</b><span>动画场景</span></div>
<div class="fact"><b>%d</b><span>切分告警</span></div>
<div class="fact"><b>%d/%d</b><span>已解题</span></div>
</div>
%s
<div class="note"><b>这是一条竖切片，不是完整产品。</b>　解题由模型生成、**未经人审**，
每题都标注了模型自评的置信度和它自己补充的前提，请对照原卷判断。
⑤ 生成场景尚未接入管线，动画只有已单独过门禁的那几题有，其余退回原卷插图。</div>
</header>
%s
<footer>切分与装配为纯代码；解题为模型生成。源文件：%s</footer>
</div>
<script>window.Scenes={};</script>
<script>%s</script>
<script>%s</script>
</body></html>""" % (esc(title), CSS, katex_css(), DEFS, esc(title),
                     len(qs["questions"]), n_fig, len(scenes),
                     len(qs.get("warnings") or []),
                     len(explain), len(qs["questions"]),
                     warn_html, "\n".join(body),
                     esc(os.path.basename(qs.get("source") or name)),
                     "\n".join(scene_js), runtime)

    open(a.out, "w", encoding="utf-8").write(page)
    # 往库里留痕。页面上的「⑦ 呈现」以这一行为准 —— 以前它是硬编码 true，
    # 而网页上传那条链压根没跑到这里，标志却一直是绿的。
    store.mark_assembled(name, os.path.abspath(a.out))
    n_tab = sum(len(segment.merged_tables(q.get("tables") or []))
                for q in qs["questions"])
    n_vlm = sum(1 for q in qs["questions"] if q.get("stem_latex"))
    print("── 装配 %s" % a.out)
    print("   %d 题 · %d 插图内嵌 · %d 张表 · %d 个动画场景 · %d 条告警"
          % (len(qs["questions"]), n_fig, n_tab, len(scenes),
             len(qs.get("warnings") or [])))
    print("   题干：%d/%d 题用视觉模型转写版；公式渲染失败 %d 条（页面上以源码显示）"
          % (n_vlm, len(qs["questions"]), n_tex_bad))
    n_inv = sum(1 for s in explain.values() if (s.get("n_invariants") or 0) > 0)
    print("   解题：%d/%d 题有（其中 %d 题写了物理断言）"
          % (len(explain), len(qs["questions"]), n_inv))
    print("   → %.0f KB，自包含无外链" % (os.path.getsize(a.out) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
