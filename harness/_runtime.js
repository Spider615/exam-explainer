/* ===== 动画运行时 ===== */
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var live = [];

  function build(fig) {
    var id = fig.getAttribute('data-scene');
    var factory = window.Scenes[id];
    if (typeof factory !== 'function') return null;
    var api;
    try { api = factory(fig); } catch (e) { console.error('[scene ' + id + '] setup failed', e); return null; }
    if (!api || typeof api.step !== 'function') { console.error('[scene ' + id + '] bad contract'); return null; }

    var bar = document.createElement('div');
    bar.className = 'ctlbar';
    var pp = document.createElement('button');
    pp.type = 'button'; pp.className = 'btn pp';
    var rp = document.createElement('button');
    rp.type = 'button'; rp.className = 'btn'; rp.textContent = '重播';
    var tag = document.createElement('span');
    tag.className = 'livebadge'; tag.textContent = 'LIVE';
    bar.appendChild(pp); bar.appendChild(rp); bar.appendChild(tag);
    var own = fig.querySelector('.ctl');
    if (own) bar.appendChild(own);
    var cap = fig.querySelector('figcaption');
    fig.insertBefore(bar, cap);

    window.__api = window.__api || {}; window.__api[id] = api;
    var s = { id: id, api: api, t: 0, playing: !reduce, visible: true, fig: fig, pp: pp };
    function paint() {
      pp.textContent = s.playing ? '暂停' : '播放';
      pp.setAttribute('aria-pressed', s.playing ? 'true' : 'false');
      pp.setAttribute('aria-label', (s.playing ? '暂停' : '播放') + '动画');
      tag.style.opacity = s.playing ? '.9' : '.3';
    }
    pp.addEventListener('click', function () { s.playing = !s.playing; paint(); });
    rp.addEventListener('click', function () {
      s.t = 0;
      try { if (api.reset) api.reset(); api.step(0); } catch (e) { console.error('[scene ' + id + '] reset', e); }
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
        if (!s.playing || !s.visible) continue;
        s.t += dt;
        try { s.api.step(s.t); }
        catch (e) { console.error('[scene ' + s.id + '] step', e); s.playing = false; }
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
