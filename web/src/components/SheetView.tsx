import { useCallback, useEffect, useState } from 'react'
import { getPaper, getProgress } from '../api'
import AnswerQuestionCard from './AnswerQuestionCard'
import type { Paper, Progress } from '../types'

/**
 * 答题卡模式的详情页。
 *
 * **和 PaperView 是两个组件。** 这边没有动画、没有目录、没有答案速览、
 * 没有「n 张图为动画」，页脚那句免责也完全不同 —— 这边的标准答案和解答过程
 * 来自老师给的参考答案，**不是 AI 生成的**，AI 生成的只有知识点标签。
 */
export default function SheetView({ name }: { name: string }) {
  const [paper, setPaper] = useState<Paper | null>(null)
  const [pg, setPg] = useState<Progress | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => {
    getPaper(name).then(setPaper).catch((e) => setErr(String(e)))
  }, [name])
  useEffect(() => { setPaper(null); setErr(null); load() }, [name, load])

  // 进度轮询：计数一变就把整卷重新拉一遍，新读出来的题会自己出现
  useEffect(() => {
    let alive = true
    let timer = 0
    let seen = ''
    const tick = async () => {
      try {
        const p = await getProgress(name)
        if (!alive) return
        setPg(p)
        const key = [p.questions, p.kps, p.lastChange ?? 0].join('-')
        if (seen && key !== seen) load()
        seen = key
      } catch { /* 后端重启之类，下一轮再说 */ }
      if (alive) timer = window.setTimeout(tick, pg?.busy === false ? 15000 : 3000)
    }
    timer = window.setTimeout(tick, 300)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [name, load, pg?.busy])

  if (err) return <div className="banner bad"><b>打不开</b>　{err}</div>
  if (!paper) return <div className="empty">载入中…</div>

  const cells = pg?.mode?.stages ?? paper.mode?.stages ?? []
  const qs = paper.questions
  const withSolution = qs.filter((q) => q.refSolution).length
  const withKps = qs.filter((q) => q.kps?.length).length

  return (
    <div>
      <div className="stages">
        {cells.map((c) => (
          <span key={c.code} className={`stage st-${c.state}`}>
            {c.state === 'now' && <i className="stage-dot" />}
            {c.label}
          </span>
        ))}
      </div>

      {pg?.failed && (
        <div className="banner bad"><b>上一次没跑完</b>　{pg.failed}</div>
      )}

      <div className="facts">
        <div className="fact"><b>{qs.length}</b><span>题</span></div>
        {/* 「带解答」天生小于题数，标题里把原因说清楚，免得被当成漏读 */}
        <div className="fact" title="参考答案的版式就是只有大题给解答过程">
          <b>{withSolution}</b><span>题带官方解答</span>
        </div>
        <div className="fact"><b>{withKps}</b><span>题挂了知识点</span></div>
      </div>

      {qs.map((q) => <AnswerQuestionCard key={q.n} q={q} />)}

      {/* 话术和解析试卷完全不同：这边的答案是老师给的，不是 AI 算的 */}
      <footer className="ai-note">
        标准答案与解答过程<b>来自你上传的参考答案</b>，由视觉模型逐页转写，
        可能有转写错误，请对照原件核对。知识点标签由 AI 生成，未经人工审核。
        这份卷子还没有题干，也还没有学生的答题卡。
      </footer>
    </div>
  )
}
