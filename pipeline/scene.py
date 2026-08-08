#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scene.py —— 阶段⑤ 生成场景

    python pipeline/scene.py <卷名> --only 16 [--rounds 8] [--model claude-sonnet-5]

这一步和前面几步性质完全不同：③④ 是一次问答，⑤ 是**带反馈的循环**。
沙箱 agent 要解参数、写 SVG、写 JS、跑门禁、读报错、再改，直到绿灯或轮次耗尽。

红线怎么保证
------------
`README` 那句「写代码的那一方不能写断言」不是靠提示词嘱咐的：

  · spec 由阶段④（DeepSeek）写，写进 `specs/<id>.spec.json`
  · 门禁 `harness/verify.py` 只读
  · 沙箱 agent 在 `runs/<id>/` 里干活，**每轮结束都会重新校验
    spec 与 harness 的 sha256**。动过就算这一轮作废。

自己给自己出卷子的验证等于没验证。所以不是「相信它不改」，是**改了会被发现**。

绿灯不等于对
------------
门禁保证的是「实现与 spec 一致」。spec 本身写错了，门禁照样全绿 ——
实测福建卷第16题，阶段③ 一次给 `√7·v₁`、一次给 `(1+√3)v₁`，两次都自称 high。
所以进这一步之前 spec 必须过人审（`specs.status`），这里只做实现层的把关。
"""
import argparse, base64, hashlib, json, os, re, signal, subprocess, sys, threading, time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store
import scenegen        # 物理与读数面板由它从 spec 生成，agent 不再写
import cliask       # claude 可执行文件的定位、以及子进程要带的代理，只写一份
import clishim      # 让 CLI 走中转的 key 而不是订阅
import arkshim      # 让 CLI 被豆包驱动（Anthropic↔OpenAI 协议翻译）

for _l in (open(os.path.join(ROOT, ".env"), encoding="utf-8")
           if os.path.exists(os.path.join(ROOT, ".env")) else []):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

CLI = cliask.CLI        # 定位规则见 cliask.find_cli()，两处别再各写一份
SPECS = os.path.join(ROOT, "specs")
RUNS = os.path.join(ROOT, "runs")
GUARD = os.path.join(ROOT, ".readonly.sha256")

# 见 build() 里的说明：sid 分配、spec 落盘、篡改快照三件事必须串行。
#
# 线程锁只管得住一个进程。而**跨进程也会撞** —— 想同时用两条 backend 跑同一道题
# 做对照时，就是两个 scene.py 进程，各有各的 threading.Lock，
# 会同时分配到同一个 `qN-gen2`，后写的把先写的 spec 覆盖掉，
# 而两边都以为自己在做自己的题。所以再叠一层文件锁。
SETUP_LOCK = threading.Lock()
SETUP_LOCKFILE = os.path.join(ROOT, "runs", ".setup.lock")


class _CrossProcLock:
    """线程锁 + 文件锁。文件锁拿不到就退回只用线程锁，不让它成为新的失败点。"""

    def __enter__(self):
        SETUP_LOCK.acquire()
        self.fh = None
        try:
            import fcntl
            os.makedirs(os.path.dirname(SETUP_LOCKFILE), exist_ok=True)
            self.fh = open(SETUP_LOCKFILE, "w")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except Exception:
            if self.fh:
                self.fh.close()
            self.fh = None
        return self

    def __exit__(self, *a):
        if self.fh:
            try:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            finally:
                self.fh.close()
        SETUP_LOCK.release()
        return False


SETUP = _CrossProcLock()

# ── 三条执行路径，改 .env 里的 EXAM_SCENE_BACKEND 就能切 ──────────────────
#
#   subscription  claude CLI 走本机已登录的订阅。不花 API 的钱，但受订阅额度限制
#   relay         claude CLI 走 302 中转的 key（经 clishim 摘掉中转不认的字段）
#   ark           火山方舟直连（豆包）。**不是 agent** —— 它不会自己跑门禁，
#                 写盘、跑 verify.py、把失败报告喂回去这一圈由这里代劳
#   ark-cli       豆包**驱动 claude CLI**：经 arkshim 把 Anthropic 协议翻译成
#                 OpenAI 协议。是完整的 agent（自己写文件、跑门禁、读报错），
#                 只是脑子换成了豆包。前提是豆包支持 function calling —— 实测支持
#
# 前两条的差别只有环境变量：claude CLI 认 ANTHROPIC_API_KEY/BASE_URL，
# 给了就走中转，不给就退回订阅。以前这是**隐式**的（看 CLAUDE_API_KEY 在不在），
# 跑完都不知道钱记在哪边，所以改成显式声明。
BACKENDS = ("subscription", "relay", "ark", "ark-cli")
BACKEND = os.environ.get("EXAM_SCENE_BACKEND", "auto")

ARK_BASE = os.environ.get("EXAM_SCENE_ARK_BASE",
                          "https://ark.cn-beijing.volces.com/api/v3")
# 单独一个 key：.env 里原有的 ARK_API_KEY 属于另一个账号，实测没开通
# doubao-seed-evolving（返回 ModelNotOpen）。两个别混用。
ARK_KEY = os.environ.get("EXAM_SCENE_ARK_KEY") or os.environ.get("ARK_API_KEY", "")

DEFAULT_MODEL = {"subscription": "claude-sonnet-5", "relay": "claude-sonnet-5",
                 "ark": "doubao-seed-evolving", "ark-cli": "doubao-seed-evolving"}


def resolve_backend(name):
    """auto：有中转 key 就走中转，没有就退回订阅 —— 和改造前的行为一致。"""
    if name == "auto":
        return "relay" if os.environ.get("CLAUDE_API_KEY") else "subscription"
    if name not in BACKENDS:
        raise SystemExit("EXAM_SCENE_BACKEND 只能是 %s，收到 %r" % ("/".join(BACKENDS), name))
    return name


MODEL = os.environ.get("EXAM_SCENE_MODEL") or DEFAULT_MODEL[resolve_backend(BACKEND)]

BRIEF_CODEGEN = """你要为一道物理题画一个动画场景。**下面是全部信息，不用去翻仓库。**

