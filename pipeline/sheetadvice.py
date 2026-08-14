#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sheetadvice.py —— 逐题建议：这道题为什么错了、这个知识点该怎么提高

    python pipeline/sheetadvice.py <卷名> --sheet <id>

老师看完「哪几道错了」之后的下一个问题是「**那我该怎么办**」。这一步回答它，
一道题一条：错在哪、针对这个知识点做什么。

三条硬规矩
----------
1. **只给没拿满分的题生成。** 对的题不需要建议，而每多一道就多一份 token ——
   便宜的筛子排在贵的前面，这是这个仓库定过的规矩（④c 挪到 ④ 前面那次）。

2. **说不出具体的就别说。** 「要加强对该知识点的理解」这种放到任何一道题上
   都成立的话**等于没说**，而它比不说更糟：它占着位置、看起来像有结论，
   老师会因此以为自己看过了。这类回答在 `collect` 里被丢掉。

3. **错因只能从「学生写的」和「标准答案」的差别里读出来。** 我们没有学生的
   思维过程，只有他写下的东西。所以提示词要求模型指出**具体的差异**，
   而不是替他编一段心理活动。
"""
import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

BASE = os.environ.get("EXAM_KP_BASE") or os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
KEY = os.environ.get("EXAM_KP_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("EXAM_ADVICE_MODEL") or os.environ.get(
    "EXAM_KP_MODEL") or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

#: 判定是这几个的题才给建议。
#: `right` 不需要；`blank` 没作答，谈不上「为什么错」；
#: `unsure` 连学生写了什么都没读出来，分析错因就是编
NEED = ("wrong", "partial")

#: 一句话「说没说具体的东西」，判据是**里面有没有出现具体的物理内容**。
#:
#: 不用「空话词表」那条路：正则永远追不上人的措辞（「对该知识点理解不到位」
#: 就绕过了第一版列的十几个词），而且列得越长越容易误伤真话。
#:
#: 换个方向问：**这句话里出现了具体的东西吗** —— 选项字母、数字、公式符号、
#: 或者一个具体的物理名词。都没有的话，它放到任何一道题上都成立，等于没说。
_CONCRETE = re.compile(
    r"[A-Da-d](?![a-z])"                     # 选项字母
    r"|\d"                                    # 数字、数量级、单位
    r"|[=＝×÷/^_√∝Δ]"                        # 式子
    r"|定律|定理|公式|方程|守恒|左手|右手|安培|洛伦兹|动能|动量|电动势"
    r"|磁通|磁感|折射|干涉|衍射|半衰期|能级|谐振|欧姆|焦耳|楞次|法拉第"
    r"|正负|方向|单位|量级|符号|下标|分母|分子|矢量|标量|受力|分解")

#: 空话里最常见的几种，单独出现时直接判空（走不到上面那条也拦得住）
_HOLLOW_HEAD = ("粗心", "马虎", "不认真", "没审题", "审题不清")


def pick(rows):
    """
    这一份卡里哪几道题该给建议。**纯函数。**

    只挑没拿满分、而且**有东西可比**的题：学生确实写了什么、且有标准答案可对。
    一道都挑不出来时回空 —— 调用方据此**一次调用都不发**（全对的卡不该花这个钱）。
    """
    out = []
    for r in rows:
        if r.get("verdict") not in NEED:
            continue
        if not r.get("refAnswer"):
            continue                      # 挂不上题，没有标准答案可对
        ans = str(r.get("answer") or "").strip()
        if ans in ("", "blank", "unreadable"):
            continue                      # 没作答 / 没读出来，错因无从谈起
        out.append(r)
    return out


def payload_for(rows):
    """把这几道题组成一段材料。**纯函数。**"""
    parts = []
    for r in rows:
        n = r["n"]
        label = ("第 %d(%d) 题" % (n // 100, n % 100)) if n >= 100 else "第 %d 题" % n
        bits = [label]
        if r.get("verdict") == "partial":
            # 「选对但不全」和「全错」的错因完全不同 —— 不说的话模型会当成全错分析
            bits.append("（**半对**，得 %s 分、满分 %s 分）"
                        % (r.get("scoreGot"), r.get("scoreFull")))
        bits.append("\n  学生写的：%s" % r.get("answer"))
        bits.append("\n  标准答案：%s" % r.get("refAnswer"))
        kps = [k.get("name") for k in (r.get("kps") or []) if k.get("name")]
        if kps:
            # 建议要落到这个知识点上；不给它，模型只能泛泛而谈
            bits.append("\n  这道题考的：%s" % "、".join(kps))
        if r.get("refSolution"):
            # 官方解答是这条链上最可信的材料，比让模型自己重解一遍强
            bits.append("\n  官方解答：%s" % str(r["refSolution"])[:600])
        parts.append("".join(bits))
    return "\n\n".join(parts)


PROMPT = """下面是一个学生在物理考试里**没拿满分**的几道题。
每道题给了：他写的答案、标准答案、这道题考的知识点，有的还有官方解答。

