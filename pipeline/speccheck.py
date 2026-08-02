#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
speccheck.py —— spec 的自动审核：让 spec 自己验自己

    python pipeline/speccheck.py <卷名> [--only 14] [--apply]

为什么需要它
------------
断言是整条链上**唯一没有下游检查的环节**。解法错了断言能抓、实现错了门禁能抓，
断言自己错了没有任何东西能抓 —— 而它错得很隐蔽。

实测福建卷第16题，阶段④ 写出的 spec 里同时有：

    受力：a = Fc + Fs − 1              ← 错的（弹簧力符号反了、摩擦力整项写丢）
    终点：碰撞瞬间速度 = (1+√3)v₁      ← 对的（照着正确答案写的）

两者互相矛盾。lint 全过（格式没毛病），沙箱跑三轮都过不了 ——
**用错的力积分，终点值不可能是 (1+√3)**。

这个检查做的就是这件事：拿 spec 自带的 `reference`（④ 写的可执行版受力方程）
跑出数据，再用 **spec 自己的 `invariants`** 去验。
自己的实现满足不了自己的断言 = 内部矛盾 = 直接 rejected。

不是「再问一个模型对不对」—— 那只是又一个意见。**这里是一次计算。**

抓不住什么
----------
如果阶段③ 从一开始就理解错了题，④ 忠实地把错误理解写成**自洽的** spec，
equations 和 given_facts 一起错但彼此不矛盾，这里会全绿。
那种只能对照原卷发现，是人审的活 —— 但经此一关，人要看的量少得多。
"""
import argparse, json, os, subprocess, sys, tempfile, textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

# 跑参考实现的子进程脚本。放子进程里有两个原因：
# 代码是模型生成的（超时、死循环、异常都不该拖垮调用方），
# 而且这样能干净地限制它的运行时间。
RUNNER = r'''
import json, math, sys
spec = json.load(open(sys.argv[1], encoding="utf-8"))
ns = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
ns["__builtins__"] = {"range": range, "len": len, "abs": abs, "min": min, "max": max,
                      "sum": sum, "round": round, "float": float, "int": int,
                      "enumerate": enumerate, "sorted": sorted, "list": list,
                      "dict": dict, "tuple": tuple, "zip": zip, "print": print}
exec(spec["reference"], ns)
probe = ns["probe"]

n = int(spec.get("sample_points") or 401)
out = {}
for c in spec["cases"]:
    cid = c["id"]
    cols = {}
    for i in range(n):
        u = i / (n - 1.0)
        r = probe(u, cid)
        for k, v in r.items():
            cols.setdefault(k, []).append(float(v))
    out[cid] = cols
json.dump(out, open(sys.argv[2], "w"))
'''


def run_reference(spec, timeout=120):
    """跑 spec 自带的参考实现，返回 {case: {量名: [采样值]}}。"""
    ref = (spec.get("reference") or "").strip()
    if not ref:
        raise RuntimeError("spec 没有 reference —— 无法自动验证")
    with tempfile.TemporaryDirectory() as tmp:
        sp = os.path.join(tmp, "spec.json")
        op = os.path.join(tmp, "out.json")
        rp = os.path.join(tmp, "runner.py")
        json.dump(spec, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
        open(rp, "w", encoding="utf-8").write(RUNNER)
        r = subprocess.run([sys.executable, rp, sp, op],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError("参考实现跑不起来：%s" % (r.stderr or "")[-300:])
        return json.load(open(op, encoding="utf-8"))


def check(spec):
    """
    用 spec 自己的断言验 spec 自己的参考实现。

    求值逻辑与 `harness/verify.py` 的 L4 **逐字一致** —— 两处不一致的话，
    这一关放行的 spec 会在门禁那里失败，等于白检查。
    """
    import numpy as np
    data = run_reference(spec)
    helpers = {
        "abs": np.abs, "min": np.min, "max": np.max, "argmin": np.argmin, "argmax": np.argmax,
        "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan,
        "exp": np.exp, "log": np.log, "pi": np.pi, "diff": np.diff, "where": np.where,
        "all": np.all, "any": np.any, "sum": np.sum, "mean": np.mean, "std": np.std,
        "isfinite": np.isfinite, "sign": np.sign, "interp": np.interp, "len": len,
        "clip": np.clip, "sort": np.sort, "cumsum": np.cumsum, "nonzero": np.nonzero,
    }
    helpers.update(spec.get("constants") or {})

    ok, bad = [], []
    for inv in spec.get("invariants") or []:
        cols = data.get(inv.get("case"))
        if cols is None:
            bad.append((inv["id"], "case '%s' 参考实现没产出数据" % inv.get("case")))
            continue
        ns = dict(helpers)
        missing = set()
        for k, v in cols.items():
            ns[k] = np.array(v, dtype=float)
        try:
            val = bool(np.all(eval(inv["expr"], {"__builtins__": {}}, ns)))
        except NameError as e:
            bad.append((inv["id"], "%s —— 参考实现没返回这个量，或名字拼错了" % e))
            continue
        except Exception as e:
            bad.append((inv["id"], "求值失败：%s" % e))
            continue
        if val:
            ok.append(inv["id"])
        else:
            rep = ""
            if inv.get("report"):
                try:
                    rep = "  实测 %s = %s" % (inv["report"], np.round(
                        np.asarray(eval(inv["report"], {"__builtins__": {}}, ns),
                                   dtype=float), 4))
                except Exception:
                    pass
            bad.append((inv["id"], "不成立：%s%s" % (inv["expr"], rep)))
    return ok, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--only", default="")
    ap.add_argument("--apply", action="store_true",
                    help="按结果改 specs.status：全过则 approved，否则 rejected")
    a = ap.parse_args()

    name = os.path.basename(os.path.normpath(a.paper))
    paper = store.get_paper(name)
    if not paper:
        print("库里没有「%s」" % name)
        return 1
    only = {int(x) for x in a.only.split(",") if x.strip()} if a.only else None

    npass = nfail = nskip = 0
    for q in paper["questions"]:
        if only and q["n"] not in only:
            continue
        row = store.get_spec(q["id"])
        if not row or not row["animatable"]:
            continue
        spec = row["spec"]
        try:
            ok, bad = check(spec)
        except Exception as e:
            nskip += 1
            print("   ? 第%2d题 无法自动验证：%s" % (q["n"], str(e)[:150]))
            if a.apply:
                store.approve_spec(q["id"], False)
            continue
        if bad:
            nfail += 1
            print("   ✗ 第%2d题 %d/%d 条断言在它自己的参考实现上就不成立"
                  % (q["n"], len(bad), len(ok) + len(bad)))
            for i, why in bad[:6]:
                print("        [%s] %s" % (i, why[:130]))
            if a.apply:
                store.approve_spec(q["id"], False)
        else:
            npass += 1
            print("   ✓ 第%2d题 %d 条断言全部自洽" % (q["n"], len(ok)))
            if a.apply:
                store.approve_spec(q["id"], True)

    print("── spec 自检 %s" % name)
    print("   自洽 %d，自相矛盾 %d，跑不起来 %d" % (npass, nfail, nskip))
    print("   这一关只查 spec **内部**是否矛盾。equations 和 given_facts 一起错但彼此"
          "自洽的情况查不出来——那要对照原卷，是人的活。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
