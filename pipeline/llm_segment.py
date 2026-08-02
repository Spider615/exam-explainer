#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_segment.py —— 阶段② 的升级通道：让模型产出切分方案

为什么需要它
------------
纯代码的锚点探测（anchors.py）实测完全依赖「题型词」这一个探测器。
做过消融：关掉它之后 20 份卷子 0/20 能切对。也就是说，
换一家出版社、一份不用「单选题」这类标记的卷子，代码路径必然崩。

为什么不让模型直接逐题切
------------------------
· 成本：每次上传都要付费，而试卷是高度重复消费的；
· 不确定：同一份卷子两次调用可能给出不同边界；
· 不可校验：没有任何办法判断它切得对不对。

所以分工是：**模型产出「切分方案」，代码执行并用同一套结构门禁校验。**

  1. 代码先跑探测器。够自信就直接用，**零模型调用**（常见情况走这条）。
  2. 不自信才升级：把带行号的版面喂给模型，要它回一份
     「第几行是第几题的开头」的方案。
  3. 拿回来的方案**必须过和代码路径完全相同的结构打分与自检**。
     过不了就不采信——模型也不享有豁免权。
  4. 按版面指纹缓存：同一家出版社的第二份卷子直接复用，不再调用。

这样既能应付陌生排版，又不会把成本和不确定性摊到每一次上传上。
"""
import hashlib, json, os, re, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    """密钥从 .env 读，不写进源码。.env 已在 .gitignore 里。"""
    fp = os.path.join(ROOT, ".env")
    if not os.path.exists(fp):
        return
    for line in open(fp, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


load_env()

CLI = next((p for p in ("/opt/homebrew/bin/claude",
                        os.path.expanduser("~/.nvm/versions/node/v25.2.1/bin/claude"),
                        "/usr/local/bin/claude") if os.path.exists(p)), None)

# 后端优先级：配了 DeepSeek 就用 DeepSeek，否则退回本机 claude CLI
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
BACKEND = "deepseek" if DEEPSEEK_KEY else ("claude-cli" if CLI else None)
DEFAULT_MODEL = DEEPSEEK_MODEL if BACKEND == "deepseek" else "claude-sonnet-5"

# 行内精定位用：题型标记（分值可有可无）
MARKER_RE = re.compile(
    r"(单选题|多选题|填空题|实验题|计算题|解答题|作图题|论述题|简答题|综合题)"
    r"(?:\s*[（(](\d+)分[)）])?")


# ---------------------------------------------------------------- 版面行视图
def build_lines(flow, text):
    """
    把文本流合并成「视觉行」：连续的、同页同 y 的文本块算一行。

    保持流的原始顺序，所以行的字符区间是连续的，
    模型给出的行号能无歧义地映射回字符偏移。
    """
    lines, cur = [], None
    for f in flow:
        key = (f["page"], round(f["y"] * 2) / 2 if f["ok"] else None)
        if cur and cur["key"] == key and f["ok"] == cur["ok"]:
            cur["end"] = f["end"]
        else:
            cur = {"key": key, "page": f["page"], "y": f["y"], "ok": f["ok"],
                   "start": f["start"], "end": f["end"]}
            lines.append(cur)
    for i, ln in enumerate(lines):
        ln["i"] = i
        ln["text"] = text[ln["start"]:ln["end"]]
    return lines


def fingerprint(doc, lines):
    """
    **试卷指纹**（内容哈希），不是版面指纹。

    这里刻意只做同卷复用。因为模型返回的是「第几行是第几题」——
    行号只对这一份卷子有意义，跨卷子复用一定是错的。

    这个粒度依然很有价值：试卷是高度重复消费的（全国真题就那么多，
    同一份会被反复上传），命中即零调用。

    真正的「跨出版社复用」需要模型改为返回一条**规则**而不是行号，
    那是另一种设计，尚未实现。
    """
    raw = "".join(ln["text"] for ln in lines)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- 提示词
PROMPT = """你在做试卷版面分析。下面是一份试卷按视觉行编号后的全文。

任务：判断**每一道题从哪一行开始**。

规则：
- 只标「题目」的开头。大题标题（如「一、单项选择题（本题共4小题…）」）不是题目，不要标。
- 小问（(1)(2)(3)）属于所属大题的一部分，不要单独标成题。
- 选项 A. B. C. D. 属于题目，不要标。
- 页眉页脚、页码、姓名栏不是题目。
- 如果行内能看出题型（单选题/多选题/填空题/实验题/计算题/解答题/作图题等）和分值，一并给出；看不出就写 null。

{context}

版面（格式：`行号|页码|内容`）：
{lines}