物理不用你算：spec 的 `reference` 已经预计算成数值表，`probe(u, caseId)`、
读数面板、figcaption 全部生成好了。**你只画图。**

═════════ 你只写这两个文件（就在当前目录，别去别处）═════════

【1】{id}.figure.html —— 画物理场景

<figure data-scene="{id}"><svg viewBox="0 0 560 H" role="img" aria-label="…">
  …你的图元，每个要动的元素都要有 id="{id}-xxx"…
  <g id="{id}-panel"></g>          ← 必须留着，读数面板由代码注入
</svg>
<figcaption>随便写</figcaption></figure>

· 所有 id 必须以 `{id}-` 开头，否则静态门禁不过
· **{rect} 这块矩形是禁区**，别画进去（读数面板占着）
· figcaption 会被代码覆盖，你写什么都行
· 可用样式类：sk(主线) sh(辅线) sa(蓝) sr(红) sc(虚线) fk/fa/fr(填充)
  u(中文标签) n(等宽数字)；箭头用 marker-end="url(#ak)"（或 aa/ar/ac）
· **文字不许压文字**：中文字宽 13.1px、ASCII 6.0px、行高 14.9px，按这个留间距

【2】{id}.draw.js —— 只准定义这四样，别的一律不许

var PERIOD = 4.0;                   // 一次完整过程播几秒，不写默认 6
var READOUTS = {readouts};          // 面板显示哪些量，须是 probe_keys 的子集
function drawFrame(ps, u, svg) {{ }}  // ps = {{情形id: {{量名: 数值}}}}
function drawReset(svg) {{ }}         // 清掉轨迹之类的累积状态

**不许定义 probe / probeAll / updatePanel / render / T / N / CASES** ——
那些是生成好的，你定义了会把它们覆盖掉，拼装时当场失败。

═════════ 一份完整的例子（照着写）═════════

figure.html：
<figure data-scene="demo"><svg viewBox="0 0 560 280" role="img" aria-label="金属棒进磁场">
  <line class="sk" x1="40" y1="100" x2="520" y2="100"/>
  <line class="sk" x1="40" y1="180" x2="520" y2="180"/>
  <line id="demo-rod" class="sr" x1="100" y1="95" x2="100" y2="185" stroke-width="4"/>
  <text id="demo-lab" class="u" x="100" y="85" text-anchor="middle">a</text>
  <line id="demo-v" class="sa" x1="110" y1="140" x2="150" y2="140" marker-end="url(#aa)"/>
  <g id="demo-panel"></g>
</svg>
<figcaption>占位</figcaption></figure>

draw.js：
var PERIOD = 4.0;
var READOUTS = ["v", "x"];
function drawFrame(ps, u, svg) {{
  var p = ps[CASES[0]];                       // 单情形取第一个
  var sx = 100 + p.x * 390;                   // 物理量 → 屏幕坐标
  var rod = svg.querySelector('#demo-rod');
  rod.setAttribute('x1', sx); rod.setAttribute('x2', sx);
  svg.querySelector('#demo-lab').setAttribute('x', sx);
  var v = svg.querySelector('#demo-v');
  v.setAttribute('x1', sx + 10); v.setAttribute('x2', sx + 10 + p.v * 40);
}}
function drawReset(svg) {{ drawFrame(probeAll(0), 0, svg); }}

═════════ 验收 ═════════

改完跑**这一条命令**（拼装和门禁在一起，不要分开跑）：

    {py} {check} {id}

末行是 `VERDICT: PASS` 或 `FAIL`。FAIL 就按报错改，改完再跑，直到 PASS。

