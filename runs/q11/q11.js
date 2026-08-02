window.Scenes["q11"] = function (fig) {
  var svg = fig.querySelector('svg');
  var currentPoint = svg.querySelector('#q11-current');
  var infoU = svg.querySelector('#q11-info-U');
  var infoW = svg.querySelector('#q11-info-W');
  var infoQ = svg.querySelector('#q11-info-Q');

  // 坐标转换：V范围0-2 → x范围60-520
  function v2x(v) {
    return 60 + (v / 2.0) * 460;
  }

  // 坐标转换：p范围0-2 → y范围260-40（反转）
  function p2y(p) {
    return 260 - (p / 2.0) * 220;
  }

  function compute(u) {
    u = Math.max(0.0, Math.min(1.0, u));
    var p, V, W, U, T, Q;
    var t;

    if (u <= 0.25) {
      t = u / 0.25;
      V = 1.0;
      p = 1.0 - 0.5 * t;
    } else if (u <= 0.5) {
      t = (u - 0.25) / 0.25;
      p = 0.5;
      V = 1.0 - 0.5 * t;
    } else if (u <= 0.75) {
      t = (u - 0.5) / 0.25;
      V = 0.5;
      p = 0.5 + 1.5 * t;
    } else {
      t = (u - 0.75) / 0.25;
      V = 0.5 + 0.5 * t;
      p = 2.0 - 1.0 * t;
    }

    if (u <= 0.25) {
      W = 0.0;
    } else if (u <= 0.5) {
      W = 0.5 * (V - 1.0);
    } else if (u <= 0.75) {
      W = -0.25;
    } else {
      W = 3 * V - V * V - 1.5;
    }

    U = p * V;
    T = U;
    Q = (U - 1.0) + W;

    return {
      u: u,
      p: p,
      V: V,
      U: U,
      T: T,
      W: W,
      Q: Q
    };
  }

  return {
    step: function (t) {
      // 取t的小数部分循环
      var u = t % 4.0 / 4.0;
      var state = compute(u);

      // 更新当前点位置
      currentPoint.setAttribute('cx', v2x(state.V));
      currentPoint.setAttribute('cy', p2y(state.p));

      // 更新信息显示
      infoU.textContent = 'U = ' + state.U.toFixed(2);
      infoW.textContent = 'W = ' + state.W.toFixed(2);
      infoQ.textContent = 'Q = ' + state.Q.toFixed(2);
    },
    reset: function () {
      currentPoint.setAttribute('cx', v2x(1.0));
      currentPoint.setAttribute('cy', p2y(1.0));
      infoU.textContent = 'U = 1.00';
      infoW.textContent = 'W = 0.00';
      infoQ.textContent = 'Q = 0.00';
    },
    probe: function (u, caseId) {
      return compute(u);
    }
  };
};
