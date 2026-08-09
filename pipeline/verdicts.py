#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verdicts.py —— 判定的值域，**全项目只有这一份**

`verdict` 的取值原来抄在四处：`store._VERDICTS`、`schema.sql` 的注释、
`set_teacher_verdict` 的报错文案、`list_sheets` 那句 `='wrong'` 的汇总。
加一个值只改一处，后果全是静默的 —— 老师改不出「半对」（白名单挡下来），
而列表里的「错 N 道」把 `partial` 漏掉，一张 8 道半对的卡显示「错 2 道」。

和 `modes.py` 是同一个病、同一个治法（阶段清单抄三份，历史上两次事故都是抄漏
一份）：**只留一份，别处指过来**，报错文案由清单拼出来而不是再抄一遍。
"""

#: 判定。**顺序有意义**：从「全对」到「说不清」，页面上按这个顺序排。
#:
#:   right    拿了满分
#:   partial  拿了一部分 —— 本轮新增。双选题「选对但不全得一半」是印在卷子上的
#:            评分规则，不是边角情况；实测 12(3) 老师打了红勾却只给 1分(满分2分)
#:   wrong    一分没拿，而且有作答
#:   blank    该题没有作答。**分子分母都不进**
#:   unsure   分数和符号都读不出，或者题号挂不上参考答案。**分子分母都不进**
VERDICTS = ("right", "partial", "wrong", "blank", "unsure")

#: 谁判的。可信度差一个量级，页面必须分得出来。
#:
#:   teacher_score  照卷子上印的得分判（**优先**，最可信）
#:   teacher_mark   照红勾红叉判（读不到得分时退回这条）
#:   code           grade.judge 判的（只用来互校，不当判据）
#:   model          模型判的
#:   teacher        老师在页面上改判的（最终）
VERDICT_BY = ("teacher_score", "teacher_mark", "code", "model", "teacher")

#: 进薄弱统计的只有这三档。`blank` / `unsure` 不是「答错了」——
#: 把它们算进去，一张读得不好的卡会凭空造出一堆假薄弱点。
COUNTED = ("right", "partial", "wrong")


def check(v):
    """校验一个判定值，不合法当场抛。回它本身，好写成 `x = check(x)`。"""
    if v not in VERDICTS:
        raise ValueError("verdict 只能是 %s，给的是 %r" % ("/".join(VERDICTS), v))
    return v


def check_by(b):
    """校验判定来源，不合法当场抛。回它本身。"""
    if b not in VERDICT_BY:
        raise ValueError("verdict_by 只能是 %s，给的是 %r"
                         % ("/".join(VERDICT_BY), b))
    return b


def of_score(got, full):
    """
    由卷子上印的得分推判定。回 `verdict`，或 `None`（分数不全，推不出来）。

    **这是判定的第一优先级，排在红勾红叉前面。** 实测 12(3)：标准答案 `AB`、
    学生只写了 `A`、老师**打了红勾**，给的却是 `1分(满分2分)` —— 双选题
    「选对但不全得一半」。红勾在这里的意思是「这行判过了」，不是「全对」。
    只看勾叉的话，这道题会被记成掌握了。

    `got > full` 判 `right` 不判 `partial`：多半是加分题或者读串了，
    而判成 `partial` 会让它进薄弱统计 —— 那是反的。
    """
    if got is None or full is None or full <= 0:
        return None
    if got >= full:
        return "right"
    if got <= 0:
        return "wrong"
    return "partial"
