window.Scenes["q17"] = function (fig) {
  var svg = fig.querySelector('svg');
  var riselane = fig.querySelector('#q17-riselane');
  var pathA = fig.querySelector('#q17-pathA');
  var pathB = fig.querySelector('#q17-pathB');
  var obj = fig.querySelector('#q17-obj');
  var ballA = fig.querySelector('#q17-ballA');
  var ballB = fig.querySelector('#q17-ballB');
  var labelA = fig.querySelector('#q17-labelA');
  var labelB = fig.querySelector('#q17-labelB');
  var arrowA = fig.querySelector('#q17-arrowA');
  var arrowB = fig.querySelector('#q17-arrowB');
  var landA = fig.querySelector('#q17-landA');
  var landB = fig.querySelector('#q17-landB');
  var dspan = fig.querySelector('#q17-dspan');
  var dlabel = fig.querySelector('#q17-dlabel');
  var tauDisplay = fig.querySelector('#q17-tau-display');
  var uDisplay = fig.querySelector('#q17-u-display');
  var phaseDisplay = fig.querySelector('#q17-phase-display');
  var yDisplay = fig.querySelector('#q17-y-display');

  // ---- 权威常数（与 spec.constants / reference 一致，不得改动力的形式）----
  var G = 10.0;
  var T = 1.0;
  var V = 2.0;
  var V0 = G * T;          // 10
  var VB = 2.0 * V;         // 4
  var H = G * T * T / 2;    // 5

  // ---- 像素布局（纯渲染用，不参与物理计算）----
  var GY = 230;             // 地面像素 y
  var S = 30;                // 像素/米
  var OX = 220;              // 抛出点像素 x
  var TOPY = GY - H * S;     // 最高点像素 y
  var ARROW_LEN = 25;

  // ---- 动画节奏：ANIM_T 秒内 u 从0线性走到1，随后停留 HOLD_T 秒再循环 ----
  var ANIM_T = 4.0;
  var HOLD_T = 1.2;
  var CYCLE = ANIM_T + HOLD_T;

  // 与 spec.reference 完全一致的纯物理函数：只依据 (u, caseId) 计算
  function physics(u, caseId) {
    var tau = 2.0 * T * u;
    var y = V0 * tau - 0.5 * G * tau * tau;
    var vy = V0 - G * tau;
    var ay = -G;
    var xA, vAx, xB, vBx;
    if (tau <= T) {
      xA = 0.0; vAx = 0.0; xB = 0.0; vBx = 0.0;
    } else {
      var dt = tau - T;
      xA = V * dt; vAx = V;
      xB = -VB * dt; vBx = -VB;
    }
    return {
      u: u, tau: tau, y: y, vy: vy, ay: ay,
      xA: xA, vAx: vAx, xB: xB, vBx: vBx
    };
  }

  function toPx(x) { return OX + x * S; }
  function toPy(y) { return GY - y * S; }

  // 预先算好炸裂后的抛物线参考轨迹（常数已定，只需算一次）
  function buildTrajectory(vx) {
    var N = 20;
    var d = '';
    for (var i = 0; i <= N; i++) {
      var tau = T + (T * i / N);
      var dt = tau - T;
      var x = vx * dt;
      var y = V0 * tau - 0.5 * G * tau * tau;
      var px = toPx(x), py = toPy(y);
      d += (i === 0 ? 'M' : 'L') + px.toFixed(2) + ' ' + py.toFixed(2) + ' ';
    }
    return d;
  }

  pathA.setAttribute('d', buildTrajectory(V));
  pathB.setAttribute('d', buildTrajectory(-VB));

  function render(u) {
    var data = physics(u, 'c1');
    var exploded = u >= 0.5;
    var landed = u >= 0.999999;

    // 炸裂前：物体沿竖直方向上升/(共用曲线)的轨迹
    if (!exploded) {
      riselane.setAttribute('y2', toPy(data.y).toFixed(2));
    } else {
      riselane.setAttribute('y2', TOPY.toFixed(2));
    }

    obj.setAttribute('opacity', exploded ? '0' : '1');
    obj.setAttribute('cy', toPy(data.y).toFixed(2));

    var cxA = toPx(data.xA), cyA = toPy(data.y);
    var cxB = toPx(data.xB), cyB = toPy(data.y);

    ballA.setAttribute('opacity', exploded ? '1' : '0');
    ballA.setAttribute('cx', cxA.toFixed(2));
    ballA.setAttribute('cy', cyA.toFixed(2));

    ballB.setAttribute('opacity', exploded ? '1' : '0');
    ballB.setAttribute('cx', cxB.toFixed(2));
    ballB.setAttribute('cy', cyB.toFixed(2));

    labelA.setAttribute('opacity', exploded ? '1' : '0');
    labelA.setAttribute('x', (cxA - 18).toFixed(2));
    labelA.setAttribute('y', (cyA - 14).toFixed(2));

    labelB.setAttribute('opacity', exploded ? '1' : '0');
    labelB.setAttribute('x', (cxB - 40).toFixed(2));
    labelB.setAttribute('y', (cyB - 14).toFixed(2));

    arrowA.setAttribute('opacity', exploded ? '1' : '0');
    arrowA.setAttribute('x1', cxA.toFixed(2));
    arrowA.setAttribute('y1', cyA.toFixed(2));
    arrowA.setAttribute('x2', (cxA + ARROW_LEN).toFixed(2));
    arrowA.setAttribute('y2', cyA.toFixed(2));

    arrowB.setAttribute('opacity', exploded ? '1' : '0');
    arrowB.setAttribute('x1', cxB.toFixed(2));
    arrowB.setAttribute('y1', cyB.toFixed(2));
    arrowB.setAttribute('x2', (cxB - ARROW_LEN).toFixed(2));
    arrowB.setAttribute('y2', cyB.toFixed(2));

    landA.setAttribute('opacity', landed ? '1' : '0');
    landB.setAttribute('opacity', landed ? '1' : '0');
    dspan.setAttribute('opacity', landed ? '1' : '0');
    dlabel.setAttribute('opacity', landed ? '1' : '0');

    tauDisplay.textContent = 'τ = ' + data.tau.toFixed(2) + ' s';
    uDisplay.textContent = 'u = ' + u.toFixed(2);
    yDisplay.textContent = 'y = ' + Math.max(data.y, 0).toFixed(2) + ' m';
    if (!exploded) {
      phaseDisplay.textContent = '阶段：上升';
    } else if (!landed) {
      phaseDisplay.textContent = '阶段：下落（A、B已分离）';
    } else {
      phaseDisplay.textContent = '阶段：已同时落地';
    }
  }

  return {
    step: function (t) {
      var m = t % CYCLE;
      var u = (m <= ANIM_T) ? (m / ANIM_T) : 1.0;
      render(u);
    },

    reset: function () {
      // 场景无内部累积状态：render() 完全由 u 纯推导，这里无需清空任何东西。
    },

    probe: function (u, caseId) {
      return physics(u, caseId);
    }
  };
};
