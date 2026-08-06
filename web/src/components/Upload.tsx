import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getJob, getProgress, Unauthorized, uploadPdf } from '../api'
import type { Job } from '../types'

/**
 * 正在跑的那个上传任务，记在 localStorage 里。
 *
 * **为什么非记不可**：上传后的头几分钟（① 摄入、② 切分、②b 公式）卷子还没入库，
 * 那段时间除了这个组件里的一份内存状态，整个页面再没有第二个地方知道它在跑 ——
 * 试卷库里查不到它，进度端点也查不到。刷新一下就全丢：拖拽框回到初始样子，
 * 看起来像什么都没发生过，而后台那条线程其实还在跑。
 *
 * **入库那一刻就把它扔掉。** 从 `solving` 起卷子已经在库里了，试卷库那一行和
 * 试卷页的进度带都能从库里算出它跑到哪 —— 库是唯一真相源，这个句柄的活干完了。
 * 留着它只会制造假象：跳进试卷页时这个组件就卸载了，`done` 那一幕它根本看不到，
 * 于是句柄一直留着，等后端某次重启后再回到这一屏，它会对着一份**早已跑完**的
 * 卷子喊「进度接不上了，重新上传同一份 PDF 就行」，把整条 ①→⑦ 白跑一遍。
 *
 * 只有一种情况要留：**卷子还没入库就失败了**。那时候库里什么都没有，这条句柄
 * 是页面上唯一还记得这件事的东西。
 */
const KEY = 'ee.upload.job'

/** name 是可选的：早先版本存过只有 id 的句柄，捡回来照样能轮询，只是问不了库 */
interface Saved { id: string; name?: string }

function loadSaved(): Saved | null {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || 'null')
    return s && typeof s.id === 'string' ? s as Saved : null
  } catch { return null }
}

function saveJob(s: Saved | null) {
  // 无痕模式之类存不下就算了 —— 存不下顶多是刷新后接不上，不该因此挡住上传
  try { s ? localStorage.setItem(KEY, JSON.stringify(s)) : localStorage.removeItem(KEY) }
  catch { /* 忽略 */ }
}

/** 会话结束（登出或过期）时清掉：句柄跟着会话作废，不留给下一个登进来的人 */
export const clearSavedJob = () => saveJob(null)

/**
 * 句柄打不开了，**先去库里问一句真相**，再决定跟人怎么说。
 *
 * `/api/jobs` 的 404 有三个来源，而且后端是**有意**让它们长得一样的（分开回答
 * 的话，拿一批 id 去试就能问出别人在跑什么）：任务不存在（后端重启过）、任务
 * 不是你的、id 本身是坏的。只看状态码就写死一句「后端重启过」，三次里至少两次
 * 在撒谎 —— 而库知道得多得多，问它一次就够。
 */
async function explainLost(name?: string): Promise<string> {
  if (!name) return '上一次上传的任务句柄失效了。它跑到哪一步，去试卷库里看。'
  try {
    const p = await getProgress(name)
    if (p.done) return `「${name}」已经跑完了，这条上传记录是旧的，已经清掉 —— 去试卷库里看它。`
    if (p.failed) return `「${name}」上一次没跑完：${p.failed}`
    return `「${name}」的任务句柄没了（后端重启过），但卷子还在库里，停在「${p.stage}」。`
      + '想接着往下跑，重新上传同一份 PDF 就行 —— 卷名不变，等于重跑。'
  } catch {
    return `上一次上传的「${name}」没有入库，它在 ①/② 那几步就断了（后端重启，或者管线失败）。`
      + '重新上传同一份 PDF 再试一次。'
  }
}

