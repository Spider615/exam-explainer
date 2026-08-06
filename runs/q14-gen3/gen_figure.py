#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时生成脚本：拼装 q14-gen3.figure.html。不是产出物，跑完可删。"""
import json, math

SID = "q14-gen3"
spec = json.load(open("../../specs/q14-gen3.spec.json", encoding="utf-8"))
D = spec["disclosures"]
D1, D2, D3, D4 = D[0]["must_contain"], D[1]["must_contain"], D[2]["must_contain"], D[3]["must_contain"]

def W(id_prefixed):
    assert id_prefixed.startswith(SID + "-"), id_prefixed
    return id_prefixed

def check_line(x, txt):
    w = sum(11.5 if ord(c) > 0x2E80 else 6.6 for c in txt)
    if x + w > 552:
        raise SystemExit("OVERFLOW x=%s w=%.1f txt=%r" % (x, w, txt))
    return txt

lines = []
def fmt(v):
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)

def T(x, y, cls, txt, id_=None, extra=""):
    check_line(x, txt)
    idattr = (' id="%s"' % id_) if id_ else ""
    clsattr = (' class="%s"' % cls) if cls else ""
    lines.append('<text%s%s x="%s" y="%s"%s>%s</text>' % (idattr, clsattr, fmt(x), fmt(y), extra, txt))

# ---------------------------------------------------------------- geometry (python, 仅用于初始占位坐标)
PI = math.pi
O = (150.0, 195.0)
SCALE1 = 62.0
sq_x, sq_y, sq_w = O[0]-SCALE1, O[1]-SCALE1, SCALE1*2
circR = SCALE1
circR2 = SCALE1*math.sqrt(2)
oa0 = (O[0]+SCALE1*1.0, O[1]-0.0)  # u=0: phi=0,l=1

G = (70.0, 538.0)
theta = PI/6
dirX, dirY = math.cos(theta), -math.sin(theta)
INCLEN = 230.0
Tpt = (G[0]+INCLEN*dirX, G[1]+INCLEN*dirY)
d0 = 200.0
cd0 = (G[0]+d0*dirX, G[1]+d0*dirY)
perpX, perpY = -dirY, dirX

def pt(p):
    return "%.2f" % p

lines.append('<figure data-scene="%s"><svg viewBox="0 0 560 560" role="img" aria-label="正方形金属框中心O绕轴旋转的OA棒（part1，安培力周期变化）与倾斜导轨上撤力后下滑的CD棒（part2，安培力与摩擦力共同作用下的减速滑动）动画">' % SID)

# ---------- header disclosures ----------
T(16, 16, "u", D1)
T(16, 32, "u", D4 + "　　" + D2)
T(16, 48, "u", D3)
lines.append('<line class="sh" x1="16" y1="60" x2="544" y2="60"/>')

# ---------- panel 1 heading ----------
T(16, 76, "u", check_line(16, "case c1：part(1)——OA匀速转动，安培力随 l 周期变化"))

# ---------- panel 1 geometry (square + O + reference circles) ----------
lines.append('<rect class="sh" x="%.2f" y="%.2f" width="%.2f" height="%.2f"/>' % (sq_x, sq_y, sq_w, sq_w))
lines.append('<circle class="sh" cx="%.2f" cy="%.2f" r="%.2f"/>' % (O[0], O[1], circR))
lines.append('<circle class="sh" cx="%.2f" cy="%.2f" r="%.2f"/>' % (O[0], O[1], circR2))
T(O[0]-4, O[1]-circR-6, "u", "L")
T(O[0]-8, O[1]-circR2-6, "u", "√2L")
lines.append('<circle class="fk" cx="%.2f" cy="%.2f" r="2.6"/>' % (O[0], O[1]))
T(O[0]+4, O[1]-6, None, "O")

lines.append('<line id="%s" class="sa" marker-end="url(#aa)" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
             % (W(SID+"-oaLine"), O[0], O[1], oa0[0], oa0[1]))
lines.append('<circle id="%s" class="fr" cx="%.2f" cy="%.2f" r="4"/>' % (W(SID+"-contactP"), oa0[0], oa0[1]))
T(oa0[0]+6, oa0[1]-6, None, "A", id_=W(SID+"-lblA"))
T((O[0]+oa0[0])/2+4, (O[1]+oa0[1])/2-6, "n", "l=1.00", id_=W(SID+"-lblLgeo"))

# ---------- panel 1 numeric panel ----------
T(250, 96, "u", "数值面板（l、F 实时）")
T(250, 120, "n", "φ = 0.00 rad (0.0°)", id_=W(SID+"-c1PhiLbl"))
T(250, 140, "n", "l = 1.000 m", id_=W(SID+"-c1LLbl"))
T(250, 160, "n a", "F = 1.000 N", id_=W(SID+"-c1FLbl"))

