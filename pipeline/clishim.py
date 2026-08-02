#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clishim.py —— 让 Claude Code 能被中转站驱动的本地垫片

    python pipeline/clishim.py [--port 8899]

    然后：
    ANTHROPIC_API_KEY=$CLAUDE_API_KEY ANTHROPIC_BASE_URL=http://127.0.0.1:8899 \
      claude -p --model claude-sonnet-5 …

为什么需要它
------------
阶段⑤ 必须是**能执行代码的沙箱**（README 的核心架构判断：解物理参数要跑 Python、
验证渲染要跑无头浏览器，纯文本生成做不到），而 Claude Code 就是那个沙箱。
但直接把它指向中转站会 403 `Parameter error`。

抓包比对后定位到原因 —— 中转的参数白名单里没有这两个字段，多一个就整体打回：

    context_management   Claude Code 用来清理思维链（clear_thinking_20251015）
    metadata.user_id     里面塞了设备指纹

**不是中转不支持工具或流式**。实测单独发 tools / system+cache_control /
thinking / stream / ?beta=true 全部 200；136 KB、27 个工具定义的请求体也不是问题。
逐项二分：去掉这两个字段就通。

所以这个垫片只做一件事：转发前把它们摘掉，别的原样透传。
"""
import argparse, http.server, json, os, sys, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _l in (open(os.path.join(ROOT, ".env"), encoding="utf-8")
           if os.path.exists(os.path.join(ROOT, ".env")) else []):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# 中转不认的字段。清单是抓包二分出来的，不是猜的 ——
# 逐个删除后重放，只有这两个能让 403 变 200。
DROP = ("context_management", "metadata")


def ensure(port=None):
    """
    保证垫片在跑，返回该塞给 claude CLI 的环境变量。

    没配 CLAUDE_API_KEY 就返回空 —— 那种情况下 CLI 走本机已登录的订阅，
    这是有意的降级：宁可用订阅，也不要因为缺 key 直接失败。
    """
    key = os.environ.get("CLAUDE_API_KEY", "")
    if not key:
        return {}
    port = port or int(os.environ.get("EXAM_SHIM_PORT", "8899"))
    url = "http://127.0.0.1:%d" % port
    import socket
    with socket.socket() as s:
        s.settimeout(0.4)
        if s.connect_ex(("127.0.0.1", port)) != 0:
            import subprocess
            import time as _t
            subprocess.Popen([sys.executable, os.path.abspath(__file__),
                              "--port", str(port), "-q"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            for _ in range(40):
                _t.sleep(0.25)
                with socket.socket() as s2:
                    s2.settimeout(0.4)
                    if s2.connect_ex(("127.0.0.1", port)) == 0:
                        break
            else:
                return {}          # 起不来就退回订阅，别把整条管线卡死
    return {"ANTHROPIC_API_KEY": key, "ANTHROPIC_BASE_URL": url}


def make_handler(upstream, verbose):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _do(self):
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n) if n else b""
            body, dropped = raw, []
            if raw:
                try:
                    d = json.loads(raw)
                    dropped = [k for k in DROP if k in d]
                    for k in dropped:
                        d.pop(k, None)
                    body = json.dumps(d).encode()
                except Exception:
                    pass          # 不是 JSON 就原样透传，别自作聪明

            hdr = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length", "accept-encoding")}
            req = urllib.request.Request(upstream + self.path, body or None, hdr,
                                         method=self.command)
            try:
                r = urllib.request.urlopen(req, timeout=1800)
                code, data = r.status, r.read()
                ctype = r.headers.get("content-type", "application/json")
            except urllib.error.HTTPError as e:
                code, data = e.code, e.read()
                ctype = e.headers.get("content-type", "application/json")
            except Exception as e:
                code, data, ctype = 502, str(e).encode(), "text/plain"

            if verbose:
                print("  %s %s → %s%s" % (self.command, self.path.split("?")[0], code,
                                          ("  已摘除 " + ",".join(dropped)) if dropped else ""),
                      flush=True)
                if code >= 400:
                    print("     " + data.decode("utf-8", "replace")[:200], flush=True)

            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

        do_GET = do_POST = do_PUT = do_DELETE = _do
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("EXAM_SHIM_PORT", "8899")))
    ap.add_argument("--upstream", default=os.environ.get("CLAUDE_BASE_URL",
                                                         "https://api.302.ai/v1").rsplit("/v1", 1)[0])
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args()
    print("垫片就绪：127.0.0.1:%d → %s（摘除 %s）" % (a.port, a.upstream, "、".join(DROP)))
    print("用法：ANTHROPIC_API_KEY=<key> ANTHROPIC_BASE_URL=http://127.0.0.1:%d claude -p …" % a.port)
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port),
                                    make_handler(a.upstream, not a.quiet)).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