只输出 JSON，不要任何解释、不要代码块围栏：
{{"questions":[{{"line":<行号>,"type":<题型或null>,"points":<分值或null>}}, ...]}}
"""


def build_prompt(doc, lines, sections, ranking, max_chars=70):
    ctx = []
    if sections:
        ctx.append("已解析出的大题声明：" + "；".join(
            "%s、%s 共%d小题" % (s["label"], s["title"], s["declared"]) for s in sections))
    if ranking:
        ctx.append("代码探测器给出的候选（仅供参考，可能全错）：")
        for sc, name, anc, why in ranking[:4]:
            ctx.append("  · %s → %s" % (name, why))
    body = []
    for ln in lines:
        t = ln["text"].strip()
        if not t:
            continue
        if len(t) > max_chars:
            t = t[:max_chars] + "…"
        body.append("%d|p%d|%s" % (ln["i"], ln["page"], t))
    return PROMPT.format(context="\n".join(ctx), lines="\n".join(body))


# ---------------------------------------------------------------- 调用
def _call_deepseek(prompt, model, timeout):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,                      # 切分要可复现，不要采样
        "response_format": {"type": "json_object"},
        "max_tokens": 8192,
    }).encode()
    req = urllib.request.Request(
        DEEPSEEK_URL.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + DEEPSEEK_KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    if "choices" not in d:
        raise RuntimeError("DeepSeek 返回异常：%s" % str(d)[:300])
    usage = d.get("usage", {})
    return d["choices"][0]["message"]["content"], usage


def _call_claude_cli(prompt, model, timeout):
    if not CLI:
        raise RuntimeError("找不到 claude 可执行文件")
    r = subprocess.run([CLI, "-p", "--model", model],
                       input=prompt, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("claude CLI 调用失败：%s" % (r.stderr or "")[-300:])
    return r.stdout.strip(), {}


def call_model(prompt, model=None, timeout=180):
    """返回 (解析后的 JSON, 用量)。后端由 .env 决定，调用方不必关心。"""
    if BACKEND is None:
        raise RuntimeError("没有可用的模型后端：既没配 DEEPSEEK_API_KEY，也找不到 claude CLI")
    model = model or DEFAULT_MODEL
    if BACKEND == "deepseek":
        out, usage = _call_deepseek(prompt, model, timeout)
    else:
        out, usage = _call_claude_cli(prompt, model, timeout)
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise RuntimeError("模型没有返回 JSON：%s" % out[:200])
    return json.loads(m.group(0)), usage


# ---------------------------------------------------------------- 对外接口
last_usage = {}


def plan_anchors(doc, text, flow, sections, ranking, cache_dir=None,
                 model=None, force=False):
    """
    返回 (anchors, 说明, 是否命中缓存)。anchors 与 anchors.py 的格式一致，
    仍然要由调用方拿结构打分器复核——本函数不保证正确性。
    """
    lines = build_lines(flow, text)
    fp = fingerprint(doc, lines)
    cpath = os.path.join(cache_dir, "layout-%s.json" % fp) if cache_dir else None

    cached = None
    if cpath and os.path.exists(cpath) and not force:
        cached = json.load(open(cpath, encoding="utf-8"))

    if cached:
        qs, hit = cached["questions"], True
    else:
        prompt = build_prompt(doc, lines, sections, ranking)
        data, usage = call_model(prompt, model=model)
        qs, hit = data.get("questions", []), False
        last_usage.clear()
        last_usage.update(usage)
        if cpath:
            os.makedirs(os.path.dirname(cpath), exist_ok=True)
            json.dump({"fingerprint": fp, "backend": BACKEND, "model": model or DEFAULT_MODEL,
                       "usage": usage, "questions": qs},
                      open(cpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    byi = {ln["i"]: ln for ln in lines}
    anchors, skipped, refined = [], 0, 0
    for q in qs:
        ln = byi.get(q.get("line"))
        if ln is None:
            skipped += 1
            continue
        # 行内精定位：并排排版会把上一题的选项 D 和下一题的标记合成同一视觉行，
        # 直接取行首会把上一题的尾巴算进下一题。行内若能找到题型标记，就以它为准。
        pos, end = ln["start"], ln["start"]
        m = MARKER_RE.search(ln["text"])
        if m:
            pos = ln["start"] + m.start(1)
            end = ln["start"] + m.end()
            if pos != ln["start"]:
                refined += 1
        anchors.append({"pos": pos, "end": end,
                        "type": q.get("type") or (m.group(1) if m else None),
                        "points": q.get("points") or
                                  (int(m.group(2)) if m and m.group(2) else None)})
    anchors.sort(key=lambda a: a["pos"])
    tok = ""
    if not hit and last_usage:
        tok = "，%d in / %d out tokens" % (last_usage.get("prompt_tokens", 0),
                                          last_usage.get("completion_tokens", 0))
    note = "模型方案：%d 题（%s·指纹 %s，%s%s）%s%s" % (
        len(anchors), BACKEND, fp, "缓存命中" if hit else "本次调用", tok,
        "，%d 个行号无效已丢弃" % skipped if skipped else "",
        "，%d 处行内精定位" % refined if refined else "")
    return anchors, note, hit
