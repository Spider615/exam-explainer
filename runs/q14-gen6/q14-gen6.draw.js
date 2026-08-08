var PERIOD = 4.0;
var READOUTS = ["B", "t", "vy", "vz"];
var _trailD = null;

function drawFrame(ps, u, svg) {
  if (_trailD === null) {
    var n = 240, d = [], i, q, sxx, syy;
    for (i = 0; i <= n; i++) {
      q = probeAll(i / n)[CASES[0]];
      sxx = 95 + q.x * 223;
      syy = 190 - q.y * 190;
      d.push((i ? "L" : "M") + sxx.toFixed(1) + " " + syy.toFixed(1));
    }
    _trailD = d.join(" ");
    svg.querySelector('#q14-gen6-trail').setAttribute('d', _trailD);
  } else {
    svg.querySelector('#q14-gen6-trail').setAttribute('d', _trailD);
  }

  var p = ps[CASES[0]];
  var sx = 95 + p.x * 223;
  var sy = 190 - p.y * 190;

  svg.querySelector('#q14-gen6-dot').setAttribute('cx', sx);
  svg.querySelector('#q14-gen6-dot').setAttribute('cy', sy);

  var vel = svg.querySelector('#q14-gen6-vel');
  vel.setAttribute('x1', sx);
  vel.setAttribute('y1', sy);
  vel.setAttribute('x2', sx + p.vx * 55);
  vel.setAttribute('y2', sy - p.vy * 55);
}

function drawReset(svg) {
  _trailD = null;
  drawFrame(probeAll(0), 0, svg);
}
