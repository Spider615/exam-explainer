# -*- coding: utf-8 -*-
"""
Ⓔ 读题干：把原卷上的题干按 Ⓐ 的题号清单填进去。

它存在的理由很具体：参考答案里 18 道题只有一个 `D` / `BC` / `170 / A`，
而一个孤零零的字母推不出这道题考什么 —— ③c 在那 18 道上必然交白卷
（实测 26 道只挂上 9 道）。

**题号清单以参考答案为准，Ⓔ 只填题干不定题号。** 多出来的题号意味着读错了，
而错的题干会把 ③c 引到另一道题上去，比没有题干更糟。
"""
import pytest

import stemread


# ---------------------------------------------------------------- flatten
def test_题干与选项并成一段():
    """
    选项是题意的一部分 —— 「下列四幅电场线图哪个正确」离了选项什么都不是，
    而 ③c 要判的正是「这道题在问什么」
    """
    n, s = stemread.flatten({"n": "6", "stem": "如图，两平行板…（ ）",
                             "options": ["A. 变大", "B. 变小"]})
    assert n == 6
    assert s == "如图，两平行板…（ ）\nA. 变大\nB. 变小"


def test_没有选项就只有题干():
    assert stemread.flatten({"n": "9", "stem": "空气柱长度", "options": []})[1] == "空气柱长度"


def test_小问题号认得出():
    assert stemread.flatten({"n": "12(1)", "stem": "求电压"})[0] == 1201


def test_题号认不出的整条丢掉():
    """把 A 题的题干安到 B 题上，比没有题干更糟"""
    assert stemread.flatten({"n": "第几题？", "stem": "如图"})[0] is None


def test_题干空的整条丢掉():
    assert stemread.flatten({"n": "6", "stem": "   "})[0] is None


def test_烂数据不炸():
    assert stemread.flatten("这不是个字典")[0] is None
    assert stemread.flatten({})[0] is None


# ---------------------------------------------------------------- spread
KNOWN = {1, 2, 9, 1201, 1202, 1203, 1401, 1402}


def test_直接命中的照填():
    fit, warn = stemread.spread({1: "第一题题干", 9: "第九题题干"}, KNOWN)
    assert fit == {1: "第一题题干", 9: "第九题题干"} and not warn


def test_主题号的题干回填给所有小问():
    """
    原卷上是「12.（6分）（1）…（2）…」，而清单里是 1201/1202/1203 ——
    它们共用同一段题干，分别写一份反而是假精确
    """
    fit, warn = stemread.spread({12: "理想变压器…"}, KNOWN)
    assert fit == {1201: "理想变压器…", 1202: "理想变压器…", 1203: "理想变压器…"}
    assert not warn


def test_小问自己给的题干优先():
    """模型能拆出更细的就用细的，回填只是兜底"""
    fit, _ = stemread.spread({12: "整题题干", 1202: "第二问自己的问法"}, KNOWN)
    assert fit[1202] == "第二问自己的问法"
    assert fit[1201] == "整题题干"


def test_清单里没有的题号丢掉并告警():
    """
    多出来意味着读错了（读到了别的卷子、或者题号看串了）。
    悄悄收下的话，③c 会拿着一段不相干的题干去判 —— 而且没人看得见
    """
    fit, warn = stemread.spread({1: "对的", 77: "不知道哪来的"}, KNOWN)
    assert 77 not in fit
    assert warn and "77" in warn[0]


def test_主题号在清单里就不当成小问():
    """第 9 题没有小问，清单里就是 9 —— 别去找它的 9xx"""
    fit, _ = stemread.spread({9: "第九题"}, KNOWN)
    assert fit == {9: "第九题"}


def test_一条都对不上时回空():
    fit, warn = stemread.spread({77: "x", 88: "y"}, KNOWN)
    assert fit == {} and warn


