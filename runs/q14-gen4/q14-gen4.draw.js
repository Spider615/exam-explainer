var PERIOD = 4.0;
var READOUTS = ["B", "I", "v", "F"];

function setText(svg, id, s) {
  var el = svg.querySelector('#' + id);
  if (el) el.textContent = s;
}

function drawFrame(ps, u, svg) {
  var c1 = ps.c1, c2 = ps.c2, c3 = ps.c3;

  setText(svg, 'q14-gen4-c1-B', c1.B.toFixed(2) + 'T');
  setText(svg, 'q14-gen4-c2-B', c2.B.toFixed(2) + 'T');

  setText(svg, 'q14-gen4-c3-x', c3.x.toFixed(2) + 'm');
  setText(svg, 'q14-gen4-c3-v', c3.v.toFixed(3) + 'm/s');
  setText(svg, 'q14-gen4-c3-a', c3.a.toFixed(3) + 'm/s²');
  setText(svg, 'q14-gen4-c3-I', c3.I.toFixed(3) + 'A');
  setText(svg, 'q14-gen4-c3-F', c3.F.toFixed(3) + 'N');
  setText(svg, 'q14-gen4-c3-q', c3.q.toFixed(2) + 'C');

  var dx = c3.x * 90;
  var loop = svg.querySelector('#q14-gen4-loop3');
  loop.setAttribute('transform', 'translate(' + dx.toFixed(2) + ',0)');

  var adX = 355 + dx;
  var flen = 15 + c3.F * 1500;
  var Farrow = svg.querySelector('#q14-gen4-Farrow');
  Farrow.setAttribute('x1', adX.toFixed(2));
  Farrow.setAttribute('x2', (adX - flen).toFixed(2));

  var centerX = adX + 45;
  var vlen = 10 + c3.v * 300;
  var varrow = svg.querySelector('#q14-gen4-varrow');
  varrow.setAttribute('x1', centerX.toFixed(2));
  varrow.setAttribute('x2', (centerX + vlen).toFixed(2));

  var exit = svg.querySelector('#q14-gen4-exit');
  exit.setAttribute('opacity', c3.x >= 0.47 ? 1 : 0);
}

function drawReset(svg) {
  var loop = svg.querySelector('#q14-gen4-loop3');
  loop.setAttribute('transform', 'translate(0,0)');

  var Farrow = svg.querySelector('#q14-gen4-Farrow');
  Farrow.setAttribute('x1', 355);
  Farrow.setAttribute('x2', 335);

  var varrow = svg.querySelector('#q14-gen4-varrow');
  varrow.setAttribute('x1', 400);
  varrow.setAttribute('x2', 430);

  var exit = svg.querySelector('#q14-gen4-exit');
  exit.setAttribute('opacity', 0);
}
