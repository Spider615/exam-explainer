/**
 * 「析题」的标记。
 *
 * 一个墨圈，左半是一块朱砂 —— 就是产品自己在用的那个 **◐（半对）**。
 *
 * 为什么是它：这个工具的主张不是「判对错」，是**丢在哪儿、丢了多少**。
 * 半对是逐题诊断的最小单位，也是设计里唯一被要求「自成一档、不许混进 ✓ 也不许
 * 混进 ✗」的判定。标记直接用产品的语言，不借一个通用比喻。
 *
 * 三处细节都是为了**别变成一个通用图标**：
 *
 * · 分界**斜 20°**。主题切换那类图标的分界永远是正垂直，斜过来就读成
 *   「一笔朱砂划过」，不是一个控件。
 * · 朱砂那半从墨圈里**缩进一道纸缝**。远看是干净的几何形，凑近才看出结构；
 *   16px 下缝糊掉也只是退回「斜分的半对」，不算坏。
 * · 墨色走 `currentColor`、朱砂走 `--hot` —— 暖纸底和深墨夜色两种主题下
 *   都跟着走，不用两套资源。
 */
export default function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 24 24"
         fill="none" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.75" />
      <path d="M13.9 6.3A6.1 6.1 0 1 0 10.1 17.7Z" fill="var(--hot)" />
    </svg>
  )
}
