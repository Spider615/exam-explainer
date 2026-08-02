#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数值求解 q16-gen2 的自洽自由参数。纯 Python 浮点 RK4（避免每步 numpy 分配开销）。

采用 spec.physics.equations 的字面符号约定（对 A 是 +Fs，对 B 是 -Fs），
与 c1-aA/aB-self-consistency 两条断言完全一致（这两条断言的表达式就是这个
约定，禁止自行改动力的形式，见 spec.physics.note）。

代价：可证明在此约定 + c1-dist-monotonic（s 单调不增）+ S 点 Fc=1,Fs=0 下，
aA(t)=Fc(s(t))+Fs(s(t))-1 对 t 单调不减，且仅在 t1 处过零，故 t1 之后严格为正，
vA(t) 在 (t1,t_end] 上严格单调递增 —— argmax(vA) 必然是轨迹终点（碰撞点），
不可能存在 t2 那种"内部速度极大值"。更进一步，即使不考虑 argmax，
given_facts F2 本身（t2 时刻 aA=0 且 Fs=3qE）在这个符号约定下代数不自洽：
aA=0 需要 Fc+Fs=1，但 Fs=3 时 Fc≥0 决定了 aA=Fc+Fs-1≥2，不可能为 0。
所以 c1-t2-aA-zero 与 c1-t2-Fs 在满足 c1-aA-self-consistency 的前提下
数学上不可兼得（与自由参数取值无关，纯代数事实）。

