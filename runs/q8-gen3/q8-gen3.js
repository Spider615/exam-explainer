/* q8-gen3 · 无人机竖直飞行 y-t 图像：EF匀速上升、FM失重过渡、MN匀速下降
 *
 * 自设（自洽求解）参数：t_E=10s, t_F=20s, t_M=40s, t_N=53s, m=2kg。
 * EF: y=4t-26（给定），MN: y=-2t+140（给定）。
 * FM段(20<=t<=40)速度题面未给具体函数，只要求 v(F)=4、v(M)=-2 且连续单调递减；
 * 本实现取 v(s)=4-0.51*s+0.0105*s^2（s=t-20），该函数满足端点与单调性，
 * 且其对 s 的积分恰为 6m，使 FM 终点高度与 MN 直线在 t=40s 处的高度（60m）严格衔接，
 * 因此 y、v 在 F、M 两点都连续，只有加速度在 F、M 处发生跳变（符合“加速度突变”的常见物理设定）。
 */
window.Scenes["q8-gen3"] = function (fig) {
  var svg = fig.querySelector('svg');

  /* ---------------- 物理常量 ---------------- */
  var T_E = 10.0, T_F = 20.0, T_M = 40.0, T_N = 53.0;
  var MASS = 2.0;
  var A1 = 0.51, B1 = 0.0105;

  function yOf(t) {
    if (t <= T_F) {
      return 4.0 * t - 26.0;
    } else if (t <= T_M) {
      var s = t - T_F;
      return 54.0 + 4.0 * s - 0.255 * s * s + 0.0035 * s * s * s;
    } else {
      return -2.0 * t + 140.0;
    }
  }
  function vOf(t) {
    if (t <= T_F) {
      return 4.0;
    } else if (t <= T_M) {
      var s = t - T_F;
      return 4.0 - A1 * s + B1 * s * s;
    } else {
      return -2.0;
    }
  }
  function aOf(t) {
    if (t <= T_F) {
      return 0.0;
    } else if (t <= T_M) {
      var s = t - T_F;
      return -A1 + 2.0 * B1 * s;
    } else {
      return 0.0;
    }
  }

  /* ================= 纯物理内核：只依据 u 计算，不碰 DOM ================= */
  function sampleAt(u) {
    var uu = u;
    if (!(uu >= 0)) { uu = 0; }
    if (uu > 1) { uu = 1; }
    var t = T_E + uu * (T_N - T_E);
    var y = yOf(t);
    var v = vOf(t);
    var a = aOf(t);
    var p = MASS * v;
    return { u: uu, t: t, y: y, v: v, a: a, p: p };
  }

  /* ---------------- 屏幕坐标映射（与 figure.html 中静态曲线所用参数一致） ---------------- */
  var TDOM0 = 8.0, TDOM1 = 55.0;
  var GX0 = 54.0, GX1 = 300.0;
  var KX = (GX1 - GX0) / (TDOM1 - TDOM0);
  function gx(t) { return GX0 + (t - TDOM0) * KX; }

  var GY_BOTTOM = 250.0, GY_TOP = 54.0, YDOM1 = 80.0;
  var KY = (GY_BOTTOM - GY_TOP) / YDOM1;
  function gy(val) { return GY_BOTTOM - val * KY; }

  var CX0 = 345.0, CX1 = 540.0;
  var KXc = (CX1 - CX0) / (TDOM1 - TDOM0);
  function chx(t) { return CX0 + (t - TDOM0) * KXc; }

  var CY_TOP = 165.0, CY_BOT = 230.0, VDOM0 = -3.0, VDOM1 = 5.0;
  var KYc = (CY_BOT - CY_TOP) / (VDOM1 - VDOM0);
  function chy(v) { return CY_BOT - (v - VDOM0) * KYc; }

  var VSCALE = 6.0;

  /* ---------------- DOM 引用 ---------------- */
  var elDrone = svg.querySelector('#q8-gen3-drone');
  var elVarrow = svg.querySelector('#q8-gen3-varrow');
  var elCursor = svg.querySelector('#q8-gen3-cursor');
  var elRoT = svg.querySelector('#q8-gen3-ro-t');
  var elRoY = svg.querySelector('#q8-gen3-ro-y');
  var elRoV = svg.querySelector('#q8-gen3-ro-v');
  var elRoA = svg.querySelector('#q8-gen3-ro-a');
  var elRoP = svg.querySelector('#q8-gen3-ro-p');
  var elStatus = svg.querySelector('#q8-gen3-status');
  var elVdot = svg.querySelector('#q8-gen3-vdot');
  var elVcursor = svg.querySelector('#q8-gen3-vcursor');

  /* ---------------- 每帧渲染：与 probe 共用 sampleAt ---------------- */
  function render(u) {
    var s = sampleAt(u);
    var px = gx(s.t), py = gy(s.y);

    elDrone.setAttribute('transform', 'translate(' + px.toFixed(2) + ',' + py.toFixed(2) + ')');

    elVarrow.setAttribute('x1', px.toFixed(2));
    elVarrow.setAttribute('y1', py.toFixed(2));
    elVarrow.setAttribute('x2', px.toFixed(2));
    elVarrow.setAttribute('y2', (py - s.v * VSCALE).toFixed(2));
    elVarrow.setAttribute('class', s.v >= 0 ? 'sa' : 'sr');

    elCursor.setAttribute('x1', px.toFixed(2));
    elCursor.setAttribute('x2', px.toFixed(2));

    elRoT.textContent = s.t.toFixed(2);
    elRoY.textContent = s.y.toFixed(2);
    elRoV.textContent = s.v.toFixed(2);
    elRoA.textContent = s.a.toFixed(2);
    elRoP.textContent = s.p.toFixed(2);

    if (s.t <= T_F + 1e-9) {
      elStatus.textContent = '当前：EF段（匀速上升，a=0）';
      elStatus.setAttribute('class', 'u a');
    } else if (s.t <= T_M + 1e-9) {
      elStatus.textContent = '当前：FM段（失重状态，a<0）';
      elStatus.setAttribute('class', 'u r');
    } else {
      elStatus.textContent = '当前：MN段（匀速下降，a=0）';
      elStatus.setAttribute('class', 'u c');
    }

    var cx = chx(s.t), cy = chy(s.v);
    elVdot.setAttribute('cx', cx.toFixed(2));
    elVdot.setAttribute('cy', cy.toFixed(2));
    elVcursor.setAttribute('x1', cx.toFixed(2));
    elVcursor.setAttribute('x2', cx.toFixed(2));
  }

  /* ---------------- 播放节奏：u 从 0 匀速播到 1，定格后循环 ---------------- */
  var ANIM_T = 6.0, T_HOLD = 1.4;
  var CYC = ANIM_T + T_HOLD;

  function step(t) {
    if (!(t >= 0)) { t = 0; }
    var tt = t - Math.floor(t / CYC) * CYC;
    var u;
    if (tt < ANIM_T) {
      u = tt / ANIM_T;
    } else {
      u = 1;
    }
    render(u);
  }

  function reset() {
    render(0);
  }

  reset();

  return {
    step: step,
    reset: reset,
    probe: function (u, caseId) {
      var s = sampleAt(u);
      return {
        u: s.u,
        t: s.t,
        y: s.y,
        v: s.v,
        a: s.a,
        p: s.p
      };
    }
  };
};
