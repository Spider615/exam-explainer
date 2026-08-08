var PERIOD = 4.0;
var READOUTS = ["t", "v1", "v2", "QR"];

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var pf = probeAll(1)[CASES[0]];

  var dux = 0.8121, duy = -0.5837;
  var pux = 0.5837, puy = 0.8121;

  var x1f = pf.x1 > 1e-6 ? pf.x1 : 1;
  var x2f = pf.x2 > 1e-6 ? pf.x2 : 1;
  var QRf = pf.QR > 1e-6 ? pf.QR : 1;

  var frac1 = Math.max(0, Math.min(1, p.x1 / x1f));
  var frac2 = Math.max(0, Math.min(1, p.x2 / x2f));

  var tAb = 0.85 - 0.30 * frac1;
  var tCd = 0.19 + 0.36 * frac2;

  var cAb = [60 + 320 * tAb, 310 - 230 * tAb];
  var cCd = [60 + 320 * tCd, 310 - 230 * tCd];

  var setLine = function (id, x1, y1, x2, y2) {
    var el = svg.querySelector('#' + id);
    el.setAttribute('x1', x1); el.setAttribute('y1', y1);
    el.setAttribute('x2', x2); el.setAttribute('y2', y2);
  };
  var setPos = function (id, x, y) {
    var el = svg.querySelector('#' + id);
    el.setAttribute('x', x); el.setAttribute('y', y);
  };
  var setOpacity = function (id, v) {
    svg.querySelector('#' + id).setAttribute('opacity', v);
  };
  var setText = function (id, s) {
    svg.querySelector('#' + id).textContent = s;
  };

  setLine('q13-tp2-ab', cAb[0] + 11.674, cAb[1] + 16.242, cAb[0] - 11.674, cAb[1] - 16.242);
  setLine('q13-tp2-cd', cCd[0] + 11.674, cCd[1] + 16.242, cCd[0] - 11.674, cCd[1] - 16.242);

  setPos('q13-tp2-ab-label', cAb[0] + 18.678, cAb[1] + 25.987);
  setPos('q13-tp2-cd-label', cCd[0] + 18.678, cCd[1] + 25.987);

  var nearEnd = Math.max(0, Math.min(1, (u - 0.9) / 0.1));
  var fadeOut = Math.max(0, Math.min(1, (u - 0.72) / 0.13));

  setPos('q13-tp2-a1', cAb[0] - 26.267, cAb[1] - 36.545);
  setText('q13-tp2-a1', 'a1=' + p.a1.toFixed(2));
  setOpacity('q13-tp2-a1', 1 - fadeOut);

  setPos('q13-tp2-a2', cCd[0] - 26.267, cCd[1] - 36.545);
  setText('q13-tp2-a2', 'a2=' + p.a2.toFixed(2));
  setOpacity('q13-tp2-a2', 1 - fadeOut);

  setLine('q13-tp2-v1arrow', cAb[0], cAb[1], cAb[0] - dux * p.v1 * 6, cAb[1] - duy * p.v1 * 6);
  setLine('q13-tp2-v2arrow', cCd[0], cCd[1], cCd[0] + dux * p.v2 * 6, cCd[1] + duy * p.v2 * 6);
  setOpacity('q13-tp2-v1arrow', 1 - fadeOut);
  setOpacity('q13-tp2-v2arrow', 1 - fadeOut);

  var fTipX = cCd[0] + dux * 35, fTipY = cCd[1] + duy * 35;
  setLine('q13-tp2-F', cCd[0], cCd[1], fTipX, fTipY);
  setPos('q13-tp2-F-label', fTipX + pux * 12, fTipY + puy * 12);
  setOpacity('q13-tp2-F', 1 - fadeOut);
  setOpacity('q13-tp2-F-label', 1 - fadeOut);

  var qrFrac = Math.max(0, Math.min(1, p.QR / QRf));
  svg.querySelector('#q13-tp2-QRfill').setAttribute('width', 100 * qrFrac);

  setOpacity('q13-tp2-flash', nearEnd);
  setOpacity('q13-tp2-Fremoved', nearEnd);
  setOpacity('q13-tp2-v1post', nearEnd);
  setOpacity('q13-tp2-v2post', nearEnd);
  setText('q13-tp2-v1post', "v1'=" + p.v1_post.toFixed(2) + ' m/s');
  setText('q13-tp2-v2post', "v2'=" + p.v2_post.toFixed(2) + ' m/s');

  setOpacity('q13-tp2-v1postarrow', nearEnd);
  setOpacity('q13-tp2-v2postarrow', nearEnd);
  setLine('q13-tp2-v1postarrow', 236, 183.5, 236 + dux * p.v1_post * 6, 183.5 + duy * p.v1_post * 6);
  setLine('q13-tp2-v2postarrow', 236, 183.5, 236 + dux * p.v2_post * 6, 183.5 + duy * p.v2_post * 6);
}

function drawReset(svg) {
  drawFrame(probeAll(0), 0, svg);
}
