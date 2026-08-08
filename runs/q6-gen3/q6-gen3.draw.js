var PERIOD = 5.0;
var READOUTS = ["v", "yDrop", "xHand", "alpha"];

var CENTER_X = 280;
var HAND_Y = 92;
var SCALE = 180;
var ARC_R = 20;
var BLOCK_HALF = 14;

var _els = null;
function els(svg) {
  if (_els) return _els;
  _els = {
    ropeL: svg.querySelector('#q6-gen3-ropeL'),
    ropeR: svg.querySelector('#q6-gen3-ropeR'),
    block: svg.querySelector('#q6-gen3-block'),
    blockLabel: svg.querySelector('#q6-gen3-blockLabel'),
    personL: svg.querySelector('#q6-gen3-personL'),
    personR: svg.querySelector('#q6-gen3-personR'),
    arc: svg.querySelector('#q6-gen3-arc'),
    alphaLabel: svg.querySelector('#q6-gen3-alphaLabel'),
    vArrowL: svg.querySelector('#q6-gen3-vArrowL'),
    vArrowR: svg.querySelector('#q6-gen3-vArrowR'),
    vLabelL: svg.querySelector('#q6-gen3-vLabelL'),
    vLabelR: svg.querySelector('#q6-gen3-vLabelR')
  };
  return _els;
}

function setLine(el, x1, y1, x2, y2) {
  el.setAttribute('x1', x1.toFixed(2));
  el.setAttribute('y1', y1.toFixed(2));
  el.setAttribute('x2', x2.toFixed(2));
  el.setAttribute('y2', y2.toFixed(2));
}

function paint(ps, u, svg) {
  var p = ps[CASES[0]];
  var e = els(svg);

  var xPix = p.xHand * SCALE;
  var yPix = p.yDrop * SCALE;
  var leftX = CENTER_X - xPix;
  var rightX = CENTER_X + xPix;
  var blockY = HAND_Y + yPix;
  var alpha = p.alpha;

  setLine(e.ropeL, leftX, HAND_Y, CENTER_X, blockY);
  setLine(e.ropeR, rightX, HAND_Y, CENTER_X, blockY);

  e.block.setAttribute('x', (CENTER_X - BLOCK_HALF).toFixed(2));
  e.block.setAttribute('y', (blockY - BLOCK_HALF).toFixed(2));
  e.blockLabel.setAttribute('y', (blockY + 4).toFixed(2));

  e.personL.setAttribute('transform', 'translate(' + leftX.toFixed(2) + ',' + HAND_Y.toFixed(2) + ')');
  e.personR.setAttribute('transform', 'translate(' + rightX.toFixed(2) + ',' + HAND_Y.toFixed(2) + ')');

  var ax0 = rightX - ARC_R, ay0 = HAND_Y;
  var ax1 = rightX - ARC_R * Math.cos(alpha), ay1 = HAND_Y + ARC_R * Math.sin(alpha);
  e.arc.setAttribute('d', 'M ' + ax0.toFixed(2) + ',' + ay0.toFixed(2) +
    ' A ' + ARC_R + ' ' + ARC_R + ' 0 0 0 ' + ax1.toFixed(2) + ',' + ay1.toFixed(2));
  var labelR = ARC_R + 14;
  var lx = rightX - labelR * Math.cos(alpha / 2);
  var ly = HAND_Y + labelR * Math.sin(alpha / 2) + 3;
  e.alphaLabel.setAttribute('x', lx.toFixed(2));
  e.alphaLabel.setAttribute('y', ly.toFixed(2));

  setLine(e.vArrowL, leftX - 26, HAND_Y, leftX - 6, HAND_Y);
  e.vLabelL.setAttribute('x', (leftX - 30).toFixed(2));
  e.vLabelL.setAttribute('y', (HAND_Y + 4).toFixed(2));

  setLine(e.vArrowR, rightX + 26, HAND_Y, rightX + 6, HAND_Y);
  e.vLabelR.setAttribute('x', (rightX + 30).toFixed(2));
  e.vLabelR.setAttribute('y', (HAND_Y + 4).toFixed(2));
}

function drawFrame(ps, u, svg) {
  paint(ps, u, svg);
}

function drawReset(svg) {
  _els = null;
  paint(probeAll(0), 0, svg);
}
