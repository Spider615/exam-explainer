#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
q16 自洽物理参数求解器
======================

无量纲化（与 spec.physics.normalization 一致）：qE = 1, m = 1, 长度单位 d1 = sqrt(kq/E)。

未知量：弹簧原长 L_s、劲度 k_s、细杆长 L_r、初始间距 d0、A 的初速度 v0。

推导（全部解析，不靠手调）
--------------------------
记 d = x_B - x_A，g(d) = a_A = 1 + 1/d^2 - 2 - F_s(d) = 1/d^2 - 1 - F_s(d)，
其中 F_s(d) = k_s (L_s - d) 当 d < L_s，否则 0。

F1  v_A 极小值在 d = 1 且 B 恰好起动
    => 需要 g(1) = 0。若 L_s > 1 则 g(1) = -k_s(L_s-1) != 0，故必须 L_s <= 1。
       L_s = 1 也不行：那样 g 在 d 略小于 1 处会 <0（见 g' 讨论），d=1 就不是极小点。
    => L_s < 1，于是 d in (L_s, 1) 上 g = 1/d^2 - 1 > 0（A 过 S 后先加速），
       d > 1 上 g < 0（A 逼近 S 时减速）。d = 1 是 v_A 的极小点。 [OK]

F2  v_A 极大值处 F_s = 3
    极大值处 g = 0 => 1/d^2 - 1 - 3 = 0 => d = 1/2，且 k_s (L_s - 1/2) = 3。 (i)

    还必须保证 d = 1/2 真是"由加速转减速"的那个零点，即 g 在 (1/2, L_s) 上 > 0。
    g'(d) = -2/d^3 + k_s，g 在 d* = (2/k_s)^(1/3) 取极小。
    若 d* > 1/2，则 g(d*) < g(1/2) = 0，(1/2, L_s) 内会出现 g<0 的区间 —— 与题意矛盾。
    => 需要 d* <= 1/2 => k_s >= 16。                                     (ii)
    这就是提示里说的"加速度在某个区间意外变号"的陷阱。

    另一方面 g 在 d < 1/2 处还有第二个零点（1/d^2 blows up）：
    k_s d^3 - (4 + k_s/2) d^2 + 1 = 0 有根 d = 1/2，因式分解后
    k_s d^2 - 4 d - 2 = 0 => d2 = (2 + sqrt(4 + 2 k_s)) / k_s。
    d < d2 时 g 又变正、v_A 又开始上升。所以细杆必须在此之前碰到 B：
    => L_r > d2。                                                        (iii)

F3/F4 B 起动后 a_A == a_B，故 v_A - v_B 恒定 = v1。令 S = v_A + v_B = -dd/dt，
    S dS/dd = -2 g(d) => S(d)^2 = v1^2 + 4 J(d)，J(d) = ∫_d^1 g(x) dx。
    J 有闭式：J(d) = 1/d + d - 2 - (k_s/2)(L_s - d)^2 (d < L_s)，否则 1/d + d - 2。
    碰撞时 v_A = 2v1, v_B = v1 => S = 3v1 => 9v1^2 = v1^2 + 4 J(L_r)
    => J(L_r) = 2 v1^2  => v1 = sqrt(J(L_r)/2)。                          (iv)

    注意 (iv) 只把 v1 和 L_r 绑在一起，仍剩 1 个自由度：随便挑 L_r（满足 (iii) 且 < 1/2），
    v1 就定了。d0 任选，初速度由 d>=1 段的能量关系 v_A(d)^2 = v1^2 + 2(d + 1/d - 2) 给出。

F5  情形②：S(1) = 2v1 => S(L_r)^2 = 4v1^2 + 4J(L_r) = 4v1^2 + 8v1^2 = 12 v1^2
    => S = 2sqrt(3) v1 => v_A = (S + 2v1)/2 = (sqrt(3)+1) v1，v_B = (sqrt(3)-1) v1。
    F5 是 F1~F4 的推论，不构成额外约束。 [自动满足]

