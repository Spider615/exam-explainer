import { useCallback, useEffect, useRef, useState } from 'react'

declare global {
  interface Window {
    Scenes?: Record<string, (fig: HTMLElement) => SceneApi>
  }
}

export interface SceneApi {
  step: (t: number) => void
  reset: () => void
  probe?: (u: number, caseId: string) => Record<string, number>
  /** 下面几样只有代码生成的新场景才有。老场景没有，宿主必须检测后再用 */
  duration?: number
  cases?: string[]
  seek?: (u: number) => void
  setCase?: (caseId: string) => string
  currentCase?: () => string
}

const SPEEDS = [0.5, 1, 2]

/**
 * 挂载一个物理动画场景。
 *
 * 帧循环写在这里，而不是复用 harness/_runtime.js —— 那份运行时挂在
 * DOMContentLoaded 上，SPA 里 figure 是后渲染的，时机对不上。
 * 契约本身没变：场景只实现 step(t)/reset()，谁来驱动由宿主决定。
 *
 * 时间轴为什么要「检测后再用」
 * ---------------------------
 * `duration`/`seek` 是这次代码生成才有的。老场景（36 个已经上线的）没有，
 * 它们只知道 `t % 自己内部的周期`，宿主拿不到总时长就画不出刻度。
 * **检测不到就退回播放/暂停，不能留一个拖不动的空条** —— 那比没有更糟。
 */
