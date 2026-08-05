import { useState } from 'react'
import Latex from './Latex'
import MathText from './MathText'
import StemBody from './StemBody'
import SolutionBody from './SolutionBody'
import SceneMount from './SceneMount'
import type { Question } from '../types'

export default function QuestionCard({ q, paper }: { q: Question; paper: string }) {
  const [compare, setCompare] = useState(false)
  // 题目可能跨页，把页码区间展开成一串页号
  const pages: number[] = []
  for (let p = q.pages[0]; p <= q.pages[1]; p++) pages.push(p)

  return (
    <article className="q" id={`q${q.n}`} tabIndex={-1} aria-label={`第 ${q.n} 题`}>
      <div className="qhd">
        <span className="qnum">{String(q.n).padStart(2, '0')}</span>
        <span className="pill">{q.type}</span>
        {q.points != null && <span className="pill">{q.points} 分</span>}
        {q.sceneId && <span className="pill g">动画 · 已过门禁</span>}
        {q.stemLatex && <span className="pill g">公式 · 视觉识别</span>}
        {q.stemLowConf && <span className="pill w">转写待核对</span>}
        {q.textQuality === 'degraded' && <span className="pill w">文字层不可用</span>}
        <button className="btn" style={{ marginLeft: 'auto' }}
                aria-pressed={compare}
                onClick={() => setCompare((c) => !c)}>
          {compare ? '收起原卷' : `对照原卷 p${q.pages[0]}${
            q.pages[1] !== q.pages[0] ? `-${q.pages[1]}` : ''}`}
        </button>
      </div>

      <div className="qbd">
        {q.textQuality === 'degraded' && (
          <div className="warn">
            这道题的文字层{q.qualityReason}，下面的题干与选项可能有信息丢失，请以原卷为准。
          </div>
        )}

        {compare && (
          <div className="cmp">
            <div className="cmp-hint">
              左边是切出来的内容，下面是原卷整页。核对题目边界、图有没有归错、
              选项是不是完整——这些光看文本判断不了。
            </div>
            <div className="cmp-pages">
              {pages.map((p) => (
                <figure key={p}>
                  <img src={`/api/papers/${encodeURIComponent(paper)}/page/${p}`}
                       alt={`原卷第 ${p} 页`} loading="lazy" />
                  <figcaption>原卷第 {p} 页</figcaption>
                </figure>
              ))}
            </div>
          </div>
        )}

        {(q.stemLowConf || q.stemRejected) && (
          <div className="warn">
            {q.stemLowConf ?? q.stemRejected}
            {q.stemImage && <>　<a href={q.stemImage} target="_blank" rel="noreferrer">看原卷题干 →</a></>}
          </div>
        )}

        <div className="stem"><StemBody q={q} /></div>

        {q.sceneId && q.sceneFigure
          ? <SceneMount sceneId={q.sceneId} figureHtml={q.sceneFigure} />
          : (q.figMarks?.length ?? 0) ? null : q.figures.map((f, i) => (
              <figure key={i}>
                <img src={f.url} alt={`第${q.n}题插图`} style={{ width: `${f.widthPct}%` }} />
              </figure>
            ))}

        {q.options.length > 0 && (
          <ul className="opts">
            {q.options.map((o) => (
              <li key={o.key}>
                <em>{o.key}</em>
                <span>
                  {o.latex
                    ? <Latex tex={o.latex} />
                    : <MathText text={o.text} math={o.math} />}
                  {o.figure && <img src={o.figure} alt={`选项${o.key}`} />}
                </span>
              </li>
            ))}
          </ul>
        )}

        {q.optionImage && (
          <details className="optimg-wrap">
            <summary>对照原卷选项区（公式由视觉模型识别，出错时以此为准）</summary>
            <img className="optimg" src={q.optionImage} alt="原卷选项区" loading="lazy" />
          </details>
        )}

        <h2 className="lbl">解题思路</h2>
        {q.solution ? <SolutionBody s={q.solution} />
          : q.solutionFailure ? (
            <div className="solve-fail">
              <b>生成失败</b>
              <span>{q.solutionFailure.reason}</span>
              <small>
                {q.solutionFailure.stage} · 已尝试 {q.solutionFailure.attempts} 次
              </small>
            </div>
          ) : (
          <div className="missing">
            <b>尚未生成</b><br />
            这道题还没跑过阶段③（解题）。
          </div>
        )}
      </div>
    </article>
  )
}
