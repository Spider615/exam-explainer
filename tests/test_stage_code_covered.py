# -*- coding: utf-8 -*-
"""
`stage_of` 会返回的每一个阶段代号，前端那张表里都要有。

为什么要一条跨语言的门禁
------------------------
后端 `stage_of()` 推出「现在在哪一步」并返回一个代号；前端 `PaperView.tsx` 的
`STAGE_OF_CODE` 把代号映到那排 ①②③ 标志里的某一格。**两边各写一份，加阶段时
只改一边不会有任何报错** —— 页面照常渲染，只是那一步全程「一格都不亮」，
看着像卡死。

③c 知识点就是这么漏的：`stage_of` 里加了 `kpmark`，前端表里没加，于是标知识点
那十几分钟整排标志一个都不亮。`refread`（Ⓐ 读参考答案）当时也一起漏了。

`PaperView.tsx` 里那句注释早就写了「少了这张表……整排标志会一个都不亮」——
**嘱咐没拦住，所以改成门禁。**
"""
import os
import re

import modes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(ROOT, "pipeline", "api.py")
VIEW = os.path.join(ROOT, "web", "src", "components", "PaperView.tsx")

# `done` 不进那张表：它表示跑完了，前端走的是 `pg.done` 那条分支
NOT_A_STEP = {"done"}


def codes_from_stage_of():
    """
    两个模式各自的 `stage_of` 会返回的所有代号。

    这些 `return "代号", ...` 原来都挤在 api.py 的 `stage_of` 一个函数体里，
    后来搬进了 `pipeline/modes.py`（一个模式一份，`api.stage_of` 退成一行
    分发）。这里跟着搬，不然这条门禁会对着搬空了的 api.stage_of 扫，
    永远扫出空集合，看着像通过，其实是瞎的。
    """
    codes = set()
    for m in modes.ALL:
        codes |= modes.codes_returned_by(m.stage_of)
    return codes - NOT_A_STEP


def codes_from_step_code():
    """
    `step_code` 那张表：管线在 ①/② 挂掉时给的失败阶段代号。

    这些代号 `stage_of` **永远不会返回**（它是从库里的计数反推的，而卷子入了库
    就意味着 ①② 已经过去了），但 `failedStage` 会给。前端表里必须有它们，
    否则那两步失败时一格都不红。这条 `PaperView.tsx` 的注释里也写着。
    """
    src = open(API, encoding="utf-8").read()
    tbl = src.split("step_code = {", 1)[1].split("}", 1)[0]
    return {m.group(1) for m in re.finditer(r':\s*"([a-z_]+)"', tbl)}


def codes_in_frontend_table():
    src = open(VIEW, encoding="utf-8").read()
    tbl = src.split("STAGE_OF_CODE: Record<string, string> = {", 1)[1].split("}", 1)[0]
    return {m.group(1) for m in re.finditer(r"([a-zA-Z_]+)\s*:", tbl)}


def test_能从后端解析出阶段代号():
    """判据本身要先站得住 —— 解析不出来的话下面那条会假绿。"""
    got = codes_from_stage_of()
    assert len(got) >= 8, "只解析出 %r，正则大概是失效了" % got
    assert {"solve", "spec", "scene", "kpmark"} <= got


def test_失败阶段代号也解析得出来():
    assert codes_from_step_code() == {"ingest", "segment"}


def test_每个阶段代号前端都认得():
    want = codes_from_stage_of() | codes_from_step_code()
    missing = sorted(want - codes_in_frontend_table())
    assert not missing, (
        "这些代号后端会给，但 PaperView.tsx 的 STAGE_OF_CODE 里没有：%s。\n"
        "后果不是报错，是那一步全程「一格都不亮」，看着像卡死。"
        "去 web/src/components/PaperView.tsx 补上映到哪一格。" % "、".join(missing))


def test_前端表里没有后端不会给的代号():
    """反向也查一遍：留着死代号会让人以为某一步存在。"""
    extra = sorted(codes_in_frontend_table()
                   - codes_from_stage_of() - codes_from_step_code())
    assert not extra, "PaperView.tsx 里这些代号后端已经不给了：%s" % "、".join(extra)
