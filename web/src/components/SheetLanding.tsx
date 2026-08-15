import { useEffect, useRef, useState } from 'react'
import { getPaperSheets } from '../api'
import SheetView from './SheetView'

/**
 * `#/sheet/<卷名>` 落在哪一屏。
 *
 * 这个地址的含义是「**给我看这份卷子的诊断结果**」—— 库里点卷名、上传卡上那个
 * 「去看这份卷子 →」、书签、刷新、老地址 `#/p/<名>` 全落在它上面。所以这里
 * 先问出「该打开哪一份卡」，然后换到 `#/sheet/<卷名>/s<id>`。
 *
 * 四条硬约束：
 *
 * · **一律问端点，不拿列表里那份数据抄近路。** 列表可能是几秒前的：在卷子页
 *   传完一个新学生再退回来，那一行还指着上一份卡 —— 而两份诊断页长得一模一样
 *   （真实数据里学生名常常是空的），跳错了没人看得出来。省下的那次请求
 *   （一份卡摘要，几百字节）不值这个风险，而且判据写两处迟早有一处先改。
 *
 * · **换址用 replace，不用 push。** push 的话历史里会留下这个中转地址，
 *   老师按一次后退就回到它，然后又被解析走 —— 后退键在两页之间来回蹦。
 *
 * · **解析不出来就换成卷子页的地址（同样 replace）。** 一份卡都没有（或者挂着的
 *   全是跑坏的空卡）时那才是该看的一屏：Ⓐ 的进度、每题的标准答案、上传入口
 *   都在那儿。**不能就地渲染而不改地址** —— 那样会留下一个含义会变的地址：
 *   老师在那一屏传完一份卡（地址 push 到 `/s<id>`）再按后退，`#/sheet/<卷名>`
 *   这次解析得出结果了，他会被直接弹回前面去，后退键成了死的。
 *   replace 不留历史格，所以换址不会造成「后退又回到解析器」。
 *
 * · **解析期间不许先把卷子页画出来。** 闪一下再跳走，正是这次要消灭的那种
 *   「中间还有一层」的观感。
 */
export default function SheetLanding({ name, onLand, onNoLanding, onOpenSheet }: {
  name: string
  /**
   * 解析出来了：**换**到这份卡的诊断页（调用方用 replace 改址，不留历史格）。
   * 和下面那个是两件事 —— 这一跳是「把中转地址换掉」，不是一次导航。
   */
  onLand: (id: number) => void
  /** 没有能看的诊断结果：**换**成卷子页的地址（同样 replace） */
  onNoLanding: () => void
  /** 卷子页里点某一份卡：那是**真的一次导航**，要 push */
  onOpenSheet: (id: number) => void
}) {
  /** true = 问过了，没有能看的诊断结果 —— 渲染卷子页 */
  const [none, setNone] = useState(false)
  /**
   * 回调放 ref 里，**effect 只依赖卷名**。
   *
   * 调用方给的是内联箭头函数（每次渲染都是新的身份），直接进依赖数组的话，
   * App 每重渲染一次就重新问一次端点 —— 而这个组件的活是「问一次、跳一次」。
   */
  const land = useRef(onLand)
  const noLand = useRef(onNoLanding)
  useEffect(() => { land.current = onLand; noLand.current = onNoLanding })

  useEffect(() => {
    let alive = true
    setNone(false)
    const fallback = () => { if (!alive) return; setNone(true); noLand.current() }
    getPaperSheets(name)
      .then((r) => {
        if (!alive) return
        if (r.landing) land.current(r.landing)
        else fallback()
      })
      // 问不到（后端重启、会话过期、这份卷子不在了）就退回卷子页 ——
      // 那一屏自己会把「打不开」「连不上」说清楚，这里不该替它编一句
      .catch(fallback)
    return () => { alive = false }
  }, [name])

  // `onNoLanding` 改完地址之后，上层会直接渲染卷子页、这个组件就卸载了 ——
  // 这一行是**兜底**：万一那个回调没能改动路由，也不能让「正在打开…」
  // 一直转下去（永远转的占位条是这一类组件最难查的坏法）
  if (none) return <SheetView name={name} onOpenSheet={onOpenSheet} />
  return <div className="empty"><b>正在打开诊断结果…</b></div>
}
