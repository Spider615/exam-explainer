var PERIOD = 4.0;
var READOUTS = ["i_s", "i_c", "F"];

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var cx = 255, cy = 155;
  var i, el, t;

  // 铜环随 u 增大向内收缩（半径 90 → 55）
  var r_ring = 90 - u * 35;
  svg.querySelector('#q6-gen4-ring').setAttribute('r', r_ring);

  // 磁感线被压缩：横向跨度收窄、纵向变短，虚线向中心密集
  var spread = 62 * (1 - 0.85 * u);
  var half = 100 - u * 45;
  for (i = 0; i < 9; i++) {
    t = (i - 4) / 4;
    var x = cx + t * spread;
    el = svg.querySelector('#q6-gen4-f' + i);
    el.setAttribute('x1', x);
    el.setAttribute('x2', x);
    el.setAttribute('y1', cy - half);
    el.setAttribute('y2', cy + half);
  }

  // 线圈电流：逆时针（屏幕坐标系下角度递减），箭头长度随 i_s = u 增长
  var a0 = 0, arc = u * 1.9, r = 118;
  var x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
  var a1 = a0 - arc, x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
  svg.querySelector('#q6-gen4-i_s').setAttribute('d',
    'M ' + x0.toFixed(2) + ' ' + y0.toFixed(2) +
    ' A ' + r + ' ' + r + ' 0 0 0 ' + x1.toFixed(2) + ' ' + y1.toFixed(2));

  // 铜环感应电流：顺时针（与线圈电流相反），方向在环上反向
  x0 = cx + r_ring * Math.cos(a0); y0 = cy + r_ring * Math.sin(a0);
  a1 = a0 + arc; x1 = cx + r_ring * Math.cos(a1); y1 = cy + r_ring * Math.sin(a1);
  svg.querySelector('#q6-gen4-i_c').setAttribute('d',
    'M ' + x0.toFixed(2) + ' ' + y0.toFixed(2) +
    ' A ' + r_ring + ' ' + r_ring + ' 0 0 1 ' + x1.toFixed(2) + ' ' + y1.toFixed(2));

  // 铜环标签跟随环的右缘
  svg.querySelector('#q6-gen4-l-ring').setAttribute('x', cx + r_ring + 12);
}

function drawReset(svg) {
  drawFrame(probeAll(0), 0, svg);
}
