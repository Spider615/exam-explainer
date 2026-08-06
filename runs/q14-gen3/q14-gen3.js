window.Scenes["q14-gen3"] = function (fig) {
  var svg = fig.querySelector('svg');
  var PI = Math.PI;

  /* ---------------- 权威解（与 spec.physics.constants / reference 完全一致） ---------------- */
  var L = 1.0, B = 1.0, OMEGA = 1.0, R = 1.0;
  var GACC = 10.0, MASS = 0.15, MU = 0.19245008972987526;
  var THETA = PI / 6;
  var TAU = 0.15, V0 = 1.0, VEQ = 0.5;
  var T_C1 = PI / 2, T_C2 = 1.5;

  function clamp01(x) { if (!(x > 0)) return 0; if (x > 1) return 1; return x; }

  /* case c1 纯物理内核：phi(u)=(pi/2)u，l 按 F1 分段公式，F=B^2*L*omega*l^2/(2R) */
  function coreC1(u) {
    var uu = clamp01(u);
    var phi = T_C1 * uu;
    var l;
    if (phi <= PI / 4) l = L / Math.cos(phi);
    else l = L / Math.sin(phi);
    var E = 0.5 * B * OMEGA * l * l;
    var I = E / R;
    var F = B * I * L;
    return { u: uu, t: phi, phi: phi, l: l, F: F, v: 0, a: 0, x: 0, f: 0 };
  }

  /* case c2 纯物理内核：v(t) 指数趋于 v_eq，a=dv/dt，x=积分，f 恒定，F=B^2*L^2*v/R */
  function coreC2(u) {
    var uu = clamp01(u);
    var t = T_C2 * uu;
    var expTerm = Math.exp(-t / TAU);
    var v = VEQ + (V0 - VEQ) * expTerm;
    var a = -(V0 - VEQ) / TAU * expTerm;
    var x = VEQ * t + (V0 - VEQ) * TAU * (1 - expTerm);
    var f = MU * MASS * GACC * Math.cos(THETA);
    var F = B * B * L * L * v / R;
    return { u: uu, t: t, phi: 0, l: 0, F: F, v: v, a: a, x: x, f: f };
  }

  /* ---------------- 屏幕几何（仅渲染用，需与 gen_figure.py 的初始占位坐标一致） ---------------- */
  var O_X = 150, O_Y = 195, SCALE1 = 62;
  var GX = 70, GY = 538;
  var DIRX = Math.cos(THETA), DIRY = -Math.sin(THETA);
  var PERPX = -DIRY, PERPY = DIRX;
  var D0 = 200, PXPERM = 150;

  var BARX = 480, BARBOT = 280, BARTOP = 170;
  var BARSCALE = (BARBOT - BARTOP) / 1.2;

  /* ---------------- DOM 引用 ---------------- */
  var oaLine = fig.querySelector('#q14-gen3-oaLine');
  var contactP = fig.querySelector('#q14-gen3-contactP');
  var lblA = fig.querySelector('#q14-gen3-lblA');
  var lblLgeo = fig.querySelector('#q14-gen3-lblLgeo');
  var c1PhiLbl = fig.querySelector('#q14-gen3-c1PhiLbl');
  var c1LLbl = fig.querySelector('#q14-gen3-c1LLbl');
  var c1FLbl = fig.querySelector('#q14-gen3-c1FLbl');
  var c1BarF = fig.querySelector('#q14-gen3-c1BarF');

  var cdBar = fig.querySelector('#q14-gen3-cdBar');
  var cdDot = fig.querySelector('#q14-gen3-cdDot');
  var arrowG = fig.querySelector('#q14-gen3-arrowG');
  var arrowF = fig.querySelector('#q14-gen3-arrowF');
  var arrowFric = fig.querySelector('#q14-gen3-arrowFric');
  var c2TLbl = fig.querySelector('#q14-gen3-c2TLbl');
  var c2VLbl = fig.querySelector('#q14-gen3-c2VLbl');
  var c2ALbl = fig.querySelector('#q14-gen3-c2ALbl');
  var c2XLbl = fig.querySelector('#q14-gen3-c2XLbl');
  var c2FLbl = fig.querySelector('#q14-gen3-c2FLbl');
  var c2FricLbl = fig.querySelector('#q14-gen3-c2FricLbl');

  function flen(v) { return 25 + 35 * v; }

  function drawC1(c) {
    var x = O_X + SCALE1 * c.l * Math.cos(c.phi);
    var y = O_Y - SCALE1 * c.l * Math.sin(c.phi);
    oaLine.setAttribute('x2', x.toFixed(2));
    oaLine.setAttribute('y2', y.toFixed(2));
    contactP.setAttribute('cx', x.toFixed(2));
    contactP.setAttribute('cy', y.toFixed(2));
    lblA.setAttribute('x', (x + 6).toFixed(2));
    lblA.setAttribute('y', (y - 6).toFixed(2));
    var mx = (O_X + x) / 2, my = (O_Y + y) / 2;
    lblLgeo.setAttribute('x', (mx + 4).toFixed(2));
    lblLgeo.setAttribute('y', (my - 6).toFixed(2));
    lblLgeo.textContent = 'l=' + c.l.toFixed(2);

    c1PhiLbl.textContent = 'φ = ' + c.phi.toFixed(2) + ' rad (' + (c.phi * 180 / PI).toFixed(1) + '°)';
    c1LLbl.textContent = 'l = ' + c.l.toFixed(3) + ' m';
    c1FLbl.textContent = 'F = ' + c.F.toFixed(3) + ' N';

    var barTopY = BARBOT - c.F * BARSCALE;
    if (barTopY < BARTOP) barTopY = BARTOP;
    c1BarF.setAttribute('y', barTopY.toFixed(2));
    c1BarF.setAttribute('height', (BARBOT - barTopY).toFixed(2));
  }

  function drawC2(c) {
    var d = D0 - c.x * PXPERM;
    if (d < 0) d = 0;
    var px = GX + d * DIRX, py = GY + d * DIRY;

    cdDot.setAttribute('cx', px.toFixed(2));
    cdDot.setAttribute('cy', py.toFixed(2));
    cdBar.setAttribute('x1', (px - 26 * PERPX).toFixed(2));
    cdBar.setAttribute('y1', (py - 26 * PERPY).toFixed(2));
    cdBar.setAttribute('x2', (px + 26 * PERPX).toFixed(2));
    cdBar.setAttribute('y2', (py + 26 * PERPY).toFixed(2));

    var mgsin = MASS * GACC * Math.sin(THETA);
    var glen = flen(mgsin);
    arrowG.setAttribute('x1', px.toFixed(2));
    arrowG.setAttribute('y1', py.toFixed(2));
    arrowG.setAttribute('x2', (px - glen * DIRX).toFixed(2));
    arrowG.setAttribute('y2', (py - glen * DIRY).toFixed(2));

    var fsx = px - 6 * PERPX, fsy = py - 6 * PERPY;
    var flenF = flen(c.F);
    arrowF.setAttribute('x1', fsx.toFixed(2));
    arrowF.setAttribute('y1', fsy.toFixed(2));
    arrowF.setAttribute('x2', (fsx + flenF * DIRX).toFixed(2));
    arrowF.setAttribute('y2', (fsy + flenF * DIRY).toFixed(2));

    var frsx = px + 6 * PERPX, frsy = py + 6 * PERPY;
    var flenFric = flen(c.f);
    arrowFric.setAttribute('x1', frsx.toFixed(2));
    arrowFric.setAttribute('y1', frsy.toFixed(2));
    arrowFric.setAttribute('x2', (frsx + flenFric * DIRX).toFixed(2));
    arrowFric.setAttribute('y2', (frsy + flenFric * DIRY).toFixed(2));

    c2TLbl.textContent = 't = ' + c.t.toFixed(3) + ' s';
    c2VLbl.textContent = 'v = ' + c.v.toFixed(3) + ' m/s';
    c2ALbl.textContent = 'a = ' + c.a.toFixed(3) + ' m/s²';
    c2XLbl.textContent = 'x = ' + c.x.toFixed(3) + ' m';
    c2FLbl.textContent = 'F = ' + c.F.toFixed(3) + ' N';
    c2FricLbl.textContent = 'f = ' + c.f.toFixed(3) + ' N';
  }

  /* ---------------- 播放节奏（仅 step 用，不影响 probe） ---------------- */
  var ANIM1 = T_C1 * 2;          /* c1 单程时长：放慢 2 倍，约 3.14s */
  var CYC1 = ANIM1 * 2;          /* 往返一次：0->1->0，展示 F 的周期振荡 */
  var ANIM2 = T_C2 * 3;          /* c2 单程时长：放慢 3 倍，约 4.5s */
  var HOLD2 = 1.5;               /* 到达新平衡后的定格时长 */
  var CYC2 = ANIM2 + HOLD2;

  return {
    step: function (t) {
      var tt1 = t % CYC1; if (!(tt1 >= 0)) tt1 = 0;
      var frac1 = tt1 <= ANIM1 ? tt1 / ANIM1 : (2 - tt1 / ANIM1);
      drawC1(coreC1(frac1));

      var tt2 = t % CYC2; if (!(tt2 >= 0)) tt2 = 0;
      var frac2 = tt2 <= ANIM2 ? tt2 / ANIM2 : 1;
      drawC2(coreC2(frac2));
    },
    reset: function () {
      drawC1(coreC1(0));
      drawC2(coreC2(0));
    },
    probe: function (u, caseId) {
      if (caseId === 'c1') return coreC1(u);
      return coreC2(u);
    }
  };
};
