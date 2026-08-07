#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kpmark.py —— 阶段③c 整卷知识点标注

    python pipeline/kpmark.py <卷名> [--force]

给每道题挂上受控词表里的知识点。诊断报告里「这个学生哪个知识点弱」这句话
就架在这一步的产出上。

为什么排在 ③ 之后
-----------------
用得上解法。知道这道题**怎么解的**，比只看题干更判得准它考什么 ——
一道「小球从斜面滑下」的题，看题干像运动学，看解法才知道考的是动能定理。

为什么整卷一次调用
------------------
和 ③b 同一个理由：模型同时看得见 16 道题，标签的粒度才对得齐。逐题各标各的，
同一卷里「动量守恒」和「碰撞问题」这种粗细不一的标签会混在一起 ——
而这一步的全部价值就在于**能聚合**，粒度不齐等于没标。

挂不上就留空
------------
模型编出来的 code 一律丢掉，不做模糊匹配、不找最接近的。塞进去的标签会污染
薄弱点统计，而且没有任何人能从结果里看出它是塞的。页面上明说「这道题没挂上
知识点」比挂一个错的强。
"""
import argparse, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kp
import store

for _l in (open(os.path.join(ROOT, ".env"), encoding="utf-8")
           if os.path.exists(os.path.join(ROOT, ".env")) else []):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# 纯文本分类任务，DeepSeek 够用而且便宜。这一步不看图 —— 题干文字加 ③ 的解法
# 已经足够判断考什么。
KEY = os.environ.get("EXAM_KP_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
BASE = os.environ.get("EXAM_KP_BASE") or os.environ.get("DEEPSEEK_BASE_URL",
                                                        "https://api.deepseek.com/v1")
MODEL = os.environ.get("EXAM_KP_MODEL") or os.environ.get("DEEPSEEK_MODEL",
                                                          "deepseek-v4-pro")

MAX_KPS = 3

PROMPT_HEAD = """给一份物理试卷的每道题挂知识点标签。

下面先给你**受控词表**，再给你整卷每道题的题号、题型、题干和解法。

三条硬规则：

1. `code` **只能从词表里挑**。词表里没有的，哪怕你觉得更准确，也不许写 ——
   编出来的会被直接丢掉。
2. 一道题最多挂 %d 个，按重要性从高到低排。挂满等于没挂。
3. `why` 是针对**这道题**的一句话（「用动量守恒求碰后速度」），
   不是知识点的定义（「动量守恒定律是指…」）。给不出来就别挂这一条。

真判不出来就给空数组 `"kps": []`。**挂不上比挂错好** ——
这些标签会拿去统计学生的薄弱知识点，挂错一个就凭空造出一个假的薄弱点。

只输出 JSON 数组，不要代码块围栏、不要解释：
[{"n": 1, "kps": [{"code": "mom.conserve", "why": "用动量守恒求碰后速度"}]}, ...]

必须覆盖下面出现的每一个题号，一个都不能少。

════════════════ 受控词表 ════════════════
""" % MAX_KPS


def payload_for(paper, sols):
    parts = []
    for q in paper["questions"]:
        stem = re.sub(r"\s+", " ", (q.get("stem_latex") or q.get("stem") or "").strip())
        bits = ["【第%d题】%s" % (q["n"], q.get("type") or ""), "题干：" + stem[:260]]
        s = sols.get(q["n"])
        if s and s.get("steps"):
            bits.append("解法：" + re.sub(r"\s+", " ", " ".join(s["steps"]))[:400])
        elif s and s.get("answer"):
            bits.append("答案：" + re.sub(r"\s+", " ", s["answer"])[:200])
        else:
            bits.append("解法：（尚未解出，只能看题干判断）")
        parts.append("\n".join(bits))
    return "\n\n".join(parts)


def keep(rows, valid_ns):
    """
    把模型的原始输出过成可以入库的形状。**纯函数，不碰网络也不碰库** ——
    这一步所有的正确性判断都在这里，所以它必须能单独测。

    过滤规则：题号必须在这份卷子里、code 必须解析得到、why 必须非空、
    去重、最多 MAX_KPS 个。一条都不剩的题不出现在结果里（= 没挂上）。
    """
    out = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if n not in valid_ns:
            continue
        kept, seen = [], set()
        for item in (r.get("kps") if isinstance(r.get("kps"), list) else []):
            if not isinstance(item, dict):
                continue
            code = kp.resolve(item.get("code"))
            why = str(item.get("why") or "").strip()
            if not code or not why or code in seen:
                continue
            seen.add(code)
            kept.append({"code": code, "why": why[:80]})
            if len(kept) == MAX_KPS:
                break
        if kept:
            out[n] = kept
    return out


def ask(payload, tries=3):
    body = json.dumps({"model": MODEL, "max_tokens": 8000, "temperature": 0,
                       "messages": [{"role": "user", "content": payload}]}).encode()
    last = None
    for k in range(tries):
        try:
            r = urllib.request.Request(BASE + "/chat/completions", body,
                                       {"Authorization": "Bearer " + KEY,
                                        "Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(r, timeout=300).read())
            txt = d["choices"][0]["message"]["content"]
            m = re.search(r"\[.*\]", txt, re.S)
            if not m:
                raise ValueError("没有返回 JSON 数组：" + txt[:160])
            return json.loads(m.group(0))
        except Exception as e:
            last = e
            if k == tries - 1:
                raise
    raise last


def mark(name, force=False, verbose=True):
    """跑一次 ③c，返回写了几题（-1 = 没跑成，0 = 跳过）。"""
    log = print if verbose else (lambda *a, **k: None)
    paper = store.get_paper(name)
    if not paper:
        log("库里没有「%s」" % name)
        return -1
    if not KEY:
        log("没有 DEEPSEEK_API_KEY（或 EXAM_KP_KEY），跳过 ③c")
        return -1
    todo = [q for q in paper["questions"] if not q.get("kps")]
    if not todo and not force:
        log("── 知识点 %s：%d 题都挂过了，跳过" % (name, len(paper["questions"])))
        return 0

    sols = store.paper_solutions(name)
    valid = {q["n"]: q["id"] for q in paper["questions"]}
    rows = ask(PROMPT_HEAD + kp.catalog_text()
               + "\n\n════════════════ 试卷 ════════════════\n\n"
               + payload_for(paper, sols))
    got = keep(rows, set(valid))

    cat = kp.load()
    for n in sorted(got):
        store.put_kps(valid[n], got[n])
        log("   第%2d题 %s" % (n, "、".join(cat[k["code"]]["name"] for k in got[n])))

    miss = sorted(set(valid) - set(got))
    log("── 知识点 %s（%s）" % (name, MODEL))
    log("   挂上 %d 题，没挂上 %d 题" % (len(got), len(miss)))
    if miss:
        # 缺了就说缺了。页面上这些题会写「没挂上知识点」，不塞一个最接近的
        log("   ⚠ 没挂上：%s（页面上会明说，不塞占位标签）"
            % "、".join("第%d题" % n for n in miss))
    return len(got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--force", action="store_true", help="已经挂过的题也重挂")
    a = ap.parse_args()
    name = os.path.basename(os.path.normpath(a.paper))
    return 1 if mark(name, a.force) < 0 else 0


if __name__ == "__main__":
    sys.exit(main())
