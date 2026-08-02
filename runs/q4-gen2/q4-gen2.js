window.Scenes["q4-gen2"] = function (fig) {
  var svg = fig.querySelector('svg');

  /* ---------------- 权威解（归一化 nR=1，p·V=T） ----------------
     与 spec.physics.equations / spec.reference 完全一致：
     ab(等压) s=3u,        T=1+s, V=T,       p=1
     bc(等温) s=3u-1,      T=2,   V=2+2s,    p=T/V
     cd(等容) s=3u-2,      V=4,   T=2+2s,    p=T/V
  */
  function clamp01(x) { if (!(x > 0)) return 0; if (x > 1) return 1; return x; }

  function core(u) {
    var uu = clamp01(u);
    var s, T, V, p;
    if (uu <= 1 / 3) {
      s = 3 * uu;
      T = 1 + s;
      V = T;
      p = 1.0;
    } else if (uu <= 2 / 3) {
      s = 3 * uu - 1;
      T = 2.0;
      V = 2 + 2 * s;
      p = T / V;
    } else {
      s = 3 * uu - 2;
      V = 4.0;
      T = 2 + 2 * s;
      p = T / V;
    }
    return { u: u, T: T, V: V, p: p };
  }

  /* ---------------- 屏幕几何（仅渲染用，不影响 probe） ---------------- */
  var TX0 = 60, TY0 = 296, SCALE_T = 40, SCALE_V = 24.8;      /* V-T 图 */
  var PX0 = 320, PY0 = 296, SCALE_P = 124 / 1.2;              /* p-T 图（T 轴与 V-T 图共用比例尺）*/

  var PISTON_MIN = 40, PISTON_MAX = 170;                       /* V=1 -> 40px, V=4 -> 170px */
  var GAS_X0 = 27;
  var THERMO_BOTTOM = 138, THERMO_MAXH = 70;

  function vtX(T) { return TX0 + SCALE_T * T; }
  function vtY(V) { return TY0 - SCALE_V * V; }
  function ptX(T) { return PX0 + SCALE_T * T; }
  function ptY(p) { return PY0 - SCALE_P * p; }

  function segLen(x1, y1, x2, y2) { var dx = x2 - x1, dy = y2 - y1; return Math.sqrt(dx * dx + dy * dy); }

  var VT_AB = { x1: vtX(1), y1: vtY(1), x2: vtX(2), y2: vtY(2) };
  var VT_BC = { x1: vtX(2), y1: vtY(2), x2: vtX(2), y2: vtY(4) };
  var VT_CD = { x1: vtX(2), y1: vtY(4), x2: vtX(4), y2: vtY(4) };
  var PT_AB = { x1: ptX(1), y1: ptY(1), x2: ptX(2), y2: ptY(1) };
  var PT_BC = { x1: ptX(2), y1: ptY(1), x2: ptX(2), y2: ptY(0.5) };
  var PT_CD = { x1: ptX(2), y1: ptY(0.5), x2: ptX(4), y2: ptY(1) };

  var LEN_VT_AB = segLen(VT_AB.x1, VT_AB.y1, VT_AB.x2, VT_AB.y2);
  var LEN_VT_BC = segLen(VT_BC.x1, VT_BC.y1, VT_BC.x2, VT_BC.y2);
  var LEN_VT_CD = segLen(VT_CD.x1, VT_CD.y1, VT_CD.x2, VT_CD.y2);
  var LEN_PT_AB = segLen(PT_AB.x1, PT_AB.y1, PT_AB.x2, PT_AB.y2);
  var LEN_PT_BC = segLen(PT_BC.x1, PT_BC.y1, PT_BC.x2, PT_BC.y2);
  var LEN_PT_CD = segLen(PT_CD.x1, PT_CD.y1, PT_CD.x2, PT_CD.y2);

  /* ---------------- DOM 引用 ---------------- */
  var pistonGroup = fig.querySelector('#q4-gen2-pistonGroup');
  var gasFill = fig.querySelector('#q4-gen2-gasFill');
  var heatGlow = fig.querySelector('#q4-gen2-heatGlow');
  var thermoFill = fig.querySelector('#q4-gen2-thermoFill');
  var lblPhase = fig.querySelector('#q4-gen2-lblPhase');
  var lblTVP = fig.querySelector('#q4-gen2-lblTVP');
  var lblU = fig.querySelector('#q4-gen2-lblU');
  var vtAB = fig.querySelector('#q4-gen2-vtAB');
  var vtBC = fig.querySelector('#q4-gen2-vtBC');
  var vtCD = fig.querySelector('#q4-gen2-vtCD');
  var vtMarker = fig.querySelector('#q4-gen2-vtMarker');
  var ptAB = fig.querySelector('#q4-gen2-ptAB');
  var ptBC = fig.querySelector('#q4-gen2-ptBC');
  var ptCD = fig.querySelector('#q4-gen2-ptCD');
  var ptMarker = fig.querySelector('#q4-gen2-ptMarker');

  function setReveal(el, len, frac) {
    el.setAttribute('stroke-dasharray', len.toFixed(3));
    el.setAttribute('stroke-dashoffset', (len * (1 - frac)).toFixed(3));
  }

  function phaseText(uu) {
    if (uu <= 1 / 3) return '过程：a→b（等压，p恒定=1）';
    if (uu <= 2 / 3) return '过程：b→c（等温，T恒定=2）';
    return '过程：c→d（等容，V恒定=4）';
  }

  function draw(u) {
    var uu = clamp01(u);
    var c = core(uu);

    var pistonX = PISTON_MIN + (c.V - 1) / 3 * (PISTON_MAX - PISTON_MIN);
    var gasW = pistonX - GAS_X0; if (gasW < 0) gasW = 0;
    pistonGroup.setAttribute('transform', 'translate(' + pistonX.toFixed(2) + ',0)');
    gasFill.setAttribute('width', gasW.toFixed(2));
    heatGlow.setAttribute('width', gasW.toFixed(2));
    var heatOp = clamp01((c.T - 1) / 3) * 0.55;
    heatGlow.setAttribute('opacity', heatOp.toFixed(3));

    var fillH = clamp01((c.T - 1) / 3) * THERMO_MAXH;
    thermoFill.setAttribute('y', (THERMO_BOTTOM - fillH).toFixed(2));
    thermoFill.setAttribute('height', fillH.toFixed(2));

    lblPhase.textContent = phaseText(uu);
    lblTVP.textContent = 'T=' + c.T.toFixed(2) + '  V=' + c.V.toFixed(2) + '  p=' + c.p.toFixed(2);
    lblU.textContent = 'u=' + uu.toFixed(2);

    var fracAB = clamp01(3 * uu);
    var fracBC = clamp01(3 * uu - 1);
    var fracCD = clamp01(3 * uu - 2);
    setReveal(vtAB, LEN_VT_AB, fracAB);
    setReveal(vtBC, LEN_VT_BC, fracBC);
    setReveal(vtCD, LEN_VT_CD, fracCD);
    setReveal(ptAB, LEN_PT_AB, fracAB);
    setReveal(ptBC, LEN_PT_BC, fracBC);
    setReveal(ptCD, LEN_PT_CD, fracCD);

    vtMarker.setAttribute('cx', vtX(c.T).toFixed(2));
    vtMarker.setAttribute('cy', vtY(c.V).toFixed(2));
    ptMarker.setAttribute('cx', ptX(c.T).toFixed(2));
    ptMarker.setAttribute('cy', ptY(c.p).toFixed(2));
  }

  /* ---------------- 播放节奏（仅 step 用，不影响 probe） ---------------- */
  var ANIM = 9.0, HOLD = 2.0, CYC = ANIM + HOLD;

  return {
    step: function (t) {
      var tt = t - Math.floor(t / CYC) * CYC;
      if (!(tt >= 0)) tt = 0;
      var u = tt <= ANIM ? tt / ANIM : 1;
      draw(u);
    },
    reset: function () {
      draw(0);
    },
    probe: function (u, caseId) {
      var c = core(u);
      return { u: c.u, T: c.T, V: c.V, p: c.p };
    }
  };
};
