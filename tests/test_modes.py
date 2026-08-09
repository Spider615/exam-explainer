# -*- coding: utf-8 -*-
"""
阶段清单只有这一份，而且它自己会检查自己。

以前这份清单抄了三处（api.stage_of 的一串 return、前端 STAGE_LABEL、
前端 STAGE_OF_CODE），两次事故都是抄漏了一份。这里的门禁在**加阶段那一刻**
触发 —— 加一格必然要改 stage_of，改完跑测试就红。
"""
import os
import re

import modes


def test_两个模式都在册():
    assert {m.code for m in modes.ALL} == {"paper", "sheet"}


def test_按source_kind找模式():
    assert modes.of("pdf") is modes.PAPER
    assert modes.of("answers_only") is modes.SHEET


def test_没给source_kind当解析试卷():
    """进度字典里没有这个键时的兜底 —— test_stage_of.py 的 BASE 就没有它"""
    assert modes.of(None) is modes.PAPER


def test_没见过的取值也当解析试卷():
    """宁可多画几格，不能把一份卷子判成没有模式（那样页面上一格都不画）"""
    assert modes.of("将来某个新值") is modes.PAPER


def test_stage_of会返回的每个代号都登记过():
    """加一格忘了往 cell_of 加一行 —— 那一步会全程「一格都不亮」"""
    for m in modes.ALL:
        for code in modes.codes_returned_by(m.stage_of) - {"done"}:
            assert code in m.cell_of, (
                "%s 模式的 stage_of 会返回 %r，但 cell_of 里没有它" % (m.code, code))


def test_cell_of的每个值都是真实存在的一格():
    for m in modes.ALL:
        for src, cell in m.cell_of.items():
            assert cell in m.cells, (
                "%s 模式把 %r 映射到 %r，可 stages 里没有这一格" % (m.code, src, cell))


def test_每个模式都走得到done():
    """走不到 done 的模式，进度带永远转"""
    for m in modes.ALL:
        assert "done" in modes.codes_returned_by(m.stage_of), m.code


def test_格子代号不重复():
    for m in modes.ALL:
        assert len(m.cells) == len(set(m.cells)), m.code


def test_needs_artifact里的格子必须真实存在():
    for m in modes.ALL:
        for c in m.needs_artifact:
            assert c in m.cells, m.code


# ---------------------------------------------------------------- 每一格的状态
#
# 这段判断原来在前端（PaperView.tsx 的 stageStates），而 web/ 一个测试都没有。
# 它恰恰是出过两次错的那段，所以搬到有测试的这一侧来。

def _states(mode, **kw):
    kw.setdefault("stage_code", None)
    kw.setdefault("done", False)
    kw.setdefault("failed_stage", None)
    kw.setdefault("artifacts", {})
    got = modes.cell_states(mode, **kw)
    return {c["code"]: c["state"] for c in got}


def test_按管线位置切三段():
    """它之前的做完了、它本身在跑、它之后的还没轮到"""
    s = _states(modes.PAPER, stage_code="spec")
    assert s["ingest"] == "done" and s["segment"] == "done" and s["solve"] == "done"
    assert s["spec"] == "now"
    assert s["scene"] == "todo" and s["assemble"] == "todo"


def test_子步骤归到所属大阶段():
    """③c 跑的时候要亮在「③ 解题」那一格上，不是一格都不亮"""
    assert _states(modes.PAPER, stage_code="kpmark")["solve"] == "now"
    assert _states(modes.PAPER, stage_code="pick")["spec"] == "now"


def test_跑完了全都是done():
    s = _states(modes.PAPER, stage_code="done", done=True,
                artifacts={"scene": True, "assemble": True})
    assert set(s.values()) == {"done"}


def test_失败只画在它自己那一格():
    """
    原来是画在「当前阶段」那一格，于是 ⑤ 正在正常出动画时那格也是红的、
    写着「②b 公式识别 失败」
    """
    s = _states(modes.PAPER, stage_code="scene", failed_stage="segment")
    assert s["segment"] == "fail"
    assert s["scene"] == "now"


