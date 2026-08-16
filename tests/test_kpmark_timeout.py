# -*- coding: utf-8 -*-
"""
③c 那次调用的超时**不能写死 300 秒**。

2026-08-16 实测：「测试」那份卷子的真实请求（提示词 14167 字符、26 题、
回 3637 字符）**一趟要 567 秒**。写死 300 的话三次重试全部倒在读超时上，
一道知识点都挂不上 —— 而端点是好的（同一时刻一个小请求 1.9 秒就回）。

这个仓库**已经踩过一模一样的坑**，`solve.py` 的注释记着：

    实测黑吉辽卷第 5、9、15 题一直没解出来、库里 12/15 挂了很久；重跑三道
    全部 `read operation timed out`，放到 900 秒后三道一次全过。
    它们不是难题，是被超时砍掉的。

那次的做法是把超时抽成带上下界的环境变量（`solve.env_int`，上限 3600），
`kpmark` 没跟上。这几条把它钉住。

**反过来也要防。** 上一轮差点把 `mathvlm` 的超时从 900 收到 300，那会砍掉
一个正当的 442 秒调用 —— 所以判据是**量出来的耗时**，不是「别的文件写了多少」。
"""
import importlib
import os
from unittest.mock import patch

import kpmark


def _reload(**env):
    """按给定环境变量重新加载 kpmark（超时是模块顶层的常量）。"""
    with patch.dict(os.environ, env, clear=False):
        return importlib.reload(kpmark)


def test_默认超时要盖得住实测的567秒():
    """
    实测一趟 567 秒。默认值必须**明显**盖得住它 —— 卡在 600 那种「刚好够」
    的数字上，换一份题多几道的卷子就又被砍了。
    """
    mod = _reload()
    try:
        assert mod.TIMEOUT >= 900, (
            "实测真实请求要 567 秒，默认超时 %s 秒盖不住" % mod.TIMEOUT)
    finally:
        _reload()


def test_超时可以用环境变量调():
    """
    `solve.py` 那次的教训里有一半是「**上限写死 300，连环境变量都调不上去**，
    正是那三道题静默消失的原因」。这里必须调得动。
    """
    mod = _reload(EXAM_KP_TIMEOUT="1200")
    try:
        assert mod.TIMEOUT == 1200
    finally:
        _reload()


def test_不许调成0或负数():
    """写错一个字（空字符串、0、负数）就把每次调用立刻砍掉，退回默认更安全。"""
    for bad in ("0", "-1", "", "abc"):
        mod = _reload(EXAM_KP_TIMEOUT=bad)
        try:
            assert mod.TIMEOUT >= 900, "EXAM_KP_TIMEOUT=%r 不该把超时打穿" % bad
        finally:
            _reload()


def test_ask真的用这个超时():
    """
    常量存在不等于用上了 —— 原来的毛病正是「`ask` 里硬写 300」。
    钉住 `urlopen` 收到的 timeout 就是这个常量。
    """
    mod = _reload()
    seen = {}

    class FakeResp:
        def read(self):
            return b'{"choices":[{"message":{"content":"[]"}}]}'

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        return FakeResp()

    try:
        with patch.object(mod.urllib.request, "urlopen", fake_urlopen):
            mod.ask("随便什么提示词")
        assert seen["timeout"] == mod.TIMEOUT
    finally:
        _reload()
