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
export default function SheetList({ rows, onOpen, onOpenPaper, onDelete, busy }: {
  rows: PaperSummary[]
  /**
   * 点卷名。**直接落到诊断结果页。**
   *
   * 这里只负责说「打开这份卷子的诊断结果」，该落到哪一份卡由 `SheetLanding`
   * 解析（`latestSheet` 只用来把 title 那句话说准）—— 判据写两处的话，
   * 迟早有一处先改，而两处的差别表现为「从库里点和从书签进打开了不同的学生」。
   */
  onOpen: (r: PaperSummary) => void
  /** 明确要看卷子页（标准答案、知识点、Ⓐ 的进度、再传一份的入口） */
  onOpenPaper: (name: string) => void
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
      { key: 'sheets', label: '答题卡', num: true },
      { key: 'more', label: '' },
    ]}>
      {rows.map((r) => (
        <tr key={r.name}>
          <td className="lib-name">
            <button className="link" onClick={() => onOpen(r)}
                    title={r.latestSheet
                      ? '打开这份卷子最新的诊断结果'
                      : '这份卷子还没有能看的诊断结果，先进卷子页'}>
              {r.name}
            </button>
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
          {/* 挂上知识点的题数。**这一格原来根本没渲染** —— 表头有「挂知识点」，
              行里没有对应的 `<td>`，于是后面每一格都往左挪了一位：答题卡数
              显示在「挂知识点」底下，`⋯` 显示在「答题卡」底下。整轮 UI 重做
              都没被发现（每一格单看都对），是 `test_lib_columns.py` 数出来的。

              **0 要显示成 0，不能显示成「—」。** 「一道都没挂上」正是这份卷子
              走不到「已完成」的原因，那是要看见的信号，不是缺数据 */}
          <td className="num" data-label="挂知识点"
              title="③c 挂上知识点的题数。挂不满是正常的——只有一个字母答案的题
                     判不出考什么；但 0 意味着这一步根本没跑成">
            {r.kps ?? 0}
          </td>
          {/* 挂了几份卡。**它是去卷子页的入口** —— 卷名那一跳直奔诊断结果，
              而「另一个学生」「每题的标准答案」「再传一份」都在卷子页上，
              得有一处点得进去 */}
          <td className="num" data-label="答题卡">
            {r.sheets
              ? <button className="link" onClick={() => onOpenPaper(r.name)}
                        title="看这份卷子的标准答案，或者再传一份答题卡">
                  {r.sheets} 份
                </button>
              : <button className="link dim" onClick={() => onOpenPaper(r.name)}
                        title="还没传过答题卡，点这里去传">
                  还没传
                </button>}
          </td>
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
