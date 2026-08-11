#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sheetread.py —— Ⓑ：读已批改答题卡上的作答、批改符号和得分

    python pipeline/sheetread.py <卷名> --sheet <id> <页图1> [页图2 ...]

**两遍，不是整页读一遍。**（2026-08-10 探针实测，数字见设计文档文末）

  Ⓑa  整页原分辨率（540×750）  → {n, y, answer, mark, conf}
  Ⓑb  按 y 切条、每条放大 3×   → {n, filled, mark, got, full, red, conf}
  Ⓑc  左上角总分那一小块 ×3    → {total}

整页读一遍那条路验过了，它在两处**必然**丢东西：选择题填涂 8 道全认不出
（模型自己标 `conf: low`，是老实的），得分 10 条错 2 条 —— 而错的那条正是
12(3) 的 `1分(满分2分)` 被读成 `1分(满分1分)`，把「半对」抹成了「全对」。
同一块裁出来单独放大 3× 再问，两样都是满分，还快 4 倍。

固定横条也验过了（4 条重叠切片），不行：切口从大题中间穿过时模型只看得见
`(1)`、看不见 `13.`，13 题四个小问的题号全裸奔；得分漏了一半，墙钟还更长。
所以**框由第一遍的 `y` 给** —— 这套做法 `stemread.py`（Ⓔ）已经在原卷上跑通。

三条硬规矩
----------
1. **Ⓑa 不许问选择题的填涂。** 实测同一张图两次：不提的时候 8 道全
   `unreadable` + `conf: low`，一个都没编；写了「填涂式的选择题也要」之后
   答了 6/8，错的两条里有一条把老师红笔写的正确答案当成了学生的作答。
   逼模型回答会把诚实的弃权变成自信的错误。
2. **Ⓑb 的提示词直接写明这一条是第几题**（Ⓑa 已经知道了），模型不必再读题号 ——
   「题号裸奔」那个失败模式因此整个消失。
2b. **勾叉两遍都读。** 2026-08-10 实跑：选择题 6/7/8 判成了「说不清」——
   作答读对了，但那几行**没有印分数**，而 Ⓑa 那一次没给出它们的勾叉。
   1-5 同样没分数却判对了，说明是模型逐行的不稳定。Ⓑb 看的是放大 3 倍的条，
   探针在同一块上勾叉读了 8/8，让它也报一份，合并时谁读到算谁的。
3. **Ⓑc 必须单独一次调用、单独一块裁图，且与 Ⓑb 的裁条不重叠。**
   总分和逐题得分同源的话，「Σ得分对总分」就成了自证。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mathvlm
import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 一条里最多装几道题、最高多少像素。**两个上限都来自探针里成功的那两个裁块**：
#: 选择题块 530×105 装 8 道（8/8），得分块 390×260 装 8 行（8/8）。
#:
#: 不能只设「最小高度」然后把挨太近的往一起并 —— 实测那样会把整页并成一条
#: （9→10 差 30px、10→11 差 28px、11→12(1) 差 52px，一路都低于任何合理的下限），
#: 而「整页读一遍」正是被探针否掉的那条路。
MAX_PER_STRIP = 8
MAX_STRIP_H = 260
#: 一条再怎么也不该比这还薄 —— 那说明位置估崩了，继续往下并
MIN_STRIP_H = 24
#: 上边留多少（相对高度）。**比 Ⓔ 的 0.012 大得多** —— 得分标注印在作答行的
#: 上方，留少了会把标注切给上一条（实测第 11 题那条里带着 12(1) 的分数标注）
PAD = 0.05
#: 切条放大几倍。实测 3 倍时填涂 8/8、得分 8/8；整页放大 2 倍反而开始编答案
ZOOM = 3

#: 「读不出来」的哨兵值。**它们是读取状态，不是作答内容** ——
#: 合并的时候要给真读出来的让路，而且不许算成两遍不一致
BLANKS = ("", "unreadable", "blank", None)