# ---------------------------------------------------------------- read()
def _stub(monkeypatch, per_page, seen, known=(1, 2)):
    monkeypatch.setattr(stemread.store, "get_paper",
                        lambda name: {"questions": [{"n": n} for n in known]})
    monkeypatch.setattr(stemread.pages, "normalize",
                        lambda paths, out, prefix="p": [
                            {"page": i, "hires": "p%d.png" % i, "web": "",
                             "src": "", "sha256": ""}
                            for i in range(1, len(per_page) + 1)])
    monkeypatch.setattr(stemread.store, "put_page_asset", lambda *a, **k: None)
    # 切图要真开图，这几条测的是「读到什么、写进去什么」那条线，跟切图无关。
    # 切图本身由上面 slices 那组纯函数用例盯着
    monkeypatch.setattr(stemread, "cut_page", lambda *a, **k: {})
    monkeypatch.setattr(stemread.store, "put_stem_image", lambda *a, **k: None)
    written = {}
    monkeypatch.setattr(stemread.store, "put_stem",
                        lambda p, n, s: written.__setitem__(n, s))

    def ask(img, prompt, want=None, timeout=None):
        seen.append(int(img[1:-4]))
        return per_page[int(img[1:-4]) - 1]
    monkeypatch.setattr(stemread.mathvlm, "ask_raw", ask)
    return written


Q1 = [{"n": "1", "stem": "第一题题干", "options": ["A. 甲", "B. 乙"]}]


def test_读到的题干写进库(monkeypatch):
    seen = []
    written = _stub(monkeypatch, [Q1], seen)
    assert stemread.read("某卷", ["a.png"], verbose=False) == 1
    assert written[1].startswith("第一题题干")


def test_开头连着三页读不出题就停(monkeypatch):
    """喂错材料（把参考答案放进「原卷」那一栏）时别一页页啃下去"""
    seen = []
    _stub(monkeypatch, [[], [], [], Q1, Q1], seen)
    with pytest.raises(RuntimeError, match="原卷"):
        stemread.read("某卷", ["a.png"], verbose=False)
    assert seen == [1, 2, 3], "第 3 页之后就该停，实际读了 %s" % seen


def test_中间空页不算(monkeypatch):
    """已经读出过题就说明材料是对的；中间夹一页答题卡说明页是常事"""
    seen = []
    _stub(monkeypatch, [Q1, [], [], [], []], seen)
    stemread.read("某卷", ["a.png"], verbose=False)
    assert seen == [1, 2, 3, 4, 5]


def test_库里没有这份卷子就明说(monkeypatch):
    monkeypatch.setattr(stemread.store, "get_paper", lambda name: None)
    with pytest.raises(RuntimeError, match="题号清单"):
        stemread.read("没有的卷", ["a.png"], verbose=False)


def test_一道题都对不上就失败(monkeypatch):
    """
    传错卷子的原卷时，题号一条都对不上。这时候写进去的会是整卷错的题干，
    宁可整批失败
    """
    seen = []
    _stub(monkeypatch, [[{"n": "77", "stem": "别的卷子的题"}]], seen)
    with pytest.raises(RuntimeError, match="原卷"):
        stemread.read("某卷", ["a.png"], verbose=False)


# ---------------------------------------------------------------- slices
def test_按题号切成一条一条():
    """
    从这道题的题号切到下一道题的题号，最后一道切到页底。
    上边留一点余量，不然题号本身会被切掉半行
    """
    got = stemread.slices([(1, 0.10), (2, 0.50)], 1000, pad=0.02)
    assert got == [(1, 80, 500), (2, 480, 1000)]


def test_只有一道题时切到页底():
    assert stemread.slices([(6, 0.30)], 1000, pad=0.0) == [(6, 300, 1000)]


def test_y没随题号递增就整页不切():
    """
    位置读乱了的话，每一条都会对错题号 —— 26 张错的图比没有图糟得多。
    宁可这一页不给图
    """
    assert stemread.slices([(1, 0.80), (2, 0.20)], 1000) == []


def test_题号本身没排好也不切():
    assert stemread.slices([(5, 0.10), (2, 0.50)], 1000) == []


def test_y缺了或越界的那条不算数():
    """模型偶尔会漏给 y 或者给个 1.7，别拿它去算像素"""
    assert stemread.slices([(1, None), (2, 0.5)], 1000) == [(2, 488, 1000)]
    assert stemread.slices([(1, 1.7)], 1000) == []


def test_太薄的条跳过():
    """两道题的 y 几乎重合，说明位置估崩了，切出来是一条线"""
    got = stemread.slices([(1, 0.500), (2, 0.505)], 1000, pad=0.0)
    assert [n for n, _, _ in got] == [2], "第一条太薄，该跳过"


def test_一条都没有时回空():
    assert stemread.slices([], 1000) == []