**别去读别的场景的文件、别读 harness/ 或 pipeline/ 的源码** —— 上面已经是全部
你需要的信息了，翻仓库只会浪费轮次。

═════════ 题目规格 ═════════

可用的物理量：{keys}

spec 在 {spec}（**只读**）。里面 `scene_requirements` 那一节说了画面上要有什么，
`probe_key_meaning` 说了每个量是什么意思 —— **只需要读这一个文件**。

铁律：不许改 spec、不许改 harness/ 下任何文件，它们的 sha256 会被校验。
不许让 probe 返回断言期望的常数来绕过检查。
"""


BRIEF = """你要为一道物理题实现一个可验证的动画场景。

工作目录就是当前目录。**只允许在这里写文件**，产出两个：

    {id}.figure.html
    {id}.js

规范见 {contract}（必读，硬性要求都在里面）。
题目规格见 {spec}（**只读，不得修改**）。

做法
----
1. 先读 CONTRACT.md 和 spec。
2. spec 的 `physics.free_parameters` 列出的参数题面没给，你要自己解出一组
   同时满足全部 `given_facts` 的自洽值。**建议先写个小脚本用数值方法求解**
   （可以在本目录建 solve.py 之类的临时文件），别靠心算凑。
3. 实现 figure.html 与 js。`probe(u, caseId)` 是验收核心：它必须是纯函数，
   返回 spec `probe_keys` 里的全部量，单位以 spec 的 `units` 为准。
4. 自己跑门禁：

       {py} {verify} {id}

   末行是 `VERDICT: PASS` 或 `FAIL`。**FAIL 就按报错改，改完再跑，直到 PASS。**
   报错里 L4 会打印「实测」值，那是定位参数不自洽的关键线索。

铁律
----
- **不许修改 {spec}、不许修改 harness/ 下任何文件。** 它们的 sha256 会被校验，
  动过这一轮直接作废。断言不合你的实现时，要改的是实现，不是断言。
- 不许把断言绕过去（例如让 probe 直接返回断言期望的常数而不真算物理）。
  probe 与 step 必须是同一套物理，L3.5 会检查画面确实动过、元素确实在画布内。
- 拿不到自洽参数时，宁可如实停下并说明卡在哪，也不要交一个凑数的实现。

最后回一行 `DONE <PASS|FAIL>`，后面跟一句话说明。
"""

# 方舟那条路要另一份说明书：它不是 agent，读不了文件也跑不了门禁，
# 所以契约和 spec 得直接塞进 prompt，产出也得用一个能可靠切开的分隔格式。
ARK_BRIEF = """你要为一道物理题实现一个可验证的动画场景，产出两个文件的完整内容。

【场景 id】{id}

【题目规格 spec（只读输入，里面的断言就是验收标准）】
{spec}

【场景契约，逐条都是硬性要求】
{contract}

要点
----
- spec 的 `disclosures[].must_contain` 里的每一句，**必须一字不差地出现在 figure 的
  可见文本里**（门禁按字符串逐条匹配，标点和括号都要一样）。这是最容易漏的一条。
- `probe(u, caseId)` 是验收核心：纯函数，返回 spec `probe_keys` 里的**全部**键，
  单位以 spec 的 `units` 为准，不是屏幕像素。
- spec 的 `physics.free_parameters` 里的参数题面没给，你要解出一组同时满足
  全部 `given_facts` 的自洽值。**要真解，不要凑**。
- **不许让 probe 直接返回断言期望的常数而不真算物理。** step 与 probe 必须是
  同一套物理，门禁会检查画面确实动过、元素确实在画布内。

只输出两个文件，用下面的格式，前后不要有任何解释：

===FILE {id}.figure.html===
（文件内容）
===FILE {id}.js===
（文件内容）
"""

ARK_RETRY = """上一轮门禁没过。下面是完整报告，按里面的层级和 id 逐条修。

**不要修改 spec，改你自己的实现。** L4 打印的「实测」值是定位参数不自洽的关键线索。

{report}

