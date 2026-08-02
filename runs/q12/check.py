#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
q12 独立核算脚本（不依赖 harness，只用来自己把物理算干净）

题：斜面顶端由静止释放带遮光片的滑块，先后经过 A、B 两个光电门，
    由两次遮光时间反算动摩擦因数 mu。

正向生成（已知 mu_true=0.30） -> 反算（用题目公式） -> 必须回到 0.30，且与 theta 无关。

用法： ../../.venv/bin/python check.py
"""
import math

G       = 9.8         # m/s^2
MU_TRUE = 0.30        # 真值，用来正向造数据
D       = 0.00525     # 遮光片宽度 5.25 mm -> m
SA      = 0.25        # 释放点到 A 门，m
L       = 0.50        # A、B 门间距，m
STOT    = 0.80        # u=1 的行程终点（>= SA+L，滑块已越过 B 门）

CASES = [("th20", 20.0), ("th30", 30.0), ("th45", 45.0), ("th60", 60.0)]


def model(theta_deg):
    """与 q12.js 里的 model() 一一对应的实现。"""
    th = math.radians(theta_deg)
    st, ct = math.sin(th), math.cos(th)
    a = G * (st - MU_TRUE * ct)          # 牛二：a = g(sin - mu cos)
    vA = math.sqrt(2 * a * SA)           # v^2 = 2 a s
    vB = math.sqrt(2 * a * (SA + L))
    dtA = D / vA                         # 秒
    dtB = D / vB
    mu = st / ct - (vB * vB - vA * vA) / (2 * G * L * ct)   # 反算式
    return dict(theta=theta_deg, a=a, vA=vA, vB=vB,
                dtA_ms=dtA * 1e3, dtB_ms=dtB * 1e3, mu=mu)


def s_of_u(u):
    """u 线性映射到过程时间 t = u*T，s = 1/2 a t^2  =>  s = STOT * u^2"""
    return STOT * u * u


def main():
    print("常量: g=%.1f  mu_true=%.2f  d=%.5f m  sA=%.2f m  L=%.2f m  s_total=%.2f m"
          % (G, MU_TRUE, D, SA, L, STOT))
    print()
    hdr = ("case", "theta", "a", "vA", "vB", "dtA(ms)", "dtB(ms)", "mu_calc", "dtA*vA", "dtB*vB")
    print("%-6s %6s %9s %9s %9s %10s %10s %10s %11s %11s" % hdr)
    print("-" * 100)
    rows = []
    for cid, th in CASES:
        m = model(th)
        rows.append((cid, m))
        print("%-6s %6.1f %9.5f %9.5f %9.5f %10.4f %10.4f %10.6f %11.8f %11.8f"
              % (cid, th, m["a"], m["vA"], m["vB"], m["dtA_ms"], m["dtB_ms"], m["mu"],
                 m["dtA_ms"] * 1e-3 * m["vA"], m["dtB_ms"] * 1e-3 * m["vB"]))
    print()

    # ---- 逐条复核 spec.invariants ----
    N = 401
    us = [i / (N - 1) for i in range(N)]
    ss = [s_of_u(u) for u in us]
    fails = []

    def chk(tag, cond, extra=""):
        print("  %s %-18s %s" % ("OK " if cond else "FAIL", tag, extra))
        if not cond:
            fails.append(tag)

    print("断言复核:")
    for cid, m in rows:
        chk(cid + "-mu", abs(m["mu"] - MU_TRUE) <= 0.004, "mu=%.10f" % m["mu"])
    for cid, m in rows:
        if cid in ("th30", "th60"):
            th = math.radians(m["theta"])
            want = G * (math.sin(th) - MU_TRUE * math.cos(th))
            chk(cid + "-accel", abs(m["a"] - want) <= 0.01, "a=%.6f want=%.6f" % (m["a"], want))
    m30 = dict(rows)["th30"]
    chk("th30-vA", abs(m30["vA"] ** 2 - 2 * m30["a"] * SA) <= 0.01,
        "vA^2=%.8f 2aSA=%.8f" % (m30["vA"] ** 2, 2 * m30["a"] * SA))
    chk("th30-vB", abs(m30["vB"] ** 2 - m30["vA"] ** 2 - 2 * m30["a"] * L) <= 0.01,
        "dv2=%.8f 2aL=%.8f" % (m30["vB"] ** 2 - m30["vA"] ** 2, 2 * m30["a"] * L))
    m45 = dict(rows)["th45"]
    chk("th45-gateA-width", abs(m45["dtA_ms"] * 1e-3 * m45["vA"] - D) <= 2e-5,
        "%.10f vs %.5f" % (m45["dtA_ms"] * 1e-3 * m45["vA"], D))
    chk("th45-gateB-width", abs(m45["dtB_ms"] * 1e-3 * m45["vB"] - D) <= 2e-5,
        "%.10f vs %.5f" % (m45["dtB_ms"] * 1e-3 * m45["vB"], D))
    chk("th45-gateB-faster", m45["dtB_ms"] < m45["dtA_ms"] - 0.01,
        "dtB=%.4f < dtA=%.4f" % (m45["dtB_ms"], m45["dtA_ms"]))
    dmin = min(ss[i + 1] - ss[i] for i in range(N - 1))
    chk("th30-s-monotone", dmin >= -1e-12 and abs(ss[0]) <= 1e-9 and ss[-1] >= SA + L - 1e-6,
        "s0=%.1e s1=%.4f min_diff=%.3e" % (ss[0], ss[-1], dmin))
    m20 = dict(rows)["th20"]
    chk("th20-slides", m20["a"] > 0.05, "a=%.6f (tan20=%.4f > mu=%.2f)"
        % (m20["a"], math.tan(math.radians(20)), MU_TRUE))

    # ---- 滑不动的临界角，用来给滑块 range 定下限 ----
    th_crit = math.degrees(math.atan(MU_TRUE))
    print()
    print("临界倾角 atan(mu) = %.4f deg —— 倾角滑块下限必须 > 此值，否则 a<=0，"
          "sqrt(2as) 会出 NaN。取 min=20 deg (a=%.4f)。"
          % (th_crit, G * (math.sin(math.radians(20)) - MU_TRUE * math.cos(math.radians(20)))))

    # ---- 播放用的真实过程时长（仅供参考，动画是等 u 慢放）----
    print()
    print("真实过程时长 T = sqrt(2*s_total/a):")
    for cid, m in rows:
        print("   %s  T=%.4f s   (慢放到 2.6 s，慢放倍数 %.2fx)"
              % (cid, math.sqrt(2 * STOT / m["a"]), 2.6 / math.sqrt(2 * STOT / m["a"])))

    print()
    print("RESULT:", "ALL OK" if not fails else "FAILED " + ",".join(fails))


if __name__ == "__main__":
    main()
