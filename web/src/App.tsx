import { useCallback, useEffect, useState } from 'react'
import { deletePapers, getMe, listPapers, logout, Unauthorized } from './api'
import Login from './components/Login'
import PaperList from './components/PaperList'
import PaperView from './components/PaperView'
import SheetList from './components/SheetList'
import SheetUpload from './components/SheetUpload'
import SheetView from './components/SheetView'
import Upload, { clearSavedJob } from './components/Upload'
import type { PaperSummary } from './types'

type Mode = 'paper' | 'sheet'

/**
 * 从地址读「哪个模式、开着哪份卷子」。
 *
 * `#/paper/<卷名>` `#/sheet/<卷名>`；只有模式时不开卷子。
 * **老地址 `#/p/<卷名>` 要继续能开** —— 直接失效是不可接受的，
 * 那些链接可能已经发出去了。命中时先当解析试卷开着，
 * 拿到整卷数据知道它真正的模式后再把地址换过去。
 */
function readHash(): { mode: Mode; open: string | null; legacy: boolean } {
  const h = window.location.hash
  let m = /^#\/(paper|sheet)(?:\/(.+))?$/.exec(h)
  if (m) return { mode: m[1] as Mode, open: m[2] ? decodeURIComponent(m[2]) : null,
                  legacy: false }
  m = /^#\/p\/(.+)$/.exec(h)
  if (m) return { mode: 'paper', open: decodeURIComponent(m[1]), legacy: true }
  return { mode: 'paper', open: null, legacy: false }
}

export default function App() {
  const [rows, setRows] = useState<PaperSummary[]>([])
  const [route, setRoute] = useState(readHash)
  const { mode, open } = route

  const go = useCallback((mode: Mode, name: string | null) => {
    window.location.hash = name
      ? `/${mode}/${encodeURIComponent(name)}` : `/${mode}`
    setRoute({ mode, open: name, legacy: false })
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

  useEffect(() => {
    const h = () => setRoute(readHash())
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])

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

  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

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
        mode === 'sheet' ? <SheetView name={open} /> : <PaperView name={open} />
      ) : mode === 'sheet' ? (
        <>
          <SheetUpload onDone={(n) => { refresh(); go('sheet', n) }} />
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
