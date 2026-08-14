/**
 * 一个状态的统一说法：成功 / 在跑 / 停了 / 要留意 / 失败。
 *
 * **文本是必填的，不是可选装饰。** 颜色不能单独承担语义 —— 红绿色觉差异下
 * 「已完成」和「失败」是同一个灰点；而这个页面上「跑完了」和「跑挂了」
 * 差着一整份卷子。所以每种状态都配一个符号 + 一句话，颜色只是第三层。
 */
export type StatusTone = 'ok' | 'run' | 'idle' | 'warn' | 'bad'

const MARK: Record<StatusTone, string> = {
  ok: '✓', run: '', idle: '—', warn: '!', bad: '✕',
}

export default function StatusBadge({ tone, text, title }: {
  tone: StatusTone
  /** 说人话的状态词。**不许留空** */
  text: string
  /** 补充说明（停在哪一步、失败原因）。鼠标够不着的地方靠它，但正文不能只靠它 */
  title?: string
}) {
  return (
    <span className={`sb sb-${tone}`} title={title}>
      {/* 在跑的那个是会动的点，比一个静止的符号更容易被扫到 */}
      {tone === 'run' ? <i className="sb-dot" /> : <i className="sb-mk">{MARK[tone]}</i>}
      {text}
    </span>
  )
}
