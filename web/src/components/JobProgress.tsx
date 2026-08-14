import type { ReactNode } from 'react'

export type JobTone = 'run' | 'ok' | 'bad'

/**
 * 一个上传任务在页面上的**固定位置**。
 *
 * 以前两个上传组件各自把 running / solving / finishing / done / error 摊成四五条
 * 横幅，一条接一条往下长 —— 状态一变，人要重新找「现在在哪」。现在同一个位置
 * 换内容：状态点、一句状态词、计数、下一步、原始日志。
 *
 * **话术留在调用方。** 这个组件不知道 Ⓐ 和 ③ 的区别，也不该知道 ——
 * 「切出 12 题，已经可以看了」和「读出 26 题的标准答案」是两条链各自的话，
 * 混进一个组件里迟早会有一句串到另一边去（判卷的话出现在高考真题上，
 * 这个仓库里已经发生过一次）。
 *
 * **日志默认折叠，失败时默认展开。** 正常跑的时候没人要读 `[③] deepseek…`；
 * 而一旦挂了，它是唯一能说清挂在哪的东西 —— 那时候把它藏起来才是真的坏。
 */
export default function JobProgress({
  tone, title, detail, counts, bar, log, actions,
}: {
  tone: JobTone
  /** 一句状态词。**在跑的时候说「在做什么」，停下来说「停在哪」** */
  title: ReactNode
  /** 这一步在做什么、接下来会发生什么。可理解的下一步比进度条要紧 */
  detail?: ReactNode
  /** 已处理页数、已识别题数这类计数。**没有就不给** —— 不许拿 0/0 占位 */
  counts?: { label: string; value: ReactNode }[]
  /** 有分母才画条。**宁可不画，也不画一个假的** */
  bar?: { cur: number; total: number } | null
  log?: string[]
  actions?: ReactNode
}) {
  const pct = bar && bar.total > 0
    ? Math.max(0, Math.min(100, Math.round((bar.cur / bar.total) * 100)))
    : null
  return (
    <section className={`runcard runcard-${tone}`} aria-live="polite">
      <div className="runcard-hd">
        {tone === 'run' && <span className="runcard-dot" />}
        <b>{title}</b>
        {bar && <span className="runcard-num">{bar.cur}/{bar.total}</span>}
      </div>

      {pct !== null && (
        <div className="runcard-bar"><i style={{ width: `${pct}%` }} /></div>
      )}

      {detail && <p className="runcard-say">{detail}</p>}

      {counts && counts.length > 0 && (
        <dl className="runcard-counts">
          {counts.map((c) => (
            <div key={c.label}>
              <dt>{c.label}</dt><dd>{c.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {actions && <div className="runcard-acts">{actions}</div>}

      {log && log.length > 0 && (
        <details className="runcard-log" open={tone === 'bad'}>
          <summary>原始日志（{log.length} 行）</summary>
          <pre>{log.join('\n')}</pre>
        </details>
      )}
    </section>
  )
}
