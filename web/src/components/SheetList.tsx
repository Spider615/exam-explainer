import type { PaperSummary } from '../types'

/**
 * 答题卡库。
 *
 * 列头和试卷库**不一样**：那边是「插图 / 动画 / 告警」，这个模式里插图和动画
 * 永远是 0，不该占一列。这边关心的是「读出来几题、几题有官方解答、几题挂上了
 * 知识点」。
 */
export default function SheetList({ rows, onOpen, onDelete, busy }: {
  rows: PaperSummary[]
  onOpen: (name: string) => void
  onDelete: (names: string[]) => void
  busy: boolean
}) {
  if (!rows.length) {
    return <div className="empty">还没有传过参考答案</div>
  }
  const confirmDelete = (name: string) => {
    if (!window.confirm(`删除「${name}」？此操作不可恢复。`)) return
    onDelete([name])
  }
  return (
    <table>
      <thead>
        <tr>
          <th>卷名</th><th>进度</th><th>题数</th><th>带解答</th><th>挂知识点</th><th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td><button className="link" onClick={() => onOpen(r.name)}>{r.name}</button></td>
            <td className="prg">
              {r.progress ? (
                r.progress.busy
                  ? <span className="run"><i />{r.progress.short}</span>
                  : r.progress.done
                    ? <span className="pill g">已完成</span>
                    : <span className="pill">已停止 · {r.progress.short}</span>
              ) : null}
            </td>
            <td className="num">{r.n}</td>
            {/* 「带解答」天生小于题数：参考答案的版式就是只有大题给详解 */}
            <td className="num" title="有官方解答过程的题数。只有大题才有，这是参考答案的版式决定的">
              {r.withSolution ?? 0}
            </td>
            <td className="num">{r.kps ?? 0}</td>
            <td>
              <button className="del" disabled={busy} title={`删除 ${r.name}`}
                      onClick={() => confirmDelete(r.name)}>删除</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
