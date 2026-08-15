import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { getSheet } from '../api'
import JobProgress from './JobProgress'
import MetricCard, { Metrics } from './MetricCard'
import PaperAnswers from './PaperAnswers'
import SheetResultRow, {
  MARK, mainOf, SheetGroupHead, showN, WORD,
} from './SheetResultRow'
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

/**
 * 跳到某一题那一行。
 *
 * **不能用 `<a href="#q13">`。** 整个 App 是 hash 路由，`#q13` 谁都不命中，
 * `readHash` 的兜底是「解析试卷库」—— 点一下速览，当前这份答题卡直接没了。
 * 同一条纪律在 `PaperView.jumpTo` 里写过一遍。
 */
function jumpToRow(n: number) {
  const el = document.getElementById(`q${n}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  // 一闪，告诉眼睛落在哪一行了 —— 表格里几十行长得都一样
  el.classList.add('qrow-hit')
  window.setTimeout(() => el.classList.remove('qrow-hit'), 1400)
}

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
 * 按大题分组。
 *
 * **自己按题号排一遍，不赖后端的顺序。** 后端确实是 `ORDER BY n`，但这个函数
 * 是「相邻即同组」的写法 —— 顺序一旦不是升序，同一道大题会被切成好几组，
 * 而那种坏法在页面上看着像「数据本来就是散的」，很难往排序上想。
 *
 * `sub` 表示「这一组是小问」：只有这时才画大题那一行头。没有小问的题
 * （第 1 题这种）照旧是一行，不给它套一个只有一条的组。
 */
function group(rows: SheetRow[]): { main: number; sub: boolean; rows: SheetRow[] }[] {
  const out: { main: number; sub: boolean; rows: SheetRow[] }[] = []
  for (const r of [...rows].sort((a, b) => a.n - b.n)) {
    const m = mainOf(r.n)
    const last = out[out.length - 1]
    if (last && last.main === m && last.sub) last.rows.push(r)
    else out.push({ main: m, sub: r.n >= 100, rows: [r] })
  }
  return out
}

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

export default function SheetDetail({ id, paper, onBack, onOpenSheet }: {
  id: number
  /** 卷名。**打不开的时候也要说得出是哪份卷子** —— 那时候 `s` 是 null */
  paper: string
  onBack: () => void
  /** 切到同一份卷子下的另一份答题卡 */
  onOpenSheet: (id: number) => void
}) {
  const [s, setS] = useState<Sheet | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  const load = useCallback(() => {
    setErr(null)
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

  /**
   * 打不开。**返回入口必须在这一屏上。**
   *
   * 以前这里是一句光秃秃的横幅，`return` 在返回按钮之前 —— 而后端重启那几十秒
   * 里任何一次请求都会落到这儿。库里点进来 → 死页面 → 只能靠面包屑回库 →
   * 再点又是同一条死路，而卷子页（标准答案、重传入口）根本够不着。
   */
  if (err) {
    return (
      <div className="sheet">
        <div className="intro">
          <div className="intro-say">
            <h1>打不开这份答题卡</h1>
            <p>{paper}</p>
          </div>
          <div className="intro-aside">
            <button className="btn" onClick={onBack}>← 回到这份卷子</button>
          </div>
        </div>
        <div className="banner bad">
          <b>没读到</b>　{err}
          <div className="runcard-acts">
            <button className="btn" onClick={load}>再试一次</button>
          </div>
        </div>
      </div>
    )
  }
  if (!s) return <div className="empty"><b>载入中…</b></div>

  const reads = s.reads || {}
  /**
   * 逐题合计对不对得上卷面总分。
   *
   * **三态，不是两态。** 原来这里是 `reads.checksum || [true, '']` ——
   * 一份彻底跑坏、`reads` 是空的卡，会在首屏画出一个绿色的「逐题合计 · 对得上」。
   * 一个字都没读出来的卡，页面在说它分数都对得上。没跑到对账那一步就说没跑到。
   */
  const sumOk = reads.checksum ? reads.checksum[0] : null
  const sumWhy = reads.checksum ? reads.checksum[1] : ''
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
  if (sumOk === false && sumWhy) notes.push(sumWhy)
  for (const w of reads.bindWarnings || []) notes.push(w.why)
  for (const c of reads.clashes || []) notes.push(c.why)
  if (unbound.length) {
    notes.push(`${unbound.length} 条挂不上题（${unbound.map((r) => showN(r.n)).join('、')}）`
      + '—— 它们的题号在参考答案里对不上，所以没有标准答案可对。')
  }

  const shown = s.rows.filter(FILTERS.find((f) => f.key === filter)!.hit)
  /**
   * 一条作答都没读出来。
   *
   * 这**不是**「这一筛没有题」，也不是一份 0 分的卷子 —— 是这一趟根本没跑成
   * （Ⓢ 没能从截图里抠出答题卡，或者那一遍模型一道题都没认出来）。
   * 而这种卡建出来就删不掉，所以它照样会被人点开。
   */
  const blank = s.rows.length === 0 && !s.job
  const sibs = s.siblings ?? []

  return (
    <div className="sheet rise">
      <div className="intro">
        <div className="intro-say">
          <h1>{s.student || '未署名'}</h1>
          <p>{s.paper}　·　{s.nPages} 页答题卡</p>
        </div>
        {/* 「回到这份卷子」换成了就地弹框。老师在这一屏要的只是「对一下答案」，
            不值得换一整页 —— 换过去看完还得退回来，而他正在逐题核对，
            回来还得找回自己滚到哪了。
            卷子页没有作废：Ⓐ 的进度和「再传一个学生」的入口还在上面，
            从答题卡库那一行的「N 份」进得去 */}
        <div className="intro-aside">
          <PaperAnswers paper={s.paper} />
        </div>
      </div>

      {/* 同一份卷子下的其他答题卡。**只在真有第二份时出现。**
          库里点卷名现在直落到其中一份，「你在看谁、还有谁」得在这一屏上说清楚 ——
          真实数据里学生名常常是空的（三栏上传那条路不收学生名），
          所以每个标签后面跟着「读出几题」，不然三个「未署名」分不出哪个是哪个 */}
      {sibs.length > 1 && (
        <div className="sibs" role="group" aria-label="这份卷子的答题卡">
          {sibs.map((x) => (
            <button key={x.id} className={x.id === s.id ? 'on' : ''}
                    aria-pressed={x.id === s.id}
                    onClick={() => x.id !== s.id && onOpenSheet(x.id)}>
              {x.student || '未署名'}
              <i>{x.answers ? `读出 ${x.answers} 题` : '没读出题'}</i>
            </button>
          ))}
        </div>
      )}

      {blank && (
        <div className="banner bad">
          {/* 全角空格是排版，不是笔误：JSX 把元素和下一行文字之间的换行吃掉，
              不留空格（这一版里已经踩到第二次了） */}
          <b>这份答题卡一条作答都没读出来</b>{'　'}
          多半是没能从截图里抠出答题卡那一条，或者那一遍模型一道题都没认出来。
          <span className="blank-ok">
            <b>卷子和标准答案都还在</b>{'　'}
            换清楚一点的图重新传一份就行 —— 入口在「← 回到这份卷子」里面。
          </span>
        </div>
      )}

      {/* 还在跑。Ⓑa 一页三四分钟，不说的话这一屏和「卡死了」长得一样 */}
      {s.job && (
        <JobProgress tone="run" title={s.job.step || '正在读这份答题卡'}
                     bar={s.job.pageTotal
                       ? { cur: s.job.pageDone ?? 0, total: s.job.pageTotal } : null}
                     detail="逐页读出学生写了什么、老师给了几分。一页要三四分钟。" />
      )}

      {/* ── 先回答「哪里丢分」 ────────────────────────────────────────────
          一条作答都没读出来时**整块不画**：那时候 `lost`/`wrong`/`answers`
          全是 0，画出来就是一屏「0 分丢了 · 0 题错」，看着像一份满分卷 */}
      {!blank && (
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
        <MetricCard
          value={sumOk === null ? '没算过' : sumOk ? '对得上' : '对不上'}
          label="逐题合计"
          tone={sumOk === null ? 'plain' : sumOk ? 'ok' : 'bad'}
          hint={sumOk === null
            ? '这一趟没跑到对账那一步 —— 不是「对得上」，是不知道'
            : sumOk ? '逐题得分加起来等于卷面总分'
              : sumWhy || '逐题得分加起来和卷面总分不一致'} />
      </Metrics>
      )}

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
      {!blank && (<>
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

      {/* 逐题速览。半对用 ◐，不混进 ✓ 也不混进 ✗。
          **必须是 button + scrollIntoView，不能是 `<a href="#q13">`** ——
          整个 App 是 hash 路由，`#q13` 四条正则一条都不命中，兜底把人踢回
          解析试卷库。`PaperView` 和 `PaperSidebar` 的注释里写着这条纪律，
          这一侧一直没兑现：点一下速览，当前这份答题卡直接没了。 */}
      <div className="glance">
        {s.rows.map((r) => (
          <button key={r.n} type="button"
                  className={`gl gl-${r.verdict || 'unsure'}`}
                  onClick={() => jumpToRow(r.n)}
                  title={`${showN(r.n)}　${r.verdict ? WORD[r.verdict] : '说不清'}`}>
            <i>{showN(r.n)}</i>{r.verdict ? MARK[r.verdict] : '?'}
          </button>
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
              <th>题</th><th>题目</th><th>原图</th><th>学生答案</th><th>正确答案</th>
              <th>判定</th><th>知识点</th><th>为什么错 · 怎么提高</th>
            </tr>
          </thead>
          <tbody>
            {/* **一道大题一组，小问挂在下面。**
                小问共用同一段题干和同一张原卷截图（Ⓔ 按主题号回填），
                逐条平铺的话第 13 题的五个小问会把同一张图贴五遍，
                而「这几行是同一道大题」反而看不出来。
                分组按筛选之后的结果算 —— 筛成「只看错的」时，剩下哪几问就归哪几问 */}
            {group(shown).map((g) => (
              <Fragment key={g.main}>
                {g.sub && <SheetGroupHead main={g.main} rows={g.rows} />}
                {g.rows.map((r) => (
                  <SheetResultRow key={r.n} r={r} sheet={s.id} onChanged={load}
                                  sub={g.sub} />
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
      </>)}

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
