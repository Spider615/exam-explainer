var PERIOD = 4.5;
var READOUTS = ["t", "v1", "v2", "x1"];

// ---- 纯渲染用几何常数（与 figure.html 里的静态坐标一致，不参与物理计算）----
var DEG = Math.PI / 180 * 30;
var dirx = Math.cos(DEG), diry = -Math.sin(DEG);     // 沿导轨向上（ab/R一侧）为正
var perpx = Math.sin(DEG), perpy = Math.cos(DEG);    // 垂直导轨方向
var FOOT = [80.0, 380.0];
var SCALE = 28.0;                                     // 像素/米，纯排版比例
var X0 = 4.32;                                        // cd 全程位移，spec 常量
var X1_APPROX = 2.976;                                // ab 全程位移的解析估计（仅用于初始锚点比例，不参与 probe）
var RAIL_GAP = 13.0;
var TAG_OFF = 34.0;

var sMN = 170.0;
var sCd0 = sMN - X0 * SCALE;
var sAb0 = sMN + X1_APPROX * SCALE;

function point(s) {
  return [FOOT[0] + s * dirx, FOOT[1] + s * diry];
}
function offset(p, k) {
  return [p[0] + k * perpx, p[1] + k * perpy];
}
function setLine(el, p1, p2) {
  el.setAttribute('x1', p1[0].toFixed(2));
  el.setAttribute('y1', p1[1].toFixed(2));
  el.setAttribute('x2', p2[0].toFixed(2));
  el.setAttribute('y2', p2[1].toFixed(2));
}

var MNc = point(sMN);
var Mpt = offset(MNc, RAIL_GAP);
var Npt = offset(MNc, -RAIL_GAP);

// ab/cd 标签固定在各自释放点（离MN最远处，不会被拖进M/N标签区），引出线随棒实时连接
var abTagAnchor = offset(point(sAb0), TAG_OFF);
var cdTagAnchor = offset(point(sCd0), -TAG_OFF);

var G_SIN = 5.0;   // g·sinθ，v1=0 时 a1 的精确值（直接代入 spec 给定方程，非再积分）
var A2_CONST = 6.0; // cd 的恒定加速度（代数解，与 invariants c1-a2-value 一致）

var COLLIDE_T = 0.93; // u 超过这个比例视为「碰撞进行中」，用于闪光/碰后箭头/读数的淡入

var abRod = svg.querySelector('#q13-tp-abRod');
var cdRod = svg.querySelector('#q13-tp-cdRod');
var abLead = svg.querySelector('#q13-tp-abLead');
var cdLead = svg.querySelector('#q13-tp-cdLead');
var abA1 = svg.querySelector('#q13-tp-abA1');
var cdA2 = svg.querySelector('#q13-tp-cdA2');
var Farrow = svg.querySelector('#q13-tp-Farrow');
var Fremoved = svg.querySelector('#q13-tp-Fremoved');
var flash = svg.querySelector('#q13-tp-flash');
var abPost = svg.querySelector('#q13-tp-abPost');
var cdPost = svg.querySelector('#q13-tp-cdPost');
var v1post = svg.querySelector('#q13-tp-v1post');
var v2post = svg.querySelector('#q13-tp-v2post');
var phase = svg.querySelector('#q13-tp-phase');
var QRbar = svg.querySelector('#q13-tp-QRbar');
var QRtext = svg.querySelector('#q13-tp-QRtext');

function drawFrame(ps, u, svg) {
  var p = ps['c1'];

  var sAb = sAb0 - p.x1 * SCALE;
  var sCd = sCd0 + p.x2 * SCALE;
  var abC = point(sAb);
  var cdC = point(sCd);

  setLine(abRod, offset(abC, RAIL_GAP), offset(abC, -RAIL_GAP));
  setLine(cdRod, offset(cdC, RAIL_GAP), offset(cdC, -RAIL_GAP));
  setLine(abLead, abTagAnchor, abC);
  setLine(cdLead, cdTagAnchor, cdC);
  abA1.textContent = 'a1=' + p.a1.toFixed(2) + 'm/s²';
  cdA2.textContent = 'a2=' + p.a2.toFixed(2) + 'm/s²';

  // F 箭头：随 cd 靠近 MN 而缩短，到达前自然收短
  var remain = Math.max(0, X0 - p.x2);
  var arm = Math.min(0.5, remain);
  var tip = point(sCd + arm * SCALE);
  setLine(Farrow, cdC, tip);

  var hold = Math.max(0, Math.min(1, (u - COLLIDE_T) / (1 - COLLIDE_T)));
  Farrow.setAttribute('opacity', hold > 0 ? '0' : '1');
  Fremoved.setAttribute('opacity', hold.toFixed(2));

  flash.setAttribute('r', (24 * hold).toFixed(2));
  flash.setAttribute('opacity', (0.8 * hold).toFixed(2));

  var abTip = [Mpt[0] + hold * 30 * dirx, Mpt[1] + hold * 30 * diry];
  var cdTip = [Npt[0] - hold * 30 * dirx, Npt[1] - hold * 30 * diry];
  setLine(abPost, Mpt, abTip);
  setLine(cdPost, Npt, cdTip);
  abPost.setAttribute('opacity', hold.toFixed(2));
  cdPost.setAttribute('opacity', hold.toFixed(2));

  v1post.textContent = 'v1_post=' + p.v1_post.toFixed(2) + 'm/s';
  v2post.textContent = 'v2_post=' + p.v2_post.toFixed(2) + 'm/s';
  v1post.setAttribute('opacity', hold.toFixed(2));
  v2post.setAttribute('opacity', hold.toFixed(2));

  phase.textContent = hold > 0 ? '阶段：碰撞瞬间' : '阶段：相向运动中';

  var qrFrac = Math.max(0, Math.min(1, p.QR / 0.85));
  QRbar.setAttribute('width', (150 * qrFrac).toFixed(2));
  QRtext.textContent = 'QR=' + p.QR.toFixed(3) + 'J';
}

function drawReset(svg) {
  // 完整地把画面复原到 u=0（release 瞬间）的状态，不依赖随后一定会调用 step(0)：
  // x1=x2=q=QR=0、v1=v2=0（spec.process_endpoints 给定），a1 在 v1=0 处即为 g·sinθ。
  var abC = point(sAb0);
  var cdC = point(sCd0);
  setLine(abRod, offset(abC, RAIL_GAP), offset(abC, -RAIL_GAP));
  setLine(cdRod, offset(cdC, RAIL_GAP), offset(cdC, -RAIL_GAP));
  setLine(abLead, abTagAnchor, abC);
  setLine(cdLead, cdTagAnchor, cdC);
  abA1.textContent = 'a1=' + G_SIN.toFixed(2) + 'm/s²';
  cdA2.textContent = 'a2=' + A2_CONST.toFixed(2) + 'm/s²';

  var tip = point(sCd0 + Math.min(0.5, X0) * SCALE);
  setLine(Farrow, cdC, tip);
  Farrow.setAttribute('opacity', '1');
  Fremoved.setAttribute('opacity', '0');

  flash.setAttribute('r', '0');
  flash.setAttribute('opacity', '0');
  setLine(abPost, Mpt, Mpt);
  setLine(cdPost, Npt, Npt);
  abPost.setAttribute('opacity', '0');
  cdPost.setAttribute('opacity', '0');

  v1post.setAttribute('opacity', '0');
  v2post.setAttribute('opacity', '0');

  QRbar.setAttribute('width', '0');
  QRtext.textContent = 'QR=0.000J';
  phase.textContent = '阶段：相向运动中';
}
