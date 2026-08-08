var PERIOD = 4.0;
var READOUTS = ["v", "alpha", "vDrop"];

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]], el;
  el = svg.querySelector('#q6-decl-rope-left');
  if (el) {
    el.setAttribute('x1', 280 - p.xHand*100);
    el.setAttribute('y2', 60 + p.yDrop*100);
  }
  el = svg.querySelector('#q6-decl-rope-right');
  if (el) {
    el.setAttribute('x1', 280 + p.xHand*100);
    el.setAttribute('y2', 60 + p.yDrop*100);
  }
  el = svg.querySelector('#q6-decl-block');
  if (el) {
    el.setAttribute('y', 60 + p.yDrop*100);
  }
  el = svg.querySelector('#q6-decl-handL');
  if (el) {
    el.setAttribute('cx', 280 - p.xHand*100);
  }
  el = svg.querySelector('#q6-decl-handR');
  if (el) {
    el.setAttribute('cx', 280 + p.xHand*100);
  }
  el = svg.querySelector('#q6-decl-studentL-body');
  if (el) {
    el.setAttribute('x1', 280 - p.xHand*100);
    el.setAttribute('x2', 280 - p.xHand*100);
  }
  el = svg.querySelector('#q6-decl-studentR-body');
  if (el) {
    el.setAttribute('x1', 280 + p.xHand*100);
    el.setAttribute('x2', 280 + p.xHand*100);
  }
  el = svg.querySelector('#q6-decl-angleRef-L');
  if (el) {
    el.setAttribute('x1', 280 - p.xHand*100);
    el.setAttribute('x2', 280 - p.xHand*100 - 20);
  }
  el = svg.querySelector('#q6-decl-angleRef-R');
  if (el) {
    el.setAttribute('x1', 280 + p.xHand*100);
    el.setAttribute('x2', 280 + p.xHand*100 + 20);
  }
  el = svg.querySelector('#q6-decl-vArrow-L');
  if (el) {
    el.setAttribute('x1', 280 - p.xHand*100);
    el.setAttribute('x2', 280 - p.xHand*100 + 30);
  }
  el = svg.querySelector('#q6-decl-vArrow-R');
  if (el) {
    el.setAttribute('x1', 280 + p.xHand*100);
    el.setAttribute('x2', 280 + p.xHand*100 - 30);
  }
  el = svg.querySelector('#q6-decl-vDropArrow');
  if (el) {
    el.setAttribute('y1', 125 + p.yDrop*100);
    el.setAttribute('y2', 140 + p.yDrop*100);
  }
  el = svg.querySelector('#q6-decl-lab-block');
  if (el) {
    el.setAttribute('y', 94 + p.yDrop*100);
  }
  el = svg.querySelector('#q6-decl-lab-handL');
  if (el) {
    el.setAttribute('x', 280 - p.xHand*100);
  }
  el = svg.querySelector('#q6-decl-lab-handR');
  if (el) {
    el.setAttribute('x', 280 + p.xHand*100);
  }
  el = svg.querySelector('#q6-decl-lab-vL');
  if (el) {
    el.setAttribute('x', 280 - p.xHand*100 + 15);
  }
  el = svg.querySelector('#q6-decl-lab-vR');
  if (el) {
    el.setAttribute('x', 280 + p.xHand*100 - 15);
  }
  el = svg.querySelector('#q6-decl-lab-alphaL');
  if (el) {
    el.setAttribute('x', 280 - p.xHand*100 - 10);
  }
  el = svg.querySelector('#q6-decl-lab-alphaR');
  if (el) {
    el.setAttribute('x', 280 + p.xHand*100 + 10);
  }
  el = svg.querySelector('#q6-decl-lab-vdrop');
  if (el) {
    el.setAttribute('y', 136.5 + p.yDrop*100);
  }
}

function drawReset(svg) { drawFrame(probeAll(0), 0, svg); }
