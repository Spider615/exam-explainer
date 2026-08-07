import { useEffect, useRef, useState } from 'react'
import { ApiError, getJob, rescene, Unauthorized } from '../api'
import Latex from './Latex'
import MathText from './MathText'
import StemBody from './StemBody'
import SolutionBody from './SolutionBody'
import SceneMount from './SceneMount'
import type { Job, Question } from '../types'

/**
 * 从任务日志里抽出一句人话：跑到第几轮、上一轮挂在哪一层。
 *
 * ⑤ 一轮几分钟，只显示一个转圈的话分不出「在跑」和「挂了」。而门禁层级尤其
 * 要说出来 —— 卡在 L4 物理断言多半是 spec 本身有问题（等下去也没用），
 * 卡在 L5 版面则是 agent 挪挪坐标就能好（等着就行）。
 */
function digest(log: string[]): string | null {
  let round: string | null = null
  let gate: string | null = null
  for (const l of log) {
    const r = l.match(/第\s*(\d+)\s*轮/)
    if (r) { round = r[1]; gate = null }        // 新一轮开始，上一轮的结论作废
    const g = l.match(/门禁 FAIL[^：:]*[：:]\s*(\S+)/)
    if (g) gate = g[1]
  }
  if (!round) return null
  return `第 ${round} 轮` + (gate ? ` · 上轮挂在 ${gate}` : '')
}

export default function QuestionCard({ q, paper, onRescened }: {
  q: Question
  paper: string
  /** 重跑出新动画了。外面要重取试卷并重新加载 scene.js，否则页面上还是旧的 */
  onRescened?: () => void
}) {
  const [compare, setCompare] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const running = job?.state === 'running'

  async function doRescene() {
    setNote(null)
    let id: string
    try {
      id = (await rescene(paper, q.n)).job
    } catch (e) {
      // 409 不是错误，是「等一下」。把后端那句话原样显示出来
      setNote(e instanceof ApiError ? e.message : String(e))
      return
    }
    setJob({ state: 'running', log: [] })
    for (;;) {
      if (!alive.current) return
      let j: Job
      try {
        j = await getJob(id)
      } catch (e) {
        if (e instanceof Unauthorized) return
        // 后端重启 / 网络抖动：任务可能还在跑，但这个句柄问不到了。
        // 不谎称失败 —— 说清楚去哪看结果
        setJob(null)
        setNote('问不到这次重跑的进度了（后端可能重启过）。它可能还在后台跑，'
                + '过一会儿刷新页面看这道题的动画有没有换。')
        return
      }
      if (!alive.current) return
      setJob(j)
      if (j.state === 'done') {
        // 不弹「重跑好了」——新动画自己会换上并开始播，那就是最好的回执。
        // 多一条要手动关掉的提示只是噪音
        setJob(null)
        onRescened?.()
        return
      }
      if (j.state === 'error') {
        setNote(j.err ?? '重跑没成功')
        setJob(null)
        return
      }
      await new Promise((r) => setTimeout(r, 4000))
    }
  }


  // 题目可能跨页，把页码区间展开成一串页号
  const pages: number[] = []
  for (let p = q.pages[0]; p <= q.pages[1]; p++) pages.push(p)

  return (
    <article className="q" id={`q${q.n}`}>
      <div className="qhd">
        <span className="qnum">{String(q.n).padStart(2, '0')}</span>
        <span className="pill">{q.type}</span>
        {q.points != null && <span className="pill">{q.points} 分</span>}
        {q.sceneId && <span className="pill g">动画 · 已过门禁</span>}
        {/* 只在已有动画时出现 —— 这个入口只做重跑，不做补做。没动画的题各有
            各的成因（④c 判不值得 / ④ 写不出断言 / ⑤ 跑失败），一个按钮糊上去
            只会让人以为点了就能有 */}
        {q.sceneId && (
          <button className="btn" onClick={() => void doRescene()} disabled={running}
                  title={running
                    ? (digest(job?.log ?? []) ?? '⑤ 一轮几分钟，跑完会自动换上并开始播')
                    : '重新生成这道题的动画（⑤），几分钟到几十分钟'}>
            {running ? <><i className="spin" />重跑中</> : '重跑动画'}
          </button>
        )}
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

        {/* 知识点。挂不上就明说 —— 不显示的话，「没挂上」和「还没跑过 ③c」
            在页面上长得一模一样 */}
        <div className="kps">
          {q.kps?.length
            ? q.kps.map((k) => (
                <span className="pill a" key={k.code} title={`${k.chapter} · ${k.why}`}>
                  {k.name}
                </span>
              ))
            : <span className="kp-none">这道题没挂上知识点</span>}
        </div>

        {/* 卷子上的标准答案。三种状态要分得出来：没跑过 ②d（不显示这一块）、
            跑过但卷子没答案、抽到了 */}
        {q.refAnswerSrc && (
          <div className="refans">
            {q.refAnswer ? (
              <>
                <b>卷子上的答案：</b>{q.refAnswer}
                <span className="src">
                  （{q.refAnswerSrc === 'paper' ? '从这份卷子里抽的' : '老师上传的答案文件'}）
                </span>
                {q.refAnswerAgrees === false && (
                  <span className="pill w">与 AI 答案不一致</span>
                )}
              </>
            ) : (
              <span className="src">
                这份卷子里没有参考答案 —— 判学生对错时这道题会记「判不了」，不算错
              </span>
            )}
          </div>
        )}

        {/* 重跑的结果说在动画旁边。重跑失败时这句话尤其要紧 —— 后端会明说
            「原来那个动画没动」，否则人会以为自己把它点没了 */}
        {note && (
          <div className="note">
            {note}
            <button className="btn" style={{ marginLeft: 8 }}
                    onClick={() => setNote(null)}>知道了</button>
          </div>
        )}


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
        {q.solution ? <SolutionBody s={q.solution} /> : (
          <div className="missing">
            <b>尚未生成</b><br />
            这道题还没跑过阶段③（解题）。
          </div>
        )}
      </div>
    </article>
  )
}
