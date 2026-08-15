import type {
  Job, Paper, PaperSummary, Progress, Sheet, SheetBrief, Verdict,
} from './types'

/** 会话是 HttpOnly cookie，JS 读不到它，只能靠请求自动带上 */
const CRED: RequestInit = { credentials: 'include' }

/**
 * 带状态码的请求失败。
 *
 * 状态码要留着：长轮询里「404 任务不存在」和「网络抖了一下」得区别对待 ——
 * 前者是任务真没了（后端重启过），后者下一轮就好了。只看 message 分不出来。
 */
export class ApiError extends Error {
  constructor(msg: string, readonly status: number) { super(msg) }
}

/** 没登录（或会话过期）时后端给 401。前端靠这个标记退回登录页 */
export class Unauthorized extends ApiError {}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }))
    const msg = d.detail ?? `HTTP ${r.status}`
    if (r.status === 401) {
      // 会话过期可能发生在任何一次请求上，包括试卷页那条每 3 秒的静默轮询。
      // 让每个调用点各自处理的话，总会漏掉一个 —— 漏掉的那个表现为页面
      // 静静地停止更新。所以在这里广播一次，由 App 统一退回登录页。
      window.dispatchEvent(new Event('auth:expired'))
      throw new Unauthorized(msg, r.status)
    }
    throw new ApiError(msg, r.status)
  }
  return r.json() as Promise<T>
}

const post = (url: string, body?: unknown) =>
  fetch(url, {
    ...CRED, method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

export const getMe = () => fetch('/api/auth/me', CRED).then(j<{ email: string }>)
export const requestCode = (email: string) =>
  post('/api/auth/code', { email })
    .then(j<{ sent: boolean; delivered: boolean; ttlMinutes: number; hint: string | null }>)
export const verifyCode = (email: string, code: string) =>
  post('/api/auth/verify', { email, code }).then(j<{ email: string; isNew: boolean }>)
export const logout = () => post('/api/auth/logout').then(j<{ ok: boolean }>)

export const listPapers = (mode?: string) =>
  fetch(mode ? `/api/papers?mode=${mode}` : '/api/papers', CRED)
    .then(j<PaperSummary[]>)

export const getPaper = (name: string) =>
  fetch(`/api/papers/${encodeURIComponent(name)}`, CRED).then(j<Paper>)
export const getJob = (id: string) => fetch(`/api/jobs/${id}`, CRED).then(j<Job>)

/** 轻量进度。只有计数，可以每几秒轮询——整卷数据有一两兆，拿来轮询太重 */
export const getProgress = (name: string) =>
  fetch(`/api/papers/${encodeURIComponent(name)}/progress`, CRED).then(j<Progress>)

/**
 * 这份卷子挂着哪些答题卡，以及**该打开哪一份**（`landing`）。
 *
 * `#/sheet/<卷名>` 的含义是「给我看这份卷子的诊断结果」，而书签、刷新、
 * 老地址落进来时前端手上只有卷名 —— 靠这条轻量端点问出落地目标。
 * **不能拿整卷端点问**：那是一两兆，为一次跳转拉它不划算。
 */
export const getPaperSheets = (name: string) =>
  fetch(`/api/papers/${encodeURIComponent(name)}/sheets`, CRED)
    .then(j<{ landing: number | null; sheets: SheetBrief[] }>)

export function uploadPdf(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return fetch('/api/upload', { ...CRED, method: 'POST', body: fd })
    .then(j<{ job: string; name: string }>)
}

/**
 * 答题卡模式的上传：卷名 + 一到多张参考答案。
 *
 * 和 uploadPdf 是两条入口，故意不合并 —— 那边卷名从文件名推、只收一个 PDF，
 * 这边卷名要人填、收一批图。
 */
/** 答题卡模式的三栏材料。`answers` 必填，另两栏这一轮读不了、只收下存着 */
export interface AnswerUpload {
  answers: File[]
  stem: File[]
  sheet: File[]
}

export function uploadAnswerPaper(name: string, g: AnswerUpload) {
  const fd = new FormData()
  fd.append('name', name)
  for (const f of g.answers) fd.append('files', f)
  for (const f of g.stem) fd.append('stem_files', f)
  for (const f of g.sheet) fd.append('sheet_files', f)
  return fetch('/api/answer-papers', { ...CRED, method: 'POST', body: fd })
    .then(j<{ job: string; name: string }>)
}

export const sceneScriptUrl = (name: string) =>
  `/api/papers/${encodeURIComponent(name)}/scene.js`

/**
 * 重跑某一道题的动画（⑤）。返回任务 id，拿它去 getJob 轮询。
 *
 * 会 409 的两种情况：这道题已经在跑、或者整卷管线在跑。两种都不是错误，
 * 是「等一下」——调用方要把 detail 原样显示出来，别糊成一句「失败」。
 */
export const rescene = (name: string, n: number) =>
  post(`/api/papers/${encodeURIComponent(name)}/questions/${n}/rescene`)
    .then(j<{ job: string; question: number }>)

/**
 * 继续执行：从卷子停下的地方接着往下跑。
 *
 * **不是重跑。** 每一步都跳过已经做完的活，所以在一份几乎跑完的卷子上应该
 * 很快就结束。最常见的停法是后端重启 —— 驱动整条链的线程随进程没了，
 * 库里的数据是好的，只是没人接着往下走。
 *
 * 409 的两种情况：正在跑、已经完成。都不是错误，是「不用点」——
 * 调用方要把 detail 原样显示出来。
 */
export const resumePaper = (name: string) =>
  post(`/api/papers/${encodeURIComponent(name)}/resume`)
    .then(j<{ job: string; name: string; from: string }>)

/** 删除结果。names 可能有已经不存在的（列表过期），后端如实分开回报 */
export interface DeleteResult { deleted: string[]; missing: string[]; objects: number }

export const deletePapers = (names: string[]) =>
  post('/api/papers/delete', { names }).then(j<DeleteResult>)

// ---------------------------------------------------------------- 答题卡（步二）

export const getSheet = (id: number) =>
  fetch(`/api/sheets/${id}`, CRED).then(j<Sheet>)

/**
 * 传一份**已批改的**答题卡，挂到一份已经读出参考答案的卷子上。
 *
 * 和 uploadAnswerPaper 是两条入口：那个建的是**卷子**（一份卷子一套标准答案），
 * 这个建的是**一份卡**（一个学生一次作答），一份卷子可以挂多份卡。
 */
export function uploadSheet(paper: string, student: string, files: File[]) {
  const fd = new FormData()
  fd.append('paper', paper)
  fd.append('student', student)
  for (const f of files) fd.append('files', f)
  return fetch('/api/answer-sheets', { ...CRED, method: 'POST', body: fd })
    .then(j<{ job: string; sheet: number; paper: string }>)
}

/**
 * 老师改判一道题。`verdict=null` 撤回改判。
 *
 * **改判成「半对」必须同时给分数** —— 半对是几分推不出来。
 * 对/错不用给：后端按满分和 0 推。
 *
 * 后端的 detail 要原样显示：那几条都是能照着做的话
 *（「半对必须给分数」「这份卡里没有第 N 题」），糊成「改判失败」就白写了。
 */
export const regrade = (sheet: number, n: number,
                        verdict: Verdict | null, score?: number) =>
  fetch(`/api/sheets/${sheet}/questions/${n}/regrade`, {
    ...CRED, method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ verdict, score }),
  }).then(j<{ ok: boolean }>)
