#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pick.py —— 阶段④c 动画选题：这道题**需不需要**做成动画

    python pipeline/pick.py <卷名> [--force] [--max 6]

为什么排在 ④ **之前**
--------------------
写一份完整 spec（spec + 可执行的参考实现，两次调用）实测约 6 分钟一道，
而这一步只要一次调用、28 秒判完整卷。**把便宜的筛子排在贵的后面是反的** ——
实测重庆卷：④ 对 10 道题写了完整 spec，最后只有 5 道真出了动画，
白写 5 道约 30 分钟；海南卷更夸张，9 道全白写。

所以现在的顺序是 ③b → **④c 选题** → ④ 只给选中的题写断言 → ④b 自检 → ⑤。

代价说清楚：没被选中的题**完全没有断言**，页面上标「无断言 · 未被检验」，
也就少了 ④b 那层「解法与受力方程对不对得上」的校验。这是有意的取舍 ——
那层校验只查 spec 内部自洽，查不出「理解错题但写得自洽」，
为它每卷多花半小时不划算。要给某道题补，随时 `spec.py --only N`。

为什么不能拿 ④ 的 `animatable` 当这道闸门
------------------------------------------
那一栏答的是「**做不做得了**」—— 写不写得出数值断言。实测重庆卷 15 题里
它筛掉 4 道（纯概念辨析、离散判定、电路读数），剩下 11 道。但剩下的里面还有
第1题「两个力求合力」、第2题「线圈平均电动势」这种 —— 做得了，可是一段动画
对理解它没有任何实质增量，一个平行四边形静态图就说清楚了。

⑤ 一题几分钟到几十分钟。全做等于把绝大部分时间花在增量最低的题上。

判据是「动画能不能说出静态图说不出的东西」
------------------------------------------
值得做的：有**随时间演化的过程**，而且过程本身就是考点 ——
带电粒子在复合场里分段运动、双棒导轨的速度趋近、简谐波的传播、碰撞前后的能量转移。
不值得做的：一次性的代数关系、静态受力平衡、读数与判定、纯概念比较。

判宽判窄都不会让错东西上页面
----------------------------
这一步只决定「给谁写断言」，不决定「谁能出动画」。后面还有两道硬闸门，
而且都是纯代码：④ 写不出数值断言就判 `animatable=false`；
④b 拿 spec 自带的参考实现验它自己的断言，自相矛盾就 rejected。
所以这里判宽了顶多多花几分钟，判窄了顶多少一个动画 —— 错的东西进不了页面。

`--max` 是硬上限：模型说 8 道都值得，也只做分数最高的前 N 道。
"""
import argparse, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

for _l in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

KEY = os.environ.get("EXAM_PICK_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
BASE = os.environ.get("EXAM_PICK_BASE") or os.environ.get("DEEPSEEK_BASE_URL",
                                                          "https://api.deepseek.com/v1")
MODEL = os.environ.get("EXAM_PICK_MODEL") or os.environ.get("DEEPSEEK_MODEL",
                                                            "deepseek-v4-pro")

PROMPT = """下面是一份物理试卷的若干道题（题干 + 权威解法）。
做一段动画要花几分钟到几十分钟，所以要挑：**哪些题做成动画是有实质增量的？**

判据只有一条：**动画能不能说出静态图说不出的东西。**

值得做（need=true）：
- 有随时间演化的过程，而且过程本身就是考点：带电粒子在复合场中分段运动、
  双棒/导轨的速度相互趋近、波的传播与叠加、碰撞前后的能量转移、变力做功的累积
- 多个物理量此消彼长，静态图只能画某一瞬间

不值得做（need=false）：
- 一次性的代数关系（合力、平均值、比例）——一张静态受力图或矢量图就说清楚了
- 静态平衡、位置求解
- 读数、判定、概念比较、单位换算
- 过程存在但极其平凡（匀速直线、自由落体）

另外，有些题**根本做不成动画**（没有随时间演化的物理过程、纯读图、纯概念判断、
只求一个静态数值），这类直接判 need=false。

