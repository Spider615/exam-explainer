import type { Job, Paper, PaperSummary, Progress } from './types'

/** 会话是 HttpOnly cookie，JS 读不到它，只能靠请求自动带上 */
const CRED: RequestInit = { credentials: 'include' }

/** 没登录（或会话过期）时后端给 401。前端靠这个标记退回登录页 */
export class Unauthorized extends Error {}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }))
    const msg = d.detail ?? `HTTP ${r.status}`
    if (r.status === 401) {
      // 会话过期可能发生在任何一次请求上，包括试卷页那条每 3 秒的静默轮询。
      // 让每个调用点各自处理的话，总会漏掉一个 —— 漏掉的那个表现为页面
      // 静静地停止更新。所以在这里广播一次，由 App 统一退回登录页。
      window.dispatchEvent(new Event('auth:expired'))
      throw new Unauthorized(msg)
    }
    throw new Error(msg)
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

export const listPapers = () => fetch('/api/papers', CRED).then(j<PaperSummary[]>)
export const getPaper = (name: string) =>
  fetch(`/api/papers/${encodeURIComponent(name)}`, CRED).then(j<Paper>)
export const getJob = (id: string) => fetch(`/api/jobs/${id}`, CRED).then(j<Job>)

/** 轻量进度。只有计数，可以每几秒轮询——整卷数据有一两兆，拿来轮询太重 */
export const getProgress = (name: string) =>
  fetch(`/api/papers/${encodeURIComponent(name)}/progress`, CRED).then(j<Progress>)

export function uploadPdf(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return fetch('/api/upload', { ...CRED, method: 'POST', body: fd })
    .then(j<{ job: string; name: string }>)
}

export const sceneScriptUrl = (name: string) =>
  `/api/papers/${encodeURIComponent(name)}/scene.js`

/** 删除结果。names 可能有已经不存在的（列表过期），后端如实分开回报 */
export interface DeleteResult { deleted: string[]; missing: string[]; objects: number }

export const deletePapers = (names: string[]) =>
  post('/api/papers/delete', { names }).then(j<DeleteResult>)
