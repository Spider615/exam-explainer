window.Scenes["q4-gen3"] = function (fig) {
  var svg = fig.querySelector('svg');
  var rodA = svg.querySelector('#q4-gen3-rod-a');
  var labelA = svg.querySelector('#q4-gen3-label-a');
  var valV = svg.querySelector('#q4-gen3-val-v');
  var valX = svg.querySelector('#q4-gen3-val-x');
  var valP = svg.querySelector('#q4-gen3-val-P');

  // 坐标映射：x无量纲[0,1] → 屏幕x坐标[100, 490]
  var xStart = 100;
  var xEnd = 490;
  var xScale = xEnd - xStart;

  // 动画周期：2秒完成一次完整运动
  var period = 2.0;

  function getPhysics(u) {
    var x = u;
    var v = 1.0 - u;
    var P = v * v;
    var a = -v;
    return {
      u: u,
      x: x,
      v: v,
      P: P,
      a: a
    };
  }

  return {
    step: function (t) {
      // 计算归一化进度u，循环播放
      var u = (t % period) / period;
      var phys = getPhysics(u);

      // 更新金属棒a的位置
      var screenX = xStart + phys.x * xScale;
      rodA.setAttribute('x1', screenX);
      rodA.setAttribute('x2', screenX);
      labelA.setAttribute('x', screenX);

      // 更新数值显示
      valV.textContent = phys.v.toFixed(2);
      valX.textContent = phys.x.toFixed(2);
      valP.textContent = phys.P.toFixed(2);
    },

    reset: function () {
      // 无需额外重置，step根据t自动计算
    },

    probe: function (u, caseId) {
      // 纯函数，仅根据u和caseId计算
      return getPhysics(u);
    }
  };
};
