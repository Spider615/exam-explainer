import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getPaper } from '../api'
import RichText from './RichText'
import { showN } from './SheetResultRow'
import type { Paper } from '../types'

/**
 * 「这份卷子的标准答案」—— 一个按钮，点开一个框，**不跳走**。
 *
 * 以前这里是「← 回到这份卷子」：跳到卷子页去看每题的标准答案，看完再退回来，
 * 而老师正在逐题核对，回来还得找回自己滚到哪了。这一屏要的只是「对一下答案」，
 * 不值得换一整页。
 *
 * **卷子页没有作废**：那上面还有 Ⓐ 的进度和「再传一个学生」的上传入口，
 * 从答题卡库那一行的「N 份」进得去。
 *
 * 数据用的是**已有的整卷端点**，没有为它新加路由 —— 加路由要重启后端，
 * 而重启会把正在跑的管线一起带走。答题卡模式的卷子没有 AI 解法、没有动画、
 * 没有插图，这一趟拿回来的东西比解析试卷那边小得多；而且只在点开时拉一次。
 */
export default function PaperAnswers({ paper }: { paper: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<Paper | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', esc)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', esc)
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open || (data && !err)) return
    let alive = true
    setErr(null)
    getPaper(paper)
      .then((p) => { if (alive) setData(p) })
      .catch((e) => { if (alive) setErr(e instanceof Error ? e.message : String(e)) })
    return () => { alive = false }
  }, [open, paper, tick])

  const qs = data?.questions ?? []

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>这份卷子的标准答案</button>
      {open && createPortal(
        // 和放大层同一套：点空白关、Esc 关。**必须 portal 到 body** ——
        // 诊断页根节点带 transform（`.rise`），fixed 会相对它定位
        <div className="lightbox" role="dialog" aria-modal="true"
             aria-label={`${paper} 的标准答案`} onClick={() => setOpen(false)}>
          <div className="lightbox-in papers" ref={box} onClick={(e) => e.stopPropagation()}>
            <header className="papers-hd">
              <b>{paper}</b>
              <span>{qs.length ? `${qs.length} 题` : ''}</span>
            </header>

            {err ? (
              <div className="banner bad">
                <b>没读到这份卷子的答案</b>　{err}
                <div className="runcard-acts">
                  <button className="btn" onClick={() => setTick((t) => t + 1)}>
                    再试一次
                  </button>
                </div>
              </div>
            ) : !data ? (
              <div className="empty"><b>正在读…</b></div>
            ) : qs.length === 0 ? (
              <div className="empty">
                <b>这份卷子还没有题</b>
                <span>参考答案那一步可能没跑完 —— 去答题卡库看看它的进度。</span>
              </div>
            ) : (
              <ol className="papers-list">
                {qs.map((q) => (
                  <li key={q.n}>
                    <b>{showN(q.n)}</b>
                    <div>
                      {/* ── 原题 ────────────────────────────────────────────
                          光有答案对不上题 —— 「D」放在这儿，老师还是得回去翻
                          第 1 题问的是什么。

                          **截图优先于转写的文字**（和别处同一条规矩）：Ⓔ 的
                          提示词要求「插图只用一句话描述」，所以转写那一段
                          把图丢了，而一道题四个选项全是公式时，那串 LaTeX
                          源码读起来还不如不给。
                          `loading="lazy"` 不能省：一份卷子二十几张整页宽的图，
                          一次全拉会把这个框卡住。 */}
                      {q.stemImage ? (
                        <img className="papers-stem" src={q.stemImage}
                             alt={`第 ${showN(q.n)} 题在原卷上的样子`} loading="lazy" />
                      ) : q.stem ? (
                        <p className="papers-stemtext">
                          <RichText text={q.stem.replace(/\$\$/g, '$')} />
                        </p>
                      ) : (
                        <p className="dim">这道题还没有题目 —— 把原卷传进「原卷」那一栏就能读到</p>
                      )}
                      {/* 留白会被读成「这道题本来就没有答案」。说清楚是哪一步没认出来 */}
                      {q.refAnswer
                        ? <p className="papers-ans">
                            <i>标准答案</i><RichText text={q.refAnswer} />
                          </p>
                        : <p className="dim">这道题没有标准答案 —— Ⓐ 读参考答案时没认出来</p>}
                      {q.refSolution && (
                        <p className="papers-sol">
                          <RichText text={q.refSolution.replace(/\$\$/g, '$')} />
                        </p>
                      )}
                      {q.kps?.length ? (
                        <p className="papers-kp">
                          {q.kps.map((k) => (
                            <span key={k.code} className="kp" title={k.why}>{k.name}</span>
                          ))}
                        </p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            )}

            <footer className="papers-ft">
              标准答案与解答过程<b>来自你上传的参考答案</b>，由视觉模型逐页转写，
              可能有转写错误。知识点标签由 AI 生成。
            </footer>
          </div>
          <button type="button" className="lightbox-x" aria-label="关闭"
                  onClick={() => setOpen(false)}>×</button>
        </div>,
        document.body)}
    </>
  )
}
