#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modes.py —— 两种模式各自的阶段清单与进度判定

「一共有哪几步、每步叫什么」这份清单，全项目**只有这一份**。

以前它抄了三处：`api.stage_of` 的一串 return、前端 `STAGE_LABEL`、
前端 `STAGE_OF_CODE`。两次事故都是抄漏了一份 —— ③c 加进管线时忘了往
`STAGE_OF_CODE` 加一行，那一步全程一格都不亮；`answers_only` 加进来时忘了给
`stage_of` 分支，进度带永远转、`done` 永远是 false。

规矩：**加一格只改这个文件**，`tests/test_modes.py` 会替你检查有没有漏登记。
"""
import inspect
import re


class Mode:
    """
    一个模式就是一条数据，不是散在各处的 if。

    stages       有序的格子：[(代号, 显示名)]，页面上那排标志按它画
    cell_of      `stage_of` 可能返回的代号 → 落在哪一格。子步骤（③b/③c/④b/④c）
                 没有自己的格子，归到所属大阶段；ingest/segment 只由 failedStage 走到
    needs_artifact  这几格在库外还有一份「产物到底存不存在」的事实，两个方向都由它说了算
    """

    def __init__(self, code, label, source_kinds, stages, cell_of,
                 needs_artifact, stage_of):
        self.code = code
        self.label = label
        self.source_kinds = source_kinds
        self.stages = stages
        self.cell_of = cell_of
        self.needs_artifact = needs_artifact
        self.stage_of = stage_of

    @property
    def cells(self):
        return [c for c, _ in self.stages]


def _stage_of_paper(pg):
    """
    解析试卷：从库里的计数反推「现在在哪一步」。

    每一步的分母都要用**那一步自己的口径**
    ------------------------------------
    这里原来一律拿题数或上一步的行数当分母，于是 ④c 挪到 ④ 前面之后，
    跑完的卷子在列表里永远显示「④ 写断言 6/16」—— ④ 只给 ④c 选中的 6 道题
    写断言，剩下 10 道**本来就不该有** spec，可是分母写的是 16。
    同样的坑还有两个：④b 自检的对象是 spec 不是题（而且 animatable=false 的
    spec 根本不过自检），⑤ 的分子必须是「试过几道」而不是「绿灯几道」——
    有一道怎么都过不了门禁的话，按绿灯数算就永远差一个，永远显示在跑。
    """
    q, sol = pg["questions"], pg["solutions"]
    # **终态失败也算「③ 走完了」。** 只数 solutions 的话，一道重试到底仍然失败的题
    # 会让进度永远停在「解题中 14/15」—— 而它已经不会再有解法了，等下去没有意义。
    terminal = sol + pg.get("solutionFailures", 0)
    if terminal < q:
        return "solve", "③ 解题", "解题中", terminal, q
    # ③b 的分母是**解出来的题数**：失败的题不会有解法，也就不会有短答案，
    # 拿题数当分母会永远差那几道
    if pg["labels"] < sol:
        return "outline", "③b 目录", "生成目录", pg["labels"], sol
    # ③c 知识点。分母是题数不是解出来的题数 —— 没解出来的题也该有知识点
    # （只看题干也判得出个大概），而诊断报告要拿它做聚合
    if pg.get("kps", 0) < q:
        return "kpmark", "③c 知识点", "标知识点", pg.get("kps", 0), q
    # ④c 的候选是「解出来的题」，不是全部题 —— 没解出来的它压根不判
    if pg["judged"] < sol:
        return "pick", "④c 选题", "动画选题", pg["judged"], sol
    if pg["specsWorth"] < pg["worth"]:
        return "spec", "④ 写断言", "写断言", pg["specsWorth"], pg["worth"]
    if pg["drafts"]:
        return "check", "④b 自检", "断言自检", pg["specs"] - pg["drafts"], pg["specs"]
    if pg["sceneTried"] < pg["ready"]:
        return "scene", "⑤ 生成场景", "生成动画", pg["sceneTried"], pg["ready"]
    if not pg["assembledFresh"]:
        return "assemble", "⑦ 装配成页", "装配成页", 0, 1
    return "done", "完成", "已完成", 1, 1


def _stage_of_sheet(pg):
    """
    答题卡诊断：「参考答案 + 题目图」的卷子。

    没跑过 ①②③，进不了 ④⑤⑦。终点是 ③c 挂完知识点。
    **不分支的话 solutions/specs/scenes 恒为 0，进度带永远转、done 永远是 false。**
    期一加 ③c 那一格已经踩过一次一模一样的坑。
    """
    q = pg["questions"]
    if not q:
        return "refread", "Ⓐ 读参考答案", "读参考答案", 0, 1
    if pg.get("kps", 0) < q:
        return "kpmark", "③c 知识点", "标知识点", pg.get("kps", 0), q
    return "done", "完成", "已完成", 1, 1


PAPER = Mode(
    code="paper", label="解析试卷",
    # None 不是「老卷子」（source_kind 在库上是 NOT NULL DEFAULT 'pdf'），
    # 而是「进度字典里根本没有这个键」的兜底 —— test_stage_of.py 的 BASE 就没有它
    source_kinds=("pdf", None),
    stages=[("ingest", "① 摄入"), ("segment", "② 切分"), ("solve", "③ 解题"),
            ("spec", "④ 断言"), ("scene", "⑤ 场景"), ("assemble", "⑦ 呈现")],
    # ingest / segment 这两条 stage_of **永远不会返回**（卷子入了库就意味着 ①②
    # 已经过去了），但 failedStage 会 —— 管线在 ① 或 ② 挂掉时给的正是它们。
    # 漏了这两条，那两步的失败一格都不红，只剩下面那条横幅。
    cell_of={"ingest": "ingest", "segment": "segment",
             "solve": "solve", "outline": "solve", "kpmark": "solve",
             "pick": "spec", "spec": "spec", "check": "spec",
             "scene": "scene", "assemble": "assemble"},
    needs_artifact=("scene", "assemble"),
    stage_of=_stage_of_paper,
)

SHEET = Mode(
    code="sheet", label="答题卡诊断",
    source_kinds=("answers_only",),
    stages=[("refread", "Ⓐ 读参考答案"), ("kpmark", "③c 知识点")],
    cell_of={"refread": "refread", "kpmark": "kpmark"},
    needs_artifact=(),
    stage_of=_stage_of_sheet,
)

ALL = [PAPER, SHEET]


def of(source_kind):
    """
    这份卷子属于哪个模式。

    **认不出的取值一律回 PAPER**，不抛也不回 None：回 None 的话页面上一格都不画，
    而那看起来和「这份卷子坏了」一模一样。多画几格至少还是能读的。
    """
    for m in ALL:
        if source_kind in m.source_kinds:
            return m
    return PAPER


_RETURN_CODE = re.compile(r'return\s+"([a-z_]+)"')


def codes_returned_by(fn):
    """
    这个 `stage_of` 会返回哪些代号 —— **从源码里扫**，不靠人手抄第二遍。

    手抄的话这份清单自己就成了第四份抄本，而这个文件存在的理由正是消掉抄本。
    """
    return set(_RETURN_CODE.findall(inspect.getsource(fn)))