剩下的自由度用"数值鲁棒性"来定：脚本对 (k_s, L_r, d0) 做网格搜索，
对每组参数完整正演、按 401 点采样、逐条求值 spec 里的 16 条 invariant，
挑一个各条余量都最大的。
"""

import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = json.load(open(os.path.join(HERE, "..", "..", "specs", "q16.spec.json"), encoding="utf-8"))


# ----------------------------------------------------------------- 物理
def make_phys(ks, Ls, Lr):
    def Fs(d):
        return ks * (Ls - d) if d < Ls else 0.0

    def g(d):
        return 1.0 / (d * d) - 1.0 - Fs(d)

    def J(d):
        base = 1.0 / d + d - 2.0
        if d < Ls:
            base -= 0.5 * ks * (Ls - d) ** 2
        return base

    return Fs, g, J


def second_zero(ks):
    """g 在 d<1/2 侧的第二个零点 d2（k_s d^2 - 4d - 2 = 0 的正根）"""
    return (2.0 + math.sqrt(4.0 + 2.0 * ks)) / ks


# ----------------------------------------------------------------- 正演积分
def simulate(ks, Ls, Lr, d0, vS, dt=4.0e-4):
    """RK4 时域积分，和 JS 里跑的是同一套算法。
    vS = A 经过 S(d=1) 时的速度。返回 t/d/vA/vB/xA 数组。"""
    _, g, _ = make_phys(ks, Ls, Lr)
    v0 = math.sqrt(vS * vS + 2.0 * (d0 + 1.0 / d0 - 2.0))

    def deriv(s, moving):
        d, vA, vB, xA = s
        a = g(d)
        return np.array([-(vA + vB), a, a if moving else 0.0, vA])

    def rk4(s, h, moving):
        k1 = deriv(s, moving)
        k2 = deriv(s + 0.5 * h * k1, moving)
        k3 = deriv(s + 0.5 * h * k2, moving)
        k4 = deriv(s + h * k3, moving)
        return s + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)

    s = np.array([d0, v0, 0.0, 0.0])
    t = 0.0
    T = [0.0]
    D, VA, VB, XA = [s[0]], [s[1]], [s[2]], [s[3]]
    moving = False
    guard = 0
    while s[0] > Lr and guard < 4000000:
        guard += 1
        target = Lr if moving else 1.0
        h = dt
        ns = rk4(s, h, moving)
        if ns[0] <= target:  # 事件：二分收缩步长精确落在 target 上
            lo, hi = 0.0, h
            for _ in range(80):
                mid = 0.5 * (lo + hi)
                if rk4(s, mid, moving)[0] > target:
                    lo = mid
                else:
                    hi = mid
            h = hi
            ns = rk4(s, h, moving)
            ns[0] = target
        s = ns
        t += h
        T.append(t)
        D.append(s[0])
        VA.append(s[1])
        VB.append(s[2])
        XA.append(s[3])
        if not moving and s[0] <= 1.0 + 1e-15:
            moving = True
    return (np.array(T), np.array(D), np.array(VA), np.array(VB), np.array(XA))


def sample(traj, n, ks, Ls, Lr, v1):
    """按均匀时间采 n 点，产出与 probe 同构的列。"""
    T, D, VA, VB, XA = traj
    Fs, g, _ = make_phys(ks, Ls, Lr)
    tq = np.linspace(0.0, T[-1], n)
    d = np.interp(tq, T, D)
    vA = np.interp(tq, T, VA)
    vB = np.interp(tq, T, VB)
    d[0], d[-1] = D[0], D[-1]
    d = np.minimum.accumulate(d)  # 保证严格不增（与 JS 一致）
    fs = np.array([Fs(x) for x in d])
    fc = 1.0 / d ** 2
    aA = fc - 1.0 - fs
    return {
        "u": np.linspace(0, 1, n), "d": d, "vA": vA, "vB": vB,
        "aA": aA, "Fs": fs, "Fc": fc, "v1": np.full(n, v1),
    }


# ----------------------------------------------------------------- 断言评估
HELPERS = {
    "abs": np.abs, "min": np.min, "max": np.max, "argmin": np.argmin, "argmax": np.argmax,
    "sqrt": np.sqrt, "diff": np.diff, "len": len, "all": np.all, "any": np.any,
    "sum": np.sum, "mean": np.mean, "isfinite": np.isfinite, "sign": np.sign,
}
HELPERS.update(SPEC.get("constants", {}))


def check(series_by_case, verbose=True):
    npass, rows = 0, []
    for inv in SPEC["invariants"]:
        ns = dict(HELPERS)
        ns.update(series_by_case[inv["case"]])
        val = bool(np.all(eval(inv["expr"], {"__builtins__": {}}, ns)))
        rep = np.round(np.asarray(eval(inv["report"], {"__builtins__": {}}, ns), dtype=float), 5)
        rows.append((inv["id"], val, rep))
        npass += val
        if verbose:
            print("  %s [%-18s] %s = %s" % ("OK " if val else "FAIL", inv["id"], inv["report"], rep))
    return npass, rows


def margins(series_by_case):
    """几条最吃紧的断言的余量（越大越稳）。"""
    c1 = series_by_case["c1"]
    ia, ib = int(np.argmin(c1["vA"])), int(np.argmax(c1["vA"]))
    c2 = series_by_case["c2"]
    return {
        "|d@vmax-0.5|": abs(c1["d"][ib] - 0.5),          # 容差 0.02
        "|aA@vmax|": abs(c1["aA"][ib]),                   # 容差 0.12
        "|aA@vmin|": abs(c1["aA"][ia]),                   # 容差 0.12
        "|Fs@vmax-3|": abs(c1["Fs"][ib] - 3.0),           # 容差 0.35
        "vmax-vend": c1["vA"][ib] - c1["vA"][-1],         # 必须 > 0，越大越稳
        "vmax-vmin": c1["vA"][ib] - c1["vA"][ia],
        # 陷阱②：d0 太大则起点速度 v0 反而是全程最大，argmax(vA) 会落到样本 0
        "vmax-v0(c1)": c1["vA"][ib] - c1["vA"][0],
        "vmax-v0(c2)": c2["vA"][int(np.argmax(c2["vA"]))] - c2["vA"][0],
        # d=0.5 附近的采样步长：最近样本离 0.5 最坏也只差半步，这是"对齐类"断言的上界
        "half-step@0.5": 0.5 * max(abs(c1["d"][ib + 1] - c1["d"][ib]),
                                   abs(c1["d"][ib] - c1["d"][ib - 1])),
    }


# ----------------------------------------------------------------- 参数搜索
def build(ks, Lr, d0, n=401, dt=4.0e-4):
    Ls = 0.5 + 3.0 / ks                       # (i)
    _, _, J = make_phys(ks, Ls, Lr)
    v1 = math.sqrt(J(Lr) / 2.0)               # (iv)
    tr1 = simulate(ks, Ls, Lr, d0, v1, dt)
    tr2 = simulate(ks, Ls, Lr, d0, 2.0 * v1, dt)
    return Ls, v1, {"c1": sample(tr1, n, ks, Ls, Lr, v1),
                    "c2": sample(tr2, n, ks, Ls, Lr, v1)}, tr1, tr2


def search():
    best = None
    print("── 参数网格搜索（k_s >= 16 由 (ii) 强制；L_r > d2 由 (iii) 强制）")
    print("  %6s %7s %6s %7s | %8s %8s %8s %8s %8s %8s" %
          ("k_s", "L_s", "L_r", "d0", "pass", "d@vmax", "aA@vmax", "Fs@vmax", "vmax-vend", "vmax-v0"))
    for ks in (18.0, 20.0, 24.0, 26.0, 30.0, 36.0, 44.0):
        Ls = 0.5 + 3.0 / ks
        d2 = second_zero(ks)
        for frac in (0.05, 0.15, 0.30, 0.50):
            Lr = d2 + frac * (0.5 - d2)
            if Lr <= d2 or Lr >= 0.5:
                continue
            for d0 in (1.25, 1.35, 1.45, 1.6, 1.8, 2.2):
                try:
                    Lsx, v1, ser, _, _ = build(ks, Lr, d0, dt=1e-3)
                except Exception:
                    continue
                npass, _ = check(ser, verbose=False)
                mg = margins(ser)
                # 归一化余量：每条离容差还有多远（0=刚好卡线，1=完美）
                # 对齐类断言取"最坏情况"（半步），不吃采样点碰巧对齐的运气
                hs = mg["half-step@0.5"]
                score = min(1 - hs / 0.02,                      # c1-d-at-vmax
                            1 - abs(ks - 16.0) * hs / 0.12,     # c1-a-zero-at-extrema（g'(0.5)=ks-16）
                            1 - ks * hs / 0.35,                 # c1-Fs-at-vmax
                            min(mg["vmax-vend"] / 0.04, 1.0),
                            min(mg["vmax-vmin"] / 0.10, 1.0),
                            min(mg["vmax-v0(c1)"] / 0.04, 1.0),
                            min(mg["vmax-v0(c2)"] / 0.04, 1.0))
                print("  %6.1f %7.4f %6.4f %7.2f | %4d/16  %8.5f %8.4f %8.4f %8.4f %8.4f  score=%.3f" %
                      (ks, Lsx, Lr, d0, npass, hs, abs(ks - 16.0) * hs,
                       ks * hs, mg["vmax-vend"], mg["vmax-v0(c1)"], score))
                if npass == 16 and (best is None or score > best[0]):
                    best = (score, ks, Lsx, Lr, d0, v1)
    return best


def refine(best):
    """网格给出的最优点是一片高原（k_s 26~30、L_r 0.35~0.42、d0 1.25~1.35 都能 16/16）。
    在这片高原里按优先序挑第一个 score>=0.70 的"圆整"参数组：常数好看、
    L_r 离第二零点 d2 也远（碰撞瞬间 a_A 明显 <0，不至于卡在拐点上）。"""
    print("\n── 圆整候选复核（按优先序，取第一个 16/16 且 score>=0.70 的）")
    cands = [(30.0, 0.40, 1.30), (28.0, 0.36, 1.30), (26.0, 0.37, 1.30),
             (30.0, 0.35, 1.30), (30.0, 0.36, 1.35)]
    pick = None
    for ks, Lr, d0 in cands:
        d2 = second_zero(ks)
        if Lr <= d2:
            continue
        Lsx, v1, ser, _, _ = build(ks, Lr, d0, dt=1e-3)
        npass, _ = check(ser, verbose=False)
        mg = margins(ser)
        hs = mg["half-step@0.5"]
        sc = min(1 - hs / 0.02, 1 - abs(ks - 16.0) * hs / 0.12, 1 - ks * hs / 0.35,
                 min(mg["vmax-vend"] / 0.04, 1.0), min(mg["vmax-vmin"] / 0.10, 1.0),
                 min(mg["vmax-v0(c1)"] / 0.04, 1.0), min(mg["vmax-v0(c2)"] / 0.04, 1.0))
        _, g, _ = make_phys(ks, Lsx, Lr)
        print("  k_s=%.1f L_s=%.6f L_r=%.4f d0=%.2f -> %d/16  v1=%.6f  L_r-d2=%.4f  "
              "a_A(碰)=%.3f  vmax-vend=%.4f  score=%.3f%s" %
              (ks, Lsx, Lr, d0, npass, v1, Lr - d2, g(Lr), mg["vmax-vend"], sc,
               "   <= 选中" if (pick is None and npass == 16 and sc >= 0.70) else ""))
        if pick is None and npass == 16 and sc >= 0.70:
            pick = (sc, ks, Lsx, Lr, d0, v1)
    return pick or best


def main():
    best = search()
    assert best is not None, "网格里没有全通的参数"
    best = refine(best)
    score, ks, Ls, Lr, d0, _ = best
    print("\n── 定稿：k_s=%.4f  L_s=%.6f  L_r=%.6f  d0=%.4f  (score=%.3f)" %
          (ks, Ls, Lr, d0, score))

    # 用细步长重算一遍作为最终交付参数
    Ls, v1, ser, tr1, tr2 = build(ks, Lr, d0, n=SPEC["sample_points"], dt=4e-4)
    d2 = second_zero(ks)
    v0_1 = math.sqrt(v1 ** 2 + 2 * (d0 + 1 / d0 - 2))
    v0_2 = math.sqrt((2 * v1) ** 2 + 2 * (d0 + 1 / d0 - 2))

    print("\n══ 最终自洽参数（无量纲）══")
    print("  k_s            = %.10f" % ks)
    print("  L_s            = %.10f      (= 0.5 + 3/k_s，由 F2 定)" % Ls)
    print("  L_r            = %.10f      (> d2 = %.10f，由 (iii) 定)" % (Lr, d2))
    print("  弹簧自然长度   = L_s - L_r = %.10f" % (Ls - Lr))
    print("  d0             = %.10f" % d0)
    print("  v1             = %.12f      (= sqrt(J(L_r)/2))" % v1)
    print("  v0 情形①      = %.12f" % v0_1)
    print("  v0 情形②      = %.12f" % v0_2)
    print("  g 的极小点 d*  = %.6f  (<0.5 保证 (1/2,L_s) 上 a_A>0)" % (2.0 / ks) ** (1 / 3.0))
    print("  g 的第二零点   = %.6f  (< L_r，保证碰撞前 a_A 一直 <0)" % d2)
    print("  T 情形①      = %.6f    T 情形② = %.6f" % (tr1[0][-1], tr2[0][-1]))
    print("  A 总位移 ①   = %.6f    ② = %.6f" % (tr1[4][-1], tr2[4][-1]))
    print("  x_B 位移 ①   = %.6f" % (tr1[4][-1] + (tr1[1][-1] - tr1[1][0])))

    print("\n══ 校验表（关键位置）══")
    _, g, J = make_phys(ks, Ls, Lr)
    print("  %8s %10s %10s %10s %10s" % ("d", "F_s", "F_c", "a_A", "J(d)"))
    for d in (d0, 1.5, 1.0, 0.8, Ls, 0.6, 0.5, 0.45, 0.4, Lr):
        Fs, _, _ = make_phys(ks, Ls, Lr)
        print("  %8.4f %10.4f %10.4f %10.4f %10.5f" % (d, Fs(d), 1 / d ** 2, g(d), J(d)))

    print("\n══ 端点核对 ══")
    for cid, exp in (("c1", (2.0, 1.0, 1.0)), ("c2", (1 + math.sqrt(3), math.sqrt(3) - 1, 2.0))):
        s = ser[cid]
        print("  %s: vA(end)/v1 = %.6f (应 %.6f)   vB(end)/v1 = %.6f (应 %.6f)   "
              "vA-vB = %.6f v1 (应 %.1f)" %
              (cid, s["vA"][-1] / v1, exp[0], s["vB"][-1] / v1, exp[1],
               (s["vA"][-1] - s["vB"][-1]) / v1, exp[2]))

    print("\n══ 逐条 invariant（用与 verify.py 相同的表达式求值）══")
    npass, _ = check(ser)
    print("  => %d/%d" % (npass, len(SPEC["invariants"])))

    print("\n══ 采样分辨率（决定 argmax/argmin 落点精度）══")
    d1c = ser["c1"]["d"]
    i5 = int(np.argmin(np.abs(d1c - 0.5)))
    i1 = int(np.argmin(np.abs(d1c - 1.0)))
    print("  d=0.5 附近相邻样本 Δd = %.6f ；最近样本 |d-0.5| = %.6f" %
          (abs(d1c[i5 + 1] - d1c[i5]), abs(d1c[i5] - 0.5)))
    print("  d=1.0 附近相邻样本 Δd = %.6f ；最近样本 |d-1.0| = %.6f" %
          (abs(d1c[i1 + 1] - d1c[i1]), abs(d1c[i1] - 1.0)))

    print("\n══ 交给 JS 的常数 ══")
    print("  KS = %.10f;  LS = %.10f;  LR = %.10f;  D0 = %.10f;  V1 = %.12f;" %
          (ks, Ls, Lr, d0, v1))


if __name__ == "__main__":
    main()
