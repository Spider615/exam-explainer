window.Scenes["q9-gen3"] = function (fig) {
  var svg = fig.querySelector('svg');

  var E = 1.0, R = 1.0, L = 1.0, C = 1.0, T_end = 15.0;

  function derivs(i3, vc) {
    var d_i3 = (E + vc - 3.0 * i3 * R) / (2.0 * L);
    var d_vc = (E - i3 * R - vc) / (2.0 * R * C);
    return [d_i3, d_vc];
  }

  // 与 spec.reference 完全一致的 RK4 数值积分：状态方程组由基尔霍夫电流/电压定律联立导出
  function computeState(u) {
    var t = u * T_end;
    var I3 = 0.0, Vc = 0.0;
    var N = 3000;
    if (t > 0.0) {
      var dt = t / N;
      for (var i = 0; i < N; i++) {
        var k1 = derivs(I3, Vc);
        var k2 = derivs(I3 + 0.5 * dt * k1[0], Vc + 0.5 * dt * k1[1]);
        var k3 = derivs(I3 + 0.5 * dt * k2[0], Vc + 0.5 * dt * k2[1]);
        var k4 = derivs(I3 + dt * k3[0], Vc + dt * k3[1]);
        I3 = I3 + (dt / 6.0) * (k1[0] + 2.0 * k2[0] + 2.0 * k3[0] + k4[0]);
        Vc = Vc + (dt / 6.0) * (k1[1] + 2.0 * k2[1] + 2.0 * k3[1] + k4[1]);
      }
    }
    var I2 = (E - I3 * R - Vc) / (2.0 * R);
    var V = I2 * R + Vc;
    var VL = V - I3 * R;
    var I1 = I2 + I3;
    return { u: u, t: t, I1: I1, I2: I2, I3: I3, Vc: Vc, VL: VL };
  }

  function clamp01(x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }

  // ---- 图内引用 ----
  var elA1 = svg.querySelector('#q9-gen3-a1-glow');
  var elA2 = svg.querySelector('#q9-gen3-a2-glow');
  var elA3 = svg.querySelector('#q9-gen3-a3-glow');
  var elCap = svg.querySelector('#q9-gen3-cap-charge');
  var elCoil = svg.querySelector('#q9-gen3-coil-glow');
  var elCurveI1 = svg.querySelector('#q9-gen3-curve-I1');
  var elCurveI2 = svg.querySelector('#q9-gen3-curve-I2');
  var elCurveI3 = svg.querySelector('#q9-gen3-curve-I3');
  var elCurI1 = svg.querySelector('#q9-gen3-cursor-I1');
  var elCurI2 = svg.querySelector('#q9-gen3-cursor-I2');
  var elCurI3 = svg.querySelector('#q9-gen3-cursor-I3');
  var elTxtI1 = svg.querySelector('#q9-gen3-txt-I1');
  var elTxtI2 = svg.querySelector('#q9-gen3-txt-I2');
  var elTxtI3 = svg.querySelector('#q9-gen3-txt-I3');
  var elTxtVc = svg.querySelector('#q9-gen3-txt-Vc');
  var elTxtVL = svg.querySelector('#q9-gen3-txt-VL');
  var elTxtT = svg.querySelector('#q9-gen3-txt-t');
  var elPhase = svg.querySelector('#q9-gen3-phase');

  // ---- 曲线图坐标映射（固定量程，不随时间变化）----
  var CH_X0 = 385, CH_X1 = 535, CH_Y0 = 142, CH_Y1 = 55, YMAX = 0.6;
  function chartX(u) { return CH_X0 + u * (CH_X1 - CH_X0); }
  function chartY(v) { return CH_Y0 - (clamp01(v / YMAX)) * (CH_Y0 - CH_Y1); }

  // 曲线形状只取决于物理本身，预先算好、画一次即可
  (function drawCurves() {
    var N = 120;
    var d1 = '', d2 = '', d3 = '';
    for (var i = 0; i <= N; i++) {
      var uu = i / N;
      var st = computeState(uu);
      var x = chartX(uu).toFixed(2);
      var p = (i === 0 ? 'M' : 'L');
      d1 += p + x + ',' + chartY(st.I1).toFixed(2) + ' ';
      d2 += p + x + ',' + chartY(st.I2).toFixed(2) + ' ';
      d3 += p + x + ',' + chartY(st.I3).toFixed(2) + ' ';
    }
    elCurveI1.setAttribute('d', d1);
    elCurveI2.setAttribute('d', d2);
    elCurveI3.setAttribute('d', d3);
  })();

  // ---- 动画时序：t=0+ 定格 -> 暂态推进 -> 稳态定格 -> 循环 ----
  var HOLD0 = 1.0, ANIM = 10.0, HOLD1 = 2.5;
  var CYCLE = HOLD0 + ANIM + HOLD1;

  function uFromT(t) {
    var phase = t % CYCLE;
    if (phase < 0) phase += CYCLE;
    if (phase < HOLD0) return 0;
    if (phase < HOLD0 + ANIM) return (phase - HOLD0) / ANIM;
    return 1;
  }

  function render(u) {
    var st = computeState(u);
    var IMAX = 0.5;
    var b1 = clamp01(st.I1 / IMAX), b2 = clamp01(st.I2 / IMAX), b3 = clamp01(st.I3 / IMAX);

    elA1.setAttribute('fill-opacity', (0.10 + 0.85 * b1).toFixed(3));
    elA2.setAttribute('fill-opacity', (0.08 + 0.85 * b2).toFixed(3));
    elA3.setAttribute('fill-opacity', (0.08 + 0.85 * b3).toFixed(3));
    elCap.setAttribute('fill-opacity', (0.08 + 0.85 * clamp01(st.Vc / IMAX)).toFixed(3));
    elCoil.setAttribute('stroke-opacity', (0.08 + 0.85 * b3).toFixed(3));

    var cx = chartX(u);
    elCurI1.setAttribute('cx', cx.toFixed(2)); elCurI1.setAttribute('cy', chartY(st.I1).toFixed(2));
    elCurI2.setAttribute('cx', cx.toFixed(2)); elCurI2.setAttribute('cy', chartY(st.I2).toFixed(2));
    elCurI3.setAttribute('cx', cx.toFixed(2)); elCurI3.setAttribute('cy', chartY(st.I3).toFixed(2));

    elTxtI1.textContent = 'I1 = ' + st.I1.toFixed(3);
    elTxtI2.textContent = 'I2 = ' + st.I2.toFixed(3);
    elTxtI3.textContent = 'I3 = ' + st.I3.toFixed(3);
    elTxtVc.textContent = 'Vc = ' + st.Vc.toFixed(3);
    elTxtVL.textContent = 'VL = ' + st.VL.toFixed(3);
    elTxtT.textContent = 't = ' + st.t.toFixed(2) + ' (u=' + u.toFixed(2) + ')';

    if (u <= 0.001) elPhase.textContent = '刚闭合：C瞬间短路 / L瞬间断路';
    else if (u >= 0.999) elPhase.textContent = '稳态：C视为断路，L视为短路';
    else elPhase.textContent = '暂态过程：电容充电、线圈建流';
  }

  function step(t) { render(uFromT(t)); }
  function reset() { render(0); }

  reset();

  return {
    step: step,
    reset: reset,
    probe: function (u, caseId) {
      var st = computeState(u);
      return { u: st.u, t: st.t, I1: st.I1, I2: st.I2, I3: st.I3, Vc: st.Vc, VL: st.VL };
    }
  };
};
