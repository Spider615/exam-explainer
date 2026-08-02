window.Scenes["q14-gen2"] = function (fig) {
  var svg = fig.querySelector('svg');

  /* ---------------- 权威解（归一化 R=v0=m=1） ---------------- */
  var PI = Math.PI;
  var TA = PI / 2;                 /* N->P 用时，v=v0 */
  var TC1 = TA + PI / 4;           /* P->M 用时(v=2v0) 之后，第一次碰撞时刻 = 3πR/(4v0) */
  var TP2 = TC1 + PI / 2;          /* 碰后 M->P 用时(v=v0)，球1第二次到达P */
  var TC2 = TP2 + PI / 3;          /* 再经 t_d=πR/(3v0)，第二次碰撞时刻 = 19πR/(12v0) */
  var MB = 3.0;                    /* 由弹性碰撞方程解出的球2质量 */

  /* ---------------- 屏幕几何 ---------------- */
  var CX = 170, CY = 185, RPX = 85;

  function clamp01(x) { if (!(x > 0)) return 0; if (x > 1) return 1; return x; }

  /* 纯物理内核：u ∈ [0,1] -> 该时刻全部物理量。step 与 probe 共用此函数。 */
  function core(u) {
    var uu = clamp01(u);
    var t = uu * TC2;
    var thetaA, vA;
    if (t <= TA) { vA = 1.0; thetaA = 0 + 1.0 * t; }
    else if (t <= TC1) { vA = 2.0; thetaA = PI / 2 + 2.0 * (t - TA); }
    else if (t <= TP2) { vA = -1.0; thetaA = PI + (-1.0) * (t - TC1); }
    else { vA = -2.0; thetaA = PI / 2 + (-2.0) * (t - TP2); }

    var thetaB, vB;
    if (t <= TC1) { vB = 0.0; thetaB = PI; }
    else { vB = 1.0; thetaB = PI + 1.0 * (t - TC1); }

    var FA = vA * vA;

    return {
      u: uu, t: t,
      thetaA: thetaA, thetaB: thetaB,
      vA: vA, vB: vB, FA: FA,
      mB: MB,
      t_collision1: TC1, t_collision2: TC2,
      vA_pre_c1: 2.0, vA_post_c1: -1.0, vB_post_c1: 1.0
    };
  }

  /* ---------------- 屏幕映射（仅渲染用，不影响 probe） ---------------- */
  function ballX(theta) { return CX + RPX * Math.cos(theta); }
  function ballY(theta) { return CY - RPX * Math.sin(theta); }
  function tangentX(theta) { return -Math.sin(theta); }
  function tangentY(theta) { return -Math.cos(theta); }

  function pulse(dist, w) {
    var v = 1 - dist / w;
    if (v < 0) v = 0; if (v > 1) v = 1;
    return v;
  }

  /* ---------------- DOM 引用 ---------------- */
  var ball1 = fig.querySelector('#q14-gen2-ball1');
  var ball2 = fig.querySelector('#q14-gen2-ball2');
  var vel1 = fig.querySelector('#q14-gen2-vel1');
  var vel2 = fig.querySelector('#q14-gen2-vel2');
  var flashP = fig.querySelector('#q14-gen2-flashP');
  var flashC1 = fig.querySelector('#q14-gen2-flashC1');
  var flashC2 = fig.querySelector('#q14-gen2-flashC2');
  var lblPhase = fig.querySelector('#q14-gen2-lblPhase');
  var lblT = fig.querySelector('#q14-gen2-lblT');
  var lblAngle = fig.querySelector('#q14-gen2-lblAngle');
  var lblVA = fig.querySelector('#q14-gen2-lblVA');
  var lblVB = fig.querySelector('#q14-gen2-lblVB');
  var lblFA = fig.querySelector('#q14-gen2-lblFA');

  function setVel(line, x, y, theta, v) {
    var sp = Math.abs(v);
    var dirSign = v > 0 ? 1 : (v < 0 ? -1 : 0);
    var vlen = sp < 1e-9 ? 0 : (8 + 14 * sp);
    var dx = dirSign * tangentX(theta) * vlen;
    var dy = dirSign * tangentY(theta) * vlen;
    line.setAttribute('x1', x.toFixed(2));
    line.setAttribute('y1', y.toFixed(2));
    line.setAttribute('x2', (x + dx).toFixed(2));
    line.setAttribute('y2', (y + dy).toFixed(2));
  }

  function phaseText(t) {
    if (t <= TA) return '阶段：N→P（v=v0）';
    if (t <= TC1) return '阶段：P→M（过P后 v=2v0）';
    if (t <= TP2) return '阶段：碰后 M→P（v=-v0）';
    return '阶段：碰后再过P（v=-2v0），趋向第二次碰撞';
  }

  function draw(c) {
    var xA = ballX(c.thetaA), yA = ballY(c.thetaA);
    var xB = ballX(c.thetaB), yB = ballY(c.thetaB);
    ball1.setAttribute('cx', xA.toFixed(2));
    ball1.setAttribute('cy', yA.toFixed(2));
    ball2.setAttribute('cx', xB.toFixed(2));
    ball2.setAttribute('cy', yB.toFixed(2));
    setVel(vel1, xA, yA, c.thetaA, c.vA);
    setVel(vel2, xB, yB, c.thetaB, c.vB);

    var w = 0.12;
    var pOpac = Math.max(pulse(Math.abs(c.t - TA), w), pulse(Math.abs(c.t - TP2), w));
    flashP.setAttribute('opacity', pOpac.toFixed(2));
    flashC1.setAttribute('opacity', pulse(Math.abs(c.t - TC1), w).toFixed(2));
    flashC2.setAttribute('opacity', pulse(Math.abs(c.t - TC2), w).toFixed(2));

    lblPhase.textContent = phaseText(c.t);
    lblT.textContent = 't = ' + c.t.toFixed(2) + ' （R/v0）';
    lblAngle.textContent = 'θA=' + (c.thetaA * 180 / PI).toFixed(1) + '°　θB=' + (c.thetaB * 180 / PI).toFixed(1) + '°';
    lblVA.textContent = 'vA = ' + c.vA.toFixed(2) + ' v0';
    lblVB.textContent = 'vB = ' + c.vB.toFixed(2) + ' v0';
    lblFA.textContent = 'FA = ' + c.FA.toFixed(2) + ' (m·v0²/R)';
  }

  /* ---------------- 播放节奏（仅 step 用，不影响 probe） ---------------- */
  var ANIM = 9.0;     /* u:0->1 播放时长(秒) */
  var HOLD = 2.0;     /* 第二次碰撞后定格时长(秒) */
  var CYC = ANIM + HOLD;

  return {
    step: function (t) {
      var tt = t - Math.floor(t / CYC) * CYC;
      if (!(tt >= 0)) tt = 0;
      var frac = tt <= ANIM ? tt / ANIM : 1;
      draw(core(frac));
    },
    reset: function () {
      draw(core(0));
    },
    probe: function (u, caseId) {
      var c = core(u);
      return {
        u: c.u,
        t: c.t,
        thetaA: c.thetaA,
        thetaB: c.thetaB,
        vA: c.vA,
        vB: c.vB,
        FA: c.FA,
        mB: c.mB,
        t_collision1: c.t_collision1,
        t_collision2: c.t_collision2,
        vA_pre_c1: c.vA_pre_c1,
        vA_post_c1: c.vA_post_c1,
        vB_post_c1: c.vB_post_c1
      };
    }
  };
};
