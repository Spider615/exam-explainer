#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api.py —— 后端 JSON API（FastAPI）

    .venv/bin/uvicorn pipeline.api:app --host 127.0.0.1 --port 8712 --reload

职责边界
--------
后端**只做编排和数据**，不拼 HTML。页面长什么样是 React 的事。

  POST   /api/auth/code           要一封验证码信（body: {"email": "..."}）
  POST   /api/auth/verify         用验证码换会话（body: {"email":..., "code":...}）
  POST   /api/auth/logout         退出
  GET    /api/auth/me             当前登录的是谁；没登录给 401

  POST   /api/upload              收 PDF，起一个后台任务跑管线
  GET    /api/jobs/{id}           轮询任务状态与日志
  GET    /api/papers              已处理的试卷列表
  DELETE /api/papers/{name}       删一份
  POST   /api/papers/delete       批量删（body: {"names": [...]}）
  GET    /api/papers/{name}       某份试卷的完整结构化数据（题干/选项/插图/场景）
  GET    /api/papers/{name}/img/  插图静态文件
  GET    /api/papers/{name}/scene.js  该卷可用场景的 JS（含运行时）

除 /api/auth/* 外一律要登录，而且**试卷按账号隔离**：拿不到会话就是 401，
拿得到但这份卷子不是你的，一律 404 —— 和「不存在」给同一个回答，
否则拿卷名去试就能问出别人库里有什么。

数据从哪来
----------
**库**，不是文件系统。`work/<卷名>/` 是构建产物目录，`store.publish` 之后
库才是唯一真相源。之前直接读 work/ 出过两次事：两棵工作目录静默漂移
（改完管线只重跑一棵，页面上还是旧数据），以及两个进程并发写同一份
questions.json。现在没 publish 就不算数，漂移无从发生。

资产（插图 / 整页渲染 / 公式裁图）一律**由本服务代理**，不直接暴露对象存储地址。
所以后端从本地目录切到 MinIO，前端的 URL 一个都不用改。

为什么管线是 Python：PDF 解析、坐标运算、数值求解、无头浏览器编排，
这几件事在 Node 生态里没有对等的库。前端不必因此也用 Python。
"""
import json, os, re, secrets, signal, subprocess, sys, threading, time, unicodedata, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import segment          # 跨页表的合并规则只写一份，前后端不能各有一套
import store            # 库与资产存储；API 只经过它
import kp               # 知识点词表：标签的名字与所属章由后端给，前端不再存一份
import mailer           # 验证码信；没配 SMTP 时退化成打日志

from fastapi import Body, Depends, FastAPI, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
UPLOADS = os.path.join(WORK, "_uploads")
RUNS = os.path.join(ROOT, "runs")
PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

app = FastAPI(title="exam-explainer")
# allow_credentials 是必须的：会话是 cookie，跨源请求默认不带 cookie。
# 开发时前端在 5173、API 在 8712，是两个源。上线同源部署时这条不生效也无害。
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173",
                                                  "http://localhost:5173"],
                   allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

JOBS = {}
# 已经开跑、但还没 publish 进库的卷名 → 开跑的人。库要等 ①②②b 跑完才认得出
# 这份卷子，这个 dict 补的就是那几分钟的空窗：卷名去重和「同名不许再开一条」
# 都要连它一起判。run.sh 里没有 --workers，单进程，记在内存里就够。
CLAIMS = {}
LOCK = threading.Lock()
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")   # 日志里的控制字符会污染 JSON


def safe_name(fn):
    base = os.path.basename((fn or "").replace("\\", "/"))
    base = re.sub(r"[^\w一-鿿.\-（）()]+", "_", base).lstrip(".")
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return (base or "upload.pdf")[:120]


def check_name(name):
    """卷名会进路径也会进 SQL。SQL 那边是参数化的，这里挡的是路径穿越。"""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "非法的试卷名")
    return name


def paper_dir(name):
    d = os.path.join(WORK, check_name(name))
    if not os.path.isdir(d):
        raise HTTPException(404, "没有这份试卷")
    return d


# ---------------------------------------------------------------- 登录
#
# 邮箱验证码，没有密码。做成这样的取舍见 schema.sql：没有密码就没有密码泄露、
# 没有撞库、没有找回流程，代价是每次新设备登录要收一封信。
#
# 会话放 **HttpOnly cookie**，不放 localStorage：token 一旦能被 JS 读到，
# 页面上任何一处 XSS 都等于会话被拿走。而这个页面要渲染的是模型生成的
# HTML/JS 场景 —— 恰恰是最不该把凭据暴露给 JS 的那类页面。
COOKIE = "ee_session"
SESSION_DAYS = int(os.environ.get("EXAM_SESSION_DAYS", "30"))
CODE_TTL_MIN = int(os.environ.get("EXAM_CODE_TTL_MIN", "10"))
# 上了 https 再打开。本地 http 开着的话浏览器根本不会存这个 cookie
COOKIE_SECURE = os.environ.get("EXAM_COOKIE_SECURE", "0") == "1"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

# 同一个 IP 每小时能要几次码。挡的是「拿这个接口当免费群发器」——
# 邮箱那一层已经有 60 秒冷却，但换邮箱就能绕过，只有按来源限才拦得住。
IP_QUOTA = int(os.environ.get("EXAM_CODE_IP_QUOTA", "20"))
IP_HITS = {}

# 上线走 Cloudflare Tunnel：cloudflared 从本机回源，于是 request.client.host
# 对每个请求都是 127.0.0.1 —— 全世界的人共用一个桶，第 21 封信开始整站 429。
# 所以对端是回环时改看 Cloudflare 放进来的真实来源。
#
# 只在对端是回环时才信这个头：这个服务只绑 127.0.0.1，除了同机的 cloudflared
# 没人连得进来，所以回环 == 来自我们自己的隧道。要是哪天改成绑 0.0.0.0，
# 这个前提就没了 —— 那时任何人都能自带一个 CF-Connecting-IP 把配额刷空。
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def client_ip(request):
    peer = request.client.host if request.client else "?"
    if peer not in LOOPBACK:
        return peer
    fwd = request.headers.get("cf-connecting-ip") \
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return fwd or peer


def ip_allow(ip):
    now = time.time()
    with LOCK:
        hits = [t for t in IP_HITS.get(ip, []) if now - t < 3600]
        if len(hits) >= IP_QUOTA:
            IP_HITS[ip] = hits
            return False
        hits.append(now)
        IP_HITS[ip] = hits
        if len(IP_HITS) > 5000:           # 别让它无限长大
            for k in [k for k, v in IP_HITS.items() if not v or now - v[-1] > 3600]:
                IP_HITS.pop(k, None)
    return True


def token_hash(tok):
    return mailer.hash_code(tok)


def code_hash(email, code):
    """
    验证码连着邮箱一起哈希。

    6 位数字只有一百万种，**光哈希挡不住手里有库的人** —— 一张彩虹表就还原了。
    连邮箱一起哈希至少让这张表不能一次算好通吃所有人。真正挡住这件事的是
    有效期 10 分钟、错 5 次作废、一码一用（见 store.check_login_code），
    以及库能被读走的时候，对方本来就能直接往 sessions 里插一行。
    """
    return mailer.hash_code("%s:%s" % (store.norm_email(email), code))


def current_user(request: Request):
    """
    这次请求是谁。没登录就 401 —— 除 /api/auth/* 外每个接口都挂着它。

    不做「没登录就当匿名用户」的降级：那会让「忘了加鉴权」和「有意公开」
    在代码里长得一模一样。要公开的接口自己不挂这个依赖，一眼能看出来。
    """
    u = store.session_user(token_hash(request.cookies.get(COOKIE, "")))
    if not u:
        raise HTTPException(401, "请先登录")
    return u


@app.post("/api/auth/code")
def auth_code(request: Request, email: str = Body(..., embed=True)):
    """
    发一封验证码信。

    **不管这个邮箱有没有注册过，回答都一样。** 分开回答的话，这个接口就成了
    「查这个人有没有在用」的查询接口。注册和登录也因此是同一条路：
    第一次验证成功时才建账号（见 /api/auth/verify）。
    """
    email = store.norm_email(email)
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "邮箱格式不对")
    if not ip_allow(client_ip(request)):
        raise HTTPException(429, "要得太频繁了，过一会儿再试")

    code = "%06d" % secrets.randbelow(1000000)
    if not store.put_login_code(email, code_hash(email, code), CODE_TTL_MIN):
        raise HTTPException(429, "刚发过一封，60 秒后才能再要")
    try:
        delivered = mailer.send_code(email, code)
    except Exception as e:
        # 配了 SMTP 但发不出去 = 真故障，要说出来。这时候库里那个码已经写下了，
        # 但没人拿得到它 —— 不算漏洞，只是这次登录得重来
        print("[auth] 发信失败 %s：%s" % (email, e), flush=True)
        raise HTTPException(502, "验证码发不出去（%s）" % str(e)[:120])
    return {"sent": True, "delivered": delivered, "ttlMinutes": CODE_TTL_MIN,
            # 没配 SMTP 时如实说清楚验证码在哪，别让人对着一个永远收不到的
            # 输入框干等。**验证码本身不回传** —— 那等于没有登录
            "hint": None if delivered else "后端还没配 SMTP，验证码打在服务端日志里"}


@app.post("/api/auth/verify")
def auth_verify(response: Response, email: str = Body(...), code: str = Body(...)):
    """验证码换会话。这个邮箱第一次来就顺手建账号 —— 注册和登录是同一条路。"""
    email = store.norm_email(email)
    ok, why = store.check_login_code(email, code_hash(email, (code or "").strip()))
    if not ok:
        raise HTTPException(400, why)
    user, fresh = store.create_user(email)
    tok = secrets.token_urlsafe(32)
    store.create_session(user["id"], token_hash(tok), SESSION_DAYS)
    response.set_cookie(COOKIE, tok, max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=COOKIE_SECURE, path="/")
    return {"email": user["email"], "isNew": fresh}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    store.drop_session(token_hash(request.cookies.get(COOKIE, "")))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(user=Depends(current_user)):
    return {"email": user["email"]}


def mine(name, user):
    """
    这份卷子必须是这个账号的，否则 404。

    **不存在**和**存在但不是你的**给同一个回答：分开回答的话，拿一批卷名
    来试就能问出别人库里有什么。
    """
    check_name(name)
    exists, owner = store.paper_owner(name)
    if not exists or owner != user["id"]:
        raise HTTPException(404, "没有这份试卷")
    return name


# ---------------------------------------------------------------- 任务
def killpg(pid):
    """连同整个进程组一起杀。子进程会 fork，只杀直接子进程会留下孙进程。"""
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def job_log(jid, s):
    with LOCK:
        JOBS[jid]["log"].append(CTRL.sub("", s)[:400])


def run_step(jid, label, cmd, timeout=900):
    """
    跑管线的一步，返回是否成功。

    **边跑边把 stdout 送进日志**，不是等它跑完一次性吐出来 —— ④ 写断言一卷要十几
    分钟，攒着的话页面上十几分钟一行不动，跟卡死没有区别。这也是阶段③ 逐题回报
    的同一个道理。stderr 并进 stdout，失败时那几行正好是最有用的。
    """
    job_log(jid, "▸ " + label)
    with LOCK:
        JOBS[jid]["step"] = label
    timed = {"hit": False}
    # PYTHONUNBUFFERED 不能省。子进程是 Python，stdout 不是 tty 时它按块缓冲，
    # 不掀掉这层缓冲上面那句「边跑边送」就是空话 —— 实测 ④ 跑了二十分钟，
    # 日志里只有孤零零一行「▸ ④ 写断言」，和卡死长得一模一样。
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    # start_new_session 让子进程自成一个进程组，这样超时能 killpg 整组端掉 ——
    # 子进程自己还会 fork，只杀直接子进程会留下孙进程继续烧额度（⑤ 实测超时后
    # 又跑了一个半小时）。
    #
    # **它管不了服务重启。** 试过用 atexit 在退出时收割子进程，实测无效：
    # atexit 只在解释器正常退出时执行，而 kill 发的是 SIGTERM，裸 python 和
    # uvicorn 下都不触发 —— 在唯一需要它的场景里完全不会跑。
    # 而且方向也不对：孤儿 spec.py 多写的那几份 spec 全落库了，下次重跑直接复用，
    # 杀掉反而是浪费。真正断掉的是**驱动链条的那个线程**（JOBS 是进程内的 dict），
    # 要修得让任务状态可恢复，不是去杀子进程。
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, env=env, start_new_session=True)
    def kill():
        timed["hit"] = True
        killpg(p.pid)

    killer = threading.Timer(timeout, kill)
    killer.start()
    try:
        for raw in p.stdout:
            # 进度条那类回车刷新的输出，splitlines 会按 \r 拆开，不至于连成一长条
            for piece in raw.splitlines():
                if piece.strip():
                    job_log(jid, "  " + piece.rstrip())
        rc = p.wait()
    finally:
        killer.cancel()
    if timed["hit"]:
        job_log(jid, "  ✗ 超时（%d 秒）被终止" % timeout)
    elif rc != 0:
        job_log(jid, "  ✗ 退出码 %d" % rc)
    return rc == 0


def solve_paper(jid, name):
    """
    阶段③ 逐题解，**每解完一题立刻写库**。

    不攒到最后一起提交：一卷十几道题要跑半小时，中途出错或被打断时，
    攒着的那些就全丢了。逐题落库的话，解出来多少就留下多少。
    """
    import solve as solver          # 与上面的 segment / store 同一条 sys.path

    def log(s):
        job_log(jid, s)

    paper = store.get_paper(name)
    qs = paper["questions"] if paper else []

    # 开跑就报一声。压轴题要十几分钟，只在解完时报的话，页面上看起来像卡死了
    def on_start(q):
        log("  → 第%d题 开跑（%s）" % (q["n"], q.get("type") or "?"))

    def on_done(r, i, total):
        n, kind, note = r
        log(("  第%d题 %s" if kind != "fail" else "  ✗ 第%d题 %s") % (n, note))
        with LOCK:
            JOBS[jid]["step"] = "解题 %d/%d" % (i, total)
            JOBS[jid]["solved"] = i

    res = solver.solve_many(name, qs, on_done=on_done, on_start=on_start)
    ok = sum(1 for r in res if r[1] != "fail")
    fail = len(res) - ok
    log("✓ 解题结束：%d 题成功，%d 题失败" % (ok, fail))
    return ok


def step_path(mod):
    return [PY, os.path.join(ROOT, "pipeline", mod)]


# ⑤ 一题几分钟到几十分钟，一卷可能跑几个钟头。超时按整卷给，可用环境变量调。
SCENE_TIMEOUT = int(os.environ.get("EXAM_SCENE_TIMEOUT", 4 * 3600))

# 单题重跑的轮次上限。**比整卷的默认 6 少**，因为这是「点一下等结果」的交互：
# scene.py 一轮上限 40 分钟，6 轮就是 4 小时，和整卷超时一样长，没人会等。
# 实测多数题两三轮就过（海南卷第19题重跑是第 1 轮、14 分钟），4 轮够用，
# 最坏压到 2.7 小时。超时再留 10 分钟给进程启停和落库。
RESCENE_ROUNDS = int(os.environ.get("EXAM_RESCENE_ROUNDS", "4"))
RESCENE_TIMEOUT = int(os.environ.get("EXAM_RESCENE_TIMEOUT",
                                     2400 * RESCENE_ROUNDS + 600))


def finish_paper(jid, name):
    """
    ③ 之后的收尾：③b 目录 → ④ 写断言 → ④b spec 自检 → ⑤ 生成场景 → ⑦ 装配。

    ⑤ 前面那道闸门换掉了，不是拆掉
    ------------------------------
    原来 `specs.status` 一律 draft，必须人审才能进 ⑤ —— 因为断言是整条链上唯一
    没有下游检查的环节。要做到全自动，就得拿一个**不是人**的东西顶上那道闸门，
    而不是直接 `--allow-draft` 把它跳过去。

    顶上来的是 `speccheck.py`：拿 spec 自带的 `reference`（④ 写的可执行受力方程）
    跑出数据，再用 **spec 自己的 invariants** 去验它。自己的实现满足不了自己的断言
    = 内部矛盾 = 直接 rejected，进不了 ⑤。这不是「再问一个模型对不对」，是一次计算。
    没有 reference 的 spec 验不了，也判 rejected —— fail-closed，宁可少一个动画。

    **它抓不住的仍然要说清楚**：③ 从一开始就理解错题、④ 忠实地把错误理解写成
    彼此自洽的 spec，这一关会全绿。那要对照原卷，是人的活。所以页面上
    「断言」这一栏标的是自动核验，不是人审。

    失败策略
    --------
    ③b/④/④b/⑤ 任何一步失败都不算整条任务失败：前面的产出已经落库、页面能看，
    缺什么页面上都照实标出来（没断言的标「无断言 · 未被检验」，没动画的退回原卷插图）。
    **只有 ⑦ 失败才是真失败** —— 它是这一步唯一的交付物。
    """
    def phase(label):
        with LOCK:
            JOBS[jid].update(state="finishing", step=label)

    phase("③b 目录")
    if not run_step(jid, "③b 目录（短标题与短答案）", step_path("outline.py") + [name],
                    timeout=600):
        job_log(jid, "  ⚠ ③b 没跑成，目录里这些题只显示题号，不显示标题")

    # ③c 知识点：整卷一次调用，几十秒。排在 ③ 之后是因为用得上解法。
    # 失败不中止 —— 知识点缺了页面照样能看题看讲解，为一个标签把跑了半小时的
    # 卷子判失败，代价不对等
    phase("③c 知识点")
    if not run_step(jid, "③c 知识点标注", step_path("kpmark.py") + [name],
                    timeout=900):
        job_log(jid, "  ⚠ ③c 没跑成，这些题在页面上会写「没挂上知识点」")

    # ④c 动画选题，**排在 ④ 之前**。它只要一次调用 28 秒判完整卷，而写一份完整
    # spec（spec + 参考实现两次调用）实测约 6 分钟一道 —— 便宜的筛子必须排在贵的前面。
    # 实测重庆卷：原来的顺序让 ④ 对 10 道题写了完整 spec，最后只有 5 道真出了动画，
    # 白跑约 30 分钟；海南卷 9 道全白跑。
    #
    # 超时给 2400 秒，不是 600。「28 秒判完整卷」是顺利时的数，实测同一份卷子同一段
    # payload 打四次，单次耗时 77 / 624 / 544 / 112 秒 —— DeepSeek 慢起来能到十分钟。
    # 而 pick.ask() 自带 3 次重试，最坏就是三个十分钟叠起来，600 秒必然被 killpg 掉。
    # （pick 那边 urlopen 的 timeout=300 拦不住这种：urllib 那个是每次 socket 读的
    # 超时，不是总时限，响应慢慢往外挤的时候压根不触发，624 秒那次就是这么过去的。）
    # 被砍掉的后果不是「少一个动画」而是整卷一道都没有：④c fail-closed，没判过的题
    # 一律不写断言。宁可多等，也不能让一次网络抖动把整卷的动画全废掉。
    phase("④c 动画选题")
    if not run_step(jid, "④c 动画选题（哪些题值得做动画）",
                    step_path("pick.py") + [name], timeout=2400):
        job_log(jid, "  ⚠ ④c 没跑成。没判过的题一律不写断言、不做动画 —— fail-closed")

    # ④ 只给 ④c 选中的题写断言。没被选中的题在页面上标「无断言 · 未被检验」，
    # 这是有意的取舍：那层校验只查 spec 内部自洽，查不出「理解错题但写得自洽」，
    # 为它每卷多花半小时不划算。要给某道题补，随时 spec.py --only N。
    phase("④ 写断言")
    if not run_step(jid, "④ 写断言（只做选中的题）",
                    step_path("spec.py") + [name, "--picked"], timeout=3600):
        job_log(jid, "  ⚠ ④ 没跑完，受影响的题在页面上标「无断言 · 未被检验」")

    # ④b 纯计算，不调模型。它是 ⑤ 的准入闸门，所以即使 ④ 半途而废也要跑 ——
    # 已经写出来的那些 spec 照样要过这一关才能进 ⑤。
    phase("④b spec 自检")
    if not run_step(jid, "④b spec 自检（自洽才放行）",
                    step_path("speccheck.py") + [name, "--apply"], timeout=900):
        job_log(jid, "  ⚠ ④b 没跑成。没过自检的 spec 一律不进 ⑤ —— 宁可少几个动画")

    out = os.path.join(WORK, name, "out.html")
    # ⑦ 先装一次。⑤ 可能要跑一两个钟头，而 out.html 是这条链唯一的离线交付物 ——
    # 让它一直缺着，等于这段时间里「导出的那份」根本不存在。
    # 网页那条路不受影响：它读库，⑤ 每绿灯一道题，刷新一下就多一个动画。
    phase("⑦ 装配成页（先出一版，无动画）")
    run_step(jid, "⑦ 装配成页（先出一版）", step_path("assemble.py") + [name, "-o", out],
             timeout=1800)

    phase("⑤ 生成场景")
    job_log(jid, "  ⑤ 是带反馈的循环（写代码→跑门禁→读报错→重来），一题几分钟到几十分钟，多题并行")
    scened = run_step(jid, "⑤ 生成场景", step_path("scene.py") + [name],
                      timeout=SCENE_TIMEOUT)
    if not scened:
        job_log(jid, "  ⚠ ⑤ 没跑完，没绿灯的题在页面上退回原卷插图")

    # ⑦ 再装一次，把通过门禁的动画装进去。⑤ 一个都没做成就不必重装
    phase("⑦ 装配成页")
    if not run_step(jid, "⑦ 装配成页（带动画）", step_path("assemble.py") + [name, "-o", out],
                    timeout=1800):
        with LOCK:
            JOBS[jid].update(state="error", err_code="assemble",
                             err="⑦ 装配失败（题目与解法已入库，网页照常可看）")
        return
    with LOCK:
        JOBS[jid].update(state="done", step="完成", out=out)
    job_log(jid, "✓ 全部完成 → %s" % out)


def run_pipeline(jid, pdf_path, name, owner_id=None):
    """
    网页上传走的整条链：
    ① 摄入 → ② 切分 → ②b 公式 → ②c 入库 → ②d 标准答案 → ③ 解题 → ③b 目录
    → ③c 知识点 → ④ 断言
    → ④b spec 自检 → ⑤ 生成场景 → ⑦ 装配。

    和 `pipeline/run.py` 那条命令行链是同一串。两条入口跑出来的东西必须一样，
    否则「上传的卷子」和「命令行跑的卷子」会在页面上呈现出两种完成度，
    而没有任何东西能提示这件事 —— 网页那条链一度只跑到 ③。
    """
    def log(s):
        job_log(jid, s)

    # 挂在哪一步。存进 JOBS，页面才判得出「这条失败说的是不是眼下这一格」——
    # 口径跟 stage_of 一致；②b 没有自己的标志位，归到 ② 上
    step_code = {"① 摄入": "ingest", "② 切分": "segment", "②b 公式识别": "segment"}

    out = os.path.join(WORK, name)
    steps = (
        ("① 摄入", [PY, os.path.join(ROOT, "pipeline", "ingest.py"), pdf_path, "-o", out]),
        ("② 切分", [PY, os.path.join(ROOT, "pipeline", "segment.py"), out]),
        # ②b 不能省。缺了它，选项只有被压平的一维文本
        # （`(GMT²)/(4π²) 1 3 卫星距地面的高度为 ( ) −R`），
        # 下游解题时模型看不懂公式 —— 实测重庆卷第10题就是因此漏判了一个选项，
        # 而它如实报告了「选项的表达式无法识别」，不是物理算错。
        ("②b 公式识别", [PY, os.path.join(ROOT, "pipeline", "mathvlm.py"), out]),
    )
    try:
        for label, cmd in steps:
            if not run_step(jid, label, cmd):
                with LOCK:
                    JOBS[jid].update(state="error", err=label + " 失败",
                                     err_code=step_code.get(label))
                return
        q = json.load(open(os.path.join(out, "questions.json"), encoding="utf-8"))
        # 发布：构建产物 → 库。没这一步页面上看不到它，这是有意的 ——
        # work/<卷名>/ 只是中间目录，库才是唯一真相源。
        log("▸ 发布入库")
        with LOCK:
            JOBS[jid]["step"] = "发布入库"
        r = store.publish(out, name, owner_id=owner_id)
        n_q = len(q["questions"])
        # 这里就把卷子标成可看了。解题一道要两三分钟，一卷十几道就是半小时，
        # 让人干等半小时才看到题目是不可接受的 —— 题先出来，解法逐题填进去。
        with LOCK:
            JOBS[jid].update(state="solving", name=name, n=n_q,
                             warnings=q.get("warnings", []), solved=0, total=n_q)
        log("✓ 切出 %d 题，入库 %d 份资产。可以开始看了，解题在后台继续" % (n_q, r["assets"]))
        # ②d 标准答案：纯代码、几十毫秒，读 doc.json 按题号切。抽不到就全记
        # none —— 高考真题本来就不带答案，那不是失败。失败也不中止整条链
        run_step(jid, "②d 标准答案", step_path("refans.py") + [name], timeout=120)
        solve_paper(jid, name)
        finish_paper(jid, name)
    except Exception as e:
        with LOCK:
            JOBS[jid].update(state="error", err=str(e))
        log("✗ " + str(e))
    finally:
        # 名字让出来。不放的话这份卷子再也重传不了 —— 上面那道闸会一直拦着
        with LOCK:
            CLAIMS.pop(name, None)
        # 上传的原件收掉。它只有 ① 摄入 用得着，之后该拿的都进了 `work/<卷名>/`。
        # 路径改成按任务分开之后，同一份 PDF 每传一次就多一个文件（原来是同名
        # 互相覆盖），不收的话 `work/_uploads/` 会一直涨
        try:
            os.remove(pdf_path)
        except OSError:
            pass


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), user=Depends(current_user)):
    data = await file.read()
    if len(data) > 80 * 1024 * 1024:
        raise HTTPException(413, "文件超过 80 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "不是有效的 PDF（当前只接受有文字层的 PDF，不支持扫描件）")
    fn = safe_name(file.filename)
    name = re.sub(r"-?题目版$", "", fn[:-4]) or fn[:-4]
    # 卷名同时是 `work/<卷名>/` 的目录名，全局唯一。自己重传同一份是「重跑」，
    # 名字不变；撞上**别人**的卷子就自动加后缀，两条管线不会写进同一个目录。
    #
    # 占用要连 CLAIMS 一起看。只查库的话有个几分钟宽的窗口：卷子要跑完 ①②②b
    # 才 publish，在那之前 `paper_owner` 一直回「不存在」，于是两个账号先后传
    # 同名 PDF（高考真题的文件名本来就长得一样），free_name 一次都不会触发，
    # 两条管线拿到同一个卷名、同一个构建目录、抢同一行 papers。
    with LOCK:
        claimed = dict(CLAIMS)
    exists, owner = store.paper_owner(name)
    if (exists and owner != user["id"]) or claimed.get(name, user["id"]) != user["id"]:
        name = store.free_name(name, also_taken=claimed)

    # 同一份卷子不能同时跑两条链。两条 run_pipeline 写同一个 `work/<卷名>/`：
    # ingest 原地覆写 doc.json 和页面 PNG，而另一条链正在读它们（页面上会冒出
    # 一条「②b 公式识别 失败」，而卷子其实是好的）；再往后 ③④⑤ 会把整份卷子的
    # 模型额度跑两遍，⑤ 按四小时上限各跑一次。
    #
    # 这道闸必须在后端。前端那个「上传中禁用拖拽框」挡不住 —— 它是前端状态，
    # 刷新、换标签页、退出再登进来都绕得过去，而恰恰是「还没入库」那几分钟里
    # 页面上什么都看不到，人最容易以为上一次没成、再传一遍。
    if active_job_for(name) or pipeline_running(name):
        raise HTTPException(409, "这份卷子正在跑，等它跑完再重传 —— 试卷库里能看到它到哪一步了")

    jid = uuid.uuid4().hex[:12]
    # 落盘要**在闸门之后**，而且路径按任务分开。
    #
    # 原来是收到就以 `_uploads/<原文件名>` 写下去，两个问题叠在一起：写在闸门
    # 之前，所以被 409 挡掉的那次也已经把文件覆盖了；路径只按文件名分，而卷名
    # 撞车时会被 free_name 改成「X (2)」—— 名字分开了，PDF 却还是同一个路径。
    # 于是 B 的上传会把 A 那份 PDF 就地覆写，而 A 的 ingest.py 可能正在读它。
    os.makedirs(UPLOADS, exist_ok=True)
    path = os.path.join(UPLOADS, "%s_%s" % (jid, fn))
    with open(path, "wb") as f:
        f.write(data)
    with LOCK:
        CLAIMS[name] = user["id"]
        JOBS[jid] = {"state": "running", "step": "排队中", "name": name,
                     "owner_id": user["id"],
                     "log": ["收到 %s（%.1f MB）" % (fn, len(data) / 1048576)]}
    threading.Thread(target=run_pipeline, args=(jid, path, name, user["id"]),
                     daemon=True).start()
    return {"job": jid, "name": name}


def active_job_for(name):
    """
    这份卷子现在有没有在跑、跑到哪一步。

    试卷页要靠它显示进度。以前进度只画在上传页上，而切分一完成（3 秒）App 就
    自动跳到试卷页 —— 后面 ③④⑤ 那几十分钟到几小时，页面上一点动静都没有，
    看起来就像什么都没在发生。用户原话：「那为啥我都看不到他处理的状态啊」。

    JOBS 是进程内的 dict，重启后端就空了。这是有意的：任务状态是临时的，
    真结果都在库里 —— 重启后进度带消失，但标志位和题目照样是对的。

    **只认整卷管线，不认单题重跑**（`kind="rescene"`）。重跑一道题的动画不是
    「这份卷子在处理中」：算进来的话，点一下重跑，整份卷子在列表和试卷页上
    都变成「处理中」、六格进度带全亮，而其余十几道题根本没在动。
    单题重跑有自己的可见路径 —— 前端拿那个 jid 单独轮询。
    """
    with LOCK:
        live = [(jid, j) for jid, j in JOBS.items()
                if j.get("name") == name and j.get("kind") != "rescene"
                and j.get("state") in ("running", "solving", "finishing")]
        if not live:
            return None
        jid, j = live[-1]          # dict 保插入序，最后一个就是最近起的那个
        return {"id": jid, "state": j.get("state"), "step": j.get("step"),
                "solved": j.get("solved"), "total": j.get("total"),
                "last": (j["log"][-1] if j.get("log") else "")}


def failed_job_for(name):
    """
    这份卷子最近一次任务是不是**失败**收场的，是的话给出 (原因, 出错的阶段代号)。

    只认得出这个进程里起过的任务 —— JOBS 是进程内的 dict，重启就空了，
    命令行跑的也不在里面。所以「没报失败」不等于成功，那种情况一律显示
    「已停止」。这是有意的：宁可少报一个失败，也不能把不知道的说成知道。

    **原因之外还要给出是哪一步挂的。** JOBS 既不删条目也没有 TTL，一条几小时前
    在 ②b 挂掉的记录会一直躺在这里；只回一句话的话，调用方只能把它按在「当前
    阶段」那一格上 —— 于是 ⑤ 正在正常出动画时那格是红的，写着「②b 公式识别
    失败」。代号是 `stage_of` 的口径，调用方拿它比一下就知道说的是不是眼下这步。
    代号可能是 None（publish 前后的兜底异常，说不清属于哪一步），那种情况只报
    原因、不往任何一格上按。

    同样**不认单题重跑**（理由见 active_job_for）：重跑一道题没成功，是那道题的事，
    不该在试卷页顶上挂一条「上一次没跑完」的红横幅、再把某一格标志染红 ——
    整卷是好的，十几道题的动画都还在。
    """
    with LOCK:
        mine = [j for j in JOBS.values()
                if j.get("name") == name and j.get("kind") != "rescene"]
    if not mine or mine[-1].get("state") != "error":
        return None, None
    return (mine[-1].get("err") or "未说明原因"), mine[-1].get("err_code")


def failure_note(name, code, busy):
    """
    这条失败现在还算不算数。返回 (原因, 阶段代号)，不算数就是 (None, None)。

    两种情况一律不报 —— 库里的事实已经推翻了内存里那条旧记录：

    - **正在跑**：失败的是上一轮，这一轮还没有结论。`failed` 和 `busy` 可以
      同时为真，而列表页把「失败」排在「在跑」前面，于是一份正常推进的卷子
      会一直显示红色「失败」。
    - **已经跑完**（`stage_of` 判 done）：中间某步挂过、后来被补跑了。典型是
      网页那次 ⑦ 装配失败，维护者在终端补跑一次 assemble.py —— 补跑不进 JOBS，
      永远盖不掉那条 error，于是列表页红着「失败」、点进去六格全绿。

    清不掉这条记录的老路只有两条：重启后端，或者从网页重传同名卷。命令行怎么
    补跑都不行 —— 所以判据必须落到库上，不能只看 JOBS。
    """
    err, at = failed_job_for(name)
    if not err or busy or code == "done":
        return None, None
    return err, at


# 管线脚本名。判「在不在跑」用它，比「多久没落库」可靠 ——
# ④ 一题六分钟、⑤ 一道十几分钟，按时间阈值判必然误报「已停止」。
PIPE_RE = re.compile(
    r"pipeline/(solve|spec|scene|outline|kpmark|refans|pick|speccheck|assemble"
    r"|ingest|segment|mathvlm)\.py")
# 而且**跑它的得是个 python**。只按命令行里出没出现过脚本名来判的话，一条
# 恰好提到了 `pipeline/solve.py` 的 shell 命令（编辑器、别的工具、甚至一次
# 手敲的 grep）就会被算成「管线在跑」，整份卷子被标成解题中。
PY_EXE = re.compile(r"(?:^|/)[Pp]ython[\d.]*$")


def running_cmds():
    """
    在跑的管线进程的完整命令行。命令行起的、服务起的，都算。

    要的是整行而不是「有没有」：**每个步骤脚本的参数里都带着卷名**，
    所以一次就能判出「在跑的是哪几份卷子」。原来只判有没有进程，
    于是任何一份卷子在跑的时候，列表里**所有**卷子都被标成在跑 ——
    一份三天前就停了的卷子也会显示「解题中」。

    **用 `ps` 不用 `pgrep`。** pgrep 的 `-l` 在 BSD（macOS，本机部署）打的是整行
    命令行，在 procps（Linux，容器里）只打进程名 —— 同一份代码换台机器跑，
    卷名匹配会**静默**退化成「所有卷子都判成不在跑」，页面上全变「已停止」。
    `ps -A -o args=` 两边行为一致，筛选放到这边自己做。
    """
    try:
        r = subprocess.run(["ps", "-A", "-o", "pid=,args="],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    out = []
    for ln in (r.stdout or "").splitlines():
        # pid / 可执行文件 / 其余参数。脚本名要出现在**参数**里，可执行文件要是
        # 个 python —— 两条都卡住，才排得掉那些只是「提到」了脚本名的命令行
        parts = ln.split(None, 2)
        if len(parts) == 3 and PY_EXE.search(parts[1]) and PIPE_RE.search(parts[2]):
            out.append(ln)
    return out


def pipeline_running(name=None, cmds=None):
    """
    这份卷子有没有进程在跑。`name=None` 问的是「有没有任何管线在跑」。

    **卷名要卡边界，不能拿 `in` 去撞。** 原来是裸 `name in ln`，而重名卷子会被
    `free_name` 排成「X (2)」—— 于是查「X」必然命中「X (2)」那一行：一份三天前
    就停了的卷子被判成在跑，页面上画着呼吸点写「正在跑这一步」，而这恰恰是
    「已停止」这个状态本来要说清的事。同一个形状还有一处：卷名由文件名推出，
    那条正则只剥「题目版」不剥「答案版」，于是「X」是「X-答案版」的前缀。

    卷名在命令行里只有两种落位，后面跟的要么是行尾、要么是一个 `-x` 参数
    （见 run_pipeline 与 finish_paper 里那几条命令），按这个卡边界就够。
    卷名本身不会含空格 —— `safe_name` 把空白都换成了下划线，只有 `free_name`
    加的「 (2)」带空格，所以 `\\s+-` 这个边界不会被卷名自己撞上。
    """
    cmds = running_cmds() if cmds is None else cmds
    if name is None:
        return bool(cmds)
    # 裸卷名：solve / spec / scene / outline / pick / speccheck / assemble
    # work/<卷名>：ingest（-o 的值）/ segment / mathvlm
    pats = [re.compile(r"(?:^|\s)%s(?:\s+-|$)" % re.escape(s))
            for s in (name, os.path.join(WORK, name))]
    return any(p.search(ln) for ln in cmds for p in pats)


def stage_of(pg):
    """
    从库里的计数反推「现在在哪一步」，返回 (代号, 带编号的阶段名, 短状态词, 已完成, 总数)。

    没有谁上报状态 —— 这是**推断**出来的，所以按管线顺序找第一个没做完的环节。
    好处是命令行跑的、服务重启过的、别的进程跑的，一律看得见。

    每一步的分母都要用**那一步自己的口径**
    ------------------------------------
    这里原来一律拿题数或上一步的行数当分母，于是 ④c 挪到 ④ 前面之后，
    跑完的卷子在列表里永远显示「④ 写断言 6/16」—— ④ 只给 ④c 选中的 6 道题
    写断言，剩下 10 道**本来就不该有** spec，可是分母写的是 16。
    同样的坑还有两个：④b 自检的对象是 spec 不是题（而且 animatable=false 的
    spec 根本不过自检），⑤ 的分子必须是「试过几道」而不是「绿灯几道」——
    有一道怎么都过不了门禁的话，按绿灯数算就永远差一个，永远显示在跑。

    两个短状态词是有区别的：`stage` 带编号，给试卷页的进度带用（和上面那排
    ①②③ 标志对得上）；`short` 是给试卷库列表用的白话，那里没有编号可对照。
    """
    q, sol = pg["questions"], pg["solutions"]
    if sol < q:
        return "solve", "③ 解题", "解题中", sol, q
    if pg["labels"] < q:
        return "outline", "③b 目录", "生成目录", pg["labels"], q
    # ④c 的候选是「解出来的题」，不是全部题 —— 没解出来的它压根不判
    if pg["judged"] < sol:
        return "pick", "④c 选题", "动画选题", pg["judged"], sol
    if pg["specsWorth"] < pg["worth"]:
        return "spec", "④ 写断言", "写断言", pg["specsWorth"], pg["worth"]
    if pg["drafts"]:
        return "check", "④b 自检", "断言自检", pg["specs"] - pg["drafts"], pg["specs"]
    if pg["sceneTried"] < pg["ready"]:
        return "scene", "⑤ 生成场景", "生成动画", pg["sceneTried"], pg["ready"]
    if not pg["assembledFresh"]:
        return "assemble", "⑦ 装配成页", "装配成页", 0, 1
    return "done", "完成", "已完成", 1, 1


@app.get("/api/papers/{name}/progress")
def paper_progress(name: str, user=Depends(current_user)):
    """
    轻量进度端点，供页面每隔几秒轮询。

    只做计数查询，不拉题目正文 —— 整卷数据有一两兆，拿来轮询太重。
    页面发现计数变了才去重新拉整卷。
    """
    pg = store.progress(mine(name, user))
    if not pg:
        raise HTTPException(404, "没有这份试卷")
    code, label, short, cur, total = stage_of(pg)
    live = active_job_for(name)
    busy = bool(live) or pipeline_running(name) or pg["busy"]
    # 先算 busy 再问失败：正在跑的时候那条旧 error 不算数
    failed, failed_stage = failure_note(name, code, busy)
    return {**pg, "stage": label, "stageCode": code, "stageShort": short,
            "stageCur": cur, "stageTotal": total,
            "done": code == "done", "failed": failed, "failedStage": failed_stage,
            # 网页上传的任务还能给出更细的信息（正在解哪道题），命令行跑的没有
            "step": (live or {}).get("step"), "last": (live or {}).get("last"),
            "busy": busy}


@app.get("/api/jobs/{jid}")
def job(jid: str, user=Depends(current_user)):
    """
    任务日志。归属看**任务自己记的 owner**，不是去库里查这份卷子归谁 ——
    上传后的头几分钟（① 摄入、② 切分）卷子还没入库，那时候查库只会得到
    「没有这份试卷」，而这几分钟恰恰是上传页最需要日志的时候。
    """
    with LOCK:
        j = JOBS.get(jid)
        if not j:
            raise HTTPException(404, "未知任务")
        j = dict(j)
    if j.pop("owner_id", None) != user["id"]:
        raise HTTPException(404, "未知任务")
    return j


# ---------------------------------------------------------------- 试卷
@app.get("/api/papers")
def papers(user=Depends(current_user)):
    """
    列表也带进度。**返回试卷库不等于任务停了** —— 后台照跑，
    所以列表这一屏也要能看出哪份还在跑、跑到哪一步，否则一退出详情页就等于瞎了。
    """
    out = store.list_papers(user["id"])
    cmds = running_cmds()            # 一次就够，别对每份卷子都 fork 一个 pgrep
    for r in out:
        r["scenes"] = len(scenes_for(r["name"]))
        pg = store.progress(r["name"])
        if pg:
            code, label, short, cur, total = stage_of(pg)
            busy = (pg["busy"] or pipeline_running(r["name"], cmds)
                    or bool(active_job_for(r["name"])))
            failed, _at = failure_note(r["name"], code, busy)
            # 一行只放得下一个状态词。跑完是「已完成」，在跑是「解题中 15/16」，
            # 都不是就是「已停止」并说明停在哪 —— 光显示阶段名读不出它已经不动了
            r["progress"] = {"stage": label, "short": short, "code": code,
                             "cur": cur, "total": total,
                             "busy": busy,
                             "done": code == "done",
                             "failed": failed,
                             "solved": pg["solutions"], "questions": pg["questions"],
                             "elapsedSeconds": pg["elapsedSeconds"]}
    return out


@app.delete("/api/papers/{name}")
def delete_paper(name: str, user=Depends(current_user)):
    r = store.delete_papers([check_name(name)], user["id"])
    if not r["deleted"]:
        raise HTTPException(404, "没有这份试卷")
    return r


@app.post("/api/papers/delete")
def delete_papers(names: list[str] = Body(..., embed=True), user=Depends(current_user)):
    """
    批量删。一个事务删完，再清理没人引用的对象。

    不存在的卷名不算错 —— 前端可能拿的是过期列表，报 404 只会让它无从下手。
    如实回报删了哪些、哪些本来就不在。
    """
    if not names:
        raise HTTPException(400, "没有指定要删的试卷")
    if len(names) > 500:
        raise HTTPException(400, "一次最多删 500 份")
    # 归属过滤压在 SQL 里（见 store.delete_papers）：这是批量接口，
    # 在这儿逐个 check 漏掉一个的代价是删掉别人的东西
    return store.delete_papers([check_name(n) for n in names], user["id"])


def scenes_for(name):
    """
    找出绑定到这份卷子的场景。两个来源：

    1. **库里的 `scenes` 表** —— 阶段⑤ 产出的。绑定是 question_id，天然精确。
    2. **`runs/` 下带 bind.json 的** —— 早先手工做的那几个，没有库记录。

    绑定必须显式：题号不是全局唯一键。实测中福建卷的「斜面测μ」动画
    曾被裸题号匹配挂到重庆卷第12题（变压器实验）上——场景本身通过了全部门禁，
    只是绑错了题。所以第 2 条路要求 bind.json 里的 paper 与卷子名一致。

    第 1 条路不需要 bind.json：库里那一行就是绑定本身，而且 `passed` 是门禁
    的裁决。以前只扫文件系统，于是 ⑤ 产出的场景（目录名带 -genN 后缀、
    也不写 bind.json）在页面上根本不会出现 —— 明明已经绿灯了。
    """
    out = {}
    if not os.path.isdir(RUNS):
        return out

    for n, sid in store.paper_scenes(name).items():
        sd = os.path.join(RUNS, sid)
        fp, jp = os.path.join(sd, sid + ".figure.html"), os.path.join(sd, sid + ".js")
        if os.path.exists(fp) and os.path.exists(jp):
            out[n] = {"id": sid, "figure": open(fp, encoding="utf-8").read(), "js": jp}

    stems = {n: re.sub(r"\s", "", s) for n, s in store.paper_stems(name).items()}
    for d in sorted(os.listdir(RUNS)):
        sd = os.path.join(RUNS, d)
        bp, fp, jp = (os.path.join(sd, "bind.json"),
                      os.path.join(sd, d + ".figure.html"),
                      os.path.join(sd, d + ".js"))
        if not all(os.path.exists(p) for p in (bp, fp, jp)):
            continue
        b = json.load(open(bp, encoding="utf-8"))
        if b.get("paper") != name:
            continue
        n = int(b.get("n", 0))
        ex = re.sub(r"\s", "", b.get("stem_excerpt", ""))[:16]
        if ex and ex not in stems.get(n, ""):
            continue                      # 题干对不上：卷子改版了，宁可不挂
        out.setdefault(n, {"id": d, "figure": open(fp, encoding="utf-8").read(), "js": jp})
    return out


_PUNCT = re.compile(r"[\s。，、；：．.,;:!？?（）()【】\[\]]+")


def answers_agree(a, b):
    """
    卷子上的标准答案与 ③ 的 AI 答案是不是一回事。

    **任一边为空回 None，不是 False。** 「比不了」和「对不上」在页面上是
    两句完全不同的话：前者是缺数据，后者是有一方错了。压成 False 等于
    在没有任何证据的情况下指认 AI 解错了。

    只做归一化字符串比与选择题的集合比 —— 本期不引 sympy（它解析带单位
    带下标的 LaTeX 会**静默**判错，正是这个项目最怕的错）。形式不同就报
    不同，让人去看，比静默判等安全。
    """
    def norm(s):
        if not s:
            return ""
        s = unicodedata.normalize("NFKC", str(s)).strip().upper()
        return _PUNCT.sub("", s)

    na, nb = norm(a), norm(b)
    if not na or not nb:
        return None
    if na == nb:
        return True
    # 选择题：两边都只由 A-D 组成才按集合比。「AB两点」和「BA两点」带了别的字，
    # 不能按集合算成同一个答案
    if re.fullmatch(r"[A-D]+", na) and re.fullmatch(r"[A-D]+", nb):
        return set(na) == set(nb)
    return False


@app.get("/api/papers/{name}")
def paper(name: str, user=Depends(current_user)):
    q = store.get_paper(mine(name, user))
    if not q:
        raise HTTPException(404, "没有这份试卷")
    sc = scenes_for(name)
    sols = store.paper_solutions(name)
    # 插图的原始尺寸只在 doc.json 里，而 doc.json 是构建产物、不入库
    # （117 KB/卷 的逐字符坐标，只有管线自己读）。取不到就按满宽渲染。
    geo = {}
    dj = os.path.join(WORK, name, "doc.json")
    if os.path.exists(dj):
        for p in json.load(open(dj, encoding="utf-8"))["pages"]:
            for im in p["images"]:
                if im.get("w"):
                    geo[im["file"]] = {"w": im["w"], "h": im["h"]}

    def fig(f):
        # 宽度占比：原卷里一张 75pt 宽的竖长图不该在页面上铺满
        g = geo.get(f)
        return {"url": "/api/papers/%s/%s" % (name, f),
                "widthPct": max(18, min(100, round(g["w"] / 476 * 100))) if g else 100}

    cat = kp.load()
    qs = []
    for x in q["questions"]:
        s = sc.get(x["n"])
        sol = sols.get(x["n"])
        qs.append({
            "n": x["n"], "type": x["type"], "points": x["points"],
            "section": x["section"], "pages": x["pages"],
            "stem": x["stem"],
            # 视觉模型转写的题干（含 $...$ 行内公式）；中文重合度不够时后端不会给
            # ③b 给的短标题。缺了就是 null —— 目录那一行只显示题号，不编一个
            "label": x.get("label"),
            "stemLatex": x.get("stem_latex"),
            # 视觉转写与原抽取的中文重合度偏低时给出的提示；页面上要显式标出来
            "stemLowConf": x.get("stem_low_conf"),
            "stemRejected": x.get("stem_vlm_rejected"),
            "stemImage": ("/api/papers/%s/%s" % (name, x["stem_image"])
                          if x.get("stem_image") else None),
            "stemMath": x.get("stem_math", []),
            # 表格：二维结构，由视觉模型转写；原图一并给出以便核对。
            # 跨页表在这里拼成一张——下半张没有表头，单独给前端毫无意义。
            "tables": [{"id": t["id"], "caption": t.get("caption", ""),
                        "rows": t.get("rows", []),
                        # 跨页表有两张原图，逐张给出
                        "images": ["/api/papers/%s/%s" % (name, i)
                                   for i in t.get("images", [])]}
                       for t in segment.merged_tables(x.get("tables", []))
                       if t.get("rows")],
            "options": [{"key": o["key"], "text": o["text"],
                         "math": o.get("math", []),
                         # 阶段②b 视觉模型识别的 LaTeX；有它就优先用它渲染
                         "latex": o.get("latex"),
                         "figure": fig(o["figure"])["url"] if o.get("figure") else None}
                        for o in x["options"]],
            "figures": [fig(f) for f in x["figures"]],
            # 图在正文中的位置：占位符 〔图N〕 → 图片 URL
            "figMarks": [{"id": f["id"], **fig(f["file"])}
                         for f in x.get("fig_marks", [])],
            "textQuality": x.get("text_quality", "ok"),
            "qualityReason": x.get("quality_reason", ""),
            # 选项区原卷截图：兜底 + 「对照原卷」
            "optionImage": ("/api/papers/%s/%s" % (name, x["option_image"])
                            if x.get("option_image") else None),
            # ③c 挂的知识点。带上名字和章 —— 前端不该为了显示一个标签再去
            # 拉一份词表，而且词表是后端的种子数据。词表里查不到的 code 退回
            # 显示 code 本身，不吞掉：那说明词表被改过而库里还留着旧标签
            "kps": [{"code": k["code"], "why": k.get("why", ""),
                     "name": cat[k["code"]]["name"] if k["code"] in cat else k["code"],
                     "chapter": cat[k["code"]]["chapter"] if k["code"] in cat else ""}
                    for k in (x.get("kps") or [])],
            # ②d 从卷子里抽的标准答案。src=None 表示还没跑过 ②d，
            # src='none' 表示跑过但这份卷子里没有答案 —— 两件事
            "refAnswer": x.get("ref_answer"),
            "refAnswerSrc": x.get("ref_answer_src"),
            # 白捡的红绿灯：卷子答案与 ③ 的 AI 答案比一次。不一致意味着
            # 要么 AI 解错了、要么那份答案有误，两种都必须让人看见。
            # None = 比不了（有一边没有），**不是**对不上
            "refAnswerAgrees": answers_agree(
                x.get("ref_answer"), sol and sol.get("short_answer")),
            "sceneId": s["id"] if s else None,
            "sceneFigure": s["figure"] if s else None,
            # 阶段③ 的解题结果。**必须连 confidence 和 assumptions 一起给**：
            # 这段讲解是模型生成的，assumptions 是它自己补的、题面没给的前提。
            # 只给结论不给这两样，等于把一个未经检验的答案伪装成权威解法。
            "solution": sol and {
                "answer": sol["answer"],
                # ③b 压出来的一行版，目录和速览表用。完整版仍在 answer 里，谁也不替谁
                "shortAnswer": sol["short_answer"],
                "steps": sol["steps"],
                "assumptions": sol["assumptions"],
                "confidence": sol["confidence"],
                "model": sol["model"],
                # 阶段④ 的状态：有没有断言、过没过人审。没有断言的讲解没被任何东西检验过
                "nInvariants": sol["n_invariants"],
                "specStatus": sol["spec_status"],
                "animatable": sol["animatable"],
                "whyNot": sol["why_not"] if sol["animatable"] is False else None,
                # 阶段④c：做得了，但值不值得花几十分钟做。和 animatable 是两件事，
                # 页面上要能分别答出「做不了」和「没必要」
                "worth": sol["worth"],
                "worthWhy": sol["worth_why"],
                # 阶段⑤：门禁的裁决，不是实现方自称的
                "scenePassed": sol["scene_passed"],
                "sceneRounds": sol["scene_rounds"],
            },
        })
    # ⑦ 的状态从库里读，不再硬编码 true —— 网页上传那条链以前根本没跑到 ⑦，
    # 标志却一直亮着绿灯。三种「不算数」都要分开说清楚：没跑过、产物被删了、
    # 产物比库里的数据旧（解完题不重装，手上那份 out.html 还是零解法的版本）。
    asm = store.assembled(name)
    asm_exists = bool(asm["path"]) and os.path.exists(asm["path"])
    if not asm["at"]:
        asm_note = "还没跑过 ⑦ 装配"
    elif not asm_exists:
        asm_note = "库里记着装过，但 out.html 已经不在磁盘上了"
    elif not asm["fresh"]:
        asm_note = "out.html 比库里的数据旧，重跑 ⑦ 才能把新的解法装进去"
    else:
        asm_note = "out.html 已生成，且不比库里的数据旧"
    return {"name": name, "sections": q.get("sections") or [],
            "warnings": q.get("warnings") or [], "questions": qs,
            "stages": {"ingest": True, "segment": True,
                       "solve": len(sols) > 0,
                       "spec": any(v["spec_status"] for v in sols.values()),
                       "scene": len(sc) > 0,
                       "assemble": asm_exists and asm["fresh"]},
            # 灭着的标志要能说出为什么灭 —— 光是灰掉，人无从知道是没跑还是跑旧了
            "stageNotes": {"assemble": asm_note},
            # 这份卷子此刻在不在跑。有的话试卷页顶部画进度带
            "job": active_job_for(name),
            # 覆盖率要如实报：只解了 6/359 题时页面不能给人「已经做完」的印象
            "coverage": {"solved": len(sols), "total": len(qs)}}


@app.get("/api/papers/{name}/scene.js")
def scene_js(name: str, user=Depends(current_user)):
    mine(name, user)
    # 只给场景工厂，不带 harness/_runtime.js —— 那份运行时是给静态页写的，
    # 挂在 DOMContentLoaded 上，SPA 里 figure 是后渲染的，时机对不上。
    # 帧循环 / 播放暂停 / 离屏暂停由前端的 SceneMount 组件实现。
    parts = ["window.Scenes = window.Scenes || {};"]
    for n, s in sorted(scenes_for(name).items()):
        parts.append(open(s["js"], encoding="utf-8").read())
    return Response("\n".join(parts), media_type="application/javascript")


def scene_runs(name, cmds=None):
    """
    这份卷子上正在跑的场景任务：返回 (单题重跑的题号集合, 有没有整卷任务)。

    两者的闸门口径不同，所以必须分开数：**同一道题不许并跑，但两道不同的题
    各自重跑是允许的**。只用 `pipeline_running(name)` 判的话，重跑第 7 题会被
    正在重跑的第 5 题挡下来 —— 那不是想要的。

    判据是命令行里带不带 `--only`：单题重跑带，整卷不带（见 finish_paper）。
    读 `ps` 而不是只读 JOBS，是因为命令行起的任务也要算 —— JOBS 只认得出
    这个进程里起过的。
    """
    cmds = running_cmds() if cmds is None else cmds
    only, whole = set(), False
    pats = [re.compile(r"(?:^|\s)%s(?:\s+-|$)" % re.escape(s))
            for s in (name, os.path.join(WORK, name))]
    for ln in cmds:
        if not any(p.search(ln) for p in pats):
            continue
        m = re.search(r"--only\s+(\d[\d,]*)", ln)
        if m and "scene.py" in ln:
            only |= {int(x) for x in m.group(1).split(",") if x.strip()}
        else:
            whole = True
    return only, whole


def run_rescene(jid, name, n):
    """
    重跑一道题的 ⑤。

    **成功与否要去库里看，不能信退出码** —— `scene.py` 跑满轮数没过门禁时
    照样 `return 0`（它是整卷工具，一道题没做成不算整体失败）。所以拿库里
    `scenes` 那行的 scene_id 前后比一次：换了才是真做出了新动画。

    这也正好说得出那句最要紧的话：**没换成的时候，你原来那个动画还在**
    —— `store.put_scene` 的 WHERE 保证了失败不会覆盖成功。
    """
    before = store.paper_scenes(name).get(n)
    run_step(jid, "⑤ 重跑第%d题（最多 %d 轮）" % (n, RESCENE_ROUNDS),
             step_path("scene.py") + [name, "--only", str(n),
                                      "--rounds", str(RESCENE_ROUNDS)],
             timeout=RESCENE_TIMEOUT)
    after = store.paper_scenes(name).get(n)
    swapped = bool(after) and after != before
    # **job_log 必须在锁外面**：它自己要拿 LOCK，而 threading.Lock 不可重入 ——
    # 在 `with LOCK:` 里面调它就是自己锁死自己，而且锁再也放不掉，
    # 之后每个碰 JOBS 的请求（含所有轮询）全部挂起。run_pipeline 里也是这个写法。
    with LOCK:
        if swapped:
            JOBS[jid].update(state="done", step="完成", scene=after)
        else:
            # 措辞要能覆盖两种收场：跑满轮数没过门禁、以及中途被打断（超时、
            # 后端重启、进程被杀）。写死「跑满 N 轮」的话，第 1 轮就被掐掉时
            # 这句话是假的 —— 具体到底怎么回事，日志里有
            JOBS[jid].update(state="error", err_code="scene",
                             err="第%d题这次没做出新动画（最多跑 %d 轮）。"
                                 "原来那个动画没动，页面上照常能看" % (n, RESCENE_ROUNDS))
    job_log(jid, ("✓ 第%d题重跑出新动画：%s（原来是 %s）" % (n, after, before))
            if swapped else
            ("✗ 第%d题没做出新动画。旧动画 %s 保持不变" % (n, before)))



@app.post("/api/papers/{name}/questions/{n}/rescene")
def rescene(name: str, n: int, user=Depends(current_user)):
    """
    重跑某一道题的动画。**只做重跑，不做补做** —— 这道题必须已经有动画。

    没动画的题（④c 判不值得、④ 写不出断言、⑤ 跑失败）不从这里走：那几种
    情况各有各的成因，一个按钮糊上去只会让人以为点了就能有。
    """
    mine(name, user)
    if n not in store.paper_scenes(name):
        raise HTTPException(400, "第%d题没有通过门禁的动画，这个入口只做重跑" % n)

    # 闸门按从便宜到贵排：先查进程内的 JOBS，再去扫 ps
    with LOCK:
        busy = any(j.get("kind") == "rescene" and j.get("name") == name
                   and j.get("qn") == n and j.get("state") == "running"
                   for j in JOBS.values())
    if busy:
        raise HTTPException(409, "第%d题正在重跑，等它跑完" % n)
    only, whole = scene_runs(name)
    if n in only:
        raise HTTPException(409, "第%d题正在重跑（命令行起的），等它跑完" % n)
    # 整卷管线在跑时一律拦：`pipeline_running` 判不出它跑到哪一步、正在做第几题，
    # 而整卷 ⑤ 恰好在做这道题的话，两个沙箱做同一道，烧双份额度还要抢 put_scene
    if whole or active_job_for(name):
        raise HTTPException(409, "这份卷子整条管线在跑，等它跑完再重跑单题")

    jid = uuid.uuid4().hex[:12]
    with LOCK:
        JOBS[jid] = {"state": "running", "step": "排队中", "kind": "rescene",
                     "name": name, "qn": n, "owner_id": user["id"],
                     "log": ["重跑第%d题的动画（⑤），最多 %d 轮" % (n, RESCENE_ROUNDS)]}
    threading.Thread(target=run_rescene, args=(jid, name, n), daemon=True).start()
    return {"job": jid, "question": n}


def send(name, row):
    """
    资产一律经本服务代理，不把对象存储地址给出去。

    代价是一次转发，换来的是**存储后端对前端完全透明** —— 从本地目录切到
    MinIO、以后再切到别处，前端的 URL 一个都不用改。
    资产是内容寻址的（key 是 sha256），所以可以放心让浏览器长期缓存。

    是 private 不是 public。这个函数挂在 current_user + mine() 后面，返回的是
    **按账号过滤过的**字节，而 URL 里只有卷名和文件名、没有那个 sha256 ——
    换句话说同一条 URL 对不同的人应该给出不同的答案（或者 404）。声明成 public
    等于允许中间缓存把它存下来，而缓存命中之后就不再回源、也就不再校验 cookie，
    任何人猜到卷名就能取走。本地跑没有中间缓存所以看不出来，一挂 CDN 就成立。
    private 只挡共享缓存，浏览器自己那份长缓存照旧。
    """
    if not row:
        raise HTTPException(404, "没有这份资产")
    data = store.read_asset(row, name)
    if data is None:
        raise HTTPException(404, "资产记录在，文件不见了")
    return Response(data, media_type=row["content_type"],
                    headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.get("/api/papers/{name}/page/{n}")
def page_render(name: str, n: int, user=Depends(current_user)):
    """整页渲染图。用来人工核对切分准不准——光看切出来的文本判断不了边界对没对。"""
    return send(name, store.find_page(mine(name, user), n))


@app.get("/api/papers/{name}/mathimg/{fn}")
def math_image(name: str, fn: str, user=Depends(current_user)):
    """选项区与表格的原卷截图。模型也会错，错了必须能被看见。"""
    if "/" in fn or ".." in fn:
        raise HTTPException(400, "非法路径")
    return send(name, store.find_asset(mine(name, user), "mathimg/" + fn))


@app.get("/api/papers/{name}/img/{fn}")
def image(name: str, fn: str, user=Depends(current_user)):
    if "/" in fn or ".." in fn:
        raise HTTPException(400, "非法路径")
    return send(name, store.find_asset(mine(name, user), "img/" + fn))


# ---------------------------------------------------------------- 前端静态
DIST = os.path.join(ROOT, "web", "dist")
if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
else:
    @app.get("/")
    def dev_hint():
        return PlainTextResponse(
            "前端还没构建。开发时跑 `cd web && npm run dev`（5173 端口），\n"
            "或 `npm run build` 之后由本服务在 / 直接托管。")
