#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solve.py —— 阶段③ 解题

    python pipeline/solve.py <卷名> [-j 并行数] [--only 12,14] [--force] [--crosscheck]

两级链路
--------
**DeepSeek 是纯文本模型**（实测 `image_url` 直接 400），而 82% 的题带插图。
但「带插图」不等于「必须看图」—— 实测重庆卷 13 题，DeepSeek 独立答对 8 道，
另外 5 道**老老实实回「NEED_FIGURE」而不是编一个读起来合理的答案**。
图里真有信息时它认得出来，这正是这条链最怕的失败模式（错得看不出来），它没犯。

    DeepSeek 盲试 ──能解──→ 采用（免费通道，实测覆盖过半）
                 └看不到图→ 豆包（会读图，图直接进 payload，一次调用）

图不走「图→文字→解题」的转换：那会把一个看得见的错换成看不见的错。
描述里把 37° 写成 53°，下游会一本正经算出一个毫无破绽的错答案。

产出什么
--------
不只是答案。阶段④ 要靠 `key_facts` 写断言，靠 `assumptions` 与 `figure_reading`
知道结论架在哪些题面之外的前提上 —— **前提错了，断言会「错得自洽」**，
门禁全绿而物理是错的。这两栏会原样呈现在页面上，人审要盯的就是它们。

`--crosscheck` 独立解两遍并比对。实测同一模型对福建卷第16题先后给出
`√7·v₁` 和 `(1+√3)v₁`（后者经门禁的数值仿真证实为对），**两次都自称 high**——
压轴题上模型的自评置信度没有区分力，只有独立复核能暴露这件事。

隔离
----
③ DeepSeek/豆包、④ DeepSeek 写断言、⑤ claude CLI 沙箱写代码，
三个环节三个进程三份上下文。「写代码的那一方不能写断言」靠进程边界保证，
不靠提示词里的一句嘱咐。
"""
import argparse, base64, concurrent.futures as cf, hashlib, json, os, re
import subprocess, sys, tempfile, threading, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store
import cliask   # 订阅只能经 claude CLI 用

for _l in (open(os.path.join(ROOT, ".env"), encoding="utf-8")
           if os.path.exists(os.path.join(ROOT, ".env")) else []):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

CLI = next((p for p in ("/opt/homebrew/bin/claude",
                        os.path.expanduser("~/.nvm/versions/node/v25.2.1/bin/claude"),
                        "/usr/local/bin/claude") if os.path.exists(p)), None)
MODEL = os.environ.get("EXAM_SOLVE_MODEL", "claude-sonnet-5")

# 两级解题：先问纯文本的 DeepSeek，它说看不到图才升级到会读图的豆包。
#
# 为什么这么排 —— 实测重庆卷 13 题：DeepSeek 独立答对 8 道，另外 5 道
# **老老实实说「NEED_FIGURE」而不是编一个读起来合理的答案**，一次都没瞎猜。
# 图里真有信息时它认得出来，这正是这条链最怕的失败模式（错得看不出来），它没犯。
# 于是六成的题不必动视觉模型，而视觉模型每题贵 50 倍。
BACKEND = os.environ.get("EXAM_SOLVE_BACKEND", "deepseek-first")
# 盲试那一级的端点。`DEEPSEEK_*` 是**五处共用**的（③ 解题、③b 目录、
# ③c 知识点、④c 选题、② 的 LLM 兜底），后三处早就各有各的覆盖变量，只有 ③ 没有
# —— 于是想给 ③ 换个端点，只能去动全局，把另外四步一起拖下水。
# 而 ③ 恰恰最不该跟着别人走：**它的答案会被 ④ 冻成物理断言**，换脑子的影响
# 一路传到动画，而且是静默的。命名跟隔壁三个模块一致，不另造一套。
DS_KEY = os.environ.get("EXAM_SOLVE_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
DS_BASE = os.environ.get("EXAM_SOLVE_BASE") or os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DS_MODEL = os.environ.get("EXAM_SOLVE_MODEL") or os.environ.get(
    "DEEPSEEK_MODEL", "deepseek-v4-pro")
ARK_KEY = os.environ.get("ARK_API_KEY", "")
ARK_BASE = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
ARK_MODEL = os.environ.get("ARK_VISION_MODEL", "doubao-seed-2-0-pro-260215")
# HTTP 那条路要任意 OpenAI 兼容端点（自己配 KEY/BASE），中转站是其中一种。
CL_KEY = os.environ.get("EXAM_VISION_KEY", "")
CL_BASE = os.environ.get("EXAM_VISION_BASE", "")
CL_MODEL = os.environ.get("EXAM_VISION_MODEL", "claude-sonnet-5")

# 读图那一级用谁：
#   subscription  经 claude CLI 走订阅。准，但**每张图一次 Read 工具调用**，
#                 实测比把图塞进 payload 的直连贵得多。默认 —— 读图错了是
#                 「看不出来的错」，宁可慢也不该在这里省。
#   doubao        火山方舟，图直接进 payload 一次调用，便宜约 50 倍；
#                 实测 5 道必须看图的题错 2 道，所以不做默认。
#   http          任意 OpenAI 兼容端点（EXAM_VISION_BASE/KEY/MODEL）
VISION = os.environ.get("EXAM_VISION", "subscription")

NEED_FIGURE = "NEED_FIGURE"
# 并行度。瓶颈在等远端返回，本地 CPU 基本闲着，所以开并行是纯赚。
# 但每个 claude 进程实测占 376 MB，打太猛也容易触发限流，4 路是个稳的默认值。
JOBS = int(os.environ.get("EXAM_SOLVE_JOBS", "4"))

PROMPT = """你是高考物理阅卷组的老师。下面是一道题，可能配有原卷插图。

