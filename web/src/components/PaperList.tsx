import { useState } from 'react'
import type { PaperSummary } from '../types'

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

  if (!rows.length) return <div className="empty">还没有处理过任何试卷</div>

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
          <button onClick={() => setSel(new Set())}>取消选择</button>
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th className="ck">
              <input type="checkbox" checked={allOn} onChange={toggleAll}
                     aria-label="全选" />
            </th>
            <th>试卷</th><th>进度</th><th>题数</th><th>插图</th><th>动画</th><th>告警</th><th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className={sel.has(r.name) ? 'on' : undefined}>
              <td className="ck">
                <input type="checkbox" checked={sel.has(r.name)}
                       onChange={() => toggle(r.name)} aria-label={`选择 ${r.name}`} />
              </td>
              <td><button className="link" onClick={() => onOpen(r.name)}>{r.name}</button></td>
              {/* 返回试卷库不等于任务停了——这一列让「哪份还在跑」一眼可见 */}
              <td className="prg">
                {r.progress ? (
                  r.progress.busy ? (
                    <span className="run"><i />{r.progress.stage}
                      {r.progress.total > 1 && ` ${r.progress.cur}/${r.progress.total}`}</span>
                  ) : r.progress.stage === '完成' ? (
                    <span className="pill g">完成</span>
                  ) : (
                    <span className="pill" title="没有进程在跑，停在这一步">
                      {r.progress.stage} {r.progress.cur}/{r.progress.total}
                    </span>
                  )
                ) : null}
              </td>
              <td className="num">{r.n}</td>
              <td className="num">{r.figures}</td>
              <td>{r.scenes ? <span className="pill g">{r.scenes}</span>
                            : <span className="pill">0</span>}</td>
              <td>{r.warnings ? <span className="pill w">{r.warnings}</span>
                              : <span className="pill">0</span>}</td>
              <td>
                <button className="del" disabled={busy} title={`删除 ${r.name}`}
                        onClick={() => confirmDelete([r.name])}>删除</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
