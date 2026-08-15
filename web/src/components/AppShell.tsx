import Logo from './Logo'
import type { ReactNode } from 'react'

export type Mode = 'paper' | 'sheet'

/**
 * 登录后所有页面共用的这一层壳：品牌、两个一级模式、账号。
 *
 * ```
 * 析题          解析试卷   答题卡诊断                         你@邮箱  退出
 * ──────────────────────────────────────────────────────────────────────
 * 页面内容
 * ```
 *
 * **首页不做永久侧栏。** 那是企业后台的语气，而这一屏只有两件事可做。
 * 固定目录只在试卷详情里出现 —— 那时候它服务的是阅读，不是导航。
 *
 * **页面标题不在这里。** 以前壳里有个 `<h1>{卷名}</h1>`，于是品牌、标题、
 * 返回、账号四样东西挤在同一行争焦点。现在标题归页面自己（`PageIntro`），
 * 壳只回答「这是什么产品、你在哪个模式、你是谁」。
 */
export default function AppShell({ mode, onMode, me, onSignOut, onHome, crumb, wide, children }: {
  mode: Mode
  onMode: (m: Mode) => void
  /** 当前账号。卷子按人隔离，「现在是谁」必须一直看得见 */
  me: string
  onSignOut: () => void
  /** 点品牌回到**当前模式**的任务库 —— 不是回到某个固定首页 */
  onHome: () => void
  /**
   * 返回入口那一行：`{ back, here }`。详情页才给，库页面上没有可返回的地方。
   *
   * 试卷详情在 Task 5 之后有自己的目录（返回入口在目录顶上），但答题卡详情和
   * 答题卡卷子页没有 —— 壳里这一行是它们唯一的退路，不能省。
   */
  crumb?: { back: string; onBack: () => void; here: ReactNode } | null
  /** 试卷页多一栏目录，960 放不下：正文会被挤到 750 出头 */
  wide?: boolean
  children: ReactNode
}) {
  const w = wide ? ' wide' : ''
  return (
    <>
      <header className="shell-top">
        <div className={`shell-bar${w}`}>
          <button className="brand" onClick={onHome} title="回到任务库">
            <Logo />析题
          </button>
          {/* 两个模式是两件事，不是一个筛选器。切过去整屏都换：上传框、
              列表列头、详情页。互相看不见对方的卷子 */}
          <nav className="modes" aria-label="工作流">
            <button className={mode === 'paper' ? 'on' : ''}
                    aria-current={mode === 'paper' ? 'page' : undefined}
                    onClick={() => onMode('paper')}>解析试卷</button>
            <button className={mode === 'sheet' ? 'on' : ''}
                    aria-current={mode === 'sheet' ? 'page' : undefined}
                    onClick={() => onMode('sheet')}>答题卡诊断</button>
          </nav>
          <div className="acct">
            <span className="who" title="卷子按账号隔离，这里只看得到你自己传的">{me}</span>
            <button className="acct-out" onClick={onSignOut}>退出</button>
          </div>
        </div>
      </header>

      {crumb && (
        <div className="shell-crumb">
          <div className={`shell-crumb-in${w}`}>
            <button className="shell-back" onClick={crumb.onBack}>← {crumb.back}</button>
            <span className="shell-here">{crumb.here}</span>
          </div>
        </div>
      )}

      <main className={wide ? 'wrap wide' : 'wrap'}>{children}</main>
    </>
  )
}
