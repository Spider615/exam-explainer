#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arkshim.py —— 让 claude CLI 被**豆包**驱动的协议翻译垫片

    python pipeline/arkshim.py [--port 8898]

    ANTHROPIC_API_KEY=x ANTHROPIC_BASE_URL=http://127.0.0.1:8898 \
      claude -p --model doubao-seed-evolving …

和 clishim 的区别
-----------------
`clishim` 是**透传**：上游本来就说 Anthropic 协议，它只摘掉两个中转不认的字段。
这里上游是火山方舟，说的是 OpenAI 协议，**两边协议不通**，必须逐字段翻译：

    Anthropic /v1/messages          OpenAI /chat/completions
    ────────────────────────────    ─────────────────────────────────
    system: [{type:text,text}]  →   {role:"system", content}
    content 块 text             →   字符串或 {type:"text"}
    content 块 image(base64)    →   {type:"image_url", url:"data:…"}
    content 块 tool_use         →   assistant.tool_calls[]
    content 块 tool_result      →   {role:"tool", tool_call_id}
    tools[{name,input_schema}]  →   [{type:"function",function:{parameters}}]
    ← content[tool_use]             ← message.tool_calls[]
    ← stop_reason: tool_use         ← finish_reason: tool_calls

流式怎么处理
------------
Claude Code 默认要 SSE。这里**不做流式转流式** —— 向方舟发非流式请求，拿到完整
结果后再合成一串合法的 Anthropic 事件（message_start → content_block_* →
message_delta → message_stop）。客户端只关心事件序列合不合法，不关心是不是
一次性到达。这样少一整套增量解析的状态机，也就少一整类难查的 bug。

代价是首字延迟等于整次生成的时间。对阶段⑤ 无所谓 —— 那本来就是一轮几分钟的活。

