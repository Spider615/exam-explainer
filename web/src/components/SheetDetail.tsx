import { useCallback, useEffect, useState } from 'react'
import { getSheet } from '../api'
import RichText from './RichText'
import type { Sheet, SheetRow, Verdict, VerdictBy } from '../types'

/**
 * 一份**已批改答题卡**的详情页。
 *
 * 版面以「逐题对错 + 原图对照」为主，六条硬约束（设计文档「页面」那节）：
 *
 *   · 原图切片必须**挨着判定**，不能藏进二级页面 —— 老师一眼能校对是唯一的红绿灯
 *   · `verdictBy` 要显示（照分数判 / 照勾叉判 / 老师改判）
 *   · 互校不一致的题必须显式标出来
 *   · 分数要跟判定一起显示（`1 分（满分 2 分）`）
 *   · Σ得分对不上总分时页面要说
 *   · **「半对」用 ◐**，不混进 ✓ 也不混进 ✗
 */

const MARK: Record<Verdict, string> = {
  right: '✓', partial: '◐', wrong: '✗', blank: '—', unsure: '?',
}
const WORD: Record<Verdict, string> = {
  right: '对', partial: '半对', wrong: '错', blank: '空着', unsure: '说不清',
}
const BY: Record<VerdictBy, string> = {
  teacher_score: '照卷子上印的分数',
  teacher_mark: '照红勾红叉',
  code: '系统按标准答案判的',
  model: '模型判的',
  teacher: '你改判的',
}

export default function SheetDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const [s, setS] = useState<Sheet | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => {
    getSheet(id).then(setS).catch((e) => setErr(String(e)))
  }, [id])
  useEffect(() => { setS(null); setErr(null); load() }, [id, load])

  // 跑着的时候接着轮询。Ⓑa 一页要三四分钟，没有这个的话页面是死的
  useEffect(() => {
    if (!s?.job) return
    const t = window.setTimeout(load, 4000)
    return () => window.clearTimeout(t)
  }, [s?.job, load])

  if (err) return <div className="banner bad"><b>打不开</b>　{err}</div>
  if (!s) return <div className="empty">载入中…</div>

  const reads = s.reads || {}
  const [sumOk, sumWhy] = reads.checksum || [true, '']
  const badCalls = (reads.calls || []).filter((c) => !c.ok)
  const unbound = s.rows.filter((r) => !r.bound)

  return (
    <div className="sheet">
      <header className="sheet-hd">
        <button onClick={onBack}>← 回到这份卷子</button>
        <h2>{s.student || '未署名'}　<small>{s.paper}</small></h2>
        <div className="facts">
          {s.total != null && (
            <div className="fact"><b>{s.total}</b><span>总分（卷子上印的）</span></div>
          )}
          <div className="fact"><b>{s.answers}</b><span>题读出来了</span></div>
          {/* 「错」和「半对」分两个数 —— 合在一起的话，8 道半对的卡会显示「错 2 道」 */}
          <div className="fact"><b>{s.wrong}</b><span>题错</span></div>
          <div className="fact"><b>{s.partial}</b><span>题半对</span></div>
          {s.lost != null && (
            <div className="fact" title="薄弱知识点按丢分排，所以这里显示的也是它">
              <b>{s.lost}</b><span>分丢了</span>
            </div>
          )}
        </div>
      </header>

      {/* 还在跑。Ⓑa 一页三四分钟，不说的话这一屏和「卡死了」长得一样 */}
      {s.job && (
        <div className="prog">
          <div className="prog-hd">
            <span className="prog-dot" />
            <b>{s.job.step || '处理中'}</b>
            {s.job.pageTotal ? (
              <span className="prog-num">{s.job.pageDone ?? 0}/{s.job.pageTotal} 页</span>
            ) : null}
          </div>
        </div>
      )}

      {/* ── 这一次跑成什么样。**每一条都要说出口** ───────────────────── */}

      {reads.aborted && (
        <div className="banner bad">
          <b>中途停了</b>　{reads.aborted}
        </div>
      )}

      {badCalls.length > 0 && (
        <div className="banner bad">
          <b>有 {badCalls.length} 次读取没成</b>
          {badCalls.map((c) => `第 ${c.page} 页 ${c.pass}`).join('、')}。
          <b>这些题下面显示的「没读出来」不是「学生没写」</b> ——
          是那一遍根本没读到。换清楚一点的图重传一次。
        </div>
      )}

      {!sumOk && sumWhy && (
        <div className="banner bad">
          <b>逐题得分加起来对不上总分</b>　{sumWhy}
          <br />
          <small>
            这条查得出「漏了一题、多读了一条、某个数字读错了」；
            <b>查不出两道题的得分对调</b>（那样总和不变）。请对照原图。
          </small>
        </div>
      )}

      {(reads.bindWarnings || []).map((w) => (
        <div className="banner" key={w.main}>
          <b>第 {w.main} 题挂不上</b>　{w.why}
        </div>
      ))}

      {(reads.clashes || []).length > 0 && (
        <div className="banner">
          <b>两遍读出来不一样的地方（{reads.clashes!.length} 处）</b>
          <ul>{reads.clashes!.map((c, i) => <li key={i}>{c.why}</li>)}</ul>
        </div>
      )}

      {/* ── 逐题速览。半对用 ◐，不混进 ✓ 也不混进 ✗ ─────────────────── */}
      <div className="glance">
        {s.rows.map((r) => (
          <a key={r.n} href={`#q${r.n}`}
             className={`gl gl-${r.verdict || 'unsure'}`}
             title={`${showN(r.n)}　${r.verdict ? WORD[r.verdict] : '说不清'}`}>
            <i>{showN(r.n)}</i>{r.verdict ? MARK[r.verdict] : '?'}
          </a>
        ))}
      </div>

      {unbound.length > 0 && (
        <div className="banner">
          <b>{unbound.length} 条挂不上题</b>
          它们的题号在参考答案里对不上（{unbound.map((r) => showN(r.n)).join('、')}）。
          下面照样列出来，但没有标准答案可对 —— 请你认一下哪条对哪条。
        </div>
      )}

      {s.rows.map((r) => <Row key={r.n} r={r} />)}

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
        知识点标签由 AI 生成，未经人工审核。
      </footer>
    </div>
  )
}

