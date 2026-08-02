window.Scenes["q8-gen4"] = function (fig) {
  var svg = fig.querySelector('svg');

  // Constants from spec
  var t_E = 10.0;
  var t_F = 20.0;
  var t_M = 40.0;
  var t_N = 53.0;
  var m = 2.0;
  var total_duration = t_N - t_E; // 43s

  // SVG coordinates mapping
  var x_min = 60;
  var x_max = 520;
  var y_min = 260;
  var y_max = 40;
  var t_scale = (x_max - x_min) / (t_N - t_E); // pixels per second
  var y_scale = (y_min - y_max) / 80.0; // 80m height range

  // DOM elements
  var drone = svg.querySelector('#q8-gen4-drone');
  var time_text = svg.querySelector('#q8-gen4-time');
  var height_text = svg.querySelector('#q8-gen4-height');
  var velocity_text = svg.querySelector('#q8-gen4-velocity');

  // Helper functions matching reference implementation
  function y_of_t(t) {
    if (t <= t_F) {
      return 4.0 * t - 26.0;
    } else if (t <= t_M) {
      var dt = t - t_F;
      return 54.0 + 4.0 * dt - 0.15 * dt * dt;
    } else {
      return -2.0 * t + 140.0;
    }
  }

  function v_of_t(t) {
    if (t <= t_F) {
      return 4.0;
    } else if (t <= t_M) {
      return 4.0 - 0.3 * (t - t_F);
    } else {
      return -2.0;
    }
  }

  // Convert physical t to screen x
  function t_to_x(t) {
    return x_min + (t - t_E) * t_scale;
  }

  // Convert physical y to screen y
  function y_to_y(y) {
    return y_min - y * y_scale;
  }

  return {
    step: function (t) {
      // t is playback time, loop every 10 seconds
      var playback_t = t % 10.0;
      var u = playback_t / 10.0; // normalize to [0,1]

      var physical_t = t_E + u * total_duration;
      var y = y_of_t(physical_t);
      var v = v_of_t(physical_t);

      // Update drone position
      var x = t_to_x(physical_t);
      var y_screen = y_to_y(y);
      drone.setAttribute('transform', 'translate(' + x + ',' + y_screen + ')');

      // Update info panel
      time_text.textContent = 't: ' + physical_t.toFixed(1) + 's';
      height_text.textContent = 'y: ' + y.toFixed(1) + 'm';
      velocity_text.textContent = 'v: ' + v.toFixed(1) + 'm/s';
    },

    reset: function () {
      // Reset to start position
      var x = t_to_x(t_E);
      var y = y_to_y(y_of_t(t_E));
      drone.setAttribute('transform', 'translate(' + x + ',' + y + ')');
      time_text.textContent = 't: ' + t_E.toFixed(1) + 's';
      height_text.textContent = 'y: ' + y_of_t(t_E).toFixed(1) + 'm';
      velocity_text.textContent = 'v: ' + v_of_t(t_E).toFixed(1) + 'm/s';
    },

    probe: function (u, caseId) {
      // caseId is only 'c1' per spec
      var t = t_E + u * total_duration;
      var y = y_of_t(t);
      var v = v_of_t(t);
      var p = m * v;

      // Calculate acceleration using numerical differentiation
      var h = 1e-4;
      var t_minus = t - h;
      var t_plus = t + h;
      if (t_minus < t_E) t_minus = t_E;
      if (t_plus > t_N) t_plus = t_N;

      var a;
      if (t_plus > t_minus) {
        a = (v_of_t(t_plus) - v_of_t(t_minus)) / (t_plus - t_minus);
      } else {
        a = 0.0;
      }

      return {
        "u": u,
        "t": t,
        "y": y,
        "v": v,
        "a": a,
        "p": p
      };
    }
  };
};