BARX, BARW, BARBOT, BARTOP = 480.0, 28.0, 280.0, 170.0
BARH = BARBOT - BARTOP
SF = BARH/1.2
fmaxY = BARBOT - 1.0*SF
fminY = BARBOT - 0.5*SF
lines.append('<rect class="sh" x="%.2f" y="%.2f" width="%.2f" height="%.2f"/>' % (BARX, BARTOP, BARW, BARH))
lines.append('<line class="sc" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>' % (BARX-10, fmaxY, BARX+BARW+10, fmaxY))
lines.append('<line class="sc" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>' % (BARX-10, fminY, BARX+BARW+10, fminY))
T(340, fmaxY+4, "n c", "F_max=1.00N")
T(340, fminY+4, "n c", "F_min=0.50N")
lines.append('<rect id="%s" class="fa" x="%.2f" y="%.2f" width="%.2f" height="%.2f"/>'
             % (W(SID+"-c1BarF"), BARX, fmaxY, BARW, BARBOT-fmaxY))

lines.append('<line class="sh" x1="16" y1="304" x2="544" y2="304"/>')

# ---------- panel 2 heading ----------
T(16, 320, "u", check_line(16, "case c2：part(2)——锁定OA、CD下滑，电动势由CD自身运动产生"))

# ---------- panel 2 geometry ----------
lines.append('<line class="sk" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>' % (G[0], G[1], Tpt[0], Tpt[1]))
lines.append('<line class="sh" x1="40" y1="%.2f" x2="330" y2="%.2f"/>' % (G[1], G[1]))
for gx in range(50, 321, 30):
    lines.append('<line class="sh" x1="%d" y1="%.2f" x2="%d" y2="%.2f"/>' % (gx, G[1], gx-8, G[1]+12))
lines.append('<path class="sh" d="M %.2f %.2f A 28 28 0 0 0 %.2f %.2f"/>'
             % (G[0]+28, G[1], G[0]+28*dirX, G[1]+28*dirY))
T(G[0]+30, G[1]-10, "u", "θ=30°")

lines.append('<line id="%s" class="sa" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
             % (W(SID+"-cdBar"), cd0[0]-26*perpX, cd0[1]-26*perpY, cd0[0]+26*perpX, cd0[1]+26*perpY))
lines.append('<circle id="%s" class="fk" cx="%.2f" cy="%.2f" r="3"/>' % (W(SID+"-cdDot"), cd0[0], cd0[1]))

lines.append('<line id="%s" class="sk" marker-end="url(#ak)" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
             % (W(SID+"-arrowG"), cd0[0], cd0[1], cd0[0]-51.25*dirX, cd0[1]+51.25*dirY))
lines.append('<line id="%s" class="sa" marker-end="url(#aa)" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
             % (W(SID+"-arrowF"), cd0[0]-6*perpX, cd0[1]-6*perpY, cd0[0]-6*perpX+60*dirX, cd0[1]-6*perpY+60*dirY))
lines.append('<line id="%s" class="sr" marker-end="url(#ar)" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
             % (W(SID+"-arrowFric"), cd0[0]+6*perpX, cd0[1]+6*perpY, cd0[0]+6*perpX+33.75*dirX, cd0[1]+6*perpY+33.75*dirY))

T(220, Tpt[1]-8, "u", "C")
T(cd0[0]-40, cd0[1]+30, "u", "D")

# ---------- panel 2 legend + numeric panel ----------
lines.append('<rect class="fa" x="335" y="350" width="9" height="9"/>')
T(350, 358, "u", "安培力 F（沿导轨向上）")
lines.append('<rect class="fr" x="335" y="368" width="9" height="9"/>')
T(350, 376, "u", "摩擦力 f（滑动摩擦，恒定）")
lines.append('<rect class="fk" x="335" y="386" width="9" height="9"/>')
T(350, 394, "u", "mg sinθ=0.75N（沿导轨向下）")

T(330, 420, "n", "t = 0.000 s", id_=W(SID+"-c2TLbl"))
T(330, 438, "n a", "v = 1.000 m/s", id_=W(SID+"-c2VLbl"))
T(330, 456, "n", "a = -3.333 m/s²", id_=W(SID+"-c2ALbl"))
T(330, 474, "n", "x = 0.000 m", id_=W(SID+"-c2XLbl"))
T(330, 492, "n a", "F = 1.000 N", id_=W(SID+"-c2FLbl"))
T(330, 510, "n r", "f = 0.250 N", id_=W(SID+"-c2FricLbl"))
T(330, 530, "u", check_line(330, "v0=1.00→v_eq=0.50 m/s，τ=0.15s"))

lines.append('</svg>')
lines.append('<figcaption>左：case c1——OA棒以恒定角速度ω绕O转动，与正方形金属框接触点的有效切割长度 l 在 L 与 √2L 之间周期变化，导致安培力 F 随之周期变化，最大最小值比为 2。右：case c2——锁定OA后推动CD下滑并撤去推力，此时安培力恰等于 F_max，CD在重力分量、安培力与滑动摩擦力共同作用下减速，速度指数趋近新的动态平衡 v_eq，由撤力瞬间加速度大小 a 反推出动摩擦因数 μ = a/(2g cosθ)。</figcaption></figure>')

html = "\n".join(lines) + "\n"
open("q14-gen3.figure.html", "w", encoding="utf-8").write(html)
print("written, bytes:", len(html.encode()))
