var PERIOD = 4.0;
var READOUTS = ["t", "v1", "v2", "x1"];

// 场景几何（屏幕坐标）
var G = {
  mx: 300, my: 210,                 // MN 连接点
  dux: 0.866, duy: -0.5,            // 上坡方向（朝右上）
  ddx: -0.866, ddy: 0.5,            // 下坡方向（朝左下）
  npx: 0.5, npy: 0.866,             // 垂直导轨
  abmax: 175, cdmax: 155            // ab/cd 出发时距 MN 的屏距
};
var MAXX1 = 0, MAXX2 = 0, MAXQR = 0.78;

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var fab = MAXX1 > 0 ? p.x1 / MAXX1 : 0;
  var fcd = MAXX2 > 0 ? p.x2 / MAXX2 : 0;
  var abx = G.mx + (1 - fab) * G.abmax * G.dux;
  var aby = G.my + (1 - fab) * G.abmax * G.duy;
  var cdx = G.mx + (1 - fcd) * G.cdmax * G.ddx;
  var cdy = G.my + (1 - fcd) * G.cdmax * G.ddy;

  // ab 棒
  var ab = svg.querySelector('#q13-ark2-ab');
  ab.setAttribute('x1', abx - 4.5); ab.setAttribute('y1', aby - 7.8);
  ab.setAttribute('x2', abx + 4.5); ab.setAttribute('y2', aby + 7.8);
  var abl = svg.querySelector('#q13-ark2-ab-lab');
  abl.setAttribute('x', abx); abl.setAttribute('y', aby - 16);

  // cd 棒
  var cd = svg.querySelector('#q13-ark2-cd');
  cd.setAttribute('x1', cdx - 4.5); cd.setAttribute('y1', cdy - 7.8);
  cd.setAttribute('x2', cdx + 4.5); cd.setAttribute('y2', cdy + 7.8);
  var cdl = svg.querySelector('#q13-ark2-cd-lab');
  cdl.setAttribute('x', cdx); cdl.setAttribute('y', cdy + 24);

  // 碰撞状态：u 接近 1 时为碰后瞬间
  var coll = u >= 0.97;

  // ab 速度箭头（碰前下滑/朝左下，碰后反向/朝右上）
  var abv = svg.querySelector('#q13-ark2-ab-v');
  var abDx = coll ? G.dux : G.ddx;
  var abDy = coll ? G.duy : G.ddy;
  var abL = 8 + p.v1 * 2.6; if (abL > 26) abL = 26;
  var abOx = abx + 14 * G.npx, abOy = aby + 14 * G.npy;
  abv.setAttribute('x1', abOx); abv.setAttribute('y1', abOy);
  abv.setAttribute('x2', abOx + abDx * abL); abv.setAttribute('y2', abOy + abDy * abL);

  // cd 速度箭头（碰前上滑/朝右上，碰后反向/朝左下）
  var cdv = svg.querySelector('#q13-ark2-cd-v');
  var cdDx = coll ? G.ddx : G.dux;
  var cdDy = coll ? G.ddy : G.duy;
  var cdL = 8 + p.v2 * 2.6; if (cdL > 26) cdL = 26;
  var cdOx = cdx - 14 * G.npx, cdOy = cdy - 14 * G.npy;
  cdv.setAttribute('x1', cdOx); cdv.setAttribute('y1', cdOy);
  cdv.setAttribute('x2', cdOx + cdDx * cdL); cdv.setAttribute('y2', cdOy + cdDy * cdL);

  // 恒力 F：指向 MN（上坡方向），碰前撤去并标注
  var f = svg.querySelector('#q13-ark2-f');
  var flab = svg.querySelector('#q13-ark2-f-lab');
  var fg = svg.querySelector('#q13-ark2-fgone');
  if (coll) {
    f.setAttribute('opacity', 0); flab.setAttribute('opacity', 0);
    fg.setAttribute('opacity', 1);
  } else {
    f.setAttribute('opacity', 1); flab.setAttribute('opacity', 1);
    fg.setAttribute('opacity', 0);
    var fo = cdx + 8 * G.npx, foy = cdy + 8 * G.npy;
    f.setAttribute('x1', fo); f.setAttribute('y1', foy);
    f.setAttribute('x2', fo + G.dux * 30); f.setAttribute('y2', foy + G.duy * 30);
    flab.setAttribute('x', fo + G.dux * 32); flab.setAttribute('y', foy + G.duy * 32);
  }

  // 实时加速度
  svg.querySelector('#q13-ark2-a1').textContent = p.a1.toFixed(1) + ' m/s²';
  svg.querySelector('#q13-ark2-a2').textContent = p.a2.toFixed(1) + ' m/s²';

  // R 上焦耳热 QR 进度条
  var qf = svg.querySelector('#q13-ark2-qrfill');
  var w = MAXQR > 0 ? (p.QR / MAXQR) * 240 : 0; if (w < 0) w = 0;
  qf.setAttribute('width', w);
  svg.querySelector('#q13-ark2-qrval').textContent = p.QR.toFixed(2) + ' J';

  // 碰撞闪光
  var k = (u - 0.9) / 0.1; if (k < 0) k = 0; if (k > 1) k = 1;
  var flash = svg.querySelector('#q13-ark2-flash');
  flash.setAttribute('opacity', k * 0.9);

  // 碰后瞬时速度
  var ct = svg.querySelector('#q13-ark2-collide');
  if (coll) {
    ct.textContent = '弹性碰撞！碰后 v1′=' + Math.abs(p.v1_post).toFixed(1)
      + ' m/s(向' + (p.v1_post >= 0 ? '上' : '下') + ')  v2′=' + Math.abs(p.v2_post).toFixed(1)
      + ' m/s(向' + (p.v2_post >= 0 ? '上' : '下') + ')';
    ct.setAttribute('opacity', 1);
  } else {
    ct.setAttribute('opacity', 0);
  }
}

function drawReset(svg) {
  var end = probeAll(1)[CASES[0]];
  MAXX1 = end.x1; MAXX2 = end.x2; MAXQR = end.QR;
  drawFrame(probeAll(0), 0, svg);
}
