import { useCallback, useEffect, useState } from 'react'
import { ApiError, getPaper, getProgress } from '../api'
import AnswerQuestionCard, { mainOf } from './AnswerQuestionCard'
import { fmtDur } from '../fmt'
import JobProgress from './JobProgress'
import MetricCard, { Metrics } from './MetricCard'
import PageIntro from './PageIntro'
import Sheets from './Sheets'
import type { Paper, Progress } from '../types'

/**
 * 答题卡模式的详情页。
 *
 * **和 PaperView 是两个组件。** 这边没有动画、没有目录、没有答案速览、
 * 没有「n 张图为动画」，页脚那句免责也完全不同 —— 这边的标准答案和解答过程
 * 来自老师给的参考答案，**不是 AI 生成的**，AI 生成的只有知识点标签。
 */
export default function SheetView({ name, onOpenSheet }: {
  name: string
  /** 点开一份答题卡 */
  onOpenSheet: (id: number) => void
}) {
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
  /**
   * 那条进度条的分子分母。两步各有各的口径，**不能共用一个**：
   *
   * Ⓐ 的分母是**页数**（一页一分钟上下），由后端从 refread 的输出里抠出来；
   * ③c 的分母是**题数**。硬拿 `stageCur/stageTotal` 画的话，Ⓐ 那一步永远是
   * 0/1 —— 一个从头到尾不动的条，比没有还糟。
   *
   * 两样都拿不到就不画条，只留状态词和日志：**宁可不画，也不画一个假的**。
   */
  const bar = pg?.stageCode === 'refread'
    ? (pg.pageTotal ? { cur: pg.pageDone ?? 0, total: pg.pageTotal, unit: '页' } : null)
    : pg?.stageCode === 'kpmark'
      // 分子是「判过几道」不是「挂上几道」—— 只有一个字母答案的题永远挂不上，
      // 按挂上几道画的话，这条进度条永远走不到头
      ? { cur: pg.kpsJudged ?? pg.kps, total: pg.questions, unit: '题判过' }
      : null
  const groups: [number, typeof qs][] = []
  for (const q of qs) {
    const m = mainOf(q.n)
    const last = groups[groups.length - 1]
    if (last && last[0] === m) last[1].push(q)
    else groups.push([m, [q]])
  }
  const withSolution = qs.filter((q) => q.refSolution).length
  const withKps = qs.filter((q) => q.kps?.length).length

  return (
    <div className="rise">
      <PageIntro title={paper.name}
                 lede="这份卷子的标准答案与知识点。传一份已经批改的答题卡上来，
                       就能逐题看对错、丢分和该补什么。" />

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

      {/* 跑着的时候要说清楚跑到哪了。
          没有这块的时候，Ⓐ 那几分钟里这一屏只有一个转不停的呼吸点和三个 0 ——
          用户原话：「都看不到读取到哪一题了，什么进度都看不到啊」。
          停下来（busy=false 但没跑完）也要画，而且要说「已停止」——
          光把进度条画在那儿，人分不出「在跑」和「停了」。 */}
      {pg && (pg.busy || !pg.done) && (
        <JobProgress
          tone={pg.failed ? 'bad' : pg.busy ? 'run' : 'ok'}
          title={pg.failed ? `失败 · ${pg.stage}`
            : pg.busy ? pg.stage : `${pg.stage} · 已停止`}
          bar={bar ? { cur: bar.cur, total: bar.total } : null}
          detail={
            <>
              {bar && <span className="prog-sub"><span>{bar.cur}/{bar.total} {bar.unit}</span>
                {pg.elapsedSeconds != null && (
                  <span className="prog-t">已用时 {fmtDur(pg.elapsedSeconds)}</span>
                )}</span>}
              {/* 最后一行日志。Ⓐ 每读完一页打一条「第2页 读到 20 条（到第14(2)题）」，
                  这句话恰好回答了「读到哪一题了」—— 比进度条本身还有用 */}
              {pg.step && (
                <code className="prog-last">
                  {pg.step}{pg.last ? ` · ${pg.last.trim()}` : ''}
                </code>
              )}
              {!pg.busy && !pg.done && (
                <code className="prog-last">
                  没有进程在动。参考答案没读完的话，重新上传一次就行 ——
                  这一步不支持接着跑（上传的原件跑完就收掉了）。
                </code>
              )}
            </>
          }
        />
      )}

      <Metrics>
        <MetricCard value={qs.length} label="题" />
        {/* 「带解答」天生小于题数，把原因说清楚，免得被当成漏读 */}
        <MetricCard value={withSolution} label="题带官方解答"
                    hint="参考答案的版式就是只有大题给解答过程" />
        <MetricCard value={withKps} label="题挂了知识点"
                    tone={withKps < qs.length ? 'plain' : 'ok'} />
        <MetricCard value={paper.sheets?.length ?? 0} label="份答题卡"
                    tone={(paper.sheets?.length ?? 0) > 0 ? 'ok' : 'plain'} />
      </Metrics>

      {/* ③c 判完了、但有题挂不上，要**明说**。
          阶段格子打了勾，人很容易读成「26 道都挂上了」；而这里挂不上的原因是
          具体且可解的（缺题干），说出来才知道下一步该做什么 —— 不说的话
          只剩一堆「这道题没挂上知识点」，看着像模型不行 */}
      {pg?.done && withKps < qs.length && (
        <div className="banner">
          {/* 这个全角空格是**排版**，不是笔误：JSX 会把元素和下一行文字之间的
              换行整个吃掉，不留空格 —— 少了它，页面上是「没挂上知识点它们的」 */}
          <b>{qs.length - withKps} 道题没挂上知识点</b>{'　'}
          它们的参考答案只有一个字母或一个数（`D`、`BC`、`170 / A`），
          判不出考什么 —— 这不是漏读，是那个答案里真的不含这个信息。
          {qs.some((q) => q.stem)
            ? '这几道连题干都有了还挂不上，多半是题干本身没读全 —— 换清楚一点的原卷图重传一次。'
            : '要挂上得有题干：把原卷传进「原卷」那一栏，重新上传一次就会连题干一起读。'}
        </div>
      )}

      {/* 这份卷子下面的答题卡。**按卡画，不占上面那排格子** —— 一份卷子可以挂
          多份卡（一个学生一份），而那排格子是按卷子算的，装不下「哪一份卡读到
          第几题」；更糟的是没传答题卡的卷子会永远走不到「已完成」。
          详见 pipeline/modes.py 里 _stage_of_sheet 的说明 */}
      <Sheets paper={name} rows={paper.sheets ?? []} onOpen={onOpenSheet} />

      {/* **按大题分组，不逐小问渲染。** 第 13 题的 4 个小问共用同一段题干、
          同一张原卷截图 —— 逐条渲染的话那张整页宽的截图会被重复贴 4 遍，
          屏幕上翻半天还在同一道题里。标准答案和知识点是逐小问不同的，
          那两样留在小问上（13(4) 挂的是「误差与有效数字」，13(1) 不是）。
          `questions` 已经按题号排好（get_paper 的 ORDER BY q.n），
          所以顺着扫一遍就能分组，不用先排序 */}
      {groups.map(([main, parts]) => (
        <AnswerQuestionCard key={main} main={main} parts={parts} />
      ))}

      {/* 话术和解析试卷完全不同：这边的答案是老师给的，不是 AI 算的。
          最后那句「还缺什么」**必须跟着卷子实际有什么变**：写死的话，Ⓔ 读题干
          做完之后它还在说「这份卷子还没有题干」，而页面上明明每道题都贴着原卷
          截图 —— 页脚是这一屏唯一交代「哪些东西还没有」的地方，它撒谎比不写更糟 */}
      <footer className="ai-note">
        标准答案与解答过程<b>来自你上传的参考答案</b>，由视觉模型逐页转写，
        可能有转写错误，请对照原件核对。知识点标签由 AI 生成，未经人工审核。
        {qs.some((q) => q.stemImage || q.stem)
          ? '题目来自你上传的原卷。'
          : '这份卷子还没有题目 —— 把原卷传进「原卷」那一栏就能读到。'}
        {/* **这句话必须跟着卷子实际有什么变。** 原来这里写死「还没有学生的
            答题卡」—— 而答题卡功能做完之后，一份挂着三个学生的卷子页脚上
            照样这么说。页脚是这一屏唯一交代「哪些东西还没有」的地方，
            它撒谎比不写更糟（同一个坑上一轮已经补过一次，见 ee93d32） */}
        {paper.sheets?.length
          ? `已经有 ${paper.sheets.length} 份学生答题卡，逐题对错来自老师的批改。`
          : '还没有学生的答题卡。'}
      </footer>
    </div>
  )
}
