/* q7-gen2 · 嫦娥六号变轨：轨道2(椭圆)上A→B的动能/加速度/机械能，与轨道1(圆)机械能对比
 *
 * 物理内核与 spec.physics.reference 完全一致：
 *   开普勒方程 π·u = E - e·sin(E) 牛顿迭代解 E(u)；r(u)=a(1-e·cosE)；
 *   活力公式给出 v(u)；角动量守恒 vt=L/r；vr=sqrt(max(v^2-vt^2,0))。
 *   probe 与 step 共用同一套 sampleC1/sampleC2，保证画的和算的是同一套物理。
 */
window.Scenes["q7-gen2"] = function (fig) {
  var svg = fig.querySelector('svg');

  /* ---------------- 物理常量（归一化：GM_月=1，r_p=1，r_a=2） ---------------- */
  var GM = 1.0;
  var R_P = 1.0;
  var R_A = 2.0;
  var A_SEMI = (R_P + R_A) / 2.0;              /* 1.5 */
  var ECC = (R_A - R_P) / (R_A + R_P);         /* 1/3 */
  var B_SEMI = A_SEMI * Math.sqrt(1 - ECC * ECC);
  var L_ANG = Math.sqrt(GM * A_SEMI * (1 - ECC * ECC));

  /* ================= 纯物理内核：只做数值计算，不碰 DOM ================= */
  function sampleC1(u) {
    var uu = u;
    if (!(uu >= 0)) { uu = 0; }
    if (uu > 1) { uu = 1; }
    var M = Math.PI * uu;
    var E = (uu < 0.8) ? (uu * Math.PI) : Math.PI;
    var i, f, fp, dE;
    for (i = 0; i < 100; i++) {
      f = E - ECC * Math.sin(E) - M;
      fp = 1 - ECC * Math.cos(E);
      dE = f / fp;
      E = E - dE;
      if (Math.abs(dE) < 1e-14) { break; }
    }
    var r = A_SEMI * (1 - ECC * Math.cos(E));
    var v2 = GM * (2.0 / r - 1.0 / A_SEMI);
    if (v2 < 0) { v2 = 0; }
    var v = Math.sqrt(v2);
    var vt = L_ANG / r;
    var vr2 = v2 - vt * vt;
    if (vr2 < 0) { vr2 = 0; }
    var vr = Math.sqrt(vr2);
    var KE = 0.5 * v2;
    var PE = -GM / r;
    var mechE = KE + PE;
    var acc = GM / (r * r);
    return { u: uu, r: r, v: v, vr: vr, vt: vt, KE: KE, acc: acc, mechE: mechE, E: E };
  }

  function sampleC2(u) {
    var r = R_P;
    var v = Math.sqrt(GM / R_P);
    var vt = v, vr = 0.0;
    var KE = 0.5 * v * v;
    var PE = -GM / r;
    var mechE = KE + PE;
    var acc = GM / (r * r);
    return { u: u, r: r, v: v, vr: vr, vt: vt, KE: KE, acc: acc, mechE: mechE };
  }

  /* ================= 屏幕几何：焦点(月球)在原点，A在-x侧，B在+x侧 ================= */
  var MX = 125, MY = 172, SCALE = 80;

  function posEllipseFromE(E) {
    var Xp = A_SEMI * (ECC - Math.cos(E));
    var Yp = B_SEMI * Math.sin(E);
    return { x: MX + SCALE * Xp, y: MY - SCALE * Yp, Xp: Xp, Yp: Yp };
  }
  function posCircleFromTheta(theta) {
    var Xp = Math.cos(theta) * R_P;
    var Yp = Math.sin(theta) * R_P;
    return { x: MX + SCALE * Xp, y: MY - SCALE * Yp };
  }
  function buildTrail(Ecur) {
    var segs = 48, i, Ei, p, d = '';
    for (i = 0; i <= segs; i++) {
      Ei = (Ecur * i) / segs;
      p = posEllipseFromE(Ei);
      d += (i === 0 ? 'M' : 'L') + p.x.toFixed(2) + ',' + p.y.toFixed(2) + ' ';
    }
    return d;
  }

  /* ---------------- DOM 引用 ---------------- */
  var elTrail = svg.querySelector('#q7-gen2-trail');
  var elVarrow = svg.querySelector('#q7-gen2-varrow');
  var elAarrow = svg.querySelector('#q7-gen2-aarrow');
  var elRline = svg.querySelector('#q7-gen2-rline');
  var elSat1 = svg.querySelector('#q7-gen2-sat1');
  var elSat2 = svg.querySelector('#q7-gen2-sat2');
  var elValU = svg.querySelector('#q7-gen2-val-u');
  var elValR = svg.querySelector('#q7-gen2-val-r');
  var elValV = svg.querySelector('#q7-gen2-val-v');
  var elValVr = svg.querySelector('#q7-gen2-val-vr');
  var elValVt = svg.querySelector('#q7-gen2-val-vt');
  var elValKE = svg.querySelector('#q7-gen2-val-KE');
  var elValAcc = svg.querySelector('#q7-gen2-val-acc');
  var elValMechE = svg.querySelector('#q7-gen2-val-mechE');
  var elValMechE1 = svg.querySelector('#q7-gen2-val-mechE1');
  var elValMechE2 = svg.querySelector('#q7-gen2-val-mechE2');

  var MECHE1_CONST = sampleC2(0).mechE;

  /* ---------------- 每帧渲染 ---------------- */
  var VPIX = 55, APIX = 55;

  function render(u, tAbs) {
    var s1 = sampleC1(u);
    var Pe = posEllipseFromE(s1.E);
    var r = s1.r;
    var rhatX = Pe.Xp / r, rhatY = Pe.Yp / r;
    var thcwX = Pe.Yp / r, thcwY = -Pe.Xp / r;
    var velX = s1.vr * rhatX + s1.vt * thcwX;
    var velY = s1.vr * rhatY + s1.vt * thcwY;
    var accX = -rhatX * s1.acc;
    var accY = -rhatY * s1.acc;

    elSat2.setAttribute('cx', Pe.x.toFixed(2));
    elSat2.setAttribute('cy', Pe.y.toFixed(2));

    elVarrow.setAttribute('x1', Pe.x.toFixed(2));
    elVarrow.setAttribute('y1', Pe.y.toFixed(2));
    elVarrow.setAttribute('x2', (Pe.x + velX * VPIX).toFixed(2));
    elVarrow.setAttribute('y2', (Pe.y - velY * VPIX).toFixed(2));

    elAarrow.setAttribute('x1', Pe.x.toFixed(2));
    elAarrow.setAttribute('y1', Pe.y.toFixed(2));
    elAarrow.setAttribute('x2', (Pe.x + accX * APIX).toFixed(2));
    elAarrow.setAttribute('y2', (Pe.y - accY * APIX).toFixed(2));

    elRline.setAttribute('x2', Pe.x.toFixed(2));
    elRline.setAttribute('y2', Pe.y.toFixed(2));

    elTrail.setAttribute('d', buildTrail(s1.E));

    var theta = Math.PI - (tAbs / PERIOD1) * 2 * Math.PI;
    var Pc = posCircleFromTheta(theta);
    elSat1.setAttribute('cx', Pc.x.toFixed(2));
    elSat1.setAttribute('cy', Pc.y.toFixed(2));

    elValU.textContent = s1.u.toFixed(3);
    elValR.textContent = s1.r.toFixed(3);
    elValV.textContent = s1.v.toFixed(3);
    elValVr.textContent = s1.vr.toFixed(3);
    elValVt.textContent = s1.vt.toFixed(3);
    elValKE.textContent = s1.KE.toFixed(3);
    elValAcc.textContent = s1.acc.toFixed(3);
    elValMechE.textContent = s1.mechE.toFixed(3);
    elValMechE1.textContent = MECHE1_CONST.toFixed(3);
    elValMechE2.textContent = s1.mechE.toFixed(3);
  }

  /* ---------------- 播放节奏：A→B 非匀速真实过程 → 定格于B → 循环 ---------------- */
  var TRAVEL = 6.0, HOLD = 1.3;
  var CYCLE = TRAVEL + HOLD;
  /* 轨道1(对比圆)持续匀速自转，周期按开普勒第三定律相对轨道2半周期换算，仅作视觉节奏参考 */
  var T1_PHYS = 2 * Math.PI * Math.sqrt((R_P * R_P * R_P) / GM);
  var T2HALF_PHYS = Math.PI * Math.sqrt((A_SEMI * A_SEMI * A_SEMI) / GM);
  var PERIOD1 = TRAVEL * (T1_PHYS / T2HALF_PHYS);

  function step(t) {
    if (!(t >= 0)) { t = 0; }
    var tt = t - Math.floor(t / CYCLE) * CYCLE;
    var u = (tt < TRAVEL) ? (tt / TRAVEL) : 1;
    render(u, t);
  }

  function reset() {
    render(0, 0);
  }

  reset();

  return {
    step: step,
    reset: reset,
    probe: function (u, caseId) {
      if (caseId === 'c2') { return sampleC2(u); }
      return sampleC1(u);
    }
  };
};
