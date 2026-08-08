var PERIOD = 6.0;
var READOUTS = ["v", "alpha"];

function drawFrame(ps, u, svg) {
  var p = ps[CASES[0]], el;
  el = svg.querySelector('#q6-inl-personLeftLine');
  if (el) {
    el.setAttribute('x1', 280-200*p.xHand);
    el.setAttribute('x2', 280-200*p.xHand);
  }
  el = svg.querySelector('#q6-inl-personRightLine');
  if (el) {
    el.setAttribute('x1', 280+200*p.xHand);
    el.setAttribute('x2', 280+200*p.xHand);
  }
  el = svg.querySelector('#q6-inl-handLeft');
  if (el) {
    el.setAttribute('cx', 280-200*p.xHand);
  }
  el = svg.querySelector('#q6-inl-handRight');
  if (el) {
    el.setAttribute('cx', 280+200*p.xHand);
  }
  el = svg.querySelector('#q6-inl-ropeLeft');
  if (el) {
    el.setAttribute('x1', 280-200*p.xHand);
    el.setAttribute('y2', 60+200*p.yDrop);
  }
  el = svg.querySelector('#q6-inl-ropeRight');
  if (el) {
    el.setAttribute('x1', 280+200*p.xHand);
    el.setAttribute('y2', 60+200*p.yDrop);
  }
  el = svg.querySelector('#q6-inl-block');
  if (el) {
    el.setAttribute('y', 60+200*p.yDrop);
  }
  el = svg.querySelector('#q6-inl-arrowLeft');
  if (el) {
    el.setAttribute('x1', 280-200*p.xHand-35);
    el.setAttribute('x2', 280-200*p.xHand-5);
  }
  el = svg.querySelector('#q6-inl-arrowRight');
  if (el) {
    el.setAttribute('x1', 280+200*p.xHand+35);
    el.setAttribute('x2', 280+200*p.xHand+5);
  }
  el = svg.querySelector('#q6-inl-arrowDown');
  if (el) {
    el.setAttribute('y1', 60+200*p.yDrop);
    el.setAttribute('y2', 60+200*p.yDrop+30);
  }
}

function drawReset(svg) { drawFrame(probeAll(0), 0, svg); }