重新输出两个文件的完整内容，格式同上（===FILE …=== 分隔），不要只给补丁。
"""


# 一轮的上限。压轴题写场景实测 15 分钟，给到 40 分钟已很宽裕；
# 再长就是卡住了而不是在算 —— 实测卡死时它跑了 2.5 小时、工作目录一个文件都没有。
ROUND_TIMEOUT = int(os.environ.get("EXAM_SCENE_ROUND_TIMEOUT", "2400"))


def run_agent(msg, workdir, model, timeout, backend="relay"):
    """
    起沙箱 agent，超时要杀**整个进程组**。

    `subprocess.run(timeout=…)` 只杀直接子进程，而 claude CLI 会 fork ——
    孙进程活下来继续占着 API 配额和内存，实测超时后又跑了一个半小时。
    所以用 start_new_session 建独立进程组，超时时 killpg 整组端掉。
    """
    if backend == "ark-cli":
        shim = arkshim.ensure()
        if not shim:
            raise RuntimeError("backend=ark-cli 但方舟垫片起不来（缺 EXAM_SCENE_ARK_KEY？）")
        env = cliask.cli_env(dict(os.environ, **shim), drop_anthropic=False)
    elif backend == "relay":
        # 走中转的 key。直连中转会 403（它的参数白名单里没有 context_management
        # 和 metadata），clishim 转发时把这两个字段摘掉。
        shim = clishim.ensure()
        if not shim:
            raise RuntimeError("backend=relay 但拿不到中转环境（缺 CLAUDE_API_KEY "
                               "或垫片起不来）。要用订阅请显式设 "
                               "EXAM_SCENE_BACKEND=subscription")
        env = cliask.cli_env(dict(os.environ, **shim), drop_anthropic=False)
    else:
        # 订阅：把继承来的 ANTHROPIC_* 全部摘掉，否则 CLI 会去连中转而不是订阅。
        # 显式声明用订阅，就不能因为环境里恰好有个 key 就偷偷改道。
        env = cliask.cli_env()
    p = subprocess.Popen(
        [CLI, "-p", "--model", model,
         "--allowed-tools", "Read,Write,Edit,Bash,Glob,Grep"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=workdir, text=True, start_new_session=True, env=env)
    try:
        out, _err = p.communicate(msg, timeout=timeout)
        return out
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            p.kill()
        p.communicate()
        raise


def ark_call(msgs, model, timeout, prev_id=None):
    """
    方舟 /responses 一次调用，返回 (正文, 用量, 本次响应 id)。

    续话用 `previous_response_id` 而不是把历史整个重发，两个原因：
    重发要把契约 + spec + 上一轮的两个文件（约一万 token）再塞一遍；
    而且把上一轮的回复当 `assistant` 角色发回去时，`output_text` 这个类型
    会被要求额外的 `input.status` 字段 —— 实测直接 400 MissingParameter。
    """
    payload = {"model": model, "input": msgs}
    if prev_id:
        payload["previous_response_id"] = prev_id
    r = urllib.request.Request(ARK_BASE + "/responses", json.dumps(payload).encode(),
                               {"Authorization": "Bearer " + ARK_KEY,
                                "Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(r, timeout=timeout).read())
    txt = "".join(c.get("text", "") for it in d.get("output", [])
                  if it.get("type") == "message" for c in it.get("content", []))
    return txt, (d.get("usage") or {}), d.get("id")


def ark_write(txt, workdir, sid, codegen=False):
    """
    把模型输出的 `===FILE …===` 段落落盘，返回写了哪些文件。

    **只接受两个文件名**，别的一律丢弃。方舟这条路上模型碰不到文件系统，
    写盘的是我们 —— 所以「不许改 spec 和 harness」在这里不是靠嘱咐，
    也不是靠事后查哈希，而是**结构上就做不到**。这是它相对沙箱的一个真优势。
    """
    allow = ({sid + ".figure.html", sid + ".draw.js"} if codegen
             else {sid + ".figure.html", sid + ".js"})
    wrote = []
    for name, body in re.findall(r"===FILE\s+(\S+?)===\n(.*?)(?=\n===FILE|\Z)", txt, re.S):
        name = os.path.basename(name.strip())
        if name not in allow:
            continue
        body = re.sub(r"^\s*```[a-zA-Z]*\n", "", body.strip())
        body = re.sub(r"\n?```\s*$", "", body).strip()
        open(os.path.join(workdir, name), "w", encoding="utf-8").write(body + "\n")
        wrote.append(name)
    return wrote


def ark_build(sid, spec, workdir, rounds, model, images, log, codegen=False):
    """
    方舟直连的实现循环。和沙箱那条路**判据完全一样**：绿灯只由 verify.py 的末行决定。

    差别在于谁动手：沙箱自己读契约、自己写文件、自己跑门禁；这里模型只吐文本，
    契约和 spec 由我们塞进 prompt，文件由我们写，门禁由我们跑，失败报告由我们喂回去。
    所以它多花的是我们的编排，省下的是每轮重起进程、重读上下文的开销。
    """
    if not ARK_KEY:
        raise RuntimeError("backend=ark 但没有 EXAM_SCENE_ARK_KEY（或 ARK_API_KEY）")
    contract = open(os.path.join(ROOT, "harness", "CONTRACT.md"), encoding="utf-8").read()
    first = [{"type": "input_text",
              "text": ARK_BRIEF.format(id=sid, contract=contract,
                                       spec=json.dumps(spec, ensure_ascii=False, indent=1))}]
    # 原卷插图一起给。实测有图时它画出来的几何和原图一致，没图只能靠题干文字猜
    for p in images or []:
        if os.path.exists(p):
            ext = os.path.splitext(p)[1].lstrip(".").lower() or "png"
            first.insert(0, {"type": "input_image", "image_url": "data:image/%s;base64,%s"
                             % (ext, base64.b64encode(open(p, "rb").read()).decode())})
    msgs = [{"role": "user", "content": first}]

    out, prev_id = "", None
    for rd in range(1, rounds + 1):
        log("   ▸ 第 %d 轮（ark %s）" % (rd, model))
        t0 = time.time()
        try:
            txt, usage, prev_id = ark_call(msgs, model, ROUND_TIMEOUT, prev_id)
        except Exception as e:
            return False, "方舟调用失败：%s" % str(e)[:200], rd, sid, "codegen" if codegen else "agent"
        log("     %.0f 秒 · 输出 %s tok（推理 %s）"
            % (time.time() - t0, usage.get("output_tokens"),
               (usage.get("output_tokens_details") or {}).get("reasoning_tokens")))

        def again(text):
            # 续话靠 previous_response_id，所以只发新的这一句，不重发历史
            return [{"role": "user", "content": [{"type": "input_text", "text": text}]}]

        wrote = ark_write(txt, workdir, sid, codegen)
        if len(wrote) < 2:
            log("     只写出 %s，本轮作废" % (wrote or "零个文件"))
            msgs = again("你没有按 ===FILE …=== 格式给全两个文件。重新完整输出两个文件。")
            continue

        ok, out = verify(sid, workdir, codegen)
        gen = "codegen" if codegen else "agent"
        if ok:
            return True, out, rd, sid, gen
        nfail, digest = fail_digest(out)
        log("     门禁 FAIL，%d 条不通过%s" % (nfail, ("：" + digest) if digest else ""))
        msgs = again(ARK_RETRY.format(report=out[-6000:]))
    return False, out or "没有产出", rounds, sid, "codegen" if codegen else "agent"


# 认证/计费失败的特征。撞上这些就不该再重试 —— 实测 302 余额耗尽那次，
# 第8、9题各把 6 轮全烧完，每轮 agent 一启动就 401 退出，日志里却记成
# 「跑满 6 轮仍未通过」，看起来像实现不行。**钱的问题要报成钱的问题。**
AUTH_FAIL = ("Insufficient account balance", "余额不足", "Failed to authenticate",
             "invalid api key", "Invalid API key", "401 ", "authentication_error",
             "credit balance is too low")


def auth_failed(text):
    low = (text or "")
    return next((s for s in AUTH_FAIL if s in low or s.lower() in low.lower()), None)


def sha256(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def guard_snapshot():
    """spec 与 harness 的指纹。沙箱跑完要比对 —— 不是相信它不改，是改了能发现。"""
    out = {}
    for line in open(GUARD, encoding="utf-8"):
        line = line.strip()
        if line:
            _h, _p = line.split(None, 1)
            out[_p] = sha256(os.path.join(ROOT, _p))
    for d in (SPECS, os.path.join(ROOT, "harness")):
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                out[os.path.relpath(p, ROOT)] = sha256(p)
    return out


def verify(sid, workdir, codegen=False):
    """
    跑门禁，返回 (是否通过, 输出)。这是唯一的判据。

    代码生成那条路**先自己跑一遍 build**，不采信 agent 有没有跑过 ——
    它可能忘了、可能跑在别的目录、也可能改完 draw.js 就直接来问结果。
    ⑥ 验的必须是拼装后的产物。
    """
    py = os.path.join(ROOT, ".venv", "bin", "python")
    py = py if os.path.exists(py) else sys.executable
    if codegen:
        r0 = subprocess.run([py, os.path.join(ROOT, "harness", "build.py"), sid],
                            cwd=workdir, capture_output=True, text=True, timeout=300)
        if r0.returncode != 0:
            return False, ((r0.stdout or "") + (r0.stderr or "")
                           + "\n（拼装没过，门禁没跑）\nVERDICT: FAIL")
    r = subprocess.run([py, os.path.join(ROOT, "harness", "verify.py"), sid],
                       cwd=workdir, capture_output=True, text=True, timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    return out.rstrip().endswith("VERDICT: PASS"), out


def fail_digest(out):
    """
    门禁报告 → (失败条数, "L4×2、L5×3")。

    连**哪一层**一起报。只说「N 条不通过」的话，页面上看着这道题一轮一轮地跑，
    却不知道它卡在物理断言还是卡在版面 —— 前者可能是 spec 本身有问题（人得介入），
    后者 agent 自己挪挪坐标就能好（等着就行）。两种情况该做的事完全不同。

    层级取自每条失败行的 `✗ [层/代号]`，不依赖 verify.py 汇总行的格式。
    两条 backend 路径共用这一份，不各写一份。
    """
    fails = [l for l in out.splitlines() if l.strip().startswith("✗")]
    by = {}
    for l in fails:
        m = re.search(r"✗\s*\[([^/\]]+)", l)
        if m:
            by[m.group(1)] = by.get(m.group(1), 0) + 1
    return len(fails), "、".join("%s×%d" % kv for kv in sorted(by.items()))


def build(sid, spec, rounds=6, model=MODEL, log=print, backend="relay", images=None):
    """
    实现一个场景，循环到门禁绿灯或轮次耗尽。

    每轮之后都跑一次门禁自己确认 —— **三条路都一样，不采信实现方自己说的 PASS**。
    它可能没跑、跑错目录、或者看错了末行。绿灯只由 verify.py 的末行决定。
    """
    if backend in ("subscription", "relay", "ark-cli") and not CLI:
        raise RuntimeError("backend=%s 需要 claude 可执行文件，没找到" % backend)
    # ── 这一整段必须串行，即使多道题在并行跑 ────────────────────────────
    # 两件事在并行下会坏掉：
    #   1. `-genN` 的分配是「查一下有没有 → 再写」，两个 worker 会抢到同一个名字，
    #      后写的把先写的 spec 覆盖掉，而两边都以为自己在做自己的题
    #   2. `before` 快照扫的是整个 specs/ 与 harness/。别的 worker 正好在写它的
    #      spec 文件时扫到半个文件，本轮结束再扫就对不上 —— 会误报「沙箱改了只读文件」
    #      而把一轮好好的结果作废
    # 分配 + 落盘 + 取快照三件事一起锁住。它们都很快，锁住不影响并行度。
    with SETUP:
        guarded = set(guard_snapshot())
        # 阶段④ 给的 id 形如 `q16`，会和 specs/ 下**受保护的人工版同名**。
        # 直接写下去就是覆盖只读文件 —— 而且是被自己的篡改检查抓住之前先毁掉原件。
        # 所以落盘前先避让：已存在且受保护的名字一律加后缀。
        if os.path.join("specs", sid + ".spec.json") in guarded:
            base, k = sid, 2
            while os.path.exists(os.path.join(SPECS, "%s-gen%d.spec.json" % (base, k))):
                k += 1
            sid = "%s-gen%d" % (base, k)
            spec = dict(spec, id=sid)     # figure 的 data-scene 与 id 前缀都要跟着改
            log("     spec id 与受保护的人工版同名，改用 %s" % sid)

        workdir = os.path.join(RUNS, sid)
        os.makedirs(workdir, exist_ok=True)
        spec_path = os.path.join(SPECS, sid + ".spec.json")
        # 先写临时文件再原子改名：别人扫快照时不会读到半个文件
        tmp = spec_path + ".tmp"
        json.dump(spec, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, spec_path)

        before = guard_snapshot()

    # 走不走代码生成，**在这里一次判死**。没有 reference 的 spec 退回原来的
    # agent 流程 —— 硬跑的话它会在拼装那一步失败，白烧一轮
    codegen, why = scenegen.can_codegen(spec)
    if codegen and backend == "ark":
        # 方舟那条路的提示词是把 CONTRACT.md 整个塞进消息里的，还在让模型写
        # `<id>.js`。开了代码生成的话它产出的文件名会被 allow-list 丢掉，
        # 白烧一轮。等那条路的提示词也改了再放开
        codegen, why = False, "方舟后端的提示词还没跟着改，先走 agent 流程"
    py = os.path.join(ROOT, ".venv", "bin", "python")
    py = py if os.path.exists(py) else "python3"
    if codegen:
        sk = scenegen.skeleton(spec)
        open(os.path.join(workdir, sid + ".skel.js"), "w", encoding="utf-8").write(sk["js"])
        log("     代码生成：物理表 %.0f KB，读数 %s"
            % (len(sk["js"]) / 1024.0, "、".join(sk["readouts"])))
    else:
        log("     退回 agent 流程：%s" % why)

    # 方舟那条路模型碰不到文件系统，写盘的是我们，篡改在结构上就不可能发生 ——
    # 所以它不用走下面那套「跑完比对哈希」的流程
    if backend == "ark":
        return ark_build(sid, spec, workdir, rounds, model, images, log, codegen)

    if codegen:
        brief = BRIEF_CODEGEN.format(
            id=sid, contract=os.path.join(ROOT, "harness", "CONTRACT.md"),
            spec=spec_path, verify=os.path.join(ROOT, "harness", "verify.py"),
            check=os.path.join(ROOT, "harness", "check.py"), py=py,
            rect=json.dumps(sk["rect"]), readouts=json.dumps(sk["readouts"]),
            keys="、".join(spec.get("probe_keys") or []))
    else:
        brief = BRIEF.format(id=sid, contract=os.path.join(ROOT, "harness", "CONTRACT.md"),
                             spec=spec_path,
                             verify=os.path.join(ROOT, "harness", "verify.py"), py=py)

    msg = brief
    for rd in range(1, rounds + 1):
        log("   ▸ 第 %d 轮（%s %s）" % (rd, backend, model))
        try:
            out_txt = run_agent(msg, workdir, model, ROUND_TIMEOUT, backend)
        except subprocess.TimeoutExpired:
            log("     第 %d 轮超时 %d 分钟，已终止整个进程组" % (rd, ROUND_TIMEOUT // 60))
            made = sid + (".draw.js" if codegen else ".js")
            if not os.path.exists(os.path.join(workdir, made)):
                return (False, "沙箱跑了 %d 分钟没写出任何文件，判为卡死"
                        % (ROUND_TIMEOUT // 60), rd, sid, "codegen" if codegen else "agent")
            out_txt = ""
        tail = (out_txt or "").strip().splitlines()[-1:] or [""]
        log("     agent: %s" % tail[0][:120])

        # 认证/计费失败：立刻停，别拿剩下的轮次去撞同一堵墙
        why = auth_failed(out_txt)
        if why:
            return (False, "后端认证/计费失败（%s）—— 不是实现的问题。"
                           "换 EXAM_SCENE_BACKEND（subscription / ark）或给中转充值" % why,
                    rd, sid, "codegen" if codegen else "agent")

        # 篡改检查先于结果判定：改过 spec 或门禁的话，这一轮的绿灯不作数
        after = guard_snapshot()
        tampered = [k for k in before if before[k] != after.get(k)]
        if tampered:
            return (False, "沙箱改动了只读文件 %s —— 这一轮作废" % tampered, rd, sid, "codegen" if codegen else "agent")

        ok, out = verify(sid, workdir, codegen)
        gen = "codegen" if codegen else "agent"
        if ok:
            return True, out, rd, sid, gen
        nfail, digest = fail_digest(out)
        log("     门禁 FAIL，%d 条不通过%s" % (nfail, ("：" + digest) if digest else ""))
        msg = ("上一轮门禁没过。**不要修改 spec 或 harness，改你自己的实现。**\n"
               "完整报告如下，按里面的层级和 id 逐条修：\n\n" + out[-6000:])
    return False, out, rounds, sid, ("codegen" if codegen else "agent")


def plan(questions, spec_of, done, only=None, allow_draft=False,
         do_all=False, redo=False):
    """
    开工前的清单：回 `(要做的, [(题号, 为什么跳过)])`。

    闸门一道比一道贵，所以顺序不能乱：
      0. **已经有通过门禁的动画** —— 最便宜，一次查询就知道，排最前
      1. ④ 有没有 spec（免费，已在库里）
      2. ④ 判做不做得了
      3. ④b 自检自不自洽（纯计算）
      4. ④c 值不值得做（一次轻量调用）
    再往后才是一题几分钟到几十分钟的付费沙箱。

    第 0 道是「继续执行」那个按钮的前提：接着没做完的往下跑，不是从头再来一遍。
    数据不会丢（`put_scene` 挡住了「失败覆盖成功」），丢的是时间和钱，而且重做
    成功时会把一个已经人工看过的动画换成一个没人看过的。

    两个例外：`only` 是人明确点名重跑（页面上那个按钮），`redo` 是整卷强制重做
    （改完管线想全部重生成时用）。
    """
    todo, skip = [], []
    for q in questions:
        if only and q["n"] not in only:
            continue
        if q["n"] in done and not only and not redo:
            skip.append((q["n"], "已经有通过门禁的动画（要重做加 --redo，或用 --only 点名）"))
            continue
        row = spec_of(q["id"])
        if not row:
            skip.append((q["n"], "没有 spec（④ 没跑到这道题）"))
            continue
        if not row["animatable"]:
            skip.append((q["n"], "④ 判定不适合做动画：%s" % (row["why_not"] or "")[:40]))
            continue
        if row["status"] != "approved" and not allow_draft:
            skip.append((q["n"], "④b 自检未过，不放行"))
            continue
        if row["worth"] is False and not do_all:
            skip.append((q["n"], "④c 判定不值得：%s" % (row["worth_why"] or "")[:40]))
            continue
        if row["worth"] is None and not (do_all or only):
            skip.append((q["n"], "④c 还没判过（跑 pick.py，或加 --all 强行做）"))
            continue
        todo.append((q, row))
    return todo, skip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--only", default="", help="题号，逗号分隔")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--allow-draft", action="store_true",
                    help="spec 还没过 ④b 自检也照做（默认拒绝）")
    ap.add_argument("--all", action="store_true",
                    help="忽略 ④c 的选题结果，候选题全做")
    ap.add_argument("--redo", action="store_true",
                    help="已经通过门禁的题也重做一遍（默认跳过，接着没做完的往下跑）")
    ap.add_argument("-j", "--jobs", type=int,
                    default=int(os.environ.get("EXAM_SCENE_JOBS", "3")),
                    help="并行度。每个沙箱是一个 claude 进程，别开太大")
    ap.add_argument("--backend", default=BACKEND, choices=("auto",) + BACKENDS,
                    help="subscription=订阅 / relay=中转 / ark=豆包直连。"
                         "也可以在 .env 里设 EXAM_SCENE_BACKEND")
    a = ap.parse_args()

    backend = resolve_backend(a.backend)
    # --model 没显式给时，跟着 backend 走，别把 claude 的模型名发给方舟
    model = a.model if a.model != MODEL or os.environ.get("EXAM_SCENE_MODEL") \
        else DEFAULT_MODEL[backend]

    name = os.path.basename(os.path.normpath(a.paper))
    paper = store.get_paper(name)
    if not paper:
        print("库里没有「%s」" % name)
        return 1
    only = {int(x) for x in a.only.split(",") if x.strip()} if a.only else None

    # ── 先出清单，再动手 ──────────────────────────────────────────────
    # 判据在 plan() 里，那边有单元测试。清单先打出来，跳过的都要说得出原因。
    todo, skip = plan(paper["questions"], store.get_spec,
                      set(store.paper_scenes(name)), only=only,
                      allow_draft=a.allow_draft, do_all=a.all, redo=a.redo)

    where = {"subscription": "claude CLI · 订阅", "relay": "claude CLI · 302 中转",
             "ark": "火山方舟直连", "ark-cli": "claude CLI · 豆包驱动"}[backend]
    print("── 生成场景 %s（%s，%s，%d 路并行）" % (name, where, model, a.jobs))
    for n, why in skip:
        print("   － 第%2d题 %s" % (n, why))
    for q, row in todo:
        print("   ▸ 第%2d题 %d 条断言 · %s"
              % (q["n"], row["n_invariants"], (row["worth_why"] or "")[:46]))
    if not todo:
        print("   没有要做的题")
        return 0

    # ── 并行 ──────────────────────────────────────────────────────────
    # 题与题之间没有任何依赖，各自在 runs/<sid>/ 里干活，时间几乎全花在等 agent。
    # 日志按题攒起来一次性打，否则几路交织在一起没法读。
    lock = threading.Lock()
    ok = fail = 0

    def one(item):
        nonlocal ok, fail
        q, row = item
        sid = row["spec"].get("id") or ("q%d" % q["n"])
        # 只做一道题时**边跑边打**，不攒到最后。
        #
        # 攒着是为了多题并行时输出不交错（三路一起打，读都没法读）。但只有一道
        # 题就没有交错可言，而这正是网页「重跑这一题」走的路 —— 攒着的话十几
        # 分钟里页面上一行不动，跟卡死一模一样，而一轮就要几分钟，人根本不知道
        # 它是在跑第几轮、还是已经挂了。api.py 的 run_step 也正是靠逐行 stdout
        # 把进度送上去的。
        stream = len(todo) == 1
        buf = []
        emit = ((lambda s: print("       第%2d题 %s" % (q["n"], s.strip()), flush=True))
                if stream else buf.append)
        t0 = time.time()
        # 原卷插图给方舟那条路用：实测有图时它画出来的几何和原图一致，
        # 没图就只能靠题干文字猜杆是朝上还是朝下 —— 那是会画反的
        imgs = [os.path.join(ROOT, "work", name, f) for f in (q.get("figures") or [])]
        try:
            passed, out, rd, sid, gen = build(sid, row["spec"], a.rounds, model,
                                              log=emit, backend=backend, images=imgs)
        except Exception as e:
            # 崩了也要留一行「试过」。不留的话进度里的 sceneTried 永远追不上
            # ready，⑤ 那一步会永远显示在跑 —— 卷子早停了也一样
            store.put_scene_attempt(q["id"], sid)
            with lock:
                fail += 1
                print("   ✗ 第%2d题 %s" % (q["n"], str(e)[:160]), flush=True)
            return
        store.put_scene(q["id"], sid, rd, passed, gen=gen)
        with lock:
            if passed:
                ok += 1
                print("   ✓ 第%2d题 %s 第 %d 轮通过门禁（%.0f 分钟）"
                      % (q["n"], sid, rd, (time.time() - t0) / 60), flush=True)
            else:
                fail += 1
                print("   ✗ 第%2d题 %s 跑满 %d 轮仍未通过：%s"
                      % (q["n"], sid, rd, out.strip().splitlines()[-1][:100]), flush=True)
            for line in buf:
                print("       第%2d题 %s" % (q["n"], line.strip()), flush=True)

    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        list(pool.map(one, todo))

    print("── 生成场景 %s 结束" % name)
    print("   绿灯 %d，未通过 %d，没做 %d" % (ok, fail, len(skip)))
    print("   绿灯 = 实现与 spec 一致，**不等于解法正确** —— ④b 只查了 spec 内部矛盾")
    return 0


if __name__ == "__main__":
    sys.exit(main())
