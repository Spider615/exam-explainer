import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'

/**
 * 一个小格子，点开看大的。
 *
 * 逐题结果那张表里，「题目」和「原图」都只有一格的宽度 —— 缩略图看得出**有**、
 * 看不清**是什么**。所以缩略图上悬浮时压一层眼睛，点开在整屏上看原尺寸。
 *
 * **不用 `<a target="_blank">`。** 新标签页会把老师从这一屏带走：他正在逐题
 * 核对，回来还得找回原来滚到哪了。放大层就地开、Esc 或点空白就关。
 *
 * 放大层里放什么由调用方给（`children`）—— 原卷截图是图，没切出截图的题
 * 是一段转写文字，两者都能放进来。
 */
export default function Zoom({ label, thumb, children, trigger = 'zoom' }: {
  /** 给读屏和 `aria-label` 用的一句话，例如「第 12(3) 题的题目」 */
  label: string
  /** 表格里那一格的样子 */
  thumb: ReactNode
  /** 放大之后看到的东西 */
  children: ReactNode
  /** 触发器的样子：`zoom` 是带边框的缩略图格子，`zoom-link` 是一行小字 */
  trigger?: 'zoom' | 'zoom-link'
}) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', esc)
    // 放大层盖住整屏时，底下那张长表不该还能滚 —— 关掉之后位置也就不会跑
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', esc)
      document.body.style.overflow = prev
    }
  }, [open])

  return (
    <>
      <button type="button" className={trigger} onClick={() => setOpen(true)}
              aria-label={`${label}（点开看大图）`} title="点开看大图">
        {thumb}
        <span className="zoom-eye" aria-hidden="true">
          {/* 一只眼睛。内联 SVG —— 这个项目不装图标库，也不该为一个图标去装 */}
          <svg viewBox="0 0 24 24" width="20" height="20">
            <path d="M1.5 12S5.5 5 12 5s10.5 7 10.5 7-4 7-10.5 7S1.5 12 1.5 12z"
                  fill="none" stroke="currentColor" strokeWidth="1.8"
                  strokeLinejoin="round" />
            <circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor"
                    strokeWidth="1.8" />
          </svg>
        </span>
      </button>

      {/**
        * **必须挂到 `body` 上，不能就地渲染。**
        *
        * 诊断页的根节点是 `<div class="sheet rise">`，而 `.rise` 是个带
        * `transform` 的进入动画 —— **带 transform 的祖先会成为
        * `position:fixed` 的包含块**。就地渲染的话，这层「铺满屏幕」的遮罩
        * 实际铺的是那张几千像素高的表：图被居中到表格中间，也就是屏幕外
        * 几千像素的地方，人只看到整页变暗、什么都没出来。
        *
        * 这个坑在短表上不显形（图恰好落在屏幕底边，看着像「有点靠下」），
        * 行一多就彻底看不见了 —— 所以别指望肉眼在截图上发现它。
        */}
      {open && createPortal(
        // 点空白关掉。里面那块 stopPropagation，免得点内容也关
        <div className="lightbox" role="dialog" aria-modal="true" aria-label={label}
             onClick={() => setOpen(false)}>
          <div className="lightbox-in" onClick={(e) => e.stopPropagation()}>
            {children}
          </div>
          <button type="button" className="lightbox-x" aria-label="关闭"
                  onClick={() => setOpen(false)}>×</button>
        </div>,
        document.body)}
    </>
  )
}
