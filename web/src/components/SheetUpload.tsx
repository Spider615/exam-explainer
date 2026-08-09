import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getJob, Unauthorized, uploadAnswerPaper } from '../api'
import type { Job } from '../types'

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

const size = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB`
  : `${Math.max(1, Math.round(n / 1024))} KB`)

type SlotKey = 'answers' | 'stem' | 'sheet'
type Batch = Record<SlotKey, File[]>
const EMPTY: Batch = { answers: [], stem: [], sheet: [] }

/**
 * 三个框，不是一个。
 *
 * 老师手上就是三样东西：原卷（题目）、答题卡、参考答案。一个框的时候他会很
 * 自然地一起拖进来（实测就是这样），而后端按文件名排页序 —— 一份叫
 * 「高二期末.pdf」的题目（名字里没数字）反而排到那些 `20260807-*.jpeg` 前面，
 * Ⓐ 从第 1 页开始一页一分钟啃整份题目。更糟的是答题卡（学生手写、带红勾红叉）
 * 排在真参考答案前面，而后端对同一题号先到先得 —— 学生写错的答案会被当成
 * 标准答案存下来。
 *
 * 换成「让系统逐页认这是什么」也不行：认错一页参考答案，那一页上的题就悄悄
 * 没了，而「悄悄」是这个项目最不能接受的失败形状。**三个框比一个聪明的分拣器
 * 可靠**，而且老师本来就知道哪份是哪份 —— 这件事不该让系统去猜。
 *
 * 另外两栏这一轮读不了，但**现在就收下**：没理由让他为此分三次、隔几周传三回。
 */
interface Slot {
  key: SlotKey
  title: string
  /** 必填 / 选填 */
  need: string
  /** 这一栏要的是什么 —— 说得越具体，传错的机会越小 */
  want: string
  /** 传上来之后会怎样。**选填那两栏尤其要说**：不说的话，人会以为传了没用 */
  fate: string
}

const SLOTS: Slot[] = [
  { key: 'answers', title: '参考答案', need: '必填',
    want: '印着「参考答案」、一题一题给出答案的那几页',
    fate: '这一轮唯一会读的：读出每题的标准答案和官方解答过程' },
  { key: 'stem', title: '原卷（题目）', need: '选填',
    want: '试卷本身，PDF 或拍的照片都行',
    fate: '现在只收下存着 —— 等「读题干」做好就能给选择题和填空题挂上知识点' },
  { key: 'sheet', title: '答题卡', need: '选填',
    want: '学生那份，已经批改过的最好',
    fate: '现在只收下存着 —— 等「读答题卡」做好就能逐题对错、出薄弱点' },
]

/**
 * 答题卡模式的上传框。
 *
 * **卷名必须人填。** 这边收的是一批照片，文件名是 `IMG_0123` 这种，
 * 推不出任何有意义的卷名 —— 而卷名是页面地址的一部分，将来还要打印在报告上。
 *
 * **松手就开跑是错的。** Ⓐ 一页要一分钟上下，四张图就是四分钟真金白银的模型
 * 调用。选好的先摊开、点「开始分析」才真的开跑。
 *
 * **POST 一返回就自动跳走也是错的。** 以前一拿到 `{job, name}` 就跳进详情页、
 * 组件跟着卸载 —— 而最常见的失败是照片拍糊了：后端抛「一道题的答案都没读
 * 出来」、把这次新建的空壳卷子删掉，`/progress` 从此 404。跳走的话没有任何 UI
 * 盯着这条链，失败原因和「卷子已经不存在了」谁都看不到。照抄 Upload.tsx 已经
 * 做对的那套：自己轮询 `getJob` 把任务画出来，跳走交给用户点。
 */
export default function SheetUpload({ onDone }: {
  /** open=true 才跳进详情页；job 进 solving/done 时只用来刷新列表 */
  onDone: (name: string, open: boolean) => void
}) {
  const [name, setName] = useState('')
  const [picked, setPicked] = useState<Batch>(EMPTY)
  const [hot, setHot] = useState<SlotKey | null>(null)
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  /** 任务句柄问不到了（后端重启，JOBS 是进程内的 dict）。终态，不再重试 */
  const [lost, setLost] = useState<string | null>(null)
  /** 连着几轮问不到后端了（网络抖动/重启中）。0 表示一切正常 */
  const [retry, setRetry] = useState(0)
  const pick = useRef<Record<string, HTMLInputElement | null>>({})
  /** 换任务用抢的：只会发生在同一次挂载里连续传了两次 */
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
   * 把选中的文件收进某一栏的暂存区，**不发**。
   *
   * 同名同大小的当成同一个（连着拖两次同一批是常事），其余追加 ——
   * 追加而不是替换：老师完全可能分两次把几张图拖进同一栏。
   */
  function stage(slot: SlotKey, files: File[]) {
    if (!files.length) return
    setErr(null)
    setPicked((prev) => {
      const seen = new Set(prev[slot].map((f) => `${f.name}|${f.size}`))
      return { ...prev,
        [slot]: [...prev[slot], ...files.filter((f) => !seen.has(`${f.name}|${f.size}`))] }
    })
  }

  const drop = (slot: SlotKey, f: File) =>
    setPicked((prev) => ({ ...prev,
      [slot]: prev[slot].filter((x) => !(x.name === f.name && x.size === f.size)) }))

  const total = picked.answers.length + picked.stem.length + picked.sheet.length

  async function send() {
    if (!picked.answers.length) { setErr('参考答案那一栏是空的 —— 它是这份诊断的地基'); return }
    if (!name.trim()) { setErr('先填一个卷名'); return }
    setErr(null); setNote(null); setJob(null); setLost(null); setRetry(0)
    setSending(true)
    let jid: string | null = null
    try {
      const r = await uploadAnswerPaper(name.trim(), {
        answers: [...picked.answers].sort(byPageOrder),
        stem: [...picked.stem].sort(byPageOrder),
        sheet: [...picked.sheet].sort(byPageOrder),
      })
      // 后端可能改过名（撞上别人的卷子、或撞上自己的一份解析试卷）。
      // 改了就要说出来 —— 不说的话人会去库里找那个他填的名字，找不到
      setNote(r.name === name.trim()
        ? `已开始读「${r.name}」的参考答案`
        : `卷名「${name.trim()}」已经被占用，这份存成了「${r.name}」`)
      jid = r.job
      setPicked(EMPTY)          // 送出去了就清空，别让下一次误传同一批
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
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

      <div className="slots">
        {SLOTS.map((s) => {
          const files = picked[s.key]
          return (
            <section key={s.key} className="slot">
              <h4>
                {s.title}
                <em className={s.key === 'answers' ? 'must' : ''}>{s.need}</em>
              </h4>
              <p className="slot-want">{s.want}</p>
              <div
                className={`drop slim${hot === s.key ? ' hot' : ''}${sending ? ' busy' : ''}`}
                onClick={() => pick.current[s.key]?.click()}
                onDragEnter={(e) => { e.preventDefault(); setHot(s.key) }}
                onDragOver={(e) => { e.preventDefault(); setHot(s.key) }}
                onDragLeave={() => setHot(null)}
                onDrop={(e) => {
                  e.preventDefault(); setHot(null)
                  stage(s.key, [...e.dataTransfer.files])
                }}
              >
                <b>{files.length ? '再拖几张' : '拖到这里'}</b>
                <span>照片 / 扫描图 / PDF</span>
                {/* value 清空：不然连着选同一批文件时 onChange 不会再触发 */}
                <input ref={(el) => { pick.current[s.key] = el }}
                       type="file" multiple hidden accept="image/*,application/pdf"
                       onChange={(e) => {
                         stage(s.key, [...(e.target.files ?? [])])
                         e.target.value = ''
                       }} />
              </div>
              <p className="slot-fate">{s.fate}</p>

              {/* 页序在开跑之前就摊开：它是按**文件名**排的，不是拖进来的顺序，
                  排错了在这一屏就看得见，不用等四分钟 */}
              {files.length > 0 && (
                <ol className="picked">
                  {[...files].sort(byPageOrder).map((f) => (
                    <li key={`${f.name}|${f.size}`}>
                      <span className="picked-n">{f.name}</span>
                      <span className="picked-sz">{size(f.size)}</span>
                      <button className="del" disabled={sending} title={`去掉 ${f.name}`}
                              onClick={() => drop(s.key, f)}>去掉</button>
                    </li>
                  ))}
                </ol>
              )}
              {files.some((f) => /\.pdf$/i.test(f.name)) && (
                <p className="picked-note">
                  里面有 PDF，会展开成多页 —— 上面这个清单只排了文件，排不出展开后的页。
                </p>
              )}
            </section>
          )
        })}
      </div>

      {total > 0 && (
        <div className="picked-go">
          <button className="btn" disabled={sending || !name.trim() || !picked.answers.length}
                  onClick={() => void send()}>
            {sending ? '正在送上去…' : '开始分析'}
          </button>
          <span>
            {!name.trim() ? '先在上面填一个卷名'
              : !picked.answers.length ? '参考答案那一栏还是空的'
                : `读参考答案一页要一分钟上下，${picked.answers.length} 个文件大约 `
                  + `${picked.answers.length} 分钟；另外 ${total - picked.answers.length} `
                  + '个只收下存着，不花时间'}
          </span>
          <button className="link" disabled={sending}
                  onClick={() => setPicked(EMPTY)}>全部清掉</button>
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
