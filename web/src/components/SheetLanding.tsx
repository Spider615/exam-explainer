import { useEffect, useRef, useState } from 'react'
import { getPaperSheets, Unauthorized } from '../api'

/**
 * `#/sheet/<卷名>` 落在哪一屏。
 *
 * 这个地址的含义是「**给我看这份卷子的诊断结果**」—— 库里点卷名、上传卡上那个
 * 「去看这份卷子 →」、书签、刷新、老地址 `#/p/<名>` 全落在它上面。所以这里
 * 先问出「该打开哪一份卡」，然后换到 `#/sheet/<卷名>/s<id>`。
 *
 * 五条硬约束：
 *
 * · **一律问端点，不拿列表里那份数据抄近路。** 列表可能是几秒前的：在卷子页
 *   传完一个新学生再退回来，那一行还指着上一份卡 —— 而两份诊断页长得一模一样
 *   （真实数据里学生名常常是空的），跳错了没人看得出来。省下的那次请求
 *   （一份卡摘要，几百字节）不值这个风险，而且判据写两处迟早有一处先改。
 *
 * · **换址用 replace，不用 push。** push 的话历史里会留下这个中转地址，
 *   老师按一次后退就回到它，然后又被解析走 —— 后退键在两页之间来回蹦。
 *
 * · **「没有可看的诊断结果」和「没问到」是两件事。**
 *   前者是权威答案，换成卷子页的地址（`/paper`）；后者（后端重启中、网络抖动、
 *   会话过期）**一个字都不许动地址** —— 动了的话，老师最自然的补救动作 F5
 *   重载的就是 `/paper`，他要看的那件事再也重试不到了。同一个文件里
 *   `App.tsx` 的 legacy 分支已经是这么做的（问不到就不动地址）。
 *   401 更要一动不动：那时 App 正在整页切登录框，重新登录后该落回他点的那一屏。
 *
 * · **改址之前先确认自己还在原地。** 浏览器后退是「先换 location、再派发
 *   hashchange」，中间有个窗口 —— 请求恰好在那时回来的话，replace 会把用户
 *   刚退回去的那一格改写掉，而且这次后退就白按了。
 *
 * · **解析期间不许先把卷子页画出来。** 闪一下再跳走，正是这次要消灭的那种
 *   「中间还有一层」的观感；出错时也不画整页卷子页（它带着上传入口，
 *   而这一屏的地址还停在「我要看诊断结果」上）。
 *
 * **调用方必须给 `key={卷名}`。** 换一份卷子走的是同文档 hash 跳转，不加 key
 * 的话 React 复用同一个实例、只换 `name`，上一份卷子的结论会先画出来。
 */
export default function SheetLanding({ name, onLand, onNoLanding, onOpenPaper }: {
  name: string
  /**
   * 解析出来了：**换**到这份卡的诊断页（调用方用 replace 改址，不留历史格）。
   * 这一跳是「把中转地址换掉」，不是一次导航。
   */
  onLand: (id: number) => void
  /** 权威答案说没有能看的诊断结果：**换**成卷子页的地址（同样 replace） */
  onNoLanding: () => void
  /** 出错时那条出路：去看这份卷子的标准答案（**push**，是真的一次导航） */
  onOpenPaper: () => void
}) {
  /** 问不到。**地址不动**，就地给一条能重试的出路 */
  const [err, setErr] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  const land = useRef(onLand)
  const noLand = useRef(onNoLanding)
  useEffect(() => { land.current = onLand; noLand.current = onNoLanding })

  useEffect(() => {
    let alive = true
    setErr(null)
    // 改址之前确认自己还在原地 —— 用户可能已经按了后退
    const here = () => window.location.hash === `#/sheet/${encodeURIComponent(name)}`
    /**
     * **等不到也要有个头。** fetch 本身不超时：合上笔记本再打开、切 wifi
     * （TCP 半开）、后端线程池被跑着的管线占满 —— 都能让它挂上几分钟，
     * 而这一屏在那期间一个字都不说。这个 App 里别处的长等待都说话
     *（上传卡「连不上后端 已经重试 N 次」、卷子页「问『进度』已经失败 N 次」）。
     */
    const stop = new AbortController()
    const timer = window.setTimeout(() => stop.abort(), 8000)
    getPaperSheets(name, stop.signal)
      .then((r) => {
        if (!alive || !here()) return
        if (r.landing) land.current(r.landing)
        else noLand.current()
      })
      .catch((e) => {
        if (!alive) return
        // 会话过期：App 正在整页切登录框，这里什么都不该做 ——
        // 尤其不许改地址，不然重新登录后落到的不是他点进来的那一屏
        if (e instanceof Unauthorized) return
        setErr(stop.signal.aborted
          ? '问了 8 秒没有回音 —— 后端可能正在重启，或者网络断了。'
          : (e instanceof Error ? e.message : String(e)))
      })
      .finally(() => window.clearTimeout(timer))
    return () => { alive = false; window.clearTimeout(timer); stop.abort() }
  }, [name, tick])

  if (err) {
    return (
      <div className="banner bad">
        <b>打不开这份卷子的诊断结果</b>　{err}
        <div className="runcard-acts">
          <button className="btn" onClick={() => setTick((t) => t + 1)}>再试一次</button>
          <button className="btn" onClick={onOpenPaper}>看这份卷子的标准答案 →</button>
        </div>
      </div>
    )
  }
  return <div className="empty"><b>正在打开诊断结果…</b></div>
}
