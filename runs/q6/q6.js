window.Scenes["q6"] = function (fig) {
  var svg = fig.querySelector('svg');
  var frontEl = svg.querySelector('#q6-front');
  var depthlineEl = svg.querySelector('#q6-depthline');
  var defectEl = svg.querySelector('#q6-defect');
  var ybPath = svg.querySelector('#q6-yb');
  var ycPath = svg.querySelector('#q6-yc');
  var ysumPath = svg.querySelector('#q6-ysum');
  var cursorEl = svg.querySelector('#q6-cursor');
  var infoEl = svg.querySelector('#q6-info');

  // ---- 权威物理计算：与spec.reference逐一对应，probe与step共用同一份 ----
  function computePhysics(u) {
    var t_max = 2.3, T = 0.2, delta_t = 1.5, v = 6.3, A = 1.0;
    var t = u * t_max;
    var d = v * delta_t / 2;
    var y_b = A * Math.sin(2 * Math.PI * t / T);
    var y_c = (t < delta_t) ? 0.0 : A * Math.sin(2 * Math.PI * (t - delta_t) / T);
    var y_sum = y_b + y_c;
    var half_delta_t = delta_t / 2;
    var p;
    if (t <= half_delta_t) { p = v * t; }
    else if (t <= delta_t) { p = d - v * (t - half_delta_t); }
    else { p = 0.0; }
    return { u: u, t: t, p: p, d: d, y_b: y_b, y_c: y_c, y_sum: y_sum };
  }

  function clamp01(u) {
    if (u < 0) return 0;
    if (u > 1) return 1;
    return u;
  }

  // ---- 屏幕坐标映射（仅渲染用，不参与probe数值） ----
  var T_MAX = 2.3;
  var Y_SURF = 42, PXPERMM = 25;      // 机翼横截面：深度(mm) -> 屏幕y
  var X0 = 244, X1 = 548;             // 波形图：时间(μs) -> 屏幕x
  var PXPERUS = (X1 - X0) / T_MAX;
  var Y_B0 = 60, Y_C0 = 128, Y_SUM0 = 196, AMP = 18; // 波形图：位移(A) -> 屏幕y
  var CYCLE = 6.0; // 一次完整过程(t: 0->2.3μs)对应的播放时长，单位秒

  // 沿[0, tNow]采样一条y-t曲线，拼成延伸绘制的path（每帧根据当前时间重新计算整条曲线，无累积状态）
  function buildWavePath(tNow, key, y0, amp) {
    var n = 150;
    var d = '';
    for (var i = 0; i <= n; i++) {
      var tt = tNow * i / n;
      var ph = computePhysics(tt / T_MAX);
      var px = X0 + tt * PXPERUS;
      var py = y0 - ph[key] * amp;
      d += (i === 0 ? 'M' : 'L') + px.toFixed(2) + ' ' + py.toFixed(2) + ' ';
    }
    return d;
  }

  function render(u) {
    var phys = computePhysics(u);

    var frontY = (Y_SURF + phys.p * PXPERMM).toFixed(2);
    frontEl.setAttribute('cy', frontY);

    var defY = (Y_SURF + phys.d * PXPERMM).toFixed(2);
    depthlineEl.setAttribute('y2', defY);
    defectEl.setAttribute('y1', defY);
    defectEl.setAttribute('y2', defY);

    ybPath.setAttribute('d', buildWavePath(phys.t, 'y_b', Y_B0, AMP));
    ycPath.setAttribute('d', buildWavePath(phys.t, 'y_c', Y_C0, AMP));
    ysumPath.setAttribute('d', buildWavePath(phys.t, 'y_sum', Y_SUM0, AMP));

    var cx = (X0 + phys.t * PXPERUS).toFixed(2);
    cursorEl.setAttribute('x1', cx);
    cursorEl.setAttribute('x2', cx);

    infoEl.textContent = 't=' + phys.t.toFixed(2) + 'μs p=' + phys.p.toFixed(2) +
      'mm y_sum=' + phys.y_sum.toFixed(2);
  }

  return {
    step: function (t) {
      var u = (t % CYCLE) / CYCLE;
      render(u);
    },
    reset: function () {
      render(0);
    },
    probe: function (u, caseId) {
      return computePhysics(clamp01(u));
    }
  };
};
