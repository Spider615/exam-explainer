#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时脚本：核算斜面场景的旋转坐标变换，确保所有关键点落在 viewBox 0 0 560 320 内。"""
import math

PX0, PY0 = 230.0, 265.0
TH = 30.0 * math.pi / 180.0
ct, st = math.cos(TH), math.sin(TH)

def rot(lx, ly):
    X = PX0 + lx * ct - ly * st
    Y = PY0 + lx * st + ly * ct
    return X, Y

D_END = 1.6818300688291623  # from solve.py
SCALE = 80.0
X_EXIT = -20.0
X_ENTRY = X_EXIT - D_END * SCALE
X_APPROACH = X_ENTRY - 55.0
X_TOP = X_APPROACH - 15.0
RAIL = 15.0   # 半轨距
FIELD_PAD = 15.0  # 场区域比 rod 行程再画宽一点，视觉收口

print("X_TOP=%.2f X_APPROACH=%.2f X_ENTRY=%.2f X_EXIT=%.2f" % (X_TOP, X_APPROACH, X_ENTRY, X_EXIT))

pts = {
    "wedge_top": (X_TOP, 0),
    "rail_top_upper": (X_TOP, -RAIL),
    "rail_top_lower": (X_TOP, RAIL),
    "rail_bottom_upper": (X_EXIT + FIELD_PAD, -RAIL),
    "rail_bottom_lower": (X_EXIT + FIELD_PAD, RAIL),
    "field_entry_upper": (X_ENTRY, -RAIL - 6),
    "field_entry_lower": (X_ENTRY, RAIL + 6),
    "field_exit_upper": (X_EXIT + FIELD_PAD, -RAIL - 6),
    "field_exit_lower": (X_EXIT + FIELD_PAD, RAIL + 6),
    "rod_at_u0_M": (X_ENTRY, -RAIL),
    "rod_at_u0_N": (X_ENTRY, RAIL),
    "rod_at_u1_M": (X_EXIT, -RAIL),
    "rod_at_u1_N": (X_EXIT, RAIL),
    "anchor": (0, 0),
    "below_anchor_ground": (30, 0),
}
for name, (lx, ly) in pts.items():
    X, Y = rot(lx, ly)
    flag = "OK" if (0 <= X <= 560 and 0 <= Y <= 320) else "OUT OF BOUNDS"
    print("%-20s local=(%7.2f,%6.2f) -> screen=(%6.2f,%6.2f)  %s" % (name, lx, ly, X, Y, flag))

# velocity/force arrow tip extremes at rod position u=0 (v=1) and u=1 (v=2, F_amp=k*2)
VSCALE = 26.0
FSCALE = 7.0
K = 2.3787151585265196
for uname, x_rod, v, F in [("u=0", X_ENTRY, 1.0, K*1.0), ("u=1", X_EXIT, 2.0, K*2.0)]:
    vx, vy = rot(x_rod + v*VSCALE, 0)
    fx, fy = rot(x_rod - F*FSCALE, 0)
    print("%s v-arrow tip screen=(%.2f,%.2f)  F-arrow tip screen=(%.2f,%.2f)" % (uname, vx, vy, fx, fy))
