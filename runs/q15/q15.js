window.Scenes["q15"] = function (fig) {
  var svg = fig.querySelector('svg');
  var rod = fig.querySelector('#q15-rod');
  var spring = fig.querySelector('#q15-spring');
  var ring = fig.querySelector('#q15-ring');
  var xDisplay = fig.querySelector('#q15-x-display');
  var omegaDisplay = fig.querySelector('#q15-omega-display');
  var springStateDisplay = fig.querySelector('#q15-spring-state');
  var btnC1 = fig.querySelector('#q15-btn-c1');
  var btnC2 = fig.querySelector('#q15-btn-c2');
  var btnC3 = fig.querySelector('#q15-btn-c3');

  // Constants from spec
  var ALPHA_RAD = Math.PI / 3;
  var COS_ALPHA = 0.5;
  var SIN_ALPHA_SQ = 0.75;
  var L = 0.2;
  var X0 = 0.1;
  var K = 100;
  var M = 1.0;
  var G = 10.0;
  var OMEGA2_FINAL = 10 * Math.sqrt(6) / 3;
  var OMEGA3_FINAL = 10.0;

  // Scaling: 1m = 1000px (so 0.2m rod is 200px)
  var SCALE = 1000;
  var O_X = 280; // O点x坐标
  var O_Y = 260; // O点y坐标

  // Current state
  var currentCase = 'c1';
  var currentTime = 0;
  var processDuration = 2.0; // 2秒完成一个过程

  // Button handlers
  btnC1.onclick = function() {
    currentCase = 'c1';
    currentTime = 0;
  };
  btnC2.onclick = function() {
    currentCase = 'c2';
    currentTime = 0;
  };
  btnC3.onclick = function() {
    currentCase = 'c3';
    currentTime = 0;
  };

  // 弹簧路径生成函数
  function generateSpringPath(x) {
    // x是圆环到O点的距离，单位m
    var pixels = x * SCALE;
    // 弹簧沿杆方向，从O点(0,0)到(pixels*cos(alpha), -pixels*sin(alpha))
    // 杆是60度向上，所以y方向向上为正，所以y坐标是 -pixels*sin(alpha)
    var endX = pixels * COS_ALPHA;
    var endY = -pixels * Math.sin(ALPHA_RAD);

    // 生成弹簧波纹
    var path = 'M0 0 ';
    var segments = 10;
    var segLength = pixels / segments;
    var amp = 5; // 波纹振幅

    for (var i = 1; i < segments; i++) {
      var t = i / segments;
      var segX = t * endX;
      var segY = t * endY;
      // 波纹垂直于杆方向
      var perpX = -endY * amp / pixels * ((i % 2 === 0) ? 1 : -1);
      var perpY = endX * amp / pixels * ((i % 2 === 0) ? 1 : -1);
      path += 'L' + (segX + perpX) + ' ' + (segY + perpY) + ' ';
    }
    path += 'L' + endX + ' ' + endY;

    // 平移到O点位置
    return path.replace(/M/g, 'M' + O_X + ' ' + O_Y + ' ').replace(/L/g, 'L' + O_X + ' ' + O_Y + ' ');
  }

  function updateDisplay(x, omega, springState) {
    xDisplay.textContent = 'x = ' + x.toFixed(3) + ' m';
    omegaDisplay.textContent = 'ω = ' + omega.toFixed(2) + ' rad/s';
    springStateDisplay.textContent = '弹簧：' + springState;
  }

  return {
    step: function (t) {
      currentTime += t;
      var u = Math.min(currentTime / processDuration, 1.0);
      if (u >= 1.0) {
        u = 1.0;
      }

      var data = this.probe(u, currentCase);

      // 更新弹簧位置
      var springPath = generateSpringPath(data.x);
      spring.setAttribute('d', springPath);

      // 更新圆环位置
      var ringX = O_X + data.x * SCALE * COS_ALPHA;
      var ringY = O_Y - data.x * SCALE * Math.sin(ALPHA_RAD);
      ring.setAttribute('cx', ringX);
      ring.setAttribute('cy', ringY);

      // 确定弹簧状态
      var springState = '';
      if (data.x < X0 - 0.001) {
        springState = '压缩';
      } else if (data.x > X0 + 0.001) {
        springState = '拉伸';
      } else {
        springState = '原长';
      }

      // 更新显示
      updateDisplay(data.x, data.omega, springState);
    },

    reset: function () {
      currentTime = 0;
    },

    probe: function (u, caseId) {
      // u ∈ [0,1]，纯函数，无副作用
      var x, omega, F_spring, a_par;

      if (caseId === 'c1') {
        omega = 0.0;
        // 阻尼振动：x = 平衡位置 + 初始偏移 * e^(-阻尼系数*u) * cos(角频率*u)
        // 初始位置x(0) = 0.2m（杆末端），平衡位置0.15m，偏移0.05m
        x = 0.15 + 0.05 * Math.exp(-5.0 * u) * Math.cos(10.0 * u);
        F_spring = K * (x - X0);
        a_par = (F_spring - M * G * COS_ALPHA) / M;
      } else if (caseId === 'c2') {
        x = 0.1;
        // 角速度从0线性增加到最终值
        omega = u * OMEGA2_FINAL;
        F_spring = 0.0;
        a_par = (M * G * COS_ALPHA - M * omega * omega * x * SIN_ALPHA_SQ) / M;
      } else if (caseId === 'c3') {
        x = 0.2;
        // 角速度从0线性增加到最终值
        omega = u * OMEGA3_FINAL;
        F_spring = K * (x - X0);
        a_par = (F_spring + M * G * COS_ALPHA - M * omega * omega * x * SIN_ALPHA_SQ) / M;
      } else {
        x = 0.0;
        omega = 0.0;
        F_spring = 0.0;
        a_par = 0.0;
      }

      return {
        u: u,
        x: x,
        omega: omega,
        F_spring: F_spring,
        a_par: a_par
      };
    }
  };
};