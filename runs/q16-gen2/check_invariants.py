#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 Python 复现 verify.py 的 L4 断言逻辑，对我们求得的参数做完整核验，
在写 JS 之前先在这里把 24 条 invariants 的通过情况摸清楚。
"""
import json
import numpy as np

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


def full_traj(v0, Lr, s0_=s0, dt=2e-5):
    xA, xB, vA, vB = 0.0, s0_, v0, 0.0
    t = 0.0
    ts = [t]; xAs=[xA]; xBs=[xB]; vAs=[vA]; vBs=[vB]
    while True:
        s = xB - xA
        if s <= Lr:
            break
        xA, xB, vA, vB = rk4_step(xA, xB, vA, vB, dt)
        t += dt
        ts.append(t); xAs.append(xA); xBs.append(xB); vAs.append(vA); vBs.append(vB)
    return map(np.array, (ts, xAs, xBs, vAs, vBs))


def resample(ts, xAs, xBs, vAs, vBs, N):
    T = ts[-1]
    u = np.linspace(0, 1, N)
    tt = u * T
    xA = np.interp(tt, ts, xAs)
    xB = np.interp(tt, ts, xBs)
    vA = np.interp(tt, ts, vAs)
    vB = np.interp(tt, ts, vBs)
    s = xB - xA
    fc = 1.0 / (s * s)
    fs = np.where(s < L0, k_spring * (L0 - s), 0.0)
    aA = fc + fs - 1.0
    aB = np.where(vB < -1e-6, 1.0 - fc - fs, 0.0)
    return dict(t=tt, xA=xA, xB=xB, vA=vA, vB=vB, s=s, Fc=fc, Fs=fs, aA=aA, aB=aB)


v0_c1 = 1.9148542155126713
v0_c2 = 2.581988897471616
Lr = 0.5

ts1, xAs1, xBs1, vAs1, vBs1 = full_traj(v0_c1, Lr)
ts2, xAs2, xBs2, vAs2, vBs2 = full_traj(v0_c2, Lr)

N = 401
c1 = resample(ts1, xAs1, xBs1, vAs1, vBs1, N)
c2 = resample(ts2, xAs2, xBs2, vAs2, vBs2, N)

print("c1: argmax(vA) index=%d / %d, u=%.4f, vA there=%.4f" % (np.argmax(c1['vA']), N, np.argmax(c1['vA'])/(N-1), c1['vA'][np.argmax(c1['vA'])]))
print("   s there=%.4f Fc there=%.4f Fs there=%.4f aA there=%.4f" % (c1['s'][np.argmax(c1['vA'])], c1['Fc'][np.argmax(c1['vA'])], c1['Fs'][np.argmax(c1['vA'])], c1['aA'][np.argmax(c1['vA'])]))
print("c1 vA range:", c1['vA'].min(), c1['vA'].max(), "at s=0.5 vA=", np.interp(0.5, c1['s'][::-1], c1['vA'][::-1]))
print("c1 vB range:", c1['vB'].min(), c1['vB'].max())

spec = json.load(open("/Users/jerry/Desktop/product/exam-explainer/specs/q16-gen2.spec.json", encoding="utf-8"))

helpers = {
    "abs": np.abs, "min": np.min, "max": np.max, "argmin": np.argmin, "argmax": np.argmax,
    "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan,
    "exp": np.exp, "log": np.log, "pi": np.pi, "diff": np.diff, "where": np.where,
    "all": np.all, "any": np.any, "sum": np.sum, "mean": np.mean, "std": np.std,
    "isfinite": np.isfinite, "sign": np.sign, "interp": np.interp, "len": len,
    "clip": np.clip, "sort": np.sort, "cumsum": np.cumsum, "nonzero": np.nonzero,
}
helpers.update(spec.get("constants", {}))

series = {"c1": c1, "c2": c2}
npass = 0
nfail = 0
for inv in spec["invariants"]:
    cid = inv["case"]
    cols = series[cid]
    ns = dict(helpers)
    ns.update(cols)
    try:
        val = bool(np.all(eval(inv["expr"], {"__builtins__": {}}, ns)))
    except Exception as e:
        print("  ERR [%s] %s : %s" % (inv["id"], inv["expr"], e))
        nfail += 1
        continue
    rep = ""
    if inv.get("report"):
        try:
            rv = eval(inv["report"], {"__builtins__": {}}, ns)
            rep = " 实测=%s" % np.round(np.asarray(rv, dtype=float), 4)
        except Exception as e:
            rep = " (report failed: %s)" % e
    if val:
        npass += 1
        print("  OK  [%s]" % inv["id"])
    else:
        nfail += 1
        print("  FAIL[%s] %s%s" % (inv["id"], inv["why"], rep))

print("\n%d / %d passed" % (npass, len(spec["invariants"])))
