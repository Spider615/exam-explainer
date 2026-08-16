# -*- coding: utf-8 -*-
"""
库表的**表头声明几列，行里就得有几个 `<td>`**。

2026-08-16 撞出来的：`SheetList.tsx` 表头声明了 7 列，行里只渲染 6 个 ——
少的是「挂知识点」。HTML 不会报错，它只是**把后面每一格都往左挪一位**：
「答题卡 1 份」显示在「挂知识点」那一列底下，`⋯` 菜单显示在「答题卡」底下。
用户看到的是「挂知识点 = 1 份」，而真值是 0（另一份卷子是 26）。

**这一条整轮 UI 重做都没被发现**，因为每一格单看都对、截图上也只是"有点怪"。
所以判据不能靠眼睛，得数。

门禁是源码级的，和这个仓库里 `PIPE_RE`、`step_code = ` 那几道同一路数 ——
前端没有测试框架，而这种错恰恰是版面看不出来的。
"""
import os
import re

import pytest

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "web", "src", "components")
TABLES = ["SheetList.tsx", "PaperList.tsx"]


def _cols_and_cells(src):
    """
    数 `cols={[...]}` 里有几个 `{ key:`，以及紧跟其后的行里有几个 `<td`。

    **先把 JSX 注释剥掉。** 不剥的话，一句解释「行里没有对应的 `<td>`」
    会被自己数进去 —— 门禁不该被散文骗（写这条测试时当场踩到了）。
    """
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)
    m = re.search(r"cols=\{\[(.*?)\]\}>", src, re.S)
    assert m, "找不到 cols={[...]}"
    n_cols = len(re.findall(r"\{\s*key:", m.group(1)))
    # 行体 = cols 之后到 </LibraryTable> 之间
    body = src[m.end():src.index("</LibraryTable>", m.end())]
    n_cells = len(re.findall(r"<td[\s>]", body))
    return n_cols, n_cells


@pytest.mark.parametrize("fn", TABLES)
def test_表头几列行里就得有几格(fn):
    src = open(os.path.join(WEB, fn), encoding="utf-8").read()

    n_cols, n_cells = _cols_and_cells(src)

    assert n_cols == n_cells, (
        "%s：表头声明 %d 列，行里只有 %d 个 <td> —— "
        "少一个不会报错，只会把后面每一格都往左挪一位，"
        "于是某一列的数显示在另一列的表头底下" % (fn, n_cols, n_cells))
