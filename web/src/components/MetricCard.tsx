import type { ReactNode } from 'react'

/**
 * 摘要里的一个数。试卷详情和答题卡诊断共用。
 *
 * **数在上、名在下，名字不许省。** 一排孤零零的数字（`16  9  6  2`）看着很
 * 干净，但没人记得第三个是什么 —— 而这一排的全部作用就是让人不用往下翻。
 */
export default function MetricCard({ value, label, hint, tone = 'plain' }: {
  value: ReactNode
  label: ReactNode
  /** 这个数是怎么来的。估算值、口径特殊的，**必须在这里说清楚** */
  hint?: string
  /** hot 是这一屏最该被看到的那个数（丢分、失败），其余一律 plain */
  tone?: 'plain' | 'hot' | 'ok' | 'bad'
}) {
  return (
    <div className={`metric metric-${tone}`} title={hint}>
      <b>{value}</b>
      <span>{label}{hint && <i className="metric-q">?</i>}</span>
    </div>
  )
}

/** 一排摘要数。空的时候不渲染，别留一条空条 */
export function Metrics({ children }: { children: ReactNode }) {
  return <div className="metrics">{children}</div>
}
