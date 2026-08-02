/* q16t · 匀强电场中两带电滑块的相互作用
 *
 * 无量纲化（与 spec 一致）：qE = 1，m = 1，长度单位 d1 = sqrt(kq/E)。
 * 自由参数 L_s / k_s / L_r / d0 / 初速度由 solve.py 解出（推导见 NOTES.md，
 * 与 runs/q16 共用同一套自洽解——两者的 spec 内容完全相同）：
 *   k_s = 30，L_s = 0.5 + 3/k_s = 0.6，L_r = 0.4，d0 = 1.3
 *   v1 = sqrt(J(L_r)/2) = sqrt(0.15)，J(d) = 积分 g 从 d 到 1
 * 下面 JS 里 v1 与两个初速度都由这些常数现算，轨迹是真的用 RK4 跑出来的。
 */
window.Scenes["q16t"] = function (fig) {
  var svg = fig.querySelector('svg');

  /* ================= 物理 ================= */
  var KS = 30.0;   /* 弹簧劲度 k_s */
  var LS = 0.6;    /* 弹簧原长 L_s（k_s(L_s-0.5)=3 由 F2 定） */
  var LR = 0.4;    /* 细杆长 L_r（须大于 g 的第二零点 1/3） */
  var D0 = 1.3;    /* 初始间距 d0 */

  function fSpring(d) { return d < LS ? KS * (LS - d) : 0; }
  function fCoul(d) { return 1 / (d * d); }
  /* a_A = 1 + 1/d^2 - 2 - F_s ；B 起动后 a_B 与之同式 */
  function accel(d) { return fCoul(d) - 1 - fSpring(d); }
  /* J(d) = ∫_d^1 a(x) dx 的闭式，用来定 v1 */
  function Jint(d) {
    var b = 1 / d + d - 2;
    if (d < LS) { b -= 0.5 * KS * (LS - d) * (LS - d); }
    return b;
  }

  var V1 = Math.sqrt(Jint(LR) / 2);          /* F3 给出 J(L_r) = 2 v1^2 */
  var VAPP = 2 * (D0 + 1 / D0 - 2);          /* d>=1 段能量项：v(d0)^2 = v(1)^2 + VAPP */

  /* ---- RK4 时域积分：状态 [d, vA, vB, xA] ---- */
  function deriv(s, moving, out) {
    var a = accel(s[0]);
    out[0] = -(s[1] + s[2]);
    out[1] = a;
    out[2] = moving ? a : 0;
    out[3] = s[1];
    return out;
  }
  function rk4(s, h, moving, out) {
    var k1 = [0, 0, 0, 0], k2 = [0, 0, 0, 0], k3 = [0, 0, 0, 0], k4 = [0, 0, 0, 0];
    var tmp = [0, 0, 0, 0], i;
    deriv(s, moving, k1);
    for (i = 0; i < 4; i++) { tmp[i] = s[i] + 0.5 * h * k1[i]; }
    deriv(tmp, moving, k2);
    for (i = 0; i < 4; i++) { tmp[i] = s[i] + 0.5 * h * k2[i]; }
    deriv(tmp, moving, k3);
    for (i = 0; i < 4; i++) { tmp[i] = s[i] + h * k3[i]; }
    deriv(tmp, moving, k4);
    for (i = 0; i < 4; i++) {
      out[i] = s[i] + (h / 6) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]);
    }
    return out;
  }

  /* vS = A 经过 S（d = 1）时的速度。d>1 段 B 被静摩擦锁住。 */
  function simulate(vS) {
    var v0 = Math.sqrt(vS * vS + VAPP);
    var dt = 4e-4;
    var s = [D0, v0, 0, 0], ns = [0, 0, 0, 0], tst = [0, 0, 0, 0];
    var T = [0], D = [D0], VA = [v0], VB = [0], XA = [0];
    var t = 0, moving = false, guard = 0, target, h, lo, hi, mid, k;
    while (s[0] > LR && guard < 200000) {
      guard++;
      target = moving ? LR : 1.0;
      h = dt;
      rk4(s, h, moving, ns);
      if (ns[0] <= target) {                    /* 事件：二分收缩步长，精确落到 target */
        lo = 0; hi = h;
        for (k = 0; k < 60; k++) {
          mid = 0.5 * (lo + hi);
          if (rk4(s, mid, moving, tst)[0] > target) { lo = mid; } else { hi = mid; }
        }
        h = hi;
        rk4(s, h, moving, ns);
        ns[0] = target;
      }
      if (!(h > 0)) { break; }
      s[0] = ns[0]; s[1] = ns[1]; s[2] = ns[2]; s[3] = ns[3];
      t += h;
      T.push(t); D.push(s[0]); VA.push(s[1]); VB.push(s[2]); XA.push(s[3]);
      if (!moving && s[0] <= 1.0) { moving = true; }
    }
    return { t: T, d: D, vA: VA, vB: VB, xA: XA, T: t };
  }

  var TR1 = simulate(V1);          /* 情形①：过 S 时 v1 */
  var TR2 = simulate(2 * V1);      /* 情形②：过 S 时 2v1 */

  function traj(cid) { return cid === 'c2' ? TR2 : TR1; }

  /* 按归一化进度 u 取状态（u=0 起点 d0，u=1 细杆碰 B） */
  function stateAt(tr, u) {
    var n = tr.t.length - 1;
    var uu = u < 0 ? 0 : (u > 1 ? 1 : u);
    var tq = uu * tr.T, lo = 0, hi = n, mid, den, w;
    if (!(tq > 0)) { return { t: 0, d: tr.d[0], vA: tr.vA[0], vB: tr.vB[0], xA: tr.xA[0] }; }
    if (tq >= tr.T) { return { t: tr.T, d: tr.d[n], vA: tr.vA[n], vB: tr.vB[n], xA: tr.xA[n] }; }
    while (hi - lo > 1) {
      mid = (lo + hi) >> 1;
      if (tr.t[mid] <= tq) { lo = mid; } else { hi = mid; }
    }
    den = tr.t[hi] - tr.t[lo];
    w = den > 0 ? (tq - tr.t[lo]) / den : 0;
    return {
      t: tq,
      d: tr.d[lo] + w * (tr.d[hi] - tr.d[lo]),
      vA: tr.vA[lo] + w * (tr.vA[hi] - tr.vA[lo]),
      vB: tr.vB[lo] + w * (tr.vB[hi] - tr.vB[lo]),
      xA: tr.xA[lo] + w * (tr.xA[hi] - tr.xA[lo])
    };
  }

  /* d 首次降到 dv 的时刻（用来标出 a=0 的两个时刻，以及位置 S） */
  function atD(tr, dv) {
    var i, w;
    for (i = 1; i < tr.d.length; i++) {
      if (tr.d[i] <= dv) {
        w = (tr.d[i - 1] - tr.d[i]) > 0 ? (tr.d[i - 1] - dv) / (tr.d[i - 1] - tr.d[i]) : 0;
        return { t: tr.t[i - 1] + w * (tr.t[i] - tr.t[i - 1]),
                 xA: tr.xA[i - 1] + w * (tr.xA[i] - tr.xA[i - 1]) };
      }
    }
    return { t: tr.T, xA: tr.xA[tr.xA.length - 1] };
  }

  /* ================= 画布几何 ================= */
  /* X0 = 物理 x=0（A 右端起点）的像素位置，SC = 每单位长度像素，FSC = 每单位力像素。
     力矢量锚在两个滑块的「外侧」边缘：这样 d 最小时（0.4）两个库仑力箭头之间
     仍有 SC*L_r + 2*BW - 2*FSC*(1/L_r^2) = 42 + 60 - 87.5 ≈ 14px 的余量，不会打架。 */
  var X0 = 90, SC = 105, BW = 30, ROD = 138, FSC = 7;
  var PXL = 358, PXW = 186, TAX = 1.6, PYB = 252, PYH = 208, VAX = 1.15;
  function pxT(t) { return PXL + (t / TAX) * PXW; }
  function pxV(v) { return PYB - (v / VAX) * PYH; }

  /* ================= DOM ================= */
  var elCase = svg.querySelector('#q16t-caselabel');
  var elBlockA = svg.querySelector('#q16t-blockA');
  var elLabA = svg.querySelector('#q16t-labA');
  var elLabAq = svg.querySelector('#q16t-labAq');
  var elBlockB = svg.querySelector('#q16t-blockB');
  var elLabB = svg.querySelector('#q16t-labB');
  var elLabBq = svg.querySelector('#q16t-labBq');
  var elRod = svg.querySelector('#q16t-rod');
  var elSpring = svg.querySelector('#q16t-spring');
  var elDarr = svg.querySelector('#q16t-darrow');
  var elSline = svg.querySelector('#q16t-sline');
  var elSlabel = svg.querySelector('#q16t-slabel');
  var elFAs = svg.querySelector('#q16t-fAs');
  var elFAf = svg.querySelector('#q16t-fAf');
  var elFAc = svg.querySelector('#q16t-fAc');
  var elFAe = svg.querySelector('#q16t-fAe');
  var elFBs = svg.querySelector('#q16t-fBs');
  var elFBf = svg.querySelector('#q16t-fBf');
  var elFBc = svg.querySelector('#q16t-fBc');
  var elFBe = svg.querySelector('#q16t-fBe');
  var elRd = svg.querySelector('#q16t-rd');
  var elRfc = svg.querySelector('#q16t-rfc');
  var elRfs = svg.querySelector('#q16t-rfs');
  var elRaa = svg.querySelector('#q16t-raa');
  var elRva = svg.querySelector('#q16t-rva');
  var elRvb = svg.querySelector('#q16t-rvb');
  var elRratio = svg.querySelector('#q16t-rratio');
  var elRt = svg.querySelector('#q16t-rt');
  var elCurveA = svg.querySelector('#q16t-curveA');
  var elCurveB = svg.querySelector('#q16t-curveB');
  var elDotA = svg.querySelector('#q16t-dotA');
  var elDotB = svg.querySelector('#q16t-dotB');
  var elMk1 = svg.querySelector('#q16t-mk1');
  var elMk2 = svg.querySelector('#q16t-mk2');
  var elMk1lab = svg.querySelector('#q16t-mk1lab');
  var elMk2lab = svg.querySelector('#q16t-mk2lab');
  var btn1 = fig.querySelector('#q16t-c1');
  var btn2 = fig.querySelector('#q16t-c2');

  /* ================= 曲线预采样 ================= */
  var CN = 240;
  function chartOf(tr) {
    var a = [], b = [], i, u, st;
    for (i = 0; i <= CN; i++) {
      u = i / CN;
      st = stateAt(tr, u);
      a.push(pxT(st.t).toFixed(2) + ',' + pxV(st.vA).toFixed(2));
      b.push(pxT(st.t).toFixed(2) + ',' + pxV(st.vB).toFixed(2));
    }
    return { a: a, b: b };
  }
  var CH1 = chartOf(TR1), CH2 = chartOf(TR2);
  var MK = {
    c1: { one: atD(TR1, 1.0), half: atD(TR1, 0.5) },
    c2: { one: atD(TR2, 1.0), half: atD(TR2, 0.5) }
  };

  /* ================= 渲染 ================= */
  function num(v) { return (isFinite(v) ? v : 0).toFixed(3); }

  function seg(el, x1, y1, x2, y2) {
    el.setAttribute('x1', x1.toFixed(2));
    el.setAttribute('y1', y1.toFixed(2));
    el.setAttribute('x2', x2.toFixed(2));
    el.setAttribute('y2', y2.toFixed(2));
  }

  /* 力矢量：从 bx 出发，dir=+1 向右，长度正比于 mag */
  function arrow(el, bx, y, dir, mag) {
    var L = FSC * mag;
    if (!(L > 1.5)) { el.setAttribute('visibility', 'hidden'); return; }
    el.setAttribute('visibility', 'visible');
    seg(el, bx, y, bx + dir * L, y);
  }

  function springPath(x1, x2, y) {
    var len = x2 - x1, i, x, amp, seg1, p;
    if (!(len > 2)) { return 'M' + x1.toFixed(2) + ' ' + y + 'L' + x2.toFixed(2) + ' ' + y; }
    amp = len > 14 ? 5 : len / 2.8;
    seg1 = len / 12;
    p = 'M' + x1.toFixed(2) + ' ' + y;
    x = x1;
    for (i = 0; i < 12; i++) {
      x += seg1;
      p += 'L' + x.toFixed(2) + ' ' + (y + (i % 2 === 0 ? -amp : amp)).toFixed(2);
    }
    return p + 'L' + x2.toFixed(2) + ' ' + y;
  }

  var cur = 'c1';

  function render(u) {
    var tr = traj(cur);
    var st = stateAt(tr, u);
    var d = st.d, vA = st.vA, vB = st.vB;
    var Fs = fSpring(d), Fc = fCoul(d), aA = accel(d);
    var xA = X0 + SC * st.xA, xB = xA + SC * d;
    var ca = xA - BW, cb = xB + BW;      /* 力矢量的锚点：两滑块的外侧边缘 */
    var P, fB, fBd, xs;

    elBlockA.setAttribute('x', (xA - BW).toFixed(2));
    elLabA.setAttribute('x', (xA - BW / 2).toFixed(2));
    elLabAq.setAttribute('x', (xA - BW / 2).toFixed(2));
    elBlockB.setAttribute('x', xB.toFixed(2));
    elLabB.setAttribute('x', (xB + BW / 2).toFixed(2));
    elLabBq.setAttribute('x', (xB + BW / 2).toFixed(2));

    seg(elRod, xA, ROD, xA + SC * LR, ROD);
    elSpring.setAttribute('d', springPath(xA + SC * LR, Math.min(xA + SC * LS, xB), ROD));
    seg(elDarr, xA, 186, xB, 186);

    /* A 上四力：电场力向右 1，库仑引力向右 Fc，滑动摩擦向左 2，弹力向左 Fs */
    arrow(elFAe, ca, 108, 1, 1);
    arrow(elFAc, ca, 95, 1, Fc);
    arrow(elFAf, ca, 82, -1, 2);
    arrow(elFAs, ca, 69, -1, Fs);

    /* B 上四力：电场力向左 1，库仑引力向左 Fc，弹力向右 Fs，摩擦力见下 */
    arrow(elFBe, cb, 108, -1, 1);
    arrow(elFBc, cb, 95, -1, Fc);
    arrow(elFBs, cb, 69, 1, Fs);
    P = 1 + Fc - Fs;                 /* B 上非摩擦力的合力，向左为正 */
    if (vB > 1e-12) { fB = 2; fBd = 1; }
    else { fB = Math.abs(P); if (fB > 2) { fB = 2; } fBd = P >= 0 ? 1 : -1; }
    arrow(elFBf, cb, 82, fBd, fB);

    /* 位置 S：A 在 d = d1 = 1 那一刻所在处 */
    xs = X0 + SC * MK[cur].one.xA;
    seg(elSline, xs, 114, xs, 158);
    elSlabel.setAttribute('x', (xs - 4).toFixed(2));

    /* 读数 */
    elRd.textContent = num(d);
    elRfc.textContent = num(Fc);
    elRfs.textContent = num(Fs);
    elRaa.textContent = num(aA);
    elRva.textContent = num(vA);
    elRvb.textContent = num(vB);
    elRratio.textContent = num(vA / V1);
    elRt.textContent = num(st.t);

    /* v–t 曲线：逐点画到当前进度 */
    var ch = cur === 'c2' ? CH2 : CH1;
    var k = Math.round((u < 0 ? 0 : (u > 1 ? 1 : u)) * CN);
    var tail = pxT(st.t).toFixed(2) + ',';
    elCurveA.setAttribute('points', ch.a.slice(0, k + 1).join(' ') + ' ' + tail + pxV(vA).toFixed(2));
    elCurveB.setAttribute('points', ch.b.slice(0, k + 1).join(' ') + ' ' + tail + pxV(vB).toFixed(2));
    elDotA.setAttribute('cx', pxT(st.t).toFixed(2));
    elDotA.setAttribute('cy', pxV(vA).toFixed(2));
    elDotB.setAttribute('cx', pxT(st.t).toFixed(2));
    elDotB.setAttribute('cy', pxV(vB).toFixed(2));
  }

  function paintCase() {
    var m = MK[cur], x1 = pxT(m.one.t), x2 = pxT(m.half.t);
    elCase.textContent = cur === 'c2'
      ? '情形② · A 过 S 时速度为 2v₁ → 碰撞时 v_A = (√3+1)v₁'
      : '情形① · A 过 S 时速度为 v₁ → 碰撞时 v_A = 2v₁、v_B = v₁';
    seg(elMk1, x1, 44, x1, PYB);
    seg(elMk2, x2, 44, x2, PYB);
    elMk1lab.setAttribute('x', (x1 - 22).toFixed(2));
    elMk2lab.setAttribute('x', (x2 - 10).toFixed(2));
    if (btn1) { btn1.setAttribute('aria-pressed', cur === 'c1' ? 'true' : 'false'); }
    if (btn2) { btn2.setAttribute('aria-pressed', cur === 'c2' ? 'true' : 'false'); }
  }

  /* ================= 时间轴（帧循环由运行时驱动） ================= */
  var HOLD0 = 0.3, HOLD1 = 1.1;
  var switchT = 0, lastT = 0;

  function step(t) {
    lastT = t;
    var tr = traj(cur);
    var span = HOLD0 + tr.T + HOLD1;
    var tt = t - switchT;
    if (!(tt > 0)) { tt = 0; }
    tt = tt - Math.floor(tt / span) * span;
    var u = tt < HOLD0 ? 0 : (tt < HOLD0 + tr.T ? (tt - HOLD0) / tr.T : 1);
    render(u);
  }

  function pick(id) {
    return function () {
      if (cur === id) { return; }
      cur = id;
      switchT = lastT;
      paintCase();
      step(lastT);
    };
  }
  if (btn1) { btn1.addEventListener('click', pick('c1')); }
  if (btn2) { btn2.addEventListener('click', pick('c2')); }

  paintCase();

  return {
    step: step,
    reset: function () {
      switchT = 0;
      lastT = 0;
      elCurveA.setAttribute('points', '');
      elCurveB.setAttribute('points', '');
      paintCase();
      render(0);
    },
    /* 纯函数：只读预计算好的轨迹，不碰 DOM、不改内部状态 */
    probe: function (u, caseId) {
      var st = stateAt(traj(caseId), u);
      return {
        u: u,
        d: st.d,
        vA: st.vA,
        vB: st.vB,
        aA: accel(st.d),
        Fs: fSpring(st.d),
        Fc: fCoul(st.d),
        v1: V1
      };
    }
  };
};
