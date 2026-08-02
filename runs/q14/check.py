#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check.py —— q14 独立物理核算 + 布局自检

用途：
  1. 从零推导 r1 / r2 / (q/m)1 / (q/m)2 / 两个半周期，打表。
  2. 用与 q14.js 完全相同的公式在 Python 里重建 probe 采样序列，
     再直接 eval spec 里的 invariants，确认物理层面能过。
  3. 复算 figure.html 的像素布局（圆心/落点/圆顶），并用 verify.py 的
     同一套字宽估算规则做文本溢出自检。

运行：
  ../../.venv/bin/python check.py
"""
import os, re, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = json.load(open(os.path.join(ROOT, "specs", "q14.spec.json"), encoding="utf-8"))

# ---------------------------------------------------------------- 1. 物理
B    = 0.1          # T
V    = 96000.0      # m/s   (9.6e4)
QM1  = 4.8e6        # C/kg
K    = 1.1          # ON / OM

# qvB = mv^2/r  =>  r = v / [(q/m) B]
r1  = V / (QM1 * B)
# 落点到 O 的距离 = 直径 => OM = 2 r1, ON = 2 r2 ; ON = 1.1 OM => r2 = 1.1 r1
r2  = K * r1
QM2 = V / (r2 * B)          # = QM1 / 1.1

w1 = QM1 * B                # 回旋角速度 rad/s
w2 = QM2 * B
T1 = np.pi / w1             # 半圆用时 s  (= pi m /(qB))
T2 = np.pi / w2

print("== q14 物理表 ==")
print("  B        = %.4g T" % B)
print("  v        = %.6g m/s" % V)
print("  (q/m)1   = %.6e C/kg" % QM1)
print("  (q/m)2   = %.6e C/kg   ( = (q/m)1 / 1.1 )" % QM2)
print("  r1       = %.6f m      OM = 2r1 = %.6f m" % (r1, 2 * r1))
print("  r2       = %.6f m      ON = 2r2 = %.6f m   ON/OM = %.6f" % (r2, 2 * r2, (2 * r2) / (2 * r1)))
print("  w1       = %.6e rad/s   w2 = %.6e rad/s   w1/w2 = %.6f" % (w1, w2, w1 / w2))
print("  T_half1  = %.6e s = %.4f us" % (T1, T1 * 1e6))
print("  T_half2  = %.6e s = %.4f us   T2/T1 = %.6f" % (T2, T2 * 1e6, T2 / T1))
print("  结论: (q/m)2 < (q/m)1  =>  r2 > r1  =>  T2 > T1  =>  打在 N 的离子【后】到达边界")
print()

# ---------------------------------------------------------------- 2. probe 重建
# u = 1 定义为【较慢】的离子(2 号, 打在 N)刚好到达边界 => t(u) = u * T2
def probe_series(n):
    u = np.linspace(0.0, 1.0, n)
    t = u * T2
    a1 = np.minimum(w1 * t, np.pi)      # 到边界后保持 pi, 不回绕
    a2 = np.minimum(w2 * t, np.pi)
    return {
        "u": u,
        "t_us": t * 1e6,
        "th1_deg": a1 * 180.0 / np.pi,
        "th2_deg": a2 * 180.0 / np.pi,
        "r1": np.full(n, r1),
        "r2": np.full(n, r2),
        "qm1": np.full(n, QM1),
        "qm2": np.full(n, QM2),
    }

N = SPEC.get("sample_points", 401)
S = probe_series(N)
i25 = 100          # spec 用 th*[100] 作 u=0.25 的取样点
print("== 采样自检 (N=%d) ==" % N)
print("  u=0.25  -> th1=%.4f  th2=%.4f  ratio=%.6f" % (S["th1_deg"][i25], S["th2_deg"][i25],
                                                       S["th1_deg"][i25] / S["th2_deg"][i25]))
print("  u=0.95  -> th1=%.4f  th2=%.4f" % (S["th1_deg"][380], S["th2_deg"][380]))
print("  u=1/1.1=%.4f 处 1 号离子到达 M" % (1 / 1.1))
print("  u=1.00  -> th1=%.4f  th2=%.4f  t=%.4f us" % (S["th1_deg"][-1], S["th2_deg"][-1], S["t_us"][-1]))
print()

# ---------------------------------------------------------------- 3. 直接 eval spec 断言
helpers = {
    "abs": np.abs, "min": np.min, "max": np.max, "argmin": np.argmin, "argmax": np.argmax,
    "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan,
    "exp": np.exp, "log": np.log, "pi": np.pi, "diff": np.diff, "where": np.where,
    "all": np.all, "any": np.any, "sum": np.sum, "mean": np.mean, "std": np.std,
    "isfinite": np.isfinite, "sign": np.sign, "interp": np.interp, "len": len,
    "clip": np.clip, "sort": np.sort, "cumsum": np.cumsum, "nonzero": np.nonzero,
}
helpers.update(SPEC.get("constants", {}))

print("== spec.invariants 预演 ==")
nfail = 0
for inv in SPEC["invariants"]:
    ns = dict(helpers); ns.update(S)
    val = bool(np.all(eval(inv["expr"], {"__builtins__": {}}, ns)))
    rep = ""
    if inv.get("report"):
        rv = eval(inv["report"], {"__builtins__": {}}, ns)
        rep = "   %s = %s" % (inv["report"], np.round(np.asarray(rv, dtype=float), 6))
    print("  %s %-16s%s" % ("OK " if val else "BAD", inv["id"], rep))
    if not val:
        nfail += 1
print("  -> %d/%d 通过" % (len(SPEC["invariants"]) - nfail, len(SPEC["invariants"])))
print()

# ---------------------------------------------------------------- 4. 像素布局
YB  = 272.0        # 边界 PP' 的屏幕 y
XO  = 112.0        # 入射点 O 的屏幕 x
PXM = 750.0        # px / m
R1p, R2p = r1 * PXM, r2 * PXM
print("== 像素布局 (viewBox 0 0 560 328) ==")
print("  scale = %g px/m" % PXM)
print("  O  = (%.1f, %.1f)" % (XO, YB))
print("  R1 = %.2f px   圆心1 = (%.2f, %.1f)   M = (%.2f, %.1f)   顶 y = %.2f"
      % (R1p, XO + R1p, YB, XO + 2 * R1p, YB, YB - R1p))
print("  R2 = %.2f px   圆心2 = (%.2f, %.1f)   N = (%.2f, %.1f)   顶 y = %.2f"
      % (R2p, XO + R2p, YB, XO + 2 * R2p, YB, YB - R2p))
print("  慢放倍数 = 5e5  =>  弧段动画时长 = %.4f s" % (5e5 * T2))
print()

# ---------------------------------------------------------------- 5. 文本溢出自检
figp = os.path.join(HERE, "q14.figure.html")
if os.path.exists(figp):
    fig = open(figp, encoding="utf-8").read()
    print("== figure 文本宽度自检 (verify.py 同款规则, 上限 552) ==")
    worst = 0.0
    for tm in re.finditer(r'<text[^>]*\bx="(-?\d+(?:\.\d+)?)"[^>]*>([^<]*)</text>', fig):
        x, txt = float(tm.group(1)), tm.group(2)
        w = sum(11.5 if ord(c) > 0x2E80 else 6.6 for c in txt)
        end = x + w
        worst = max(worst, end)
        flag = "OVERFLOW" if end > 552 else "        "
        print("  %s x=%-6g end=%-7.1f %s" % (flag, x, end, txt[:44]))
    print("  最大右端 = %.1f" % worst)

    # 运行时会被改写的读数, 用最长文案再算一遍
    print("== 动态文本(最长态)宽度自检 ==")
    dyn = [(362.0, "θ₁ = 180.0°"), (452.0, "已到达 M"),
           (362.0, "θ₂ = 180.0°"), (452.0, "已到达 N"),
           (64.0,  "t = 7.20 μs（慢放 5×10⁵ 倍）")]
    for x, txt in dyn:
        w = sum(11.5 if ord(c) > 0x2E80 else 6.6 for c in txt)
        print("  %s x=%-6g end=%-7.1f %s" % ("OVERFLOW" if x + w > 552 else "        ", x, x + w, txt))
