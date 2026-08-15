import { useState } from 'react'
import { regrade } from '../api'
import RichText from './RichText'
import Zoom from './Zoom'
import type { SheetRow, Verdict, VerdictBy } from '../types'

/** **半对是 ◐，自己一档。** 归到 ✓ 会让人以为这块掌握了，归到 ✗ 会让
    「一分没得」和「差一点」看起来一样严重 */
export const MARK: Record<Verdict, string> = {
  right: '✓', partial: '◐', wrong: '✗', blank: '—', unsure: '?',
}
export const WORD: Record<Verdict, string> = {
  right: '对', partial: '半对', wrong: '错', blank: '空着', unsure: '说不清',
}
const BY: Record<VerdictBy, string> = {
  teacher_score: '照卷子上印的分数',
  teacher_mark: '照红勾红叉',
  code: '系统按标准答案判的',
  model: '模型判的',
  teacher: '你改判的',
}

/** 1203 → `12(3)`；9 → `9` */
export function showN(n: number) {
  return n >= 100 ? `${Math.floor(n / 100)}(${n % 100})` : String(n)
}

/**
 * 逐题结果的一行。
 *
 * **原图切片挨着判定，不藏进二级页面** —— 它是老师校对模型转写的唯一红绿灯。
 * 但也不占半屏：行内缩略图，点开看大的。
 *
 * 展开之后才出现「怎么判的、老师红笔写了什么、官方解答、改判」。第一眼不需要，
 * 但要够得着。
 */
export default function SheetResultRow({ r, sheet, onChanged }: {
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
        <td className="qn" data-label="题">{showN(r.n)}</td>

        {/* ── 题目 ────────────────────────────────────────────────────────
            **它是一列，不藏在展开区里。** 「第 6 题错了」的下一个问题永远是
            「第 6 题问的是什么」—— 为这个点一下展开，二十几道题就要点二十几次。

            截图优先于转写的文字（和卷子页同一条规矩）：转写那一段把图丢了，
            而一道题四个选项全是公式时，`$\frac{...}{...}$` 这种源码读起来
            还不如不给。 */}
        <td className="qstem-cell" data-label="题目">
          {r.stemImage ? (
            <Zoom label={`第 ${showN(r.n)} 题的题目`}
                  thumb={<img src={r.stemImage} alt={`第 ${showN(r.n)} 题的题目`}
                              loading="lazy" />}>
              <img className="lightbox-img" src={r.stemImage}
                   alt={`第 ${showN(r.n)} 题在原卷上的样子`} />
            </Zoom>
          ) : r.stem ? (
            <Zoom label={`第 ${showN(r.n)} 题的题目`}
                  thumb={<span className="zoom-text">题目（文字）</span>}>
              <div className="lightbox-text">
                {/* 只把 `$$` 收成 `$`，不做别的修补 —— 题干大半是中文散句，
                    整段包成公式会被 KaTeX 拿去硬解析中文和标点 */}
                <RichText text={r.stem.replace(/\$\$/g, '$')} />
                <p className="dim">这道题没切出原卷截图，上面是转写的文字。</p>
              </div>
            </Zoom>
          ) : (
            /* 留白会被读成「这道题本来就没有题目」。两种缺法要说得不一样 */
            <span className="dim" title={r.bound
              ? '这份卷子还没读过题干 —— 把原卷传进「原卷」那一栏，重新上传一次'
              : '这一条挂不上题（题号在参考答案里对不上），找不到它对应的题目'}>
              {r.bound ? '没有题干' : '挂不上题'}
            </span>
          )}
        </td>

        <td className="qcrop-cell" data-label="原图">
          {r.crop
            ? <Zoom label={`第 ${showN(r.n)} 题在答题卡上的原图`}
                    thumb={<img src={r.crop} alt={`第 ${showN(r.n)} 题原图`}
                                loading="lazy" />}>
                <img className="lightbox-img" src={r.crop}
                     alt={`第 ${showN(r.n)} 题在答题卡上的原图`} />
              </Zoom>
            : <span className="dim">没有切片</span>}
        </td>

        <td className="ans" data-label="学生答案">
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

        <td className="ans" data-label="正确答案">
          {r.refAnswer
            ? <RichText text={r.refAnswer} />
            : <span className="dim" title={r.bound ? '' : '这条挂不上题，没有标准答案可对'}>
                {r.bound ? '—' : '挂不上题'}
              </span>}
        </td>

        <td data-label="判定">
          <span className={`v v-${v}`}>{MARK[v]} {WORD[v]}</span>
          {/* 分数跟判定一起给 —— 只说「半对」而不给分，老师没法核对 */}
          {r.scoreGot != null && r.scoreFull != null && (
            <em className="score">{r.scoreGot}/{r.scoreFull}</em>
          )}
          {r.teacherVerdict && <em className="by">已改判</em>}
          {/* 「详情」那个按钮去掉了（题目已经是一列，不用再点开看）。
              剩下的那几样 —— 怎么判的、老师红笔写了什么、官方解答、改判 ——
              全都是**判定**这件事的下文，所以入口挪到这一格里，
              名字直接叫它要做的事 */}
          <button className="qwhy" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? '收起' : '依据 · 改判'}
          </button>
        </td>

        <td data-label="知识点">
          {r.kps.length
            ? r.kps.map((k) => (
                <span key={k.code} className="kp" title={k.why}>{k.name}</span>
              ))
            : <span className="dim">—</span>}
        </td>

        {/* 老师看完「哪几道错了」之后的下一个问题是「那我该怎么办」。
            **只有没拿满分的题才有** —— 对的题不需要建议。
            **说不出具体的就留白**，不拿一句正确的废话补位 */}
        <td className="adv" data-label="为什么错 · 怎么提高">
          {r.advice?.why && <p className="adv-why">{r.advice.why}</p>}
          {r.advice?.fix && <p className="adv-fix">{r.advice.fix}</p>}
          {!r.advice?.why && !r.advice?.fix && (
            <span className="dim">{v === 'right' ? '—' : '看不出具体原因'}</span>
          )}
        </td>

      </tr>

      {open && (
        <tr className="qrow-more">
          {/* 题目已经是一列了，这里不再重复贴一遍 —— 剩下的全是「怎么判的」
              和「要不要改判」 */}
          <td colSpan={7}>
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
                <button className="btn" key={k} disabled={busy || v === k}
                        onClick={() => change(k)}>
                  {MARK[k]} {WORD[k]}
                </button>
              ))}
              {r.teacherVerdict && (
                <button className="btn" disabled={busy} onClick={() => change(null)}>
                  撤回改判
                </button>
              )}
            </div>
            {err && <div className="banner bad">{err}</div>}
          </td>
        </tr>
      )}
    </>
  )
}
