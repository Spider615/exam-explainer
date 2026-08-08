var PERIOD = 4.0;
var READOUTS = ["t", "v1", "v2", "x1"];

var MN = { x: 260, y: 190 };
var DIR = { x: 0.8660254, y: -0.5 };   // 沿斜面向上
var NRM = { x: 0.5, y: 0.8660254 };    // 垂直于导轨方向（连接两条导轨）
var SCALE = 25;                        // px / m
var X1_MAX = 3.0 * SCALE;              // ab 释放点到MN的距离
var X2_MAX = 4.32 * SCALE;             // cd 释放点到MN的距离
var QR_MAX = 0.8;

function pt(base, dx, s) {
  return { x: base.x + dx.x * s, y: base.y + dx.y * s };
}

function setLine(el, p1, p2) {
  el.setAttribute('x1', p1.x); el.setAttribute('y1', p1.y);
  el.setAttribute('x2', p2.x); el.setAttribute('y2', p2.y);
}

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var collided = u >= 0.999;

  var remAb = Math.max(0, X1_MAX - p.x1 * SCALE);
  var remCd = Math.max(0, X2_MAX - p.x2 * SCALE);

  var abC = pt(MN, DIR, remAb);
  var cdC = pt(MN, DIR, -remCd);

  setLine(svg.querySelector('#q13-ark-ab'), pt(abC, NRM, -18), pt(abC, NRM, 18));
  svg.querySelector('#q13-ark-ab-lab').setAttribute('x', abC.x);
  svg.querySelector('#q13-ark-ab-lab').setAttribute('y', abC.y - 12);

  setLine(svg.querySelector('#q13-ark-cd'), pt(cdC, NRM, -18), pt(cdC, NRM, 18));
  svg.querySelector('#q13-ark-cd-lab').setAttribute('x', cdC.x);
  svg.querySelector('#q13-ark-cd-lab').setAttribute('y', cdC.y + 20);

  // F 箭头：碰前作用于cd，碰撞后撤去
  var fArrow = svg.querySelector('#q13-ark-F-arrow');
  var fLab = svg.querySelector('#q13-ark-F-lab');
  if (collided) {
    fArrow.setAttribute('opacity', 0);
    fLab.textContent = 'F已撤去';
    var fdone = pt(cdC, NRM, -45);
    fLab.setAttribute('x', fdone.x);
    fLab.setAttribute('y', fdone.y);
  } else {
    fArrow.setAttribute('opacity', 1);
    var fs = pt(cdC, NRM, -45);
    var fe = pt(fs, DIR, 30);
    setLine(fArrow, fs, fe);
    fLab.textContent = 'F';
    fLab.setAttribute('x', fe.x + 4);
    fLab.setAttribute('y', fe.y - 4);
  }

  // v1 v2 速度箭头
  var v1Arrow = svg.querySelector('#q13-ark-v1-arrow');
  var v2Arrow = svg.querySelector('#q13-ark-v2-arrow');
  if (!collided) {
    var v1s = pt(abC, NRM, 22);
    var v1e = pt(v1s, DIR, -Math.min(30, p.v1 * 6));
    setLine(v1Arrow, v1s, v1e);
    var v2s = pt(cdC, NRM, -22);
    var v2e = pt(v2s, DIR, Math.min(30, p.v2 * 4));
    setLine(v2Arrow, v2s, v2e);
    v1Arrow.setAttribute('opacity', 1);
    v2Arrow.setAttribute('opacity', 1);
  } else {
    var v1ps = pt(abC, NRM, 22);
    var v1pe = pt(v1ps, DIR, Math.min(30, p.v1_post * 6));
    setLine(v1Arrow, v1ps, v1pe);
    var v2ps = pt(cdC, NRM, -22);
    var v2pe = pt(v2ps, DIR, -Math.min(30, Math.abs(p.v2_post) * 4));
    setLine(v2Arrow, v2ps, v2pe);
  }

  // 碰撞闪光与碰后速度箭头
  var flash = svg.querySelector('#q13-ark-flash');
  var v1post = svg.querySelector('#q13-ark-v1post-arrow');
  var v2post = svg.querySelector('#q13-ark-v2post-arrow');
  if (collided) {
    flash.setAttribute('opacity', 0.7);
    var pe1 = pt(MN, DIR, 34);
    setLine(v1post, MN, pe1);
    v1post.setAttribute('opacity', 1);
    var pe2 = pt(MN, DIR, -34);
    setLine(v2post, MN, pe2);
    v2post.setAttribute('opacity', 1);
  } else {
    flash.setAttribute('opacity', 0);
    v1post.setAttribute('opacity', 0);
    v2post.setAttribute('opacity', 0);
  }

  // QR 进度条
  var bar = svg.querySelector('#q13-ark-QR-bar');
  var w = Math.max(0, Math.min(1, p.QR / QR_MAX)) * 140;
  bar.setAttribute('width', w);
}

function drawReset(svg) {
  drawFrame(probeAll(0), 0, svg);
}
