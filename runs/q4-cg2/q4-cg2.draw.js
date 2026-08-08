var PERIOD = 4.0;
var READOUTS = ["v", "P", "x", "a"];

// 坐标映射：x 无量纲 [0,1] → 屏幕 [100, 490]
var X0 = 100, X1 = 490;
var ARROW_MAX = 34;

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var sx = X0 + p.x * (X1 - X0);

  var rodA = svg.querySelector('#q4-cg2-rod-a');
  rodA.setAttribute('x1', sx);
  rodA.setAttribute('x2', sx);
  svg.querySelector('#q4-cg2-label-a').setAttribute('x', sx);

  // 速度箭头：起点随 a 移动，长度随 v（无量纲，v0=1）线性收缩到 0
  var vlen = Math.max(0, p.v) * ARROW_MAX;
  var varrow = svg.querySelector('#q4-cg2-varrow');
  varrow.setAttribute('x1', sx);
  varrow.setAttribute('x2', sx + vlen);
}

function drawReset(svg) {
  var rodA = svg.querySelector('#q4-cg2-rod-a');
  rodA.setAttribute('x1', X0);
  rodA.setAttribute('x2', X0);
  svg.querySelector('#q4-cg2-label-a').setAttribute('x', X0);

  var varrow = svg.querySelector('#q4-cg2-varrow');
  varrow.setAttribute('x1', X0);
  varrow.setAttribute('x2', X0 + ARROW_MAX);
}
