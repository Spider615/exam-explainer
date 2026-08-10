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

/** ③c 挂在题上的知识点。name/chapter 由后端从词表带出，前端不存第二份词表 */
export interface KnowledgePoint {
  code: string
  name: string
  chapter: string
  /** 针对这道题的一句话，不是知识点定义 */
  why: string
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
  /** ③c 挂的知识点。空数组 = 没挂上，页面要明说，不能干脆不显示 */
  kps?: KnowledgePoint[]
  /** ②d 从卷子里抽的标准答案 */
  refAnswer?: string | null
  /** null = 还没跑过 ②d；'none' = 跑过但卷子里没有答案。两件事 */
  refAnswerSrc?: string | null
  /**
   * 参考答案里的官方解答过程。
   * null = 参考答案上这道题本来就没有过程（只有大题给详解），**不是**没读出来。
   * 页面上这两件事必须是两句不同的话
   */
  refSolution?: string | null
  /** 卷子答案与 AI 答案是否一致。**null = 比不了，不是对不上** */
  refAnswerAgrees?: boolean | null
  sceneId: string | null
  sceneFigure: string | null
  /** 阶段③ 的解题结果。没解过就是 null，前端必须显式呈现「未生成」 */
  solution: Solution | null
  /** 阶段③ 已结束但没有产出解法时，保留最后一次失败的安全摘要。 */
  solutionFailure: SolutionFailure | null
}

