#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spec.py —— 阶段④ 写题目规格与物理断言

    python pipeline/spec.py <卷名> [--only 11,14] [--force] [--limit N]

这一步产出的是**交给沙箱的唯一规范**：题干、权威解法、要覆盖的情形、
probe 必须暴露的物理量、以及渲染后必须通过的数值断言。

为什么由 DeepSeek 写、而不是写代码的那一方写
--------------------------------------------
`README` 那句「写代码的那一方不能写断言」是整套架构的支点。
自己给自己出卷子的验证等于没验证 —— 实现方照着自己的实现写断言，
写出来的一定是「与我的实现一致」，而不是「与物理一致」。

所以：③ 解题用 claude CLI（要看图），④ 写断言用 DeepSeek，
⑤ 写场景用 claude CLI 的沙箱 agent。三个环节三个进程三份上下文，
红线靠进程边界保证，不靠提示词里的一句嘱咐。

这一步也是**整条链上唯一没有下游检查的环节**
--------------------------------------------
解法错了断言能抓，实现错了断言能抓，**断言自己错了没有任何东西能抓**。
而且它错的方式很隐蔽：

  · 写松了（`<= 100`）—— 永远绿灯，门禁形同虚设
  · 物理量名写错（`v_A` 写成 `vA`）—— L4 报「case 没有采样数据」，不是失败
  · 架在错误假设上 —— 实现与 spec 一致，全绿，而物理是错的

所以产物一律 `status='draft'`，必须过人审才能进阶段⑤。
`animatable=false` 是诚实阀门：纯概念题、纯读图题写不出数值断言，
与其编几条永远成立的假断言，不如明说它不适合做成动画。
"""
import argparse, hashlib, json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store
import cliask      # 订阅只能经 claude CLI 用，没有 HTTP 端点

for _l in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# 断言这一环用 claude-sonnet-5。换掉 DeepSeek 的直接原因：
# 它给福建卷第16题写的受力方程把**弹簧力的符号写反、摩擦力整项写丢**
# （`a = Fc + Fs − 1`，正确是 `a = 1 + 1/d² − 2 − Fs`），
# 而同一份 spec 的终点值断言又编码了正确答案 —— 两者互相矛盾，
# 沙箱跑三轮都过不了。lint 只能查形式，查不出力的方向错了。
#
# 传输方式两选一：
#   subscription  经 claude CLI 走本机订阅（默认）。**订阅没有 HTTP 端点**，
#                 只能这么用。中转站欠费那次整卷 ④ 全挂，就是因为原来写死了 HTTP。
#   http          任何 OpenAI 兼容端点（EXAM_SPEC_BASE/KEY/MODEL），
#                 例如火山方舟：https://ark.cn-beijing.volces.com/api/v3
# 同 solve.py：5 分钟不回就是卡死，重试一条新连接。原来 1800×3 = 最长 90 分钟干等
HTTP_TIMEOUT = int(os.environ.get("EXAM_HTTP_TIMEOUT", "300"))
BACKEND = os.environ.get("EXAM_SPEC_BACKEND", "subscription")
KEY = os.environ.get("EXAM_SPEC_KEY", "")
BASE = os.environ.get("EXAM_SPEC_BASE", "")
MODEL = os.environ.get("EXAM_SPEC_MODEL") or (
    "claude-sonnet-5" if BACKEND == "subscription" else "doubao-seed-evolving")

# L4 求值时命名空间里只有这些 —— 断言表达式不能用别的函数
ALLOWED = ("abs min max argmin argmax sqrt sin cos tan arctan exp log pi diff where "
           "all any sum mean std isfinite sign interp len clip sort cumsum nonzero").split()

PROMPT = """你在为一个「把物理题做成可验证动画」的管线写**题目规格（spec）**。

下游有两方，互不相见：
- 沙箱 agent 拿你的 spec 去写动画代码。它**看不到你的推理过程**，只看 spec。
- 一个只读的门禁程序拿你的 `invariants` 去检验它写出来的动画。

沙箱会实现一个纯函数 `probe(u, caseId)`：`u ∈ [0,1]` 是**物理过程进度**
（不是播放时间），返回你在 `probe_keys` 里点名的全部物理量。
门禁会在 `sample_points` 个 u 上采样，把每个物理量堆成 numpy 数组，
然后逐条 eval 你的 `expr`。

