window.Scenes["q5"] = function (fig) {
  var svg = fig.querySelector('svg');
  var ropeEl = svg.querySelector('#q5-rope');
  var frontEl = svg.querySelector('#q5-front');
  var sEl = svg.querySelector('#q5-S');
  var pEl = svg.querySelector('#q5-P');
  var infoT = svg.querySelector('#q5-info-t');
  var infoYS = svg.querySelector('#q5-info-yS');
  var infoYP = svg.querySelector('#q5-info-yP');

  // 归一化常数（题目未给出具体数值，取λ=T=A=1为单位，波速v=λ/T=1）
  var A = 1.0;
  var T = 1.0;
  var V = 1.0;
  var XP = 1.5;
  var TOTAL_PERIODS = 3.0;
  var CYCLE = 6.0; // 一次完整过程(3T)对应的播放时长，单位为秒（仅播放节奏，与probe物理无关）

  // 屏幕坐标映射
  var X0 = 60, SCALE = 120;   // x(λ) -> 屏幕x
  var Y0 = 140, AMPPX = 55;   // y(A) -> 屏幕y
  var WALL_X_PHYS = 3.6;      // 墙的位置(λ)，恒大于3，保证t∈[0,3T]内波前不触墙
  var ROPE_DX = 0.02;

  function x2px(x) { return X0 + x * SCALE; }
  function y2px(y) { return Y0 - y * AMPPX; }

  // 绳上位置x处、时刻t的竖直位移（波前未到达处保持静止）
  function yAt(x, t) {
    if (t >= x / V) {
      return A * Math.sin(2.0 * Math.PI * (t - x) / T);
    }
    return 0.0;
  }

  function vAt(x, t) {
    if (t >= x / V) {
      return A * (2.0 * Math.PI / T) * Math.cos(2.0 * Math.PI * (t - x) / T);
    }
    return 0.0;
  }

  // 与probe共用的核心物理计算（纯函数，只依赖物理时间t，单位为周期T）
  function computePhysics(t) {
    var yS = A * Math.sin(2.0 * Math.PI * t / T);
    var vS = A * (2.0 * Math.PI / T) * Math.cos(2.0 * Math.PI * t / T);
    var yP = yAt(XP, t);
    var vP = vAt(XP, t);
    var xFront = V * t;
    var yX025 = yAt(0.25, t);
    var yX075 = yAt(0.75, t);
    var yX125 = yAt(1.25, t);
    return {
      yS: yS, vS: vS, yP: yP, vP: vP, xFront: xFront,
      yX025: yX025, yX075: yX075, yX125: yX125
    };
  }

  function buildRopePath(t) {
    var d = '';
    var n = Math.round(WALL_X_PHYS / ROPE_DX);
    for (var i = 0; i <= n; i++) {
      var x = i * ROPE_DX;
      var y = yAt(x, t);
      var px = x2px(x), py = y2px(y);
      d += (i === 0 ? 'M' : 'L') + px.toFixed(2) + ' ' + py.toFixed(2) + ' ';
    }
    return d;
  }

  function render(tPhys) {
    var phys = computePhysics(tPhys);

    ropeEl.setAttribute('d', buildRopePath(tPhys));

    sEl.setAttribute('cy', y2px(phys.yS).toFixed(2));
    pEl.setAttribute('cy', y2px(phys.yP).toFixed(2));

    var fx = x2px(phys.xFront).toFixed(2);
    frontEl.setAttribute('x1', fx);
    frontEl.setAttribute('x2', fx);

    infoT.textContent = 't = ' + tPhys.toFixed(2) + ' T';
    infoYS.textContent = 'y_S = ' + phys.yS.toFixed(2) + ' A';
    infoYP.textContent = 'y_P = ' + phys.yP.toFixed(2) + ' A';
  }

  return {
    step: function (t) {
      var u = (t % CYCLE) / CYCLE;
      var tPhys = TOTAL_PERIODS * T * u;
      render(tPhys);
    },
    reset: function () {
      render(0);
    },
    probe: function (u, caseId) {
      var uu = u;
      if (uu < 0) uu = 0;
      if (uu > 1) uu = 1;
      var t = TOTAL_PERIODS * T * uu;
      var phys = computePhysics(t);
      return {
        u: uu,
        t: t,
        xFront: phys.xFront,
        xS: 0.0,
        yS: phys.yS,
        vS: phys.vS,
        xP: XP,
        yP: phys.yP,
        vP: phys.vP,
        yX025: phys.yX025,
        yX075: phys.yX075,
        yX125: phys.yX125
      };
    }
  };
};