#: 批改符号里的「没看见」。合并时和上面那几个一个待遇。
#:
#: `none` 的意思是「这一行我没看见批改符号」，**不是**「这一行确实没有符号」——
#: 拿它盖掉另一遍**看见了**的读数，正好把有信息的那条丢了。
#: 2026-08-10 实跑：选择题 6/7/8 判成「说不清」，1-5 判对，差别就在这一栏。
MARK_BLANKS = ("", "none", "unknown", None)


PROMPT_A = """这是一张**已批改**物理答题卡的一整页（学生手写作答 + 老师红笔批改）。

逐题读出来，按从上到下的顺序，每题一个对象：

  n       题号。小问写成 "12(1)"。看不清写 null
  y       **这道题（或这个小问）所在那一行的位置**，用 0 到 1 之间的小数表示
          它距离页面顶端的相对高度。页面最上面是 0，最下面是 1。
          这个数是后续裁图用的，**必须随题号从小到大递增**
  answer  学生手写的作答，原样转写，数学式子用 LaTeX。
          整题空着写 "blank"，写了但认不出写 "unreadable"
  mark    老师批的符号："right" 红勾 / "wrong" 红叉 / "half" 勾上带叉 / "none" 没有
  conf    "high" / "low"

**填涂式的选择题只报题号和 y，answer 一律写 "unreadable"** —— 那种填涂在这个
分辨率下看不准，后面有单独一步放大了读。不要猜。

只输出 JSON 数组，不要别的话。"""

PROMPT_B = """这是一张**已批改**物理答题卡的一条横切片，已经放大过。
这一条里有这几道题：%s。

只读这几道题，每题一个对象：

  n       题号，就用上面给的那几个之一
  filled  如果这题是**填涂式选择题**：学生涂黑的字母，如 "D" 或 "AC"。
          一个都没涂写 "blank"，看不清写 "unreadable"。不是填涂题写 null
  mark    老师批在这一行的符号："right" 红勾 / "wrong" 红叉 /
          "half" 勾上带叉 / "none" 这一行确实没有符号
  got     红色得分标注里得了几分，数字。没有标注写 null
  full    红色得分标注里的满分，数字。没有标注写 null
  red     老师用红笔在这一行**写的字**（通常是正确答案）。没有写 null
  conf    "high" / "low"

三条要求：
· `filled` 只报**学生涂黑的**，老师红笔写的一律进 `red`。这两样绝不能混。
· 得分标注形如「1分(满分2分)」，通常印在作答行的**右上方**。
· **`mark` 要认真读**：选择题那几行**没有分数标注**，红勾红叉是判对错的唯一依据。
  这一条已经放大过，看得清 —— 看不清才写 "none"，不要因为省事写 "none"。

只输出 JSON 数组，不要别的话。"""

PROMPT_C = """这是一张已批改答题卡的**左上角**，已经放大过。

那里印着这次考试的**总分**（一个数字，可能带小数）。读出来。

只输出 JSON 对象：{"total": 数字}。没看到总分就写 {"total": null}。
不要把某一道题的得分当成总分 —— 总分印在页眉附近，不挨着任何一道题。"""


def strips(marks, height, max_n=MAX_PER_STRIP, max_h=MAX_STRIP_H, pad=PAD):
    """
    这一页切成横条。**纯函数**，返回 `[(题号列表, 上, 下)]`（像素）。

    `marks` 是 `[(题号, y)]`，`y` 是那一行的相对高度（0~1）。

    **按探针里验过的形状打包**，一条装到「够 8 道题」或「够 260 px」为止。
    那两个数来自探针中成功的两个裁块：选择题块 530×105 装 8 道（8/8）、
    得分块 390×260 装 8 行（8/8）。

    **不能反过来按「最小高度」把挨太近的往一起并** —— 实测那样会把整页并成
    一条（9→10 差 30px、10→11 差 28px、11→12(1) 差 52px，一路都低于任何合理的
    下限），而「整页读一遍」正是被探针否掉的那条路。这一版就是这么写错过一次。

    和 `stemread.slices` 还有两处**故意**不一样：

    **（一）一条里可以有多道题。** Ⓔ 是一题一条（那是给人看的成品），
    Ⓑ 的条只是喂给模型的输入，提示词里会写明这一条要读哪几道题。

    **（二）上边留得多（`pad=0.05` 对 `0.012`），条与条允许重叠。**
    得分标注印在作答行的**上方**，留少了会把标注切给上一条
    （实测第 11 题那条里带着 12(1) 的「1分(满分1分)」）。

    **y 不单调时，只丢破坏单调的那几条**，不是整页不切 ——
    详见 `strips_report`（初版就是整页不切，被第二轮实跑打了脸）。
    要知道丢了哪几道题，用 `strips_report`。
    """
    return strips_report(marks, height, max_n, max_h, pad)[0]


