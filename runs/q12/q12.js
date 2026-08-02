window.Scenes["q12"] = function (fig) {
  "use strict";

  /* ---------- 物理常量（全部取自 spec，国际单位） ---------- */
  var G = 9.8;            /* m/s^2 */
  var MU_TRUE = 0.30;     /* 真动摩擦因数，用来正向造数据 */
  var D = 0.00525;        /* 遮光片宽度 5.25 mm -> m */
  var SA = 0.25;          /* 释放点到 A 门 */
  var LAB = 0.50;         /* A、B 门间距 */
  var STOT = 0.80;        /* u=1 的行程终点，> SA+LAB，滑块已越过 B 门 */

  /* ---------- 斜面几何（局部坐标：x 沿斜面向下为正，原点在斜面底端） ---------- */
  var PX0 = 296, PY0 = 252;      /* 旋转中心 = 斜面底端 */
  var SCALE = 240;               /* 像素 / 米 */
  var XREL = -222;               /* 释放点局部 x */
  var XSURF = -240;              /* 斜面上端局部 x */
  var XA = XREL + SA * SCALE;            /* A 门 -162 */
  var XB = XREL + (SA + LAB) * SCALE;    /* B 门  -42 */
  var RARC = 36;

  /* ---------- 播放节奏（step 只按 t 取模，绝无定时器） ---------- */
  var TRUN = 2.6, THOLD = 0.9, TPER = TRUN + THOLD;

  /* ---------- 右图坐标系 ---------- */
  var CL = 386, CR = 538, CT = 48, CB = 180;
  var TH_LO = 15, TH_HI = 70, MU_HI = 0.6;

  var NS = "http://www.w3.org/2000/svg";
  var DEG = Math.PI / 180;

  var slope = fig.querySelector('#q12-slope');
  var wedge = fig.querySelector('#q12-wedge');
  var arc = fig.querySelector('#q12-arc');
  var block = fig.querySelector('#q12-block');
  var beamA = fig.querySelector('#q12-beamA');
  var beamB = fig.querySelector('#q12-beamB');
  var labA = fig.querySelector('#q12-labA');
  var labB = fig.querySelector('#q12-labB');
  var labTh = fig.querySelector('#q12-labTh');
  var labRel = fig.querySelector('#q12-labRel');
  var roTheta = fig.querySelector('#q12-roTheta');
  var roA = fig.querySelector('#q12-roA');
  var roMu = fig.querySelector('#q12-roMu');
  var roAdt = fig.querySelector('#q12-roAdt');
  var roAv = fig.querySelector('#q12-roAv');
  var roBdt = fig.querySelector('#q12-roBdt');
  var roBv = fig.querySelector('#q12-roBv');
  var cursor = fig.querySelector('#q12-cursor');
  var dots = fig.querySelector('#q12-dots');
  var slider = fig.querySelector('#q12-theta');
  var thval = fig.querySelector('#q12-thval');

  var tOff = 0, lastT = 0, lastU = 0;
  var seen = {};

  /* ================= 物理内核：唯一的一份计算 =================
     a  = g(sinθ − μcosθ)
     vA = √(2a·sA)          vB = √(2a·(sA+L))
     Δt = d/v               （遮光片极窄，平均速度代替瞬时速度）
     反算 μ = tanθ − (vB²−vA²)/(2gL·cosθ)   —— 恒等于 μ_true，与 θ 无关
  ============================================================ */
  function model(thDeg) {
    var th = thDeg * DEG;
    var st = Math.sin(th), ct = Math.cos(th);
    var a = G * (st - MU_TRUE * ct);
    if (!(a > 1e-6)) a = 1e-6;        /* 防守：θ ≤ arctanμ 时不下滑，避免 NaN */
    var vA = Math.sqrt(2 * a * SA);
    var vB = Math.sqrt(2 * a * (SA + LAB));
    return {
      thDeg: thDeg, a: a, vA: vA, vB: vB,
      dtA: D / vA,                    /* 秒 */
      dtB: D / vB,                    /* 秒 */
      mu: st / ct - (vB * vB - vA * vA) / (2 * G * LAB * ct)
    };
  }

  /* u -> 位移：过程时间 t = u·T，s = ½at² ⟹ s = STOT·u²（0 起、单调不减） */
  function sOfU(u) { return STOT * u * u; }

  function thetaOfCase(caseId) {
    if (caseId === "th20") return 20;
    if (caseId === "th30") return 30;
    if (caseId === "th45") return 45;
    if (caseId === "th60") return 60;
    var p = parseFloat(String(caseId).replace(/[^0-9.]/g, ""));
    if (isFinite(p) && p > 0 && p < 90) return p;
    return 30;
  }

  /* ================= 探针：纯函数，不碰 DOM、不读滑块 ================= */
  function probe(u, caseId) {
    var uu = u;
    if (!(uu >= 0)) uu = 0;
    if (uu > 1) uu = 1;
    var th = thetaOfCase(caseId);
    var m = model(th);
    return {
      u: uu,
      theta_deg: th,
      a: m.a,
      s: sOfU(uu),
      vA: m.vA,
      vB: m.vB,
      dtA_ms: m.dtA * 1000,           /* 秒 -> 毫秒 */
      dtB_ms: m.dtB * 1000,
      mu_calc: m.mu
    };
  }

  /* ================= 渲染 ================= */
  function rot(lx, ly, thDeg) {
    var th = thDeg * DEG, ct = Math.cos(th), st = Math.sin(th);
    return [PX0 + lx * ct - ly * st, PY0 + lx * st + ly * ct];
  }
  function chx(th) { return CL + (th - TH_LO) / (TH_HI - TH_LO) * (CR - CL); }
  function chy(mu) { return CB - mu / MU_HI * (CB - CT); }
  function f(v, n) { return v.toFixed(n); }
  function put(el, x, y) {
    el.setAttribute('x', f(x, 1));
    el.setAttribute('y', f(y, 1));
  }

  function curTheta() {
    var v = slider ? parseFloat(slider.value) : 30;
    if (!isFinite(v)) v = 30;
    if (v < TH_LO + 3) v = TH_LO + 3;
    if (v > TH_HI) v = TH_HI;
    return v;
  }

  function render(u) {
    var th = curTheta();
    var m = model(th);
    var s = sOfU(u);
    var passA = s >= SA, passB = s >= SA + LAB;

    /* 斜面整体按倾角旋转 */
    slope.setAttribute('transform',
      'translate(' + PX0 + ',' + PY0 + ') rotate(' + f(th, 2) + ')');
    block.setAttribute('transform', 'translate(' + f(XREL + s * SCALE, 2) + ',0)');

    var ap = rot(XSURF, 0, th);
    wedge.setAttribute('points',
      f(ap[0], 1) + ',' + f(ap[1], 1) + ' ' +
      f(ap[0], 1) + ',' + PY0 + ' ' + PX0 + ',' + PY0);

    var ae = rot(-RARC, 0, th);
    arc.setAttribute('d', 'M ' + (PX0 - RARC) + ' ' + PY0 +
      ' A ' + RARC + ' ' + RARC + ' 0 0 1 ' + f(ae[0], 1) + ' ' + f(ae[1], 1));
    var al = (180 + th / 2) * DEG;
    put(labTh, PX0 + 52 * Math.cos(al), PY0 + 52 * Math.sin(al) + 4);

    var pa = rot(XA, -44, th), pb = rot(XB, -44, th), pr = rot(XREL - 8, -38, th);
    put(labA, pa[0], pa[1]);
    put(labB, pb[0], pb[1]);
    put(labRel, pr[0], pr[1]);

    /* 遮光反馈：滑块中心越过门后光路被切断 */
    beamA.setAttribute('class', passA ? 'sr' : 'sc');
    beamB.setAttribute('class', passB ? 'sr' : 'sc');

    roTheta.textContent = '倾角 θ = ' + f(th, 0) + '°';
    roA.textContent = 'a = ' + f(m.a, 3) + ' m/s²';
    roAdt.textContent = passA ? 'Δt = ' + f(m.dtA * 1000, 3) + ' ms' : 'Δt = —';
    roAv.textContent = passA ? 'v = ' + f(m.vA, 3) + ' m/s' : 'v = —';
    roBdt.textContent = passB ? 'Δt = ' + f(m.dtB * 1000, 3) + ' ms' : 'Δt = —';
    roBv.textContent = passB ? 'v = ' + f(m.vB, 3) + ' m/s' : 'v = —';
    roMu.textContent = passB ? '反算 μ = ' + f(m.mu, 3) : '反算 μ = —';

    var cx = chx(th);
    cursor.setAttribute('x1', f(cx, 1));
    cursor.setAttribute('x2', f(cx, 1));
    if (thval) thval.textContent = f(th, 0) + '°';

    /* 跑完一个倾角就在 μ−θ 图上打一个点 */
    if (u >= 1) {
      var key = 'k' + f(th, 0);
      if (!seen[key]) {
        seen[key] = 1;
        var c = document.createElementNS(NS, 'circle');
        c.setAttribute('cx', f(cx, 1));
        c.setAttribute('cy', f(chy(m.mu), 1));
        c.setAttribute('r', '3.4');
        c.setAttribute('class', 'fa');
        dots.appendChild(c);
      }
    }
  }

  function step(t) {
    if (!(t >= 0)) t = 0;
    lastT = t;
    var ph = t - tOff;
    if (!(ph >= 0)) ph = 0;
    ph = ph - Math.floor(ph / TPER) * TPER;      /* 循环：跑一遍 + 定格 */
    lastU = ph < TRUN ? ph / TRUN : 1;
    render(lastU);
  }

  function reset() {
    tOff = 0; lastT = 0; lastU = 0; seen = {};
    while (dots.firstChild) dots.removeChild(dots.firstChild);
    render(0);
  }

  if (slider) {
    slider.addEventListener('input', function () {
      tOff = lastT;                 /* 换倾角就从头再跑一遍 */
      lastU = 0;
      render(0);
    });
  }

  return { step: step, reset: reset, probe: probe };
};