给每道题写两句话，帮老师决定下一步讲什么：

  why  **他错在哪。** 只能从「他写的」和「标准答案」的差别里读出来 ——
       指出具体差在什么地方（少选了哪个、哪一步的公式用错了、单位/数量级差了多少）。
       **不要替他编心理活动**（「粗心」「没认真审题」这类一概不要）。
  fix  **针对这个知识点，接下来做什么。** 要具体到能照着做：
       练哪一类题、先补哪个前置概念、哪一步该怎么检查。

**看不出具体差别的，`why` 就写空字符串；给不出具体办法的，`fix` 就写空字符串。**
一句「加强对该知识点的理解」放到任何一道题上都成立，等于没说 ——
它会占着位置让老师以为看过了，比不写更糟。宁可空着。

只输出 JSON 数组，每项 `{"n": "题号", "why": "...", "fix": "..."}`，
题号原样用上面给的（小问写成 "12(3)"）。

%s"""


def _qnum(s):
    s = str(s or "").strip().replace("（", "(").replace("）", ")")
    if "(" in s:
        a, _, b = s.partition("(")
        b = b.rstrip(")")
        if a.strip().isdigit() and b.strip().isdigit():
            return int(a) * 100 + int(b)
        return None
    return int(s) if s.isdigit() else None


def _hollow(t):
    """
    这句话是不是空话（放到任何一道题上都成立）。

    判据是**里面有没有具体的东西** —— 选项字母、数字、式子符号、
    或者一个具体的物理名词。一样都没有，那它对哪道题都成立，等于没说。
    """
    t = str(t or "").strip()
    if not t:
        return True
    if any(w in t for w in _HOLLOW_HEAD):
        return True
    return not _CONCRETE.search(t)


def collect(rows):
    """
    模型回来的东西 → `{题号: {"why", "fix"}}`。**纯函数。**

    **空话丢掉**（见 `_EMPTY`）：留着它比不留更糟。
    两句只剩一句也留着 —— 说得出错因、说不出办法，仍然比两样都没有强。
    """
    out = {}
    for r in rows or []:
        n = _qnum(r.get("n"))
        if n is None:
            continue
        why = "" if _hollow(r.get("why")) else str(r["why"]).strip()
        fix = "" if _hollow(r.get("fix")) else str(r["fix"]).strip()
        if why or fix:
            out[n] = {"why": why, "fix": fix}
    return out


def ask(payload, tries=2):
    body = json.dumps({"model": MODEL, "max_tokens": 4000, "temperature": 0,
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
        except Exception as e:                                # noqa: BLE001
            last = e
            if k == tries - 1:
                raise
    raise last


def advise(rows, verbose=True):
    """
    给这一份卡的错题写建议，回 `{题号: {"why", "fix"}}`。

    **一道都不用给时一次调用都不发。** 全对的卡不该花这个钱。
    """
    log = (lambda s: print(s, flush=True)) if verbose else (lambda *a, **k: None)
    todo = pick(rows)
    if not todo:
        log("── 没有需要建议的题（全对，或者错的那几道没有可比的材料）")
        return {}
    if not KEY:
        log("── 没有 API key，跳过逐题建议")
        return {}
    log("── 逐题建议：%d 道（%s）" % (len(todo), MODEL))
    got = collect(ask(PROMPT % payload_for(todo)))
    log("   写出 %d 条" % len(got))
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--sheet", type=int, required=True)
    a = ap.parse_args()
    from pipeline import api                                  # noqa: PLC0415
    rows = api.sheet_detail_rows(a.paper, a.sheet)
    for n, adv in advise(rows).items():
        store.put_sheet_answer(a.sheet, n, advice=adv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