export default function Upload({ onDone }: {
  /** open=true 才跳进试卷页。刷新后接上的那次不能跳 —— 人是自己停在这一屏的 */
  onDone: (name: string, open: boolean) => void
}) {
  const [hot, setHot] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  /** **只表示「这一次的 POST /api/upload 还在飞」**，不表示后台那条管线在跑 */
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [lost, setLost] = useState<string | null>(null)
  /** 连着几轮问不到后端了。0 表示一切正常 */
  const [retry, setRetry] = useState(0)
  const pick = useRef<HTMLInputElement>(null)
  /**
   * 此刻该盯着哪个任务。**换任务用抢的，不是用挡的**：原来这里是一个布尔守卫
   * （已经有循环在跑就直接 return），于是传第二份卷子时新任务被静默吞掉 ——
   * 句柄已经换成新的，循环却还盯着旧的，旧的一跑完还把新句柄一起清了。
   */
  const watching = useRef<string | null>(null)
  // 跳进试卷页时这个组件会卸载，循环得跟着停 —— 否则回到试卷库再挂载一次，
  // 就有两条循环在打同一个任务
  const alive = useRef(true)

  /**
   * 盯着一个任务直到它收场。上传完接上去、刷新后也接上去，是同一段循环。
   *
   * 出错分三种，处理方式完全不同：401 交给 App 去退登录页；404 是句柄打不开了
   * （去库里问清楚再说话）；其余（网络抖动、后端重启中、代理 502）**不能当成
   * 任务没了** —— 停一下接着问，但要**把「问不到」说出来**：不说的话，界面和
   * 「正在后台解题」一模一样，人会一直等下去。
   */
  const follow = useCallback(async (id: string, name: string | undefined, navigate: boolean) => {
    if (watching.current === id) return
    watching.current = id                 // 抢过来，旧循环下一轮自己退出
    setLost(null); setRetry(0)
    let announced = false
    let cleared = false
    let miss = 0
    try {
      for (;;) {
        if (!alive.current || watching.current !== id) return
        let j: Job
        try {
          j = await getJob(id)
        } catch (e) {
          if (e instanceof Unauthorized) return          // App 会退回登录页
          if (e instanceof ApiError && e.status === 404) {
            saveJob(null); setJob(null)
            setLost(await explainLost(name))
            return
          }
          miss += 1
          setRetry(miss)
          // 退避到 15 秒封顶：后端重启一次要几秒，隧道断了可能要几分钟
          await new Promise((r) => setTimeout(r, Math.min(3000 * miss, 15000)))
          continue
        }
        if (!alive.current || watching.current !== id) return
        miss = 0; setRetry(0)
        setJob(j)
        // 入库了：卷子在试卷库里冒出来了，外面要把列表刷一遍才看得见。
        // **`error` 不算入库** —— 后端建任务时就写死了 name，管线在 ①/② 挂掉时
        // name 照样有值而卷子根本不存在，跳过去只会得到一句「打不开」，
        // 而真正的失败原因随着这个组件卸载一起消失
        const inDb = j.state === 'solving' || j.state === 'finishing' || j.state === 'done'
        if (inDb && !cleared) { cleared = true; saveJob(null) }
        if (inDb && !announced && j.name) {
          announced = true
          onDone(j.name, navigate)
        }
        if (j.state === 'done' || j.state === 'error') {
          if (inDb && j.name) onDone(j.name, false)
          break
        }
        // running 是入库前那几分钟，值得盯紧；之后一步几分钟起，没必要
        await new Promise((r) => setTimeout(r, j.state === 'running' ? 600 : 4000))
      }
    } finally {
      if (watching.current === id) watching.current = null
    }
  }, [onDone])

  // 进这一屏就看看有没有没跑完的任务要接上
  useEffect(() => {
    alive.current = true
    const s = loadSaved()
    if (s) void follow(s.id, s.name, false)
    return () => { alive.current = false }
  }, [follow])

  async function send(file: File) {
    if (!/\.pdf$/i.test(file.name)) { setErr('只接受 PDF 文件'); return }
    setErr(null); setLost(null); setSending(true)
    setJob({ state: 'running', step: '上传中', log: [`上传 ${file.name}…`] })
    let started: { id: string; name: string } | null = null
    try {
      const { job: id, name } = await uploadPdf(file)
      // 先落盘再轮询：万一这一瞬间刷新了，句柄已经在手上
      saveJob({ id, name })
      started = { id, name }
    } catch (e) {
      setJob(null)
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      // POST 回来就放开拖拽框。**盯着后台那条管线不是禁用它的理由** ——
      // 一卷从 ③ 到 ⑦ 要几小时，把上传框锁上几小时等于这段时间根本不能用；
      // 而「同一份卷子不许同时跑两条」那道闸在后端（/api/upload 会回 409），
      // 前端状态挡不住刷新和换标签页，本来也不该由它来挡
      setSending(false)
    }
    if (started) await follow(started.id, started.name, true)
  }

  const dismiss = () => { saveJob(null); setJob(null); setLost(null); setRetry(0) }

  return (
    <div>
      <div
        className={`drop${hot ? ' hot' : ''}${sending ? ' busy' : ''}`}
        onClick={() => pick.current?.click()}
        onDragEnter={(e) => { e.preventDefault(); setHot(true) }}
        onDragOver={(e) => { e.preventDefault(); setHot(true) }}
        onDragLeave={() => setHot(false)}
        onDrop={(e) => {
          e.preventDefault(); setHot(false)
          const f = e.dataTransfer.files[0]
          if (f) void send(f)
        }}
      >
        <b>{sending ? '上传中…' : '把试卷 PDF 拖到这里'}</b>
        <span>{sending ? '正在把文件送上去' : '或者点一下选择文件 · 只接受有文字层的 PDF，暂不支持扫描件'}</span>
        <input ref={pick} type="file" accept="application/pdf" hidden
               onChange={(e) => { const f = e.target.files?.[0]; if (f) void send(f) }} />
      </div>

      {err && <div className="banner bad"><b>失败</b>　{err}</div>}

      {/* 问不到后端。不说的话，界面和「正在后台解题」长得一模一样 */}
      {retry > 0 && (
        <div className="banner bad">
          <b>连不上后端</b>　已经重试 {retry} 次。后台那条管线可能还在跑，
          它的产出都在库里，恢复之后刷新就能看到。
        </div>
      )}

      {/* 句柄打不开了。到底怎么回事是问过库之后才写出来的，不硬套「后端重启过」 */}
      {lost && (
        <div className="banner">
          <b>上一次上传</b>　{lost}
          <button className="btn" onClick={dismiss}>知道了</button>
        </div>
      )}

      {job && <pre className="log">{job.log.join('\n')}</pre>}

      {job?.state === 'solving' && (
        <div className="banner">
          <b>切出 {job.n} 题，已经可以看了</b>　解题在后台逐题进行
          （{job.solved ?? 0}/{job.total ?? job.n}），解一道要两三分钟，
          解完一道页面上就多一道。
          {job.name && (
            <button className="btn" onClick={() => onDone(job.name!, true)}>
              去看这份卷子 →
            </button>
          )}
        </div>
      )}
      {job?.state === 'finishing' && (
        <div className="banner">
          <b>{job.n} 题都解完了</b>　正在跑 ④ 写断言与 ⑦ 装配离线页（{job.step}）。
          题目和解法已经在库里，这一步不影响现在看。
          {job.name && (
            <button className="btn" onClick={() => onDone(job.name!, true)}>
              去看这份卷子 →
            </button>
          )}
        </div>
      )}
      {job?.state === 'done' && (
        <div className={`banner${job.warnings?.length ? ' bad' : ''}`}>
          <b>完成</b>　切出 {job.n} 题
          {job.warnings?.length ? (
            <>
              ，{job.warnings.length} 条告警：
              <ul>{job.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </>
          ) : '，无告警'}
        </div>
      )}
      {job?.state === 'error' && (
        <div className="banner bad">
          <b>管线失败</b>　{job.err}
          <button className="btn" onClick={dismiss}>知道了</button>
        </div>
      )}
    </div>
  )
}
