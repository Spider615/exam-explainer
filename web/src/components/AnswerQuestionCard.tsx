import MathText from './MathText'
import RichText from './RichText'
import type { Question } from '../types'

/** 1201 → 「12(1)」，11 → 「11」。小问的编号约定是 主题号*100+小问号 */
function showQnum(n: number) {
  return n >= 100 ? `${Math.floor(n / 100)}(${n % 100})` : String(n)
}

/**
 * 答题卡模式的一道题。
 *
 * **和解析试卷那张卡是两个组件，故意的。** 这边没有 AI 解法、没有动画、
 * 没有重跑按钮；这边的答案是**老师给的参考答案**，不是模型算出来的 ——
 * 两套话术缠在一个组件里，迟早会有一句串到另一边去（判卷的话出现在
 * 一份高考真题上，已经发生过一次）。
 */
export default function AnswerQuestionCard({ q }: { q: Question }) {
  return (
    <section className="acard" id={`q${q.n}`} tabIndex={-1}>
      <h3>第 {showQnum(q.n)} 题</h3>

      {/* 标准答案和官方解答走 RichText（按 $...$ 切 LaTeX，交给 KaTeX）——
          Ⓐ 的提示词就是让模型「公式用 LaTeX」。MathText 要的是后端版面解析器
          产出的 MathML 区间，这条链根本没有那个东西，传它只会原样打出反斜杠 */}
      <dl>
        <dt>标准答案</dt>
        <dd className="ans"><RichText text={q.refAnswer ?? ''} /></dd>

        <dt>官方解答</dt>
        <dd>
          {q.refSolution
            ? <RichText text={q.refSolution} />
            /* 「参考答案上没有」和「我们没读出来」是两句话。参考答案的版式就是
               只有大题给详解，把它说成读取失败是冤枉这份材料 */
            : <span className="dim">参考答案上这道题没有解答过程（通常只有大题才有）</span>}
        </dd>

        <dt>知识点</dt>
        <dd>
          {q.kps?.length
            ? q.kps.map((k) => (
                <span key={k.code} className="kp" title={k.why}>
                  {k.name}<i>{k.chapter}</i>
                </span>
              ))
            : <span className="dim">这道题没挂上知识点</span>}
        </dd>

        <dt>题干</dt>
        <dd>
          {q.stem
            ? <MathText text={q.stem} math={q.stemMath ?? []} />
            /* 留白会被读成「这道题没题干」。要明说它为什么没有 */
            : <span className="dim">这道题的题干还没有 —— 要传题目图才读得到</span>}
        </dd>
      </dl>
    </section>
  )
}