export interface SolutionFailure {
  kind: 'timeout' | 'network' | 'provider' | 'invalid_response' | 'configuration' | 'internal'
  reason: string
  attempts: number
  stage: string
  updatedAt: string
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

/** 一格阶段标志。state 由后端算好，前端只管画 */
export interface StageCell {
  code: string
  label: string
  /** done 做完了 / now 在跑 / todo 还没轮到 / fail 挂在这一格 / empty 跑过了没产物 */
  state: 'done' | 'now' | 'todo' | 'fail' | 'empty'
}

/**
 * 这份卷子属于哪个模式，以及那排格子现在什么样。
 *
 * **格子清单和每格状态都由后端给。** 前端曾经自己写死一份 6 格清单加一张
 * 代号映射表，加阶段时漏改就会「一步全程一格都不亮」——踩过。
 * 而且 web/ 没有测试框架，那段判断放在这边没有任何东西看得住。
 */
export interface ModeInfo {
  code: string
  label: string
  stages: StageCell[]
}

export interface Paper {
  name: string
  /**
   * `'pdf'` 解析试卷 / `'answers_only'` 答题卡诊断。**这是两个功能**，
   * 页面话术要按它分开：解析试卷上没有学生答案要判，判卷的提示一句都不该出现。
   *
   * 进度里也有一份，但那是轮询回来的、带延迟 —— 拿它决定一句话显不显示会闪，
   * 所以整卷自己也带一份。
   */
  sourceKind?: string
  /** 模式与阶段格子，由后端下发 */
  mode?: ModeInfo
  sections: Section[]
  warnings: string[]
  questions: Question[]
  stages: Record<string, boolean>
  /** 灭着的阶段为什么灭（目前只有 ⑦：没跑过 / 产物被删了 / 比库里的数据旧） */
  stageNotes: Record<string, string>
  /** 这份卷子此刻在不在跑。非空时试卷页顶部画进度带 */
  job?: JobBrief | null
  coverage: { solved: number; failed: number; total: number }
  /**
   * 这份卷子下面的答题卡（一个学生一份，可以有多份）。
   * **只有答题卡模式才有这一栏** —— 解析试卷压根没有这回事。
   *
   * 答题卡的进度和失败画在**卡**上，不占上面那排格子：那排是按卷子算的，
   * 装不下「哪一份卡读到第几题」，而且没传答题卡的卷子会永远走不到「已完成」。
   */
  sheets?: SheetBrief[]
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
  /**
   * 'pdf' | 'answers_only'。
   *
   * `answers_only` 是「参考答案 + 题目图」的卷子：没跑过 ①②③，终点是 ③c。
   * 阶段条要按它收缩 —— 否则那几格永远灭着，看起来像卡住了
   */
  sourceKind?: string
  /** 模式与阶段格子，由后端下发 */
  mode?: ModeInfo
  questions: number
  labels: number
  /** 挂上知识点的题数（③c）。分母是题数，不是解出来的题数 */
  kps: number
  /**
   * ③c **判过**几道（不是挂上几道）。
   *
   * 挂不上是允许的结果 —— 参考答案那条链上，只有一个字母答案（`D`/`BC`）的题
   * 判不出考什么，那个字母里真的不含这个信息。进度的分子必须用这个，
   * 否则那份卷子永远到不了「已完成」、页面上永远写着「已停止」。
   */
  kpsJudged?: number
  solutions: number
  solutionFailures: number
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
  /** 最近一次阶段产物或终态失败写入的 Unix 时间戳（秒）。 */
  lastChange: number
  elapsedSeconds: number | null
  /** 网页上传的任务才有的细节（正在解哪道题）；命令行跑的是 null */
  step?: string | null
  last?: string | null
  /**
   * Ⓐ 读参考答案读到第几页 / 共几页。
   *
   * **没有分母的进度条只是个转不停的圈** —— 人分不出「在读第 2 页」和「卡死了」，
   * 而 Ⓐ 一页要一分钟上下，四页起步。两个值都由后端从 refread 自己的输出里抠
   * （`api.read_progress`）；解析试卷那条链没有这两个键，是 null。
   */
  pageDone?: number | null
  pageTotal?: number | null
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
    solved: number; solutionFailures: number; questions: number; elapsedSeconds: number | null
  }
  /** 'pdf' | 'answers_only'。两种模式的列表列头不一样 */
  sourceKind?: string
  /** 有官方解答过程的题数。参考答案的版式就是只有大题给详解，天生小于题数 */
  withSolution?: number
  /** 挂上知识点的题数（③c） */
  kps?: number
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

// ---------------------------------------------------------------- 答题卡（步二）

/** 判定。**`partial` 是这一轮新增的**，页面上用 ◐，不许混进 ✓ 也不许混进 ✗ */
export type Verdict = 'right' | 'partial' | 'wrong' | 'blank' | 'unsure'

/**
 * 谁判的。可信度差一个量级，页面必须分得出来：
 *   teacher_score 照卷子上印的得分判（最可信）
 *   teacher_mark  照红勾红叉判（读不到得分时退回这条）
 *   teacher       老师在页面上改判的
 */
export type VerdictBy = 'teacher_score' | 'teacher_mark' | 'code' | 'model' | 'teacher'

/** 一份答题卡在卷子详情页上的一行 */
export interface SheetBrief {
  id: number
  student: string | null
  nPages: number
  created_at: string
  updated_at: string
  /** 卷子上印的总分。null = 没读到 */
  total: number | null
  answers: number
  wrong: number
  /** 半对几道。**和 wrong 分开数** —— 合在一起，8 道半对的卡会显示「错 2 道」 */
  partial: number
  /** 丢了多少分。薄弱知识点按它排，所以卡片上显示的也该是它 */
  lost: number | null
}

export interface SheetRow {
  n: number
  /** 挂到卷子上的题没有。false = 小问编号对不上，页面要单独列出来请人认 */
  bound: boolean
  answer: string | null
  markRaw: string | null
  /** 老师在旁边红笔写的正确答案（实测题 6 写了 BC）。白捡的第三份对照 */
  red: string | null
  readConf: string | null
  scoreGot: number | null
  scoreFull: number | null
  verdict: Verdict | null
  verdictBy: VerdictBy | null
  /** 为什么这么判。页面要显示 —— 判定的可信度全靠它 */
  verdictWhy: string | null
  /** 老师改判过没有。null = 没改过，显示的是系统原判 */
  teacherVerdict: Verdict | null
  /** 这道题在原图上的切片。**必须挨着判定显示** —— 老师一眼能校对是唯一的红绿灯 */
  crop: string | null
  refAnswer: string | null
  refSolution: string | null
  kps: KnowledgePoint[]
}

/** 这一次 Ⓑ 跑成什么样。**页面要按块说出来**，不能只在后台记一笔 */
export interface SheetReads {
  calls?: { page: number; pass: string; ok: boolean; seconds: number; rows: number; err: string | null }[]
  /** [对得上吗, 一句人话] */
  checksum?: [boolean, string]
  clashes?: { n: number | null; why: string }[]
  /** 小问编号对不上的整题告警 */
  bindWarnings?: { main: number; why: string }[]
  /** 中途停了的理由。有值说明后面几页根本没读 */
  aborted?: string | null
  total?: number | null
}

export interface Sheet extends SheetBrief {
  paper: string
  pages: string[]
  reads: SheetReads
  rows: SheetRow[]
  job: { id: string; state: string; step?: string; pageDone?: number; pageTotal?: number } | null
}
