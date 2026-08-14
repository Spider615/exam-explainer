import { useCallback, useEffect, useMemo, useState } from 'react'
import { getPaper, getProgress, resumePaper, sceneScriptUrl } from '../api'
import JobProgress from './JobProgress'
import MetricCard, { Metrics } from './MetricCard'
import PaperSidebar from './PaperSidebar'
import QuestionCard from './QuestionCard'
import { fmtDur } from '../fmt'
import type { Paper, Progress, Question } from '../types'

/**
 * 跳到某一题。
 *
 * **不能用 `<a href="#q3">`。** 整个 App 是 hash 路由（`#/p/<卷名>`），
 * 改 hash 会被路由当成「回到试卷库」，点一下目录直接把当前卷子关掉。
 * 所以目录一律是 button + scrollIntoView，不碰 location.hash。
 */
function jumpTo(n: number) {
  const target = document.getElementById(`q${n}`)
  if (!target) return
  target.focus({ preventScroll: true })
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 一格答案放得下多少字。超过就不硬塞，点进去看完整解法 */
const SHORT_MAX = 24

/**
 * 速览/目录里那一格答案，连同它是哪一种「有」或「没有」。
 *
 * 短答案由 ③b 压出来，而 ③b 是**整卷一次调用**，跑在 ③ 之后（现在也会在 ③
 * 中途滚动跑）。所以必然有一段时间是「题已经解出来了，短答案还没压出来」——
 * 那时候显示「尚未生成」是**错的**：它说的是这题还没解，而它已经解了。
 *
 * 所以分五种：
 *   short    ③b 压好的一行答案
 *   raw      还没压，但完整答案本身就短（选择题的 `D`、多空的 `小于,等于,小于`）
 *            —— 整条显示，**不截断**。截一段得到的是「(1) α=30°，U_MN=3mv…」，
 *            既不完整也不好看，不如不给
 *   pending  已解出，但答案是一长串三问，等 ③b 压
 *   failed   ③ 已经结束，但三次尝试都没有产出解法
 *   none     真的还没解
 */
function shortOf(q: Question): {
  text: string
  kind: 'short' | 'raw' | 'pending' | 'failed' | 'none'
} {
  if (!q.solution && q.solutionFailure) return { text: '生成失败', kind: 'failed' }
  const s = q.solution
  if (!s) return { text: '尚未生成', kind: 'none' }
  const short = s.shortAnswer?.trim()
  if (short) return { text: short, kind: 'short' }
  const full = (s.answer || '').trim()
  if (full && !full.includes('\n') && full.length <= SHORT_MAX)
    return { text: full, kind: 'raw' }
  return { text: '已解出 · 待压缩', kind: 'pending' }
}

export default function PaperView({ name }: { name: string }) {
  const [paper, setPaper] = useState<Paper | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [scenesReady, setScenesReady] = useState(false)
  const [pg, setPg] = useState<Progress | null>(null)
  const [playing, setPlaying] = useState(true)
  const [resuming, setResuming] = useState(false)
  const [resumeNote, setResumeNote] = useState<string | null>(null)

  const load = useCallback(() => {
    getPaper(name).then(setPaper).catch((e) => setErr(String(e)))
  }, [name])

  useEffect(() => {
    setPaper(null); setErr(null); setScenesReady(false)
    load()
  }, [name, load])

  /**
   * 进度轮询。**从库里算，不看内存里的任务表。**
   *
   * 以前这里轮询的是 `/api/jobs/{id}`，而任务表是 api.py 进程内的一个 dict——
   * 命令行跑的任务根本不在里面，服务重启后内存也清空。于是后台明明在跑，
   * 页面上一点动静都没有。用户原话：「为啥我在页面上根本都没有看到任何在跑的等待效果」。
   *
   * 现在轮询的是计数（解了几题、写了几份 spec、过了几个门禁）。**计数一变就
   * 重新拉整卷**，所以新解出的题、新绿灯的动画会自己出现，不用手动刷新。
   * 轮询的是轻量端点：整卷数据有一两兆，不能拿来每三秒拉一次。
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
        const solutionFailures = p.solutionFailures ?? 0
        const key = [p.solutions, solutionFailures, p.labels, p.specs, p.judged, p.scenes,
                     p.assembled, p.lastChange ?? 0].join('-')
        if (seen && key !== seen) load()      // 有新东西落库了，把整卷重新拉一遍
        seen = key
      } catch { /* 服务重启中之类，下一轮再说 */ }
      // 在跑就盯紧点，跑完了就放慢——没必要为一份静止的卷子每三秒打一次
      if (alive) timer = window.setTimeout(tick, pg?.busy === false ? 15000 : 3000)
    }
    timer = window.setTimeout(tick, 300)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [name, load, pg?.busy])

  /**
   * 继续执行。
   *
   * 后端 409 的两种情况（正在跑、已经完成）都不是错误，是「不用点」——
   * 所以把 detail 原样显示出来，别糊成一句「失败」。
   *
   * 点完立刻把 busy 打开：轮询要 3 秒才回来，这三秒里按钮还在、状态还写着
   * 「已停止」，人会以为没点上而再点一次。
   */
  const onResume = useCallback(async () => {
    setResuming(true); setResumeNote(null)
    try {
      const r = await resumePaper(name)
      setResumeNote(`已从「${r.from}」接着跑。已经做完的步骤会跳过。`)
      setPg((p) => (p ? { ...p, busy: true } : p))
    } catch (e) {
      setResumeNote(String(e instanceof Error ? e.message : e))
    } finally {
      setResuming(false)
    }
  }, [name])

  // 场景脚本必须在 QuestionCard 渲染之前就位，否则工厂还没注册。
  // 每次换卷子都重新加载：不同卷子绑定的场景不同。
  useEffect(() => {
    if (!paper) return
    const s = document.createElement('script')
    s.src = sceneScriptUrl(name) + `?t=${Date.now()}`
    s.onload = () => setScenesReady(true)
    s.onerror = () => setScenesReady(true)   // 没有场景也要往下渲染
    document.head.appendChild(s)
    return () => { s.remove() }
  }, [paper, name])

  const stats = useMemo(() => {
    if (!paper) return null
    const qs = paper.questions
    const points = qs.reduce((a, q) => a + (q.points ?? 0), 0)
    // 大题分布按 section 分组，没有 section 的卷子退回按题型
    const groups = new Map<string, Question[]>()
    for (const q of qs) {
      const k = q.section || q.type || '未分组'
      groups.set(k, [...(groups.get(k) ?? []), q])
    }
    return {
      n: qs.length,
      points,
      groups: [...groups.entries()],
      scenes: qs.filter((q) => q.sceneId).length,
      // 建议用时按分值估（高考物理 100 分 / 75 分钟）。是估算，标签里写明白
      minutes: points ? Math.round(points * 0.75) : 0,
    }
  }, [paper])

  if (err) return <div className="banner bad"><b>打不开</b>　{err}</div>
  if (!paper || !stats) return <div className="empty">载入中…</div>

  const pct = pg && pg.stageTotal ? Math.round((pg.stageCur / pg.stageTotal) * 100) : null
  // 格子清单与每格状态都由后端算好 —— 轮询回来的更新，没回来就用整卷带的那份
  const cells = pg?.mode?.stages ?? paper.mode?.stages ?? []
  const failureCount = pg?.solutionFailures ?? 0
  const failedQuestions = paper.questions.filter((q) => !q.solution && q.solutionFailure)
  const toggleAll = () => {
    const next = !playing
    setPlaying(next)
    window.dispatchEvent(new CustomEvent<boolean>('scenes:playing', { detail: next }))
  }

  let lastSection: string | null = null
  return (
    <div>
      {/* 没跑到的阶段**不能画成删除线** —— 删除线读作「作废、不做了」，
          而它们只是还没排到。每种状态给一种视觉：做完了(青底✓)、在跑(实底+呼吸点)、
          还没轮到(虚线框)、跑过了没产物(灰实线—)。停下来的时候「在跑」那格不闪，
          免得看着像还在动 */}
      <div className="stages">
        {cells.map((c) => {
          const stalled = c.state === 'now' && pg != null && !pg.busy
          const why = c.state === 'fail' ? `失败：${pg?.failed}`
            : c.state === 'empty' ? '这一步跑过了，但没有产出'
              : stalled ? '停在这一步，还没做完'
                : c.state === 'now' ? '正在跑这一步'
                  : c.state === 'done' ? '已完成'
                    // 「还没轮到」有两种，话不一样。库里明明有这一步的产出、
                    // 而推断说还没走到，那不是「还没跑」—— 管线不是单调跑一遍的，
                    // 实测九份卷子有三份是这个样子（见 modes.cell_states 的说明）。
                    // 说成「还没跑到」会让人以为库里是空的
                    : paper.stages[c.code]
                      ? '这一轮还没跑到这一步（库里已经有一些产出）'
                      : '还没跑到这一步'
          return (
            <span key={c.code}
                  className={`stage st-${c.state}${stalled ? ' idle' : ''}`}
                  title={[why, paper.stageNotes?.[c.code]].filter(Boolean).join(' · ')}>
              {c.state === 'now' && <i className="stage-dot" />}
              {c.label}
            </span>
          )
        })}
      </div>

      {/* 失败要**用字说出来**，不能只靠某一格变红加一个 title —— title 在触屏和
          键盘上根本够不着，而后端说不清是哪一步时连那一格都没有 */}
      {pg?.failed && (
        <div className="banner bad">
          <b>上一次没跑完</b>　{pg.failed}
          {!pg.failedStage && '　（后端说不清是哪一步挂的）'}
        </div>
      )}

      {pg && (pg.busy || !pg.done) && (
        <JobProgress
          tone={pg.failed ? 'bad' : pg.busy ? 'run' : 'ok'}
          /* 状态词在前，阶段在后。停下来的时候「停在哪」和「已停止」一样重要 */
          title={pg.failed ? `失败 · ${pg.stage}`
            : pg.busy ? pg.stage : `${pg.stage} · 已停止`}
          bar={pct !== null ? { cur: pg.stageCur, total: pg.stageTotal } : null}
          detail={
            <>
              {/* 每个分母都用那一步自己的口径：④ 只做 ④c 选中的题，
                  ⑤ 只做自检通过的题。拿题数当分母的话，一份跑完的卷子会显示成
                  「断言 6/16」，像是没做完 */}
              <span className="prog-sub">
                <span>解题 {pg.solutions + failureCount}/{pg.questions}</span>
                {failureCount > 0 && <span className="prog-fail">失败 {failureCount}</span>}
                <span>选题 {pg.judged}/{pg.solutions}</span>
                <span>断言 {pg.specsWorth}{pg.worth ? `/${pg.worth}` : ''}</span>
                <span>自检 {pg.approved}/{pg.specs}</span>
                <span>动画 {pg.scenes}{pg.ready ? `/${pg.ready}` : ''}</span>
                {pg.elapsedSeconds !== null && <span className="prog-t">
                  {pg.assembled ? '总耗时' : '已用时'} {fmtDur(pg.elapsedSeconds)}
                </span>}
              </span>
              {pg.failed && <code className="prog-last">{pg.failed}</code>}
              {resumeNote && <code className="prog-last">{resumeNote}</code>}
              {pg.step && (
                <code className="prog-last">
                  {pg.step}{pg.last ? ` · ${pg.last.trim()}` : ''}
                </code>
              )}
            </>
          }
          /* 停下来的卷子给一个「继续执行」。最常见的停法是后端重启：驱动整条链
             的线程随进程没了，库里的数据是好的，只是没人接着往下走。
             跑完的卷子不给 —— 那时点它只会白等一圈。 */
          actions={!pg.busy && !pg.done ? (
            <button className="btn" disabled={resuming} onClick={onResume}>
              {resuming ? '正在启动…' : '继续执行'}
            </button>
          ) : undefined}
        />
      )}

      {failedQuestions.length > 0 && (
        <div className="banner bad solve-fail-summary">
          <b>有 {failedQuestions.length} 道题生成失败</b>
          <ul>{failedQuestions.map((q) => (
            <li key={q.n}>
              <button type="button" onClick={() => jumpTo(q.n)}>第 {q.n} 题</button>
              <span>{q.solutionFailure!.reason}</span>
            </li>
          ))}</ul>
        </div>
      )}

      <Metrics>
        <MetricCard value={stats.n} label="题" />
        {stats.points > 0 && <MetricCard value={stats.points} label="分" />}
        <MetricCard value={`${paper.coverage.solved}/${paper.coverage.total}`}
                    label="已解题"
                    tone={paper.coverage.failed > 0 ? 'bad' : 'plain'} />
        <MetricCard value={stats.scenes} label="题有动画"
                    tone={stats.scenes > 0 ? 'ok' : 'plain'} />
        {stats.minutes > 0 && (
          <MetricCard value={stats.minutes} label="分钟"
                      hint="按分值估算（100 分 / 75 分钟），不是原卷标注" />
        )}
        {pg?.elapsedSeconds != null && (
          <MetricCard value={fmtDur(pg.elapsedSeconds)}
                      label={pg.assembled ? '总耗时' : '已用时'}
                      hint="从这一轮上传开始，到 ⑦ 装配完成为止" />
        )}
        {/* 投屏讲解时一键控制全卷。**只在真有动画时出现** */}
        {stats.scenes > 0 && (
          <div className="metrics-act">
            <button className="btn" onClick={toggleAll}>
              {playing ? '⏸ 全部暂停' : '▶ 全部播放'}
            </button>
          </div>
        )}
      </Metrics>

      {paper.warnings.length > 0 && (
        <div className="banner bad">
          <b>切分告警 {paper.warnings.length} 条</b>
          <ul>{paper.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      <div className="pgrid">
        <PaperSidebar
          name={paper.name} count={stats.n} onJump={jumpTo}
          groups={stats.groups.map(([sec, qs]) => [sec, qs.map((q) => {
            const a = shortOf(q)
            // 目录这一列窄，只放真答案和终态失败；其余中间态留白
            return { n: q.n, label: q.label,
                     answer: a.kind === 'short' || a.kind === 'raw' || a.kind === 'failed'
                       ? a.text : '' }
          })])} />

        <div className="pmain">
          <details className="quick" open>
            <summary>答案速览</summary>
            <div className="quick-g">
              {paper.questions.map((q) => {
                const a = shortOf(q)
                return (
                  <button key={q.n} className="quick-c" onClick={() => jumpTo(q.n)}>
                    <span className="quick-h">
                      {String(q.n).padStart(2, '0')} {q.type}
                    </span>
                    <span className={`quick-a${a.kind === 'failed' ? ' failed'
                      : a.kind === 'short' || a.kind === 'raw' ? '' : ' none'}`}
                          title={a.kind === 'failed' ? q.solutionFailure?.reason
                            : a.kind === 'pending'
                              ? '③b 目录会把它压成一行，点开看完整解法' : ''}>
                      {a.text}
                    </span>
                  </button>
                )
              })}
            </div>
          </details>

          {!scenesReady ? <div className="empty"><b>载入动画场景…</b></div>
            : paper.questions.map((q) => {
              const head = q.section !== lastSection ? (lastSection = q.section) : null
              const cnt = head ? paper.questions.filter((x) => x.section === head).length : 0
              return (
                <div key={q.n}>
                  {head && (
                    <div className="sec">
                      <h3>{head}</h3><span>{cnt} 题</span>
                    </div>
                  )}
                  {/* 重跑成功后调 load()：它重取试卷（拿到新的 sceneId），
                      而 paper 身份一变，上面那个场景脚本 effect 会跟着重跑、
                      带新时间戳重新加载 scene.js —— 新动画才真的换得上去 */}
                  <QuestionCard q={q} paper={name}
                                sourceKind={paper.sourceKind} onRescened={load} />
                </div>
              )
            })}
        </div>
      </div>

      {/* 整卷读完时再说一次「这是模型写的」。每道题头上那排 pill 已经逐题标了，
          但那是读到某一题时才看见的；一路翻到底的人需要在结尾也被提醒一次。
          措辞不能softening成「仅供参考」——要具体说清门禁验的是什么、验不了什么 */}
      <footer className="ai-note">
        答案、解题步骤与动画均由 AI 生成，<b>未经人工审核</b>。动画通过的是程序化的物理断言门禁，
        它只能排除自相矛盾，排不掉「从一开始就理解错题」。请对照原卷自行甄别后使用。
      </footer>
    </div>
  )
}
