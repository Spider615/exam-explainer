import { useCallback, useEffect, useMemo, useState } from 'react'
import { getPaper, getProgress, sceneScriptUrl } from '../api'
import QuestionCard from './QuestionCard'
import type { Paper, Progress, Question } from '../types'

export const STAGE_LABEL: [string, string][] = [
  ['ingest', '① 摄入'], ['segment', '② 切分'], ['solve', '③ 解题'],
  ['spec', '④ 断言'], ['scene', '⑤ 场景'], ['assemble', '⑦ 呈现'],
]

/**
 * 后端的阶段代号 → 上面这排标志里的哪一格。
 *
 * ③b 目录、④b 自检、④c 选题都是子步骤，没有自己的标志位，归到所属的大阶段上。
 * 少了这张表，跑 ④c 选题的时候整排标志会一个都不亮，看着像卡死了。
 *
 * `ingest` / `segment` 这两条 **`stage_of` 永远不会返回**（它是从库里的计数反推的，
 * 而卷子入了库就意味着 ①② 已经过去了），但 `failedStage` 会 —— 管线在 ① 摄入或
 * ② 切分挂掉时给的正是它们。漏了这两条，那两步的失败查表得到 undefined，
 * 于是失败**一格都不红**，只剩下面那条横幅。
 */
const STAGE_OF_CODE: Record<string, string> = {
  ingest: 'ingest', segment: 'segment',
  solve: 'solve', outline: 'solve',
  pick: 'spec', spec: 'spec', check: 'spec',
  scene: 'scene', assemble: 'assemble',
}

type StageState = 'done' | 'now' | 'todo' | 'fail' | 'empty'

/**
 * 这两格在库外还有一份「产物到底存不存在」的事实，**两个方向都由它说了算**。
 *
 * `stage_of` 推的是「按管线顺序，第一个没做完的环节」。它只能回答走没走过去，
 * 回答不了走过去之后有没有东西留下来 —— 而这两步恰恰两头都会错：
 *
 * **推断说做完了，其实什么都没留下**
 * - ⑤：`sceneTried` 数的是**试过几道**（数绿灯的话，有一道怎么都过不了门禁就
 *   永远差一个、永远显示在跑）。六道全试过、门禁一个都没过时计数照样往前走，
 *   于是「一个动画都没做出来」被画成「⑤ 做完了」。
 * - ⑦：`assembledFresh` 只比时间戳，不看 out.html 还在不在磁盘上。
 *
 * **推断说还没轮到，其实早就跑过了**（三段切分假设管线是单调跑一遍的，可它不是）
 * 实测库里九份卷子有三份是这个样子：2024 河北卷 `stage_of` 停在 ③（还有题没解
 * 出来），而 ⑤ 早跑过、两个动画正在这个页面上播着；2023 重庆卷停在 ④c，⑤ 有五
 * 个绿灯。照三段切分画出来，⑤ 是一个虚线框写着「还没跑到这一步」，而人眼前就有
 * 动画在动。
 *
 * `paper.stages` 这两格是查过产物的（scenes 只收门禁通过的，assemble 还带一次
 * os.path.exists），所以两边都听它的。**其余几格不能这么办**：`stages.solve` 是
 * 「解出过至少一题」、`stages.spec` 是「写过至少一份断言」，拿它们判完成正是这次
 * 要修掉的老毛病 —— 解了 5/15 和真做完长得一模一样。
 */
const NEEDS_ARTIFACT = new Set(['scene', 'assemble'])

/**
 * 每一格标志此刻是什么状态。
 *
 * **按管线位置推断，不看 `paper.stages` 那个布尔。** 那个布尔的口径是「有没有
 * 产物」：解出一题 `solve` 就是 true —— 于是一份只解了 5/15 的卷子，③ 和真做完了
 * 的 ①② 长得一模一样，「亮着」被读成「做完了」。
 *
 * 后端的 `stage_of` 已经按管线顺序推出了「第一个没做完的环节」，拿它把这排标志切
 * 三段就够了：它之前的做完了，它本身在跑，它之后的还没轮到。轮询还没回来时才退回
 * 布尔兜底 —— 那时候只知道有没有产物，也只能说这么多。
 *
 * 两处例外见 `NEEDS_ARTIFACT`（跑过去了但没产物）和 `failAt`（失败只画在它自己
 * 那一格上，而不是画在「当前这一格」上）。
 */
