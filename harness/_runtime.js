/* ===== 动画运行时 =====
 *
 * 离线页 out.html 用的就是这一份。**Web 端的 SceneMount.tsx 要同步改** ——
 * 只改一边的话，两个入口的控件不一样，而没有任何东西会提示这件事。
 *
 * 时间轴为什么要「检测后再用」：duration/seek 是代码生成的新场景才有的。
 * 老场景只知道 t % 自己内部的周期，宿主拿不到总时长就画不出刻度。
 * 检测不到就退回播放/暂停，**不留一个拖不动的空条** —— 那比没有更糟。
 */
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var live = [];
  var SPEEDS = [0.5, 1, 2];

  function mkbtn(txt, cls) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'btn' + (cls ? ' ' + cls : ''); b.textContent = txt;
    return b;
  }

  function build(fig) {
    var id = fig.getAttribute('data-scene');
    var factory = window.Scenes[id];
    if (typeof factory !== 'function') return null;
    var api;
    try { api = factory(fig); } catch (e) { console.error('[scene ' + id + '] setup failed', e); return null; }
    if (!api || typeof api.step !== 'function') { console.error('[scene ' + id + '] bad contract'); return null; }

    // 两样都齐才认为能拖：只有 duration 没有 seek 的话，拖了也没反应
    var seekable = (typeof api.seek === 'function' &&
                    typeof api.duration === 'number' && api.duration > 0);

    var bar = document.createElement('div');
    bar.className = 'ctlbar';
    var pp = mkbtn('', 'pp');
    var rp = mkbtn('重播');
    var tag = document.createElement('span');
    tag.className = 'livebadge'; tag.textContent = 'LIVE';
    bar.appendChild(pp); bar.appendChild(rp);

    var s = { id: id, api: api, t: 0, playing: !reduce, visible: true,
              fig: fig, pp: pp, speed: 1, scrub: false, seekable: seekable };

    var range = null, num = null;
    if (seekable) {
      range = document.createElement('input');
      range.type = 'range'; range.min = '0'; range.max = '1'; range.step = '0.001';
      range.value = '0'; range.setAttribute('aria-label', '播放进度');
      num = document.createElement('span');
      num.className = 'ctl-num'; num.textContent = '0%';
      bar.appendChild(range); bar.appendChild(num);

      for (var si = 0; si < SPEEDS.length; si++) {
        (function (sp) {
          var b = mkbtn(sp + '×');
          b.addEventListener('click', function () {
            s.speed = sp; paint();
          });
          b.setAttribute('data-speed', String(sp));
          bar.appendChild(b);
        })(SPEEDS[si]);
      }

      // 多情形：切的是读数面板显示哪一个；画面上各情形本来就一起画
      if (api.cases && api.cases.length > 1 && typeof api.setCase === 'function') {
        var lab = document.createElement('span');
        lab.className = 'ctl-lab'; lab.textContent = '读数';
        bar.appendChild(lab);
        for (var ci = 0; ci < api.cases.length; ci++) {
          (function (cid) {
            var b = mkbtn(cid);
            b.setAttribute('data-case', cid);
            b.addEventListener('click', function () {
              api.setCase(cid);
              seekTo(s.t / api.duration % 1);
              paint();
            });
            bar.appendChild(b);
          })(api.cases[ci]);
        }
      }
    }

    bar.appendChild(tag);
    var own = fig.querySelector('.ctl');
    if (own) bar.appendChild(own);
    var cap = fig.querySelector('figcaption');
    fig.insertBefore(bar, cap);

    window.__api = window.__api || {}; window.__api[id] = api;

    function paint() {
      pp.textContent = s.playing ? '暂停' : '播放';
      pp.setAttribute('aria-pressed', s.playing ? 'true' : 'false');
      pp.setAttribute('aria-label', (s.playing ? '暂停' : '播放') + '动画');
      tag.style.opacity = s.playing ? '.9' : '.3';
      var bs = bar.querySelectorAll('[data-speed]');
      for (var i = 0; i < bs.length; i++) {
        bs[i].setAttribute('aria-pressed',
          parseFloat(bs[i].getAttribute('data-speed')) === s.speed ? 'true' : 'false');
      }
      var cs = bar.querySelectorAll('[data-case]');
      var cur = api.currentCase ? api.currentCase() : null;
      for (var j = 0; j < cs.length; j++) {
        cs[j].setAttribute('aria-pressed',
          cs[j].getAttribute('data-case') === cur ? 'true' : 'false');
      }
    }

    /* 跳到进度 u。**跳完把 s.t 对齐成 u*duration** —— 不对齐的话点播放
       画面会跳回拖之前的位置，看的人会以为拖动没生效 */
    function seekTo(u) {
      if (!seekable) return;
      u = u < 0 ? 0 : (u > 1 ? 1 : u);
      s.t = u * api.duration;
      if (range) range.value = String(u);
      if (num) num.textContent = Math.round(u * 100) + '%';
      try { api.seek(u); } catch (e) { console.error('[scene ' + id + '] seek', e); }
    }
    s.seekTo = seekTo;

    pp.addEventListener('click', function () { s.playing = !s.playing; paint(); });
    rp.addEventListener('click', function () {
      s.t = 0;
      if (range) range.value = '0';
      if (num) num.textContent = '0%';
      try { if (api.reset) api.reset(); api.step(0); } catch (e) { console.error('[scene ' + id + '] reset', e); }
    });

    if (range) {
      // 拖动时暂停，**松手后保持暂停** —— 演示时松手就跑，话还没说完画面已经过去了
      range.addEventListener('pointerdown', function () {
        s.scrub = true; s.playing = false; paint();
      });
      range.addEventListener('pointerup', function () { s.scrub = false; });
      range.addEventListener('pointercancel', function () { s.scrub = false; });
      range.addEventListener('input', function () { seekTo(parseFloat(range.value)); });
    }

    /* 键盘：演示时手在键盘上。只在这个 figure 获得焦点时生效 ——
       一页十几个场景，全局监听会让空格同时控制所有场景 */
    fig.setAttribute('tabindex', '0');
    fig.addEventListener('keydown', function (e) {
      if (e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault(); s.playing = !s.playing; paint(); return;
      }
      if (!seekable) return;
      var d = 1 / 400;
      var u = (s.t / api.duration) % 1;
      if (e.key === 'ArrowRight') { e.preventDefault(); s.playing = false; paint(); seekTo(u + d); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); s.playing = false; paint(); seekTo(u - d); }
      else if (e.key === 'Home') { e.preventDefault(); s.playing = false; paint(); seekTo(0); }
      else if (e.key === 'End') { e.preventDefault(); s.playing = false; paint(); seekTo(1); }
    });

    paint();
    try { if (api.reset) api.reset(); api.step(0); } catch (e) { console.error('[scene ' + id + '] first frame', e); }

    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (es) { s.visible = es[0].isIntersecting; },
        { rootMargin: '120px' }).observe(fig);
    }
    return s;
  }

  function boot() {
    var figs = document.querySelectorAll('figure[data-scene]');
    for (var i = 0; i < figs.length; i++) {
      var s = build(figs[i]);
      if (s) live.push(s);
    }
    var g = document.getElementById('gswitch');
    if (g) {
      g.addEventListener('click', function () {
        var anyOn = live.some(function (s) { return s.playing; });
        live.forEach(function (s) { if (s.playing === anyOn) s.pp.click(); });
        g.textContent = anyOn ? '▶ 全部播放' : '⏸ 全部暂停';
      });
      g.textContent = reduce ? '▶ 全部播放' : '⏸ 全部暂停';
    }
    var last = 0;
    function frame(now) {
      var dt = last ? Math.min((now - last) / 1000, 1 / 30) : 0;
      last = now;
      for (var i = 0; i < live.length; i++) {
        var s = live[i];
        if (!s.playing || !s.visible || s.scrub) continue;
        s.t += dt * s.speed;
        try { s.api.step(s.t); }
        catch (e) { console.error('[scene ' + s.id + '] step', e); s.playing = false; }
        if (s.seekable && s.api.duration) {
          var u = (s.t % s.api.duration) / s.api.duration;
          var r = s.fig.querySelector('.ctlbar input[type=range]');
          var n = s.fig.querySelector('.ctlbar .ctl-num');
          if (r) r.value = String(u);
          if (n) n.textContent = Math.round(u * 100) + '%';
        }
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
