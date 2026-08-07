import { useEffect, useRef, useState } from 'react'
import { ApiError, getJob, listSceneVersions, pickScene, rescene, Unauthorized } from '../api'
import type { SceneVersion } from '../api'
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
  /** null = 还没查过。**懒加载**：一卷十几道题，进页面就每道都查一次太浪费 */
  const [vers, setVers] = useState<SceneVersion[] | null>(null)
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
        setNote(`重跑好了${j.scene ? `：${j.scene}` : ''}`)
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

  async function toggleVersions() {
    if (vers) { setVers(null); return }
    try {
      setVers((await listSceneVersions(paper, q.n)).versions)
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    }
  }

  async function switchTo(sceneId: string) {
    try {
      await pickScene(paper, q.n, sceneId)
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e)); return
    }
    setVers(null)
    onRescened?.()      // 换了版本，外面要重取试卷并重新加载 scene.js
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
                  title={running ? '⑤ 一轮几分钟，跑完这道题的动画会自动换上'
                                 : '重新生成这道题的动画（⑤），几分钟到几十分钟'}>
            {running ? (digest(job?.log ?? []) ?? '重跑中…') : '重跑动画'}
          </button>
        )}
        {/* 重跑出来的不一定更好（实测会把标签甩离它标注的对象），所以旧版一律
            留着，随时能换回去。懒加载：进页面时不查，点开才查 */}
        {q.sceneId && (
          <button className="btn" aria-pressed={!!vers}
                  onClick={() => void toggleVersions()}
                  title="这道题历次做出来的动画版本，可以换回旧的">
            {vers ? '收起版本' : '历史版本'}
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

        {/* 重跑的结果说在动画旁边。重跑失败时这句话尤其要紧 —— 后端会明说
            「原来那个动画没动」，否则人会以为自己把它点没了 */}
        {note && (
          <div className="note">
            {note}
            <button className="btn" style={{ marginLeft: 8 }}
                    onClick={() => setNote(null)}>知道了</button>
          </div>
        )}
        {running && (
          <div className="note">
            正在重跑这道题的动画（⑤ 是写代码→跑门禁→读报错→重来的循环，
            一轮几分钟）。<b>下面这个是旧动画，照常能看</b> —— 新的跑出来才会替换它。
          </div>
        )}

        {vers && (
          <div className="note">
            {vers.length <= 1
              ? '这道题只有当前这一个版本。'
              : <>这道题做出过 {vers.length} 个通过门禁的版本。
                  <b>新的不一定更好</b> —— 挑一个用：</>}
            <ul className="opts" style={{ marginTop: 8 }}>
              {vers.map((v) => (
                <li key={v.sceneId}>
                  <em>{v.current ? '●' : '○'}</em>
                  <span>
                    <code>{v.sceneId}</code>
                    　第 {v.rounds} 轮过门禁　{v.createdAt.slice(0, 16).replace('T', ' ')}
                    {v.current
                      ? <b>　（当前）</b>
                      : <>　<button className="btn"
                             onClick={() => void switchTo(v.sceneId)}>用这个</button></>}
                  </span>
                </li>
              ))}
            </ul>
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
