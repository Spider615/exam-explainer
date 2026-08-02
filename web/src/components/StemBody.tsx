import Latex from './Latex'
import MathText from './MathText'
import RichText from './RichText'
import type { Question } from '../types'

/** 单元格内容可能夹带 $...$ 行内公式 */
function Cell({ text }: { text: string }) {
  const parts = text.split('$')
  if (parts.length < 3) return <>{text}</>
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 && p.trim() ? <Latex key={i} tex={p} /> : <span key={i}>{p}</span>,
      )}
    </>
  )
}

/**
 * 题干正文：把 `〔表N〕` 占位符换成真正的表格。
 *
 * 切分阶段把表格里的文字整体摘走了 —— 二维的表塞进一维的题干只会变成乱码。
 * 表的内容由视觉模型另行转写，在这里按占位符插回原位。
 */
export default function StemBody({ q }: { q: Question }) {
  const body = q.stemLatex ?? q.stem
  const chunks = body.split(/(〔[图表]\d+〕)/)

  return (
    <>
      {chunks.map((c, i) => {
        const fm = /^〔图(\d+)〕$/.exec(c)
        if (fm) {
          const f = (q.figMarks ?? []).find((x) => x.id === Number(fm[1]))
          if (!f) return <span key={i} className="tbl-missing">{c}</span>
          return (
            <figure key={i} className="inlinefig">
              <img src={f.url} alt={`第${q.n}题插图`} style={{ width: `${f.widthPct}%` }} />
            </figure>
          )
        }
        const m = /^〔表(\d+)〕$/.exec(c)
        if (!m) {
          if (!c) return null
          return q.stemLatex
            ? <RichText key={i} text={c} />
            : <MathText key={i} text={c} math={q.stemMath} />
        }
        const t = (q.tables ?? []).find((x) => x.id === Number(m[1]))
        if (!t) return <span key={i} className="tbl-missing">{c}</span>
        return (
          <figure key={i} className="qtable">
            {t.caption && <figcaption className="qtable-cap">{t.caption}</figcaption>}
            <div className="qtable-scroll">
              <table>
                <tbody>
                  {t.rows.map((row, r) => (
                    <tr key={r}>
                      {row.map((cell, c2) =>
                        r === 0
                          ? <th key={c2}><Cell text={cell} /></th>
                          : <td key={c2}><Cell text={cell} /></td>,
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {t.images.length > 0 && (
              <details className="optimg-wrap">
                <summary>对照原卷表格</summary>
                {/* 跨页表拼成了一张，原图有两张，都要给 —— 只给上半张就没法核对下半张 */}
                {t.images.map((src, k) => (
                  <img key={k} className="optimg" src={src} alt="原卷表格" loading="lazy" />
                ))}
              </details>
            )}
          </figure>
        )
      })}
    </>
  )
}
