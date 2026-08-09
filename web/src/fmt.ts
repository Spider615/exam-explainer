/**
 * 两个模式都要用的小工具。
 *
 * 放在这里而不是各抄一份：两条链的进度带都要显示「已用时」，抄两份的话
 * 迟早一边改了另一边没改，而这一整轮改动的理由就是消灭这种重复。
 */

/** 秒 → 「1 小时 4 分」。整条链动辄一小时，只显示秒数没人读得出来 */
export function fmtDur(sec: number) {
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分 ${s % 60} 秒`
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`
}