对每道题给出：
  `n`      题号
  `need`   true / false
  `score`  0-10，动画相对静态图的增量有多大（need=false 时给 0-3）
  `why`    一句话，20 字以内，说清楚为什么。need=false 时这句话会**直接显示在页面上**
           告诉读者这道题为什么没有动画，所以要写成人话，不要写「不满足条件」。

只输出 JSON 数组，不要代码块围栏、不要解释：
[{"n": 13, "need": true, "score": 9, "why": "粒子分三段运动，静态图画不出速度如何逐段加倍"}]

必须覆盖下面出现的每一个题号。
"""


def payload_for(cands):
    """只喂题干 + 解法。这一步跑在 ④ 之前，那时候还没有 spec 可用。"""
    parts = []
    for q, sol in cands:
        bits = ["【第%d题】%s" % (q["n"], q.get("type") or "")]
        stem = re.sub(r"\s+", " ", (q.get("stem_latex") or q.get("stem") or ""))[:300]
        bits.append("题干：" + stem)
        if sol.get("answer"):
            bits.append("答案：" + re.sub(r"\s+", " ", sol["answer"])[:200])
        steps = sol.get("steps") or []
        if steps:
            bits.append("解法：" + re.sub(r"\s+", " ", " / ".join(steps))[:260])
        parts.append("\n".join(bits))
    return "\n\n".join(parts)


def ask(payload, tries=3):
    body = json.dumps({"model": MODEL, "max_tokens": 4000, "temperature": 0,
                       "messages": [{"role": "user", "content": payload}]}).encode()
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
        except Exception:
            if k == tries - 1:
                raise
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--max", type=int, default=int(os.environ.get("EXAM_PICK_MAX", "6")),
                    help="一卷最多做几道动画（硬上限，模型说了不算）")
    ap.add_argument("--force", action="store_true", help="已经判过的也重判")
    a = ap.parse_args()

    name = os.path.basename(os.path.normpath(a.paper))
    paper = store.get_paper(name)
    if not paper:
        print("库里没有「%s」" % name)
        return 1

    # 候选：解出来了的题。这一步现在是**第一道筛子**，前面没有别的闸门
    cands, blocked = [], []
    for q in paper["questions"]:
        sol = store.get_solution(q["id"])
        if not sol:
            blocked.append((q["n"], "还没解出来"))
            continue
        if q.get("anim_worth") is not None and not a.force:
            continue                       # 判过了
        cands.append((q, sol))

    print("── 动画选题 %s（%s）" % (name, MODEL))
    for n, why in blocked:
        print("   － 第%2d题 %s" % (n, why))
    if not cands:
        print("   没有需要新判的候选题")
        return 0
    if not KEY:
        print("   没有 DEEPSEEK_API_KEY，跳过 ④c —— 候选题一律不做动画（fail-closed）")
        return 1

    rows = ask(PROMPT + "\n\n" + payload_for(cands))
    by_n = {q["n"]: q for q, _ in cands}
    picked = []
    for r in rows:
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if n not in by_n:
            continue
        why = (r.get("why") or "").strip()[:80]
        try:
            score = float(r.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        picked.append((score, n, bool(r.get("need")), why))

    # 模型没提到的候选题一律判为不做 —— 缺信息时保守，别把时间花在没依据的题上
    seen = {n for _s, n, _need, _w in picked}
    for n in by_n:
        if n not in seen:
            picked.append((0.0, n, False, "④c 没给出判断，保守起见不做"))

    picked.sort(key=lambda x: (-x[0], x[1]))
    yes = [p for p in picked if p[2]][:a.max]
    cut = [p for p in picked if p[2]][a.max:]
    yes_n = {p[1] for p in yes}

    for score, n, need, why in picked:
        mark = "✓" if n in yes_n else "－"
        note = why
        if need and n not in yes_n:
            note = "排在 --max %d 之外（增量 %.0f 分）：%s" % (a.max, score, why)
        print("   %s 第%2d题 %s" % (mark, n, note))
        store.put_worth(by_n[n]["id"], n in yes_n, note)

    print("   要做动画 %d 道，不做 %d 道%s"
          % (len(yes), len(picked) - len(yes),
             ("（其中 %d 道是被上限截掉的）" % len(cut)) if cut else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
