#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grade.py —— 判对错的归一化

**纯函数，不碰网络也不碰库。** 阅卷的全部正确性判断都在这里，所以它必须
能单独测，而且要测厚。

只做不会静默出错的两件事
------------------------
归一化字符串比、数值比。它们要么明确相等要么明确不等，没有第三种。

**不引 sympy。** 它解析带单位带下标的中文物理题 LaTeX 容易翻车，而翻车的
样子是「静默给出一个错误的等价判断」—— 学生答对的题被判错，凭空造出一个
薄弱知识点，页面上一切看起来正常。

判不了就说判不了
----------------
`judge` 回 `(None, 原因)` 表示代码档下不了结论，交给模型档。**绝不猜。**
判错的代价是不对称的：判对了没人受损，判错了会凭空造出一个假的薄弱知识点，
而薄弱知识点是这整个功能唯一的产出。

三个踩过的坑，都写成了测试
--------------------------
1. **单位必须有边界。** 不设白名单的话，「2mv」会被解析成「数值 2 + 单位 mv」，
   于是 `2mv` 和 `2Mv` 判等 —— 一个静默的错误等价判断，正是这里最怕的。
   只有认识的物理单位才算单位；不认识就说明这根本不是「数值+单位」，
   该走表达式那条路。
2. **单位大小写不能抹。** `m` 是米、`M` 可能是兆；`mgh` 和 `mgH` 不是一回事。
3. **`/` 有歧义**：既是分数线（3/2）又是多空分隔符（小于/等于/小于）。
   两边都能整体读成数值时按数值走，否则才按多空拆。
