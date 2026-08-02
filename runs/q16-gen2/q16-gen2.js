window.Scenes["q16-gen2"] = function (fig) {
  "use strict";
  var svg = fig.querySelector('svg');

  // ---- 物理常数（题面给定，归一化 m=1,q=1,E=1,k=1,v1=1） ----
  var QE = 1.0;      // qE
  var FRIC = 2.0;    // 2qE，A、B 最大静摩擦=滑动摩擦

  // ---- 自由参数（数值打靶求得，见 solve.py / NOTES.md） ----
  var S0 = 3.0;              // 初始距离 xB-xA
  var K_SPRING = 12.0;       // 弹簧劲度系数
  var L0 = 1.0;              // 弹簧原长（= r1=1，保证 S 点弹簧恰好未接触）
  var V0_C1 = 1.9148542155126713;   // c1 初速度，使到达 S 时 vA=v1=1
  var V0_C2 = 2.581988897471616;    // c2 初速度，使到达 S 时 vA=2v1=2
  var LR = 0.5;                     // 细杆长度（s<=LR 时视为与 B 相碰，过程终点）

  // ---- 力学：与 spec.physics.equations 完全一致的力律（禁止自行改动力的形式）----
  function Fc_of(s) { return 1.0 / (s * s); }
  function Fs_of(s) { return s < L0 ? K_SPRING * (L0 - s) : 0.0; }

  function deriv(xA, xB, vA, vB) {
    var s = xB - xA;
    var fc = Fc_of(s);
    var fs = Fs_of(s);
    var aA = fc + fs - QE;              // qE - fA*sign(vA) + Fc + Fs ，vA>0 时 fA=FRIC=2
    var aB;
    if (vB < -1e-9) {
      aB = QE - fc - fs;                // -qE + fB - Fc - Fs ，vB<0 时 fB=FRIC=2
    } else {
      var drive = -QE - fc - fs;        // B 静止时的净驱动力（不含摩擦）
      aB = (drive < -FRIC) ? (drive + FRIC) : 0.0;
    }
    return [vA, vB, aA, aB];
  }

  function rk4Step(xA, xB, vA, vB, dt) {
    var k1 = deriv(xA, xB, vA, vB);
    var k2 = deriv(xA + 0.5 * dt * k1[0], xB + 0.5 * dt * k1[1], vA + 0.5 * dt * k1[2], vB + 0.5 * dt * k1[3]);
    var k3 = deriv(xA + 0.5 * dt * k2[0], xB + 0.5 * dt * k2[1], vA + 0.5 * dt * k2[2], vB + 0.5 * dt * k2[3]);
    var k4 = deriv(xA + dt * k3[0], xB + dt * k3[1], vA + dt * k3[2], vB + dt * k3[3]);
    return [
      xA + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]),
      xB + dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]),
      vA + dt / 6 * (k1[2] + 2 * k2[2] + 2 * k3[2] + k4[2]),
      vB + dt / 6 * (k1[3] + 2 * k2[3] + 2 * k3[3] + k4[3])
    ];
  }

  // 积分一次完整过程（t=0 到 s<=LR），dt 固定步长，返回稠密轨迹
  function integrate(v0) {
    var dt = 5e-4;
    var xA = 0.0, xB = S0, vA = v0, vB = 0.0, t = 0.0;
    var ts = [t], xAs = [xA], xBs = [xB], vAs = [vA], vBs = [vB];
    var guard = 0;
    while ((xB - xA) > LR && guard < 200000) {
      var nx = rk4Step(xA, xB, vA, vB, dt);
      xA = nx[0]; xB = nx[1]; vA = nx[2]; vB = nx[3]; t += dt;
      ts.push(t); xAs.push(xA); xBs.push(xB); vAs.push(vA); vBs.push(vB);
      guard++;
    }
    return { ts: ts, xAs: xAs, xBs: xBs, vAs: vAs, vBs: vBs, T: t };
  }

  // 线性插值查表（ts 单调递增）
  function interp(xs, ys, x) {
    var n = xs.length;
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    var lo = 0, hi = n - 1;
    while (hi - lo > 1) {
      var mid = (lo + hi) >> 1;
      if (xs[mid] <= x) lo = mid; else hi = mid;
    }
    var t0 = xs[lo], t1 = xs[hi], f = (x - t0) / (t1 - t0);
    return ys[lo] + (ys[hi] - ys[lo]) * f;
  }

  // 重采样为均匀 u 网格，供 probe/step 做纯函数查表
  function buildTable(traj, N) {
    var t = [], xA = [], xB = [], vA = [], vB = [];
    var T = traj.T;
    for (var i = 0; i < N; i++) {
      var u = i / (N - 1);
      var tt = u * T;
      t.push(tt);
      xA.push(interp(traj.ts, traj.xAs, tt));
      xB.push(interp(traj.ts, traj.xBs, tt));
      vA.push(interp(traj.ts, traj.vAs, tt));
      vB.push(interp(traj.ts, traj.vBs, tt));
    }
    // S 点（s 首次 <= r1=1 处）对应的 xA，用于画 S 标记
    var xAatS = xA[0];
    for (var j = 0; j < traj.ts.length; j++) {
      if ((traj.xBs[j] - traj.xAs[j]) <= 1.0) { xAatS = traj.xAs[j]; break; }
    }
    return { t: t, xA: xA, xB: xB, vA: vA, vB: vB, T: T, N: N, xAatS: xAatS };
  }

  var TRAJ_C1 = integrate(V0_C1);
  var TRAJ_C2 = integrate(V0_C2);
  var TABLES = {
    c1: buildTable(TRAJ_C1, 600),
    c2: buildTable(TRAJ_C2, 600)
  };

  function tableFor(caseId) {
    return TABLES[caseId] || TABLES.c1;
  }

  // 由 (xA,xB,vA,vB) 推导出全部物理量——probe 与渲染共用同一套推导
  function deriveState(u, caseId) {
    var uu = u < 0 ? 0 : (u > 1 ? 1 : u);
    var tab = tableFor(caseId);
    var idx = uu * (tab.N - 1);
    var i0 = Math.floor(idx);
    var i1 = i0 + 1 >= tab.N ? tab.N - 1 : i0 + 1;
    var f = idx - i0;
    var t = tab.t[i0] + (tab.t[i1] - tab.t[i0]) * f;
    var xA = tab.xA[i0] + (tab.xA[i1] - tab.xA[i0]) * f;
    var xB = tab.xB[i0] + (tab.xB[i1] - tab.xB[i0]) * f;
    var vA = tab.vA[i0] + (tab.vA[i1] - tab.vA[i0]) * f;
    var vB = tab.vB[i0] + (tab.vB[i1] - tab.vB[i0]) * f;
    var s = xB - xA;
    var fc = Fc_of(s);
    var fs = Fs_of(s);
    var aA = fc + fs - QE;
    var aB = (vB < -1e-6) ? (QE - fc - fs) : 0.0;
    return { t: t, xA: xA, xB: xB, vA: vA, vB: vB, s: s, Fc: fc, Fs: fs, aA: aA, aB: aB };
  }

  // ---- 渲染坐标映射 ----
  var SCALE = 130, X0 = 55;
  var PXV = 16;          // 每单位速度对应的箭头像素长
  function cx(pos) { return X0 + pos * SCALE; }

  function springPath(x0, y0, len) {
    if (len < 6) len = 6;
    var amp = 6, n = 5;
    var d = "M" + x0.toFixed(2) + "," + y0.toFixed(2);
    var seg = len / n;
    for (var i = 1; i <= n; i++) {
      var x = x0 + seg * i, y;
      if (i === n) y = y0;
      else if (i % 2 === 1) y = y0 - amp;
      else y = y0 + amp;
      d += " L" + x.toFixed(2) + "," + y.toFixed(2);
    }
    return d;
  }

  // ---- DOM 引用 ----
  var elBlockA = svg.querySelector('#q16-gen2-blockA');
  var elBlockB = svg.querySelector('#q16-gen2-blockB');
  var elSpringA = svg.querySelector('#q16-gen2-springA');
  var elVelA = svg.querySelector('#q16-gen2-velA');
  var elVelB = svg.querySelector('#q16-gen2-velB');
  var elDistBracket = svg.querySelector('#q16-gen2-distBracket');
  var elDistLabel = svg.querySelector('#q16-gen2-distLabel');
  var elSMark = svg.querySelector('#q16-gen2-sMark');
  var elSMarkLabel = svg.querySelector('#q16-gen2-sMarkLabel');
  var elCollide = svg.querySelector('#q16-gen2-collideFlag');
  var elReadout1 = svg.querySelector('#q16-gen2-readout1');
  var elReadout2 = svg.querySelector('#q16-gen2-readout2');
  var elReadout3 = svg.querySelector('#q16-gen2-readout3');
  var btnC1 = fig.querySelector('#q16-gen2-btnC1');
  var btnC2 = fig.querySelector('#q16-gen2-btnC2');

  var PAUSE = 1.0;
  var currentCase = 'c1';
  var switchOffset = 0;
  var lastT = 0;

  function setCase(cid) {
    if (cid === currentCase) return;
    currentCase = cid;
    switchOffset = lastT;
    if (btnC1) btnC1.setAttribute('aria-pressed', cid === 'c1' ? 'true' : 'false');
    if (btnC2) btnC2.setAttribute('aria-pressed', cid === 'c2' ? 'true' : 'false');
    render(0, currentCase);
  }
  if (btnC1) btnC1.addEventListener('click', function () { setCase('c1'); });
  if (btnC2) btnC2.addEventListener('click', function () { setCase('c2'); });

  function render(u, caseId) {
    var st = deriveState(u, caseId);
    var cxA = cx(st.xA), cxB = cx(st.xB);

    elBlockA.setAttribute('transform', 'translate(' + cxA.toFixed(2) + ',0)');
    elBlockB.setAttribute('transform', 'translate(' + cxB.toFixed(2) + ',0)');

    var springLen = (st.s < L0 ? st.s : L0) * SCALE;
    elSpringA.setAttribute('d', springPath(17, 172, springLen));

    var vaLen = st.vA * PXV;
    elVelA.setAttribute('x2', vaLen.toFixed(2));
    elVelA.setAttribute('y2', '128');
    var vbLen = st.vB * PXV;
    elVelB.setAttribute('x2', vbLen.toFixed(2));
    elVelB.setAttribute('y2', '128');

    var edgeA = cxA + 17, edgeB = cxB - 17;
    elDistBracket.setAttribute('d',
      'M' + edgeA.toFixed(2) + ',94 L' + edgeA.toFixed(2) + ',102' +
      ' M' + edgeA.toFixed(2) + ',98 L' + edgeB.toFixed(2) + ',98' +
      ' M' + edgeB.toFixed(2) + ',94 L' + edgeB.toFixed(2) + ',102');
    var midx = (edgeA + edgeB) / 2;
    elDistLabel.setAttribute('x', midx.toFixed(2));
    elDistLabel.textContent = 's=' + st.s.toFixed(2);

    var sMarkX = cx(tableFor(caseId).xAatS);
    elSMark.setAttribute('x1', sMarkX.toFixed(2));
    elSMark.setAttribute('x2', sMarkX.toFixed(2));
    elSMarkLabel.setAttribute('x', sMarkX.toFixed(2));

    elCollide.setAttribute('opacity', u >= 0.995 ? '1' : '0');

    var label = caseId === 'c2' ? '新过程(c2)' : '原过程(c1)';
    elReadout1.textContent = '情形：' + label + '　t = ' + st.t.toFixed(2) + ' s';
    elReadout2.textContent = 's = ' + st.s.toFixed(2) + '   vA = ' + st.vA.toFixed(2) + '   vB = ' + st.vB.toFixed(2);
    elReadout3.textContent = 'Fc = ' + st.Fc.toFixed(2) + '   Fs = ' + st.Fs.toFixed(2) + '   aA = ' + st.aA.toFixed(2);
  }

  function step(t) {
    lastT = t;
    var tab = tableFor(currentCase);
    var cycle = tab.T + PAUSE;
    var localT = t - switchOffset;
    localT = localT % cycle;
    if (localT < 0) localT += cycle;
    var u = localT <= tab.T ? (tab.T > 0 ? localT / tab.T : 1) : 1;
    render(u, currentCase);
  }

  function reset() {
    switchOffset = 0;
    lastT = 0;
  }

  function probe(u, caseId) {
    var st = deriveState(u, caseId);
    return {
      t: st.t, xA: st.xA, xB: st.xB, vA: st.vA, vB: st.vB,
      s: st.s, Fc: st.Fc, Fs: st.Fs, aA: st.aA, aB: st.aB
    };
  }

  return { step: step, reset: reset, probe: probe };
};
