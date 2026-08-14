import { useState } from 'react'
import LibraryTable, { RowMenu } from './LibraryTable'
import StatusBadge from './StatusBadge'
import type { PaperSummary } from '../types'

/**
 * 进度列只放**一个状态**，不是一串阶段计数。
 *
 * 一行里放得下的信息很少，所以先答「它现在怎么样」：失败 / 在跑 / 已完成 /
 * 已停止。在跑的时候才补上是哪一步、到第几题（`解题中 15/16`）；停下来的时候
 * 也要说停在哪 —— 光写「已停止」，人无从知道是差一步还是差一半。
 *
 * 「已完成」的判据是 ⑦ 装的就是当前这份数据。装过但比库里的数据旧**不算**：
 * 那种情况下手里那份 out.html 还是解法更少的旧版本，标成完成是骗人的。
 */
function Prog({ p }: { p: NonNullable<PaperSummary['progress']> }) {
  const at = p.total > 1 ? ` ${p.cur}/${p.total}` : ''
  const failureCount = p.solutionFailures ?? 0
  if (p.failed) return <StatusBadge tone="bad" text="失败" title={p.failed} />
  if (p.busy) return <StatusBadge tone="run" text={`${p.short}${at}`} />
  if (p.done && failureCount)
    return <StatusBadge tone="warn" text={`已完成 · ${failureCount} 题失败`} />
  if (p.done) return <StatusBadge tone="ok" text="已完成" />
  return (
    <StatusBadge tone="idle" text={`已停止 · ${p.short}${at}`}
                 title={`没有进程在跑，停在「${p.stage}」`} />
  )
}

/**
 * 试卷库。
 *
 * 删除是不可逆的，所以确认框里要写清**删的是哪几份**，不能只说「确定删除 3 份？」——
 * 勾错一个的代价是重新跑一遍管线，而用户在点确认那一刻已经看不到列表了。
 */
export default function PaperList({ rows, onOpen, onDelete, busy }: {
  rows: PaperSummary[]
  onOpen: (name: string) => void
  onDelete: (names: string[]) => void
  busy: boolean
}) {
  const [sel, setSel] = useState<Set<string>>(new Set())

  if (!rows.length) {
    return (
      <div className="empty">
        <b>还没有处理过任何试卷</b>
        <span>把一份有文字层的物理卷 PDF 拖到上面那个框里就开始。</span>
      </div>
    )
  }

  // 列表会因为删除/上传而变，选中集合里可能留着已经不在的名字
  const live = rows.filter((r) => sel.has(r.name)).map((r) => r.name)
  const allOn = live.length === rows.length && rows.length > 0

  const toggle = (name: string) => {
    const s = new Set(sel)
    s.has(name) ? s.delete(name) : s.add(name)
    setSel(s)
  }
  const toggleAll = () => setSel(allOn ? new Set() : new Set(rows.map((r) => r.name)))

  const confirmDelete = (names: string[]) => {
    const list = names.length > 8
      ? names.slice(0, 8).join('\n') + `\n…… 另外 ${names.length - 8} 份`
      : names.join('\n')
    if (!window.confirm(`删除以下 ${names.length} 份试卷？此操作不可恢复。\n\n${list}`)) return
    setSel(new Set())
    onDelete(names)
  }

  return (
    <>
      {live.length > 0 && (
        <div className="bulkbar">
          <span>已选 {live.length} 份</span>
          <button className="danger" disabled={busy} onClick={() => confirmDelete(live)}>
            {busy ? '删除中…' : '删除所选'}
          </button>
          {/* 窄屏下表头（连同那个「全选」勾选框）是收起来的，全选得在这里够得着 */}
          <button onClick={toggleAll}>{allOn ? '取消全选' : '全选'}</button>
          <button onClick={() => setSel(new Set())}>取消选择</button>
        </div>
      )}
      <LibraryTable cols={[
        { key: 'ck',
          label: <input type="checkbox" checked={allOn} onChange={toggleAll}
                        aria-label="全选" /> },
        { key: 'name', label: '试卷' },
        { key: 'prog', label: '进度' },
        { key: 'n', label: '题数', num: true },
        { key: 'fig', label: '插图', num: true },
        { key: 'scene', label: '动画', num: true },
        { key: 'warn', label: '告警', num: true },
        { key: 'more', label: '' },
      ]}>
        {rows.map((r) => (
          <tr key={r.name} className={sel.has(r.name) ? 'on' : undefined}>
            <td className="ck">
              <input type="checkbox" checked={sel.has(r.name)}
                     onChange={() => toggle(r.name)} aria-label={`选择 ${r.name}`} />
            </td>
            <td className="lib-name">
              <button className="link" onClick={() => onOpen(r.name)}>{r.name}</button>
            </td>
            {/* 返回试卷库不等于任务停了——这一列让「哪份还在跑」一眼可见 */}
            <td className="prg" data-label="进度">
              {r.progress ? <Prog p={r.progress} /> : null}
            </td>
            <td className="num" data-label="题数">{r.n}</td>
            <td className="num" data-label="插图">{r.figures}</td>
            <td className="num" data-label="动画">
              {r.scenes ? <span className="pill g">{r.scenes}</span>
                        : <span className="pill">0</span>}
            </td>
            <td className="num" data-label="告警">
              {r.warnings ? <span className="pill w">{r.warnings}</span>
                          : <span className="pill">0</span>}
            </td>
            <td className="lib-more">
              <RowMenu label={`「${r.name}」的更多操作`}>
                <button className="rowmenu-danger" disabled={busy}
                        onClick={() => confirmDelete([r.name])}>删除这份卷子</button>
              </RowMenu>
            </td>
          </tr>
        ))}
      </LibraryTable>
    </>
  )
}