"""
import re, unicodedata

# 归一化时可以安全丢掉的标点。**不含 `/`** —— 它既是单位分隔符（m/s）
# 又是多空分隔符，丢了会把两个不同的答案压成一个
_PUNCT = re.compile(r"[\s。，、；：．,;:!？?（）()【】\[\]]+")
_CHOICE = re.compile(r"[A-D]+")
_HAS_ALPHA = re.compile(r"[A-Za-z]")

# 数值部分：`1.5`、`3/2`、`1.6e-19`、`1.6×10^-19`。**尾巴原样留着**，
# 是不是单位由 _unit_ok 另判
_NUM = re.compile(r"""^\s*
    (?P<sign>[-+])?\s*
    (?: (?P<a>\d+(?:\.\d+)?)\s*[×xX*]\s*10\s*\^?\s*(?P<exp>[-+]?\d+)
      | (?P<b>\d+(?:\.\d+)?)\s*[eE]\s*(?P<exp2>[-+]?\d+)
      | (?P<num>\d+(?:\.\d+)?)\s*/\s*(?P<den>\d+(?:\.\d+)?)
      | (?P<c>\d+(?:\.\d+)?) )
    \s*(?P<tail>.*)$""", re.X | re.S)

# 认识的物理单位。**白名单，不是「看起来像就算」** —— 见模块开头第 1 条。
# 长的排在前面，免得 `ms` 被 `m` 抢先匹配掉
_ATOM = ("mol|MeV|keV|min|rad|kg|cm|mm|km|nm|ms|Hz|Pa|eV|°C|Ω|μm|μs"
         "|m|s|g|h|N|J|W|V|A|C|T|K|L|°|%")
_UNIT = re.compile(r"^(?:%s)(?:\^?-?\d)?(?:[/·*](?:%s)(?:\^?-?\d)?)*$" % (_ATOM, _ATOM))

_SUBSUP = {"₀": "_0", "₁": "_1", "₂": "_2", "₃": "_3", "₄": "_4",
           "₅": "_5", "₆": "_6", "₇": "_7", "₈": "_8", "₉": "_9",
           "⁰": "^0", "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4",
           "⁵": "^5", "⁶": "^6", "⁷": "^7", "⁸": "^8", "⁹": "^9"}

# 归一化后超过这么长，或两边长度差这么多倍，就不敢判不等 —— 交给模型
LONG = 40
RATIO = 3


def norm_text(s):
    """NFKC 折全角、去空白与标点、转大写。**只给不含字母的答案用**。"""
    if s is None:
        return ""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", str(s)).strip().upper())


def as_choice(s):
    """纯 A-D 字母时回排序去重后的字母串，否则 None。"""
    t = norm_text(s)
    if not t or not _CHOICE.fullmatch(t):
        return None
    return "".join(sorted(set(t)))


def _lead_number(s):
    """
    读出开头的数值，回 `(值, 尾巴原文)`；读不出回 None。

    尾巴是不是单位这里不判 —— 那是 `unit_ok` 的事。分开是因为「数值相同
    但单位对不上」和「根本不是数值」要给出两种不同的结论。
    """
    if s is None:
        return None
    t = unicodedata.normalize("NFKC", str(s)).strip()
    m = _NUM.match(t)
    if not m:
        return None
    g = m.groupdict()
    if g["a"] is not None:
        # 用字符串拼出来再 float，不要 1.6 * 10**-19 ——
        # 浮点乘幂会给出 1.6000000000000002e-19
        v = float("%se%d" % (g["a"], int(g["exp"])))
    elif g["b"] is not None:
        v = float("%se%d" % (g["b"], int(g["exp2"])))
    elif g["num"] is not None:
        den = float(g["den"])
        if den == 0:
            return None          # 除零不许炸，也不许给个假值
        v = float(g["num"]) / den
    else:
        v = float(g["c"])
    if g["sign"] == "-":
        v = -v
    return (v, (g["tail"] or "").strip())


def unit_ok(tail):
    """这段尾巴是不是一个**认识的**物理单位（空也算）。见模块开头第 1 条。"""
    t = _PUNCT.sub("", unicodedata.normalize("NFKC", str(tail or "")).strip())
    return t == "" or bool(_UNIT.fullmatch(t))


def unit_of(tail):
    """归一化后的单位原文。**不转大小写** —— m 是米、M 可能是兆。"""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", str(tail or "")).strip())


def as_number(s):
    """`(值, 单位)`；不是「数值 + 认识的单位」就回 None。"""
    r = _lead_number(s)
    if r is None or not unit_ok(r[1]):
        return None
    return (r[0], unit_of(r[1]))


def norm_expr(s):
    """
    LaTeX 归一化：去空白、`\\dfrac`→`\\frac`、`·`→`\\cdot`、上下标统一。

    **不动大小写。** 见模块开头第 2 条。
    """
    t = unicodedata.normalize("NFC", str(s or ""))
    for k, v in _SUBSUP.items():
        t = t.replace(k, v)
    t = t.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    t = t.replace("·", "\\cdot").replace("×", "\\times")
    t = re.sub(r"\^\{([^{}])\}", r"^\1", t)     # ^{2} → ^2
    t = re.sub(r"_\{([^{}])\}", r"_\1", t)
    return re.sub(r"\s+", "", t)


def split_blanks(s):
    """多空答案按 `/` 拆。`小于 / 等于 / 小于` → 三个空。"""
    return [x.strip() for x in re.split(r"\s*/\s*", str(s or "")) if x.strip()]


def _wordy(s):
    """不含 ASCII 字母 —— 这类答案（「小于」「向右」）大小写本来就无意义。"""
    return not _HAS_ALPHA.search(str(s or ""))


def _same_value(x, y):
    """相对误差 1e-6 内算相等。`0.40` 和 `0.4` 是同一个答案。"""
    return x == y or abs(x - y) <= 1e-6 * max(abs(x), abs(y), 1e-12)


def judge(student, ref):
    """
    代码档判定。回 `('right'|'wrong', 理由)`，或 `(None, 为什么判不了)`。

    判不了不是失败，是**明确地把结论交出去**。绝不猜。
    """
    if not str(student or "").strip() or not str(ref or "").strip():
        return (None, "有一边没有内容，判不了")

    # 选择题
    ca, cb = as_choice(student), as_choice(ref)
    if ca is not None and cb is not None:
        return ("right", "选项集合相等") if ca == cb else \
               ("wrong", "选了 %s，标准答案 %s" % (ca, cb))

    # 数值。**排在多空之前** —— `3/2` 是分数不是两个空（模块开头第 3 条）
    la, lb = _lead_number(student), _lead_number(ref)
    if la and lb and (unit_ok(la[1]) or unit_ok(lb[1])):
        if not _same_value(la[0], lb[0]):
            return ("wrong", "%g 不等于 %g" % (la[0], lb[0]))
        ua, ub = unit_of(la[1]), unit_of(lb[1])
        if ua == ub:
            return ("right", "数值与单位都相同")
        return (None, "数值一样但单位对不上（%s vs %s），判不了"
                      % (ua or "无单位", ub or "无单位"))

    # 多空
    sb_, rb_ = split_blanks(student), split_blanks(ref)
    if len(rb_) > 1 or len(sb_) > 1:
        if len(sb_) != len(rb_):
            return (None, "空的个数对不上（学生 %d 个、标准答案 %d 个），判不了"
                          % (len(sb_), len(rb_)))
        for i, (a, b) in enumerate(zip(sb_, rb_), 1):
            v, w = judge(a, b)
            if v is None:
                return (None, "第 %d 空判不了：%s" % (i, w))
            if v == "wrong":
                return ("wrong", "第 %d 空不对（%s ≠ %s）" % (i, a, b))
        return ("right", "%d 个空全对" % len(rb_))

    # 表达式 / 文字
    ea, eb = norm_expr(student), norm_expr(ref)
    if ea == eb:
        return ("right", "归一化后完全相同")
    if _wordy(student) and _wordy(ref) and norm_text(student) == norm_text(ref):
        return ("right", "文字归一化后相同")

    # 敢不敢判「不等」：只有两边都短、长度也不悬殊时才敢。
    # 长答案里同一个意思有一百种写法，而判错的代价是不对称的
    lo, hi = sorted((len(ea), len(eb)))
    if hi > LONG or hi > RATIO * max(lo, 1):
        return (None, "形式差得远（%d 字 vs %d 字），代码判不了" % (len(ea), len(eb)))
    return ("wrong", "归一化后不同：%s ≠ %s" % (ea, eb))
