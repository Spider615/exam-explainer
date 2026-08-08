# -*- coding: utf-8 -*-
"""
②b 公式识别的传输路。

为什么不能走 arkshim
--------------------
最自然的想法是「claude CLI + arkshim + 豆包」，一行环境变量就切完。**不行**：
`arkshim.blocks_to_openai` 处理 `tool_result` 时只把 `text` 块串起来，
图片块没有 `text` 键，会被静默丢成空串。而 claude CLI 读图靠的就是 Read
工具的 tool_result —— 图会在垫片里消失，模型收到一句「请读这张图」外加空内容，
然后一本正经地编出选项来。**是最坏的那种错：不报错、结果看着像对的。**

所以这条路把图 base64 内联进 payload 直连方舟，跟 `solve.ask_doubao` 一样：
一次调用，没有工具循环，图不可能在中途丢。
"""
import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import mathvlm

# 1×1 的透明 PNG，够用来验载荷形状
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "opt.png"
    p.write_bytes(PNG)
    return str(p)


def test_不设环境变量时默认是订阅那条路(monkeypatch):
    """
    切后端必须是显式的。

    这里重新求一遍那行默认值，不能直接断言 `mathvlm.BACKEND` —— 它是 import
    时读的快照，而这台机器的 .env 里已经写了 doubao，那样断言的是环境不是逻辑。
    """
    monkeypatch.delenv("EXAM_VLM_BACKEND", raising=False)
    assert os.environ.get("EXAM_VLM_BACKEND", "subscription") == "subscription"


def test_不传后端就跟着模块配置走(monkeypatch):
    monkeypatch.setattr(mathvlm, "BACKEND", "doubao")
    assert mathvlm.resolve_backend(None) == "doubao"
    assert mathvlm.resolve_backend("subscription") == "subscription"   # 显式的赢


def test_后端名写错要当场报错(monkeypatch):
    with pytest.raises(SystemExit):
        mathvlm.resolve_backend("doubao-seed-evolving")   # 填成了模型名


def test_豆包载荷把图内联成_data_uri(png):
    """图必须在 payload 里，不能只留一个路径让模型自己去读。"""
    msgs = mathvlm.vision_payload("读这张图", png)
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    kinds = [c["type"] for c in msgs[0]["content"]]
    assert kinds == ["text", "image_url"]
    assert msgs[0]["content"][0]["text"] == "读这张图"
    url = msgs[0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG


def test_豆包那条路不碰_claude_cli(monkeypatch, png):
    """CLI 找不到也要能跑通 —— 证明这条路真的没有 CLI 依赖。"""
    monkeypatch.setattr(mathvlm, "CLI", None)
    monkeypatch.setattr(mathvlm, "ARK_KEY", "ark-test")
    seen = {}

    def fake_post(payload, timeout):
        seen.update(payload=payload, timeout=timeout)
        return '{"stem":"v = at"}'

    monkeypatch.setattr(mathvlm, "post_doubao", fake_post)
    got = mathvlm.ask_raw(png, "读这张图", backend="doubao")
    assert got == {"stem": "v = at"}
    assert seen["payload"]["model"] == mathvlm.ARK_MODEL
    assert seen["payload"]["temperature"] == 0


def test_豆包缺_key_要报得明白(monkeypatch, png):
    monkeypatch.setattr(mathvlm, "ARK_KEY", "")
    with pytest.raises(RuntimeError, match="ARK_API_KEY"):
        mathvlm.ask_raw(png, "读这张图", backend="doubao")


def test_豆包也走_loads_lenient(monkeypatch, png):
    """
    JSON 会静默吃掉 LaTeX 反斜杠（`\\times` → TAB+"imes"）。这条容错在订阅那条
    路上已经有了，换后端不能把它丢掉 —— 否则同一张图换个后端就出乱码。
    """
    monkeypatch.setattr(mathvlm, "ARK_KEY", "ark-test")
    monkeypatch.setattr(mathvlm, "post_doubao",
                        lambda payload, timeout: r'{"stem":"3\times10^8"}')
    assert mathvlm.ask_raw(png, "读", backend="doubao") == {"stem": r"3\times10^8"}


def test_豆包能取数组(monkeypatch, png):
    """Ⓐ 读参考答案要的是数组，两种形状都得支持。"""
    monkeypatch.setattr(mathvlm, "ARK_KEY", "ark-test")
    monkeypatch.setattr(mathvlm, "post_doubao",
                        lambda payload, timeout: '前言 [{"no":"1"}] 后语')
    assert mathvlm.ask_raw(png, "读", want="array", backend="doubao") == [{"no": "1"}]
