export type TextQuality = 'ok' | 'suspect' | 'degraded'

export interface Figure { url: string; widthPct: number }

/** 题干/选项里一段公式：[s,e) 是它在文本里的字符区间，mathml 是二维渲染 */
export interface MathSeg { s: number; e: number; mathml: string }

export interface Option {
  key: string
  text: string
  math: MathSeg[]
  figure: string | null
  /** 阶段②b 视觉模型识别出的 LaTeX；有它就优先用它渲染 */
  latex?: string | null
}

export interface Question {
  n: number
  type: string
  points: number | null
  /** 阶段③b 给的 2-5 字短标题（「火星车」）。目录用；缺了就只显示题号，不编 */
  label?: string | null
  section: string | null
  pages: [number, number]
  stem: string
  /** 视觉模型转写的题干，含 $...$ 行内公式；有它就优先用 */
  stemLatex?: string | null
  /** 视觉转写置信度偏低的提示；有值就必须在页面上标出来 */
  stemLowConf?: string | null
  stemRejected?: string | null
  stemImage?: string | null
  stemMath: MathSeg[]
  tables?: QTable[]
  figMarks?: FigMark[]
  options: Option[]
  figures: Figure[]
  textQuality: TextQuality
  qualityReason: string
  /** 选项区的原卷截图，作为兜底与「对照原卷」的依据 */
  optionImage?: string | null
  sceneId: string | null
  sceneFigure: string | null
  /** 重跑之前那个动画。非空时给一个「换回原来那个」—— 重跑出来的不一定更好 */
  prevScene?: string | null
  /** 阶段③ 的解题结果。没解过就是 null，前端必须显式呈现「未生成」 */
  solution: Solution | null
}

/**
 * 模型给出的解法。
 *
 * `confidence` 与 `assumptions` 是必须一起呈现的：这段讲解没有经过人审，
 * assumptions 是模型自己补的、题面没给的前提 —— 只给结论不给这两样，
 * 等于把一个未经检验的答案伪装成权威解法。
 */
export interface Solution {
  answer: string
  /** 阶段③b 压成一行的答案，目录与速览表用。完整版仍在 answer 里 */
  shortAnswer?: string | null
  steps: string[]
  assumptions: string[]
  confidence: 'high' | 'medium' | 'low'
  model: string | null
  /** 阶段④ 写了多少条物理断言。0 表示这段讲解没被任何东西检验过 */
  nInvariants: number
  specStatus: string | null
  animatable: boolean | null
  /** animatable=false 时，为什么这道题不适合做成动画（④ 判「做不做得了」） */
  whyNot: string | null
  /** 阶段④c 判「值不值得做」。做得了但没增量的题不进 ⑤，理由写在 worthWhy */
  worth?: boolean | null
  worthWhy?: string | null
  /** 阶段⑤：门禁的裁决，不是实现方自称的 */
  scenePassed: boolean | null
  sceneRounds: number | null
}

/** 题干里的表格。占位符 〔表N〕 出现在 stem 里，前端据此把它渲染到正确位置 */
export interface QTable {
  id: number
  caption: string
  rows: string[][]
  /** 原卷截图，用于对照核对。跨页表已在后端拼成一张，这里会有两张图 */
  images: string[]
}

/** 图在正文中的落位：占位符 〔图N〕 对应的图片 */
export interface FigMark { id: number; url: string; widthPct: number }

export interface Section { label: string; title: string; declared: number }

export interface Paper {
  name: string
  sections: Section[]
  warnings: string[]
  questions: Question[]
  stages: Record<string, boolean>
  /** 灭着的阶段为什么灭（目前只有 ⑦：没跑过 / 产物被删了 / 比库里的数据旧） */
  stageNotes: Record<string, string>
  /** 这份卷子此刻在不在跑。非空时试卷页顶部画进度带 */
  job?: JobBrief | null
  coverage: { solved: number; total: number }
}

/** 从库里算出来的进度。谁跑的都算得出来——命令行跑的、服务重启过的，一样可见 */
export interface Progress {
  /** 带编号的阶段名（`③ 解题`），和上面那排 ①②③ 标志对得上 */
  stage: string
  /** 白话状态词（`解题中`），列表页用——那里没有编号可对照 */
  stageShort: string
  stageCode: string
  stageCur: number
  stageTotal: number
  busy: boolean
  /** 跑完了：⑦ 装的是当前这份数据。装过但比库里的数据旧不算完成 */
  done: boolean
  /** 失败原因。只认得出这个后端进程里起过的任务，null 不等于成功 */
  failed: string | null
  /**
   * 挂在哪一步（`stage_of` 的代号）。null = 后端也说不清（publish 前后的兜底
   * 异常）—— 那种情况**不许**把这条失败按到任何一格上，只能整条说出来
   */
  failedStage: string | null
  questions: number
  labels: number
  solutions: number
  specs: number
  approved: number
  judged: number
  worth: number
  scenes: number
  /** ④c 选中的题里写了几份 spec。④ 的分母是 worth，不是题数 */
  specsWorth: number
  /** 还没过 ④b 自检的 spec */
  drafts: number
  /** ⑤ 真正会做的题（自检通过 + ④c 选中），以及其中已经试过的 */
  ready: number
  sceneTried: number
  assembled: boolean
  assembledFresh: boolean
  elapsedSeconds: number | null
  /** 网页上传的任务才有的细节（正在解哪道题）；命令行跑的是 null */
  step?: string | null
  last?: string | null
}

/** /api/papers/{name} 里带的活跃任务摘要，够画一条进度带 */
export interface JobBrief {
  id: string
  state: string
  step?: string | null
  solved?: number | null
  total?: number | null
  last?: string
}

export interface PaperSummary {
  name: string
  n: number
  warnings: number
  figures: number
  scenes: number
  mtime: number
  /** 列表页也要能看出哪份还在跑——返回试卷库不等于任务停了 */
  progress?: {
    stage: string; short: string; code: string
    cur: number; total: number
    busy: boolean; done: boolean; failed: string | null
    solved: number; questions: number; elapsedSeconds: number | null
  }
}

export interface Job {
  /**
   * solving：题已切好、可以看了，阶段③ 还在后台逐题解
   * finishing：题都解完了，在跑 ④ 写断言与 ⑦ 装配离线页
   */
  state: 'running' | 'solving' | 'finishing' | 'done' | 'error'
  step?: string
  name?: string
  /** 整卷上传时是「切出几题」；单题重跑不用它，那条走 qn */
  n?: number
  /** 'rescene' = 单题重跑。整卷上传的任务没有这个字段 */
  kind?: string
  /** 重跑的是第几题 */
  qn?: number
  /** 重跑成功后的新场景 id。没换成就没有这个字段 */
  scene?: string
  solved?: number
  total?: number
  warnings?: string[]
  err?: string
  log: string[]
}
