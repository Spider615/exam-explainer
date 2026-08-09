import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getJob, Unauthorized, uploadAnswerPaper } from '../api'
import type { Job } from '../types'

/**
 * 答题卡模式的上传框：卷名 + 一批参考答案。
 *
 * **卷名必须人填。** 这边收的是一批照片，文件名是 `IMG_0123` 这种，
 * 推不出任何有意义的卷名 —— 而卷名是页面地址的一部分，将来还要打印在报告上。
 *
 * **POST 一返回就自动跳走是错的，这轮改掉了。** 以前这里一拿到 `{job, name}`
 * 就直接 `onDone(r.name)` 跳进详情页，组件跟着卸载 —— 而 Ⓐ 读参考答案要几
 * 分钟，最常见的失败场景就是照片拍糊了：`refread.read()` 抛「一道题的答案
 * 都没读出来」，后端把这次新建的空壳卷子删掉，`/progress` 从此 404。跳走的
 * 话没有任何 UI 盯着这条链的进度，失败原因和「卷子已经不存在了」这件事
 * 谁都看不到，页面只会在 SheetView 里停在「Ⓐ 读参考答案」那个呼吸点不动
 * （另一半修在 SheetView.tsx 的轮询 catch 里）。
 *
 * 照抄 Upload.tsx 已经做对的那套：自己轮询 `getJob` 把任务画出来，跳走交给
 * 用户点按钮。比 Upload.tsx 简单的地方是不用 localStorage 记句柄——那边要
 * 应付「切分完就跳进试卷页，头几分钟卷子还没入库，刷新就把句柄丢了」；这边
 * POST 一失败页面还在原地、没有跳走这回事，也没有单题重跑那种要恢复的场景。
 */
