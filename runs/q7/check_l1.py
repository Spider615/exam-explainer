#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时脚本：本地模拟 verify.py 的 L1 静态检查，快速试错，不等无头浏览器。"""
import re, json

sid = "q7"
fig = open("q7.figure.html", encoding="utf-8").read()
js = open("q7.js", encoding="utf-8").read() if __import__("os").path.exists("q7.js") else ""
spec = json.load(open("/Users/jerry/Desktop/product/exam-explainer/specs/q7.spec.json", encoding="utf-8"))

fails = []

m = re.search(r'<figure[^>]*\bdata-scene="([^"]+)"', fig)
if not m or m.group(1) != sid:
    fails.append("data-scene mismatch")

vb = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"', fig)
if not vb or abs(float(vb.group(1)) - 560) > 0.01:
    fails.append("viewBox width != 560")
else:
    print("viewBox height =", vb.group(2))

scan = re.sub(r'xmlns(:\w+)?="[^"]*"', "", fig)
for pat, desc in [
    (r'<script', "script"),
    (r'<style', "style"),
    (r'https?://|src="//', "外链"),
    (r'url\(\s*[\'"]?(?!#)', "外部url()"),
    (r'<animate|<set\b', "SMIL"),
    (r'#[0-9a-fA-F]{6}\b|rgb\(|hsl\(', "写死颜色"),
]:
    if re.search(pat, scan):
        fails.append("非法内容: " + desc)

have = set(re.findall(r'\bid="([^"]+)"', fig))
want = set(re.findall(r'querySelector\(\s*[\'"]#([A-Za-z0-9_\-]+)[\'"]\s*\)', js))
miss = sorted(w for w in want if w not in have)
if miss:
    fails.append("dangling id refs: " + ", ".join(miss))

stray = sorted(h for h in have if not h.startswith(sid + "-"))
if stray:
    fails.append("id 未加前缀: " + ", ".join(stray))

for d in spec.get("disclosures", []):
    if d["must_contain"] not in fig:
        fails.append("缺少披露: " + d["must_contain"])

for tm in re.finditer(r'<text[^>]*\bx="(-?\d+(?:\.\d+)?)"[^>]*>([^<]*)</text>', fig):
    x, txt = float(tm.group(1)), tm.group(2)
    w = sum(11.5 if ord(c) > 0x2E80 else 6.6 for c in txt)
    if x + w > 552:
        fails.append("溢出: x=%g w=%.0f 内容=%r" % (x, w, txt[:40]))

for kw in ("let ", "const ", "=>", "class "):
    if kw in js:
        fails.append("非ES5: " + kw)
for pat in (r'\brequestAnimationFrame\b', r'\bsetTimeout\b', r'\bsetInterval\b'):
    if re.search(pat, js):
        fails.append("禁止的计时器: " + pat)

if not re.search(r'window\.Scenes\s*\[\s*[\'"]%s[\'"]\s*\]\s*=' % re.escape(sid), js):
    fails.append("未注册 window.Scenes")

print("id 数量:", len(have), " querySelector 引用数量:", len(want))
if fails:
    print("FAIL:")
    for f in fails:
        print(" -", f)
else:
    print("本地 L1 模拟检查全部通过")
