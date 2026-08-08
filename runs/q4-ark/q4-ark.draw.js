var PERIOD = 4.0;
var READOUTS = ["v", "P", "x", "a"];

// 布局常量：OO' 边界屏幕 x、a 的最大位移对应的像素行程
var Q4 = { OO: 360, scale: 100 };

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var sx = Q4.OO + p.x * Q4.scale;          // 位移 x ∈ [0,1] → 屏幕 x
  var ra = svg.querySelector('#q4-ark-rod-a');
  ra.setAttribute('x1', sx);
  ra.setAttribute('x2', sx);
  svg.querySelector('#q4-ark-lab-a').setAttribute('x', sx);
  var v = svg.querySelector('#q4-ark-v');
  v.setAttribute('x1', sx + 8);
  v.setAttribute('x2', sx + 8 + p.v * 80);   // 速度箭头长度 ∝ v，v 从 1 减到 0
}

function drawReset(svg) {
  drawFrame(probeAll(0), 0, svg);
}
