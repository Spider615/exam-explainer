var PERIOD = 4.0;
var READOUTS = ["v", "x", "P"];

// 坐标映射：x 无量纲 [0,1] → 屏幕 [100, 490]
var X0 = 100, X1 = 490;

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var sx = X0 + p.x * (X1 - X0);
  svg.querySelector('#q4-cg-rod-a').setAttribute('x1', sx);
  svg.querySelector('#q4-cg-rod-a').setAttribute('x2', sx);
  svg.querySelector('#q4-cg-label-a').setAttribute('x', sx);
}

function drawReset(svg) {
  var a = svg.querySelector('#q4-cg-rod-a');
  a.setAttribute('x1', X0); a.setAttribute('x2', X0);
  svg.querySelector('#q4-cg-label-a').setAttribute('x', X0);
}
