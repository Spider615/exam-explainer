/**
 * 试卷详情的题号目录。
 *
 * **桌面固定在左边，窄屏收成一条横向跳转带。** 手机上留一栏 200px 的侧栏，
 * 正文就只剩一百多像素 —— 题干读起来会变成一列一个字。
 *
 * 每一项右边那格只放**真答案和终态失败**，中间态一律留白：目录这一列窄，
 * 塞一句「已解出 · 待压缩」进去，扫目录的人会以为那是答案。
 */
export default function PaperSidebar({ name, count, groups, onJump }: {
  name: string
  count: number
  /** [分组名, 该组的题] —— 分组由调用方按 section 或题型算好 */
  groups: [string, { n: number; label?: string | null; answer: string }[]][]
  /**
   * 跳到某一题。**必须是回调，不能是 `<a href="#q3">`** —— 整个 App 是
   * hash 路由（`#/paper/<卷名>`），改 hash 会被路由当成「回到试卷库」，
   * 点一下目录直接把当前卷子关掉。
   */
  onJump: (n: number) => void
}) {
  return (
    <nav className="toc" aria-label="题目目录">
      <div className="toc-hd">
        <b title={name}>{name}</b>
        <span>{count} 题</span>
      </div>
      {groups.map(([sec, qs]) => (
        <div key={sec} className="toc-g">
          <h4>{sec.includes('、') ? sec.split('、').pop() : sec}</h4>
          {qs.map((q) => (
            <button key={q.n} className="toc-i" onClick={() => onJump(q.n)}>
              <span className="toc-n">{String(q.n).padStart(2, '0')}</span>
              <span className="toc-l">{q.label || ''}</span>
              <span className="toc-a">{q.answer}</span>
            </button>
          ))}
        </div>
      ))}
    </nav>
  )
}