export default function SheetUpload({ onDone }: {
  /** open=true 才跳进详情页；job 进 solving/done 时只用来刷新列表 */
  onDone: (name: string, open: boolean) => void
}) {
  const [name, setName] = useState('')
  const [hot, setHot] = useState(false)
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  /** 任务句柄问不到了（后端重启，JOBS 是进程内的 dict）。终态，不再重试 */
  const [lost, setLost] = useState<string | null>(null)
  /** 连着几轮问不到后端了（网络抖动/重启中）。0 表示一切正常 */
  const [retry, setRetry] = useState(0)
  const pick = useRef<HTMLInputElement>(null)
  /** 换任务用抢的：只会发生在同一次挂载里连续传了两次，道理和 Upload.tsx
      的 watching 一样，这里更简单——没有「挂载时接上一个旧任务」那一路 */
  const watching = useRef<string | null>(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  /**
   * 盯着一个任务直到它收场（'done' 或 'error'）。
   *
   * 出错分两种：404 是任务句柄没了——JOBS 只在内存里，后端重启一次就清空，
   * 这是终态，问下去没有意义。其余（网络抖动、后端重启中）不能当成任务
   * 没了，退避重试，但要把「问不到」说出来——不说的话，界面和「正在读」
   * 长得一模一样，人会一直等下去。
   */
  const follow = useCallback(async (id: string) => {
    if (watching.current === id) return
    watching.current = id
    setLost(null); setRetry(0)
    let announced = false
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
            setLost('这个上传任务的句柄没了（后端多半重启过）。卷子如果已经'
              + '读出了参考答案，刷新一下答题卡库就能看到；如果是这一步本身'
              + '没跑完，那份新建的空壳已经被清掉了 —— 重新上传一次就行。')
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
        // solving 起卷子已经在库里了（Ⓐ 成功、题已经读出来），外面要刷一遍
        // 列表才看得见。done 之后不会再变成 error——③c 挂不上知识点不算失败
        if (!announced && j.name && (j.state === 'solving' || j.state === 'done')) {
          announced = true
          onDone(j.name, false)
        }
        if (j.state === 'done' || j.state === 'error') return
        // running 是 Ⓐ 在跑（一页一分钟上下），值得盯紧；到 solving 之后
        // 只是 ③c 在后台挂知识点，没必要那么频繁
        await new Promise((r) => setTimeout(r, j.state === 'running' ? 800 : 4000))
      }
    } finally {
      if (watching.current === id) watching.current = null
    }
  }, [onDone])

  async function send(files: File[]) {
    if (!files.length) return
    if (!name.trim()) { setErr('先填一个卷名'); return }
    setErr(null); setNote(null); setJob(null); setLost(null); setRetry(0)
    setSending(true)
    let jid: string | null = null
    try {
      const r = await uploadAnswerPaper(name.trim(), files)
      // 后端可能改过名（撞上别人的卷子、或撞上自己的一份解析试卷）。
      // 改了就要说出来 —— 不说的话人会去库里找那个他填的名字，找不到。
      // 这条 note 现在不会跟着组件一起卸载了——上面文件头写了为什么
      setNote(r.name === name.trim()
        ? `已开始读「${r.name}」的参考答案`
        : `卷名「${name.trim()}」已经被占用，这份存成了「${r.name}」`)
      jid = r.job
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      // POST 回来就放开拖拽框——盯着后台那条链不是禁用它的理由，
      // 「同一份卷子不许同时跑两条」那道闸在后端（会回 409）
      setSending(false)
    }
    if (jid) await follow(jid)
  }

  const dismiss = () => { setJob(null); setLost(null); setRetry(0) }

  return (
    <div>
      <label className="fieldrow">
        <span>卷名</span>
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="2025-2026高二物理期末" disabled={sending} />
      </label>
      <div
        className={`drop${hot ? ' hot' : ''}${sending ? ' busy' : ''}`}
        onClick={() => pick.current?.click()}
        onDragEnter={(e) => { e.preventDefault(); setHot(true) }}
        onDragOver={(e) => { e.preventDefault(); setHot(true) }}
        onDragLeave={() => setHot(false)}
        onDrop={(e) => {
          e.preventDefault(); setHot(false)
          void send([...e.dataTransfer.files])
        }}
      >
        <b>{sending ? '上传中…' : '把参考答案拖到这里'}</b>
        <span>
          {sending ? '正在把文件送上去'
            : '照片 / 扫描图 / PDF 都行，可以一次多张 · 按文件名排页序'}
        </span>
        <input ref={pick} type="file" multiple hidden
               accept="image/*,application/pdf"
               onChange={(e) => void send([...(e.target.files ?? [])])} />
      </div>

      {err && <div className="banner bad"><b>失败</b>　{err}</div>}
      {note && <div className="banner">{note}</div>}

      {job && <pre className="log">{job.log.join('\n')}</pre>}

      {/* 问不到后端。不说的话，界面和「正在读」长得一模一样 */}
      {retry > 0 && (
        <div className="banner bad">
          <b>连不上后端</b>　已经重试 {retry} 次。任务如果还在跑，
          恢复之后这里会接着更新。
        </div>
      )}

      {/* 任务句柄彻底没了（后端重启过）。到底怎么回事说清楚，不硬套一句「失败」 */}
      {lost && (
        <div className="banner">
          <b>问不到这个任务了</b>　{lost}
          <button className="btn" onClick={dismiss}>知道了</button>
        </div>
      )}

      {job?.state === 'solving' && (
        <div className="banner">
          <b>已经读出 {job.n} 题，可以看了</b>　知识点在后台继续挂，
          挂完这份卷子就完整了。
          {job.name && (
            <button className="btn" onClick={() => onDone(job.name!, true)}>
              去看这份卷子 →
            </button>
          )}
        </div>
      )}
      {job?.state === 'done' && (
        <div className="banner">
          <b>完成</b>　参考答案读完了，知识点也挂完了。
          {job.name && (
            <button className="btn" onClick={() => onDone(job.name!, true)}>
              去看这份卷子 →
            </button>
          )}
        </div>
      )}
      {job?.state === 'error' && (
        <div className="banner bad">
          <b>Ⓐ 读参考答案失败</b>　{job.err}
          <button className="btn" onClick={dismiss}>知道了</button>
        </div>
      )}
    </div>
  )
}
