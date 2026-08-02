import { useEffect, useRef, useState } from 'react'

declare global {
  interface Window {
    Scenes?: Record<string, (fig: HTMLElement) => SceneApi>
  }
}

export interface SceneApi {
  step: (t: number) => void
  reset: () => void
  probe?: (u: number, caseId: string) => Record<string, number>
}

/**
 * 挂载一个物理动画场景。
 *
 * 帧循环写在这里，而不是复用 harness/_runtime.js —— 那份运行时挂在
 * DOMContentLoaded 上，SPA 里 figure 是后渲染的，时机对不上。
 * 契约本身没变：场景只实现 step(t)/reset()，谁来驱动由宿主决定。
 */
export default function SceneMount({ sceneId, figureHtml }: {
  sceneId: string
  figureHtml: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(true)
  const [failed, setFailed] = useState<string | null>(null)
  const api = useRef<SceneApi | null>(null)
  const visible = useRef(true)

  // 建场景：figure 注入 DOM 之后再调工厂
  useEffect(() => {
    const el = host.current?.querySelector<HTMLElement>('figure[data-scene]')
    if (!el) return
    const factory = window.Scenes?.[sceneId]
    if (typeof factory !== 'function') {
      setFailed('场景脚本未注册')
      return
    }
    try {
      const a = factory(el)
      if (typeof a?.step !== 'function') throw new Error('契约不符：缺少 step')
      api.current = a
      // 挂到元素上，供无头探针主动驱动。
      // 虚拟时间下 rAF 几乎不推进，只靠截图/等待判断「有没有动」必然误判——
      // 必须由测试自己调 step()。
      ;(el as HTMLElement & { __sceneApi?: SceneApi }).__sceneApi = a
      a.reset?.()
      a.step(0)
    } catch (e) {
      setFailed(String(e))
    }
    const io = new IntersectionObserver(
      (es) => { visible.current = es[0].isIntersecting },
      { rootMargin: '150px' },
    )
    io.observe(el)
    return () => { io.disconnect(); api.current = null }
  }, [sceneId, figureHtml])

  // 帧循环：离屏不推进，尊重 prefers-reduced-motion
  useEffect(() => {
    if (!playing || failed) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    let last = 0
    let t = 0
    const frame = (now: number) => {
      const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 0
      last = now
      if (visible.current && api.current) {
        t += dt
        try {
          api.current.step(t)
        } catch (e) {
          // 单个场景炸掉不能拖垮整页
          console.error(`[scene ${sceneId}]`, e)
          setFailed(String(e))
          return
        }
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [playing, failed, sceneId])

  // 「全部暂停/播放」：顶部统计条广播一个事件，每个场景各自响应。
  // 用事件而不是把状态提到 PaperView —— 场景是 dangerouslySetInnerHTML 出来的，
  // 播放状态属于场景自己，提上去就得让 PaperView 管一堆它不该管的东西。
  useEffect(() => {
    const h = (e: Event) => setPlaying((e as CustomEvent<boolean>).detail)
    window.addEventListener('scenes:playing', h)
    return () => window.removeEventListener('scenes:playing', h)
  }, [])

  const replay = () => {
    try {
      api.current?.reset()
      api.current?.step(0)
    } catch { /* 忽略：重播失败不影响已渲染的画面 */ }
  }

  return (
    <div ref={host}>
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
          <span className="livebadge" style={{ opacity: playing ? 0.9 : 0.3 }}>LIVE</span>
        </div>
      )}
    </div>
  )
}
