import type { MathSeg } from '../types'

/**
 * 渲染夹带公式的文本。
 *
 * 公式用 MathML 渲染 —— 分子在上、分母在下，和原卷长得一样。
 * 现代浏览器（Chrome 109+ / Safari / Firefox）原生支持，不需要引任何库，
 * 也就不会有 CSP 或体积问题。
 *
 * MathML 由后端的版面解析器生成（不是模型写的、也不是用户输入），
 * 只含 mfrac/msqrt/msup/msub/mi/mn/mo 这些标记，且内容已做 HTML 转义。
 */
export default function MathText({ text, math }: { text: string; math?: MathSeg[] }) {
  if (!math?.length) return <>{text}</>

  const segs = [...math].sort((a, b) => a.s - b.s)
  const out: React.ReactNode[] = []
  let cur = 0
  segs.forEach((m, i) => {
    if (m.s < cur) return               // 区间重叠，跳过后来的
    if (m.s > cur) out.push(<span key={`t${i}`}>{text.slice(cur, m.s)}</span>)
    out.push(
      <span key={`m${i}`} className="mathml"
            dangerouslySetInnerHTML={{ __html: m.mathml }} />,
    )
    cur = m.e
  })
  if (cur < text.length) out.push(<span key="tail">{text.slice(cur)}</span>)
  return <>{out}</>
}
