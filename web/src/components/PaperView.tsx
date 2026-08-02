import { useCallback, useEffect, useMemo, useState } from 'react'
import { getPaper, getProgress, sceneScriptUrl } from '../api'
import QuestionCard from './QuestionCard'
import type { Paper, Progress, Question } from '../types'

const STAGE_LABEL: [string, string][] = [
  ['ingest', '① 摄入'], ['segment', '② 切分'], ['solve', '③ 解题'],
  ['spec', '④ 断言'], ['scene', '⑤ 场景'], ['assemble', '⑦ 呈现'],
]

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

/** 速览/目录里那一格答案。③b 没给就留空 —— 不拿完整答案截一段来充数 */
function shortOf(q: Question) {
  return q.solution?.shortAnswer?.trim() || ''
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
  const toggleAll = () => {
    const next = !playing
    setPlaying(next)
    window.dispatchEvent(new CustomEvent<boolean>('scenes:playing', { detail: next }))
  }

  let lastSection: string | null = null
  return (
    <div>
      <div className="stages">
        {STAGE_LABEL.map(([k, label]) => (
          <span key={k} className={`stage ${paper.stages[k] ? 'on' : 'off'}`}
                title={paper.stageNotes?.[k] ?? ''}>{label}</span>
        ))}
      </div>

      {pg && (pg.busy || !pg.assembled) && (
        <div className={`prog${pg.busy ? '' : ' idle'}`}>
          <div className="prog-hd">
            <span className="prog-dot" />
            <b>{pg.busy ? pg.stage : `${pg.stage} · 已停止`}</b>
            {pct !== null && (
              <span className="prog-num">{pg.stageCur}/{pg.stageTotal}</span>
            )}
          </div>
          {pct !== null && (
            <div className="prog-bar"><i style={{ width: `${pct}%` }} /></div>
          )}
          <div className="prog-sub">
            <span>解题 {pg.solutions}/{pg.questions}</span>
            <span>断言 {pg.specs}</span>
            <span>自检 {pg.judged}</span>
            <span>动画 {pg.scenes}{pg.worth ? `/${pg.worth}` : ''}</span>
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

      <div className="note">
        <b>这是一条竖切片，不是完整产品。</b>　上传一份 PDF 会自动跑完
        ① 摄入 → ② 切分 → ③ 解题 → ③b 目录 → ④ 写断言 → ④b 自检 → ⑤ 生成场景 → ⑦ 呈现，
        上面每个标志亮着才算真跑过（鼠标停上去能看到灭着的原因）。
        <b>动画的准入靠的是计算，不是人审</b>：④b 拿 spec 自带的参考实现跑一遍，
        满足不了它自己的断言就不进 ⑤。这只排除内部矛盾 ——
        解法要是从一开始就理解错题、而断言写得自洽，这一关照样全绿。
        所以解题与断言都请对照原卷判断。
      </div>

      <div className="pgrid">
        <nav className="toc">
          {stats.groups.map(([sec, qs]) => (
            <div key={sec} className="toc-g">
              <h4>{sec.includes('、') ? sec.split('、').pop() : sec}</h4>
              {qs.map((q) => (
                <button key={q.n} className="toc-i" onClick={() => jumpTo(q.n)}>
                  <span className="toc-n">{String(q.n).padStart(2, '0')}</span>
                  <span className="toc-l">{q.label || ''}</span>
                  <span className="toc-a">{shortOf(q)}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="pmain">
          <div className="quick">
            <h4>答案速览</h4>
            <div className="quick-g">
              {paper.questions.map((q) => (
                <button key={q.n} className="quick-c" onClick={() => jumpTo(q.n)}>
                  <span className="quick-h">
                    {String(q.n).padStart(2, '0')} {q.type}
                  </span>
                  <span className={`quick-a${shortOf(q) ? '' : ' none'}`}>
                    {shortOf(q) || '尚未生成'}
                  </span>
                </button>
              ))}
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
                  <QuestionCard q={q} paper={name} />
                </div>
              )
            })}
        </div>
      </div>
    </div>
  )
}
