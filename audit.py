#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit.py —— 逐题体检

    .venv/bin/python audit.py [卷名前缀…]

对切分与公式还原的结果做静态自查，把**可疑**的题挑出来，供人对照原卷复核。
它不判断对错，只回答「哪些地方值得人去看一眼」。

**查的是库，不是工作目录。** 体检对象必须和页面上呈现的是同一份数据 ——
以前扫 work/_batch/ 的 questions.json，而 Web 读的是另一棵树，
出现过「体检全绿、页面上还是旧结果」。没 publish 就不算数，这里也一样。

检查项分两类：

结构类（切分是否可信）
  · 题干过短 / 过长
  · 选择题选项数不是 4
  · 选项互相重复 —— 公式被压平最典型的后果就是 A、B 长得一模一样
  · 插图重复归属
  · 题干里混进了下一题的题型标记

公式类（还原是否可信）
  · 括号不配对
  · 残留压平痕迹（字母紧跟多位数字、`]12` 这类）
  · 出现 `^(` / `_(` 兜底写法（说明没能转成正常上下标）
  · 分式的一侧为空
  · MathML 标签不配对
"""
import os, re, sys, collections

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))
import segment          # 跨页表怎么合并，以管线里那份判据为准
import store            # 体检的对象是库，和页面读的是同一份数据

FLAT = re.compile(r"[A-Za-zΩωπρμ]\s?\d{2,}|\]\d+|\d+[A-Za-z]{1,2}\d+")
TRIG = re.compile(r"(sin|cos|tan|cot|sec|csc)\s?\d")


def flat_hits(t):
    """
    压平痕迹。

    `sin37°`「字母紧跟两位数字」天生就长这样，不是痕迹 —— 而物理卷里
    `sin37°=0.6` 这类给定值极其常见，实测占全部命中的四成。
    误报多了这份报告就没人看了，所以专门放过三角函数。
    """
    return [m.group(0) for m in FLAT.finditer(t)
            if not TRIG.match(t, max(0, m.start() - 2))]
TYPEWORD = re.compile(r"(单选题|多选题|填空题|实验题|计算题|解答题|作图题|论述题|综合题)")


def balanced(t):
    """括号配平。全角半角一起数 —— 原卷本身就混用（如 `（选填…"D")`），
    分开数会产生一堆与解析无关的误报。"""
    d = 0
    for ch in t:
        d += (ch in "(（") - (ch in ")）")
        if d < 0:
            return False
    return d == 0


def check_question(q):
    out = []
    stem = q["stem"]
    opts = q.get("options", [])
    texts = [o["text"] for o in opts]

    # ---- 结构 ----
    n = q.get("n_chars", len(stem))
    # 「下列说法正确的是（ ）」这类题干本来就只有十来个字，只要选项齐全就不算异常
    if n < 25 and len(opts) != 4:
        out.append(("结构", "题干只有 %d 字且选项不全，疑似切断" % n))
    if n > 900:
        out.append(("结构", "题干 %d 字，疑似吞并了下一题" % n))
    if q["type"] in ("单选题", "多选题") and len(opts) != 4:
        out.append(("结构", "%s 却解析出 %d 个选项" % (q["type"], len(opts))))
    dup = [t for t, c in collections.Counter(t for t in texts if t.strip()).items() if c > 1]
    if dup:
        out.append(("结构", "选项内容重复：%s —— 公式压平最典型的后果" % "、".join(dup)[:60]))
    inner = TYPEWORD.findall(stem[20:])
    if inner:
        out.append(("结构", "题干里出现题型标记 %s，疑似吞并了下一题" % "、".join(set(inner))))

    # ---- 表格占位符 ----
    # 表是从题干里摘走的，靠 〔表N〕 占位符插回原位。
    # 占位符缺失 = 表不会显示；数量不符 = 表插在错误的位置。
    # 后者尤其危险：页面看起来完全正常，只是位置错了。
    tabs = q.get("tables", [])
    if tabs:
        body = q.get("stem_latex") or stem
        marks = re.findall(r"〔表(\d+)〕", body)
        # 跨页续表不该有自己的占位符 —— 它并进上半张一起渲染
        want = {str(t["id"]) for t in tabs if not t.get("cont_of")}
        if set(marks) != want:
            out.append(("表格", "占位符 %s 与检出的表 %s 对不上——表会插错位置或不显示"
                        % (sorted(marks) or "无", sorted(want))))
        for w in segment.merge_warnings(tabs):
            out.append(("表格", w))
        for t in segment.merged_tables(tabs):
            if not t.get("rows"):
                out.append(("表格", "表%d 没有转写内容" % t["id"]))
            elif len({len(r) for r in t["rows"]}) > 1:
                out.append(("表格", "表%d 各行列数不一致：%s"
                            % (t["id"], [len(r) for r in t["rows"]])))

    # ---- 公式 ----
    for label, t, ms in ([("题干", stem, q.get("stem_math", []))] +
                         [("选项" + o["key"], o["text"], o.get("math", [])) for o in opts]):
        if not t.strip():
            continue
        if not balanced(t):
            out.append(("公式", "%s 括号不配对：%s" % (label, t[:70])))
        hits = flat_hits(t)
        if hits:
            out.append(("公式", "%s 残留压平痕迹 %s：%s" % (label, hits[:3], t[:70])))
        if "^(" in t or "_(" in t:
            out.append(("公式", "%s 用了 ^()/_() 兜底写法：%s" % (label, t[:70])))
        if re.search(r"\(\)/|/\(\)|/\s*$|^\s*/", t):
            out.append(("公式", "%s 分式一侧为空：%s" % (label, t[:70])))
        for m in ms:
            ml = m["mathml"]
            for tag in ("math", "mfrac", "msqrt", "msup", "msub", "mrow"):
                if ml.count("<%s>" % tag) != ml.count("</%s>" % tag):
                    out.append(("公式", "%s 的 MathML 标签 <%s> 不配对" % (label, tag)))
                    break
    return out


def main():
    want = sys.argv[1:]
    names = [r["name"] for r in store.list_papers()]
    if want:
        names = [n for n in names if any(w in n for w in want)]
        if not names:
            print("库里没有匹配 %s 的试卷" % "、".join(want))
            return 1
    tot_q = tot_flag = 0
    by_kind = collections.Counter()

    for p in sorted(names):
        data = store.get_paper(p)
        if not data:
            continue
        flags = []
        for q in data["questions"]:
            tot_q += 1
            issues = check_question(q)
            if issues:
                tot_flag += 1
                flags.append((q["n"], issues))
                for k, _ in issues:
                    by_kind[k] += 1
        mark = "✓" if not flags else "!"
        print("%s %-38s %2d 题，%d 题可疑" % (mark, p[:38], len(data["questions"]), len(flags)))
        for n, issues in flags:
            for k, msg in issues:
                print("      第%2d题 [%s] %s" % (n, k, msg))

    print("─" * 72)
    print("共 %d 题，%d 题被标记（%.1f%%）；结构类 %d 条，表格类 %d 条，公式类 %d 条"
          % (tot_q, tot_flag, 100.0 * tot_flag / max(1, tot_q),
             by_kind["结构"], by_kind["表格"], by_kind["公式"]))
    print("提示：被标记 ≠ 错。这只是把值得人对照原卷看一眼的地方挑出来。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
