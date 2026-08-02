import { useCallback, useEffect, useState } from 'react'
import { deletePapers, getMe, listPapers, logout, Unauthorized } from './api'
import Login from './components/Login'
import PaperList from './components/PaperList'
import PaperView from './components/PaperView'
import Upload from './components/Upload'
import type { PaperSummary } from './types'

/** 从 #/p/<name> 读当前试卷。用 hash 是为了让试卷页可以直接分享链接。 */
function readHash(): string | null {
  const m = /^#\/p\/(.+)$/.exec(window.location.hash)
  return m ? decodeURIComponent(m[1]) : null
}

export default function App() {
  const [rows, setRows] = useState<PaperSummary[]>([])
  const [open, setOpenState] = useState<string | null>(readHash)
  /**
   * 登录态。三个值不能合并成一个布尔：`undefined` 是「还没问过后端」。
   * 把它当成「没登录」的话，每次刷新页面都会先闪一下登录框再跳回列表。
   */
  const [me, setMe] = useState<string | null | undefined>(undefined)

  const checkMe = useCallback(() => {
    getMe().then((u) => setMe(u.email)).catch(() => setMe(null))
  }, [])
  useEffect(checkMe, [checkMe])

  const setOpen = useCallback((name: string | null) => {
    window.location.hash = name ? `/p/${encodeURIComponent(name)}` : ''
    setOpenState(name)
  }, [])

  useEffect(() => {
    const h = () => setOpenState(readHash())
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])

  // 任何一次请求撞上 401 都退回登录页（api.ts 里广播）。会话是 30 天，
  // 但它可能在一次长任务跑到一半时过期 —— 那时候页面正开着试卷页
  useEffect(() => {
    const h = () => setMe(null)
    window.addEventListener('auth:expired', h)
    return () => window.removeEventListener('auth:expired', h)
  }, [])

  const refresh = useCallback(() => {
    if (!me) return
    listPapers().then(setRows).catch((e) => {
      // 会话过期时不能只是清空列表——那看起来像「一份卷子都没有」。
      // 退回登录页，把「你得重新登录」这件事说出来
      if (e instanceof Unauthorized) setMe(null)
      setRows([])
    })
  }, [me])
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
        if (open && r.deleted.includes(open)) setOpen(null)
        const bits = [`已删除 ${r.deleted.length} 份`]
        if (r.missing.length) bits.push(`${r.missing.length} 份本来就不在`)
        if (r.objects) bits.push(`清理 ${r.objects} 个对象`)
        setNote(bits.join('，'))
        refresh()
      })
      .catch((e) => setNote('删除失败：' + e.message))
      .finally(() => setBusy(false))
  }, [open, refresh, setOpen])

  const signOut = useCallback(() => {
    logout().finally(() => { setMe(null); setRows([]); setOpen(null) })
  }, [setOpen])

  if (me === undefined) return <div className="wrap"><div className="empty">载入中…</div></div>
  // 登录页整页接管：没登录时页面上只该有一件事可做，套上「回到试卷库」那层
  // 壳只会给出一个点了没用的入口
  if (me === null) return <Login onDone={checkMe} />

  return (
    // 试卷页多一栏目录，960 放不下：正文会被挤到 750 出头，题干读起来就窄了
    <div className={open ? 'wrap wide' : 'wrap'}>
      <div className="top">
        <button className="brand" onClick={() => setOpen(null)}>exam-explainer</button>
        <h1>{open ?? '上传试卷'}</h1>
        <span className="crumb">
          {open && <button onClick={() => setOpen(null)}>← 回到试卷库</button>}
          <span className="who" title="试卷按账号隔离，这里只看得到你自己传的">{me}</span>
          <button onClick={signOut}>退出</button>
        </span>
      </div>

      {open ? (
        <PaperView name={open} />
      ) : (
        <>
          <Upload onDone={(name) => { refresh(); setOpen(name) }} />
          <h2 className="lbl">试卷库</h2>
          {note && <div className="toast">{note}</div>}
          <PaperList rows={rows} onOpen={setOpen} onDelete={remove} busy={busy} />
        </>
      )}
    </div>
  )
}
