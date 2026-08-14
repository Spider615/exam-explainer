import LibraryTable, { RowMenu } from './LibraryTable'
import StatusBadge from './StatusBadge'
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
    return (
      <div className="empty">
        <b>还没有传过参考答案</b>
        <span>上面那三个框里，「参考答案」是必填的 —— 它是整份诊断的地基。</span>
      </div>
    )
  }
  const confirmDelete = (name: string) => {
    if (!window.confirm(`删除「${name}」？此操作不可恢复。`)) return
    onDelete([name])
  }
  return (
    <LibraryTable cols={[
      { key: 'name', label: '卷名' },
      { key: 'prog', label: '进度' },
      { key: 'n', label: '题数', num: true },
      { key: 'sol', label: '带解答', num: true },
      { key: 'kp', label: '挂知识点', num: true },
      { key: 'more', label: '' },
    ]}>
      {rows.map((r) => (
        <tr key={r.name}>
          <td className="lib-name">
            <button className="link" onClick={() => onOpen(r.name)}>{r.name}</button>
          </td>
          <td className="prg" data-label="进度">
            {r.progress ? (
              r.progress.busy
                ? <StatusBadge tone="run" text={r.progress.short} />
                : r.progress.done
                  ? <StatusBadge tone="ok" text="已完成" />
                  : <StatusBadge tone="idle" text={`已停止 · ${r.progress.short}`}
                                 title={`没有进程在跑，停在「${r.progress.stage}」`} />
            ) : null}
          </td>
          <td className="num" data-label="题数">{r.n}</td>
          {/* 「带解答」天生小于题数：参考答案的版式就是只有大题给详解 */}
          <td className="num" data-label="带解答"
              title="有官方解答过程的题数。只有大题才有，这是参考答案的版式决定的">
            {r.withSolution ?? 0}
          </td>
          <td className="num" data-label="挂知识点">{r.kps ?? 0}</td>
          <td className="lib-more">
            <RowMenu label={`「${r.name}」的更多操作`}>
              <button className="rowmenu-danger" disabled={busy}
                      onClick={() => confirmDelete(r.name)}>删除这份卷子</button>
            </RowMenu>
          </td>
        </tr>
      ))}
    </LibraryTable>
  )
}
