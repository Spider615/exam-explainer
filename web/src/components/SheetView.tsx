import { useCallback, useEffect, useState } from 'react'
import { ApiError, getPaper, getProgress } from '../api'
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
  /** 卷子确认不在了（进度端点 404）。多半是刚才一次 Ⓐ 读参考答案失败，
      后端把这次新建的空壳删掉了——是终态，不用再问 */
  const [gone, setGone] = useState(false)
  /** 连着几轮问不到进度了（网络抖动/后端重启中，不是卷子没了）。0 = 正常 */
  const [pollMiss, setPollMiss] = useState(0)

  const load = useCallback(() => {
    getPaper(name).then(setPaper).catch((e) => setErr(String(e)))
  }, [name])
  useEffect(() => {
    setPaper(null); setErr(null); setGone(false); setPollMiss(0)
    load()
  }, [name, load])

  /**
   * 进度轮询：计数一变就把整卷重新拉一遍，新读出来的题会自己出现。
   *
   * **404 和「问不到」是两件不一样的事，不能都吞掉。** 以前这里 `catch {}`
   * 什么都不做——Ⓐ 读参考答案失败到「一道题都没读出来」时，后端会删掉这次
   * 新建的空壳卷子，进度端点从此 404；旧代码会让 `pg` 停在删除前最后一次
   * 成功轮询的样子，「正在跑这一步」的呼吸点永远闪下去，页面看起来像还在
   * 处理，其实那份卷子已经不存在了。现在 404 直接判定为「卷子不在了」，
   * 停止轮询；其余错误（网络抖动、后端重启中）继续退避重试，但要把
   * 「问不到」这件事说出来——静默重试和「一切正常」在界面上长得一样。
   */
  useEffect(() => {
    let alive = true
    let timer = 0
    let seen = ''
    const tick = async () => {
      try {
        const p = await getProgress(name)
        if (!alive) return
        setPg(p)
        setPollMiss(0)
        const key = [p.questions, p.kps, p.lastChange ?? 0].join('-')
        if (seen && key !== seen) load()
        seen = key
      } catch (e) {
        if (!alive) return
        if (e instanceof ApiError && e.status === 404) {
          setGone(true)
          return          // 确认没了，不再排下一轮
        }
        setPollMiss((m) => m + 1)
      }
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
      {/* 卷子确认不在了。多半是 Ⓐ 读参考答案没成功——一道题的答案都没认出来时，
          后端会把这次新建的空壳卷子删掉，进度端点从此 404。下面仍然用 pg 画
          阶段格子，但那是删除前最后一次问到的快照，不能让「正在跑」的呼吸点
          接着闪，那会撒谎——见下面 stalled 的判断 */}
      {gone && (
        <div className="banner bad">
          <b>这份卷子不在了</b>　多半是刚才那次「Ⓐ 读参考答案」没成功——一道
          题的答案都没认出来时，后端会把这次新建的空壳卷子删掉。下面显示的是
          它消失前的最后一次快照，不会再更新了。回答题卡库重新传一批更清楚的图。
        </div>
      )}
      {/* 问不到进度不等于卷子没了——网络抖动、后端重启中都会短暂 404 不了、
          而是直接连不上。不能像以前那样静默重试，界面会和「一切正常」长得
          一模一样 */}
      {!gone && pollMiss > 0 && (
        <div className="banner bad">
          <b>连不上后端</b>　问「进度」已经失败 {pollMiss} 次。下面显示的是
          最后一次问到的状态，可能不是最新的；恢复之后会接着更新。
        </div>
      )}

      {/* 停下来的「在跑」格子不能继续闪 —— 呼吸点是「正在动」的信号，一份已经
          停在这一步的卷子那格还在闪会被当成还在跑。逻辑抄自 PaperView（那边的
          注释写了完整理由）；这条链只有两格、没有「产物」这一说，所以 why 比
          那边少一档「库里已经有一些产出」——但为了不撒谎，其余分支照样要覆盖到，
          不能图省事写死成「已完成」。`gone` 同样要拦下呼吸点，理由见上面那条 */}
      <div className="stages">
        {cells.map((c) => {
          const stalled = c.state === 'now' && (gone || (pg != null && !pg.busy))
          const why = gone && c.state === 'now' ? '卷子不在了——这是它消失前的最后状态'
            : c.state === 'fail' ? `失败：${pg?.failed}`
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