export function stageStates(paper: Paper, pg: Progress | null): Record<string, StageState> {
  const cur = pg && !pg.done ? STAGE_OF_CODE[pg.stageCode] : null
  const at = cur ? STAGE_LABEL.findIndex(([k]) => k === cur) : -1
  // 失败画在**它自己那一格**上。原来是画在「当前阶段」那一格，而后端那条失败
  // 记录既没有时间窗也不带阶段（JOBS 不清理、命令行补跑又进不去），于是 ⑤ 正在
  // 正常出动画时那格也是红的、写着「②b 公式识别 失败」。
  // 后端给不出阶段代号时一格都不画 —— 那条信息改由下面的横幅整条说出来。
  const failAt = pg?.failed && pg.failedStage ? STAGE_OF_CODE[pg.failedStage] : null
  const out: Record<string, StageState> = {}
  STAGE_LABEL.forEach(([k], i) => {
    let st: StageState
    if (k === failAt) st = 'fail'
    else if (pg?.done) st = 'done'
    else if (at < 0) st = paper.stages[k] ? 'done' : 'todo'
    else if (i < at) st = 'done'
    else if (i > at) st = 'todo'
    else st = 'now'
    if (NEEDS_ARTIFACT.has(k) && st !== 'now' && st !== 'fail') {
      // 产物在 —— 不管推断走到哪一步了，这一格就是有东西的
      if (paper.stages[k]) st = 'done'
      // 推断说走过去了，可什么都没留下。既不是「完成」，也不是「还没轮到」
      else if (st === 'done') st = 'empty'
    }
    out[k] = st
  })
  return out
}

/**
 * 跳到某一题。
 *
 * **不能用 `<a href="#q3">`。** 整个 App 是 hash 路由（`#/p/<卷名>`），
 * 改 hash 会被路由当成「回到试卷库」，点一下目录直接把当前卷子关掉。
 * 所以目录一律是 button + scrollIntoView，不碰 location.hash。
 */
