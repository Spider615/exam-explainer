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
/**
 * 页序：把文件名按数字段切开，数字段按数值比、其余按小写字典序比。
 *
 * **必须和后端 `pipeline/pages.py` 的 `sort_key` 一模一样** —— 这个清单存在的
 * 全部意义就是「开跑之前让人看见后端会怎么排」。排法不一致的话，它给出的是
 * 一个看着可信、实际不作数的顺序，比不给还糟。
 *
 * 为什么要按数值比：`IMG_10` 按字典序会跑到 `IMG_2` 前面，而拍照的人绝对
 * 想不到是这个原因（这条注释在 pages.py 里也有一份，是同一个坑）。
 */
function pageKey(filename: string): [number, string][] {
  const base = filename.split(/[\\/]/).pop() ?? filename
  return base.split(/(\d+)/).filter((t) => t !== '').map(
    (t) => (/^\d+$/.test(t) ? [Number(t), ''] : [0, t.toLowerCase()]),
  )
}

function byPageOrder(a: File, b: File): number {
  const ka = pageKey(a.name)
  const kb = pageKey(b.name)
  for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
    if (ka[i][0] !== kb[i][0]) return ka[i][0] - kb[i][0]
    if (ka[i][1] !== kb[i][1]) return ka[i][1] < kb[i][1] ? -1 : 1
  }
  return ka.length - kb.length          // 前缀相同时短的在前，和 Python 一致
}

const kb = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB`
  : `${Math.max(1, Math.round(n / 1024))} KB`)

export default function SheetUpload({ onDone }: {
  /** open=true 才跳进详情页；job 进 solving/done 时只用来刷新列表 */
  onDone: (name: string, open: boolean) => void
}) {
  const [name, setName] = useState('')
  /**
   * 选好但**还没送出去**的文件。
   *
   * **松手就开跑是错的。** Ⓐ 一页要一分钟上下、四张图就是四分钟真金白银的
   * 模型调用，而这条链有两件事必须在开跑之前让人确认：卷名（这边推不出来，
   * 只能人填）和**页序**（按文件名排，不是拖进来的顺序）。手一滑拖错一个
   * 文件夹，旧版会立刻开跑、几分钟后才在失败里看到。
   */
  const [picked, setPicked] = useState<File[]>([])
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

  /**
   * 把选中的文件收进暂存区，**不发**。
   *
   * 同名同大小的当成同一个（连着拖两次同一批是常事），其余追加 ——
   * 追加而不是替换：老师完全可能分两次把 4 张图拖进来。
   */
  function stage(files: File[]) {
    if (!files.length) return
    setErr(null)
    setPicked((prev) => {
      const seen = new Set(prev.map((f) => `${f.name} ${f.size}`))
      return [...prev, ...files.filter((f) => !seen.has(`${f.name} ${f.size}`))]
    })
  }

  async function send() {
    const files = [...picked].sort(byPageOrder)
    if (!files.length) { setErr('还没有选文件'); return }
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
      setPicked([])          // 送出去了就清空，别让下一次误传同一批
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
          stage([...e.dataTransfer.files])
        }}
      >
        {/* **说清楚要什么、更要说清楚不要什么。** 这个模式叫「答题卡诊断」，
            老师手上是三样东西（题目、答题卡、参考答案），而这一栏这一轮只吃
            参考答案 —— 不写明的话，人自然会把三样一起拖进来（实测就是这样）。
            后果不只是白等：题目 PDF 文件名里没数字，按文件名排序反而排到最前，
            一页一分钟先啃完整份题目；答题卡上学生手写的答案还可能被当成标准
            答案存下来。后端也拦了一道（连着三页读不出就停），但那是兜底 */}
        <b>{picked.length ? '再拖几张，或者换几张' : '把参考答案拖到这里'}</b>
        <span>只要<b>参考答案</b>那几页 —— 印着「参考答案」、一题一题给出答案的那种</span>
        <span>照片 / 扫描图 / PDF 都行，可以一次多张 · 按文件名排页序</span>
        <span className="drop-no">
          题目和答题卡这一轮还用不上，别混进来 —— 混着传会先把题目一页页啃完，
          还可能把答题卡上学生写的答案当成标准答案
        </span>
        {/* value 清空：不然连着选同一批文件时 onChange 不会再触发 */}
        <input ref={pick} type="file" multiple hidden
               accept="image/*,application/pdf"
               onChange={(e) => {
                 stage([...(e.target.files ?? [])])
                 e.target.value = ''
               }} />
      </div>

      {/* 选好的先摊在这儿，**点了「开始分析」才真的开跑**。
          Ⓐ 一页一分钟上下，四张就是四分钟真金白银的模型调用 —— 手一滑拖错
          一个文件夹，旧版会立刻开跑、几分钟后才在失败里看到。
          页序也在这里摊开：它是按**文件名**排的，不是拖进来的顺序，
          排错了在这一屏就能看见，不用等四分钟。 */}
      {picked.length > 0 && (
        <div className="picked">
          <div className="picked-hd">
            <b>选了 {picked.length} 个文件</b>
            <span>会按这个顺序当成第 1、2、3… 页读</span>
            <button className="link" disabled={sending}
                    onClick={() => setPicked([])}>全部清掉</button>
          </div>
          <ol>
            {[...picked].sort(byPageOrder).map((f) => (
              <li key={`${f.name} ${f.size}`}>
                <span className="picked-n">{f.name}</span>
                <span className="picked-sz">{kb(f.size)}</span>
                <button className="del" disabled={sending} title={`去掉 ${f.name}`}
                        onClick={() => setPicked((p) => p.filter(
                          (x) => !(x.name === f.name && x.size === f.size)))}>
                  去掉
                </button>
              </li>
            ))}
          </ol>
          {/* 混着 PDF 和图片时，页序最容易出人意料：`pages.sort_key` 把文件名
              按数字段切开比，**没有数字的文件名整体排在有数字的前面**（`(0, 名字)`
              对上 `(20260807, ...)`）。于是一份叫「高二期末.pdf」的题目会排到
              那堆 `20260807-*.jpeg` 前头，把真正的参考答案挤到十几页之后。
              这条不说的话，上面那张「按这个顺序读」的清单是骗人的 —— 它只排了
              文件，没排 PDF 展开出来的那些页 */}
          {picked.some((f) => /\.pdf$/i.test(f.name)) && (
            <p className="picked-note">
              <b>里面有 PDF。</b>它会展开成多页，真实页数比这里的文件数多得多，
              而上面这个清单只排了文件、排不出展开后的页。
              如果这份 PDF 是<b>题目</b>而不是参考答案，请把它去掉 ——
              它会排在最前面被一页页读完（一页约一分钟）。
            </p>
          )}
          <div className="picked-go">
            <button className="btn" disabled={sending || !name.trim()}
                    onClick={() => void send()}>
              {sending ? '正在送上去…' : '开始分析'}
            </button>
            <span>
              {!name.trim() ? '先在上面填一个卷名'
                : `读参考答案一页要一分钟上下，${picked.length} 个文件大约 ${picked.length} 分钟`}
            </span>
          </div>
        </div>
      )}

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
