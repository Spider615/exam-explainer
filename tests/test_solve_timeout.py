# -*- coding: utf-8 -*-
"""
盲试和读图不能共用一个超时。

实测：黑吉辽卷第 5、9、15 题**一直没解出来**，库里 12/15 挂了很久。
这次重跑三道全部 `The read operation timed out`，把超时从 300 秒放到 900
之后**三道一次全过**。所以它们不是难题，是被超时砍掉的 —— 而且
`solution_failures` 表里一条记录都没有，是**静默消失**。

两条路的耗时差一个量级：
  盲试   纯文本，实测中位数几十秒
  读图   图 base64 内联进 payload，一道题几分钟

300 秒这个默认值是按盲试定的（注释里写着「5 分钟不回基本就是卡死而不是在算」，
那是拿本机代理挂死的两次事故定的）。拿它去砍读图，砍掉的是正常请求。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import solve


def test_读图的超时明显长于盲试():
    assert solve.VISION_TIMEOUT > solve.HTTP_TIMEOUT


def test_读图超时要够_900_秒():
    """实测 900 能过、300 不能过。低于这个值就是在重蹈覆辙。"""
    assert solve.VISION_TIMEOUT >= 900


def test_盲试超时不动():
    """
    盲试那条路没有证据说 300 不够，而放宽它会让「挂在代理上」那类死锁
    每次多堵好几分钟。没有证据就不改。
    """
    assert solve.HTTP_TIMEOUT == 300


def test_两个都能用环境变量单独调(monkeypatch):
    assert solve.timeout_from({"EXAM_HTTP_TIMEOUT": "77"}, "EXAM_HTTP_TIMEOUT", 300) == 77
    assert solve.timeout_from({}, "EXAM_HTTP_TIMEOUT", 300) == 300
    assert solve.timeout_from({"EXAM_VISION_TIMEOUT": "1200"}, "EXAM_VISION_TIMEOUT", 900) == 1200


def test_post_默认用盲试的超时_可以显式覆盖(monkeypatch):
    seen = {}

    class FakeResp:
        def read(self):
            return b'{"choices":[{"message":{"content":"{\\"answer\\":\\"D\\"}"}}]}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(req, timeout=None):
        seen["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(solve.urllib.request, "urlopen", fake_open)
    solve.post("https://x", "k", {"model": "m"})
    assert seen["timeout"] == solve.HTTP_TIMEOUT
    solve.post("https://x", "k", {"model": "m"}, timeout=solve.VISION_TIMEOUT)
    assert seen["timeout"] == solve.VISION_TIMEOUT


def test_读图那三条路都用长超时(monkeypatch):
    """ask_doubao / ask_claude 走的是同一个 post，别漏掉哪一条。"""
    seen = []
    monkeypatch.setattr(solve, "post", lambda b, k, p, timeout=None: seen.append(timeout) or {})
    solve.ask_doubao("题", [])
    solve.ask_claude("题", [])
    assert seen == [solve.VISION_TIMEOUT, solve.VISION_TIMEOUT]
