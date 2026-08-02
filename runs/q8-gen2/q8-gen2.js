window.Scenes["q8-gen2"] = function (fig) {
  var svg = fig.querySelector('svg');

  // constants (mirrors spec/reference exactly)
  var t_E = 10.0, t_F = 20.0, t_M = 40.0, t_N = 53.0;
  var m = 2.0;

  function yOf(t) {
    if (t <= t_F) {
      return 4.0 * t - 26.0;
    } else if (t <= t_M) {
      var dt = t - t_F;
      return 54.0 + 4.0 * dt - 0.15 * dt * dt;
    } else {
      return -2.0 * t + 140.0;
    }
  }
  function vOf(t) {
    if (t <= t_F) {
      return 4.0;
    } else if (t <= t_M) {
      return 4.0 - 0.3 * (t - t_F);
    } else {
      return -2.0;
    }
  }
  function aOf(t) {
    var h = 1e-4;
    var tm = t - h, tp = t + h;
    if (tm < t_E) tm = t_E;
    if (tp > t_N) tp = t_N;
    if (tp > tm) {
      return (vOf(tp) - vOf(tm)) / (tp - tm);
    }
    return 0.0;
  }

  // coordinate maps
  function xT(t) { return 55 + (t - t_E) * (540 - 55) / (t_N - t_E); }
  function pyY(y) { return 200 - y * 2.0; }          // 0->200, 80->40
  function pyV(v) { return 275 - v * 11.25; }       // 0->275, 4->230, -2->297.5

  // element refs
  var elEF = svg.querySelector('#q8-gen2-ef');
  var elFM = svg.querySelector('#q8-gen2-fm');
  var elMN = svg.querySelector('#q8-gen2-mn');
  var elVT = svg.querySelector('#q8-gen2-vt');
  var elNow = svg.querySelector('#q8-gen2-now');
  var elDrop = svg.querySelector('#q8-gen2-drop');
  var elDrone = svg.querySelector('#q8-gen2-drone');
  var elVdot = svg.querySelector('#q8-gen2-vdot');
  var elT = svg.querySelector('#q8-gen2-txt-t');
  var elY = svg.querySelector('#q8-gen2-txt-y');
  var elV = svg.querySelector('#q8-gen2-txt-v');
  var elA = svg.querySelector('#q8-gen2-txt-a');
  var elP = svg.querySelector('#q8-gen2-txt-p');
  var elState = svg.querySelector('#q8-gen2-txt-state');

  function buildPath(x0, x1, n, yfn) {
    var d = '';
    for (var i = 0; i <= n; i++) {
      var t = x0 + (x1 - x0) * i / n;
      var x = xT(t);
      var y = pyY(yfn(t));
      d += (i === 0 ? 'M' : 'L') + x.toFixed(2) + ',' + y.toFixed(2) + ' ';
    }
    return d;
  }
  function buildVPath(x0, x1, n) {
    var d = '';
    for (var i = 0; i <= n; i++) {
      var t = x0 + (x1 - x0) * i / n;
      var x = xT(t);
      var y = pyV(vOf(t));
      d += (i === 0 ? 'M' : 'L') + x.toFixed(2) + ',' + y.toFixed(2) + ' ';
    }
    return d;
  }

  function renderStatic() {
    elEF.setAttribute('d', buildPath(t_E, t_F, 60, yOf));
    elFM.setAttribute('d', buildPath(t_F, t_M, 120, yOf));
    elMN.setAttribute('d', buildPath(t_M, t_N, 80, yOf));
    elVT.setAttribute('d', buildVPath(t_E, t_N, 200));
  }
  renderStatic();

  function fmt(x, d) {
    var s = x.toFixed(d);
    return s;
  }

  function drawAt(u) {
    var t = t_E + u * (t_N - t_E);
    var y = yOf(t);
    var v = vOf(t);
    var a = aOf(t);
    var p = m * v;

    var cx = xT(t);
    var cy = pyY(y);

    elNow.setAttribute('x1', cx.toFixed(2));
    elNow.setAttribute('x2', cx.toFixed(2));
    elNow.setAttribute('y1', (cy - 6).toFixed(2));
    elNow.setAttribute('y2', '200');

    elDrop.setAttribute('x1', cx.toFixed(2));
    elDrop.setAttribute('y1', cy.toFixed(2));
    elDrop.setAttribute('x2', cx.toFixed(2));
    elDrop.setAttribute('y2', pyV(v).toFixed(2));

    elDrone.setAttribute('transform', 'translate(' + cx.toFixed(2) + ',' + cy.toFixed(2) + ')');

    var vx = xT(t);
    var vy = pyV(v);
    elVdot.setAttribute('cx', vx.toFixed(2));
    elVdot.setAttribute('cy', vy.toFixed(2));

    elT.textContent = fmt(t, 1) + ' s';
    elY.textContent = fmt(y, 1) + ' m';
    elV.textContent = fmt(v, 2) + ' m/s';
    elA.textContent = fmt(a, 2) + ' m/s²';
    elP.textContent = fmt(p, 2) + ' kg·m/s';

    var state;
    if (t < t_F) {
      state = 'EF段匀速上升';
      elState.setAttribute('class', 'u a');
    } else if (t <= t_M) {
      state = 'FM段减速（a<0，失重）';
      elState.setAttribute('class', 'u r');
    } else {
      state = 'MN段匀速下降（a=0）';
      elState.setAttribute('class', 'u r');
    }
    elState.textContent = state;
  }

  var PERIOD = 9.0;

  return {
    step: function (t) {
      var u = (t % PERIOD) / PERIOD;
      drawAt(u);
    },
    reset: function () {
      drawAt(0);
    },
    probe: function (u, caseId) {
      var tt = t_E + u * (t_N - t_E);
      var y = yOf(tt);
      var v = vOf(tt);
      var p = m * v;
      var a = aOf(tt);
      return { u: u, t: tt, y: y, v: v, a: a, p: p };
    }
  };
};