解这道题，输出 JSON（不要代码块围栏、不要任何解释文字）：

{
  "figure_reading": ["从插图里读到的每一条事实，逐条列出"],
  "answer": "选择题填选项字母（多选写成 \\"BD\\"）；非选择题填最终结果的表达式或数值",
  "steps": ["逐步讲解，每步一句话，从受力/守恒/几何关系讲到结论"],
  "key_facts": ["可以用数值检验的事实"],
  "assumptions": ["题面没有给出、你自己补上的量或前提"],
  "unreadable": ["看不清或图上信息不足以判断的地方"],
  "confidence": "high | medium | low"
}

要求：

- **figure_reading 是最重要的一栏**。把你从图里读出来的每条事实单独写出来：
  「倾角标注为 37°」「图线在 t=2s 处过零并转为负值」「P 点在第 2、3 条磁感线之间」
  「选项 B 的图是一条先增后减的抛物线」。
  实测读图出错是这类题最主要的错误来源，而且错了之后推导会显得完全合理 ——
  单独列出来，人对着原图扫一眼就能发现，不必读完整段推导。
  **图里没有的信息不要写进这一栏。**
- **key_facts 是给下游写物理断言用的**，必须是可检验的命题，形如
  「速度取极小值处恰在 d = d₁」「碰撞瞬间 v_A = 2v₁」「全程间距单调不增」。
  不要写「由动能定理可得」这种过程描述 —— 那属于 steps。
- **assumptions 必须诚实**。题面没给弹簧劲度、没给初速度、没给倾角，
  而你解题时用到了，就写进来。这一栏空着比编一个数危险得多。
- 图上看不清、或者图里的信息不足以定量的，写进 unreadable，**不要猜**。
  unreadable 非空时 confidence 不得为 high。
- 只有你确信解法与答案都对时才写 high。拿不准就 medium 或 low ——
  下游会按 confidence 决定要不要进人工队列。
- **表达式一律写成 `$…$` 包起来的 LaTeX**：`$\\sqrt{\\dfrac{2ah}{\\cos\\theta}}$`、
  `$\\dfrac{4mv_0^2}{R}$`。不要用 `sqrt(...)`、`v0^2` 这种 ASCII 写法，
  也不要写不带 `$` 的裸 LaTeX。answer / steps / key_facts 都是。
  选择题的 answer 仍然只填字母，不要包 `$`。
