import { useState } from 'react'
import { uploadSheet } from '../api'
import type { SheetBrief } from '../types'

/**
 * 一份卷子下面的答题卡：列表 + 传一份新的。
 *
 * **一份卷子可以挂多份卡**（一个学生一份），所以这是列表不是单条。
 * 卡的进度和失败都画在**卡**上，不占上面那排按卷子算的格子 ——
 * 那排格子装不下「哪一份卡读到第几题」，而且没传答题卡的卷子会永远走不到
 * 「已完成」。理由写在 `pipeline/modes.py` 的 `_stage_of_sheet` 里。
 */
export default function Sheets({ paper, rows, onOpen }: {
  paper: string
  rows: SheetBrief[]
  onOpen: (id: number) => void
}) {
  const [student, setStudent] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const send = async () => {
    if (!files.length) return
    setBusy(true); setErr(null)
    try {
      const r = await uploadSheet(paper, student, files)
      setFiles([]); setStudent('')
      onOpen(r.sheet)
    } catch (e) {
      // 后端的 detail 要原样显示 —— 那几条都是能照着做的话
      //（「先把参考答案读完」「这份卷子正在跑」），糊成「上传失败」就白写了
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="sheets">
      <h3>学生的答题卡</h3>

      {rows.length === 0 ? (
        <p className="dim">还没有传过答题卡。传一份已经批改好的，就能逐题看对错。</p>
      ) : (
        <table className="sheet-tbl">
          <thead>
            <tr>
              <th>学生</th><th>总分</th><th>丢分</th>
              <th>错</th><th>半对</th><th>读出</th><th>页</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} onClick={() => onOpen(s.id)}>
                <td>{s.student || <span className="dim">未署名</span>}</td>
                <td>{s.total ?? <span className="dim">—</span>}</td>
                {/* 丢分排在错题数前面：薄弱知识点按它排，它才是要看的那个数 */}
                <td><b>{s.lost ?? '—'}</b></td>
                <td>{s.wrong}</td>
                {/* 半对**单独一列**。并进「错」的话，8 道半对的卡会显示「错 2 道」 */}
                <td>{s.partial}</td>
                <td>{s.answers}</td>
                <td>{s.nPages}</td>
                <td><button onClick={(e) => { e.stopPropagation(); onOpen(s.id) }}>
                  打开
                </button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="sheet-up">
        <input placeholder="学生（选填，比如「张三」）" value={student}
               onChange={(e) => setStudent(e.target.value)} />
        <input type="file" multiple accept="image/*,.pdf"
               onChange={(e) => setFiles(Array.from(e.target.files || []))} />
        <button disabled={busy || !files.length} onClick={send}>
          {busy ? '上传中…' : `传 ${files.length || ''} 张已批改的答题卡`}
        </button>
      </div>
      <p className="dim">
        手机截图直接传就行 —— 系统会把中间那条答题卡抠出来，
        状态栏和按钮不用自己裁掉。
      </p>
      {err && <div className="banner bad"><b>没传成</b>　{err}</div>}
    </section>
  )
}
