import { useCallback, useEffect, useMemo, useState } from 'react'
import { getSheet } from '../api'
import JobProgress from './JobProgress'
import MetricCard, { Metrics } from './MetricCard'
import SheetResultRow, { MARK, showN, WORD } from './SheetResultRow'
import type { Sheet, SheetRow } from '../types'

/**
 * 一份**已批改答题卡**的诊断结果页。
 *
 * 顺序是「**先给结论，再给证据**」：
 *
 *   1. 丢了多少分、错几道、哪个知识点最该补
 *   2. 这一趟有没有读不准的地方（收成一行）
 *   3. 逐题证据，可筛选
 *
 * 六条硬约束（设计文档「页面」那节）一条没松：
 *
 *   · 原图切片必须**挨着判定**，不能藏进二级页面 —— 老师一眼能校对是唯一的红绿灯
 *   · `verdictBy` 要显示（照分数判 / 照勾叉判 / 老师改判）
 *   · 互校不一致的题必须显式标出来
 *   · 分数要跟判定一起显示（`1 分（满分 2 分）`）
 *   · Σ得分对不上总分时页面要说
 *   · **「半对」用 ◐**，不混进 ✓ 也不混进 ✗
 */

type Filter = 'all' | 'wrong' | 'partial' | 'unread' | 'unbound'

const FILTERS: { key: Filter; label: string; hit: (r: SheetRow) => boolean }[] = [
  { key: 'all', label: '全部', hit: () => true },
  { key: 'wrong', label: '错', hit: (r) => r.verdict === 'wrong' },
  { key: 'partial', label: '半对', hit: (r) => r.verdict === 'partial' },
  // 「没读清」不是「学生没作答」。它们在这里也必须是两个筛子：
  // 前者要老师去核原图，后者是真实的失分
  { key: 'unread', label: '没读清',
    hit: (r) => r.verdict === 'unsure' || (!r.answer || r.answer === 'unreadable') },
  { key: 'unbound', label: '挂不上题', hit: (r) => !r.bound },
]

/**
 * 优先提升的知识点：按**丢分**排，不按错题数。
 *
 * 三道 2 分的选择题错了和一道 12 分的大题丢了 9 分，后者才是该先补的 ——
 * 按题数排会把前者顶到第一位。只统计**分数确实知道**的题：没读到得分的题
 * 参与排序等于拿一个猜的数去决定老师先讲什么。
 */
function weakSpots(rows: SheetRow[]) {
  const lost = new Map<string, { name: string; lost: number; n: number }>()
  for (const r of rows) {
    if (r.scoreGot == null || r.scoreFull == null) continue
    const gap = r.scoreFull - r.scoreGot
    if (gap <= 0) continue
    for (const k of r.kps) {
      const cur = lost.get(k.code) ?? { name: k.name, lost: 0, n: 0 }
      cur.lost += gap
      cur.n += 1
      lost.set(k.code, cur)
    }
  }
  return [...lost.values()].sort((a, b) => b.lost - a.lost).slice(0, 3)
}

