#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时脚本：数值反解安培力系数 k，使得 v(0)=1, v(t_total=1)=2。
用二分法在 ODE m*dv/dt = m*g*sinθ - k*v 上调 k，与 spec.reference 的算法一致。
"""
import math

m = 1.0
g = 10.0
theta = math.pi / 6.0
v0_ = 1.0
t_total = 1.0
target_v = 2.0 * v0_

N = 2000
dt = t_total / N


def simulate(k):
    v = v0_
    d = 0.0
    impulse = 0.0
    Q = 0.0
    for i in range(N):
        F = k * v
        a = g * math.sin(theta) - F / m
        v_new = v + a * dt
        v_mid = 0.5 * (v + v_new)
        d += v_mid * dt
        impulse += k * v_mid * dt
        Q += k * v_mid * v_mid * dt
        v = v_new
    return v, d, impulse, Q


k_lo, k_hi = 0.0, 100.0
for _ in range(60):
    k_mid = 0.5 * (k_lo + k_hi)
    v_end, _, _, _ = simulate(k_mid)
    if v_end > target_v:
        k_lo = k_mid
    else:
        k_hi = k_mid
k = 0.5 * (k_lo + k_hi)

v_end, d_end, impulse_end, Q_end = simulate(k)

print("k =", k)
print("v_end =", v_end, "(target 2.0)")
print("d_end =", d_end)
print("impulse_end =", impulse_end)
print("expected impulse F2 = m*g*t*sinθ - m*v =", m * g * t_total * math.sin(theta) - m * v0_)
print("Q_end =", Q_end)
print("Ek0 =", 0.5 * m * v0_ ** 2, "Ek_end =", 0.5 * m * v_end ** 2)
print("dEk expected 1.5*m*v0^2 =", 1.5 * m * v0_ ** 2)
print("1.5*v0*t (F4 comparison, should NOT equal d_end) =", 1.5 * v0_ * t_total)
print("gravity work m*g*sinθ*d =", m * g * math.sin(theta) * d_end)
print("Q_end < gravity work ?", Q_end < m * g * math.sin(theta) * d_end)
