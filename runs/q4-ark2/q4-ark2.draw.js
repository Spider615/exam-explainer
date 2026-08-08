var PERIOD = 4.0;
var READOUTS = ["v", "P", "x", "a"];
function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var sx = 180 + p.x * 160;               // 位移 0→1 映射到 x 180→340
  var rod = svg.querySelector('#q4-ark2-rod-a');
  rod.setAttribute('x', sx);
  svg.querySelector('#q4-ark2-rod-a-lab').setAttribute('x', sx + 4);
  svg.querySelector('#q4-ark2-rod-a-lab').setAttribute('y', 214);
  var v = svg.querySelector('#q4-ark2-v');
  v.setAttribute('x1', sx + 16);
  v.setAttribute('x2', sx + 16 + p.v * 40);   // 速度箭头随 v 缩短
}
function drawReset(svg) { drawFrame(probeAll(0), 0, svg); }