"""


def q_source_hash(q, figs):
    """题面内容哈希：题干 + 选项 + 插图字节。题没变就不必重解。"""
    h = hashlib.sha256()
    h.update((q.get("stem_latex") or q.get("stem") or "").encode())
    for o in q.get("options") or []:
        h.update((o.get("key", "") + (o.get("latex") or o.get("text") or "")).encode())
    for t in q.get("tables") or []:
        h.update(json.dumps(t.get("rows") or [], ensure_ascii=False).encode())
    for b in figs:
        h.update(hashlib.sha256(b).digest())
    return h.hexdigest()


def question_text(q):
    parts = ["【题型】%s" % (q.get("type") or "未标注")]
    if q.get("points"):
        parts.append("【分值】%d 分" % q["points"])
    parts.append("【题干】\n" + (q.get("stem_latex") or q.get("stem") or ""))
    for t in q.get("tables") or []:
        if t.get("rows"):
            rows = "\n".join(" | ".join(r) for r in t["rows"])
            parts.append("【表%d%s】\n%s" % (t["id"],
                                            "（%s）" % t["caption"] if t.get("caption") else "",
                                            rows))
    if q.get("options"):
        # 「选项本身就是图片」的题（实测全库 8 道）选项文本是空的，
        # 只在这里写文本会让模型看到四个空选项 —— 它会如实回答「无法确定」，
        # 但那是我们没把图给它，不是它不会做
        parts.append("【选项】\n" + "\n".join(
            "%s. %s" % (o["key"], o.get("latex") or o.get("text") or
                        ("见下方标注为「选项%s」的图" % o["key"] if o.get("figure") else "（空）"))
            for o in q["options"]))
    if q.get("stem_low_conf"):
        parts.append("【注意】题干由视觉模型转写，可信度提示：" + q["stem_low_conf"])
    return "\n\n".join(parts)


BLIND = ("\n\n**注意：这道题配有插图，但你看不到图。**\n"
         "仅凭文字足以解出就解；只要有一处必须看图才能确定（角度、位置关系、"
         "图像形状、仪表读数、选项本身是图 等），`answer` 一律只填 \"%s\"，"
         "其余字段留空。**不要猜。**\n" % NEED_FIGURE)


def norm_tex(s):
    r"""
    行内公式统一成 `$…$`。

    模型会混用三种写法：`$…$`、`\(…\)`、`\[…\]`。前端和静态页都只认第一种，
    别的会原样打印成 `\(\frac{4m...` —— 实测重庆卷第14题就是这样。
    在入口处归一，比让每个渲染点各自兼容三种写法可靠。
    """
    if not isinstance(s, str):
        return s
    s = re.sub(r"\\\((.+?)\\\)", lambda m: "$%s$" % m.group(1).strip(), s, flags=re.S)
    s = re.sub(r"\\\[(.+?)\\\]", lambda m: "$%s$" % m.group(1).strip(), s, flags=re.S)
    return s


def loads_json(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("没有返回 JSON：%s" % txt[:200])
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', m.group(0)))


# 一次调用的上限。正常几秒到一两分钟，**5 分钟不回基本就是卡死而不是在算** ——
# 实测两次都是请求挂在本机代理（127.0.0.1:7897）上，连接还在、CPU 0%、永远等不到响应。
# 原来给 900 秒，等于一道题白白堵掉 15 分钟；重试一条新连接通常几秒就出结果。
HTTP_TIMEOUT = int(os.environ.get("EXAM_HTTP_TIMEOUT", "300"))
HTTP_TRIES = int(os.environ.get("EXAM_HTTP_TRIES", "2"))


def post(base, key, payload):
    last = None
    for k in range(HTTP_TRIES):
        try:
            r = urllib.request.Request(base + "/chat/completions",
                                       json.dumps(payload).encode(),
                                       {"Authorization": "Bearer " + key,
                                        "Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(r, timeout=HTTP_TIMEOUT).read())
            return loads_json(d["choices"][0]["message"]["content"])
        except Exception as e:
            last = e
            if k == HTTP_TRIES - 1:
                raise
            time.sleep(3)
    raise last


def blind_banner(base, model):
    """
    盲试这一级用的是谁。跑完那行要写出来 ——「跑完都不知道钱记在哪边」
    这件事在 ⑤ 上踩过，而 ③ 是整条链里唯一决定答案对错的一步，更该说清楚。
    """
    where = "火山方舟" if "volces.com" in base else \
            "DeepSeek 官方" if "api.deepseek.com" in base else base
    return "%s %s" % (where, model)


def ask_deepseek(text):
    """纯文本试解。看不到图就返回 None，交给上一层升级。"""
    d = post(DS_BASE, DS_KEY, {"model": DS_MODEL, "temperature": 0,
                               "messages": [{"role": "user",
                                             "content": PROMPT + BLIND + "\n\n" + text}]})
    return None if str(d.get("answer", "")).strip() == NEED_FIGURE else d


def vision_payload(text, imgs):
    """图直接进 payload —— 一次调用，没有工具循环。标签必须带，否则分不清哪张是选项 A。"""
    content = [{"type": "text", "text": PROMPT + "\n\n" + text}]
    for lab, raw in imgs:
        content.append({"type": "text", "text": "【%s】" % lab})
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(raw).decode()}})
    return [{"role": "user", "content": content}]


def ask_doubao(text, imgs):
    return post(ARK_BASE, ARK_KEY, {"model": ARK_MODEL, "temperature": 0,
                                    "messages": vision_payload(text, imgs)})


def ask_claude(text, imgs):
    """
    claude-sonnet-5 走中转直连。

    `max_tokens` 必须给足：它会先出思维链，额度不够的话正文返回空串，
    错误表现成「没有返回 JSON」而不是「被截断」—— 比原因难查得多。
    """
    return post(CL_BASE, CL_KEY, {"model": CL_MODEL, "max_tokens": 32000,
                                  "messages": vision_payload(text, imgs)})


def ask_subscription(text, imgs):
    """
    经 claude CLI 走订阅读图。

    上游给的 imgs 是 [(标签, 字节)] —— 图是从对象存储读出来的，本来就没有本地路径。
    而 CLI 读不了 stdin 里的 base64，只能落成临时文件给它用 Read 工具读。
    所以每张图一次工具调用，比把图塞进 payload 的直连贵。换来的是不依赖中转站额度。

    标签必须写进 prompt：否则模型分不清哪张是选项 A 的图。
    """
    with tempfile.TemporaryDirectory() as td:
        paths, lines = [], []
        for i, (lab, raw) in enumerate(imgs):
            p = os.path.join(td, "img%02d.png" % i)
            open(p, "wb").write(raw)
            paths.append(p)
            lines.append("%s：%s" % (lab, p))
        prompt = PROMPT + "\n\n" + text + "\n\n【原卷插图】\n" + "\n".join(lines)
        return loads_json(cliask.ask(prompt, images=paths, model=CL_MODEL, timeout=1800))


def ask_vision(text, imgs):
    """读图那一级。默认订阅 —— 读图错了是「看不出来的错」，不该在这里省钱。"""
    if VISION == "doubao":
        if not ARK_KEY:
            raise RuntimeError("EXAM_VISION=doubao 但没有 ARK_API_KEY")
        return ask_doubao(text, imgs), ARK_MODEL
    if VISION == "http":
        if not CL_KEY or not CL_BASE:
            raise RuntimeError("EXAM_VISION=http 但缺 EXAM_VISION_KEY / EXAM_VISION_BASE")
        return ask_claude(text, imgs), CL_MODEL
    if not cliask.available():
        raise RuntimeError("找不到 claude 可执行文件，订阅视觉通道不可用")
    return ask_subscription(text, imgs), CL_MODEL + "（订阅）"


def ask(text, imgs):
    """imgs 是 [(标签, 路径)]。标签必须带，否则模型分不清哪张是选项 A 的图。"""
    if not CLI:
        raise RuntimeError("找不到 claude 可执行文件")
    prompt = PROMPT + "\n\n" + text
    if imgs:
        prompt += "\n\n【原卷插图】请直接读这些图：\n" + \
                  "\n".join("%s：%s" % (lab, os.path.abspath(p)) for lab, p in imgs)
    # claude -p 是 agent 不是一次 API 调用：每张图都要一次 Read 工具调用，
    # 也就是多一轮。限定只给 Read，省掉它在项目里乱翻的那些轮。
    # 压轴题实测十几分钟，600s 会被自己的客户端超时打断。
    r = subprocess.run([CLI, "-p", "--model", MODEL, "--allowed-tools", "Read"],
                       input=prompt, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError("模型调用失败：%s" % (r.stderr or "")[-200:])
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        raise RuntimeError("没有返回 JSON：%s" % r.stdout[:200])
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', m.group(0)))


def key_answer(a):
    """答案的可比形式。只留字母数字，去掉排版差异（空格、全角标点、LaTeX 修饰）。"""
    s = re.sub(r"\\[a-zA-Z]+|[\s{}$（）()，,；;·\\]", "", str(a or ""))
    return s.lower()


def solve_one(name, q, tmp, force=False, crosscheck=False):
    """
    解一道题，写回库。返回 (是否新解, 摘要)。

    上传流程和 CLI 都走这里 —— 两条路各写一份，迟早会有一条落下修复。
    """
    want = [("题干插图%d" % (i + 1), f) for i, f in enumerate(q.get("figures") or [])]
    want += [("选项%s" % o["key"], o["figure"]) for o in q["options"] if o.get("figure")]
    figs, paths, labeled = [], [], []
    for i, (lab, f) in enumerate(want):
        row = store.find_asset(name, f)
        b = store.read_asset(row, name) if row else None
        if b:
            figs.append(b)
            labeled.append((lab, b))
            p = os.path.join(tmp, "q%02d_%d.png" % (q["n"], i))
            open(p, "wb").write(b)
            paths.append((lab, p))

    sha = q_source_hash(q, figs)
    if not force and store.solution_fresh(q["id"], sha):
        return False, "题面未变，跳过"

    text = question_text(q)

    def once():
        if BACKEND != "deepseek-first":
            return ask(text, paths), MODEL
        # 没有图的题连升级路径都不需要；有图的先盲试，看不到图它会自己认输
        d = ask_deepseek(text) if DS_KEY else None
        if d is not None:
            return d, DS_MODEL
        if not labeled:
            # 说要看图却没抽到插图：可能图没被抽出来，也可能只是过于谨慎。
            # 兜底给原卷整页 —— 那是真相本身，抽取失败也盖得住。
            for p in range(q["pages"][0], q["pages"][1] + 1):
                row = store.find_page(name, p)
                b = store.read_asset(row, name) if row else None
                if b:
                    labeled.append(("原卷第%d页" % p, b))
            if not labeled:
                raise RuntimeError("这道题必须看图，但既没有插图也没有整页渲染")
        return ask_vision(text, labeled)

    d, used = once()
    conf = d.get("confidence", "low")
    disagree = None
    if crosscheck:
        # 独立再解一遍。**实测同一模型对福建卷第16题先后给出 √7 和 (1+√3)，
        # 两次都自称 high** —— 压轴题上模型的自评置信度没有区分力，
        # 而阶段④ 会把答案原样写成断言、⑤ 照着实现，门禁全绿而物理是错的。
        # 两次不一致说明这题不该被当成可信输入，必须人来判。
        try:
            d2, _ = once()
            if key_answer(d2.get("answer")) != key_answer(d.get("answer")):
                disagree = str(d2.get("answer") or "")[:80]
                conf = "low"
        except Exception as e:
            disagree = "复核调用失败：%s" % str(e)[:60]
    # 看不清就不许自称 high —— 模型偶尔两边都填，这里以事实为准
    if d.get("unreadable") and conf == "high":
        conf = "medium"
    # 读图结果并进 assumptions 一起呈现。它们性质相同：都是「结论所依赖的、
    # 题面文字之外的前提」，也都是错了之后推导依然显得合理的地方。
    # 实测豆包在 5 道必须看图的题里读错 2 道，这一栏就是让那 2 道能被一眼看见。
    store.put_solution(q["id"], {
        "answer": norm_tex(str(d.get("answer") or "")),
        "steps": [norm_tex(x) for x in (d.get("steps") or [])],
        "key_facts": [norm_tex(x) for x in (d.get("key_facts") or [])],
        "assumptions": ([norm_tex("【复核不一致】再解一遍得到的是：" + disagree)]
                        if disagree else []) +
                       [norm_tex("【从图中读到】" + x) for x in (d.get("figure_reading") or [])] +
                       [norm_tex(x) for x in (d.get("assumptions") or [])] +
                       [norm_tex("【图上看不清】" + x) for x in (d.get("unreadable") or [])],
        "confidence": conf,
    }, sha, used)          # 记下真正作答的那个模型，页面上要显示
    return True, "%-22s %s 答案 %s（%d步 %d事实 %d假设%s%s）" % (
        used, conf, str(d.get("answer"))[:14], len(d.get("steps") or []),
        len(d.get("key_facts") or []), len(d.get("assumptions") or []),
        "，看不清 %d 处" % len(d["unreadable"]) if d.get("unreadable") else "",
        "，⚠复核不一致" if disagree else "")


# ③ 跑到一半时回头刷一次 ③b 目录，每 N 题一次。0 = 关掉。
#
# 为什么放在这儿而不是编排层：网页上传（api.py 直接调 solve_many）和命令行
# （run.py 起 solve.py 子进程）都要经过这个函数，写在这里两条入口自动一致 ——
# 两边各写一份，迟早有一条落下修复。
OUTLINE_EVERY = int(os.environ.get("EXAM_OUTLINE_EVERY", "4"))


class _Outliner:
    """
    在 ③ 进行中滚动刷新 ③b 目录。

    「答案速览」和左边的目录读的是 ③b 的产出，而 ③b 原来只排在 ③ 之后 ——
    于是解题那二三十分钟里，已经解出来的题在速览里也全写着「尚未生成」。

    三条约束：**不能拖慢 ③**（所以另起线程，解题这边不等它）、**不能堆积**
    （一次调用几十秒，上一次没回来就跳过这一次）、**失败必须无害**
    （③b 挂了不该影响解题，异常一律吞掉，反正管线末尾还会正经跑一次）。
    """

    def __init__(self, name):
        self.name = name
        self.busy = False
        self.lock = threading.Lock()

    def kick(self):
        with self.lock:
            if self.busy:
                return
            self.busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            import outline
            got = outline.refresh(self.name, verbose=False)
            if got > 0:
                print("   ③b 目录已刷新：%d 题有了短标题与短答案" % got, flush=True)
        except Exception as e:
            print("   ③b 顺带刷新没成（不影响解题）：%s" % str(e)[:100], flush=True)
        finally:
            with self.lock:
                self.busy = False


def solve_many(name, qs, jobs=4, force=False, on_done=None, on_start=None,
               crosscheck=False):
    """
    并行解一批题。

    题与题之间没有任何依赖，而每道题的时间几乎全花在等远端返回上
    （实测一题 6 轮、165s，本地 CPU 基本闲着），所以并行是纯赚的：
    15 道题串行半小时，4 路并行七八分钟。

    并发安全靠两点：`store` 里每次操作各开各的连接；每题解完立刻单独提交，
    线程之间不共享事务。**不攒到最后一起写** —— 中途出错时攒着的那些会全丢。

    并行度别开太大：每个 claude 进程实测占 376 MB，而且打太猛容易触发限流。
    """
    lock = threading.Lock()
    out = []
    # 最后一题不用刷：管线紧接着就会正经跑一次 ③b，两次挨着调没意义
    outliner = _Outliner(name) if OUTLINE_EVERY > 0 and len(qs) > OUTLINE_EVERY else None

    def run(q):
        # 开跑就报一声。压轴题要十几分钟，只在解完时打印的话，
        # 中间那十几分钟没有任何动静，看起来像卡死了
        if on_start:
            with lock:
                on_start(q)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fresh, note = solve_one(name, q, tmp, force, crosscheck)
                r = (q["n"], "ok" if fresh else "skip", note)
            except Exception as e:
                r = (q["n"], "fail", str(e)[:160])
        with lock:
            out.append(r)
            if on_done:
                on_done(r, len(out), len(qs))
            done = len(out)
        if outliner and done % OUTLINE_EVERY == 0 and done < len(qs):
            outliner.kick()
        return r

    with cf.ThreadPoolExecutor(max(1, jobs)) as ex:
        list(ex.map(run, qs))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="只做这几题，逗号分隔题号")
    ap.add_argument("--force", action="store_true", help="题面没变也重解")
    ap.add_argument("--crosscheck", action="store_true",
                    help="每题独立解两遍，答案不一致就降为 low 并标记（成本翻倍）")
    ap.add_argument("-j", "--jobs", type=int, default=JOBS,
                    help="并行解几道（默认 %d）" % JOBS)
    a = ap.parse_args()

    name = os.path.basename(os.path.normpath(a.paper))
    paper = store.get_paper(name)
    if not paper:
        print("库里没有「%s」" % name)
        return 1
    only = {int(x) for x in a.only.split(",") if x.strip()} if a.only else None

    qs = [q for q in paper["questions"] if not only or q["n"] in only]
    if a.limit:
        qs = qs[:a.limit]
    t0 = time.time()

    def started(q):
        print("   →  第%2d题 开跑（%s，%d 字，%d 图）"
              % (q["n"], q.get("type") or "?",
                 len(q.get("stem_latex") or q.get("stem") or ""),
                 len(q.get("figures") or [])), flush=True)

    def report(r, i, total):
        n, kind, note = r
        mark = {"ok": "✓", "skip": "·", "fail": "✗"}[kind]
        print("   [%2d/%d] %s 第%2d题 %s" % (i, total, mark, n, note), flush=True)

    res = solve_many(name, qs, a.jobs, a.force, report, started, a.crosscheck)
    done = sum(1 for r in res if r[1] == "ok")
    skip = sum(1 for r in res if r[1] == "skip")
    fail = sum(1 for r in res if r[1] == "fail")

    vis = ARK_MODEL if VISION == "doubao" else CL_MODEL
    used = ("%s → %s" % (blind_banner(DS_BASE, DS_MODEL), vis)) \
        if BACKEND == "deepseek-first" else MODEL
    print("── 解题 %s（%s，%d 路并行）" % (name, used, a.jobs))
    print("   新解 %d 题，跳过 %d（题面未变），失败 %d，耗时 %.0f 分钟"
          % (done, skip, fail, (time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
