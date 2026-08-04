window.Scenes["q10"] = function (fig) {
  var svg = fig.querySelector('svg');

  // ---- 物理常量（示例参数，取自 spec.constants，与 reference 完全一致）----
  var G = 10.0, K = 10.0, M = 1.0;
  var X_EQ = M * G / K;
  var OMEGA0 = Math.sqrt(K / M);
  var GAMMA1 = 0.3, GAMMA2 = 1.0;
  var C_EM = 2.0 * M * (GAMMA2 - GAMMA1);
  var EPS_STOP = 0.02;
  var OMEGA_D1 = Math.sqrt(OMEGA0 * OMEGA0 - GAMMA1 * GAMMA1);
  var OMEGA_D2 = Math.sqrt(OMEGA0 * OMEGA0 - GAMMA2 * GAMMA2);
  var T1 = Math.log(1.0 / EPS_STOP) / GAMMA1;
  var T2 = Math.log(1.0 / EPS_STOP) / GAMMA2;

  // 权威解析解：与 spec.physics.equations 完全一致，step 与 probe 共用
  function stateAt(t, caseId) {
    var gamma = caseId === 'c1' ? GAMMA1 : GAMMA2;
    var omega_d = caseId === 'c1' ? OMEGA_D1 : OMEGA_D2;
    var e = Math.exp(-gamma * t);
    var cos_wd = Math.cos(omega_d * t);
    var sin_wd = Math.sin(omega_d * t);
    var x = X_EQ * (1.0 - e * (cos_wd + (gamma / omega_d) * sin_wd));
    var v = X_EQ * (OMEGA0 * OMEGA0 / omega_d) * e * sin_wd;
    var a = X_EQ * (OMEGA0 * OMEGA0 / omega_d) * e * (omega_d * cos_wd - gamma * sin_wd);
    var F_amp = caseId === 'c1' ? 0.0 : C_EM * v;
    var Eloss = M * G * x - 0.5 * K * x * x - 0.5 * M * v * v;
    return { t: t, x: x, v: v, a: a, F_amp: F_amp, Eloss: Eloss };
  }

  // ---- 引用 ----
  var spring1 = svg.querySelector('#q10-spring1');
  var spring2 = svg.querySelector('#q10-spring2');
  var magnet1 = svg.querySelector('#q10-magnet1');
  var magnet2 = svg.querySelector('#q10-magnet2');
  var varrow1 = svg.querySelector('#q10-varrow1');
  var varrow2 = svg.querySelector('#q10-varrow2');
  var coilShrink = svg.querySelector('#q10-coilShrink');
  var coilCurrent = svg.querySelector('#q10-coilCurrent');
  var status1 = svg.querySelector('#q10-status1');
  var status2 = svg.querySelector('#q10-status2');
  var dotX1 = svg.querySelector('#q10-dotX1');
  var dotX2 = svg.querySelector('#q10-dotX2');
  var dotE1 = svg.querySelector('#q10-dotE1');
  var dotE2 = svg.querySelector('#q10-dotE2');
  var dotF2 = svg.querySelector('#q10-dotF2');
  var rt1 = svg.querySelector('#q10-rt1');
  var rt2 = svg.querySelector('#q10-rt2');
  var curveX1 = svg.querySelector('#q10-curveX1');
  var curveX2 = svg.querySelector('#q10-curveX2');
  var curveX2flat = svg.querySelector('#q10-curveX2flat');
  var curveE1 = svg.querySelector('#q10-curveE1');
  var curveE2 = svg.querySelector('#q10-curveE2');
  var curveE2flat = svg.querySelector('#q10-curveE2flat');
  var curveF2 = svg.querySelector('#q10-curveF2');
  var turnMark = svg.querySelector('#q10-turnMark');
  var turnLabel = svg.querySelector('#q10-turnLabel');

  // ---- 示意图几何 ----
  var CX1 = 90, CX2 = 235, CEIL_Y = 44, Y0 = 70, PXPM = 66;

  // ---- 曲线坐标映射 ----
  var GX0 = 300, GX1 = 548;
  function t2px(t) { return GX0 + (t / T1) * (GX1 - GX0); }

  var G1_Y0 = 108;
  function xVal2px(x) { return G1_Y0 - 37.0 * x; }

  var G2_Y0 = 180, G2_TOP = 118;
  var E_SCALE = (G2_Y0 - G2_TOP) / 6.0;
  function eVal2px(ev) { return G2_Y0 - E_SCALE * ev; }

  var G3_ZERO = 234;
  var F_SCALE = (252 - 190) / 7.0;
  function fVal2px(fv) { return G3_ZERO - F_SCALE * fv; }

  function buildPath(n, tStart, tEnd, caseId, mapY, keyFn) {
    var d = '';
    for (var i = 0; i <= n; i++) {
      var t = tStart + (tEnd - tStart) * (i / n);
      var s = stateAt(t, caseId);
      var px = t2px(t);
      var py = mapY(keyFn(s));
      d += (i === 0 ? 'M ' : ' L ') + px.toFixed(2) + ' ' + py.toFixed(2);
    }
    return d;
  }

  // ---- 预计算静态参考曲线（只算一次）----
  curveX1.setAttribute('d', buildPath(160, 0, T1, 'c1', xVal2px, function (s) { return s.x; }));
  curveX2.setAttribute('d', buildPath(160, 0, T2, 'c2', xVal2px, function (s) { return s.x; }));
  curveE1.setAttribute('d', buildPath(160, 0, T1, 'c1', eVal2px, function (s) { return s.Eloss; }));
  curveE2.setAttribute('d', buildPath(160, 0, T2, 'c2', eVal2px, function (s) { return s.Eloss; }));
  curveF2.setAttribute('d', buildPath(160, 0, T2, 'c2', fVal2px, function (s) { return s.F_amp; }));

  var finalState2 = stateAt(T2, 'c2');
  var flatX2y = xVal2px(finalState2.x);
  var flatE2y = eVal2px(finalState2.Eloss);
  curveX2flat.setAttribute('d', 'M ' + t2px(T2).toFixed(2) + ' ' + flatX2y.toFixed(2) +
    ' L ' + t2px(T1).toFixed(2) + ' ' + flatX2y.toFixed(2));
  curveE2flat.setAttribute('d', 'M ' + t2px(T2).toFixed(2) + ' ' + flatE2y.toFixed(2) +
    ' L ' + t2px(T1).toFixed(2) + ' ' + flatE2y.toFixed(2));

  var tTurn2 = Math.PI / OMEGA_D2;
  var sTurn2 = stateAt(tTurn2, 'c2');
  turnMark.setAttribute('cx', t2px(tTurn2).toFixed(2));
  turnMark.setAttribute('cy', fVal2px(sTurn2.F_amp).toFixed(2));
  turnLabel.setAttribute('x', (t2px(tTurn2) - 15).toFixed(2));

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  var PAUSE = 2.2;
  var PERIOD = T1 + PAUSE;

  function render(tGlobal) {
    var tm = tGlobal % PERIOD;
    if (tm < 0) tm += PERIOD;
    var t1r = Math.min(tm, T1);
    var t2r = Math.min(tm, T2);
    var s1 = stateAt(t1r, 'c1');
    var s2 = stateAt(t2r, 'c2');

    var y1 = Y0 + PXPM * s1.x;
    var y2 = Y0 + PXPM * s2.x;
    spring1.setAttribute('d', 'M ' + CX1 + ' ' + CEIL_Y + ' L ' + CX1 + ' ' + y1.toFixed(2));
    spring2.setAttribute('d', 'M ' + CX2 + ' ' + CEIL_Y + ' L ' + CX2 + ' ' + y2.toFixed(2));
    magnet1.setAttribute('transform', 'translate(' + CX1 + ',' + y1.toFixed(2) + ')');
    magnet2.setAttribute('transform', 'translate(' + CX2 + ',' + y2.toFixed(2) + ')');

    var VSCALE = 9;
    varrow1.setAttribute('x1', CX1 + 18); varrow1.setAttribute('y1', y1.toFixed(2));
    varrow1.setAttribute('x2', CX1 + 18); varrow1.setAttribute('y2', (y1 + clamp(s1.v * VSCALE, -36, 36)).toFixed(2));
    varrow2.setAttribute('x1', CX2 + 18); varrow2.setAttribute('y1', y2.toFixed(2));
    varrow2.setAttribute('x2', CX2 + 18); varrow2.setAttribute('y2', (y2 + clamp(s2.v * VSCALE, -36, 36)).toFixed(2));

    var approaching = s2.v > 0.03;
    coilShrink.setAttribute('opacity', approaching ? '1' : '0');
    coilCurrent.setAttribute('opacity', Math.abs(s2.v) > 0.02 ? '1' : '0.15');
    coilCurrent.setAttribute('transform', s2.v >= 0 ? '' : 'translate(470,0) scale(-1,1)');

    status1.textContent = (t1r >= T1 - 1e-6) ? '已停止' : '运动中';
    status2.textContent = (t2r >= T2 - 1e-6) ? '已停止' : '运动中';

    dotX1.setAttribute('cx', t2px(t1r).toFixed(2)); dotX1.setAttribute('cy', xVal2px(s1.x).toFixed(2));
    dotX2.setAttribute('cx', t2px(t2r).toFixed(2)); dotX2.setAttribute('cy', xVal2px(s2.x).toFixed(2));
    dotE1.setAttribute('cx', t2px(t1r).toFixed(2)); dotE1.setAttribute('cy', eVal2px(s1.Eloss).toFixed(2));
    dotE2.setAttribute('cx', t2px(t2r).toFixed(2)); dotE2.setAttribute('cy', eVal2px(s2.Eloss).toFixed(2));
    dotF2.setAttribute('cx', t2px(t2r).toFixed(2)); dotF2.setAttribute('cy', fVal2px(s2.F_amp).toFixed(2));

    rt1.textContent = 't=' + s1.t.toFixed(2) + 's x=' + s1.x.toFixed(3) + 'm v=' + s1.v.toFixed(2) +
      'm/s Eloss=' + s1.Eloss.toFixed(2) + 'J';
    rt2.textContent = 't=' + s2.t.toFixed(2) + 's x=' + s2.x.toFixed(3) + 'm v=' + s2.v.toFixed(2) +
      'm/s F_amp=' + s2.F_amp.toFixed(2) + 'N Eloss=' + s2.Eloss.toFixed(2) + 'J';
  }

  render(0);

  return {
    step: function (t) { render(t); },
    reset: function () { render(0); },
    probe: function (u, caseId) {
      var Tc = caseId === 'c1' ? T1 : T2;
      var t = u * Tc;
      var s = stateAt(t, caseId);
      return { u: u, t: s.t, x: s.x, v: s.v, a: s.a, F_amp: s.F_amp, Eloss: s.Eloss };
    }
  };
};
