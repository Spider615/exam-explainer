# -*- coding: utf-8 -*-
"""
阶段清单只有这一份，而且它自己会检查自己。

以前这份清单抄了三处（api.stage_of 的一串 return、前端 STAGE_LABEL、
前端 STAGE_OF_CODE），两次事故都是抄漏了一份。这里的门禁在**加阶段那一刻**
触发 —— 加一格必然要改 stage_of，改完跑测试就红。
"""
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
