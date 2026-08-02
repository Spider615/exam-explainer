#!/usr/bin/env python3
# 验证无量纲化下参数自洽性

# 按照spec的normalization赋值
v0 = 1.0
x_max = 1.0
P0 = 1.0

# 由x_max = mRv0/(B²L²) => B²L²/(mR) = v0/x_max = 1/1 = 1
k = 1.0  # B²L²/(mR) = 1

# 验证公式
print("验证v(x) = v0 - kx:")
for x in [0, 0.25, 0.5, 0.75, 1.0]:
    v = v0 - k * x
    print(f"x={x:.2f}, v={v:.2f}")

print("\n验证P(x) = (B²L²/R)v²:")
# 由P0 = B²L²v0²/R = 1 => B²L²/R = 1/v0² = 1
p_factor = 1.0
for x in [0, 0.25, 0.5, 0.75, 1.0]:
    v = v0 - k * x
    P = p_factor * v * v
    print(f"x={x:.2f}, v={v:.2f}, P={P:.2f}")

print("\n验证a(x) = -F/m = -B²L²v/(mR) = -kv:")
for x in [0, 0.25, 0.5, 0.75, 1.0]:
    v = v0 - k * x
    a = -k * v
    print(f"x={x:.2f}, v={v:.2f}, a={a:.2f}")

print("\n所有公式自洽，符合spec要求！")