只输出 JSON（不要代码块围栏、不要解释）：

{
  "animatable": true/false,
  "why_not": "animatable 为 false 时说明理由，否则空串",
  "spec": {
    "id": "q<题号>",
    "title": "一句话标题",
    "stem": "题干（可以精简，但不能改变物理条件）",
    "physics": {
      "note": "以下为权威解法，实现必须与之一致。禁止自行改动力的形式。",
      "normalization": "如何无量纲化（取哪个量为 1）",
      "definitions": ["符号的定义"],
      "equations": ["运动方程 / 守恒关系"],
      "given_facts": ["F1 · …", "F2 · …"],
      "free_parameters": "题面没给、需要实现方自己解出来的参数；没有就写空串"
    },
    "scene_requirements": ["画面上必须出现什么"],
    "units": "各物理量的单位约定",
    "cases": [{"id": "c1", "label": "情形说明"}],
    "probe_keys": ["u", "..."],
    "probe_key_meaning": {"u": "归一化进度，等于传入的 u"},
    "process_endpoints": "u=0 和 u=1 分别对应物理过程的哪一刻",
    "sample_points": 401,
    "constants": {},
    "disclosures": [{"must_contain": "无量纲", "why": "为什么必须在画面上披露"}],
    "invariants": [
      {"id": "c1-xxx", "case": "c1", "expr": "abs(vA[-1] - 2.0) <= 0.04",
       "report": "vA[-1]", "why": "对应 given_facts 的哪一条"}
    ]
  }
}

写 `invariants` 的硬性要求：

1. **表达式里出现的每个变量名，必须在 `probe_keys` 里**。名字写错不会报错，
   门禁只会说「case 没有采样数据」，于是这条断言等于没写。
2. 只能用这些函数：__ALLOWED__。没有 `np.`，没有 `import`，没有属性访问。
   数组切片（`vA[-1]`、`d[argmin(vA)]`）和布尔索引（`vA[vB > 0]`）可以用。
3. **每条断言必须钉住一个具体数值**，来自题目给定或解出的答案。
   `max(diff(d)) <= 1e-9`（单调）、`abs(vA[-1]/v1[0] - 2.0) <= 0.04`（终值）
   这种是对的；`vA[-1] > 0` 这种松到永远成立的是**有害的**——它让门禁变成摆设。
4. **容差要留给数值积分**。实现方是用数值方法积出轨迹的，不是解析解。
   对由积分累积出来的量（速度、位移、时间），容差取该量的 2%~5%；
   对代数关系直接给出的量（力、加速度），可以收到 1%。
   一律写 1e-9 会把正确实现误杀，一律写 0.5 等于没约束 —— 两头都要避免。
5. 必须同时包含这三类，缺一类就等于漏掉一整类错误：
   · **终点值**：对应题目答案，例如 `abs(vA[-1]/v1[0] - 2.0) <= 0.04`
   · **单调性 / 守恒量**：覆盖全过程，例如 `max(diff(d)) <= 1e-9`
   · **物理量之间的自洽**：例如「速度取极值处加速度必须为零」
     `abs(aA[argmin(vA)]) <= 0.12`。
     这一类最容易被忽略，但它抓的是「probe 内部自相矛盾」——
     实现方可能让 vA 与 aA 各算各的，数值上互不相干却都满足各自的终点值。
     **凡是 probe_keys 里同时有某个量和它的导数，就必须写一条这样的断言。**
6. `why` 要指回 `given_facts` 的编号，人审时才能对照。

> 写完之后会有一步自动检查：把你的 `equations` 实现成可执行代码跑一遍，
> 再用**你自己的 `invariants`** 去验。**验不过就自动打回。**
> 所以 `equations`、`given_facts`、`invariants` 三者必须真的能对上，
> 不能「受力公式随手写、终点值照抄答案」—— 那样两边对不上，一跑就露。

判 `animatable=false` 的情形：题目没有随时间演化的物理过程
（纯概念辨析、纯读图、纯单位换算、只求一个静态数值），
或者所有可检验量都是离散的选项字母而非连续物理量。
**这种情况不要硬编断言**，直接说明理由。
""".replace("__ALLOWED__", "、".join(ALLOWED))   # 正文里有 % 号，不能用 % 格式化


REF_PROMPT = """把下面这份 spec 里的物理**实现成可执行的 Python**，供自动校验用。

