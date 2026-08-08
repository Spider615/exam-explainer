var PERIOD = 4.0;
var READOUTS = ["Fres", "Fx1", "Fy1", "Fx2"];

var OX = 150, OY = 190, S = 65, R_ARC = 30;

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]];
  var half = p.alpha / 2;
  var c2 = Math.cos(half), s2 = Math.sin(half);

  var f1x = OX + S * c2, f1y = OY - S * s2;
  var f2x = OX + S * c2, f2y = OY + S * s2;
  var frx = OX + S * p.Fx, fry = OY - S * p.Fy;

  var f1 = svg.querySelector('#q1-cg1-f1');
  f1.setAttribute('x1', OX); f1.setAttribute('y1', OY);
  f1.setAttribute('x2', f1x); f1.setAttribute('y2', f1y);

  var f2 = svg.querySelector('#q1-cg1-f2');
  f2.setAttribute('x1', OX); f2.setAttribute('y1', OY);
  f2.setAttribute('x2', f2x); f2.setAttribute('y2', f2y);

  var fres = svg.querySelector('#q1-cg1-fres');
  fres.setAttribute('x1', OX); fres.setAttribute('y1', OY);
  fres.setAttribute('x2', frx); fres.setAttribute('y2', fry);

  var ax1 = OX + R_ARC * c2, ay1 = OY - R_ARC * s2;
  var ax2 = OX + R_ARC * c2, ay2 = OY + R_ARC * s2;
  var arc = svg.querySelector('#q1-cg1-arc');
  arc.setAttribute('d', 'M ' + ax1.toFixed(2) + ' ' + ay1.toFixed(2) +
    ' A ' + R_ARC + ' ' + R_ARC + ' 0 0 1 ' + ax2.toFixed(2) + ' ' + ay2.toFixed(2));

  var fv = svg.querySelector('#q1-cg1-formula-val');
  fv.textContent = 'F合 = 2F·cos(α/2) = ' + p.Fres_formula.toFixed(2);

  var deg = p.alpha * 180 / Math.PI;
  var sv = svg.querySelector('#q1-cg1-status-val');
  sv.textContent = '当前夹角：α = ' + p.alpha.toFixed(2) + ' rad ≈ ' + deg.toFixed(0) + '°';
}

function drawReset(svg) {
  var f1 = svg.querySelector('#q1-cg1-f1');
  f1.setAttribute('x1', OX); f1.setAttribute('y1', OY);
  f1.setAttribute('x2', OX + S); f1.setAttribute('y2', OY);

  var f2 = svg.querySelector('#q1-cg1-f2');
  f2.setAttribute('x1', OX); f2.setAttribute('y1', OY);
  f2.setAttribute('x2', OX + S); f2.setAttribute('y2', OY);

  var fres = svg.querySelector('#q1-cg1-fres');
  fres.setAttribute('x1', OX); fres.setAttribute('y1', OY);
  fres.setAttribute('x2', OX + 2 * S); fres.setAttribute('y2', OY);

  var arc = svg.querySelector('#q1-cg1-arc');
  arc.setAttribute('d', 'M ' + (OX + R_ARC).toFixed(2) + ' ' + OY.toFixed(2) +
    ' A ' + R_ARC + ' ' + R_ARC + ' 0 0 1 ' + (OX + R_ARC).toFixed(2) + ' ' + OY.toFixed(2));

  var fv = svg.querySelector('#q1-cg1-formula-val');
  fv.textContent = 'F合 = 2F·cos(α/2) = 2.00';

  var sv = svg.querySelector('#q1-cg1-status-val');
  sv.textContent = '当前夹角：α = 0.00 rad ≈ 0°';
}