export default function SceneMount({ sceneId, figureHtml }: {
  sceneId: string
  figureHtml: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(true)
  const [failed, setFailed] = useState<string | null>(null)
  const [speed, setSpeed] = useState(1)
  const [u, setU] = useState(0)
  /** 有没有时间轴能力。老场景是 null */
  const [seekable, setSeekable] = useState<{ duration: number; cases: string[] } | null>(null)
  const [curCase, setCurCase] = useState<string>('')
  const api = useRef<SceneApi | null>(null)
  const visible = useRef(true)
  /** 帧循环的累计时间。seek 要能改它，所以放 ref 不放闭包 */
  const tRef = useRef(0)
  const scrubbing = useRef(false)

  // 建场景：figure 注入 DOM 之后再调工厂
  useEffect(() => {
    const el = host.current?.querySelector<HTMLElement>('figure[data-scene]')
    if (!el) return
    setFailed(null)
    setSeekable(null)
    setU(0)
    tRef.current = 0
    let io: IntersectionObserver | null = null
    let timer = 0
    let tries = 0

    /**
     * **工厂可能还没到，要等。**
     *
     * 重跑换了动画之后，sceneId 立刻就变成新的，而新的 scene.js 是
     * PaperView 用 <script> 异步加载的 —— 这个 effect 跑在它到达之前。
     * 原来这里一查不到就 setFailed('场景脚本未注册')，于是新动画只剩
     * figure.html 里写死的静态首帧、帧循环还被 failed 挡住不跑，
     * 非刷新页面不可。现在改成轮询等它，等不到才判失败。
     */
    const build = () => {
      const factory = window.Scenes?.[sceneId]
      if (typeof factory !== 'function') {
        if (++tries > 100) { setFailed('场景脚本未注册'); return }   // 100×100ms = 10s
        timer = window.setTimeout(build, 100)
        return
      }
      try {
        const a = factory(el)
        if (typeof a?.step !== 'function') throw new Error('契约不符：缺少 step')
        api.current = a
        ;(el as HTMLElement & { __sceneApi?: SceneApi }).__sceneApi = a
        // 两样都齐才认为能拖。只有 duration 没有 seek 的话拖了也没反应
        if (typeof a.seek === 'function' && typeof a.duration === 'number' && a.duration > 0) {
          setSeekable({ duration: a.duration, cases: a.cases ?? [] })
          setCurCase(a.currentCase?.() ?? (a.cases?.[0] ?? ''))
        }
        a.reset?.()
        a.step(0)
        setPlaying(true)
      } catch (e) {
        setFailed(String(e))
      }
    }
    build()

    io = new IntersectionObserver(
      (es) => { visible.current = es[0].isIntersecting },
      { rootMargin: '150px' },
    )
    io.observe(el)
    return () => {
      if (timer) window.clearTimeout(timer)
      io?.disconnect()
      api.current = null
    }
  }, [sceneId, figureHtml])

  // 帧循环：离屏不推进，尊重 prefers-reduced-motion
  useEffect(() => {
    if (!playing || failed) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    let last = 0
    const frame = (now: number) => {
      const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 0
      last = now
      if (visible.current && api.current && !scrubbing.current) {
        tRef.current += dt * speed
        try {
          api.current.step(tRef.current)
          const d = api.current.duration
          if (d) setU((tRef.current % d) / d)
        } catch (e) {
          console.error(`[scene ${sceneId}]`, e)
          setFailed(String(e))
          return
        }
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [playing, failed, sceneId, speed])

  // 「全部暂停/播放」：顶部统计条广播一个事件，每个场景各自响应。
  useEffect(() => {
    const h = (e: Event) => setPlaying((e as CustomEvent<boolean>).detail)
    window.addEventListener('scenes:playing', h)
    return () => window.removeEventListener('scenes:playing', h)
  }, [])

  /**
   * 跳到进度 uu。
   *
   * **跳完把 tRef 对齐成 uu*duration** —— 不对齐的话点「播放」画面会跳回
   * 拖之前的位置，老师会以为拖动没生效。
   */
  const seekTo = useCallback((uu: number) => {
    const a = api.current
    if (!a?.seek || !a.duration) return
    const v = Math.min(1, Math.max(0, uu))
    setU(v)
    tRef.current = v * a.duration
    try { a.seek(v) } catch (e) { console.error(`[scene ${sceneId}]`, e) }
  }, [sceneId])

  const replay = () => {
    tRef.current = 0
    setU(0)
    try {
      api.current?.reset()
      api.current?.step(0)
    } catch { /* 忽略：重播失败不影响已渲染的画面 */ }
  }

  /**
   * 键盘：老师演示时手在键盘上，够不着鼠标。
   *
   * 只在这个场景获得焦点时生效 —— 一页有十几个场景，全局监听会让空格
   * 同时控制所有场景。
   */
  const onKey = (e: React.KeyboardEvent) => {
    if (failed) return
    const d = seekable?.duration
    if (e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault(); setPlaying((p) => !p); return
    }
    if (!d) return
    const stepU = 1 / 400                       // 与 spec 的 sample_points 同量级
    if (e.key === 'ArrowRight') { e.preventDefault(); setPlaying(false); seekTo(u + stepU) }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); setPlaying(false); seekTo(u - stepU) }
    else if (e.key === 'Home') { e.preventDefault(); setPlaying(false); seekTo(0) }
    else if (e.key === 'End') { e.preventDefault(); setPlaying(false); seekTo(1) }
  }

  return (
    <div ref={host} tabIndex={0} onKeyDown={onKey} className="scenebox">
      <div dangerouslySetInnerHTML={{ __html: figureHtml }} />
      {failed ? (
        <div className="warn">动画未能启动：{failed}（已退回静态首帧）</div>
      ) : (
        <div className="ctlbar">
          <button className="btn" aria-pressed={playing}
                  onClick={() => setPlaying((p) => !p)}>
            {playing ? '暂停' : '播放'}
          </button>
          <button className="btn" onClick={replay}>重播</button>

          {/* 时间轴只在场景支持时出现。检测不到就什么都不画 ——
              留一个拖不动的空条比没有更糟 */}
          {seekable && (
            <>
              <input
                type="range" min={0} max={1} step={0.001} value={u}
                aria-label="播放进度"
                onPointerDown={() => { scrubbing.current = true; setPlaying(false) }}
                onPointerUp={() => { scrubbing.current = false }}
                onPointerCancel={() => { scrubbing.current = false }}
                onChange={(e) => seekTo(Number(e.target.value))}
              />
              {/* 松手后**保持暂停**：演示时松手就跑，话还没说完画面已经过去了 */}
              <span className="ctl-num">{(u * 100).toFixed(0)}%</span>
              <span className="ctl-num">{(u * seekable.duration).toFixed(1)}s</span>
            </>
          )}

          {seekable && (
            <span className="ctl">
              {SPEEDS.map((s) => (
                <button key={s} className="btn" aria-pressed={speed === s}
                        onClick={() => setSpeed(s)}>{s}×</button>
              ))}
            </span>
          )}

          {/* 多情形：切的是读数面板显示哪一个，画面上各情形本来就一起画 */}
          {seekable && seekable.cases.length > 1 && (
            <span className="ctl">
              <span className="ctl-lab">读数</span>
              {seekable.cases.map((c) => (
                <button key={c} className="btn" aria-pressed={curCase === c}
                        onClick={() => {
                          const got = api.current?.setCase?.(c)
                          if (got) { setCurCase(got); seekTo(u) }
                        }}>{c}</button>
              ))}
            </span>
          )}

          <span className="livebadge" style={{ opacity: playing ? 0.9 : 0.3 }}>LIVE</span>
        </div>
      )}
    </div>
  )
}