只输出代码（不要 JSON、不要围栏、不要解释），定义一个函数：

    def probe(u, case):
        ...
        return {"u": u, ...}          # spec 的 probe_keys 里的全部量

要求：

- **力的形式必须与 spec 的 `physics.equations` 完全一致。** 这段代码就是用来
  检验那些方程的，照抄答案凑数没有意义 —— 凑出来的会和 `invariants` 对不上。
- 题面没给的参数（spec 的 `free_parameters`）你要自己解出一组满足全部
  `given_facts` 的自洽值，写死在代码里。用数值方法求解，别心算。
- `u ∈ [0,1]` 是物理过程进度，`u=1` 对应 `process_endpoints` 说的终点。
- 单位以 spec 的 `units` 为准。
- 只能用 `math` 的函数（`sqrt`、`pi`、`sin` 等已预置，直接写名字），
  **不要 import、不要读写文件、不要 print**。数值积分自己写循环。
- 返回值必须是有限数值，不能有 NaN/Infinity。

spec 如下：

"""


def ask_reference(spec, tries=2):
    """
    单独一次调用要参考实现。

    不和写 spec 合并成一次 —— 实测合并后 prompt 太重，模型的思维链把
    32000 token 额度全吃光、正文一个字都没输出（`finish_reason: length`，
    `content` 为空串）。拆成两次，每次都轻，而且第二次是个界限清楚的编码任务。
    """
    slim = {k: spec[k] for k in ("id", "physics", "units", "cases", "probe_keys",
                                 "probe_key_meaning", "process_endpoints", "constants",
                                 "invariants") if k in spec}
    for k in range(tries):
        try:
            txt = ask_raw(REF_PROMPT + json.dumps(slim, ensure_ascii=False, indent=1))
            code = re.sub(r"^```[a-z]*\n|```$", "", txt.strip(), flags=re.M).strip()
            if "def probe" in code:
                return code
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(5)
    return ""


def ask_raw(payload, tries=3):
    """调模型，返回原始文本。两条传输路只在这里分叉，上面的逻辑一律不用管。"""
    for k in range(tries):
        try:
            if BACKEND == "subscription":
                return cliask.ask(payload, model=MODEL)
            body = json.dumps({"model": MODEL, "max_tokens": 32000,
                               "messages": [{"role": "user", "content": payload}]}).encode()
            r = urllib.request.Request(BASE + "/chat/completions", body,
                                       {"Authorization": "Bearer " + KEY,
                                        "Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(r, timeout=HTTP_TIMEOUT).read())
            return d["choices"][0]["message"].get("content") or ""
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def ask(payload, tries=3):
    """
    调模型要 spec。

    压轴题的 spec 又长又带思维链，实测响应会被截断成 `IncompleteRead`——
    不是模型不会写，是连接没撑住。重试即可，不必降级题目。

    `max_tokens` 要么不设、要么给足。思维链和正文共用这个额度，
    设成 16000 时压轴题的思维链把额度吃光、正文返回空串，
    错误表现成「没有返回 JSON」而不是「被截断」—— 比原因难查得多。
    """
    txt = ask_raw(payload, tries)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("没有返回 JSON：%s" % txt[:200])
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', m.group(0)))


IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
# 科学计数法里的 e 不是变量名（`1e-9` 会被切出一个 `e`），先把数字整个抹掉
NUM = re.compile(r"\b\d+\.?\d*(?:[eE][+-]?\d+)?\b")
# 表达式在 eval 里跑，Python 的这些关键字/字面量是合法的
KEYWORDS = {"and", "or", "not", "True", "False", "None", "if", "else", "in", "is"}


def names_in(expr):
    return set(IDENT.findall(NUM.sub(" ", expr or ""))) - KEYWORDS


def lint(spec):
    """
    静态检查 spec 自身。**这是断言唯一的下游检查**，所以宁可严一点。

    抓的都是「不会报错、只会让门禁失效」的写法：变量名不在 probe_keys 里、
    用了 L4 命名空间里没有的函数、断言松到永远成立。
    """
    bad = []
    keys = set(spec.get("probe_keys") or [])
    cases = {c["id"] for c in (spec.get("cases") or [])}
    consts = set(spec.get("constants") or {})
    if not keys:
        bad.append("probe_keys 是空的，断言无从写起")
    if not cases:
        bad.append("cases 是空的")
    invs = spec.get("invariants") or []
    if not invs:
        bad.append("一条断言都没有")
    seen = set()
    for inv in invs:
        i = inv.get("id", "?")
        if i in seen:
            bad.append("断言 id 重复：%s" % i)
        seen.add(i)
        for f in ("id", "case", "expr", "why"):
            if not inv.get(f):
                bad.append("断言 %s 缺 %s" % (i, f))
        if inv.get("case") and inv["case"] not in cases:
            bad.append("断言 %s 的 case '%s' 不在 cases 里" % (i, inv["case"]))
        expr = inv.get("expr") or ""
        unknown = names_in(expr) - keys - set(ALLOWED) - consts
        if unknown:
            bad.append("断言 %s 用了未声明的名字 %s —— 门禁会当成「没有采样数据」而不是失败"
                       % (i, sorted(unknown)))
        if not re.search(r"[<>=]", expr):
            bad.append("断言 %s 没有比较运算，不构成命题：%s" % (i, expr))
        # 「永远成立」的典型写法：只跟 0 比大小，没有钉住任何数值
        if re.fullmatch(r"[\w\[\]\-\.]+\s*[<>]=?\s*0(\.0*)?", expr.strip()):
            bad.append("断言 %s 只与 0 比较，松到几乎永远成立：%s" % (i, expr))

    # ---- 覆盖面：缺一类就漏掉一整类错误 ----
    exprs = " ".join(inv.get("expr", "") for inv in invs)
    if "diff(" not in exprs and "std(" not in exprs:
        bad.append("没有任何单调性/守恒量断言（没用到 diff 或 std）——"
                   "过程中间怎么走完全不受约束，只要两端对上就能过")
    if "[-1]" not in exprs:
        bad.append("没有任何终点值断言（没用到 [-1]）——题目的答案没有被检验")
    # probe_keys 里同时有某量和它的导数时，必须有一条把两者绑起来的断言。
    # 少了它，实现方可以让二者各算各的：数值上互不相干，却都满足各自的终点值。
    pairs = [(v, d) for v, d in (("vA", "aA"), ("v_A", "a_A"), ("v", "a"))
             if v in keys and d in keys]
    for v, d in pairs:
        if not any(d in e and ("argmin(%s)" % v in e or "argmax(%s)" % v in e)
                   for e in (inv.get("expr", "") for inv in invs)):
            bad.append("%s 与 %s 同时暴露，却没有一条断言把两者绑起来"
                       "（如「速度取极值处加速度为零」）—— probe 内部自相矛盾抓不出来" % (v, d))
    return bad


def src_hash(q, sol):
    h = hashlib.sha256()
    h.update((q.get("stem_latex") or q.get("stem") or "").encode())
    h.update(json.dumps(sol.get("key_facts") or [], ensure_ascii=False).encode())
    h.update(str(sol.get("answer") or "").encode())
    return h.hexdigest()


def payload_for(q, sol):
    parts = ["【题号】%d" % q["n"], "【题型】%s" % (q.get("type") or "")]
    parts.append("【题干】\n" + (q.get("stem_latex") or q.get("stem") or ""))
    for t in q.get("tables") or []:
        if t.get("rows"):
            parts.append("【表%d】\n%s" % (t["id"], "\n".join(" | ".join(r) for r in t["rows"])))
    if q.get("options"):
        parts.append("【选项】\n" + "\n".join(
            "%s. %s" % (o["key"], o.get("latex") or o.get("text") or "") for o in q["options"]))
    parts.append("【阶段③ 给出的答案】\n" + (sol.get("answer") or ""))
    parts.append("【解题步骤】\n" + "\n".join("- " + s for s in (sol.get("steps") or [])))
    parts.append("【可检验事实】（断言应当钉住这些）\n" +
                 "\n".join("- " + s for s in (sol.get("key_facts") or [])))
    if sol.get("assumptions"):
        parts.append("【解题时自补的假设】（题面没给，断言若依赖它们必须在 free_parameters 里说明）\n"
                     + "\n".join("- " + s for s in sol["assumptions"]))
    parts.append("【解题置信度】" + (sol.get("confidence") or "?"))
    return "\n\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--picked", action="store_true",
                    help="只给 ④c 选中要做动画的题写断言（管线里默认这么跑）")
    ap.add_argument("-j", "--jobs", type=int,
                    default=int(os.environ.get("EXAM_SPEC_JOBS", "4")),
                    help="并行度。瓶颈全在等远端，本地基本闲着")
    a = ap.parse_args()

    name = os.path.basename(os.path.normpath(a.paper))
    paper = store.get_paper(name)
    if not paper:
        print("库里没有「%s」" % name)
        return 1
    only = {int(x) for x in a.only.split(",") if x.strip()} if a.only else None

    # ── 先挑出要做的题，再并行 ──────────────────────────────────────
    # 原来是逐题串行的。一题两次模型调用（spec + 参考实现），实测豆包 6 分钟一题 ——
    # 19 题的卷子就是近两小时，而这段时间里本地 CPU 基本闲着，全在等远端。
    # 和 solve.py 一样：题与题之间没有任何依赖，并行是纯赚的。
    todo = []
    skip = 0
    # --picked：只做 ④c 选中的题。断言的用途主要是给 ⑤ 当验收标准，
    # 而写一份完整 spec 要两次调用约 6 分钟 —— 给注定不做动画的题写等于白花
    pick = store.picked(name) if a.picked else None
    for q in paper["questions"]:
        if only and q["n"] not in only:
            continue
        if pick is not None and q["n"] not in pick:
            skip += 1
            continue
        if a.limit and len(todo) >= a.limit:
            break
        sol = store.get_solution(q["id"])
        if not sol:
            continue                       # 还没解题，跳过
        sha = src_hash(q, sol)
        if not a.force and store.spec_fresh(q["id"], sha):
            skip += 1
            continue
        todo.append((q, sol, sha))

    done = fail = noanim = 0
    lock = threading.Lock()

    def one(item):
        nonlocal done, fail, noanim
        q, sol, sha = item
        try:
            d = ask(PROMPT + "\n\n" + payload_for(q, sol))
        except Exception as e:
            with lock:
                fail += 1
                print("   ✗ 第%2d题 %s" % (q["n"], str(e)[:140]), flush=True)
            return

        spec = d.get("spec") or {}
        if not d.get("animatable", True):
            store.put_spec(q["id"], spec, False, d.get("why_not") or "", sha, MODEL)
            with lock:
                noanim += 1
                print("   第%2d题 不适合做动画：%s"
                      % (q["n"], (d.get("why_not") or "")[:70]), flush=True)
            return

        problems = lint(spec)
        # 再要一段可执行的受力实现。它是 speccheck 的输入 ——
        # 没有它就只能靠人看方程，而方程写错正是这一环最常见的失败
        try:
            spec["reference"] = ask_reference(spec)
            if not spec["reference"]:
                problems.append("没能拿到参考实现，无法自动校验")
        except Exception as e:
            problems.append("参考实现调用失败：%s" % str(e)[:80])
        store.put_spec(q["id"], spec, True, "；".join(problems), sha, MODEL)
        with lock:
            done += 1
            print("   第%2d题 %d 条断言 · %d 个 probe_key · %d 个情形%s"
                  % (q["n"], len(spec.get("invariants") or []),
                     len(spec.get("probe_keys") or []), len(spec.get("cases") or []),
                     "" if not problems else "  ⚠ %d 处问题" % len(problems)), flush=True)
            for pb in problems:
                print("      · " + pb, flush=True)

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
            list(pool.map(one, todo))

    print("── 写 spec %s（%s，%d 路并行%s）"
          % (name, MODEL, a.jobs, "，只做 ④c 选中的题" if a.picked else ""))
    print("   新写 %d 题，判定不适合做动画 %d 题，跳过 %d，失败 %d" % (done, noanim, skip, fail))
    print("   全部为 draft —— 断言是唯一没有下游检查的环节，必须过人审才能进阶段⑤")
    return 0


if __name__ == "__main__":
    sys.exit(main())
