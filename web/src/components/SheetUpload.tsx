import { useRef, useState } from 'react'
import { uploadAnswerPaper } from '../api'

/**
 * 答题卡模式的上传框：卷名 + 一批参考答案。
 *
 * **卷名必须人填。** 这边收的是一批照片，文件名是 `IMG_0123` 这种，
 * 推不出任何有意义的卷名 —— 而卷名是页面地址的一部分，将来还要打印在报告上。
 */
export default function SheetUpload({ onDone }: {
  onDone: (name: string) => void
}) {
  const [name, setName] = useState('')
  const [hot, setHot] = useState(false)
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const pick = useRef<HTMLInputElement>(null)

  async function send(files: File[]) {
    if (!files.length) return
    if (!name.trim()) { setErr('先填一个卷名'); return }
    setErr(null); setNote(null); setSending(true)
    try {
      const r = await uploadAnswerPaper(name.trim(), files)
      // 后端可能改过名（撞上别人的卷子、或撞上自己的一份解析试卷）。
      // 改了就要说出来 —— 不说的话人会去库里找那个他填的名字，找不到
      setNote(r.name === name.trim()
        ? `已开始读「${r.name}」的参考答案`
        : `卷名「${name.trim()}」已经被占用，这份存成了「${r.name}」`)
      onDone(r.name)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div>
      <label className="fieldrow">
        <span>卷名</span>
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="2025-2026高二物理期末" disabled={sending} />
      </label>
      <div
        className={`drop${hot ? ' hot' : ''}${sending ? ' busy' : ''}`}
        onClick={() => pick.current?.click()}
        onDragEnter={(e) => { e.preventDefault(); setHot(true) }}
        onDragOver={(e) => { e.preventDefault(); setHot(true) }}
        onDragLeave={() => setHot(false)}
        onDrop={(e) => {
          e.preventDefault(); setHot(false)
          void send([...e.dataTransfer.files])
        }}
      >
        <b>{sending ? '上传中…' : '把参考答案拖到这里'}</b>
        <span>
          {sending ? '正在把文件送上去'
            : '照片 / 扫描图 / PDF 都行，可以一次多张 · 按文件名排页序'}
        </span>
        <input ref={pick} type="file" multiple hidden
               accept="image/*,application/pdf"
               onChange={(e) => void send([...(e.target.files ?? [])])} />
      </div>
      {err && <div className="banner bad"><b>失败</b>　{err}</div>}
      {note && <div className="banner">{note}</div>}
    </div>
  )
}
