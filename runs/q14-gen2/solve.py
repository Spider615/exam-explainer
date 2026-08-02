import math

PI = math.pi

# Segment breakpoints (physical time, R=v0=m=1)
TA = PI/2          # N->P, first pass, v=1
TC1 = TA + PI/4     # P->M, v=2 (quarter arc at speed 2 takes PI/4) -> collision 1
TP2 = TC1 + PI/2    # M->P after collision, v=-1 (quarter arc at speed 1 takes PI/2)
TC2 = TP2 + PI/3    # P-> onward v=-2 for t_d = PI/3 (given) -> collision 2

print("TA", TA, "TC1", TC1, "expect 3pi/4", 3*PI/4)
print("TP2", TP2)
print("TC2", TC2, "expect 19pi/12", 19*PI/12)


def core(u):
    uu = min(max(u, 0.0), 1.0)
    t = uu * TC2
    if t <= TA:
        vA = 1.0
        thetaA = 0 + 1*t
    elif t <= TC1:
        vA = 2.0
        thetaA = PI/2 + 2*(t-TA)
    elif t <= TP2:
        vA = -1.0
        thetaA = PI + (-1)*(t-TC1)
    else:
        vA = -2.0
        thetaA = PI/2 + (-2)*(t-TP2)

    if t <= TC1:
        vB = 0.0
        thetaB = PI
    else:
        vB = 1.0
        thetaB = PI + 1*(t-TC1)

    FA = vA*vA
    return dict(u=uu, t=t, thetaA=thetaA, thetaB=thetaB, vA=vA, vB=vB, FA=FA)


# check collision2 position match
c1 = core(1.0)
print("u=1:", c1)
print("sin diff", math.sin(c1['thetaA']) - math.sin(c1['thetaB']))
print("cos diff", math.cos(c1['thetaA']) - math.cos(c1['thetaB']))

# check elastic collision solving for mB
# m*2 = m*vA' + mB*vB' ; 4 = vA'^2 + mB*vB'^2 ; vA'=-vB'
for mB in [x/100.0 for x in range(50, 500)]:
    vBp = 2.0/(mB-1) if mB != 1 else None
    if vBp is None:
        continue
    vAp = -vBp
    lhs = vAp**2 + mB*vBp**2
    if abs(lhs - 4.0) < 1e-3:
        print("mB candidate", mB, "vAp", vAp, "vBp", vBp)

# sample across u to check max FA and monotonic thetaB
N = 401
maxFA = 0
prevThetaB = None
minDiffThetaB = 1e9
for i in range(N):
    u = i/(N-1)
    c = core(u)
    maxFA = max(maxFA, c['FA'])
    if prevThetaB is not None:
        minDiffThetaB = min(minDiffThetaB, c['thetaB']-prevThetaB)
    prevThetaB = c['thetaB']
print("maxFA", maxFA)
print("minDiffThetaB", minDiffThetaB)
