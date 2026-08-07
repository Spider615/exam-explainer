window.Scenes["q19-gen2"] = function (fig) {
  var svg = fig.querySelector('svg');

  var m = 1.0, q = 1.0, B = 1.0, v0 = 1.0;
  var R = m * v0 / (q * B);
  var PI = Math.PI;

  // ---------------------------------------------------------------- 物理核心（与 spec.physics.reference 完全一致）
  // 区域Ⅰ、Ⅱ：磁场垂直纸面向外，正电荷顺时针转动
  // 区域Ⅲ：漂移 v_drift=(0,v0) 叠加绕导向中心逆时针的圆周分量 v_circ
  function calcC1(u) {
    var omega1 = q * B / m;
    var omega2 = q * B / (2 * m);
    var tBoundary = PI / (2 * omega1);
    var tTotal = tBoundary + PI / (2 * omega2);
    var t = u * tTotal;
    var x, y, vx, vy;
    if (t <= tBoundary) {
      var tau = t;
      var phi1 = PI - omega1 * tau;
      x = 2 * R + R * Math.cos(phi1);
      y = R * Math.sin(phi1);
      vx = R * omega1 * Math.sin(phi1);
      vy = -R * omega1 * Math.cos(phi1);
    } else {
      var tau2 = t - tBoundary;
      var r2 = 2 * R;
      var phi2 = PI / 2 - omega2 * tau2;
      x = 2 * R + r2 * Math.cos(phi2);
      y = -R + r2 * Math.sin(phi2);
      vx = r2 * omega2 * Math.sin(phi2);
      vy = -r2 * omega2 * Math.cos(phi2);
    }
    var speed = Math.sqrt(vx * vx + vy * vy);
    return { u: u, t: t, x: x, y: y, vx: vx, vy: vy, speed: speed, m: m, q: q, B: B, v0: v0, R: R };
  }

  function calcC2(u) {
    var omega3 = q * B / m;
    var thetaTotal = 286.0 * PI / 180.0;
    var theta = u * thetaTotal;
    var t = theta / omega3;
    var a = 24.0 * v0 / 25.0;
    var b = -32.0 * v0 / 25.0;
    var vcx = a * Math.cos(theta) - b * Math.sin(theta);
    var vcy = a * Math.sin(theta) + b * Math.cos(theta);
    var vx = vcx;
    var vy = v0 + vcy;
    var speed = Math.sqrt(vx * vx + vy * vy);
    var x = 4 * R + (a * Math.sin(theta) + b * Math.cos(theta) - b) / omega3;
    var y0 = 0.0;
    var y = y0 + v0 * t + (a * (1 - Math.cos(theta)) + b * Math.sin(theta)) / omega3;
    return { u: u, t: t, x: x, y: y, vx: vx, vy: vy, speed: speed, m: m, q: q, B: B, v0: v0, R: R };
  }

  function probeCalc(u, caseId) {
    if (caseId === 'c2') return calcC2(u);
    return calcC1(u);
  }

  // ---------------------------------------------------------------- 屏幕映射
  // 主图（区域Ⅰ、Ⅱ）：常规世界坐标 x 右 y 上
  var S1 = 44, OX1 = 80, OY1 = 230;
  function mx(x) { return OX1 + S1 * x; }
  function my(y) { return OY1 - S1 * y; }

  // 区域Ⅲ展开图：横轴 = 沿 MN 的漂移方向(世界 y)，纵轴 = 深入区域Ⅲ的深度(世界 x-4R)。
  // 区域Ⅲ内粒子沿 y 方向的漂移远大于 x 方向摆动，故旋转 90° 展开以适应画布，比例尺与主图不同。
  var S3 = 46, OX3 = 70, OY3 = 406;
  function ix(yWorld) { return OX3 + S3 * yWorld; }
  function iy(xWorld) { return OY3 + S3 * (xWorld - 4 * R); }

  function pathFromPoints(pts) {
    var d = '';
    for (var i = 0; i < pts.length; i++) {
      d += (i === 0 ? 'M ' : ' L ') + pts[i][0].toFixed(2) + ' ' + pts[i][1].toFixed(2);
    }
    return d;
  }

  // ---------------------------------------------------------------- 静态几何（构造时算一次）
  var regionIIpath = svg.querySelector('#q19-gen2-regionII-boundary');
  (function buildRegionII() {
    var pts = [];
    for (var k = 0; k <= 32; k++) {
      var betaDeg = 90 + 180 * (k / 32);
      var betaRad = betaDeg * PI / 180;
      var wx = 4 * R + 2 * R * Math.cos(betaRad);
      var wy = 1 * R + 2 * R * Math.sin(betaRad);
      pts.push([mx(wx), my(wy)]);
    }
    regionIIpath.setAttribute('d', pathFromPoints(pts) + ' Z');
  })();

  var c1FullPath = svg.querySelector('#q19-gen2-c1-fullpath');
  (function buildC1Full() {
    var pts = [];
    for (var i = 0; i <= 40; i++) {
      var s = calcC1(i / 40);
      pts.push([mx(s.x), my(s.y)]);
    }
    c1FullPath.setAttribute('d', pathFromPoints(pts));
  })();

  var c2FullPath = svg.querySelector('#q19-gen2-c2-fullpath');
  (function buildC2Full() {
    var pts = [];
    for (var i = 0; i <= 60; i++) {
      var s = calcC2(i / 60);
      pts.push([ix(s.y), iy(s.x)]);
    }
    c2FullPath.setAttribute('d', pathFromPoints(pts));
  })();

  // 区域Ⅲ入射点(u=0)：静态标注入射角与参考方向(世界 -y 方向)
  var entryMark = svg.querySelector('#q19-gen2-c2-entrymark');
  var entryArrow = svg.querySelector('#q19-gen2-c2-entryarrow');
  var entryRef = svg.querySelector('#q19-gen2-c2-refline');
  (function buildEntry() {
    var e = calcC2(0);
    var ex = ix(e.y), ey = iy(e.x);
    entryMark.setAttribute('cx', ex); entryMark.setAttribute('cy', ey);
    var alen = 34;
    entryArrow.setAttribute('x1', ex); entryArrow.setAttribute('y1', ey);
    entryArrow.setAttribute('x2', ex + e.vy * alen); entryArrow.setAttribute('y2', ey + e.vx * alen);
    entryRef.setAttribute('x1', ex); entryRef.setAttribute('y1', ey);
    entryRef.setAttribute('x2', ex); entryRef.setAttribute('y2', ey + 30);
  })();

  // 动能最大点(u=0.5)：静态标注
  var maxMark = svg.querySelector('#q19-gen2-c2-maxmark');
  var maxLine = svg.querySelector('#q19-gen2-c2-maxline');
  (function buildMax() {
    var s = calcC2(0.5);
    var mxp = ix(s.y), myp = iy(s.x);
    maxMark.setAttribute('cx', mxp); maxMark.setAttribute('cy', myp);
    maxLine.setAttribute('x1', OX3 - 10); maxLine.setAttribute('x2', 405);
    maxLine.setAttribute('y1', myp); maxLine.setAttribute('y2', myp);
  })();

  // ---------------------------------------------------------------- 动态引用
  var c1dot = svg.querySelector('#q19-gen2-c1-dot');
  var c1progress = svg.querySelector('#q19-gen2-c1-progress');
  var c1varrow = svg.querySelector('#q19-gen2-c1-varrow');
  var c1live = svg.querySelector('#q19-gen2-c1-live');

  var c2dot = svg.querySelector('#q19-gen2-c2-dot');
  var c2gc = svg.querySelector('#q19-gen2-c2-gc');
  var c2radius = svg.querySelector('#q19-gen2-c2-radius');
  var c2progress = svg.querySelector('#q19-gen2-c2-progress');
  var c2varrow = svg.querySelector('#q19-gen2-c2-varrow');
  var c2live = svg.querySelector('#q19-gen2-c2-live');

  // ---------------------------------------------------------------- 动画时序（播放节奏与真实物理时间无关，只影响观感）
  var PLAY1 = 3.8, PAUSE1 = 1.0, PERIOD1 = PLAY1 + PAUSE1;
  var PLAY2 = 5.2, PAUSE2 = 1.2, PERIOD2 = PLAY2 + PAUSE2;

  function fmod(a, n) { var r = a % n; if (r < 0) r += n; return r; }

  function render(t) {
    var tm1 = fmod(t, PERIOD1);
    var u1 = Math.min(tm1, PLAY1) / PLAY1;
    var tm2 = fmod(t, PERIOD2);
    var u2 = Math.min(tm2, PLAY2) / PLAY2;

    var s1 = calcC1(u1);
    var p1x = mx(s1.x), p1y = my(s1.y);
    c1dot.setAttribute('cx', p1x); c1dot.setAttribute('cy', p1y);
    var k1 = 18;
    c1varrow.setAttribute('x1', p1x); c1varrow.setAttribute('y1', p1y);
    c1varrow.setAttribute('x2', p1x + s1.vx * k1); c1varrow.setAttribute('y2', p1y - s1.vy * k1);
    var pts1 = [];
    var n1 = Math.max(2, Math.round(28 * u1));
    for (var i1 = 0; i1 <= n1; i1++) {
      var uu1 = (u1 * i1) / n1;
      var ss1 = calcC1(uu1);
      pts1.push([mx(ss1.x), my(ss1.y)]);
    }
    c1progress.setAttribute('d', pts1.length ? pathFromPoints(pts1) : '');
    c1live.textContent = 'u=' + u1.toFixed(2) + ' t=' + s1.t.toFixed(2) +
      ' x=' + s1.x.toFixed(2) + ' y=' + s1.y.toFixed(2) + ' v=' + s1.speed.toFixed(2);

    var s2 = calcC2(u2);
    var p2x = ix(s2.y), p2y = iy(s2.x);
    c2dot.setAttribute('cx', p2x); c2dot.setAttribute('cy', p2y);

    var omega3 = q * B / m;
    var vcx2 = s2.vx;
    var vcy2 = s2.vy - v0;
    var rx = vcy2 / omega3;
    var ry = -vcx2 / omega3;
    var gcxWorld = s2.x - rx;
    var gcyWorld = s2.y - ry;
    var gcx = ix(gcyWorld), gcy = iy(gcxWorld);
    c2gc.setAttribute('cx', gcx); c2gc.setAttribute('cy', gcy);
    c2radius.setAttribute('x1', gcx); c2radius.setAttribute('y1', gcy);
    c2radius.setAttribute('x2', p2x); c2radius.setAttribute('y2', p2y);

    var k2 = 10;
    c2varrow.setAttribute('x1', p2x); c2varrow.setAttribute('y1', p2y);
    c2varrow.setAttribute('x2', p2x + s2.vy * k2); c2varrow.setAttribute('y2', p2y + s2.vx * k2);

    var pts2 = [];
    var n2 = Math.max(2, Math.round(40 * u2));
    for (var i2 = 0; i2 <= n2; i2++) {
      var uu2 = (u2 * i2) / n2;
      var ss2 = calcC2(uu2);
      pts2.push([ix(ss2.y), iy(ss2.x)]);
    }
    c2progress.setAttribute('d', pts2.length ? pathFromPoints(pts2) : '');
    c2live.textContent = 'u=' + u2.toFixed(2) + ' t=' + s2.t.toFixed(2) +
      ' x=' + s2.x.toFixed(2) + ' y=' + s2.y.toFixed(2) + ' v=' + s2.speed.toFixed(2);
  }

  render(0);

  return {
    step: function (t) { render(t); },
    reset: function () { render(0); },
    probe: function (u, caseId) { return probeCalc(u, caseId); }
  };
};
