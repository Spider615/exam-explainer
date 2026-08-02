import numpy as np

t_E, t_F, t_M, t_N = 10.0, 20.0, 40.0, 53.0
m = 2.0

def y_of_t(t):
    if t <= t_F:
        return 4.0*t - 26.0
    elif t <= t_M:
        dt = t - t_F
        return 54.0 + 4.0*dt - 0.255*dt*dt + 0.0035*dt*dt*dt
    else:
        return -2.0*t + 140.0

def v_of_t(t):
    if t <= t_F:
        return 4.0
    elif t <= t_M:
        dt = t - t_F
        return 4.0 - 0.51*dt + 0.0105*dt*dt
    else:
        return -2.0

def a_of_t(t):
    h = 1e-4
    tm = max(t-h, t_E)
    tp = min(t+h, t_N)
    if tp > tm:
        return (v_of_t(tp) - v_of_t(tm)) / (tp - tm)
    return 0.0

# check continuity
print("y(20-):", y_of_t(20.0-1e-9), "y(20+):", y_of_t(20.0+1e-9))
print("y(40-):", y_of_t(40.0-1e-9), "y(40+):", y_of_t(40.0+1e-9))
print("v(20-):", v_of_t(19.9999), "v(20+):", v_of_t(20.0001))
print("v(40-):", v_of_t(39.9999), "v(40+):", v_of_t(40.0001))
print("y(10)=",y_of_t(10), "y(20)=",y_of_t(20),"y(40)=",y_of_t(40),"y(53)=",y_of_t(53))

# peak
dts = np.linspace(0,20,20001)
ys = [54.0 + 4.0*dt - 0.255*dt*dt + 0.0035*dt**3 for dt in dts]
print("max y in FM:", max(ys), "at dt=", dts[np.argmax(ys)])

# check invariants numerically
ts = np.linspace(t_E, t_N, 401)
vs = np.array([v_of_t(t) for t in ts])
ys_ = np.array([y_of_t(t) for t in ts])
as_ = np.array([a_of_t(t) for t in ts])
ps = m*vs

def mean_in(lo,hi):
    mask = (ts>=lo)&(ts<=hi)
    return vs[mask].mean()

print("mean v in EF (10.5-19.5):", mean_in(10.5,19.5))
print("mean v in MN (40.5-52.5):", mean_in(40.5,52.5))

mask_fm = (ts>=20)&(ts<=40)
print("max diff v in FM:", np.diff(vs[mask_fm]).max())

mask_fm_int = (ts>=21)&(ts<=39)
print("max a in FM interior:", as_[mask_fm_int].max())

mask_mn = (ts>=41)&(ts<=52)
print("mean a in MN:", as_[mask_mn].mean())

print("v at t=20 (interp):", np.interp(20, ts, vs))
print("v at last point:", vs[-1])

print("p at last - p at F(interp):", abs(ps[-1] - np.interp(20, ts, ps)))
print("max abs(p - 2v):", np.max(np.abs(ps - 2*vs)))

print("max abs(y_FM_end - y_MN_start):", abs(y_of_t(40.0) - (-2.0*40.0+140.0)))
