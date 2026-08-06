window.Scenes["q8-gen5"] = function (fig) {
  var svg = fig.querySelector('svg');

  var MG = 1.0;
  var M = 1.0;
  var CASES = {
    c1: { Ff: 0.5, kQq: 1.0, x0: 2.0 },
    c2: { Ff: 0.5, kQq: 0.3, x0: 2.0 }
  };

  var ROD_TOP = 56, ROD_BOTTOM = 268;
  var X_PHYS_MIN = -0.15, X_PHYS_MAX = 2.3;
  var SCALE = (ROD_BOTTOM - ROD_TOP) / (X_PHYS_MAX - X_PHYS_MIN);
  var CX1 = 96, CX2 = 246;
  var GRAPH_X0 = 316, GRAPH_X1 = 546;

  function xToY(x) { return ROD_BOTTOM - (x - X_PHYS_MIN) * SCALE; }
  function u2x(u) { return GRAPH_X0 + u * (GRAPH_X1 - GRAPH_X0); }

  var FORCE_PX = 16, FORCE_MIN = 3, FORCE_MAX = 60;
  function forceLen(mag) {
    var L = Math.abs(mag) * FORCE_PX;
    if (L < FORCE_MIN) L = FORCE_MIN;
    if (L > FORCE_MAX) L = FORCE_MAX;
    return L;
  }

  var trajCache = {};

  function computeTrajectory(caseId) {
    if (trajCache[caseId]) return trajCache[caseId];
    var p = CASES[caseId] || CASES.c1;
    var F_f = p.Ff, kQq = p.kQq, x0 = p.x0;
    var dt = 0.001;

    function netForce(x) { return -MG + kQq / (x * x); }
    function accel(x, direction) { return (-MG + kQq / (x * x) - F_f * direction) / M; }

    var x = x0, v = 0.0, t = 0.0;
    var ts = [0.0], xs = [x0], vs = [0.0];

    var f0 = netForce(x0);
    var direction, moving;
    if (Math.abs(f0) <= F_f) { direction = 0.0; moving = false; }
    else { direction = f0 > 0.0 ? 1.0 : -1.0; moving = true; }

    var as = [moving ? accel(x0, direction) : 0.0];

    var stepsInPhase = 0, totalSteps = 0;
    var maxTotalSteps = 2000000, maxPhases = 12, phasesDone = 0;

    while (moving && totalSteps < maxTotalSteps && phasesDone < maxPhases) {
      var x1 = x, v1 = v;
      var a1 = accel(x1, direction);
      var k1x = v1, k1v = a1;
      var x2 = x1 + 0.5 * dt * k1x, v2 = v1 + 0.5 * dt * k1v;
      var a2 = accel(x2, direction);
      var k2x = v2, k2v = a2;
      var x3 = x1 + 0.5 * dt * k2x, v3 = v1 + 0.5 * dt * k2v;
      var a3 = accel(x3, direction);
      var k3x = v3, k3v = a3;
      var x4 = x1 + dt * k3x, v4 = v1 + dt * k3v;
      var a4 = accel(x4, direction);
      var k4x = v4, k4v = a4;

      var xNew = x1 + (dt / 6.0) * (k1x + 2.0 * k2x + 2.0 * k3x + k4x);
      var vNew = v1 + (dt / 6.0) * (k1v + 2.0 * k2v + 2.0 * k3v + k4v);
      var tNew = t + dt;
      stepsInPhase++; totalSteps++;

      var crossed = false;
      if (stepsInPhase > 1) {
        if (direction > 0.0 && vNew <= 0.0) crossed = true;
        else if (direction < 0.0 && vNew >= 0.0) crossed = true;
      }

      if (crossed) {
        var denom = v1 - vNew;
        var frac = denom === 0.0 ? 1.0 : v1 / denom;
        if (frac < 0.0) frac = 0.0;
        if (frac > 1.0) frac = 1.0;
        var xCross = x1 + frac * (xNew - x1);
        var tCross = t + frac * dt;

        ts.push(tCross); xs.push(xCross); vs.push(0.0);

        var fCross = netForce(xCross);
        if (Math.abs(fCross) <= F_f) {
          as.push(0.0);
          x = xCross; v = 0.0; t = tCross;
          moving = false;
        } else {
          var newDirection = fCross > 0.0 ? 1.0 : -1.0;
          as.push(accel(xCross, newDirection));
          x = xCross; v = 0.0; t = tCross;
          direction = newDirection;
          phasesDone++;
          stepsInPhase = 0;
        }
      } else {
        ts.push(tNew); xs.push(xNew); vs.push(vNew);
        as.push(accel(xNew, direction));
        x = xNew; v = vNew; t = tNew;
      }
    }

    var Ttotal = ts[ts.length - 1];
    if (Ttotal <= 0.0) Ttotal = 1.0;

    var traj = { ts: ts, xs: xs, vs: vs, as: as, Ttotal: Ttotal, kQq: kQq, Ff: F_f };
    trajCache[caseId] = traj;
    return traj;
  }

  function sampleAt(traj, u) {
    if (u < 0.0) u = 0.0;
    if (u > 1.0) u = 1.0;
    var tq = u * traj.Ttotal;
    var ts = traj.ts, xs = traj.xs, vs = traj.vs, as = traj.as;
    var xi, vi, ai;
    if (tq <= ts[0]) { xi = xs[0]; vi = vs[0]; ai = as[0]; }
    else if (tq >= ts[ts.length - 1]) { xi = xs[xs.length - 1]; vi = vs[vs.length - 1]; ai = as[as.length - 1]; }
    else {
      var lo = 0, hi = ts.length - 1;
      while (hi - lo > 1) {
        var mid = Math.floor((lo + hi) / 2);
        if (ts[mid] <= tq) lo = mid; else hi = mid;
      }
      var t0 = ts[lo], t1 = ts[hi];
      var span = t1 - t0;
      var w = span <= 0.0 ? 0.0 : (tq - t0) / span;
      xi = xs[lo] + w * (xs[hi] - xs[lo]);
      vi = vs[lo] + w * (vs[hi] - vs[lo]);
      ai = as[lo] + w * (as[hi] - as[lo]);
    }
    return { x: xi, v: vi, a: ai };
  }

  function extractKeyPoints(traj) {
    var xs = traj.xs, vs = traj.vs;
    var iMinV = 0, iMaxV = 0, iMinX = 0;
    for (var i = 1; i < xs.length; i++) {
      if (vs[i] < vs[iMinV]) iMinV = i;
      if (vs[i] > vs[iMaxV]) iMaxV = i;
      if (xs[i] < xs[iMinX]) iMinX = i;
    }
    var xFinal = xs[xs.length - 1];
    var xMin = xs[iMinX];
    return {
      xMaxDescSpeed: xs[iMinV],
      xMin: xMin,
      xMaxAscSpeed: xs[iMaxV],
      xFinal: xFinal,
      hasBounce: (xFinal - xMin) > 0.05
    };
  }

  function probeCalc(u, caseId) {
    var cid = (caseId === 'c2') ? 'c2' : 'c1';
    var traj = computeTrajectory(cid);
    var s = sampleAt(traj, u);
    var Ep = traj.kQq / s.x;
    return { u: u, x: s.x, v: s.v, a: s.a, Ep: Ep };
  }

  var traj1 = computeTrajectory('c1');
  var traj2 = computeTrajectory('c2');
  var key1 = extractKeyPoints(traj1);
  var key2 = extractKeyPoints(traj2);

  var PAUSE = 1.5;
  var T1 = traj1.Ttotal, T2 = traj2.Ttotal;
  var PERIOD1 = T1 + PAUSE, PERIOD2 = T2 + PAUSE;

  var r1ball = svg.querySelector('#q8-gen5-r1-ball');
  var r1fg = svg.querySelector('#q8-gen5-r1-fg');
  var r1fc = svg.querySelector('#q8-gen5-r1-fc');
  var r1ff = svg.querySelector('#q8-gen5-r1-ff');
  var r1O = svg.querySelector('#q8-gen5-r1-O');
  var r1x0 = svg.querySelector('#q8-gen5-r1-x0tick');
  var r1tickmax = svg.querySelector('#q8-gen5-r1-tickmax');
  var r1tickmin = svg.querySelector('#q8-gen5-r1-tickmin');

  var r2ball = svg.querySelector('#q8-gen5-r2-ball');
  var r2fg = svg.querySelector('#q8-gen5-r2-fg');
  var r2fc = svg.querySelector('#q8-gen5-r2-fc');
  var r2ff = svg.querySelector('#q8-gen5-r2-ff');
  var r2O = svg.querySelector('#q8-gen5-r2-O');
  var r2x0 = svg.querySelector('#q8-gen5-r2-x0tick');
  var r2tickmax = svg.querySelector('#q8-gen5-r2-tickmax');
  var r2tickmin = svg.querySelector('#q8-gen5-r2-tickmin');
  var r2tickturn = svg.querySelector('#q8-gen5-r2-tickturn');
  var r2tickfinal = svg.querySelector('#q8-gen5-r2-tickfinal');

  var curve1 = svg.querySelector('#q8-gen5-graph-curve1');
  var curve2 = svg.querySelector('#q8-gen5-graph-curve2');
  var dot1 = svg.querySelector('#q8-gen5-graph-dot1');
  var dot2 = svg.querySelector('#q8-gen5-graph-dot2');

  var c1lmax = svg.querySelector('#q8-gen5-c1-lmax');
  var c1lmin = svg.querySelector('#q8-gen5-c1-lmin');
  var c1lfinal = svg.querySelector('#q8-gen5-c1-lfinal');
  var c1live = svg.querySelector('#q8-gen5-c1-live');

  var c2lmax = svg.querySelector('#q8-gen5-c2-lmax');
  var c2lmin = svg.querySelector('#q8-gen5-c2-lmin');
  var c2lturn = svg.querySelector('#q8-gen5-c2-lturn');
  var c2lfinal = svg.querySelector('#q8-gen5-c2-lfinal');
  var c2live = svg.querySelector('#q8-gen5-c2-live');

  function setTick(el, cx, xVal) {
    var y = xToY(xVal);
    el.setAttribute('x1', cx - 12);
    el.setAttribute('x2', cx + 12);
    el.setAttribute('y1', y);
    el.setAttribute('y2', y);
  }

  r1O.setAttribute('cx', CX1); r1O.setAttribute('cy', xToY(0));
  r2O.setAttribute('cx', CX2); r2O.setAttribute('cy', xToY(0));
  setTick(r1x0, CX1, traj1.xs[0]);
  setTick(r2x0, CX2, traj2.xs[0]);
  setTick(r1tickmax, CX1, key1.xMaxDescSpeed);
  setTick(r1tickmin, CX1, key1.xMin);
  setTick(r2tickmax, CX2, key2.xMaxDescSpeed);
  setTick(r2tickmin, CX2, key2.xMin);
  setTick(r2tickturn, CX2, key2.xMaxAscSpeed);
  setTick(r2tickfinal, CX2, key2.xFinal);

  c1lmax.textContent = '最大速度点: x1≈' + key1.xMaxDescSpeed.toFixed(2);
  c1lmin.textContent = '最低点: x_min≈' + key1.xMin.toFixed(2);
  c1lfinal.textContent = '终点: x_f≈' + key1.xFinal.toFixed(2);

  c2lmax.textContent = '下降最快点: x1≈' + key2.xMaxDescSpeed.toFixed(2);
  c2lmin.textContent = '最低点: x_min≈' + key2.xMin.toFixed(2);
  c2lturn.textContent = '回弹最快点: x_t≈' + key2.xMaxAscSpeed.toFixed(2);
  c2lfinal.textContent = '终点: x_f≈' + key2.xFinal.toFixed(2);

  function buildCurve(traj) {
    var n = 120;
    var d = '';
    for (var i = 0; i <= n; i++) {
      var u = i / n;
      var s = sampleAt(traj, u);
      var px = u2x(u), py = xToY(s.x);
      d += (i === 0 ? 'M ' : ' L ') + px.toFixed(2) + ' ' + py.toFixed(2);
    }
    return d;
  }
  curve1.setAttribute('d', buildCurve(traj1));
  curve2.setAttribute('d', buildCurve(traj2));

  function updateRod(ballEl, fgEl, fcEl, ffEl, cx, s, kQq) {
    var y = xToY(s.x);
    ballEl.setAttribute('cx', cx);
    ballEl.setAttribute('cy', y);

    var netF = -MG + kQq / (s.x * s.x);
    var coulombF = kQq / (s.x * s.x);
    var frictionF = M * s.a - netF;

    var gx = cx - 16;
    fgEl.setAttribute('x1', gx); fgEl.setAttribute('x2', gx);
    fgEl.setAttribute('y1', y); fgEl.setAttribute('y2', y + forceLen(MG));

    var cxp = cx + 16;
    fcEl.setAttribute('x1', cxp); fcEl.setAttribute('x2', cxp);
    fcEl.setAttribute('y1', y); fcEl.setAttribute('y2', y - forceLen(coulombF));

    var fx = cx + 34;
    var flen = forceLen(frictionF);
    ffEl.setAttribute('x1', fx); ffEl.setAttribute('x2', fx);
    ffEl.setAttribute('y1', y);
    ffEl.setAttribute('y2', frictionF >= 0 ? (y - flen) : (y + flen));
  }

  function render(tGlobal) {
    var tm1 = tGlobal % PERIOD1; if (tm1 < 0) tm1 += PERIOD1;
    var tm2 = tGlobal % PERIOD2; if (tm2 < 0) tm2 += PERIOD2;
    var tc1 = Math.min(tm1, T1);
    var tc2 = Math.min(tm2, T2);
    var u1 = T1 > 0 ? tc1 / T1 : 0;
    var u2 = T2 > 0 ? tc2 / T2 : 0;
    var s1 = sampleAt(traj1, u1);
    var s2 = sampleAt(traj2, u2);

    updateRod(r1ball, r1fg, r1fc, r1ff, CX1, s1, traj1.kQq);
    updateRod(r2ball, r2fg, r2fc, r2ff, CX2, s2, traj2.kQq);

    dot1.setAttribute('cx', u2x(u1)); dot1.setAttribute('cy', xToY(s1.x));
    dot2.setAttribute('cx', u2x(u2)); dot2.setAttribute('cy', xToY(s2.x));

    c1live.textContent = 'u=' + u1.toFixed(2) + ' x=' + s1.x.toFixed(2) +
      ' v=' + s1.v.toFixed(2) + ' a=' + s1.a.toFixed(2);
    c2live.textContent = 'u=' + u2.toFixed(2) + ' x=' + s2.x.toFixed(2) +
      ' v=' + s2.v.toFixed(2) + ' a=' + s2.a.toFixed(2);
  }

  render(0);

  return {
    step: function (t) { render(t); },
    reset: function () { render(0); },
    probe: function (u, caseId) { return probeCalc(u, caseId); }
  };
};
