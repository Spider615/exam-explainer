import type { ReactNode } from 'react'

/**
 * 页面开头那三行：这是什么、能得到什么、右边有没有别的入口。
 *
 * **它不是装饰。** 老师进任何一屏，三秒内要知道「这是什么、现在到哪、下一步
 * 做什么」—— 以前壳里只有一个卷名，一个第一次用的人看不出这一屏是干什么的。
 */
export default function PageIntro({ title, lede, aside }: {
  title: ReactNode
  /** 一句话说清这条工作流给的是什么。**说具体的产出，不说愿景** */
  lede?: ReactNode
  /** 右侧辅助动作。主动作不放这儿 —— 主动作是页面正文里那张卡 */
  aside?: ReactNode
}) {
  return (
    <div className="intro">
      <div className="intro-say">
        <h1>{title}</h1>
        {lede && <p>{lede}</p>}
      </div>
      {aside && <div className="intro-aside">{aside}</div>}
    </div>
  )
}