/** 1203 → `12(3)`；9 → `9` */
function showN(n: number) {
  return n >= 100 ? `${Math.floor(n / 100)}(${n % 100})` : String(n)
}

function Row({ r }: { r: SheetRow }) {
  const v = r.verdict || 'unsure'
  return (
    <section className={`srow srow-${v}`} id={`q${r.n}`} tabIndex={-1}>
      <h3>
        第 {showN(r.n)} 题
        <em className={`v v-${v}`}>{MARK[v]} {WORD[v]}</em>
        {/* 分数要跟判定一起显示 —— 只说「半对」而不给分，老师没法核对 */}
        {r.scoreGot != null && r.scoreFull != null && (
          <em className="score">{r.scoreGot} 分（满分 {r.scoreFull} 分）</em>
        )}
        {r.teacherVerdict && <em className="by">你改判过</em>}
      </h3>

      {/* 原图切片**挨着判定**，不藏进二级页面 */}
      <div className="srow-body">
        {r.crop ? (
          <a href={r.crop} target="_blank" rel="noreferrer" title="点开看大图">
            <img className="cropshot" src={r.crop} alt={`第 ${showN(r.n)} 题的原图`} />
          </a>
        ) : (
          <p className="dim">这道题没有原图切片</p>
        )}

        <dl>
          <dt>你写的</dt>
          <dd className="ans">
            {r.answer && r.answer !== 'unreadable' && r.answer !== 'blank'
              ? <RichText text={r.answer} />
              : r.answer === 'blank'
                ? <span className="dim">这道题空着</span>
                /* 「没读出来」和「没作答」是两句不同的话。写成后者的话，
                   老师读到「这孩子没写」，而事实是我们没读出来 */
                : <span className="dim">没读出来 —— 不是学生没写，是这一栏没转写成功</span>}
          </dd>

          <dt>标准答案</dt>
          <dd className="ans">
            {r.refAnswer
              ? <RichText text={r.refAnswer} />
              : <span className="dim">
                  {r.bound ? '参考答案里这道题没有答案' : '这条挂不上题，没有标准答案可对'}
                </span>}
          </dd>

          {/* 老师在旁边红笔写的正确答案。第三份对照，白捡的 */}
          {r.red && (
            <>
              <dt>老师写的</dt>
              <dd className="ans"><RichText text={r.red} /></dd>
            </>
          )}

          <dt>怎么判的</dt>
          <dd>
            <span className="dim">
              {r.verdictBy ? BY[r.verdictBy] : '说不清'}
              {r.verdictWhy ? `：${r.verdictWhy}` : ''}
            </span>
          </dd>

          {r.kps.length > 0 && (
            <>
              <dt>知识点</dt>
              <dd>
                {r.kps.map((k) => (
                  <span key={k.code} className="kp" title={k.why}>
                    {k.name}<i>{k.chapter}</i>
                  </span>
                ))}
              </dd>
            </>
          )}
        </dl>
      </div>

      {r.refSolution && (
        <details className="srow-sol">
          <summary>官方解答</summary>
          <RichText text={r.refSolution.replace(/\$\$/g, '$')} />
        </details>
      )}
    </section>
  )
}
