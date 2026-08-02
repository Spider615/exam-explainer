import type { Job, Paper, PaperSummary, Progress } from './types'

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(d.detail ?? `HTTP ${r.status}`)
  }
  return r.json() as Promise<T>
}

export const listPapers = () => fetch('/api/papers').then(j<PaperSummary[]>)
export const getPaper = (name: string) =>
  fetch(`/api/papers/${encodeURIComponent(name)}`).then(j<Paper>)
export const getJob = (id: string) => fetch(`/api/jobs/${id}`).then(j<Job>)

/** 轻量进度。只有计数，可以每几秒轮询——整卷数据有一两兆，拿来轮询太重 */
export const getProgress = (name: string) =>
  fetch(`/api/papers/${encodeURIComponent(name)}/progress`).then(j<Progress>)

export function uploadPdf(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return fetch('/api/upload', { method: 'POST', body: fd }).then(j<{ job: string; name: string }>)
}

export const sceneScriptUrl = (name: string) =>
  `/api/papers/${encodeURIComponent(name)}/scene.js`

/** 删除结果。names 可能有已经不存在的（列表过期），后端如实分开回报 */
export interface DeleteResult { deleted: string[]; missing: string[]; objects: number }

export const deletePapers = (names: string[]) =>
  fetch('/api/papers/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ names }),
  }).then(j<DeleteResult>)
