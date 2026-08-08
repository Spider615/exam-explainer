# -*- coding: utf-8 -*-
"""
`arkshim.ensure()` 复用别人起的垫片之前，必须核对那个垫片是不是自己要的那个。

为什么非加不可
--------------
垫片的思考开关（`EXAM_ARK_THINKING`）和方舟 key 都是**进程启动时读一次**的常量。
`ensure()` 原来只探端口通不通，通了就复用 —— 于是：

  上一轮跑 ⑤ 起了个开思考的垫片，没退出；这一轮 .env 改成关思考再跑，
  端口是通的，直接复用 —— **拿到的还是开思考那个**。慢 2.6 倍，零提示。

key 换了更糟：请求会静默发到旧账号，用量记在别人头上。

所以复用前拉一次身份对一对，对不上就当场停，并把两边都打出来。
不自动去杀那个进程 —— 那可能是别人正在用的。
"""
import http.server
import json
import os
import socket
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import arkshim


def stub(payload):
    """在一个随机空闲端口上起个假垫片，返回 (端口, 关闭函数)。"""
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            body = payload if isinstance(payload, bytes) else \
                json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port, srv.shutdown


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(arkshim, "ARK_KEY", "ark-bafa1234567890abcd28e7")
    monkeypatch.setattr(arkshim, "THINKING", "disabled")
    return arkshim.ARK_KEY


def test_指纹只露头尾_不泄漏整把_key(key):
    fp = arkshim.fingerprint(key)
    assert key not in fp
    assert fp.startswith("ark-ba") and fp.endswith("28e7")


def test_空_key_的指纹不是空串(key):
    assert arkshim.fingerprint("") == "（无）"


def test_身份带上思考设置和账号(key):
    idy = arkshim.identity()
    assert idy["thinking"] == "disabled"
    assert idy["key"] == arkshim.fingerprint(key)
    assert idy["base"] == arkshim.ARK_BASE


def test_一致就照常复用(key):
    port, stop = stub(dict(arkshim.identity(), ok=True))
    try:
        env = arkshim.ensure(port)
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:%d" % port
        assert env["ANTHROPIC_API_KEY"]      # 必须有值，否则 CLI 会走订阅
    finally:
        stop()


def test_思考设置对不上要当场停并把两边都说清楚(key):
    port, stop = stub(dict(arkshim.identity(), ok=True, thinking="auto"))
    try:
        with pytest.raises(RuntimeError) as e:
            arkshim.ensure(port)
        msg = str(e.value)
        assert "auto" in msg and "disabled" in msg     # 在跑的 / 要的
        assert str(port) in msg                        # 去哪儿找它
    finally:
        stop()


def test_key_对不上也要停(key):
    port, stop = stub(dict(arkshim.identity(), ok=True, key="ark-ffff…0000"))
    try:
        with pytest.raises(RuntimeError, match="key"):
            arkshim.ensure(port)
    finally:
        stop()


def test_报错里不能出现完整的_key(key):
    port, stop = stub(dict(arkshim.identity(), ok=True, thinking="auto"))
    try:
        with pytest.raises(RuntimeError) as e:
            arkshim.ensure(port)
        assert key not in str(e.value)
    finally:
        stop()


def test_加身份牌之前的旧垫片要单独说清楚(key):
    """
    改动之前的垫片 GET / 只回 `{"ok":true}`。它**是**垫片，只是认不出配置 ——
    报「不是垫片」会把人带偏，得说清楚「是旧的、很可能还开着思考」。
    """
    port, stop = stub({"ok": True})
    try:
        with pytest.raises(RuntimeError, match="旧垫片"):
            arkshim.ensure(port)
    finally:
        stop()


def test_端口上蹲的不是垫片也要停(key):
    port, stop = stub("<html>我是别的服务</html>".encode())
    try:
        with pytest.raises(RuntimeError, match="不是方舟垫片"):
            arkshim.ensure(port)
    finally:
        stop()


def test_没有_key_时仍然返回空字典(monkeypatch):
    """调用方靠这个空字典判「方舟通道不可用」，这条老行为不能变。"""
    monkeypatch.setattr(arkshim, "ARK_KEY", "")
    assert arkshim.ensure(9) == {}
