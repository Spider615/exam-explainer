import { useRef, useState } from 'react'
import { getJob, uploadPdf } from '../api'
import type { Job } from '../types'

export default function Upload({ onDone }: { onDone: (name: string) => void }) {
  const [hot, setHot] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const pick = useRef<HTMLInputElement>(null)

  async function send(file: File) {
    if (!/\.pdf$/i.test(file.name)) { setErr('只接受 PDF 文件'); return }
    setErr(null); setBusy(true)
    setJob({ state: 'running', step: '上传中', log: [`上传 ${file.name}…`] })
    try {
      const { job: id } = await uploadPdf(file)
      // 切分通常 3 秒内跑完，之后转入 solving —— 解题一道两三分钟，
      // 一卷十几道就是半小时。所以切完就放人进去看，解法在后台逐题填。
      let opened = false
      for (;;) {
        const j = await getJob(id)
        setJob(j)
        if (j.state === 'solving' && !opened && j.name) { opened = true; onDone(j.name) }
        if (j.state === 'done' || j.state === 'error') {
          if (j.state === 'done' && !opened && j.name) onDone(j.name)
          break
        }
        const slow = j.state === 'solving' || j.state === 'finishing'
        await new Promise((r) => setTimeout(r, slow ? 4000 : 600))
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div
        className={`drop${hot ? ' hot' : ''}${busy ? ' busy' : ''}`}
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
        <b>{busy ? '处理中…' : '把试卷 PDF 拖到这里'}</b>
        <span>{busy ? job?.step ?? '' : '或者点一下选择文件 · 只接受有文字层的 PDF，暂不支持扫描件'}</span>
        <input ref={pick} type="file" accept="application/pdf" hidden
               onChange={(e) => { const f = e.target.files?.[0]; if (f) void send(f) }} />
      </div>

      {err && <div className="banner bad"><b>失败</b>　{err}</div>}

      {job && <pre className="log">{job.log.join('\n')}</pre>}

      {job?.state === 'solving' && (
        <div className="banner">
          <b>切出 {job.n} 题，已经可以看了</b>　解题在后台逐题进行
          （{job.solved ?? 0}/{job.total ?? job.n}），解一道要两三分钟，
          解完一道页面上就多一道。
        </div>
      )}
      {job?.state === 'finishing' && (
        <div className="banner">
          <b>{job.n} 题都解完了</b>　正在跑 ④ 写断言与 ⑦ 装配离线页（{job.step}）。
          题目和解法已经在库里，这一步不影响现在看。
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
        <div className="banner bad"><b>管线失败</b>　{job.err}</div>
      )}
    </div>
  )
}
