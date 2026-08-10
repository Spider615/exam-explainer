import { useCallback, useEffect, useRef, useState } from 'react'
import { deletePapers, getMe, getProgress, listPapers, logout, Unauthorized } from './api'
import Login from './components/Login'
import PaperList from './components/PaperList'
import PaperView from './components/PaperView'
import SheetList from './components/SheetList'
import SheetUpload from './components/SheetUpload'
import SheetView from './components/SheetView'
import SheetDetail from './components/SheetDetail'
import Upload, { clearSavedJob } from './components/Upload'
import type { PaperSummary } from './types'

type Mode = 'paper' | 'sheet'

/**
 * 从地址读「哪个模式、开着哪份卷子」。
 *
 * `#/paper/<卷名>` `#/sheet/<卷名>`；只有模式时不开卷子。
 * 答题卡模式多一层：`#/sheet/<卷名>/s<卡号>` 打开某一份学生的答题卡。
 * 卡号带 `s` 前缀，免得和卷名里可能出现的数字段混起来。
 * **老地址 `#/p/<卷名>` 要继续能开** —— 直接失效是不可接受的，
 * 那些链接可能已经发出去了。命中时先当解析试卷开着，
 * 拿到整卷数据知道它真正的模式后再把地址换过去。
 */
function readHash(): {
  mode: Mode; open: string | null; sheet: number | null; legacy: boolean
} {
  const h = window.location.hash
  let m = /^#\/sheet\/(.+)\/s(\d+)$/.exec(h)
  if (m) return { mode: 'sheet', open: decodeURIComponent(m[1]),
                  sheet: Number(m[2]), legacy: false }
  m = /^#\/(paper|sheet)(?:\/(.+))?$/.exec(h)
  if (m) return { mode: m[1] as Mode, open: m[2] ? decodeURIComponent(m[2]) : null,
                  sheet: null, legacy: false }
  m = /^#\/p\/(.+)$/.exec(h)
  if (m) return { mode: 'paper', open: decodeURIComponent(m[1]), sheet: null,
                  legacy: true }
  return { mode: 'paper', open: null, sheet: null, legacy: false }
}

