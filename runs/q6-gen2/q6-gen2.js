window.Scenes["q6-gen2"] = function (fig) {
  var svg = fig.querySelector('svg');
  var rodEl = svg.querySelector('#q6-gen2-rod');
  var penEl = svg.querySelector('#q6-gen2-pen');
  var xoffEl = svg.querySelector('#q6-gen2-xoffset');
  var projLineEl = svg.querySelector('#q6-gen2-projline');
  var projMarkEl = svg.querySelector('#q6-gen2-projmark');
  var traceEl = svg.querySelector('#q6-gen2-trace');
  var dotEl = svg.querySelector('#q6-gen2-graphdot');
  var tlabelEl = svg.querySelector('#q6-gen2-tlabel');
  var vtagEl = svg.querySelector('#q6-gen2-vtag');
  var svalueEl = svg.querySelector('#q6-gen2-svalue');

  // 物理常量（权威解法：ω=2πn，x=Lcosθ，v=-Lωsinθ，s=∫|v|dt，φ0=0 任取）
  var L = 0.1;
  var N_REV = 0.2;
  var OMEGA = 2 * Math.PI * N_REV;
  var PHI0 = 0.0;
  var T_MAIN = 12.5;   // 题目本身（c1）观测时长，动画展示这一情形
  var PAUSE = 1.5;     // 每轮播放结束后的定格时长，不计入物理过程
  var T_LOOP = T_MAIN + PAUSE;

  var CX = 125, CY = 150, R = 65;      // 左：轻杆转动圆的屏幕坐标
  var GX0 = 270, GX1 = 545, GT = T_MAIN; // 右：x-t图 时间轴屏幕范围
  var GY0 = 150, AMP_PX = 70, AMP_M = L;
  var PROJ_Y = 245;

  function graphX(t) { return GX0 + (t / GT) * (GX1 - GX0); }
  function graphY(x) { return GY0 - (x / AMP_M) * AMP_PX; }

  // 与 probe 共用的核心物理（纯函数，只依赖时间 t）
  function physAt(t) {
    var theta = OMEGA * t + PHI0;
    var x = L * Math.cos(theta);
    var v = -L * OMEGA * Math.sin(theta);
    return { theta: theta, x: x, v: v };
  }

  // s(t) = ∫_0^t |v(t')| dt'，梯形积分，步长与权威解法一致
  function pathAt(t) {
    if (t <= 0) return 0.0;
    var dt = 0.0005;
    var steps = Math.max(1, Math.round(t / dt));
    var h = t / steps;
    var s = 0.0;
    var prevV = Math.abs(-L * OMEGA * Math.sin(PHI0));
    for (var i = 1; i <= steps; i++) {
      var ti = i * h;
      var vi = Math.abs(-L * OMEGA * Math.sin(OMEGA * ti + PHI0));
      s += (prevV + vi) * 0.5 * h;
      prevV = vi;
    }
    return s;
  }

  var tracePts = [];
  var lastTMod = -1;

  function render(tPhys, freshLoop) {
    var st = physAt(tPhys);
    var sVal = pathAt(tPhys);

    var penX = CX + R * Math.cos(st.theta);
    var penY = CY - R * Math.sin(st.theta);
    rodEl.setAttribute('x2', penX.toFixed(2));
    rodEl.setAttribute('y2', penY.toFixed(2));
    penEl.setAttribute('cx', penX.toFixed(2));
    penEl.setAttribute('cy', penY.toFixed(2));
    xoffEl.setAttribute('y1', penY.toFixed(2));
    xoffEl.setAttribute('x2', penX.toFixed(2));
    xoffEl.setAttribute('y2', penY.toFixed(2));
    projLineEl.setAttribute('x1', penX.toFixed(2));
    projLineEl.setAttribute('y1', penY.toFixed(2));
    projLineEl.setAttribute('x2', penX.toFixed(2));
    projMarkEl.setAttribute('cx', penX.toFixed(2));

    if (freshLoop) tracePts = [];
    var gx = graphX(tPhys), gy = graphY(st.x);
    var last = tracePts.length ? tracePts[tracePts.length - 1] : null;
    if (!last || Math.abs(tPhys - last.t) > 1e-9) tracePts.push({ t: tPhys, x: gx, y: gy });
    var d = '';
    for (var i = 0; i < tracePts.length; i++) {
      var p = tracePts[i];
      d += (i === 0 ? 'M' : 'L') + p.x.toFixed(2) + ' ' + p.y.toFixed(2) + ' ';
    }
    if (!d) d = 'M' + graphX(0).toFixed(2) + ' ' + graphY(L).toFixed(2);
    traceEl.setAttribute('d', d);
    dotEl.setAttribute('cx', gx.toFixed(2));
    dotEl.setAttribute('cy', gy.toFixed(2));

    var vMax = L * OMEGA;
    var ratio = Math.abs(st.v) / vMax;
    var cls = 'fk';
    var tag = '';
    if (ratio < 0.12) { cls = 'fr'; tag = '此刻：v=0（速度为零，位移最大）'; }
    else if (ratio > 0.88) { cls = 'fa'; tag = '此刻：v最大（x=0，经过平衡位置）'; }
    penEl.setAttribute('class', cls);
    dotEl.setAttribute('class', cls);
    vtagEl.textContent = tag;

    tlabelEl.textContent = 't = ' + tPhys.toFixed(2) + ' s';
    svalueEl.textContent = sVal.toFixed(3) + ' m';
  }

  return {
    step: function (t) {
      var tMod = t % T_LOOP;
      var fresh = tMod < lastTMod - 1e-6;
      lastTMod = tMod;
      var tPhys = Math.min(tMod, T_MAIN);
      render(tPhys, fresh);
    },
    reset: function () {
      tracePts = [];
      lastTMod = -1;
      render(0, true);
    },
    probe: function (u, caseId) {
      var uu = u;
      if (uu < 0) uu = 0;
      if (uu > 1) uu = 1;
      var T_total = (caseId === 'c2') ? 7.5 : 12.5;
      var t = uu * T_total;
      var st = physAt(t);
      var s = pathAt(t);
      return { u: uu, t: t, theta: st.theta, x: st.x, v: st.v, s: s };
    }
  };
};