def test_后端说不清是哪一步挂的就一格都不画():
    s = _states(modes.PAPER, stage_code="scene", failed_stage=None)
    assert "fail" not in s.values()


def test_跑过去了却没有产物是empty():
    """六道全试过、门禁一个都没过时，不能画成「⑤ 做完了」"""
    s = _states(modes.PAPER, stage_code="assemble",
                artifacts={"scene": False, "assemble": False})
    assert s["scene"] == "empty"


def test_有产物就算数不管推断走到哪():
    """
    三段切分假设管线是单调跑一遍的，可它不是：实测有卷子 stage_of 停在 ③，
    而 ⑤ 早跑过、动画正在页面上播着
    """
    s = _states(modes.PAPER, stage_code="solve", artifacts={"scene": True})
    assert s["scene"] == "done"


def test_轮询还没回来时退回看产物():
    """那时候只知道有没有产物，也只能说这么多"""
    s = _states(modes.PAPER, stage_code=None,
                artifacts={"scene": True, "assemble": False})
    assert s["scene"] == "done" and s["assemble"] == "todo"


def test_答题卡模式只有两格():
    s = _states(modes.SHEET, stage_code="kpmark")
    assert list(s) == ["refread", "kpmark"]
    assert s["refread"] == "done" and s["kpmark"] == "now"


def test_答题卡模式没有产物那一说():
    """它没有 ⑤ 和 ⑦，empty 这个状态在这个模式里根本不该出现"""
    s = _states(modes.SHEET, stage_code="done", done=True)
    assert set(s.values()) == {"done"}


def test_在跑的格子不许被产物覆盖():
    """
    ⑤ 正在重试，而上一次部分尝试留下的产物还在磁盘上 ——
    这时候画成「做完了」是骗人的
    """
    s = _states(modes.PAPER, stage_code="scene", artifacts={"scene": True})
    assert s["scene"] == "now", (
        "在跑的格子 scene 有产物时不应该被覆盖成 done，应该保持 now")


def test_挂掉的格子不许被产物覆盖():
    """
    ② 挂掉了，但上一次的部分处理结果（产物）还在磁盘上 ——
    不能让产物的存在掩盖了这次失败
    """
    s = _states(modes.PAPER, failed_stage="scene", artifacts={"scene": True})
    assert s["scene"] == "fail", (
        "挂掉的格子 scene 有产物时不应该被覆盖成 done，应该保持 fail")


# ---------------------------------------------------------------- 失败阶段代号
#
# 这一条是从 tests/test_stage_code_covered.py 搬过来的。那条门禁原来跨语言查
# 「后端的代号前端那张表里都有吗」；前端那张表删掉之后它没有对象可查了，
# 但它守的**第二条**不变量还在：①/② 挂掉时给的失败代号必须落得进那排格子，
# 否则那两步失败时一格都不红，只剩下面一条横幅。

_API = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "pipeline", "api.py")


def _step_code_values():
    """
    `run_pipeline` 里那张 `step_code` 表的值。

    这些代号 `stage_of` **永远不会返回**（它是从库里的计数反推的，而卷子入了库
    就意味着 ①② 已经过去了），只有 `failedStage` 会给。
    """
    src = open(_API, encoding="utf-8").read()
    tbl = src.split("step_code = {", 1)[1].split("}", 1)[0]
    return {m.group(1) for m in re.finditer(r':\s*"([a-z_]+)"', tbl)}


def test_失败阶段代号解析得出来():
    """判据本身要先站得住 —— 解析不出来的话下面那条会假绿"""
    assert _step_code_values() == {"ingest", "segment"}


def test_失败阶段代号都落得进解析试卷的格子():
    missing = sorted(_step_code_values() - set(modes.PAPER.cell_of))
    assert not missing, (
        "这些代号管线挂掉时会给，但 PAPER.cell_of 里没有：%s。\n"
        "后果不是报错，是那一步失败时一格都不红。" % "、".join(missing))
