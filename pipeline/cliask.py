#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cliask.py —— 用**订阅**跑一次 claude，拿回文本

    from cliask import ask
    txt = ask("只回 JSON：…")                    # 纯文本
    txt = ask("看图回答…", images=["/abs/a.png"])  # 带图

为什么要这个东西
----------------
订阅**只能通过 claude CLI 用**，没有 HTTP 端点。而 ④ 写断言、③ 的视觉升级
本来都是直接发 HTTP 到中转站的。中转站一欠费，这两步就全断 ——
实测那天 ④ 整卷失败、⑤ 的第8、9题把 6 轮全烧在 401 上。

所以把「用订阅发一次请求」抽出来，让 HTTP 那条路可以整条换掉。

和阶段⑤ 的沙箱不是一回事
------------------------
⑤ 要的是**能执行代码的 agent**：写文件、跑门禁、读报错、再改。
这里要的只是**一次问答**，所以默认不给任何工具 —— 少一个工具就少一条
它跑去读无关文件、把上下文撑大的路径。只有传了图片才开 Read，
因为 CLI 读不了 stdin 里的 base64，图只能给绝对路径让它自己读。

代价要知道
----------
带图那条路每张图一次 Read 工具调用，比把图直接塞进 payload 的方式贵得多
（实测单题 6 轮 165 秒 $0.41）。纯文本那条路没有这个问题。
所以 ③ 的视觉升级如果在意成本，豆包仍然是更划算的选择。
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLI = next((p for p in ("/opt/homebrew/bin/claude",
                        os.path.expanduser("~/.nvm/versions/node/v25.2.1/bin/claude"),
                        "/usr/local/bin/claude") if os.path.exists(p)), None)

MODEL = os.environ.get("EXAM_CLI_MODEL", "claude-sonnet-5")

# 这几个一旦存在，CLI 就会去连它们指向的中转而不是订阅。
# 显式声明用订阅，就不能因为环境里恰好有个 key 就偷偷改道。
ANTHROPIC_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")


def available():
    return CLI is not None


def ask(prompt, images=None, model=None, timeout=1800):
    """
    跑一次，返回 stdout 文本。失败抛异常，由调用方决定要不要重试。

    超时杀**整个进程组** —— CLI 会 fork，只杀直接子进程的话孙进程会活下来
    继续占额度（阶段⑤ 实测超时后又跑了一个半小时）。
    """
    if not CLI:
        raise RuntimeError("找不到 claude 可执行文件，订阅通道不可用")
    env = {k: v for k, v in os.environ.items() if k not in ANTHROPIC_VARS}
    cmd = [CLI, "-p", "--model", model or MODEL]
    if images:
        # CLI 读不了 stdin 里的图，只能把绝对路径写进 prompt 让它用 Read 读
        cmd += ["--allowed-tools", "Read"]
        prompt = ("先用 Read 工具读下面这些图片，再回答问题：\n"
                  + "\n".join(os.path.abspath(p) for p in images)
                  + "\n\n" + prompt)
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=env,
                         start_new_session=True, cwd=ROOT)
    try:
        out, err = p.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        import signal
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            p.kill()
        p.communicate()
        raise
    if p.returncode != 0:
        raise RuntimeError("claude CLI 退出码 %d：%s" % (p.returncode, (err or "")[-300:]))
    return out or ""


if __name__ == "__main__":
    print(ask(sys.argv[1] if len(sys.argv) > 1 else "只回两个字：可用"))
