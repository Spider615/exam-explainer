window.Scenes["q13-gen4"] = function (fig) {
  var svg = fig.querySelector('svg');
  var abRod = fig.querySelector('#q13-gen4-abRod');
  var cdRod = fig.querySelector('#q13-gen4-cdRod');
  var Farrow = fig.querySelector('#q13-gen4-Farrow');
  var Fremoved = fig.querySelector('#q13-gen4-Fremoved');
  var flash = fig.querySelector('#q13-gen4-flash');
  var abPost = fig.querySelector('#q13-gen4-abPost');
  var cdPost = fig.querySelector('#q13-gen4-cdPost');
  var v1Marker = fig.querySelector('#q13-gen4-v1Marker');
  var v2Marker = fig.querySelector('#q13-gen4-v2Marker');
  var infoPhase = fig.querySelector('#q13-gen4-info-phase');
  var infoV1 = fig.querySelector('#q13-gen4-info-v1');
  var infoA1 = fig.querySelector('#q13-gen4-info-a1');
  var infoV2 = fig.querySelector('#q13-gen4-info-v2');
  var infoA2 = fig.querySelector('#q13-gen4-info-a2');
  var infoT = fig.querySelector('#q13-gen4-info-t');
  var infoQR = fig.querySelector('#q13-gen4-info-QR');
  var QRbar = fig.querySelector('#q13-gen4-QRbar');
  var infoV1post = fig.querySelector('#q13-gen4-info-v1post');
  var infoV2post = fig.querySelector('#q13-gen4-info-v2post');

  // ---- 权威常数（与 spec.constants 完全一致，不得改动力的形式）----
  var B = 0.2, L = 1.0, R = 0.02, r1 = 0.08, C = 1.0;
  var m1 = 0.8, m2 = 0.4, F = 4.64, x0 = 4.32, g = 10.0, sinTheta = 0.5;

  // cd：匀加速直线运动，代数解
  var a2 = (F - m2 * g * sinTheta) / (m2 + B * B * L * L * C);
  var t1 = Math.sqrt(2.0 * x0 / a2);

  // ab：dv1/dt = g*sinθ - k*v1，数值积分（RK4，与 spec.reference 完全一致）
  var k = (B * B * L * L) / (m1 * (R + r1));
  var gSin = g * sinTheta;

  function deriv(v1) {
    var dv1 = gSin - k * v1;
    var dx1 = v1;
    var I1 = B * L * v1 / (R + r1);
    var dQR = R * I1 * I1;
    return [dv1, dx1, dQR];
  }

  function integrate(tTarget) {
    var steps = 2000;
    if (tTarget <= 0.0) return [0.0, 0.0, 0.0];
    var dt = tTarget / steps;
    var v1 = 0.0, x1 = 0.0, QR = 0.0;
    var i, k1, k2, k3, k4;
    for (i = 0; i < steps; i++) {
      k1 = deriv(v1);
      k2 = deriv(v1 + 0.5 * dt * k1[0]);
      k3 = deriv(v1 + 0.5 * dt * k2[0]);
      k4 = deriv(v1 + dt * k3[0]);
      v1 = v1 + (dt / 6.0) * (k1[0] + 2.0 * k2[0] + 2.0 * k3[0] + k4[0]);
      x1 = x1 + (dt / 6.0) * (k1[1] + 2.0 * k2[1] + 2.0 * k3[1] + k4[1]);
      QR = QR + (dt / 6.0) * (k1[2] + 2.0 * k2[2] + 2.0 * k3[2] + k4[2]);
    }
    return [v1, x1, QR];
  }

  // 碰撞时刻（u=1）的状态：只需算一次，供初始几何与碰后速度使用
  var res_t1 = integrate(t1);
  var v1_t1 = res_t1[0], x1_t1 = res_t1[1];
  var v2_t1 = a2 * t1;
  var v1_post = ((m1 - m2) * (-v1_t1) + 2.0 * m2 * v2_t1) / (m1 + m2);
  var v2_post = ((m2 - m1) * v2_t1 + 2.0 * m1 * (-v1_t1)) / (m1 + m2);

  // 纯物理函数：只依据 (u, caseId) 计算，probe 与 step 共用
  function physics(u, caseId) {
    u = Math.max(0, Math.min(1, u));
    var t = u * t1;
    var res = integrate(t);
    var v1 = res[0], x1 = res[1], QR = res[2];
    var a1 = gSin - k * v1;
    var q = B * L * x1 / (R + r1);
    var v2 = a2 * t;
    var x2 = 0.5 * a2 * t * t;
    return {
      u: u, t: t, x1: x1, v1: v1, a1: a1, x2: x2, v2: v2, a2: a2,
      q: q, QR: QR, v1_post: v1_post, v2_post: v2_post
    };
  }

  // ---- 像素布局（纯渲染用，不参与物理计算）----
  // 坡面几何：地面基线 + 30°夹角 + 竖直辅助线，双导轨沿斜面画出，
  // 与 q13-gen2（浮动导轨、右侧单栏面板）、q13-gen3（浮动导轨、反向构图、上下左右分栏）均不同：
  // 本场景额外画出完整坡面（地面/夹角弧/竖直辅助线），并在右侧加一块实时 v-t 曲线小图。
  var DEG = Math.PI / 180 * 30;
  var dirx = Math.cos(DEG), diry = -Math.sin(DEG);   // 沿导轨向上（ab/R一侧）为正
  var perpx = Math.sin(DEG), perpy = Math.cos(DEG);  // 垂直导轨方向（画双轨间距/棒长）
  var SCALE = 24.0;
  var foot = [40.0, 350.0];
  var sMN = 160.0;
  var sCd0 = sMN - x0 * SCALE;
  var sAb0 = sMN + x1_t1 * SCALE;

  function point(s) {
    return [foot[0] + s * dirx, foot[1] + s * diry];
  }
  function offset(p, kk) {
    return [p[0] + kk * perpx, p[1] + kk * perpy];
  }
  var MNc = point(sMN);
  var Mpt = offset(MNc, 12);
  var Npt = offset(MNc, -12);

  function setLine(el, p1, p2) {
    el.setAttribute('x1', p1[0].toFixed(2));
    el.setAttribute('y1', p1[1].toFixed(2));
    el.setAttribute('x2', p2[0].toFixed(2));
    el.setAttribute('y2', p2[1].toFixed(2));
  }

  // v-t 曲线小图坐标映射
  var gx0 = 370.0, gy0 = 220.0;
  var tPxPerSec = 160.0 / 1.2;
  var vPxPerUnit = 140.0 / 8.0;

  function render(u, hold) {
    var s = physics(u, 'c1');
    var collided = u >= 1;

    var sCd = sCd0 + s.x2 * SCALE;
    var sAb = sAb0 - s.x1 * SCALE;
    var abC = point(sAb);
    var cdC = point(sCd);
    setLine(abRod, offset(abC, 12), offset(abC, -12));
    setLine(cdRod, offset(cdC, 12), offset(cdC, -12));

    if (!collided) {
      // F 箭头沿导轨指向 MN，随 cd 靠近而缩短，避免越过 MN 与 M/N 标签重叠
      var remain = x0 - s.x2;
      var arm = Math.min(0.5, remain);
      var tip = point(sCd + arm * SCALE);
      setLine(Farrow, cdC, tip);
      Farrow.setAttribute('opacity', '1');
      Fremoved.setAttribute('opacity', '0');
    } else {
      Farrow.setAttribute('opacity', '0');
      Fremoved.setAttribute('opacity', '1');
    }

    if (hold > 0) {
      var hh = Math.min(hold, 1);
      flash.setAttribute('r', (10 + 26 * hh).toFixed(2));
      flash.setAttribute('opacity', (Math.max(0, 1 - hh) * 0.85).toFixed(2));

      var growth = Math.min(hold * 3, 1);
      var abTip = [Mpt[0] + 34 * growth * dirx, Mpt[1] + 34 * growth * diry];
      var cdTip = [Npt[0] - 34 * growth * dirx, Npt[1] - 34 * growth * diry];
      setLine(abPost, Mpt, abTip);
      setLine(cdPost, Npt, cdTip);
      abPost.setAttribute('opacity', '1');
      cdPost.setAttribute('opacity', '1');
    } else {
      flash.setAttribute('r', '0');
      flash.setAttribute('opacity', '0');
      setLine(abPost, Mpt, Mpt);
      setLine(cdPost, Npt, Npt);
      abPost.setAttribute('opacity', '0');
      cdPost.setAttribute('opacity', '0');
    }

    // v-t 曲线小图上的实时标记点
    var v1x = gx0 + s.t * tPxPerSec;
    var v1y = gy0 - s.v1 * vPxPerUnit;
    var v2y = gy0 - s.v2 * vPxPerUnit;
    v1Marker.setAttribute('cx', v1x.toFixed(2));
    v1Marker.setAttribute('cy', v1y.toFixed(2));
    v2Marker.setAttribute('cx', v1x.toFixed(2));
    v2Marker.setAttribute('cy', v2y.toFixed(2));

    infoPhase.textContent = collided ? '碰撞瞬间！方向反转' : '沿导轨相向运动中';
    infoV1.textContent = 'v1 = ' + s.v1.toFixed(2) + ' m/s';
    infoA1.textContent = 'a1 = ' + s.a1.toFixed(2) + ' m/s²';
    infoV2.textContent = 'v2 = ' + s.v2.toFixed(2) + ' m/s';
    infoA2.textContent = 'a2 = ' + s.a2.toFixed(2) + ' m/s²';
    infoT.textContent = 't=' + s.t.toFixed(2) + 's u=' + s.u.toFixed(2);
    infoQR.textContent = 'QR=' + s.QR.toFixed(3) + 'J';
    QRbar.setAttribute('width', (200 * Math.min(s.QR / 0.78, 1)).toFixed(2));

    if (collided) {
      infoV1post.setAttribute('opacity', '1');
      infoV2post.setAttribute('opacity', '1');
      infoV1post.textContent = 'v1_post=' + s.v1_post.toFixed(2) + ' m/s';
      infoV2post.textContent = 'v2_post=' + s.v2_post.toFixed(2) + ' m/s';
    } else {
      infoV1post.setAttribute('opacity', '0');
      infoV2post.setAttribute('opacity', '0');
    }
  }

  var ANIM_T = 3.2, HOLD_T = 1.6;
  var CYCLE = ANIM_T + HOLD_T;

  return {
    step: function (t) {
      var cyc = t % CYCLE;
      var u, hold;
      if (cyc <= ANIM_T) { u = cyc / ANIM_T; hold = 0; }
      else { u = 1; hold = (cyc - ANIM_T) / HOLD_T; }
      render(u, hold);
    },
    reset: function () {
      render(0, 0);
    },
    probe: function (u, caseId) {
      return physics(u, caseId);
    }
  };
};
