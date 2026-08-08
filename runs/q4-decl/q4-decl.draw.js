var PERIOD = 4.0;
var READOUTS = ["v", "x", "P"];

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]], el;
  el = svg.querySelector('#q4-decl-rod-a');
  if (el) {
    el.setAttribute('x1', 100 + p.x*390);
    el.setAttribute('x2', 100 + p.x*390);
  }
  el = svg.querySelector('#q4-decl-lab-a');
  if (el) {
    el.setAttribute('x', 100 + p.x*390);
  }
}

function drawReset(svg) { drawFrame(probeAll(0), 0, svg); }
