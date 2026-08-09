# -*- coding: utf-8 -*-
"""
Ⓐ 读参考答案时「读到第几页 / 共几页」。

没有分母的进度条只是个转不停的圈 —— 人分不出「在读第 2 页」和「卡死了」。
用户原话：「都看不到读取到哪一题了，什么进度都看不到啊」。

分子分母都是从 refread 自己的输出里抠的，所以这里要把**它真实会打出来的
那些行**都过一遍：抠错了不会报错，只会让进度条乱跳或者不动。
"""
from pipeline import api


def _run(lines, start=None):
    cur = dict(start or {})
    for ln in lines:
        cur = api.read_progress(ln, cur)
    return cur


def test_从共几页那行拿到分母():
    assert _run(["── 共 4 页要读（一页一分钟上下）"])["pageTotal"] == 4


def test_从每页那行拿到分子():
    got = _run(["── 共 4 页要读（一页一分钟上下）",
                "   第1页 读到 20 条（到第14(2)题）",
                "   第2页 读到 3 条（到第15(2)题）"])
    assert (got["pageDone"], got["pageTotal"]) == (2, 4)


def test_逐题清单不会被当成页号():
    """
    Ⓐ 读完会把每道题打一遍：「第12(1)题   170 / A」。
    卡的是「第…页」这个形状，别把题号当页号 —— 那会让进度条冲到第 16 页
    """
    got = _run(["── 共 4 页要读", "   第1页 读到 20 条",
                "   第1题       D   （无解答过程）",
                "   第12(1)题   170 / A",
                "   第16(3)题   \\frac{27m^3g^2R^2}{50B^4L^4}"])
    assert got["pageDone"] == 1


def test_失败汇总里的页号不算数():
    """
    收尾那行「⚠ 有 2 页没读成（第 1、2 页）」不是进度，是汇总
    """
    got = _run(["── 共 4 页要读", "   第3页 读到 5 条",
                "   ⚠ 有 2 页没读成（第 1、2 页），这几页上的题全缺了，请重传"])
    assert got["pageDone"] == 3


def test_只有一页没读成时那行也不算数():
    """
    **实拨真实日志时抓到的。** 只认「第…页」的话，`（第 4 页）` 会命中，
    进度条在只成功 3 页时直接跳到 4/4；而多页写成「第 1、2 页」反倒不命中 ——
    同一类消息一页命中、两页不命中，错得还不一致。所以分子要连「读到 / ✗」一起卡
    """
    got = _run(["── 共 4 页要读", "   第3页 读到 5 条",
                "   ⚠ 有 1 页没读成（第 4 页），这几页上的题全缺了，请重传"])
    assert got["pageDone"] == 3


def test_某一页读失败也算这一页完了():
    """
    「第4页 ✗ 没读成：超时」—— 这一页确实结束了，只是失败。
    不算的话，一批里有一页超时，进度条就永远差那一格、停在 3/4 不动
    """
    got = _run(["── 共 4 页要读", "   第3页 读到 5 条",
                "   第4页 ✗ 没读成：读图超时（600 秒）"])
    assert got["pageDone"] == 4


def test_页号只增不减():
    """
    模型的输出顺序不保证与版面一致（`last_qnum_of` 那条注释记着同一件事）。
    倒退一格会让进度条抖，看着像出错了
    """
    got = _run(["   第3页 读到 5 条", "   第1页 读到 2 条"])
    assert got["pageDone"] == 3


def test_跟进度无关的行原样放过():
    """大多数行本来就跟进度无关，不该把已有的值抹掉"""
    before = {"pageDone": 2, "pageTotal": 4, "state": "running"}
    assert api.read_progress("   ── 参考答案 某卷：写入 26 题", before) == before


def test_没开始读时两个都还没有():
    got = api.read_progress("收到 参考答案 4 个文件（0.3 MB）", {})
    assert got.get("pageDone") is None and got.get("pageTotal") is None


def test_不改传进来的那个字典():
    """
    调用方是在 LOCK 里拿 JOBS[jid] 传进来的。就地改的话，抠错一次就把
    任务状态污染了 —— 纯函数，回新的
    """
    before = {"pageDone": 1, "state": "running"}
    api.read_progress("   第2页 读到 3 条", before)
    assert before == {"pageDone": 1, "state": "running"}
