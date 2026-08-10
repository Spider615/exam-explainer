#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sheetverdict.py —— Ⓒ：把 Ⓑ 读出来的东西变成判定

**纯函数，没有 IO。** 这条链上判据最密的一段，也是唯一能被测厚的一段 ——
混进 `sheetread.py` 会被模型调用的桩淹掉。

三件事：

  `bind`        题号绑到参考答案的清单上（**按大题的小问集合比**）
  `decide`      由分数/符号推 `verdict`（**分数优先**）
  `crosscheck`  跟 `grade.judge` 和老师红笔写的正确答案互校（**只报不改**）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grade
import verdicts


def _main(n):
    """1301 → 13；9 → 9。小问编号约定 `主题号*100 + 小问号`"""
    return n // 100 if n >= 100 else n


def _sub(n):
    return n % 100 if n >= 100 else 0


def _show_subs(ns):
    """[1301, 1302, 1304] → `(1)(2)(4)`；没有小问回空串"""
    return "".join("(%d)" % _sub(n) for n in sorted(ns) if _sub(n))


def bind(rows, known_ns):
    """
    把答题卡上的题号绑到参考答案给出的那份清单上。

    返回 `(行, 整题级告警)`。每行多一个 `bind` 键：绑上了就是那个题号，
    绑不上是 `None`。

    **按整道大题的小问编号集合比，不逐条比。** 这是这一轮最隐蔽的一条：

    实测答题卡第 13 题印的小问编号是 `(1)(2)(4)(5)`，参考答案是 `(1)(2)(3)(4)`。
    按 `n = 主题号*100 + 小问号` 算，答题卡侧是 1301/1302/**1304**/1305，
    参考答案侧是 1301/1302/1303/1304 —— **三条精确等于一个已存在的题号**。

    逐条绑的话，这三条全绑到题上了，只有 1305 挂不上，页面只会说「有 1 条挂
    不上」；而卡上的 (4) 实际对应答案的 (3)（按满分序列 2/1/2/1 核实过），
    于是「你写的 X / 标准答案 Y」那一栏拿的是**另一小问**的答案，互校要么冒
    一条查无实据的不一致、要么两边碰巧一样而全线沉默。

    设计里那道「不许猜一个最近的题号安上去」的防线**拦不住它** ——
    那条防的是「猜」，而这是精确相等。

    所以规矩是：**某道大题的小问集合与参考答案不完全相等时，这道大题下所有
    小问一律不绑**，整题单独列出来请老师认。少写一个小问也算不等 ——
    前几条看起来能对上，但少一条就说明两边的编号体系未必是一回事。

    这四条按满分序列恰好能一一对上，但那是这一份材料的巧合，不是判据。
    """
    known = set(known_ns)
    by_main = {}
    for n in known:
        by_main.setdefault(_main(n), set()).add(n)

    got_main = {}
    for r in rows:
        got_main.setdefault(_main(r["n"]), set()).add(r["n"])

    ok_mains, warn = set(), []
    for m, ns in sorted(got_main.items()):
        ref = by_main.get(m)
        if ref is None:
            warn.append({"main": m,
                         "why": "参考答案里没有第 %d 题 —— 答题卡上这 %d 条挂不上，"
                                "多半是题号读错了，或者学生多写了一道"
                                % (m, len(ns))})
        elif ns == ref:
            ok_mains.add(m)
        else:
            warn.append({"main": m,
                         "why": "第 %d 题的小问编号对不上：答题卡上是 %s，"
                                "参考答案上是 %s。这道大题下的 %d 条都没有挂到题上 —— "
                                "请你认一下哪条对哪条"
                                % (m, _show_subs(ns) or "（无小问）",
                                   _show_subs(ref) or "（无小问）", len(ns))})

    out = [dict(r, bind=(r["n"] if _main(r["n"]) in ok_mains else None))
           for r in rows]
    return out, warn


