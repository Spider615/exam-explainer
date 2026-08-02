/* q7 · 斜面导轨中导体杆在磁场中减速（实为加速）运动的动量与能量分析
 *
 * 物理内核与 spec.physics.reference 完全一致：
 *   m dv/dt = m g sinθ − k v，k 未知，由边界条件 v(0)=v0、v(t_total)=2v0
 *   用二分法数值反解（显式欧拉 + 中点速度做位移/冲量/焦耳热的梯形积分，
 *   N=2000 步），probe 直接按 u 取最近采样点，不重新做任何插值近似。
 */
window.Scenes["q7"] = function (fig) {
  var svg = fig.querySelector('svg');

  /* ---------------- 物理常量（国际单位制，θ、m、g 为自设值） ---------------- */
  var M = 1.0;
  var G = 10.0;
  var THETA = Math.PI / 6.0;      /* 30° */
  var V0 = 1.0;
  var T_TOTAL = 1.0;
  var TARGET_V = 2.0 * V0;
  var N = 2000;
  var DT = T_TOTAL / N;
  var GS = G * Math.sin(THETA);   /* g sinθ，重力沿斜面分量的加速度 */

  function simulate(k) {
    var v = V0, d = 0.0, impulse = 0.0, Q = 0.0, i, F, aOfv, vNew, vMid;
    var trajV = [v], trajD = [d], trajImp = [impulse], trajQ = [Q];
    for (i = 0; i < N; i++) {
      F = k * v;
      aOfv = GS - F / M;
      vNew = v + aOfv * DT;
      vMid = 0.5 * (v + vNew);
      d += vMid * DT;
      impulse += k * vMid * DT;
      Q += k * vMid * vMid * DT;
      v = vNew;
      trajV.push(v);
      trajD.push(d);
      trajImp.push(impulse);
      trajQ.push(Q);
    }
    return { v: trajV, d: trajD, imp: trajImp, Q: trajQ };
  }

  /* 二分反解 k，使 v(t_total) = 2 v0（与 spec.reference 相同算法） */
  var kLo = 0.0, kHi = 100.0, kMid, traj, vEnd, it;
  for (it = 0; it < 60; it++) {
    kMid = 0.5 * (kLo + kHi);
    traj = simulate(kMid);
    vEnd = traj.v[N];
    if (vEnd > TARGET_V) { kLo = kMid; } else { kHi = kMid; }
  }
  var K = 0.5 * (kLo + kHi);
  var TRAJ = simulate(K);
  var D_END = TRAJ.d[N];

  /* ================= 纯物理内核：只读 TRAJ，不碰 DOM ================= */
  function sampleAt(u) {
    var uu = u;
    if (!(uu >= 0)) { uu = 0; }
    if (uu > 1) { uu = 1; }
    var idx = Math.round(uu * N);
    if (idx < 0) { idx = 0; }
    if (idx > N) { idx = N; }
    var v = TRAJ.v[idx];
    var F = K * v;
    var a = GS - F / M;
    return {
      u: uu, v: v, a: a, F: F,
      d: TRAJ.d[idx], imp: TRAJ.imp[idx], Q: TRAJ.Q[idx],
      Ek: 0.5 * M * v * v
    };
  }

  /* ================= 屏幕几何（斜面局部坐标：x 沿斜面向下为正） ================= */
  var PX0 = 230, PY0 = 265, TH = THETA, CT = Math.cos(TH), ST = Math.sin(TH);
  function rot(lx, ly) { return [PX0 + lx * CT - ly * ST, PY0 + lx * ST + ly * CT]; }

  var SCALE = 80;          /* px / (v0*t0) */
  var RAIL = 15;           /* 半轨距 */
  var FIELD_PAD = 15;      /* 磁场区域比杆的终点再往下画一点，视觉收口 */
  var X_EXIT = -20;
  var X_ENTRY = X_EXIT - D_END * SCALE;
  var X_APPROACH = X_ENTRY - 55;   /* 入场前的引导区（仅用于 step 视觉，不影响 probe） */

  var VSCALE = 22, FSCALE = 7;

  /* ---------------- DOM 引用 ---------------- */
  var elFieldRect = svg.querySelector('#q7-fieldrect');
  var elFieldPat = svg.querySelector('#q7-fieldpat');
  var elRailU = svg.querySelector('#q7-railU');
  var elRailL = svg.querySelector('#q7-railL');
  var elBoundEntry = svg.querySelector('#q7-boundEntry');
  var elBoundExit = svg.querySelector('#q7-boundExit');
  var elRod = svg.querySelector('#q7-rod');
  var elDotM = svg.querySelector('#q7-dotM');
  var elDotN = svg.querySelector('#q7-dotN');
  var elVarrow = svg.querySelector('#q7-varrow');
  var elFarrow = svg.querySelector('#q7-farrow');
  var elLabM = svg.querySelector('#q7-labM');
  var elLabN = svg.querySelector('#q7-labN');
  var elRoU = svg.querySelector('#q7-ro-u');
  var elRoV = svg.querySelector('#q7-ro-v');
  var elRoD = svg.querySelector('#q7-ro-d');
  var elRoA = svg.querySelector('#q7-ro-a');
  var elRoF = svg.querySelector('#q7-ro-F');
  var elRoEk = svg.querySelector('#q7-ro-Ek');
  var elC1Curve = svg.querySelector('#q7-c1-curve');
  var elC1Dot = svg.querySelector('#q7-c1-dot');
  var elC2Curve = svg.querySelector('#q7-c2-curve');
  var elC2Dot = svg.querySelector('#q7-c2-dot');
  var elC2Final = svg.querySelector('#q7-c2-final');
  var elC3CurveW = svg.querySelector('#q7-c3-curveW');
  var elC3CurveQ = svg.querySelector('#q7-c3-curveQ');
  var elC3DotQ = svg.querySelector('#q7-c3-dotQ');
  var elC3DotW = svg.querySelector('#q7-c3-dotW');
  var elCursor = svg.querySelector('#q7-cursor');
  var elKval = svg.querySelector('#q7-kval');

  /* ---------------- 图表坐标（右侧三个小图共用横轴 u∈[0,1]） ---------------- */
  var CX0 = 345, CX1 = 545;
  function chx(u) { return CX0 + u * (CX1 - CX0); }
  var C1_YTOP = 48, C1_YBOT = 110, C1_LO = 1.0, C1_HI = 2.0;
  var C2_YTOP = 128, C2_YBOT = 190, C2_LO = 0.0, C2_HI = 4.4;
  var C3_YTOP = 208, C3_YBOT = 270, C3_LO = 0.0, C3_HI = 9.5;
  function chy(val, ytop, ybot, lo, hi) { return ybot - (val - lo) / (hi - lo) * (ybot - ytop); }

  /* 预采样曲线（与 probe 用同一个 sampleAt，保证画的和算的是同一套物理） */
  var CN = 150, i2, uu2, s2, PT1 = [], PT2 = [], PT3W = [], PT3Q = [];
  for (i2 = 0; i2 <= CN; i2++) {
    uu2 = i2 / CN;
    s2 = sampleAt(uu2);
    PT1.push(chx(uu2).toFixed(2) + ',' + chy(s2.v, C1_YTOP, C1_YBOT, C1_LO, C1_HI).toFixed(2));
    PT2.push(chx(uu2).toFixed(2) + ',' + chy(s2.imp, C2_YTOP, C2_YBOT, C2_LO, C2_HI).toFixed(2));
    PT3W.push(chx(uu2).toFixed(2) + ',' + chy(M * G * Math.sin(THETA) * s2.d, C3_YTOP, C3_YBOT, C3_LO, C3_HI).toFixed(2));
    PT3Q.push(chx(uu2).toFixed(2) + ',' + chy(s2.Q, C3_YTOP, C3_YBOT, C3_LO, C3_HI).toFixed(2));
  }

  /* ---------------- 静态几何（只与 D_END 有关，随 u 不变，设一次即可） ---------------- */
  function setStaticGeometry() {
    var pTop = rot(X_ENTRY - 70, 0);
    /* 斜面楔形（仅装饰，起点略高于导轨顶端即可，不参与物理） */
    var wedge = svg.querySelector('#q7-wedge');
    if (wedge) {
      wedge.setAttribute('points',
        pTop[0].toFixed(1) + ',' + pTop[1].toFixed(1) + ' ' +
        pTop[0].toFixed(1) + ',' + PY0.toFixed(1) + ' ' +
        PX0.toFixed(1) + ',' + PY0.toFixed(1));
    }
    elRailU.setAttribute('x1', (X_ENTRY - 70).toFixed(2));
    elRailU.setAttribute('y1', (-RAIL).toFixed(2));
    elRailU.setAttribute('x2', (X_EXIT + FIELD_PAD).toFixed(2));
    elRailU.setAttribute('y2', (-RAIL).toFixed(2));
    elRailL.setAttribute('x1', (X_ENTRY - 70).toFixed(2));
    elRailL.setAttribute('y1', RAIL.toFixed(2));
    elRailL.setAttribute('x2', (X_EXIT + FIELD_PAD).toFixed(2));
    elRailL.setAttribute('y2', RAIL.toFixed(2));

    elFieldRect.setAttribute('x', X_ENTRY.toFixed(2));
    elFieldRect.setAttribute('y', (-RAIL - 6).toFixed(2));
    elFieldRect.setAttribute('width', (X_EXIT + FIELD_PAD - X_ENTRY).toFixed(2));
    elFieldRect.setAttribute('height', (2 * (RAIL + 6)).toFixed(2));
    elFieldPat.setAttribute('x', X_ENTRY.toFixed(2));
    elFieldPat.setAttribute('y', (-RAIL - 6).toFixed(2));
    elFieldPat.setAttribute('width', (X_EXIT + FIELD_PAD - X_ENTRY).toFixed(2));
    elFieldPat.setAttribute('height', (2 * (RAIL + 6)).toFixed(2));

    elBoundEntry.setAttribute('x1', X_ENTRY.toFixed(2));
    elBoundEntry.setAttribute('x2', X_ENTRY.toFixed(2));
    elBoundEntry.setAttribute('y1', (-RAIL - 6).toFixed(2));
    elBoundEntry.setAttribute('y2', (RAIL + 6).toFixed(2));
    elBoundExit.setAttribute('x1', X_EXIT.toFixed(2));
    elBoundExit.setAttribute('x2', X_EXIT.toFixed(2));
    elBoundExit.setAttribute('y1', (-RAIL - 6).toFixed(2));
    elBoundExit.setAttribute('y2', (RAIL + 6).toFixed(2));

    if (elKval) { elKval.textContent = 'k≈' + K.toFixed(3); }
    if (elC2Final) { elC2Final.textContent = 'impulse(1)=' + TRAJ.imp[N].toFixed(2); }
  }

  /* ---------------- 每帧渲染：rodX 为杆在局部坐标下的 x（引导阶段与物理阶段共用） ---------------- */
  function render(uPhys, rodX) {
    var s = sampleAt(uPhys);
    var rx = (typeof rodX === 'number') ? rodX : (X_ENTRY + s.d * SCALE);

    elRod.setAttribute('x1', rx.toFixed(2));
    elRod.setAttribute('x2', rx.toFixed(2));
    elDotM.setAttribute('cx', rx.toFixed(2));
    elDotN.setAttribute('cx', rx.toFixed(2));
    elVarrow.setAttribute('x1', rx.toFixed(2));
    elVarrow.setAttribute('x2', (rx + s.v * VSCALE).toFixed(2));
    elFarrow.setAttribute('x1', rx.toFixed(2));
    elFarrow.setAttribute('x2', (rx - s.F * FSCALE).toFixed(2));

    var pM = rot(rx, -RAIL), pN = rot(rx, RAIL);
    elLabM.setAttribute('x', pM[0].toFixed(2));
    elLabM.setAttribute('y', (pM[1] - 6).toFixed(2));
    elLabN.setAttribute('x', pN[0].toFixed(2));
    elLabN.setAttribute('y', (pN[1] + 12).toFixed(2));

    elRoU.textContent = s.u.toFixed(3);
    elRoV.textContent = s.v.toFixed(3);
    elRoD.textContent = s.d.toFixed(3);
    elRoA.textContent = s.a.toFixed(3);
    elRoF.textContent = s.F.toFixed(3);
    elRoEk.textContent = s.Ek.toFixed(3);

    var k = Math.round(s.u * CN);
    if (k < 0) { k = 0; }
    if (k > CN) { k = CN; }
    var xNow = chx(s.u).toFixed(2);
    elC1Curve.setAttribute('points', PT1.slice(0, k + 1).join(' ') + ' ' + xNow + ',' + chy(s.v, C1_YTOP, C1_YBOT, C1_LO, C1_HI).toFixed(2));
    elC1Dot.setAttribute('cx', xNow);
    elC1Dot.setAttribute('cy', chy(s.v, C1_YTOP, C1_YBOT, C1_LO, C1_HI).toFixed(2));

    elC2Curve.setAttribute('points', PT2.slice(0, k + 1).join(' ') + ' ' + xNow + ',' + chy(s.imp, C2_YTOP, C2_YBOT, C2_LO, C2_HI).toFixed(2));
    elC2Dot.setAttribute('cx', xNow);
    elC2Dot.setAttribute('cy', chy(s.imp, C2_YTOP, C2_YBOT, C2_LO, C2_HI).toFixed(2));

    var wNow = M * G * Math.sin(THETA) * s.d;
    elC3CurveW.setAttribute('points', PT3W.slice(0, k + 1).join(' ') + ' ' + xNow + ',' + chy(wNow, C3_YTOP, C3_YBOT, C3_LO, C3_HI).toFixed(2));
    elC3CurveQ.setAttribute('points', PT3Q.slice(0, k + 1).join(' ') + ' ' + xNow + ',' + chy(s.Q, C3_YTOP, C3_YBOT, C3_LO, C3_HI).toFixed(2));
    elC3DotW.setAttribute('cx', xNow);
    elC3DotW.setAttribute('cy', chy(wNow, C3_YTOP, C3_YBOT, C3_LO, C3_HI).toFixed(2));
    elC3DotQ.setAttribute('cx', xNow);
    elC3DotQ.setAttribute('cy', chy(s.Q, C3_YTOP, C3_YBOT, C3_LO, C3_HI).toFixed(2));

    elCursor.setAttribute('x1', xNow);
    elCursor.setAttribute('x2', xNow);
  }

  /* ---------------- 播放节奏：引导入场 → 磁场中真实过程（慢放）→ 定格 → 循环 ---------------- */
  var T_LEAD = 0.9, ANIM_T = 3.0, T_HOLD = 1.3;
  var CYC = T_LEAD + ANIM_T + T_HOLD;

  function step(t) {
    if (!(t >= 0)) { t = 0; }
    var tt = t - Math.floor(t / CYC) * CYC;
    if (tt < T_LEAD) {
      var lf = T_LEAD > 0 ? tt / T_LEAD : 1;
      render(0, X_APPROACH + lf * (X_ENTRY - X_APPROACH));
    } else if (tt < T_LEAD + ANIM_T) {
      var up = (tt - T_LEAD) / ANIM_T;
      render(up);
    } else {
      render(1);
    }
  }

  function reset() {
    setStaticGeometry();
    render(0, X_APPROACH);
  }

  reset();

  return {
    step: step,
    reset: reset,
    probe: function (u, caseId) {
      var s = sampleAt(u);
      return {
        u: s.u,
        v_inst: s.v,
        a_inst: s.a,
        F_amp: s.F,
        d: s.d,
        impulse_amp: s.imp,
        Q: s.Q,
        Ek: s.Ek,
        t_total: T_TOTAL,
        v0: V0,
        m: M,
        g: G,
        theta: THETA
      };
    }
  };
};