#: 单调修复之后至少要留下多少才肯切。留不下这么多就说明位置整体估崩了 ——
#: 那时候切出来每一条都对不上题号，宁可这一页没有第二遍
KEEP_FRAC = 0.6
KEEP_MIN = 3


def strips_report(marks, height, max_n=MAX_PER_STRIP, max_h=MAX_STRIP_H,
                  pad=PAD):
    """
    同 `strips`，但连**丢掉了哪几道题**一起回：`(条, 丢掉的题号)`。

    **一条坏的 `y` 不该废掉整页。** 初版是「y 不按题号递增就整页不切」，
    2026-08-10 第二轮实跑打了脸：Ⓑa 那一次给出的 18 条里有一条 y 乱了，
    于是整页一条都没切，Ⓑb **一次都没被调用** —— 选择题填涂全丢、
    12(3) 的分数没读到、判定从 `partial` 回退成 `right`。

    现在按题号顺序取 **y 严格递增的最长子序列**，破坏单调的那几条丢掉并报出来；
    留不下多数（见 `KEEP_FRAC` / `KEEP_MIN`）才整页不切 —— 那时候是位置整体
    估崩了，切出来每一条都对不上题号。

    **丢了几条必须说出来**：静默丢弃和静默失败一样糟。
    """
    marks = [(n, float(y)) for n, y in marks
             if isinstance(y, (int, float)) and 0 <= y <= 1]
    if not marks:
        return [], []
    marks = sorted(marks, key=lambda t: t[0])

    # 按题号顺序、y 严格递增的最长子序列（n 不大，O(n²) 足够）
    best = [1] * len(marks)
    prev = [-1] * len(marks)
    for i in range(len(marks)):
        for j in range(i):
            if marks[j][1] < marks[i][1] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    end = max(range(len(marks)), key=lambda i: best[i])
    keep_idx = []
    while end != -1:
        keep_idx.append(end)
        end = prev[end]
    keep_idx.reverse()

    # 门槛只在**真有冲突**的时候才判：一条都没冲突（子序列就是全部）时，
    # 哪怕整页只有一两道题也照切。写成「条数多才判」是错的 ——
    # 两条互相矛盾时留下一条是任选一个，而那一条也不可信
    if len(keep_idx) < len(marks) and \
            len(keep_idx) < max(KEEP_MIN, KEEP_FRAC * len(marks)):
        return [], [n for n, _ in marks]
    kept = {i for i in keep_idx}
    dropped = [marks[i][0] for i in range(len(marks)) if i not in kept]
    marks = [marks[i] for i in keep_idx]

    groups = [[marks[0]]]
    for cur in marks[1:]:
        g = groups[-1]
        tall = (cur[1] - g[0][1]) * height
        # 够数了、或者够高了就另起一条；但太薄的不许单独成条（位置估崩了）
        if (len(g) >= max_n or tall >= max_h) and tall >= MIN_STRIP_H:
            groups.append([cur])
        else:
            g.append(cur)

    out = []
    for i, g in enumerate(groups):
        top = max(0, int((g[0][1] - pad) * height))
        bottom = (int(groups[i + 1][0][1] * height) if i + 1 < len(groups)
                  else height)
        out.append(([n for n, _ in g], top, bottom))
    return out, dropped