def decide(row):
    """
    这一行该判什么。返回 `(verdict, verdict_by, 一句人话)`。

    优先级：**卷子上印的分数 > 红勾红叉 > 说不清。**

    分数排第一是探针推翻原设计的结果：实测 12(3) 老师打的是**红勾**，
    给的却是 `1分(满分2分)` —— 标准答案 `AB`、学生只写了 `A`，双选题
    「选对但不全得一半」。红勾在这里的意思是「这行判过了」，不是「全对」。
    只看勾叉，这道题会被记成掌握了。

    **「读不出来」一律判 `unsure`，绝不判 `blank`。** 这两件事在页面上是
    两句完全不同的话：`blank` 会被写成「这孩子没写」，而事实是「我们没读出来」；
    更要命的是 `blank` 分子分母都不进（`verdicts.COUNTED`），
    那道题会从薄弱统计里整个消失 —— 而错题正是这个功能唯一的产出。
    """
    got, full = row.get("got"), row.get("full")
    v = verdicts.of_score(got, full)
    if v is not None:
        # 有分数但一分没得，还要分「答错了」和「压根没写」
        if v == "wrong" and str(row.get("answer") or "").strip() == "blank":
            return "blank", "teacher_score", "这道题空着，0 分（满分 %g）" % float(full)
        return v, "teacher_score", "老师给了 %g 分（满分 %g）" % (float(got), float(full))

    mark = row.get("mark")
    if mark in ("right", "wrong", "half"):
        m = {"right": "right", "wrong": "wrong", "half": "partial"}[mark]
        word = {"right": "红勾", "wrong": "红叉", "half": "勾上带叉"}[mark]
        return m, "teacher_mark", "卷子上这道题只有%s，没有分数标注" % word

    ans = str(row.get("answer") or "").strip()
    if ans == "blank":
        return "blank", "teacher_mark", "这道题空着，而且没有批改符号"
    if ans in ("", "unreadable"):
        return "unsure", "teacher_mark", "学生写的什么没读出来，也没有分数和批改符号"
    return "unsure", "teacher_mark", "读到了作答，但没有分数、也没有批改符号"


def crosscheck(row, ref_answer):
    """
    白捡的红绿灯：拿学生作答和标准答案跑一遍 `grade.judge`，跟老师的判定对。
    不一致回一句人话，一致或比不了回 `None`。**只报，不改数据。**

    三条不许报的：

    · **`partial` 不算不一致。** `grade.judge("A", "AB")` 回 `wrong`，
      老师给的是 `partial` —— 这不是矛盾，是代码档判等本来就没有「部分对」
      这一档。算成异常的话，每道双选半对题都会冒一条假警告，
      而**真正的异常会被淹掉**。
    · `grade.judge` 回 `None` 是常态（长解答题），不算异常。
    · 判定本身是 `unsure` / `blank` 时不比 —— 有一边说不清，结论没有意义。

    另外还比一次**老师红笔写在旁边的正确答案**（实测题 6 写了 `BC`、
    题 8 写了 `AC`）：它跟参考答案对不上，说明 Ⓐ 那一栏抽错了。
    这是第三份对照，一分钱不花。
    """
    if not ref_answer:
        return None
    red = str(row.get("red") or "").strip()
    if red:
        v, _ = grade.judge(red, ref_answer)
        if v == "wrong":
            return ("老师在旁边红笔写的正确答案是「%s」，而参考答案里抽出来的是"
                    "「%s」—— 两边对不上，多半是参考答案那一栏读错了"
                    % (red, ref_answer))

    verdict = row.get("verdict")
    if verdict not in ("right", "wrong"):
        return None
    ans = str(row.get("answer") or "").strip()
    if ans in ("", "blank", "unreadable"):
        return None
    v, why = grade.judge(ans, ref_answer)
    if v is None or v == verdict:
        return None
    return ("系统按标准答案判「%s」，老师判的是「%s」（%s）—— "
            "请对照原图：要么学生的作答读错了，要么参考答案抽错了，"
            "要么这道题批错了"
            % ("对" if v == "right" else "错",
               "对" if verdict == "right" else "错", why))
