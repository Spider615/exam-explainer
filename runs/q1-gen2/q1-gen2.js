window.Scenes = window.Scenes || {};
window.Scenes["q1-gen2"] = function (fig) {
  var force1 = fig.querySelector('#q1-gen2-force1');
  var force2 = fig.querySelector('#q1-gen2-force2');
  var par1 = fig.querySelector('#q1-gen2-par1');
  var par2 = fig.querySelector('#q1-gen2-par2');
  var resultant = fig.querySelector('#q1-gen2-resultant');
  var angleArc = fig.querySelector('#q1-gen2-angle-arc');
  var f1Label = fig.querySelector('#q1-gen2-f1-label');
  var f2Label = fig.querySelector('#q1-gen2-f2-label');
  var fresLabel = fig.querySelector('#q1-gen2-fres-label');
  var alphaRadEl = fig.querySelector('#q1-gen2-alpha-rad');
  var alphaDegEl = fig.querySelector('#q1-gen2-alpha-deg');
  var fresValEl = fig.querySelector('#q1-gen2-fres-val');
  var fresFormulaValEl = fig.querySelector('#q1-gen2-fres-formula-val');

  var SCALE = 100;
  var ORIGIN_X = 100;
  var ORIGIN_Y = 160;
  var ANGLE_RADIUS = 30;
  var PERIOD = 5;

  function compute(u) {
    var F = 1.0;
    var alpha = Math.PI * u;
    var halfAlpha = alpha / 2;
    var cosHalf = Math.cos(halfAlpha);
    var sinHalf = Math.sin(halfAlpha);
    var Fx1 = F * cosHalf;
    var Fy1 = F * sinHalf;
    var Fx2 = F * cosHalf;
    var Fy2 = -F * sinHalf;
    var Fx = Fx1 + Fx2;
    var Fy = Fy1 + Fy2;
    var Fres = Math.sqrt(Fx * Fx + Fy * Fy);
    var Fres_formula = 2 * F * cosHalf;
    return {
      u: u,
      alpha: alpha,
      F: F,
      Fx1: Fx1,
      Fy1: Fy1,
      Fx2: Fx2,
      Fy2: Fy2,
      Fx: Fx,
      Fy: Fy,
      Fres: Fres,
      Fres_formula: Fres_formula
    };
  }

  function update(data) {
    var Fx1 = data.Fx1;
    var Fy1 = data.Fy1;
    var Fx2 = data.Fx2;
    var Fy2 = data.Fy2;
    var Fres = data.Fres;
    var alpha = data.alpha;
    var halfAlpha = alpha / 2;
    var cosHalf = Math.cos(halfAlpha);
    var sinHalf = Math.sin(halfAlpha);

    var f1x2 = ORIGIN_X + SCALE * Fx1;
    var f1y2 = ORIGIN_Y - SCALE * Fy1;
    var f2x2 = ORIGIN_X + SCALE * Fx2;
    var f2y2 = ORIGIN_Y - SCALE * Fy2;
    var rx2 = ORIGIN_X + SCALE * Fres;
    var ry2 = ORIGIN_Y;

    force1.setAttribute('x1', ORIGIN_X);
    force1.setAttribute('y1', ORIGIN_Y);
    force1.setAttribute('x2', f1x2);
    force1.setAttribute('y2', f1y2);

    force2.setAttribute('x1', ORIGIN_X);
    force2.setAttribute('y1', ORIGIN_Y);
    force2.setAttribute('x2', f2x2);
    force2.setAttribute('y2', f2y2);

    resultant.setAttribute('x1', ORIGIN_X);
    resultant.setAttribute('y1', ORIGIN_Y);
    resultant.setAttribute('x2', rx2);
    resultant.setAttribute('y2', ry2);

    par1.setAttribute('x1', f1x2);
    par1.setAttribute('y1', f1y2);
    par1.setAttribute('x2', rx2);
    par1.setAttribute('y2', ry2);

    par2.setAttribute('x1', f2x2);
    par2.setAttribute('y1', f2y2);
    par2.setAttribute('x2', rx2);
    par2.setAttribute('y2', ry2);

    var arcStartX = ORIGIN_X + ANGLE_RADIUS * cosHalf;
    var arcStartY = ORIGIN_Y + ANGLE_RADIUS * sinHalf;
    var arcEndX = ORIGIN_X + ANGLE_RADIUS * cosHalf;
    var arcEndY = ORIGIN_Y - ANGLE_RADIUS * sinHalf;
    var arcD = 'M ' + arcStartX + ' ' + arcStartY + ' A ' + ANGLE_RADIUS + ' ' + ANGLE_RADIUS + ' 0 0 0 ' + arcEndX + ' ' + arcEndY;
    angleArc.setAttribute('d', arcD);

    var f1MidX = ORIGIN_X + 0.5 * SCALE * Fx1;
    var f1MidY = ORIGIN_Y - 0.5 * SCALE * Fy1;
    var f1LabelX = f1MidX + 8 * (-Fy1);
    var f1LabelY = f1MidY + 8 * (-Fx1);
    f1Label.setAttribute('x', f1LabelX);
    f1Label.setAttribute('y', f1LabelY);

    var f2MidX = ORIGIN_X + 0.5 * SCALE * Fx2;
    var f2MidY = ORIGIN_Y - 0.5 * SCALE * Fy2;
    var f2LabelX = f2MidX + 8 * (-Fy1);
    var f2LabelY = f2MidY + 8 * Fx1;
    f2Label.setAttribute('x', f2LabelX);
    f2Label.setAttribute('y', f2LabelY);

    var fresMidX = ORIGIN_X + 0.5 * SCALE * Fres;
    var fresMidY = ORIGIN_Y - 12;
    fresLabel.setAttribute('x', fresMidX);
    fresLabel.setAttribute('y', fresMidY);
    fresLabel.setAttribute('opacity', Fres < 0.05 ? '0' : '1');

    alphaRadEl.textContent = data.alpha.toFixed(2);
    alphaDegEl.textContent = (data.alpha * 180 / Math.PI).toFixed(1);
    fresValEl.textContent = Fres.toFixed(2);
    fresFormulaValEl.textContent = data.Fres_formula.toFixed(2);
  }

  update(compute(0));

  return {
    step: function (t) {
      var u = (t % PERIOD) / PERIOD;
      update(compute(u));
    },
    reset: function () {
      update(compute(0));
    },
    probe: function (u, caseId) {
      return compute(u);
    }
  };
};
