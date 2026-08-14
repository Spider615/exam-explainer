import { useCallback, useEffect, useState } from 'react'
import { getSheet, regrade } from '../api'
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
  // 重跑过几次。**要说出来** —— 悄悄重跑然后当没事发生，等于把「这份材料
  // 模型读不稳」藏起来，而那正是老师最该知道的：换一张更清楚的图比重试可靠
  const retried = (reads.calls || []).filter((c) => (c.attempt ?? 1) > 1)
  const unbound = s.rows.filter((r) => !r.bound)

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

      {/* 这一次跑成什么样：**收成一行，点开才展开**。
          原来是六条横幅铺在最上面，逐题结果被挤到屏幕外 —— 而老师第一眼要的
          是「哪几道错了」，不是我的内部诊断。用户原话：「这些都去掉吧」。

          **收起来不等于不说。** 这几条里有真信息（13 题挂不上题所以没有标准
          答案可对、16(3) 根本没读到），藏掉的话页面上那几行会莫名其妙。
          所以留一行摘要，点开看全 —— 而不是删掉。 */}
      {notes.length > 0 && (
        <details className="notes">
          <summary>
            {notes.length} 处需要你留意
            <span className="dim">（题号对不上、有题没读到、加起来对不上总分）</span>
          </summary>
          {notes.map((t, i) => <p key={i}>{t}</p>)}
        </details>
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

      {/* **一道题一行**：学生答案 · 正确答案 · 对错 · 知识点。
          原来是一题一张大卡（原图占半屏、官方解答、改判按钮全铺开），
          26 道题要翻很久才看得完一遍 —— 而老师第一眼要的就是「哪几道错了、
          错在哪个知识点」。原图切片收成行内缩略图，点开看大的；
          官方解答和改判收进那一行展开后才出现。
          用户原话：「一道题目对应学生答案、正确答案、是否正确、本题知识点即可」 */}
      <table className="qtbl">
        <thead>
          <tr>
            <th>题</th><th>原图</th><th>学生答案</th><th>正确答案</th>
            <th>对错</th><th>知识点</th><th>为什么错 · 怎么提高</th><th />
          </tr>
        </thead>
        <tbody>
          {s.rows.map((r) => <Row key={r.n} r={r} sheet={s.id} onChanged={load} />)}
        </tbody>
      </table>

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

function Row({ r, sheet, onChanged }: {
  r: SheetRow
  sheet: number
  onChanged: () => void
}) {
  const v = r.verdict || 'unsure'
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  const change = async (next: Verdict | null) => {
    // 半对是几分推不出来，得问一句。对/错后端按满分和 0 推，不用打扰老师
    let score: number | undefined
    if (next === 'partial') {
      const got = window.prompt(
        `第 ${showN(r.n)} 题改判为「半对」——得几分？（满分 ${r.scoreFull ?? '?'} 分）`)
      if (got == null) return
      const num = Number(got)
      if (!Number.isFinite(num)) { setErr('分数要填一个数'); return }
      score = num
    }
    setBusy(true); setErr(null)
    try {
      await regrade(sheet, r.n, next, score)
      onChanged()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <tr className={`qrow qrow-${v}`} id={`q${r.n}`}>
        <td className="qn">{showN(r.n)}</td>

        {/* 原图切片：**行内缩略图，点开看大的**。设计里它是「老师一眼能校对的
            唯一红绿灯」，所以不能收进二级页面；但也不该占半屏 */}
        <td>
          {r.crop
            ? <a href={r.crop} target="_blank" rel="noreferrer" title="点开看大图">
                <img className="qthumb" src={r.crop} alt={`第 ${showN(r.n)} 题原图`} />
              </a>
            : <span className="dim">—</span>}
        </td>

        <td className="ans">
          {r.answer && r.answer !== 'unreadable' && r.answer !== 'blank'
            ? <RichText text={r.answer} />
            : r.answer === 'blank'
              ? <span className="dim">空着</span>
              /* 「没读出来」和「学生没写」是两句不同的话 —— 写成后者的话，
                 老师读到「这孩子没写」，而事实是我们没转写出来 */
              : <span className="dim" title="不是学生没写，是这一栏没转写成功">
                  没读出来
                </span>}
        </td>

        <td className="ans">
          {r.refAnswer
            ? <RichText text={r.refAnswer} />
            : <span className="dim" title={r.bound ? '' : '这条挂不上题，没有标准答案可对'}>
                {r.bound ? '—' : '挂不上题'}
              </span>}
        </td>

        <td>
          <span className={`v v-${v}`}>{MARK[v]} {WORD[v]}</span>
          {/* 分数跟判定一起给 —— 只说「半对」而不给分，老师没法核对 */}
          {r.scoreGot != null && r.scoreFull != null && (
            <em className="score">{r.scoreGot}/{r.scoreFull}</em>
          )}
          {r.teacherVerdict && <em className="by">已改判</em>}
        </td>

        <td>
          {r.kps.length
            ? r.kps.map((k) => (
                <span key={k.code} className="kp" title={k.why}>{k.name}</span>
              ))
            : <span className="dim">—</span>}
        </td>

        {/* 老师看完「哪几道错了」之后的下一个问题是「那我该怎么办」。
            **只有没拿满分的题才有** —— 对的题不需要建议。
            **说不出具体的就留白**，不拿一句正确的废话补位 */}
        <td className="adv">
          {r.advice?.why && <p className="adv-why">{r.advice.why}</p>}
          {r.advice?.fix && <p className="adv-fix">{r.advice.fix}</p>}
          {!r.advice?.why && !r.advice?.fix && (
            <span className="dim">
              {v === 'right' ? '—' : '看不出具体原因'}
            </span>
          )}
        </td>

        <td>
          <button className="qmore" onClick={() => setOpen(!open)}>
            {open ? '收起' : '详情'}
          </button>
        </td>
      </tr>

      {/* 展开才出现：怎么判的、官方解答、改判。第一眼不需要，但要够得着 */}
      {open && (
        <tr className="qrow-more">
          <td colSpan={8}>
            <p className="dim">
              {r.verdictBy ? BY[r.verdictBy] : '说不清'}
              {r.verdictWhy ? `：${r.verdictWhy}` : ''}
              {r.teacherVerdict && r.sysVerdict &&
                `　（系统原判是「${WORD[r.sysVerdict]}${
                  r.sysScoreGot != null ? ` · ${r.sysScoreGot} 分` : ''}」）`}
            </p>
            {r.red && <p>老师在旁边写的正确答案：<RichText text={r.red} /></p>}
            {r.refSolution && (
              <details>
                <summary>官方解答</summary>
                <RichText text={r.refSolution.replace(/\$\$/g, '$')} />
              </details>
            )}
            <div className="srow-fix">
              <span className="dim">改判为</span>
              {(['right', 'partial', 'wrong', 'blank'] as Verdict[]).map((k) => (
                <button key={k} disabled={busy || v === k} onClick={() => change(k)}>
                  {MARK[k]} {WORD[k]}
                </button>
              ))}
              {r.teacherVerdict && (
                <button disabled={busy} onClick={() => change(null)}>撤回改判</button>
              )}
            </div>
            {err && <div className="banner bad">{err}</div>}
          </td>
        </tr>
      )}
    </>
  )
}
