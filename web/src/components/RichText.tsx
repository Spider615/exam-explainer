import Latex from './Latex'

/**
 * 渲染夹带 `$...$` 行内公式的文本（视觉模型转写的题干）。
 *
 * 只按成对的 `$` 切分；落单的 `$` 当普通字符，不做任何猜测性修补。
 */
export default function RichText({ text }: { text: string }) {
  const parts = text.split('$')
  if (parts.length < 3) return <>{text}</>
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 && p.trim()
          ? <Latex key={i} tex={p} />
          : <span key={i}>{p}</span>,
      )}
    </>
  )
}
