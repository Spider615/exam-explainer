var PERIOD = 4.5;
var READOUTS = ["t", "v1", "v2", "QR"];

// ---- 像素布局（纯渲染用，坐标沿斜面方向展开，不参与物理计算）----
var DEG = Math.PI / 6; // 30°
var DIRX = Math.cos(DEG), DIRY = -Math.sin(DEG);   // 沿导轨向上（ab/R一侧）为正
var PERPX = Math.sin(DEG), PERPY = Math.cos(DEG);  // 垂直导轨方向（画双轨间距/棒长）
var FOOT = [70, 430];   // 导轨下端（C 一侧）落地点
var SCALE = 24;         // px / m
var S_MN = 140;         // MN 在导轨方向上的位置（px）
var S_CD0 = S_MN - 4.32 * SCALE;  // cd 初始位置（x0=4.32m 是已知常量，精确）
var S_AB0 = S_MN + 2.98 * SCALE;  // ab 初始位置（2.98m 是碰前位移的估算，仅用于布局比例尺）
var RUNG = 12;          // 棒的半长（L=1m 按 SCALE 换算）
var COLLIDE_U = 0.93;   // u 超过此值视为“碰撞进行中”，用于触发闪光/反向箭头/F已撤去

function pt(s) { return [FOOT[0] + s * DIRX, FOOT[1] + s * DIRY]; }
function off(p, k) { return [p[0] + k * PERPX, p[1] + k * PERPY]; }
function setLine(el, p1, p2) {
  el.setAttribute('x1', p1[0].toFixed(2));
  el.setAttribute('y1', p1[1].toFixed(2));
  el.setAttribute('x2', p2[0].toFixed(2));
  el.setAttribute('y2', p2[1].toFixed(2));
}

var M_PT = off(pt(S_MN), RUNG);
var N_PT = off(pt(S_MN), -RUNG);

var _els = null;
function els(svg) {
  if (_els) return _els;
  _els = {
    abRod: svg.querySelector('#q13-cg1-abRod'),
    cdRod: svg.querySelector('#q13-cg1-cdRod'),
    Farrow: svg.querySelector('#q13-cg1-Farrow'),
    flash: svg.querySelector('#q13-cg1-flash'),
    abPost: svg.querySelector('#q13-cg1-abPost'),
    cdPost: svg.querySelector('#q13-cg1-cdPost'),
    phase: svg.querySelector('#q13-cg1-phase'),
    QRbar: svg.querySelector('#q13-cg1-QRbar'),
    QRval: svg.querySelector('#q13-cg1-QRval'),
    v1: svg.querySelector('#q13-cg1-v1'),
    a1: svg.querySelector('#q13-cg1-a1'),
    v2: svg.querySelector('#q13-cg1-v2'),
    a2: svg.querySelector('#q13-cg1-a2'),
    v1post: svg.querySelector('#q13-cg1-v1post'),
    v2post: svg.querySelector('#q13-cg1-v2post')
  };
  return _els;
}

function paint(ps, u, svg) {
  var p = ps[CASES[0]];
  var e = els(svg);
  var collided = u >= COLLIDE_U;
  var flashT = collided ? Math.min(1, (u - COLLIDE_U) / (1 - COLLIDE_U)) : 0;

  var sAb = S_AB0 - p.x1 * SCALE;
  var sCd = S_CD0 + p.x2 * SCALE;
  var abC = pt(sAb), cdC = pt(sCd);
  setLine(e.abRod, off(abC, RUNG), off(abC, -RUNG));
  setLine(e.cdRod, off(cdC, RUNG), off(cdC, -RUNG));

  if (!collided) {
    var remain = S_MN - sCd;
    var arm = Math.max(4, Math.min(18, remain - 2));
    setLine(e.Farrow, cdC, pt(sCd + arm));
    e.Farrow.setAttribute('opacity', '1');
  } else {
    e.Farrow.setAttribute('opacity', '0');
  }

  if (collided) {
    e.flash.setAttribute('r', (6 + 30 * flashT).toFixed(2));
    e.flash.setAttribute('opacity', (Math.max(0, 1 - flashT) * 0.9).toFixed(2));
    var grow = Math.min(1, flashT * 2.5);
    setLine(e.abPost, M_PT, [M_PT[0] + 34 * grow * DIRX, M_PT[1] + 34 * grow * DIRY]);
    setLine(e.cdPost, N_PT, [N_PT[0] - 34 * grow * DIRX, N_PT[1] - 34 * grow * DIRY]);
    e.abPost.setAttribute('opacity', '1');
    e.cdPost.setAttribute('opacity', '1');
    e.v1post.setAttribute('opacity', '1');
    e.v2post.setAttribute('opacity', '1');
    e.v1post.textContent = 'v1_post=' + p.v1_post.toFixed(2) + ' m/s';
    e.v2post.textContent = 'v2_post=' + p.v2_post.toFixed(2) + ' m/s';
  } else {
    e.flash.setAttribute('r', '0');
    e.flash.setAttribute('opacity', '0');
    setLine(e.abPost, M_PT, M_PT);
    setLine(e.cdPost, N_PT, N_PT);
    e.abPost.setAttribute('opacity', '0');
    e.cdPost.setAttribute('opacity', '0');
    e.v1post.setAttribute('opacity', '0');
    e.v2post.setAttribute('opacity', '0');
  }

  e.phase.textContent = collided ? '碰撞瞬间！F已撤去，方向反转' : 'ab、cd沿导轨相向滑动';

  e.QRbar.setAttribute('width', (200 * Math.min(p.QR / 0.78, 1)).toFixed(2));
  e.QRval.textContent = 'QR=' + p.QR.toFixed(3) + 'J';

  e.v1.textContent = 'v1=' + p.v1.toFixed(2) + ' m/s';
  e.a1.textContent = 'a1=' + p.a1.toFixed(2) + ' m/s²';
  e.v2.textContent = 'v2=' + p.v2.toFixed(2) + ' m/s';
  e.a2.textContent = 'a2=' + p.a2.toFixed(2) + ' m/s²';
}

function drawFrame(ps, u, svg) {
  paint(ps, u, svg);
}

function drawReset(svg) {
  _els = null;
  paint(probeAll(0), 0, svg);
}
