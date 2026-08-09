# -*- coding: utf-8 -*-
"""
Ⓐ 开头连着几页读不出东西就停，别再往下啃。

2026-08-09 实测踩到的：老师把手上**全部**资料一起拖了进来 —— 一份 8 页的题目
PDF、2 张答题卡截图、4 张参考答案。`pages.normalize` 按文件名排序，而
`高二期末.pdf` 里没有数字（排序键 `(0, '高二期末.pdf')`）反而排在那些
`20260807-*.jpeg` 前面，于是 Ⓐ 从第 1 页开始啃的是整份**题目**，一页一分钟，
读到第 11 页才轮到真正的参考答案。

比浪费十分钟更糟的是**顺序**：答题卡截图（学生手写、带红勾红叉）排在真参考
答案前面，而 `keep()` 对同一题号先到先得 —— 学生写错的答案会被当成标准答案
存下来，真的那个反而被丢掉。
"""
import pytest

import refread


def _stub(monkeypatch, per_page, seen):
    """把 read() 周围的世界打桩掉，只留下「读了几页、读到什么」这条线。"""
    monkeypatch.setattr(refread.pages, "normalize",
                        lambda paths, out, prefix="p": [
                            {"page": i, "hires": "p%d.png" % i, "web": "", "src": "",
                             "sha256": ""} for i in range(1, len(per_page) + 1)])
    monkeypatch.setattr(refread.store, "put_page_asset", lambda *a, **k: None)
    monkeypatch.setattr(refread.store, "get_paper", lambda name: None)
    monkeypatch.setattr(refread.store, "put_answer_question", lambda *a, **k: None)

    def ask(img, prompt, want=None, timeout=None):
        n = int(img[1:-4])
        seen.append(n)
        return per_page[n - 1]
    monkeypatch.setattr(refread.mathvlm, "ask_raw", ask)


ANS = [{"n": "11", "answer": "2BIL / MP", "solution": None}]


def test_开头连着三页空就停(monkeypatch):
    seen = []
    _stub(monkeypatch, [[], [], [], ANS, ANS, ANS, ANS], seen)
    with pytest.raises(RuntimeError, match="参考答案"):
        refread.read("某卷", ["a.png"], verbose=False)


def test_停下来之后不再往下烧钱(monkeypatch):
    """
    这条才是它存在的理由。只断言「抛了异常」的话，把 raise 挪到循环之后
    照样绿 —— 而那样一页都没省下来，代价一分钱不少。
    """
    seen = []
    _stub(monkeypatch, [[], [], [], ANS, ANS, ANS, ANS], seen)
    with pytest.raises(RuntimeError):
        refread.read("某卷", ["a.png"], verbose=False)
    assert seen == [1, 2, 3], "第 3 页之后就该停，实际读了 %s" % seen


def test_第三页读出东西就不算空(monkeypatch):
    """前两页空可能只是封面、说明页，不该一棍子打死"""
    seen = []
    _stub(monkeypatch, [[], [], ANS], seen)
    refread.read("某卷", ["a.png"], verbose=False)
    assert seen == [1, 2, 3]


def test_中间空很多页不算(monkeypatch):
    """
    整页都是上一小问推导的续写、没有新题号，是参考答案里的常态。
    只在**开头**卡 —— 已经读出过东西就说明材料是对的
    """
    seen = []
    _stub(monkeypatch, [ANS, [], [], [], [], []], seen)
    refread.read("某卷", ["a.png"], verbose=False)
    assert seen == [1, 2, 3, 4, 5, 6]


def test_读出来但一条都留不住也算空(monkeypatch):
    """
    模型回了东西、但 keep() 全过滤掉了（没题号、没答案），
    等于什么都没读到 —— 判据要看**留得住几条**，不是模型回了几条
    """
    junk = [{"n": None, "answer": ""}, {"answer": "D"}]
    seen = []
    _stub(monkeypatch, [junk, junk, junk, ANS], seen)
    with pytest.raises(RuntimeError):
        refread.read("某卷", ["a.png"], verbose=False)
    assert seen == [1, 2, 3]


def test_那句话要说清该传什么(monkeypatch):
    """
    「失败了」不够用。人得知道下一步做什么 —— 这一栏只要参考答案那几页，
    题目和答题卡混进来会怎样，都要写出来
    """
    seen = []
    _stub(monkeypatch, [[], [], []], seen)
    with pytest.raises(RuntimeError) as e:
        refread.read("某卷", ["a.png"], verbose=False)
    msg = str(e.value)
    assert "参考答案" in msg and "答题卡" in msg and "题目" in msg
