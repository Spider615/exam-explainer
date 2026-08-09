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
      {/* 停下来的「在跑」格子不能继续闪 —— 呼吸点是「正在动」的信号，一份已经
          停在这一步的卷子那格还在闪会被当成还在跑。逻辑抄自 PaperView（那边的
          注释写了完整理由）；这条链只有两格、没有「产物」这一说，所以 why 比
          那边少一档「库里已经有一些产出」——但为了不撒谎，其余分支照样要覆盖到，
          不能图省事写死成「已完成」 */}
      <div className="stages">
        {cells.map((c) => {
          const stalled = c.state === 'now' && pg != null && !pg.busy
          const why = c.state === 'fail' ? `失败：${pg?.failed}`
            : c.state === 'empty' ? '这一步跑过了，但没有产出'
              : stalled ? '停在这一步，还没做完'
                : c.state === 'now' ? '正在跑这一步'
                  : c.state === 'done' ? '已完成'
                    : '还没跑到这一步'
          return (
            <span key={c.code}
                  className={`stage st-${c.state}${stalled ? ' idle' : ''}`}
                  title={why}>
              {c.state === 'now' && <i className="stage-dot" />}
              {c.label}
            </span>
          )
        })}
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