export default function App() {
  const [rows, setRows] = useState<PaperSummary[]>([])
  const [route, setRoute] = useState(readHash)
  const { mode, open, sheet } = route

  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  // `go` 和 hashchange 都要知道「换模式前是哪个模式」，但只有 `go` 能在
  // 同一次调用里同步拿到旧值——hashchange 触发时 `mode` 这个闭包变量可能是
  // 装载时那份旧的（effect 依赖是 []）。用一个跟着 `mode` 走的 ref，两条路径
  // 读同一份「当下真正的模式」，不用各自猜
  const modeRef = useRef(mode)
  useEffect(() => { modeRef.current = mode }, [mode])

  /**
   * 换模式要把上一屏的残留清掉。 不清的话，在解析试卷删完一份卷子再切到
   * 答题卡诊断，那句「已删除 1 份」会跟着挂在答题卡库上面 —— 而那一屏什么都
   * 没删过。`rows` 同理：`refresh` 是异步的，不清就有至少一帧拿上一个模式的
   * 卷子去渲染这一屏的表格（PDF 卷子出现在答题卡库里，带着两列空的「带解答 /
   * 挂知识点」）。「互相看不见对方的卷子」这句话得是真的，不能只写在注释里。
   *
   * **两条路径共用这一个函数，不许各写一份。** 以前这段清理只写在 `go` 里，
   * 只覆盖点击路径——从答题卡按浏览器后退回解析试卷，hashchange 处理器
   * 直接 `setRoute(readHash())`，什么都不清，会有至少一帧用答题卡的
   * `rows` 去渲染解析试卷的表格。「互相看不见」那句注释于是只写在注释里，
   * 这条路径上从没兑现过。
   *
   * 清空写在这里而不是 `setRoute` 的更新函数里：更新函数必须是纯的，
   * StrictMode 下会跑两遍，把副作用塞进去等于让它执行两次。
   */
  const clearModeResidue = useCallback(() => { setRows([]); setNote(null) }, [])

  const go = useCallback((next: Mode, name: string | null) => {
    window.location.hash = name
      ? `/${next}/${encodeURIComponent(name)}` : `/${next}`
    if (next !== modeRef.current) clearModeResidue()
    setRoute({ mode: next, open: name, sheet: null, legacy: false })
  }, [clearModeResidue])

  /** 打开/关掉某一份答题卡。地址要跟着变，刷新和分享才回得到同一屏 */
  const goSheet = useCallback((name: string, id: number | null) => {
    window.location.hash = id
      ? `/sheet/${encodeURIComponent(name)}/s${id}`
      : `/sheet/${encodeURIComponent(name)}`
    setRoute({ mode: 'sheet', open: name, sheet: id, legacy: false })
  }, [])

  /**
   * 登录态。三个值不能合并成一个布尔：`undefined` 是「还没问过后端」。
   * 把它当成「没登录」的话，每次刷新页面都会先闪一下登录框再跳回列表。
   */
  const [me, setMe] = useState<string | null | undefined>(undefined)

  const checkMe = useCallback(() => {
    getMe().then((u) => setMe(u.email)).catch(() => setMe(null))
  }, [])
  useEffect(checkMe, [checkMe])

  /**
   * 老地址 `#/p/<卷名>` 落地后，把它换到这份卷子真正属于的那个模式去。
   *
   * **不换的话，一份答案卷会用解析试卷那套页面打开** —— 答案速览、动画开关、
   * 「解题步骤与动画均由 AI 生成」的页脚，全是错的话。那正是这轮要消灭的
   * 「两套话术缠在一起」。
   *
   * 问的是 `/progress` 而不是整卷：它是那个轻量端点（只有计数），而且已经带着
   * `mode.code` —— 模式的判定留在后端，前端不再自己从 sourceKind 映射一遍。
   * 问不到（卷子不在了、会话过期）就留在解析试卷模式，让详情页自己把
   * 「打不开」说出来 —— 这里不该替它编一句话。
   */
  useEffect(() => {
    if (!route.legacy || !route.open || !me) return
    let alive = true
    getProgress(route.open)
      .then((p) => {
        if (!alive) return
        const m = p.mode?.code === 'sheet' ? 'sheet' : 'paper'
        go(m, route.open)
      })
      .catch(() => { if (alive) setRoute((r) => ({ ...r, legacy: false })) })
    return () => { alive = false }
  }, [route.legacy, route.open, me, go])

  // 浏览器前进/后退也要走上面那段模式清理，不能只在 `go()` 里做一遍
  useEffect(() => {
    const h = () => {
      const next = readHash()
      if (next.mode !== modeRef.current) clearModeResidue()
      setRoute(next)
    }
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [clearModeResidue])

  // 任何一次请求撞上 401 都退回登录页（api.ts 里广播）。会话是 30 天，
  // 但它可能在一次长任务跑到一半时过期 —— 那时候页面正开着试卷页
  useEffect(() => {
    // 句柄跟着会话作废。过期和主动登出是同一件事 —— 不清的话，下一个在这台
    // 机器上登进来的人会拿着别人的任务 id 去问，只能得到一条 404 和一句
    // 关于他从没传过的卷子的说明
    const h = () => { clearSavedJob(); setMe(null) }
    window.addEventListener('auth:expired', h)
    return () => window.removeEventListener('auth:expired', h)
  }, [])

  const refresh = useCallback(() => {
    if (!me) return
    listPapers(mode).then(setRows).catch((e) => {
      // 会话过期时不能只是清空列表——那看起来像「一份卷子都没有」。
      // 退回登录页，把「你得重新登录」这件事说出来
      if (e instanceof Unauthorized) setMe(null)
      setRows([])
    })
  }, [me, mode])
  useEffect(refresh, [refresh])

  // 列表每 8 秒自己刷一次。后台任务跑着的时候，退回试卷库也能看到它在推进——
  // 不刷新就只能看到一份「上次打开时」的快照
  useEffect(() => {
    if (open || !me) return              // 详情页有自己的轮询，别重复打
    const t = window.setInterval(refresh, 8000)
    return () => window.clearInterval(t)
  }, [open, me, refresh])

  const remove = useCallback((names: string[]) => {
    setBusy(true)
    setNote(null)
    deletePapers(names)
      .then((r) => {
        // 删掉的正好是当前打开的那份，就退回列表——否则详情页会 404
        if (open && r.deleted.includes(open)) go(mode, null)
        const bits = [`已删除 ${r.deleted.length} 份`]
        if (r.missing.length) bits.push(`${r.missing.length} 份本来就不在`)
        if (r.objects) bits.push(`清理 ${r.objects} 个对象`)
        setNote(bits.join('，'))
        refresh()
      })
      .catch((e) => setNote('删除失败：' + e.message))
      .finally(() => setBusy(false))
  }, [open, mode, refresh, go])

  const signOut = useCallback(() => {
    // 上传任务的句柄也要清 —— 它是上一个账号的，留着只会让下一个人看到一条 404
    clearSavedJob()
    logout().finally(() => { setMe(null); setRows([]); go(mode, null) })
  }, [mode, go])

  if (me === undefined) return <div className="wrap"><div className="empty">载入中…</div></div>
  // 登录页整页接管：没登录时页面上只该有一件事可做，套上「回到试卷库」那层
  // 壳只会给出一个点了没用的入口
  if (me === null) return <Login onDone={checkMe} />

  return (
    // 试卷页多一栏目录，960 放不下：正文会被挤到 750 出头，题干读起来就窄了
    <div className={open ? 'wrap wide' : 'wrap'}>
      <div className="top">
        <button className="brand" onClick={() => go(mode, null)}>exam-explainer</button>
        <h1>{open ?? (mode === 'sheet' ? '答题卡诊断' : '上传试卷')}</h1>
        <span className="crumb">
          {open && <button onClick={() => go(mode, null)}>← 回到{mode === 'sheet' ? '答题卡库' : '试卷库'}</button>}
          <span className="who" title="卷子按账号隔离，这里只看得到你自己传的">{me}</span>
          <button onClick={signOut}>退出</button>
        </span>
      </div>

      {/* 两个模式是两件事，不是一个筛选器。切过去整屏都换：上传框、列表列头、
          详情页。互相看不见对方的卷子 */}
      <nav className="modes">
        <button className={mode === 'paper' ? 'on' : ''}
                onClick={() => go('paper', null)}>解析试卷</button>
        <button className={mode === 'sheet' ? 'on' : ''}
                onClick={() => go('sheet', null)}>答题卡诊断</button>
      </nav>

      {open ? (
        mode === 'sheet' ? (
          sheet != null
            ? <SheetDetail id={sheet} onBack={() => goSheet(open, null)} />
            : <SheetView name={open} onOpenSheet={(id) => goSheet(open, id)} />
        ) : <PaperView name={open} />
      ) : mode === 'sheet' ? (
        <>
          <SheetUpload onDone={(n, o) => { refresh(); if (o) go('sheet', n) }} />
          <h2 className="lbl">答题卡库</h2>
          {note && <div className="toast">{note}</div>}
          <SheetList rows={rows} onOpen={(n) => go('sheet', n)}
                     onDelete={remove} busy={busy} />
        </>
      ) : (
        <>
          <Upload onDone={(n, o) => { refresh(); if (o) go('paper', n) }} />
          <h2 className="lbl">试卷库</h2>
          {note && <div className="toast">{note}</div>}
          <PaperList rows={rows} onOpen={(n) => go('paper', n)}
                     onDelete={remove} busy={busy} />
        </>
      )}
    </div>
  )
}
