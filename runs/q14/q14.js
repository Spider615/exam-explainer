window.Scenes["q14"] = function (fig) {
  /* ---------------- 物理常量（国际单位制） ---------------- */
  var B = 0.1;                 /* T */
  var V = 96000.0;             /* m/s, 即 9.6e4 */
  var QM1 = 4800000.0;         /* C/kg, 即 4.8e6 —— 打在 M 的离子 */
  var K = 1.1;                 /* ON / OM */

  /* qvB = mv^2/r  ->  r = v / [(q/m)B] */
  var R1 = V / (QM1 * B);                 /* 0.20 m */
  /* 垂直边界入射 -> 圆心在边界上 -> 落点距 O 等于直径；ON = 1.1 OM -> r2 = 1.1 r1 */
  var R2 = K * R1;                        /* 0.22 m */
  var QM2 = V / (R2 * B);                 /* = QM1/1.1 约 4.36e6 C/kg，比荷更小 */

  var W1 = QM1 * B;                       /* 回旋角速度 rad/s */
  var W2 = QM2 * B;
  var TH1 = Math.PI / W1;                 /* 半圆用时 s，与速率无关 */
  var TH2 = Math.PI / W2;                 /* 比荷小者周期长 1.1 倍 -> 后到达 */
  var PI = Math.PI;

  /* ---------------- 屏幕几何 ---------------- */
  var YB = 272;                /* 边界 PP' 的 y */
  var XO = 112;                /* 入射点 O 的 x */
  var PXM = 750;               /* px per meter */
  var P1 = R1 * PXM;           /* 150 px */
  var P2 = R2 * PXM;           /* 165 px */
  var C1 = XO + P1;            /* 圆心 1 在边界上 */
  var C2 = XO + P2;
  var VLEN = 30;               /* 速度矢量画长 px */
  var FLEN = 26;               /* 洛伦兹力矢量画长 px */

  /* ---------------- 动画节奏（step 用，不影响 probe） ---------------- */
  var SLOW = 500000;                 /* 慢放倍数 5e5 */
  var DUR = SLOW * TH2;              /* 弧段时长约 3.60 s */
  var HOLD = 1.6;                    /* 走完后定格 */
  var CYC = DUR + HOLD;

  /* ---------------- DOM 引用 ---------------- */
  var arc1 = fig.querySelector('#q14-arc1');
  var arc2 = fig.querySelector('#q14-arc2');
  var ion1 = fig.querySelector('#q14-ion1');
  var ion2 = fig.querySelector('#q14-ion2');
  var vv1 = fig.querySelector('#q14-v1');
  var vv2 = fig.querySelector('#q14-v2');
  var ff1 = fig.querySelector('#q14-f1');
  var ff2 = fig.querySelector('#q14-f2');
  var rd1 = fig.querySelector('#q14-rad1');
  var rd2 = fig.querySelector('#q14-rad2');
  var lb1 = fig.querySelector('#q14-lb1');
  var lb2 = fig.querySelector('#q14-lb2');
  var tx1 = fig.querySelector('#q14-th1');
  var tx2 = fig.querySelector('#q14-th2');
  var sx1 = fig.querySelector('#q14-st1');
  var sx2 = fig.querySelector('#q14-st2');
  var txT = fig.querySelector('#q14-time');

  /* ---------------- 纯物理内核 ---------------- */
  /* u = 0 两离子同时射入；u = 1 较慢的 2 号离子刚好到达边界 N。
     故 t(u) = u * TH2；1 号离子在 u = 1/1.1 就已到达 M，之后角度保持 PI。 */
  function core(u) {
    var uu = u;
    if (!(uu > 0)) uu = 0;
    if (uu > 1) uu = 1;
    var t = uu * TH2;
    var a1 = W1 * t;
    var a2 = W2 * t;
    if (a1 > PI) a1 = PI;
    if (a2 > PI) a2 = PI;
    return { u: uu, t: t, a1: a1, a2: a2 };
  }

  function px(cx, rr, a) { return cx - rr * Math.cos(a); }
  function py(rr, a) { return YB - rr * Math.sin(a); }

  function arcPath(cx, rr, a) {
    var n = 72, i, th, s = '';
    for (i = 0; i <= n; i++) {
      th = a * i / n;
      s += (i === 0 ? 'M' : ' L') + px(cx, rr, th).toFixed(2) + ' ' + py(rr, th).toFixed(2);
    }
    return s;
  }

  function seg(el, x1, y1, x2, y2) {
    el.setAttribute('x1', x1.toFixed(2));
    el.setAttribute('y1', y1.toFixed(2));
    el.setAttribute('x2', x2.toFixed(2));
    el.setAttribute('y2', y2.toFixed(2));
  }

  /* 一个离子的全部图元更新 */
  function one(a, cx, rr, arc, dot, vel, frc, rad, lab, ldx, ldy) {
    var x = px(cx, rr, a), y = py(rr, a);
    /* 切向单位矢量（屏幕坐标，y 向下） */
    var vx = Math.sin(a), vy = -Math.cos(a);
    /* 指向圆心的单位矢量 */
    var fx = Math.cos(a), fy = Math.sin(a);
    var landed = a >= PI - 1e-12;

    arc.setAttribute('d', arcPath(cx, rr, a));
    dot.setAttribute('cx', x.toFixed(2));
    dot.setAttribute('cy', y.toFixed(2));
    seg(vel, x, y, x + vx * VLEN, y + vy * VLEN);
    seg(frc, x, y, x + fx * FLEN, y + fy * FLEN);
    seg(rad, cx, YB, x, y);
    frc.setAttribute('opacity', landed ? '0' : '1');
    lab.setAttribute('x', (x + vx * VLEN + ldx).toFixed(2));
    lab.setAttribute('y', (y + vy * VLEN + ldy).toFixed(2));
  }

  function deg(a) { return a * 180 / PI; }

  function draw(u) {
    var c = core(u);
    one(c.a1, C1, P1, arc1, ion1, vv1, ff1, rd1, lb1, 8, 1);
    one(c.a2, C2, P2, arc2, ion2, vv2, ff2, rd2, lb2, -24, -3);
    tx1.textContent = 'θ₁ = ' + deg(c.a1).toFixed(1) + '°';
    tx2.textContent = 'θ₂ = ' + deg(c.a2).toFixed(1) + '°';
    sx1.textContent = (c.a1 >= PI - 1e-12) ? '已到达 M' : '飞行中';
    sx2.textContent = (c.a2 >= PI - 1e-12) ? '已到达 N' : '飞行中';
    txT.textContent = 't = ' + (c.t * 1e6).toFixed(2) + ' μs（慢放 5×10⁵ 倍）';
  }

  return {
    step: function (t) {
      var tt = t - Math.floor(t / CYC) * CYC;
      if (!(tt >= 0)) tt = 0;
      var u = tt / DUR;
      if (u > 1) u = 1;
      draw(u);
    },
    reset: function () {
      draw(0);
    },
    probe: function (u, caseId) {
      var c = core(u);
      return {
        u: c.u,
        t_us: c.t * 1e6,
        th1_deg: deg(c.a1),
        th2_deg: deg(c.a2),
        r1: R1,
        r2: R2,
        qm1: QM1,
        qm2: QM2
      };
    }
  };
};
