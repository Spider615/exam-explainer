#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py <scene-id>  —— 场景验收门禁（只读，不得修改）

四层：
  L1 静态门禁   文件结构 / viewBox / 非法内容 / id 引用完整性 / 必填披露
  L2 装载       无头 Chrome 加载页面，运行时必须成功注册并跑出首帧
  L3 探针       逐 case 采样 probe(u,caseId)，检查纯度、无副作用、数值有限
  L4 断言       用 spec.invariants 里的物理断言检查采样序列

最后一行输出 VERDICT: PASS / FAIL
"""
import sys, os, re, json, subprocess, shutil, math
import numpy as np

HARNESS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HARNESS)
SPECS = os.path.join(ROOT, "specs")

CHROME = next((p for p in [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome") or "", shutil.which("chromium") or "",
] if p and os.path.exists(p)), None)

FAILS = []
def bad(layer, code, msg):
    FAILS.append((layer, code, msg))
    print("  ✗ [%s/%s] %s" % (layer, code, msg))
def ok(layer, msg):
    print("  ✓ [%s] %s" % (layer, msg))


# ---------------------------------------------------------------- L1 静态
def layer1(sid, spec, fig, js):
    print("── L1 静态门禁")

    m = re.search(r'<figure[^>]*\bdata-scene="([^"]+)"', fig)
    if not m:
        bad("L1", "no-figure", "找不到 <figure data-scene=...>")
    elif m.group(1) != sid:
        bad("L1", "scene-id", 'data-scene="%s" 与 id "%s" 不一致' % (m.group(1), sid))
    else:
        ok("L1", "figure 根元素与 data-scene 正确")

    vb = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"', fig)
    if not vb:
        bad("L1", "viewbox", "svg 缺少 viewBox=\"0 0 W H\"")
    elif abs(float(vb.group(1)) - 560) > 0.01:
        bad("L1", "viewbox", "viewBox 宽度必须为 560，实际 %s" % vb.group(1))
    else:
        ok("L1", "viewBox 宽度 560（高 %s）" % vb.group(2))

    # 注意：url(#ak) 这类内部 marker 引用是合法的，只禁外部 url；xmlns 里的 http 也合法
    scan = re.sub(r'xmlns(:\w+)?="[^"]*"', "", fig)
    n0 = len(FAILS)
    for pat, code, desc in [
        (r'<script', "illegal", "figure 内不得有 <script>"),
        (r'<style', "illegal", "figure 内不得有 <style>"),
        (r'https?://|src="//', "illegal", "figure 内不得有外链"),
        (r'url\(\s*[\'"]?(?!#)', "illegal", "figure 内不得引用外部资源 url()"),
        (r'<animate|<set\b', "smil", "不得使用 SMIL 动画元素"),
        (r'#[0-9a-fA-F]{6}\b|rgb\(|hsl\(', "color", "不得写死颜色，用 CSS 变量"),
    ]:
        if re.search(pat, scan):
            bad("L1", code, desc + "（命中 /%s/）" % pat)
    if len(FAILS) == n0:
        ok("L1", "figure 无非法内容")

    for pat, code in [(r'\brequestAnimationFrame\b', "raf"),
                      (r'\bsetTimeout\b', "timer"),
                      (r'\bsetInterval\b', "timer")]:
        if re.search(pat, js):
            bad("L1", code, "js 不得使用 %s 驱动物理" % pat.strip("\\b"))

    if not re.search(r'window\.Scenes\s*\[\s*[\'"]%s[\'"]\s*\]\s*=' % re.escape(sid), js):
        bad("L1", "register", 'js 必须以 window.Scenes["%s"] = function(fig){…} 注册' % sid)
    else:
        ok("L1", "场景已正确注册到 window.Scenes")

    for kw in ("let ", "const ", "=>", "class "):
        if kw in js:
            bad("L1", "es5", "js 出现非 ES5 写法：%r" % kw)

    # id 引用完整性 —— 历史最高频缺陷
    have = set(re.findall(r'\bid="([^"]+)"', fig))
    # 只认完整的字面量 querySelector('#xxx')；'#q16-' + n 这种拼接不在静态检查范围内
    want = set(re.findall(r'querySelector\(\s*[\'"]#([A-Za-z0-9_\-]+)[\'"]\s*\)', js))
    miss = sorted(w for w in want if w not in have)
    if miss:
        bad("L1", "dangling-id", "js 引用了 figure 中不存在的 id：%s" % ", ".join(miss))
    else:
        ok("L1", "id 引用完整（%d 个）" % len(want))

    stray = sorted(h for h in have if not h.startswith(sid + "-"))
    if stray:
        bad("L1", "id-prefix", "figure 中 id 未加 '%s-' 前缀：%s" % (sid, ", ".join(stray)))

    for d in spec.get("disclosures", []):
        if d["must_contain"] not in fig:
            bad("L1", "disclosure", "缺少必填披露文字：%r（%s）" % (d["must_contain"], d["why"]))
    if spec.get("disclosures"):
        if not any(f[1] == "disclosure" for f in FAILS):
            ok("L1", "必填披露齐全（%d 条）" % len(spec["disclosures"]))

    # 文本溢出粗查
    for tm in re.finditer(r'<text[^>]*\bx="(-?\d+(?:\.\d+)?)"[^>]*>([^<]*)</text>', fig):
        x, txt = float(tm.group(1)), tm.group(2)
        w = sum(11.5 if ord(c) > 0x2E80 else 6.6 for c in txt)
        if x + w > 552:
            bad("L1", "overflow", "文本可能超出 viewBox：x=%g 估宽=%.0f 内容=%r" % (x, w, txt[:28]))


# ---------------------------------------------------------------- L2/L3 运行
PROBE_JS = r"""
function __runProbe(){
  var out = {ok:false, errors:[], render:[], scenes:[], series:{}, notes:[]};
  function rec(e){ out.errors.push(String(e && e.stack || e)); }
  window.onerror = function(m,s,l,c,e){ rec(m + " @" + l + ":" + c); };
  var _ce = console.error; console.error = function(){ rec([].join.call(arguments," ")); _ce.apply(console, arguments); };
  try {
    var SID = "__SID__", SPEC = __SPEC__;
    out.scenes = Object.keys(window.Scenes || {});
    var fig = document.querySelector('figure[data-scene="' + SID + '"]');
    if (!fig) { out.errors.push("DOM 里找不到 figure[data-scene=" + SID + "]"); throw 0; }
    var api = (window.__api || {})[SID];
    if (!api) { out.errors.push("运行时未能构造该场景（工厂抛错或契约不符）"); throw 0; }
    ["step","reset","probe"].forEach(function(k){
      if (typeof api[k] !== "function") out.errors.push("api." + k + " 不是函数");
    });
    if (out.errors.length) throw 0;

    var svg = fig.querySelector("svg");

    // --- 渲染压力：跑 451 帧 step()，抓异常与脏数值 ---
    try {
      api.reset(); api.step(0);
      for (var t = 0; t <= 18.0001; t += 0.04) api.step(t);
    } catch (e) { rec("step() 抛异常: " + e); }
    var dom = svg.outerHTML;
    ["NaN","Infinity","undefined","null"].forEach(function(w){
      var n = (dom.match(new RegExp(w, "g")) || []).length;
      if (n) out.errors.push("渲染后 SVG 中出现 " + w + " ×" + n);
    });

    /* --- L3.5 渲染覆盖 ---
       断言只跑 probe，看不见渲染。历史教训：把 translate(cx,cy) rotate(θ)
       误写成 rotate(θ cx cy)，整组元素飞出画布，四层门禁 13/13 全绿放行。
       这里补上：每个带 id 的 SVG 元素，必须在某一采样时刻真的画在 viewBox 内。
       只查「位置」不查「可见性」—— opacity=0 的元素 getBBox 依然有效，
       所以合法隐藏的结论框不会被误伤，而「整组飞出画布」是全时段的，必然被抓。*/
    try {
      api.reset();
      var vb = svg.viewBox.baseVal;
      var els = svg.querySelectorAll("[id]");
      var ids = [], everOK = {}, everDrawn = {}, snaps = [];
      for (var q0 = 0; q0 < els.length; q0++) ids.push(els[q0].getAttribute("id"));
      /* 注意：不能用 el.getCTM() —— 它含 viewBox 缩放，返回的是渲染像素坐标，
         拿去和 viewBox 数值比会把右下方的元素全部误判出界。
         正确做法是经 svg 根的 screenCTM 求逆，换回 viewBox 用户单位。 */
      for (var tq = 0; tq <= 20.0001; tq += 0.5) {
        api.step(tq);
        snaps.push(svg.innerHTML);
        var rootM = svg.getScreenCTM();
        if (!rootM) continue;
        var invM = rootM.inverse();
        for (var q1 = 0; q1 < els.length; q1++) {
          var idq = ids[q1];
          if (everOK[idq]) continue;
          var bb, mm;
          try { bb = els[q1].getBBox(); mm = els[q1].getScreenCTM(); } catch (err0) { continue; }
          if (!mm) continue;
          if (bb.width <= 0 && bb.height <= 0) continue;   /* 退化元素不判位置 */
          everDrawn[idq] = true;
          mm = invM.multiply(mm);                          /* → viewBox 用户单位 */
          var cxq = bb.x + bb.width / 2, cyq = bb.y + bb.height / 2;
          var XQ = mm.a * cxq + mm.c * cyq + mm.e;
          var YQ = mm.b * cxq + mm.d * cyq + mm.f;
          if (XQ >= vb.x - 2 && XQ <= vb.x + vb.width + 2 &&
              YQ >= vb.y - 2 && YQ <= vb.y + vb.height + 2)
            everOK[idq] = true;
        }
      }
      var off = [], dead = [];
      for (var q2 = 0; q2 < ids.length; q2++) {
        if (!everDrawn[ids[q2]]) dead.push(ids[q2]);
        else if (!everOK[ids[q2]]) off.push(ids[q2]);
      }
      if (off.length)
        out.render.push("这些元素在全部 41 个采样时刻都画在 viewBox 之外（画面上看不到）：" + off.join(", "));
      var moved = false;
      for (var q3 = 1; q3 < snaps.length; q3++) if (snaps[q3] !== snaps[0]) { moved = true; break; }
      if (!moved)
        out.render.push("采样了 " + snaps.length + " 个不同时刻，SVG 内容完全没有变化——动画没有动");
      out.notes.push("渲染覆盖：" + ids.length + " 个带 id 元素，" +
                     Object.keys(everOK).length + " 个曾正常出现在画面内" +
                     (dead.length ? "，" + dead.length + " 个全程无几何(" + dead.slice(0, 6).join(",") + ")" : ""));
    } catch (errR) { out.render.push("渲染覆盖检查自身失败: " + errR); }

    /* --- L5 版面：文字不许压文字 ---
       断言只看 probe 的数值，L3.5 只看元素在不在画布内，谁都不看**画成什么样**。
       实测 31 个场景有 14 个存在文字互压（读数行压说明、标签压标题），
       而 ⑤ 的沙箱 agent 是**盲写坐标**的 —— 字号写在 CSS 里，它算不出自己
       那行中文有多宽，只能靠这一层告诉它。

       三条判据来自全库标定，不是拍脑袋：

       1. **逐帧比，绝不取跨帧包络。** 挂在运动物体上的标签，其轨迹包络必然
          互相交叠，但任一时刻都不真的压在一起。实测 q7「M」×「N」包络重叠
          65.6px、逐帧 0；q14「圆心」×「v₂」包络 13.4px、逐帧 0。用包络判
          会把一整类合法写法冤枉掉。

       2. **判据是重叠矩形的短边，不是面积比。** 面积比对「长串薄重叠」系统性
          高估（225×2.2 的虚碰也能顶到 17%），永远分不开两个峰。按短边重排，
          全库分布是：16 个干净场景 ≤2.1px，两个边缘案例 3.5/3.6px，13 个
          确凿缺陷 ≥7.4px —— 3.6 到 7.4 之间那道 3.8px 的空档是整个数据集
          最宽的间隙，阈值取 5 落在正中，对字体和测量误差都留足了余量。
          下界 2.1 的成因：em 盒比字墨高约 1.9px，两行「刚好贴着」会碰盒不碰墨。

       3. **场标记不算文字。** `×` `·` 这些是用 <text> 画的底纹，本来就该被
          别的东西盖住。q4-gen3 有 31 个，占它全部 text 的大半 —— 不排除的话
          这个干净场景第一天就会被判红。*/
    try {
      api.reset();
      var L5_FAIL = 5.0, L5_WARN = 2.5;
      var MARK = {"×":1, "·":1, "⊙":1, "⊗":1, "•":1, "∙":1};
      var allT = svg.querySelectorAll("text"), tel = [], tinfo = [], nMark = 0;
      for (var a0 = 0; a0 < allT.length; a0++) {
        var s0 = (allT[a0].textContent || "").replace(/^\s+|\s+$/g, "");
        if (!s0) continue;
        if (s0.length === 1 && MARK[s0]) { nMark++; continue; }
        tel.push(allT[a0]); tinfo.push(s0.length > 34 ? s0.slice(0, 34) + "…" : s0);
      }
      /* 不用 getComputedStyle：热循环里每帧每元素调一次太慢，而契约禁止
         figure 内写 <style>，透明度只可能来自 JS 设的属性或内联样式。 */
      function vis(el) {
        var n = el, op = 1;
        while (n && n !== svg) {
          if (n.style && n.style.display === "none") return false;
          if (n.getAttribute && n.getAttribute("display") === "none") return false;
          var o = NaN;
          if (n.style && n.style.opacity !== "" && n.style.opacity != null) o = parseFloat(n.style.opacity);
          else if (n.getAttribute && n.getAttribute("opacity") !== null) o = parseFloat(n.getAttribute("opacity"));
          if (!isNaN(o)) op *= o;
          n = n.parentNode;
        }
        return op > 0.05;
      }
      var NT = tel.length, worst = {}, rootM5, inv5;
      function frame5(tv) {
        rootM5 = svg.getScreenCTM(); if (!rootM5) return;
        inv5 = rootM5.inverse();
        var bx = [];
        for (var k5 = 0; k5 < NT; k5++) {
          if (!vis(tel[k5])) { bx.push(null); continue; }
          var bb5, mm5;
          try { bb5 = tel[k5].getBBox(); mm5 = tel[k5].getScreenCTM(); } catch (e5) { bx.push(null); continue; }
          if (!mm5 || (bb5.width <= 0 && bb5.height <= 0)) { bx.push(null); continue; }
          var m5 = inv5.multiply(mm5);
          var px = [bb5.x, bb5.x + bb5.width], py = [bb5.y, bb5.y + bb5.height];
          var X0 = 1e9, X1 = -1e9, Y0 = 1e9, Y1 = -1e9;
          for (var u5 = 0; u5 < 2; u5++) for (var v5 = 0; v5 < 2; v5++) {
            var xx = m5.a * px[u5] + m5.c * py[v5] + m5.e;
            var yy = m5.b * px[u5] + m5.d * py[v5] + m5.f;
            if (xx < X0) X0 = xx; if (xx > X1) X1 = xx;
            if (yy < Y0) Y0 = yy; if (yy > Y1) Y1 = yy;
          }
          bx.push({x0: X0, x1: X1, y0: Y0, y1: Y1});
        }
        for (var i5 = 0; i5 < NT; i5++) { var A5 = bx[i5]; if (!A5) continue;
          for (var j5 = i5 + 1; j5 < NT; j5++) { var B5 = bx[j5]; if (!B5) continue;
            var w5 = Math.min(A5.x1, B5.x1) - Math.max(A5.x0, B5.x0);
            var h5 = Math.min(A5.y1, B5.y1) - Math.max(A5.y0, B5.y0);
            if (w5 <= 0 || h5 <= 0) continue;
            var d5 = w5 < h5 ? w5 : h5, key5 = i5 + "_" + j5;
            if (!worst[key5] || d5 > worst[key5].d)
              worst[key5] = {d: d5, w: w5, h: h5, t: tv, i: i5, j: j5,
                             a: [A5.x0, A5.y0, A5.x1, A5.y1],
                             b: [B5.x0, B5.y0, B5.x1, B5.y1]};
          }
        }
      }
      /* 步长 0.25：判据的量词是「∃某一帧」，欠采样会直接漏判，
         而 81 帧全量文字包围盒实测只要几毫秒，占整轮不到 1%。 */
      frame5(0);
      for (var t5 = 0; t5 <= 20.0001; t5 += 0.25) { api.step(t5); frame5(t5); }
      var lfails = [], lwarn = 0;
      for (var k6 in worst) { if (!worst.hasOwnProperty(k6)) continue;
        var r6 = worst[k6];
        if (r6.d >= L5_FAIL) {
          lfails.push("「" + tinfo[r6.i] + "」与「" + tinfo[r6.j] + "」在 t=" +
            r6.t.toFixed(2) + "s 压在一起：重叠 " + r6.w.toFixed(1) + "×" + r6.h.toFixed(1) +
            "px（短边 " + r6.d.toFixed(1) + " ≥ " + L5_FAIL + "）。前者盒 [" +
            r6.a[0].toFixed(0) + "," + r6.a[1].toFixed(0) + "]-[" + r6.a[2].toFixed(0) + "," + r6.a[3].toFixed(0) +
            "]，后者盒 [" + r6.b[0].toFixed(0) + "," + r6.b[1].toFixed(0) + "]-[" + r6.b[2].toFixed(0) + "," + r6.b[3].toFixed(0) + "]");
        } else if (r6.d >= L5_WARN) lwarn++;
      }
      lfails.sort();
      out.layout = {fails: lfails, warns: lwarn, nText: NT, nMark: nMark};
      api.reset();
    } catch (errL) { out.layout = {fails: [], warns: 0, nText: 0, nMark: 0,
                                   self: "版面检查自身失败: " + errL}; }

    // --- probe 采样 ---
    var N = SPEC.sample_points || 401;
    for (var ci = 0; ci < SPEC.cases.length; ci++) {
      var cid = SPEC.cases[ci].id;
      var cols = {}; SPEC.probe_keys.forEach(function(k){ cols[k] = []; });

      // 纯度 + 无副作用
      var before = svg.outerHTML;
      var a1 = api.probe(0.37, cid), a2 = api.probe(0.37, cid);
      if (svg.outerHTML !== before) out.errors.push("[" + cid + "] probe() 修改了 DOM（必须是纯函数）");
      SPEC.probe_keys.forEach(function(k){
        if (!(k in a1)) out.errors.push("[" + cid + "] probe 返回值缺少键 " + k);
        else if (a1[k] !== a2[k]) out.errors.push("[" + cid + "] probe 不纯：同一 u 两次调用 " + k + " 不同（" + a1[k] + " vs " + a2[k] + "）");
      });

      var nbad = 0;
      for (var i = 0; i < N; i++) {
        var u = i / (N - 1);
        var r;
        try { r = api.probe(u, cid); }
        catch (e) { out.errors.push("[" + cid + "] probe(" + u.toFixed(3) + ") 抛异常: " + e); break; }
        for (var ki = 0; ki < SPEC.probe_keys.length; ki++) {
          var k = SPEC.probe_keys[ki], v = r ? r[k] : undefined;
          if (typeof v !== "number" || !isFinite(v)) { nbad++; v = null; }
          cols[k].push(v);
        }
      }
      if (nbad) out.errors.push("[" + cid + "] probe 返回了 " + nbad + " 个非有限数值");
      out.series[cid] = cols;
    }
    out.ok = out.errors.length === 0 && out.render.length === 0;
  } catch (e) { if (e) rec(e); }
  document.getElementById("TESTOUT").textContent = "@@" + JSON.stringify(out) + "@@";
}
/* 必须等运行时 boot 完（它也挂在 DOMContentLoaded 上，且注册在前），
   同时保证 <pre id="TESTOUT"> 已经存在 */
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", __runProbe);
else __runProbe();
"""


def run_browser(sid, spec, fig, js, workdir):
    print("── L2 装载 + L3 探针")
    if not CHROME:
        bad("L2", "no-chrome", "找不到 Chrome/Chromium")
        return None
    tpl = open(os.path.join(HARNESS, "page.tpl.html"), encoding="utf-8").read()
    rt = open(os.path.join(HARNESS, "_runtime.js"), encoding="utf-8").read()
    probe = PROBE_JS.replace("__SID__", sid).replace("__SPEC__", json.dumps(spec, ensure_ascii=False))
    page = (tpl.replace("<!--FIGURE-->", fig)
               .replace("<!--SCENEJS-->", js)
               .replace("<!--RUNTIME-->", rt)
               .replace("<!--PROBE-->", probe))
    pth = os.path.join(workdir, "_probe.html")
    open(pth, "w", encoding="utf-8").write(page)

    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--virtual-time-budget=8000", "--dump-dom", "file://" + pth],
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        bad("L2", "timeout", "无头浏览器超时（>180s），probe 可能死循环")
        return None

    m = re.search(r"@@(\{.*\})@@", r.stdout, re.S)
    if not m:
        bad("L2", "no-output", "探针没有产出结果（页面可能在早期就崩了）")
        print("   stderr:", (r.stderr or "")[-500:])
        return None
    data = json.loads(m.group(1))

    if sid not in data.get("scenes", []):
        bad("L2", "not-registered", "window.Scenes 中没有 '%s'（实际注册：%s）"
            % (sid, data.get("scenes")))
    for e in data.get("errors", []):
        bad("L3", "runtime", e)
    if not data.get("errors"):
        ok("L2/L3", "装载成功、451 帧 step() 无异常、probe 纯净且数值有限")
    for e in data.get("render", []):
        bad("L3.5", "render", e)
    for n in data.get("notes", []):
        print("  · %s" % n)
    if not data.get("render"):
        ok("L3.5", "渲染覆盖：所有带 id 元素都曾画在 viewBox 内，且画面随时间变化")

    # --- L5 版面 ---
    lay = data.get("layout")
    if lay is None:
        bad("L5", "no-layout", "版面检查没有产出结果")
    elif lay.get("self"):
        bad("L5", "self", lay["self"])
    else:
        for e in lay.get("fails", []):
            bad("L5", "overlap", e)
        if not lay.get("fails"):
            ok("L5", "版面：%d 条文字两两不压（另有 %d 个场标记不计）"
               % (lay.get("nText", 0), lay.get("nMark", 0)))
        # 黄灯只报数不判红：em 盒比字墨高约 1.9px，两行「刚好贴着」会碰盒不碰墨。
        # 说出来是为了让人知道它们存在，也知道**不用管** —— 不说的话，
        # 下一个看到这份报告的人会去修一批根本看不出问题的东西
        if lay.get("warns"):
            print("  · 版面：另有 %d 对文字贴着 em 盒边缘（短边 2.5~5px），不判红"
                  % lay["warns"])
    return data


# ---------------------------------------------------------------- L4 断言
def layer4(spec, data):
    print("── L4 物理断言")
    if not data or not data.get("series"):
        bad("L4", "no-series", "没有可用的采样数据，断言全部跳过")
        return

    helpers = {
        "abs": np.abs, "min": np.min, "max": np.max, "argmin": np.argmin, "argmax": np.argmax,
        "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan,
        "exp": np.exp, "log": np.log, "pi": np.pi, "diff": np.diff, "where": np.where,
        "all": np.all, "any": np.any, "sum": np.sum, "mean": np.mean, "std": np.std,
        "isfinite": np.isfinite, "sign": np.sign, "interp": np.interp, "len": len,
        "clip": np.clip, "sort": np.sort, "cumsum": np.cumsum, "nonzero": np.nonzero,
    }
    helpers.update(spec.get("constants", {}))

    npass = 0
    for inv in spec["invariants"]:
        cid = inv["case"]
        cols = data["series"].get(cid)
        if cols is None:
            bad("L4", inv["id"], "case '%s' 没有采样数据" % cid); continue
        ns = dict(helpers)
        for k, v in cols.items():
            ns[k] = np.array([np.nan if x is None else float(x) for x in v], dtype=float)
        try:
            val = bool(np.all(eval(inv["expr"], {"__builtins__": {}}, ns)))
        except Exception as e:
            bad("L4", inv["id"], "断言表达式求值失败：%s（%s）" % (e, inv["expr"])); continue
        rep = ""
        if inv.get("report"):
            try:
                rv = eval(inv["report"], {"__builtins__": {}}, ns)
                rep = "  实测 %s = %s" % (inv["report"], np.round(np.asarray(rv, dtype=float), 4))
            except Exception as e:
                rep = "  (report 求值失败: %s)" % e
        if val:
            npass += 1
            print("  ✓ [L4/%s] %s" % (inv["id"], inv["why"]))
        else:
            bad("L4", inv["id"], "%s\n      断言 %s 不成立%s" % (inv["why"], inv["expr"], rep))
    print("  L4: %d/%d 条断言通过" % (npass, len(spec["invariants"])))


# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) < 2:
        print("用法: verify.py <scene-id>"); sys.exit(2)
    sid = sys.argv[1]
    workdir = os.getcwd()
    spec = json.load(open(os.path.join(SPECS, sid + ".spec.json"), encoding="utf-8"))

    print("═══ verify %s ═══" % sid)
    fp = os.path.join(workdir, sid + ".figure.html")
    jp = os.path.join(workdir, sid + ".js")
    for p in (fp, jp):
        if not os.path.exists(p):
            print("  ✗ [L0/missing] 缺少文件 %s" % os.path.basename(p))
            print("VERDICT: FAIL"); sys.exit(1)
    fig = open(fp, encoding="utf-8").read()
    js = open(jp, encoding="utf-8").read()

    layer1(sid, spec, fig, js)
    data = run_browser(sid, spec, fig, js, workdir)
    layer4(spec, data)

    # 门禁自己记录每次调用 —— 迭代轮次由此统计，不依赖被测方自觉
    import time, hashlib
    logp = os.path.join(workdir, "_verify_log.jsonl")
    nround = sum(1 for _ in open(logp, encoding="utf-8")) + 1 if os.path.exists(logp) else 1
    entry = {
        "round": nround, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "scene": sid,
        "verdict": "FAIL" if FAILS else "PASS",
        "n_fail": len(FAILS),
        "fails": [{"layer": l, "code": c, "msg": m.split("\n")[0][:220]} for l, c, m in FAILS],
        "sha_fig": hashlib.sha256(fig.encode()).hexdigest()[:12],
        "sha_js": hashlib.sha256(js.encode()).hexdigest()[:12],
        "bytes_js": len(js.encode()),
    }
    with open(logp, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print("─" * 52)
    print("第 %d 轮验收" % nround)
    if FAILS:
        by = {}
        for l, c, _ in FAILS: by[l] = by.get(l, 0) + 1
        print("失败 %d 条：%s" % (len(FAILS), ", ".join("%s×%d" % kv for kv in sorted(by.items()))))
        print("VERDICT: FAIL"); sys.exit(1)
    print("全部通过：静态门禁 + 装载 + 探针 + 版面 + %d 条物理断言" % len(spec["invariants"]))
    print("VERDICT: PASS"); sys.exit(0)


if __name__ == "__main__":
    main()