本脚本把自由参数（L0, k_spring, Lr）调至让其余 20 条全部满足、
只让这 2 条力所不及的失败：Lr=0.5 使 t2-Fc/t2-dist 精确命中，
L0=1.0（弹簧原长恰好=r1，S 点 Fs 精确为 0）+ k_spring 打靶命中 vA(碰撞)=2。
"""
import math

k_spring = 12.0
L0 = 1.0
s0 = 3.0


def Fc(s):
    return 1.0 / (s * s)


def Fs(s):
    return k_spring * (L0 - s) if s < L0 else 0.0


def deriv(xA, xB, vA, vB):
    s = xB - xA
    fc = Fc(s)
    fs = Fs(s)
    aA = fc + fs - 1.0
    if vB < -1e-9:
        aB = 1.0 - fc - fs
    else:
        drive = -1.0 - fc - fs
        aB = (drive + 2.0) if drive < -2.0 else 0.0
    return vA, vB, aA, aB


def rk4_step(xA, xB, vA, vB, dt):
    k1 = deriv(xA, xB, vA, vB)
    k2 = deriv(xA + 0.5*dt*k1[0], xB + 0.5*dt*k1[1], vA + 0.5*dt*k1[2], vB + 0.5*dt*k1[3])
    k3 = deriv(xA + 0.5*dt*k2[0], xB + 0.5*dt*k2[1], vA + 0.5*dt*k2[2], vB + 0.5*dt*k2[3])
    k4 = deriv(xA + dt*k3[0], xB + dt*k3[1], vA + dt*k3[2], vB + dt*k3[3])
    nxA = xA + dt/6.0*(k1[0]+2*k2[0]+2*k3[0]+k4[0])
    nxB = xB + dt/6.0*(k1[1]+2*k2[1]+2*k3[1]+k4[1])
    nvA = vA + dt/6.0*(k1[2]+2*k2[2]+2*k3[2]+k4[2])
    nvB = vB + dt/6.0*(k1[3]+2*k2[3]+2*k3[3]+k4[3])
    return nxA, nxB, nvA, nvB


def run_to_s(v0, s_target, s0_=s0, dt=1e-4, t_max=30.0):
    xA, xB, vA, vB = 0.0, s0_, v0, 0.0
    t = 0.0
    while t < t_max:
        s = xB - xA
        if s <= s_target:
            return t, xA, xB, vA, vB
        pxA, pxB, pvA, pvB, pt = xA, xB, vA, vB, t
        xA, xB, vA, vB = rk4_step(xA, xB, vA, vB, dt)
        t += dt
        if (xB - xA) <= s_target:
            # 二分细化，精确定位穿越时刻
            lo, hi = 0.0, dt
            axA, axB, avA, avB = pxA, pxB, pvA, pvB
            for _ in range(40):
                mid = 0.5*(lo+hi)
                mxA, mxB, mvA, mvB = rk4_step(pxA, pxB, pvA, pvB, mid)
                if (mxB - mxA) > s_target:
                    lo = mid
                else:
                    hi = mid
            mxA, mxB, mvA, mvB = rk4_step(pxA, pxB, pvA, pvB, hi)
            return pt + hi, mxA, mxB, mvA, mvB
    raise RuntimeError("never reached s=%s (v0=%s) t_max exceeded, s=%s" % (s_target, v0, xB - xA))


def vA_at_S(v0):
    t, xA, xB, vA, vB = run_to_s(v0, 1.0)
    return vA


def bisect(f, lo, hi, iters=50):
    flo = f(lo)
    for _ in range(iters):
        mid = 0.5*(lo+hi)
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo = mid
            flo = fm
        else:
            hi = mid
    return 0.5*(lo+hi)


print("solving v0 (c1): vA(s=1)=1.0")
v0_c1 = bisect(lambda v0: vA_at_S(v0) - 1.0, 1.7, 5.0)
print("  v0_c1 =", v0_c1, "check:", vA_at_S(v0_c1))

print("solving v0' (c2): vA(s=1)=2.0")
v0_c2 = bisect(lambda v0: vA_at_S(v0) - 2.0, 2.2, 3.5)
print("  v0_c2 =", v0_c2, "check:", vA_at_S(v0_c2))

# Lr 固定为 0.5：这样碰撞点 s 精确=0.5，Fc 精确=1/0.5^2=4，直接命中
# c1-t2-dist 与 c1-t2-Fc（argmax(vA) 在此约定下必然是轨迹终点，见上方证明）。
Lr = 0.5
print("\nLr fixed =", Lr, "(so Fc(Lr)=%.4f, s(Lr)=%.4f hit t2-Fc/t2-dist exactly)" % (Fc(Lr), Lr))

print("solving k_spring so that c1 collision (s=Lr) has vA = 2.0")


def vA_end_c1(k):
    global k_spring
    k_spring = k
    t, xA, xB, vA, vB = run_to_s(v0_c1, Lr)
    return vA


k_spring = bisect(lambda k: vA_end_c1(k) - 2.0, 3.0, 100.0)
print("  k_spring =", k_spring, "check vA=", vA_end_c1(k_spring))

t1c, xA1, xB1, vA1c, vB1c = run_to_s(v0_c1, 1.0)
tEc, xAe, xBe, vAe, vBe = run_to_s(v0_c1, Lr)
print("\n--- case c1 summary ---")
print("t1 (S point): t=%.4f vA=%.4f vB=%.4f s=%.4f Fc=%.4f Fs=%.4f" % (t1c, vA1c, vB1c, xB1-xA1, Fc(xB1-xA1), Fs(xB1-xA1)))
print("collision (= argmax(vA), see proof above): t=%.4f vA=%.4f vB=%.4f s=%.4f Fc=%.4f Fs=%.4f aA=%.4f"
      % (tEc, vAe, vBe, xBe-xAe, Fc(xBe-xAe), Fs(xBe-xAe), Fc(xBe-xAe)+Fs(xBe-xAe)-1.0))
print("dK S->end = %.4f (expect 2.0)" % (0.5*(vAe**2+vBe**2) - 0.5*(vA1c**2+vB1c**2)))
print("  -> c1-t2-aA-zero wants aA~0 (got %.2f) and c1-t2-Fs wants Fs~3 (got %.2f):"
      " both provably unreachable together with Fc~4 given aA=Fc+Fs-1, see module docstring."
      % (Fc(xBe-xAe)+Fs(xBe-xAe)-1.0, Fs(xBe-xAe)))

print("\n--- case c2 summary (same Lr) ---")
t1c2, xA1b, xB1b, vA1c2, vB1c2 = run_to_s(v0_c2, 1.0)
tEc2, xAeb, xBeb, vAe2, vBe2 = run_to_s(v0_c2, Lr)
print("S point:   t=%.4f vA=%.4f vB=%.4f" % (t1c2, vA1c2, vB1c2))
print("collision: t=%.4f vA=%.4f vB=%.4f  (expect vA=1+sqrt3=%.4f vB=1-sqrt3=%.4f)" %
      (tEc2, vAe2, vBe2, 1+3**0.5, 1-3**0.5))
print("dK S->end = %.4f (expect 2.0)" % (0.5*(vAe2**2+vBe2**2) - 0.5*(vA1c2**2+vB1c2**2)))
