var PERIOD = 4.0;
var READOUTS = ["aP", "s_path", "yP", "t"];
function drawFrame(ps, u, svg) {
  var A = 0.1;            // 振幅 m
  var p = ps[CASES[0]];
  var yP = p.yP, vP = p.vP, aP = p.aP, s_path = p.s_path;

  var sx = 171;                       // P 固定 x 屏幕坐标（x=6m）
  var sy = 300 - (yP / A) * 60;       // 位移 -> 屏幕 y（+A=240, -A=360）

  // P 质点位置
  svg.querySelector('#q9-gen4-P').setAttribute('cy', sy);

  // P 振动轨迹（累积状态存 DOM）
  var trail = svg.querySelector('#q9-gen4-trail');
  var pts = trail.getAttribute('points') || '';
  pts += (pts ? ' ' : '') + sx + ',' + sy.toFixed(1);
  trail.setAttribute('points', pts);

  // 速度矢量（+y 向上 = 屏幕 y 减小）
  var vLen = vP * 510;                // max|v|≈0.0785 -> 40px
  var vLine = svg.querySelector('#q9-gen4-v');
  vLine.setAttribute('y1', sy);
  vLine.setAttribute('y2', sy - vLen);

  // 加速度矢量（aP=-ω²yP>0 恒指向 +y）
  var aLen = aP * 480;                // max|a|≈0.0617 -> 30px
  var aLine = svg.querySelector('#q9-gen4-a');
  aLine.setAttribute('y1', sy);
  aLine.setAttribute('y2', sy - aLen);

  // 路程累积条：0.1m -> 150px
  var pw = 70 + Math.min(s_path, 0.1) * 1500;
  svg.querySelector('#q9-gen4-path').setAttribute('x2', pw);
}
function drawReset(svg) {
  svg.querySelector('#q9-gen4-trail').setAttribute('points', '');
  drawFrame(probeAll(0), 0, svg);
}
