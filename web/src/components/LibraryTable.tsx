import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

/**
 * 两个任务库共用的表面。
 *
 * **列是各自定的。** 试卷库关心插图/动画/告警，答题卡库关心带解答/挂知识点 ——
 * 强行合成一套列，两边都会多出一列永远是 0 的东西。这里统一的只有：表面、
 * 表头语气、窄屏退化方式。
 *
 * **窄屏退化用 CSS 做，不做第二套 JSX。** 每个 `<td>` 带一个 `data-label`，
 * 640 以下整张表变成一行一张卡、字段名跟在左边。两套 JSX 的话，改一处忘另一处
 * 是必然的 —— 而「手机上少了一列」这种事没人会在桌面上发现。
 */
export default function LibraryTable({ cols, children }: {
  /** `label` 收 ReactNode：试卷库的第一列表头是那个「全选」勾选框 */
  cols: { key: string; label: ReactNode; num?: boolean }[]
  children: ReactNode
}) {
  return (
    <table className="lib">
      <thead>
        <tr>
          {cols.map((c) => (
            <th key={c.key} className={c.num ? 'num' : undefined}>{c.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  )
}

/**
 * 每行末尾的「更多」。**删除收在这里面。**
 *
 * 删除是不可逆的，而它在这一屏上是最低频的动作 —— 让它和「打开」一样一直
 * 摆在手边，是在给误点铺路。收进菜单不等于藏起来：一次点击就够得着，
 * 而确认框里仍然会列出删的是哪几份。
 */
export function RowMenu({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  // 点别处、按 Esc 都要关掉。不关的话，滚动几行之后屏幕上会飘着一个
  // 不知道属于哪一行的菜单
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <div className="rowmenu" ref={box}>
      <button className="rowmenu-btn" aria-haspopup="menu" aria-expanded={open}
              aria-label={label} onClick={() => setOpen((o) => !o)}>⋯</button>
      {open && (
        <div className="rowmenu-pop" role="menu" onClick={() => setOpen(false)}>
          {children}
        </div>
      )}
    </div>
  )
}
