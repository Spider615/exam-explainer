window.Scenes["q13"] = function (fig) {
  var svg = fig.querySelector('svg');
  var cycleAB = fig.querySelector('#q13-cycleAB');
  var cycleCD = fig.querySelector('#q13-cycleCD');
  var current = fig.querySelector('#q13-current');
  var infoPhase = fig.querySelector('#q13-info-phase');
  var infoP = fig.querySelector('#q13-info-p');
  var infoV = fig.querySelector('#q13-info-V');
  var infoT = fig.querySelector('#q13-info-T');

  // ---- 权威常数（与 spec.constants / reference 完全一致，不得改动力的形式）----
  var PA = 800000.0, PB = 400000.0, PC = 100000.0, PD = 200000.0;
  var V1 = 1.0, V2 = 2.0, T1 = 1200.0, T2 = 300.0;

  // ---- 像素布局（纯渲染用，不参与物理计算）----
  var X0 = 60, VSCALE = 136;
  var Y0 = 260, PSCALE = 220 / 900000;

  function v2x(V) { return X0 + V * VSCALE; }
  function p2y(p) { return Y0 - p * PSCALE; }

  // 与 spec.reference 完全一致的纯物理函数：只依据 (u, caseId) 计算
  function physics(u, caseId) {
    var t, V, T, p;
    u = Math.max(0, Math.min(1, u));
    if (u <= 0.25) {
      t = u / 0.25;
      V = V1 + (V2 - V1) * t;
      T = T1;
      p = PA * V1 / V;
    } else if (u <= 0.5) {
      t = (u - 0.25) / 0.25;
      V = V2;
      T = T1 + (T2 - T1) * t;
      p = PB * T / T1;
    } else if (u <= 0.75) {
      t = (u - 0.5) / 0.25;
      V = V2 + (V1 - V2) * t;
      T = T2;
      p = PC * V2 / V;
    } else {
      t = (u - 0.75) / 0.25;
      V = V1;
      T = T2 + (T1 - T2) * t;
      p = PD * T / T2;
    }
    return { u: u, p: p, V: V, T: T };
  }

  // 预先算好 AB、CD 两条等温双曲线（pV=常数）的作图路径：常数已定，只需算一次
  function buildIsotherm(Vstart, Vend, pvConst, steps) {
    var d = '', i, V, p, x, y;
    for (i = 0; i <= steps; i++) {
      V = Vstart + (Vend - Vstart) * i / steps;
      p = pvConst / V;
      x = v2x(V); y = p2y(p);
      d += (i === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2) + ' ';
    }
    return d;
  }
  cycleAB.setAttribute('d', buildIsotherm(V1, V2, PA * V1, 24));
  cycleCD.setAttribute('d', buildIsotherm(V2, V1, PC * V2, 24));

  function phaseLabel(u) {
    if (u <= 0.25) return 'AB：等温膨胀';
    if (u <= 0.5) return 'BC：等容降压';
    if (u <= 0.75) return 'CD：等温压缩';
    return 'DA：等容升压';
  }

  function render(u) {
    var s = physics(u, 'c1');
    current.setAttribute('cx', v2x(s.V).toFixed(2));
    current.setAttribute('cy', p2y(s.p).toFixed(2));
    infoPhase.textContent = phaseLabel(u);
    infoP.textContent = 'p = ' + s.p.toFixed(0) + ' Pa';
    infoV.textContent = 'V = ' + s.V.toFixed(2) + ' m³';
    infoT.textContent = 'T = ' + s.T.toFixed(0) + ' K';
  }

  var CYCLE = 8.0;

  return {
    step: function (t) {
      var u = (t % CYCLE) / CYCLE;
      render(u);
    },
    reset: function () {
      render(0);
    },
    probe: function (u, caseId) {
      return physics(u, caseId);
    }
  };
};
