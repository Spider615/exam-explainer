#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mailer.py —— 发验证码邮件（SMTP）

    python pipeline/mailer.py you@example.com      自检：真发一封测试信

配置（.env）
------------
    SMTP_HOST     smtp.example.com
    SMTP_PORT     465（隐式 SSL）/ 587（STARTTLS）。不写按端口猜
    SMTP_USER     登录账号，通常就是发信邮箱
    SMTP_PASS     密码或授权码（163/QQ 邮箱要的是**授权码**，不是登录密码）
    SMTP_FROM     发信地址，不写就用 SMTP_USER
    SMTP_FROM_NAME 发信人显示名，默认 exam-explainer

没配 SMTP 会怎样
----------------
**不报错，把验证码打到后端日志里**，并且如实告诉前端「这封信没发出去」。

理由是这条路只有两种失败方式，得分开对待：配置没填好（开发中，看日志继续
用就是了）和配置填了但发信失败（真故障，必须报出来）。混成一个「发送失败」
的话，本地开发每次都得先去配一个 SMTP 才能点登录按钮。

**验证码绝不回传给前端**。回传等于任何人输入任意邮箱就能登进来 ——
那不是「开发模式」，那是没有登录。
"""
import hashlib, os, smtplib, ssl, sys
from email.message import EmailMessage
from email.utils import formataddr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _l in (open(os.path.join(ROOT, ".env"), encoding="utf-8")
           if os.path.exists(os.path.join(ROOT, ".env")) else []):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

HOST = os.environ.get("SMTP_HOST", "").strip()
PORT = int(os.environ.get("SMTP_PORT", "0") or 0)
USER = os.environ.get("SMTP_USER", "").strip()
PASS = os.environ.get("SMTP_PASS", "").strip()
FROM = os.environ.get("SMTP_FROM", "").strip() or USER
FROM_NAME = os.environ.get("SMTP_FROM_NAME", "exam-explainer").strip()

CODE_TTL_MIN = int(os.environ.get("EXAM_CODE_TTL_MIN", "10"))


def _ascii(s):
    try:
        (s or "").encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


# 账号密码里混进中文是**配置没填好**，不是发信故障，所以要在这儿就拦下来。
# 不拦的话，报错来自 smtplib 深处的 `initial_response.encode('ascii')`
# （SMTP AUTH 走的是 base64(ASCII)，中文根本编码不出去），
# 一个 UnicodeEncodeError 的调用栈完全看不出「你把提示文字当密码粘进去了」。
# 实测就是这么踩的：SMTP_PASS 填成了「授权码_cce6」。
BAD_CRED = ("SMTP_USER / SMTP_PASS 里有非 ASCII 字符（中文、全角标点等）—— "
            "多半是把说明文字当成密码粘进去了。QQ 授权码是 16 位纯小写字母。"
            if not (_ascii(USER) and _ascii(PASS)) else None)


def configured():
    """四项齐全、而且账号密码是 SMTP 认得的 ASCII，才算配好。"""
    return bool(HOST and USER and PASS and FROM) and not BAD_CRED


BODY = """你正在登录 exam-explainer。

验证码：%s

%d 分钟内有效，输错 5 次作废。不是你本人操作的话，忽略这封信即可 ——
只有拿到这个验证码才能登录，这封信本身不会让任何人进入你的账号。
"""


def send_code(to, code):
    """
    发一封验证码信。返回 True=真发出去了，False=没配 SMTP（验证码已打进日志）。
    配了但发失败会抛异常 —— 那是真故障，不能悄悄咽掉。
    """
    if not configured():
        print("[mailer] %s，验证码打在这里：%s → %s"
              % (BAD_CRED or "没配 SMTP（SMTP_HOST/USER/PASS/FROM）", to, code),
              flush=True)
        return False

    msg = EmailMessage()
    msg["Subject"] = "exam-explainer 登录验证码 %s" % code
    msg["From"] = formataddr((FROM_NAME, FROM))
    msg["To"] = to
    msg.set_content(BODY % (code, CODE_TTL_MIN))

    port = PORT or 465
    # 465 是隐式 SSL，587/25 是先明文连上再 STARTTLS 升级。两者不能混用 ——
    # 对 465 发 STARTTLS 会挂在握手上，对 587 直接上 SSL 也一样
    if port == 465:
        with smtplib.SMTP_SSL(HOST, port, timeout=20,
                              context=ssl.create_default_context()) as s:
            s.login(USER, PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(HOST, port, timeout=20) as s:
            s.ehlo()
            try:
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass                      # 内网中继可能就是不带 TLS 的
            s.login(USER, PASS)
            s.send_message(msg)
    return True


def hash_code(s):
    """
    存哈希不存明文，验证码和会话 token 都经过这里。

    会话 token 是 32 字节随机串，裸哈希就够。**验证码不是** —— 6 位数字只有
    一百万种，所以调用方要连邮箱一起喂进来（见 api.code_hash）。
    """
    return hashlib.sha256(str(s).encode()).hexdigest()


def main():
    if len(sys.argv) < 2:
        print("用法：python pipeline/mailer.py <收件邮箱>")
        print("当前配置：host=%s port=%s user=%s from=%s → %s"
              % (HOST or "（空）", PORT or "（按需猜）", USER or "（空）",
                 FROM or "（空）", "可发信" if configured() else "未配置，只会打日志"))
        if BAD_CRED:
            print("⚠ " + BAD_CRED)
        return 1
    ok = send_code(sys.argv[1], "123456")
    print("真发出去了" if ok else "没配 SMTP，只打了日志")
    return 0


if __name__ == "__main__":
    sys.exit(main())