export default function SheetDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const [s, setS] = useState<Sheet | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  const load = useCallback(() => {
    getSheet(id).then(setS).catch((e) => setErr(String(e)))
  }, [id])
  useEffect(() => { setS(null); setErr(null); setFilter('all'); load() }, [id, load])

  // 跑着的时候接着轮询。Ⓑa 一页要三四分钟，没有这个的话页面是死的
  useEffect(() => {
    if (!s?.job) return
    const t = window.setTimeout(load, 4000)
    return () => window.clearTimeout(t)
  }, [s?.job, load])

  const weak = useMemo(() => (s ? weakSpots(s.rows) : []), [s])

  if (err) return <div className="banner bad"><b>打不开</b>　{err}</div>
  if (!s) return <div className="empty"><b>载入中…</b></div>

  const reads = s.reads || {}
  const [sumOk, sumWhy] = reads.checksum || [true, '']
  const badCalls = (reads.calls || []).filter((c) => !c.ok)
  // 重跑过几次。**要说出来** —— 悄悄重跑然后当没事发生，等于把「这份材料
  // 模型读不稳」藏起来，而那正是老师最该知道的：换一张更清楚的图比重试可靠
  const retried = (reads.calls || []).filter((c) => (c.attempt ?? 1) > 1)
  const unbound = s.rows.filter((r) => !r.bound)

  /**
   * 满分。**只有每道题的满分都读到了，才敢把它当分母。**
   *
   * 缺一道就不给：那时候这个和是个**下界**，而写成「58.5 / 18」的话，分母比
   * 分子还小 —— 老师第一眼看到的是一个坏掉的比值，读完 title 才知道是怎么回事。
   * 一个需要解释才不误导的数字，不如不显示。
   */
  const noFull = s.rows.filter((r) => r.scoreFull == null).length
  const fullSum = s.rows.reduce((a, r) => a + (r.scoreFull ?? 0), 0)
  const full = noFull === 0 && fullSum > 0 ? fullSum : null

  // 把这一趟的异常汇成一串话。**不删，只收起来** —— 里面有真信息：
  // 哪道大题的题号对不上（那几行因此没有标准答案可对）、哪几条根本没读到、
  // 得分加起来差多少。藏掉的话页面上那几行会莫名其妙
  const notes: string[] = []
  if (reads.aborted) notes.push(`中途停了：${reads.aborted}`)
  if (badCalls.length) {
    notes.push(`有 ${badCalls.length} 次读取没成（${badCalls
      .map((c) => `第 ${c.page} 页 ${c.pass}`).join('、')}）——`
      + '这些题的「没读出来」不是「学生没写」，是那一遍根本没读到。')
  }
  if (retried.length) {
    notes.push(`有 ${retried.length} 次读取重跑过 —— 同一张图两次读得不一样，`
      + '说明这几页对模型偏难，换一张更清楚的重传比多重试可靠。')
  }
  if (!sumOk && sumWhy) notes.push(sumWhy)
  for (const w of reads.bindWarnings || []) notes.push(w.why)
  for (const c of reads.clashes || []) notes.push(c.why)
  if (unbound.length) {
    notes.push(`${unbound.length} 条挂不上题（${unbound.map((r) => showN(r.n)).join('、')}）`
      + '—— 它们的题号在参考答案里对不上，所以没有标准答案可对。')
  }

  const shown = s.rows.filter(FILTERS.find((f) => f.key === filter)!.hit)

  return (
    <div className="sheet rise">
      <div className="intro">
        <div className="intro-say">
          <h1>{s.student || '未署名'}</h1>
          <p>{s.paper}　·　{s.nPages} 页答题卡</p>
        </div>
        <div className="intro-aside">
          <button className="btn" onClick={onBack}>← 回到这份卷子</button>
        </div>
      </div>

      {/* 还在跑。Ⓑa 一页三四分钟，不说的话这一屏和「卡死了」长得一样 */}
      {s.job && (
        <JobProgress tone="run" title={s.job.step || '正在读这份答题卡'}
                     bar={s.job.pageTotal
                       ? { cur: s.job.pageDone ?? 0, total: s.job.pageTotal } : null}
                     detail="逐页读出学生写了什么、老师给了几分。一页要三四分钟。" />
      )}

      {/* ── 先回答「哪里丢分」 ──────────────────────────────────────────── */}
      <Metrics>
        {s.total != null && (
          <MetricCard
            value={full ? <>{s.total}<i className="metric-of">/{full}</i></> : s.total}
            label="总分" tone="hot"
            hint={full ? '卷子上印的总分 / 逐题满分之和'
              : `卷子上印的总分。满分算不出来 —— 有 ${noFull} 道题没读到满分`} />
        )}
        {s.lost != null && (
          <MetricCard value={s.lost} label="分丢了" tone="bad"
                      hint="下面的「优先补」按这个排，不按错题数" />
        )}
        {/* 「错」和「半对」分两个数 —— 合在一起的话，8 道半对的卡会显示「错 2 道」 */}
        <MetricCard value={s.wrong} label="题错" tone={s.wrong ? 'bad' : 'plain'} />
        <MetricCard value={s.partial} label="题半对" />
        <MetricCard value={s.answers} label="题读出来了"
                    hint="这份卡上认出了作答的题数，不等于学生答了几题" />
        <MetricCard value={sumOk ? '对得上' : '对不上'} label="逐题合计"
                    tone={sumOk ? 'ok' : 'bad'}
                    hint={sumOk ? '逐题得分加起来等于卷面总分'
                      : sumWhy || '逐题得分加起来和卷面总分不一致'} />
      </Metrics>

      {/* 优先补哪个知识点。**按丢分排** —— 三道 2 分的选择题错了，
          抵不上一道大题丢的 9 分 */}
      {weak.length > 0 && (
        <div className="weak">
          <h2 className="lbl">优先补</h2>
          <ul>
            {weak.map((w) => (
              <li key={w.name}>
                <b>{w.name}</b>
                <span>丢 {w.lost} 分 · {w.n} 题</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 这一次跑成什么样：**收成一行，点开才展开**。
          **收起来不等于不说** —— 这几条里有真信息（13 题挂不上题所以没有标准
          答案可对、16(3) 根本没读到），藏掉的话页面上那几行会莫名其妙 */}
      {notes.length > 0 && (
        <details className="notes">
          <summary>
            {notes.length} 处需要你留意
            <span className="dim">（题号对不上、有题没读到、加起来对不上总分）</span>
          </summary>
          {notes.map((t, i) => <p key={i}>{t}</p>)}
        </details>
      )}

      {/* ── 再给逐题证据 ────────────────────────────────────────────────── */}
      <div className="qfilter" role="group" aria-label="筛选逐题结果">
        {FILTERS.map((f) => {
          const n = s.rows.filter(f.hit).length
          return (
            <button key={f.key} className={filter === f.key ? 'on' : ''}
                    aria-pressed={filter === f.key}
                    disabled={n === 0 && f.key !== 'all'}
                    onClick={() => setFilter(f.key)}>
              {f.label}<i>{n}</i>
            </button>
          )
        })}
      </div>

      {/* 逐题速览。半对用 ◐，不混进 ✓ 也不混进 ✗ */}
      <div className="glance">
        {s.rows.map((r) => (
          <a key={r.n} href={`#q${r.n}`}
             className={`gl gl-${r.verdict || 'unsure'}`}
             title={`${showN(r.n)}　${r.verdict ? WORD[r.verdict] : '说不清'}`}>
            <i>{showN(r.n)}</i>{r.verdict ? MARK[r.verdict] : '?'}
          </a>
        ))}
      </div>

      {shown.length === 0 ? (
        <div className="empty">
          <b>这一筛没有题</b>
          <span>换一个筛子，或者点「全部」。</span>
        </div>
      ) : (
        <table className="qtbl">
          <thead>
            <tr>
              <th>题</th><th>原图</th><th>学生答案</th><th>正确答案</th>
              <th>判定</th><th>知识点</th><th>为什么错 · 怎么提高</th><th />
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <SheetResultRow key={r.n} r={r} sheet={s.id} onChanged={load} />
            ))}
          </tbody>
        </table>
      )}

      {s.pages.length > 0 && (
        <details className="sheet-pages">
          <summary>答题卡原图（{s.pages.length} 页）</summary>
          {s.pages.map((p) => (
            <a key={p} href={p} target="_blank" rel="noreferrer">
              <img src={p} alt="答题卡原图" />
            </a>
          ))}
        </details>
      )}

      <footer className="ai-note">
        对错与分数<b>来自老师在答题卡上的批改</b>，由视觉模型逐页转写，
        可能有转写错误 —— 逐题原图就在上面，请对照核对。
        知识点标签与「怎么提高」由 AI 生成，未经人工审核。
      </footer>
    </div>
  )
}
