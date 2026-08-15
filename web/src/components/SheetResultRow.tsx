import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { regrade } from '../api'
import RichText from './RichText'
import Zoom from './Zoom'
import type { SheetRow, Verdict } from '../types'

/** **半对是 ◐，自己一档。** 归到 ✓ 会让人以为这块掌握了，归到 ✗ 会让
    「一分没得」和「差一点」看起来一样严重 */
export const MARK: Record<Verdict, string> = {
  right: '✓', partial: '◐', wrong: '✗', blank: '—', unsure: '?',
}
export const WORD: Record<Verdict, string> = {
  right: '对', partial: '半对', wrong: '错', blank: '空着', unsure: '说不清',
}
/** 1203 → `12(3)`；9 → `9` */
export function showN(n: number) {
  return n >= 100 ? `${Math.floor(n / 100)}(${n % 100})` : String(n)
}

/**
 * 改判：**就地弹一个小菜单，不再往下展开一行。**
 *
 * 展开行的毛病是它把整张表顶开、上下行错位，改一道题要重新找回自己看到哪 ——
 * 而改判本身只是「在四个档里挑一个」。
 *
 * 菜单**挂到 `body` 上并按按钮的位置摆**，两个理由：
 *   · `.qtbl` 有 `overflow:hidden`（圆角要它），绝对定位的菜单会被裁掉；
 *   · 诊断页的根节点带 `transform`（`.rise`），`position:fixed` 会相对它定位。
 * 这两条都踩过。
 *
 * 页面一滚位置就不对了，所以**滚动就关**，不做跟随。
 */
function RegradeMenu({ r, busy, err, onPick }: {
  r: SheetRow
  busy: boolean
  err: string | null
  onPick: (v: Verdict | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState<{ top: number; left: number } | null>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const pop = useRef<HTMLDivElement>(null)
  const v = r.verdict || 'unsure'

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (!pop.current?.contains(e.target as Node)
          && !btn.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const gone = () => setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    window.addEventListener('scroll', gone, true)
    window.addEventListener('resize', gone)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', esc)
      window.removeEventListener('scroll', gone, true)
      window.removeEventListener('resize', gone)
    }
  }, [open])

  // 改判成功后这一行会被重新拉取，菜单跟着关掉
  useEffect(() => { if (!busy && !err) setOpen(false) }, [r.verdict, r.scoreGot])

  const toggle = () => {
    const b = btn.current?.getBoundingClientRect()
    if (b) setAt({ top: b.bottom + 6, left: b.left })
    setOpen((o) => !o)
  }

  /**
   * 摆好之后量一下，装不下就翻到按钮上方 / 往左收。
   *
   * **不能靠估一个高度。** 菜单是四档还是五档（有没有「撤回改判」）、
   * 有没有报错那一行，高度差着好几十像素；而表格最下面那几行的按钮离视口底边
   * 只有几十像素 —— 估错了菜单就掉出屏幕，那几道题永远改不了。
   */
  useLayoutEffect(() => {
    if (!open || !at || !pop.current) return
    const m = pop.current.getBoundingClientRect()
    const b = btn.current?.getBoundingClientRect()
    let { top, left } = at
    if (b && m.bottom > window.innerHeight - 8) top = Math.max(8, b.top - m.height - 6)
    if (m.right > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - m.width - 8)
    }
    if (top !== at.top || left !== at.left) setAt({ top, left })
  }, [open, at])

  return (
    <>
      <button ref={btn} className="qwhy" aria-haspopup="menu" aria-expanded={open}
              onClick={toggle}>改判</button>
      {open && at && createPortal(
        <div className="regrade" role="menu" ref={pop}
             style={{ top: at.top, left: at.left }}>
          <div className="regrade-hd">第 {showN(r.n)} 题改判为</div>
          {(['right', 'partial', 'wrong', 'blank'] as Verdict[]).map((k) => (
            <button key={k} role="menuitem" disabled={busy || v === k}
                    onClick={() => onPick(k)}>
              <i>{MARK[k]}</i>{WORD[k]}
            </button>
          ))}
          {/* 改判过才给「撤回」，并且说清楚要退回到什么 ——
              不说的话，老师不知道自己撤回之后会变成哪一档 */}
          {r.teacherVerdict && (
            <button className="regrade-undo" role="menuitem" disabled={busy}
                    onClick={() => onPick(null)}>
              撤回改判
              {r.sysVerdict && (
                <em>退回系统原判「{WORD[r.sysVerdict]}
                  {r.sysScoreGot != null ? ` · ${r.sysScoreGot} 分` : ''}」</em>
              )}
            </button>
          )}
          {err && <p className="regrade-err">{err}</p>}
        </div>,
        document.body)}
    </>
  )
}

/**
 * 逐题结果的一行。
 *
 * **原图切片挨着判定，不藏进二级页面** —— 它是老师校对模型转写的唯一红绿灯。
 * 但也不占半屏：行内缩略图，点开看大的。题目同理，它是单独一列。
 *
 * **这一行不再往下展开。** 判定依据不显示了（老师要的是结论和改判入口，
 * 不是我的判定过程）；改判是就地弹的小菜单；老师红笔写的答案和官方解答
 * 归到「正确答案」那一格 —— 它们本来就是「正确答案是什么」的另外两个来源。
 */
export default function SheetResultRow({ r, sheet, onChanged }: {
  r: SheetRow
  sheet: number
  onChanged: () => void
}) {
  const v = r.verdict || 'unsure'
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

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
          {/* 老师在卷子旁边红笔写的正确答案。**白捡的第三份对照** ——
              它和「正确答案是什么」是同一件事，所以就长在这一格里 */}
          {r.red && (
            <span className="ans-red">老师红笔：<RichText text={r.red} /></span>
          )}
          {/* 官方解答往往几百字，塞进格子里会把整行撑开 —— 点开在放大层里读，
              和题目那一列同一个交互 */}
          {r.refSolution && (
            <Zoom trigger="zoom-link" label={`第 ${showN(r.n)} 题的官方解答`}
                  thumb={<>官方解答</>}>
              <div className="lightbox-text">
                <RichText text={r.refSolution.replace(/\$\$/g, '$')} />
                <p className="dim">来自你上传的参考答案，不是 AI 写的。</p>
              </div>
            </Zoom>
          )}
        </td>

        {/* 判定依据不显示了 —— 老师要的是结论和改判入口，不是我的判定过程。
            它仍然留在 `title` 里：想知道「凭什么这么判」的时候够得着，
            但不占版面 */}
        <td data-label="判定" title={r.verdictWhy ?? undefined}>
          <span className={`v v-${v}`}>{MARK[v]} {WORD[v]}</span>
          {/* 分数跟判定一起给 —— 只说「半对」而不给分，老师没法核对 */}
          {r.scoreGot != null && r.scoreFull != null && (
            <em className="score">{r.scoreGot}/{r.scoreFull}</em>
          )}
          {r.teacherVerdict && <em className="by">已改判</em>}
          <RegradeMenu r={r} busy={busy} err={err} onPick={change} />
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
    </>
  )
}
