import { useCallback, useEffect, useState } from 'react'
import { deletePapers, listPapers } from './api'
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

  const setOpen = useCallback((name: string | null) => {
    window.location.hash = name ? `/p/${encodeURIComponent(name)}` : ''
    setOpenState(name)
  }, [])

  useEffect(() => {
    const h = () => setOpenState(readHash())
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])

  const refresh = useCallback(() => {
    listPapers().then(setRows).catch(() => setRows([]))
  }, [])
  useEffect(refresh, [refresh])

  // 列表每 8 秒自己刷一次。后台任务跑着的时候，退回试卷库也能看到它在推进——
  // 不刷新就只能看到一份「上次打开时」的快照
  useEffect(() => {
    if (open) return                     // 详情页有自己的轮询，别重复打
    const t = window.setInterval(refresh, 8000)
    return () => window.clearInterval(t)
  }, [open, refresh])

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

  return (
    // 试卷页多一栏目录，960 放不下：正文会被挤到 750 出头，题干读起来就窄了
    <div className={open ? 'wrap wide' : 'wrap'}>
      <div className="top">
        <button className="brand" onClick={() => setOpen(null)}>exam-explainer</button>
        <h1>{open ?? '上传试卷'}</h1>
        {open && (
          <span className="crumb">
            <button onClick={() => setOpen(null)}>← 回到试卷库</button>
          </span>
        )}
      </div>

      {open ? (
        <PaperView name={open} />
      ) : (
        <>
          <Upload onDone={(name) => { refresh(); setOpen(name) }} />
          <h2 className="lbl">试卷库</h2>
          {note && <div className="toast">{note}</div>}
          <PaperList rows={rows} onOpen={setOpen} onDelete={remove} busy={busy} />
          <div className="note">
            <b>当前能力</b>　① PDF 摄入、② 题目切分、⑦ 页面呈现已接通，全程纯代码零模型调用；
            切分不自信时会自动升级到模型通道，模型给的方案仍要过同一套结构门禁。
            <b>未接通</b>：③ 解题、④ 写断言、⑤ 生成场景。
          </div>
        </>
      )}
    </div>
  )
}
