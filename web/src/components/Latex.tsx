import { useMemo } from 'react'
import katex from 'katex'

/**
 * 渲染一段 LaTeX。
 *
 * 内容来自视觉模型对原卷截图的识别（阶段②b），不是用户输入。
 * KaTeX 以 throwOnError:false 运行，遇到不认识的宏会原样吐出而不是炸掉整页；
 * 真出错时降级显示原始 LaTeX，**不静默吞掉**——看得见才改得动。
 */
export default function Latex({ tex }: { tex: string }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, {
        throwOnError: false,
        strict: false,
        displayMode: false,
        output: 'html',
      })
    } catch {
      return null
    }
  }, [tex])

  if (!html) return <code className="texfail">{tex}</code>
  return <span className="tex" dangerouslySetInnerHTML={{ __html: html }} />
}