def _blank(v, key=None):
    """这个值算不算「没读到」。`mark` 那一栏的哨兵不一样，见 MARK_BLANKS。"""
    return v in (MARK_BLANKS if key == "mark" else BLANKS)


def merge(a_rows, b_rows):
    """
    合并两遍的结果。**纯函数**，返回 `(行, 冲突列表)`。

    规矩：**逐字段取非空的那个；两边都非空且不相等 → 记一条冲突。**

    不许「先到先得」—— 实测踩过：同一题两条记录，一条有 `got`/`full` 一条没有，
    按先到先得合并**把有分数的那条丢了**。

    也不许悄悄挑一个：挑一个就等于替后端下了结论，而两边都可能是错的。

    `unreadable` / `blank` **不算「非空」**：它们是读取状态、不是作答内容。
    选择题上 Ⓑa 必然回 `unreadable`、Ⓑb 回 8/8 —— 按「两边不等就记冲突」的话，
    8 道选择题每一道都会冒一条假警告，而**永远亮着的警告等于没有警告**。

    Ⓑb 报出 Ⓑa 没有的题号要报出来（说明切条切歪了）；反过来不算异常
    （Ⓑb 只补细节，某一条没补上是常态）。
    """
    out, clash = {}, []
    for r in a_rows:
        if r.get("n") is not None:
            out[r["n"]] = dict(r)
    for r in b_rows:
        n = r.get("n")
        if n is None:
            continue
        if n not in out:
            clash.append({"n": n, "why": "只有 Ⓑb 读到了第 %s 题，Ⓑa 没有 —— "
                                          "多半是切条切歪了" % n})
            out[n] = dict(r)
            continue
        cur = out[n]
        for k, v in r.items():
            if k == "n":
                continue
            # Ⓑb 的 filled 就是这道题的作答（填涂式选择题）
            key = "answer" if k == "filled" else k
            if _blank(v, key):
                continue
            if _blank(cur.get(key), key):
                cur[key] = v
            elif cur[key] != v:
                clash.append({"n": n, "why": "两遍读出来不一样：%s 一个是 %r、"
                                             "一个是 %r" % (key, cur[key], v)})
    return [out[k] for k in sorted(out)], clash


def checksum(rows, total):
    """
    Σ 得分对卷子上印的总分。返回 `(ok, 一句人话)`。

    **它查得出**「漏了一条非零分的题、多读了一条、某个数字读错了」。

    **它查不出「读串」** —— 把第 9 题的得分安到第 10 题上、第 10 题的安到
    第 9 题上，总和一个字都不变。别把它当成读串的防线（本函数初版的注释
    就是这么写的，那句话是错的）。读串靠另外三条：两遍对账（`merge`）、
    题号清单对账（`sheetverdict.bind`）、满分对账（`full` 对参考答案的分值）。

    对不上**不失败**，只报 —— 硬失败会把一份 25/26 题都对的结果整个扔掉。

    **差额要有归属。** 2026-08-10 实跑：Σ 差 28 分，而那 28 正好是选择题 1–8
    的总分 —— 它们在这张答题卡上**本来就不印每题得分**（选择题是整块阅的）。
    只说「差 28」会让人以为哪里读错了，然后去翻一遍其实没错的题；
    点名说出「这 8 道没有分数标注」，差额立刻有了归属。
    """
    if total is None:
        return True, "没读到总分，跳过这条校验"
    got = sum(r["got"] for r in rows if r.get("got") is not None)
    if abs(got - float(total)) < 0.01:
        return True, "逐题得分加起来 %g，和卷子上印的总分对得上" % got
    why = ("逐题得分加起来是 %g，卷子上印的总分是 %g —— 差 %g。"
           % (got, float(total), abs(got - float(total))))
    noscore = [r["n"] for r in rows if r.get("got") is None]
    if noscore:
        why += ("其中 %d 道没有分数标注（%s）—— 这类题（多半是选择题）在答题卡上"
                "本来就不印每题得分，差额多半就在这里。"
                % (len(noscore), "、".join(_show(n) for n in noscore[:10])
                   + ("…" if len(noscore) > 10 else "")))
    else:
        why += "多半是漏了一题、多读了一条，或者某个数字读错了"
    return False, why


