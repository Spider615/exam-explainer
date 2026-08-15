import { useState } from 'react'
import { uploadSheet } from '../api'
import { fmtDur } from '../fmt'
import type { SheetBrief } from '../types'

/**
 * 一份卡这一趟跑成什么样，说给人听。**每一档都带下一步该干什么** ——
 * 光说「失败」的话，老师不知道该重传还是该等，而这两件事代价差很远。
 *
 * `done` 不在这里：跑完的卡由那一排数字说话，再挂个「已完成」是噪音。
 */
const STATE: Record<string, { word: string; pill: string; say: string }> = {
  running: { word: '在跑', pill: 'a', say: '一页三四分钟，读完自己会出结果' },
  failed: { word: '没跑成', pill: 'w', say: '' },
  empty: { word: '没读出作答', pill: 'w',
           say: '一条作答都没读出来 —— 换张清楚点的图重传' },
}

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
      <div className="sec-hd">
        <h2>学生的答题卡</h2>
        {rows.length > 0 && <span>{rows.length} 份</span>}
      </div>

      {rows.length === 0 ? (
        <div className="empty">
          <b>还没有传过答题卡</b>
          <span>传一份已经批改好的，就能逐题看对错、丢分和该补什么。</span>
        </div>
      ) : (
        <table className="lib sheet-tbl">
          <thead>
            <tr>
              <th>学生</th><th className="num">总分</th><th className="num">丢分</th>
              <th className="num">错</th><th className="num">半对</th>
              <th className="num">读出</th><th className="num">页</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              /* `done` 不在 STATE 里（跑完的卡由数字说话）；**后端还是旧的时候
                 `state` 是 undefined**，一样落到这里 —— 退回只显示数字，
                 而不是让 `STATE[undefined].pill` 把整页炸成白屏。
                 改完后端没重启是这个仓库反复发生的事，别让它以白屏收场 */
              const st = STATE[s.state]
              return (
              <tr key={s.id} onClick={() => onOpen(s.id)}>
                <td className="lib-name">
                  <button className="link" onClick={(e) => { e.stopPropagation(); onOpen(s.id) }}>
                    {s.student || '未署名'}
                  </button>
                </td>
                {!st ? (
                  <>
                    <td className="num" data-label="总分">
                      {s.total ?? <span className="dim">—</span>}
                    </td>
                    {/* 丢分排在错题数前面：薄弱知识点按它排，它才是要看的那个数 */}
                    <td className="num" data-label="丢分"><b>{s.lost ?? '—'}</b></td>
                    <td className="num" data-label="错">{s.wrong}</td>
                    {/* 半对**单独一列**。并进「错」的话，8 道半对的卡会显示「错 2 道」 */}
                    <td className="num" data-label="半对">{s.partial}</td>
                    <td className="num" data-label="读出">{s.answers}</td>
                  </>
                ) : (
                  /* 还没有数的时候**不摆五个 0**。那五个 0 正是「在跑」「跑挂了」
                     「读出 0」三种情况在这张表上长得一模一样的原因 ——
                     而这三种的下一步完全不同：等着、换图重传、去看原图 */
                  <td className="sheet-state" colSpan={5} data-label="状态">
                    <span className={`pill ${st.pill}`}>{st.word}</span>
                    {s.state === 'running' && s.runSeconds != null && (
                      <span className="dim">已跑 {fmtDur(s.runSeconds)}</span>
                    )}
                    {/* 失败原因是后端给的、能照着做的那句话，原样显示；
                        没给出原因时才退回本地那句通用的 */}
                    <span className="dim">{s.stateNote || st.say}</span>
                  </td>
                )}
                <td className="num" data-label="页">{s.nPages}</td>
                <td className="lib-more">
                  <button className="btn" onClick={(e) => { e.stopPropagation(); onOpen(s.id) }}>
                    打开
                  </button>
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
      )}

      <div className="sheet-up">
        <label className="fieldrow">
          <span>学生</span>
          <input placeholder="选填，比如「张三」" value={student}
                 onChange={(e) => setStudent(e.target.value)} />
        </label>
        <div className="sheet-up-go">
          <input type="file" multiple accept="image/*,.pdf" aria-label="选择已批改的答题卡"
                 onChange={(e) => setFiles(Array.from(e.target.files || []))} />
          <button className="btn hot" disabled={busy || !files.length} onClick={send}>
            {busy ? '上传中…' : `传 ${files.length || ''} 张已批改的答题卡`}
          </button>
        </div>
        <p className="dim">
          手机截图直接传就行 —— 系统会把中间那条答题卡抠出来，
          状态栏和按钮不用自己裁掉。
        </p>
      </div>
      {err && <div className="banner bad"><b>没传成</b>　{err}</div>}
    </section>
  )
}