前提
----
豆包必须支持 OpenAI 的 function calling，否则 claude CLI 一个工具都调不动，
整条路等于废的。实测 `doubao-seed-evolving` 与 `doubao-seed-2-0-pro-260215`
都能正确返回 `tool_calls`，所以才有这个文件。
"""
import argparse, http.server, json, os, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _l in (open(os.path.join(ROOT, ".env"), encoding="utf-8")
           if os.path.exists(os.path.join(ROOT, ".env")) else []):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

ARK_BASE = os.environ.get("EXAM_SCENE_ARK_BASE",
                          "https://ark.cn-beijing.volces.com/api/v3")
ARK_KEY = os.environ.get("EXAM_SCENE_ARK_KEY") or os.environ.get("ARK_API_KEY", "")
# disabled / auto / enabled，空表示不传这个字段（保持模型默认）
THINKING = os.environ.get("EXAM_ARK_THINKING", "").strip()


# ──────────────────────────────────────────────── 请求：Anthropic → OpenAI
def blocks_to_openai(content):
    """把一条消息的 content 翻成 OpenAI 的形状，同时把工具相关的块摘出来。"""
    if isinstance(content, str):
        return content, [], []
    parts, tool_calls, tool_results = [], [], []
    for b in content or []:
        t = b.get("type")
        if t == "text":
            parts.append({"type": "text", "text": b.get("text", "")})
        elif t == "image":
            src = b.get("source") or {}
            if src.get("type") == "base64":
                parts.append({"type": "image_url", "image_url": {
                    "url": "data:%s;base64,%s" % (src.get("media_type", "image/png"),
                                                  src.get("data", ""))}})
        elif t == "tool_use":
            tool_calls.append({"id": b.get("id"), "type": "function",
                               "function": {"name": b.get("name"),
                                            "arguments": json.dumps(b.get("input") or {},
                                                                    ensure_ascii=False)}})
        elif t == "tool_result":
            c = b.get("content")
            if isinstance(c, list):
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
            tool_results.append({"role": "tool", "tool_call_id": b.get("tool_use_id"),
                                 "content": c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)})
    # 只有纯文本时退回字符串：有些端点对单元素数组比对字符串挑剔
    if parts and all(p["type"] == "text" for p in parts):
        parts = "\n".join(p["text"] for p in parts)
    return parts, tool_calls, tool_results


def to_openai(d):
    msgs = []
    sysc = d.get("system")
    if isinstance(sysc, list):
        sysc = "\n".join(b.get("text", "") for b in sysc if isinstance(b, dict))
    if sysc:
        msgs.append({"role": "system", "content": sysc})

    for m in d.get("messages") or []:
        role = m.get("role")
        body, calls, results = blocks_to_openai(m.get("content"))
        # tool_result 必须作为独立的 tool 角色消息，且要排在触发它的 assistant 之后
        if results:
            msgs.extend(results)
        if role == "assistant":
            am = {"role": "assistant", "content": body if body else None}
            if calls:
                am["tool_calls"] = calls
            if am["content"] or calls:
                msgs.append(am)
        elif body:
            msgs.append({"role": role, "content": body})

    out = {"model": d.get("model"), "messages": msgs}
    # 思考预算。DeepSeek-V4-Flash 是推理模型，实测同一道物理题：
    #   开思考  22.4 秒，输出 1774 token，其中 1769 个是 reasoning
    #   关思考   3.6 秒，输出  286 token，答案照样对（推导写进可见输出）
    # 生成速率两者都是 80 tok/s —— 慢不是模型慢，是它生成了 6 倍的 token。
    # 默认不动（跟以前一样），要关得显式设 EXAM_ARK_THINKING=disabled
    if THINKING:
        out["thinking"] = {"type": THINKING}
    if d.get("max_tokens"):
        out["max_tokens"] = d["max_tokens"]
    if d.get("temperature") is not None:
        out["temperature"] = d["temperature"]
    if d.get("tools"):
        out["tools"] = [{"type": "function",
                         "function": {"name": t.get("name"),
                                      "description": t.get("description", ""),
                                      "parameters": t.get("input_schema")
                                      or {"type": "object", "properties": {}}}}
                        for t in d["tools"] if t.get("name")]
    tc = d.get("tool_choice") or {}
    if tc.get("type") == "auto":
        out["tool_choice"] = "auto"
    elif tc.get("type") == "any":
        out["tool_choice"] = "required"
    elif tc.get("type") == "tool" and tc.get("name"):
        out["tool_choice"] = {"type": "function", "function": {"name": tc["name"]}}
    return out


# ──────────────────────────────────────────────── 响应：OpenAI → Anthropic
STOP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use",
        "function_call": "tool_use", "content_filter": "end_turn"}


def to_anthropic(d, model):
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    blocks = []
    if msg.get("content"):
        blocks.append({"type": "text", "text": msg["content"]})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"__raw": fn.get("arguments")}
        blocks.append({"type": "tool_use", "id": tc.get("id") or "toolu_shim",
                       "name": fn.get("name"), "input": args})
    if not blocks:
        blocks = [{"type": "text", "text": ""}]
    u = d.get("usage") or {}
    return {"id": "msg_" + str(d.get("id") or "shim").replace("-", "")[:24], "type": "message", "role": "assistant",
            "model": model, "content": blocks,
            "stop_reason": STOP.get(ch.get("finish_reason"), "end_turn"),
            "stop_sequence": None,
            "usage": {"input_tokens": u.get("prompt_tokens", 0),
                      "output_tokens": u.get("completion_tokens", 0)}}


def sse(resp):
    """把一份完整的 Anthropic 响应合成为一串合法的 SSE 事件。"""
    def ev(t, obj):
        return ("event: %s\ndata: %s\n\n" % (t, json.dumps(obj, ensure_ascii=False))).encode()

    head = dict(resp, content=[], stop_reason=None,
                usage={"input_tokens": resp["usage"]["input_tokens"], "output_tokens": 0})
    yield ev("message_start", {"type": "message_start", "message": head})
    yield ev("ping", {"type": "ping"})
    for i, b in enumerate(resp["content"]):
        if b["type"] == "text":
            yield ev("content_block_start", {"type": "content_block_start", "index": i,
                                             "content_block": {"type": "text", "text": ""}})
            if b["text"]:
                yield ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                 "delta": {"type": "text_delta", "text": b["text"]}})
        else:
            yield ev("content_block_start", {"type": "content_block_start", "index": i,
                                             "content_block": {"type": "tool_use", "id": b["id"],
                                                               "name": b["name"], "input": {}}})
            yield ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                             "delta": {"type": "input_json_delta",
                                                       "partial_json": json.dumps(b["input"], ensure_ascii=False)}})
        yield ev("content_block_stop", {"type": "content_block_stop", "index": i})
    yield ev("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": resp["stop_reason"], "stop_sequence": None},
                               "usage": {"output_tokens": resp["usage"]["output_tokens"]}})
    yield ev("message_stop", {"type": "message_stop"})


def call_ark(payload, timeout):
    r = urllib.request.Request(ARK_BASE + "/chat/completions",
                               json.dumps(payload, ensure_ascii=False).encode(),
                               {"Authorization": "Bearer " + ARK_KEY,
                                "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())


def fingerprint(key):
    """认得出是哪把 key，又不泄漏它。全文任何时候都不许打出来。"""
    return "%s…%s" % (key[:6], key[-4:]) if len(key) >= 10 else ("（无）" if not key else "…")


def identity():
    """这个进程的垫片配置。跨进程比对的就是这三样。"""
    return {"thinking": THINKING, "base": ARK_BASE, "key": fingerprint(ARK_KEY)}


def probe(port, timeout=1.0):
    """问端口上那位是谁。不是垫片就回 None。"""
    try:
        d = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/" % port, timeout=timeout).read())
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("ok") and "thinking" in d else None


def ensure(port=None):
    """
    保证垫片在跑，返回该塞给 claude CLI 的环境变量。

    和 clishim.ensure() 同一个形状，方便 scene.py 用同一套代码起 agent ——
    区别只在于这个上游说的是 OpenAI 协议，要翻译。

    **端口通了不等于可以用。** 思考开关和方舟 key 都是垫片**进程启动时读一次**
    的常量，改 .env 影响不到已经在跑的那个。原来这里探到端口通就直接复用，于是：
    上一轮起了个开思考的垫片没退出，这一轮改成关思考再跑 —— 端口是通的，
    复用，拿到的还是开思考那个，慢 2.6 倍，零提示。key 换了更糟：请求静默
    发到旧账号。所以复用前核对身份，对不上就当场停，把两边都打出来。

    不自动去杀那个进程 —— 它可能是别人正在用的。
    """
    if not ARK_KEY:
        return {}
    port = port or int(os.environ.get("EXAM_ARKSHIM_PORT", "8898"))
    import socket
    with socket.socket() as s:
        s.settimeout(0.4)
        busy = s.connect_ex(("127.0.0.1", port)) == 0
    if busy:
        live, want = probe(port), identity()
        if live is None:
            raise RuntimeError(
                "127.0.0.1:%d 上蹲着的不是方舟垫片。换个端口："
                "EXAM_ARKSHIM_PORT=8899，或先腾出来：lsof -ti:%d | xargs kill" % (port, port))
        diff = [(k, live.get(k), want[k]) for k in want if live.get(k) != want[k]]
        if diff:
            raise RuntimeError(
                "127.0.0.1:%d 上在跑的垫片跟这次要的对不上，%s。\n"
                "它是上一轮留下的 —— 那些设置是进程启动时读死的，改 .env 影响不到它。\n"
                "换掉它：lsof -ti:%d | xargs kill，或换端口 EXAM_ARKSHIM_PORT=8899"
                % (port, "；".join("%s 在跑的是 %r、这次要 %r" % (k, a, b)
                                   for k, a, b in diff), port))
    else:
        import subprocess
        subprocess.Popen([sys.executable, os.path.abspath(__file__),
                          "--port", str(port), "-q"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(40):
            time.sleep(0.25)
            with socket.socket() as s2:
                s2.settimeout(0.4)
                if s2.connect_ex(("127.0.0.1", port)) == 0:
                    break
        else:
            return {}
    # ANTHROPIC_API_KEY 必须有值，CLI 才会走 BASE_URL 而不是订阅；
    # 真正的鉴权在垫片里用方舟的 key 完成，这里给什么都行
    return {"ANTHROPIC_API_KEY": "arkshim", "ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % port}


def make_handler(verbose, timeout):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                return self._send(400, b'{"error":"bad json"}')

            # Claude Code 会先问 token 数。给个粗估就够，它只拿来做上下文管理
            if self.path.rstrip("/").endswith("count_tokens"):
                chars = len(raw.decode("utf-8", "replace"))
                return self._send(200, json.dumps({"input_tokens": chars // 3}).encode())

            model = d.get("model") or "doubao-seed-evolving"
            want_stream = bool(d.get("stream"))
            if verbose:
                print("  ← %s stream=%s msgs=%d tools=%d hdr=%s"
                      % (self.path, want_stream, len(d.get("messages") or []),
                         len(d.get("tools") or []),
                         dict((k, v) for k, v in self.headers.items()
                              if k.lower() in ("accept", "anthropic-version", "anthropic-beta"))),
                      flush=True)
            t0 = time.time()
            try:
                ark = call_ark(to_openai(d), timeout)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                if verbose:
                    print("  ✗ 方舟 %s %s" % (e.code, body[:200]), flush=True)
                return self._send(e.code, json.dumps(
                    {"type": "error", "error": {"type": "api_error", "message": body[:400]}}).encode())
            except Exception as e:
                return self._send(502, json.dumps(
                    {"type": "error", "error": {"type": "api_error", "message": str(e)[:300]}}).encode())

            resp = to_anthropic(ark, model)
            if verbose:
                kinds = [b["type"] for b in resp["content"]]
                print("  %s → %s  %.1fs  %s  out=%s tok"
                      % (model, resp["stop_reason"], time.time() - t0, kinds,
                         resp["usage"]["output_tokens"]), flush=True)

            if not want_stream:
                return self._send(200, json.dumps(resp, ensure_ascii=False).encode())
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            try:
                nb = 0
                for chunk in sse(resp):
                    self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                    nb += len(chunk)
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
                if verbose:
                    print("  → SSE 写出 %d 字节，关闭连接" % nb, flush=True)
            except BrokenPipeError:
                pass


        def do_GET(self):
            # 身份牌。ensure() 复用之前拉这个对一对 —— 思考开关和 key 都是
            # 启动时读死的，光看端口通不通认不出这是不是自己要的那个垫片
            self._send(200, json.dumps(dict(identity(), ok=True)).encode())
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("EXAM_ARKSHIM_PORT", "8898")))
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args()
    if not ARK_KEY:
        print("没有 EXAM_SCENE_ARK_KEY / ARK_API_KEY")
        return 1
    print("方舟垫片就绪：127.0.0.1:%d → %s" % (a.port, ARK_BASE))
    print("用法：ANTHROPIC_API_KEY=x ANTHROPIC_BASE_URL=http://127.0.0.1:%d "
          "claude -p --model doubao-seed-evolving …" % a.port)
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port),
                                    make_handler(not a.quiet, a.timeout)).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