# ---------------------------------------------------------------- 跑起来

def _cut(page_png, top, bottom, dst, zoom=ZOOM):
    from PIL import Image
    im = Image.open(page_png).crop((0, top, Image.open(page_png).width, bottom))
    im.resize((im.width * zoom, im.height * zoom), Image.LANCZOS).save(dst)
    return dst


def read(paper_name, sheet_id, page_files, known_ns=None,
         verbose=True, on_call=None):
    """
    读一份答题卡。返回
    `{"rows", "clashes", "total", "checksum", "calls", "aborted"}`。

    `on_call(rec)` 每跑完一次子调用回调一次，`rec` 是
    `{"page", "pass", "ok", "seconds", "rows", "err"}` —— **每次子调用的成败
    都要落一行**，不然「Ⓑb 第 2 页整遍失败」和「这几道题本来就读不出」
    在库里和页面上完全同形。

    `known_ns` 是参考答案给出的题号清单。给了的话就多一道**中途闸门**：
    第一页读完，如果一个**大题号**都对不上这份清单，就停下来 ——
    这几张图多半根本不是这份卷子的答题卡（拍错了、传串了）。
    不停的话会把剩下几页也读完，十几次调用换一份全是 `unsure` 的报告。
    判据和 `refread.BLANK_PAGES_LIMIT` 同构。
    """
    import time
    log = (lambda s: print(s, flush=True)) if verbose else (lambda *a, **k: None)
    work = os.path.join(ROOT, "work", paper_name, "sheet", str(sheet_id), "cut")
    os.makedirs(work, exist_ok=True)
    calls = []

    def call(page_i, which, img, prompt, want):
        t0 = time.time()
        rec = {"page": page_i, "pass": which, "ok": False,
               "seconds": 0, "rows": 0, "err": None}
        try:
            got = mathvlm.ask_raw(img, prompt, want=want, timeout=900)
            rec["ok"] = True
            rec["rows"] = len(got) if isinstance(got, list) else 1
            return got
        except Exception as e:                                # noqa: BLE001
            rec["err"] = "%s: %s" % (type(e).__name__, e)
            log("   ✗ 第 %d 页 %s 没读成：%s" % (page_i, which, rec["err"]))
            return None
        finally:
            rec["seconds"] = round(time.time() - t0, 1)
            calls.append(rec)
            if on_call:
                on_call(rec)

    log("共 %d 页要读" % len(page_files))
    all_rows, all_clash = [], []
    for i, pg in enumerate(page_files, 1):
        a = call(i, "Ⓑa", pg, PROMPT_A, "array") or []
        marks = [(_qnum(r.get("n")), r.get("y")) for r in a
                 if _qnum(r.get("n")) is not None]
        b = []
        cut_list, dropped_y = strips_report(marks, _height(pg))
        if dropped_y:
            # **静默丢弃和静默失败一样糟。** 这几道题这一页没跑第二遍，
            # 它们的填涂和得分不是「读不出」，是根本没去读
            all_clash.append({
                "n": None,
                "why": "第 %d 页有 %d 道题的位置读乱了（%s），这几道没有跑第二遍 —— "
                       "它们的填涂和得分是空的，不代表卷子上没有"
                       % (i, len(dropped_y),
                          "、".join(_show(n) for n in dropped_y[:8]))})
        for ns, top, bot in cut_list:
            dst = os.path.join(work, "p%02d-%d.png" % (i, top))
            _cut(pg, top, bot, dst)
            got = call(i, "Ⓑb", dst, PROMPT_B % "、".join(_show(n) for n in ns),
                       "array")
            b += got or []
        rows, clash = merge([dict(r, n=_qnum(r.get("n"))) for r in a
                             if _qnum(r.get("n")) is not None],
                            [dict(r, n=_qnum(r.get("n"))) for r in (b or [])
                             if _qnum(r.get("n")) is not None])
        # **整遍失败要认出来**：Ⓑa 报了 N 条而 Ⓑb 一条都没回，不是「这些题没有
        # 分数」，是那一遍挂了。走逐题降级的话，页面会把它显示成「这些题读不出」
        # **「没去读」和「读了没回来」是两句不同的话。** 前者是我们自己没敢切，
        # 后者是模型挂了 —— 一个该说「位置读乱了」，一个该说「重传/重试」
        if marks and not cut_list:
            all_clash.append({"n": None,
                              "why": "第 %d 页整页没能按题切条（位置读乱了），"
                                     "所以填涂和得分一条都没读 —— 不是「读不出」，"
                                     "是没去读。换清楚一点的图重传这一页" % i})
        elif cut_list and not b:
            all_clash.append({"n": None,
                              "why": "第 %d 页的 Ⓑb 整遍没回来（模型侧失败）—— "
                                     "这一页的填涂和得分都不是「读不出」，是根本没读"
                                     % i})
        log("   第 %d 页 读到 %d 条" % (i, len(rows)))
        all_rows += rows
        all_clash += clash

        # 中途闸门：第一页一个大题号都对不上参考答案的清单 → 停。
        # 这几张图多半根本不是这份卷子的答题卡。继续读只会把剩下几页的调用
        # 也花掉，换一份全是 unsure 的报告
        if i == 1 and known_ns and rows:
            mains = {n // 100 if n >= 100 else n for n in
                     (r["n"] for r in rows)}
            ref_mains = {n // 100 if n >= 100 else n for n in known_ns}
            if not (mains & ref_mains):
                why = ("第 1 页读出来的题号（%s）和这份卷子的参考答案（%s）"
                       "一个都对不上 —— 这几张图多半不是这份卷子的答题卡。"
                       "剩下 %d 页没有读。"
                       % ("、".join(_show(n) for n in sorted(mains)[:6]),
                          "、".join(_show(n) for n in sorted(ref_mains)[:6]),
                          len(page_files) - 1))
                log("✗ " + why)
                return {"rows": all_rows, "clashes": all_clash, "total": None,
                        "checksum": (False, why), "calls": calls,
                        "aborted": why}

    total = None
    if page_files:
        dst = os.path.join(work, "total.png")
        _cut(page_files[0], 0, int(_height(page_files[0]) * 0.10), dst)
        got = call(1, "Ⓑc", dst, PROMPT_C, "object")
        total = (got or {}).get("total")
    ok, why = checksum(all_rows, total)
    log(("✓ " if ok else "⚠ ") + why)
    return {"rows": all_rows, "clashes": all_clash, "total": total,
            "checksum": (ok, why), "calls": calls, "aborted": None}


def _height(png):
    from PIL import Image
    return Image.open(png).height


def _qnum(s):
    """`12(1)` → 1201，`9` → 9。认不出回 None。约定同 refread。"""
    s = str(s or "").strip().replace("（", "(").replace("）", ")")
    if "(" in s:
        a, _, b = s.partition("(")
        b = b.rstrip(")")
        if a.strip().isdigit() and b.strip().isdigit():
            return int(a) * 100 + int(b)
        return None
    return int(s) if s.isdigit() else None


def _show(n):
    return "%d(%d)" % (n // 100, n % 100) if n >= 100 else str(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--sheet", type=int, required=True)
    a = ap.parse_args()
    got = read(a.paper, a.sheet, a.pages)
    for r in got["rows"]:
        store.put_sheet_answer(a.sheet, r["n"], scored=True,
                               raw_text=r.get("answer"),
                               mark_raw=r.get("mark"),
                               score_got=r.get("got"), score_full=r.get("full"),
                               teacher_red=r.get("red"),
                               read_conf=r.get("conf"))
    if got["total"] is not None:
        store.set_sheet_total(a.sheet, got["total"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
