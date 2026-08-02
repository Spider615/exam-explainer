#!/usr/bin/env python3
import numpy as np

# Reference implementation from spec
t_E = 10.0
t_F = 20.0
t_M = 40.0
t_N = 53.0
m = 2.0

def y_of_t(t):
    if t <= t_F:
        return 4.0 * t - 26.0
    elif t <= t_M:
        dt = t - t_F
        return 54.0 + 4.0 * dt - 0.15 * dt * dt
    else:
        return -2.0 * t + 140.0

def v_of_t(t):
    if t <= t_F:
        return 4.0
    elif t <= t_M:
        return 4.0 - 0.3 * (t - t_F)
    else:
        return -2.0

def probe(u):
    t = t_E + u * (t_N - t_E)
    y = y_of_t(t)
    v = v_of_t(t)
    p = m * v

    h = 1e-4
    t_minus = t - h
    t_plus = t + h
    if t_minus < t_E:
        t_minus = t_E
    if t_plus > t_N:
        t_plus = t_N

    if t_plus > t_minus:
        a = (v_of_t(t_plus) - v_of_t(t_minus)) / (t_plus - t_minus)
    else:
        a = 0.0

    return {
        "u": u,
        "t": t,
        "y": y,
        "v": v,
        "a": a,
        "p": p
    }

# Test key points
print("Testing key points:")
print("u=0 (E point):", probe(0.0))
print("u=10/43 (F point t=20):", probe(10/43))
print("u=30/43 (M point t=40):", probe(30/43))
print("u=1 (N point t=53):", probe(1.0))

# Verify invariants
print("\nVerifying invariants:")
# EF speed
ef_vals = [probe(u) for u in np.linspace(0.5/43, 9.5/43, 10)]
ef_v = [v['v'] for v in ef_vals]
print("EF mean v:", np.mean(ef_v), "expected 4.0, diff:", abs(np.mean(ef_v)-4.0))

# MN speed
mn_vals = [probe(u) for u in np.linspace(30.5/43, 52.5/43, 10)]
mn_v = [v['v'] for v in mn_vals]
print("MN mean v:", np.mean(mn_v), "expected -2.0, diff:", abs(np.mean(mn_v)+2.0))

# FM speed monotonic decrease
fm_vals = [probe(u) for u in np.linspace(10/43, 30/43, 20)]
fm_v = [v['v'] for v in fm_vals]
fm_diff = np.diff(fm_v)
print("FM max diff v:", np.max(fm_diff), "should be <=0")

# FM acceleration negative
fm_a = [v['a'] for v in fm_vals[1:-1]]
print("FM max a:", np.max(fm_a), "should be <=-0.05")

# MN acceleration zero
mn_a = [v['a'] for v in mn_vals[1:-1]]
print("MN mean a:", np.mean(mn_a), "should be ~0")

# F point velocity
f_point = probe(10/43)
print("F point v:", f_point['v'], "expected 4.0, diff:", abs(f_point['v']-4.0))

# N point velocity
n_point = probe(1.0)
print("N point v:", n_point['v'], "expected -2.0, diff:", abs(n_point['v']+2.0))

# Momentum change FN
fn_p_change = abs(n_point['p'] - f_point['p'])
print("FN momentum change:", fn_p_change, "expected 12.0, diff:", abs(fn_p_change-12.0))

# p = m*v consistency
all_vals = [probe(u) for u in np.linspace(0, 1, 100)]
max_p_diff = max([abs(v['p'] - 2*v['v']) for v in all_vals])
print("Max p - 2v diff:", max_p_diff, "should be <=1e-6")
