/* q1 · 矫正牙齿两等大牵引力的合力
 *
 * 归一化：单个牵引力 F = 1。角平分线取为固定的 x 轴，
 * 两力关于 x 轴对称放置，故合力 y 分量恒为 0，合力矢量方向恒沿 x 轴，
 * 只有长度随 α 变化（α 从 0 连续增大到 π，非题图中固定的某一角度）。
 * probe() 与 step() 都调用同一个 physics(u)，保证渲染与断言物理一致。
 */
window.Scenes["q1"] = function (fig) {
  var svg = fig.querySelector('svg');

  function clamp01(u) {
    if (!(u >= 0)) { return 0; }
    if (u > 1) { return 1; }
    return u;
  }

  /* 纯物理：与 spec.reference 完全一致 */
  function physics(u) {
    var uu = clamp01(u);
    var F = 1.0;
    var alpha = Math.PI * uu;
    var half = alpha / 2;
    var c = Math.cos(half), s = Math.sin(half);
    var Fx1 = F * c, Fy1 = F * s;
    var Fx2 = F * c, Fy2 = -F * s;
    var Fx = Fx1 + Fx2, Fy = Fy1 + Fy2;
    var Fres = Math.sqrt(Fx * Fx + Fy * Fy);
    var Fres_formula = 2 * F * c;
    return {
      u: uu, alpha: alpha, F: F,
      Fx1: Fx1, Fy1: Fy1, Fx2: Fx2, Fy2: Fy2,
      Fx: Fx, Fy: Fy, Fres: Fres, Fres_formula: Fres_formula,
      cosHalf: c, sinHalf: s
    };
  }

  /* ================= 画布几何 ================= */
  var OX = 128, OY = 150, SCALE = 76, RARC = 34;
  var CL = 390, CR = 540, CT = 54, CB = 190;

  function chx(alpha) { return CL + (alpha / Math.PI) * (CR - CL); }
  function chy(fres) { return CB - (fres / 2) * (CB - CT); }

  function f(v, n) { return (isFinite(v) ? v : 0).toFixed(n); }

  /* ================= DOM 引用 ================= */
  var elArc = svg.querySelector('#q1-arc');
  var elF1 = svg.querySelector('#q1-f1');
  var elF2 = svg.querySelector('#q1-f2');
  var elPara1 = svg.querySelector('#q1-para1');
  var elPara2 = svg.querySelector('#q1-para2');
  var elFres = svg.querySelector('#q1-fres');
  var elLabF1 = svg.querySelector('#q1-labF1');
  var elLabF2 = svg.querySelector('#q1-labF2');
  var elLabFres = svg.querySelector('#q1-labFres');
  var elRoAlpha = svg.querySelector('#q1-roAlpha');
  var elRoFres = svg.querySelector('#q1-roFres');
  var elRoFormula = svg.querySelector('#q1-roFormula');
  var elCursor = svg.querySelector('#q1-cursor');
  var elDot = svg.querySelector('#q1-dot');

  function seg(el, x1, y1, x2, y2) {
    el.setAttribute('x1', f(x1, 2));
    el.setAttribute('y1', f(y1, 2));
    el.setAttribute('x2', f(x2, 2));
    el.setAttribute('y2', f(y2, 2));
  }

  function render(u) {
    var ph = physics(u);
    var c = ph.cosHalf, s = ph.sinHalf;

    var P1x = OX + SCALE * ph.Fx1, P1y = OY - SCALE * ph.Fy1;
    var P2x = OX + SCALE * ph.Fx2, P2y = OY - SCALE * ph.Fy2;
    var Rx = OX + SCALE * ph.Fx, Ry = OY - SCALE * ph.Fy;

    seg(elF1, OX, OY, P1x, P1y);
    seg(elF2, OX, OY, P2x, P2y);
    seg(elPara1, P1x, P1y, Rx, Ry);
    seg(elPara2, P2x, P2y, Rx, Ry);
    seg(elFres, OX, OY, Rx, Ry);

    var ax1 = OX + RARC * c, ay1 = OY + RARC * s;
    var ax2 = OX + RARC * c, ay2 = OY - RARC * s;
    elArc.setAttribute('d', 'M ' + f(ax1, 2) + ' ' + f(ay1, 2) +
      ' A ' + RARC + ' ' + RARC + ' 0 0 1 ' + f(ax2, 2) + ' ' + f(ay2, 2));

    elLabF1.setAttribute('x', f(P1x + 10 * c, 1));
    elLabF1.setAttribute('y', f(P1y - 10 * s - 4, 1));
    elLabF2.setAttribute('x', f(P2x + 10 * c, 1));
    elLabF2.setAttribute('y', f(P2y + 10 * s + 12, 1));
    elLabFres.setAttribute('x', f(Rx + 8, 1));
    elLabFres.setAttribute('y', f(OY - 6, 1));

    var alphaDeg = ph.alpha * 180 / Math.PI;
    elRoAlpha.textContent = f(ph.alpha, 3) + ' rad ≈ ' + f(alphaDeg, 1) + '°';
    elRoFres.textContent = '= ' + f(ph.Fres, 3);
    elRoFormula.textContent = '= 2F·cos(α/2) = ' + f(ph.Fres_formula, 3);

    var cx = chx(ph.alpha), cy = chy(ph.Fres);
    elCursor.setAttribute('x1', f(cx, 2));
    elCursor.setAttribute('x2', f(cx, 2));
    elDot.setAttribute('cx', f(cx, 2));
    elDot.setAttribute('cy', f(cy, 2));
  }

  /* ================= 时间轴（帧循环由运行时驱动） ================= */
  var TRUN = 3.2, THOLD = 1.0, TPER = TRUN + THOLD;

  function step(t) {
    var tt = t;
    if (!(tt > 0)) { tt = 0; }
    var ph = tt - Math.floor(tt / TPER) * TPER;
    var u = ph < TRUN ? ph / TRUN : 1;
    render(u);
  }

  render(0);

  return {
    step: step,
    reset: function () { render(0); },
    probe: function (u, caseId) {
      return physics(u);
    }
  };
};