function jumpTo(n: number) {
  document.getElementById(`q${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 秒 → 「1 小时 4 分」。整条链动辄一小时，只显示秒数没人读得出来 */
function fmtDur(sec: number) {
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分 ${s % 60} 秒`
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`
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
 * 所以分四种：
 *   short    ③b 压好的一行答案
 *   raw      还没压，但完整答案本身就短（选择题的 `D`、多空的 `小于,等于,小于`）
 *            —— 整条显示，**不截断**。截一段得到的是「(1) α=30°，U_MN=3mv…」，
 *            既不完整也不好看，不如不给
 *   pending  已解出，但答案是一长串三问，等 ③b 压
 *   none     真的还没解
 */
function shortOf(q: Question): { text: string; kind: 'short' | 'raw' | 'pending' | 'none' } {
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
        const key = [p.solutions, p.labels, p.specs, p.judged, p.scenes,
                     p.assembled].join('-')
        if (seen && key !== seen) load()      // 有新东西落库了，把整卷重新拉一遍
        seen = key
      } catch { /* 服务重启中之类，下一轮再说 */ }
      // 在跑就盯紧点，跑完了就放慢——没必要为一份静止的卷子每三秒打一次
      if (alive) timer = window.setTimeout(tick, pg?.busy === false ? 15000 : 3000)
    }
    timer = window.setTimeout(tick, 300)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [name, load, pg?.busy])

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
  const states = stageStates(paper, pg)
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
        {STAGE_LABEL.map(([k, label]) => {
          const st = states[k]
          const stalled = st === 'now' && pg != null && !pg.busy
          const why = st === 'fail' ? `失败：${pg?.failed}`
            : st === 'empty' ? '这一步跑过了，但没有产出'
              : stalled ? '停在这一步，还没做完'
                : st === 'now' ? '正在跑这一步'
                  : st === 'done' ? '已完成'
                    // ④ 的布尔是「写过至少一份断言」，判不出完成度，所以它照旧
                    // 按推断画 —— 但话不能说成「还没跑到」，库里明明有东西
                    : paper.stages[k] ? '这一轮还没跑到这一步（库里已经有一些产出）'
                      : '还没跑到这一步'
          return (
            <span key={k} className={`stage st-${st}${stalled ? ' idle' : ''}`}
                  title={[why, paper.stageNotes?.[k]].filter(Boolean).join(' · ')}>
              {st === 'now' && <i className="stage-dot" />}
              {label}
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
        <div className={`prog${pg.busy ? '' : ' idle'}`}>
          <div className="prog-hd">
            <span className="prog-dot" />
            {/* 状态词在前，阶段在后。停下来的时候「停在哪」和「已停止」一样重要 */}
            <b>{pg.failed ? `失败 · ${pg.stage}`
              : pg.busy ? pg.stage
                : `${pg.stage} · 已停止`}</b>
            {pct !== null && (
              <span className="prog-num">{pg.stageCur}/{pg.stageTotal}</span>
            )}
          </div>
          {pct !== null && (
            <div className="prog-bar"><i style={{ width: `${pct}%` }} /></div>
          )}
          {pg.failed && <code className="prog-last">{pg.failed}</code>}
          {/* 每个分母都用那一步自己的口径：④ 只做 ④c 选中的题，⑤ 只做自检通过的题。
              拿题数当分母的话，一份跑完的卷子会显示成「断言 6/16」，像是没做完 */}
          <div className="prog-sub">
            <span>解题 {pg.solutions}/{pg.questions}</span>
            <span>选题 {pg.judged}/{pg.solutions}</span>
            <span>断言 {pg.specsWorth}{pg.worth ? `/${pg.worth}` : ''}</span>
            <span>自检 {pg.approved}/{pg.specs}</span>
            <span>动画 {pg.scenes}{pg.ready ? `/${pg.ready}` : ''}</span>
            {pg.elapsedSeconds !== null && <span className="prog-t">
              {pg.assembled ? '总耗时' : '已用时'} {fmtDur(pg.elapsedSeconds)}
            </span>}
          </div>
          {pg.step && <code className="prog-last">{pg.step}{pg.last ? ` · ${pg.last.trim()}` : ''}</code>}
        </div>
      )}

      <div className="facts">
        <div className="fact"><b>{stats.n}</b><span>题</span></div>
        {stats.points > 0 && <div className="fact"><b>{stats.points}</b><span>分</span></div>}
        <div className="fact">
          <b>{stats.groups.map(([, v]) => v.length).join(' + ')}</b>
          <span>{stats.groups.map(([k]) => k.split('、').pop()).join(' / ')}</span>
        </div>
        {stats.minutes > 0 && (
          <div className="fact" title="按分值估算（100 分 / 75 分钟），不是原卷标注">
            <b>{stats.minutes}</b><span>分钟 · 估</span>
          </div>
        )}
        <div className="fact"><b>{paper.coverage.solved}/{paper.coverage.total}</b>
          <span>已解题</span></div>
        {pg?.elapsedSeconds != null && (
          <div className="fact" title="从这一轮上传开始，到 ⑦ 装配完成为止">
            <b>{fmtDur(pg.elapsedSeconds)}</b>
            <span>{pg.assembled ? '总耗时' : '已用时'}</span>
          </div>
        )}
        {stats.scenes > 0 && (
          <div className="fact fact-act">
            <button className="btn" onClick={toggleAll}>
              {playing ? '⏸ 全部暂停' : '▶ 全部播放'}
            </button>
            <span>{stats.scenes} 张图为动画</span>
          </div>
        )}
      </div>

      {paper.warnings.length > 0 && (
        <div className="banner bad">
          <b>切分告警 {paper.warnings.length} 条</b>
          <ul>{paper.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      <div className="pgrid">
        <nav className="toc">
          {stats.groups.map(([sec, qs]) => (
            <div key={sec} className="toc-g">
              <h4>{sec.includes('、') ? sec.split('、').pop() : sec}</h4>
              {qs.map((q) => {
                const a = shortOf(q)
                return (
                  <button key={q.n} className="toc-i" onClick={() => jumpTo(q.n)}>
                    <span className="toc-n">{String(q.n).padStart(2, '0')}</span>
                    <span className="toc-l">{q.label || ''}</span>
                    {/* 目录这一列窄，只放真答案；「待压缩」「尚未生成」留白 */}
                    <span className="toc-a">
                      {a.kind === 'short' || a.kind === 'raw' ? a.text : ''}
                    </span>
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="pmain">
          <div className="quick">
            <h4>答案速览</h4>
            <div className="quick-g">
              {paper.questions.map((q) => {
                const a = shortOf(q)
                return (
                  <button key={q.n} className="quick-c" onClick={() => jumpTo(q.n)}>
                    <span className="quick-h">
                      {String(q.n).padStart(2, '0')} {q.type}
                    </span>
                    <span className={`quick-a${a.kind === 'short' || a.kind === 'raw' ? '' : ' none'}`}
                          title={a.kind === 'pending' ? '③b 目录会把它压成一行，点开看完整解法' : ''}>
                      {a.text}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {!scenesReady ? <div className="empty">载入动画场景…</div>
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
                  <QuestionCard q={q} paper={name} onRescened={load} />
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
