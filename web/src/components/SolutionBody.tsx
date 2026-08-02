import RichText from './RichText'
import type { Solution } from '../types'

const CONF: Record<string, { label: string; cls: string }> = {
  high: { label: '模型自评 高', cls: 'pill' },
  medium: { label: '模型自评 中 · 建议核对', cls: 'pill w' },
  low: { label: '模型自评 低 · 需人工复核', cls: 'pill w' },
}

/**
 * 断言的状态说的是「④b 自检」，不是人审 —— 这两件事差得远，措辞不能含糊。
 *
 * 自检做的是一次计算：拿 spec 自带的参考实现跑出数据，再用 spec 自己的断言去验它。
 * 它能抓住「受力方程和终点值互相矛盾」，抓不住「从一开始就理解错题、但写得自洽」。
 * 后者要对照原卷，是人的活 —— 所以这里绝不能写成「已通过审核」。
 */
const SPEC_NOTE: Record<string, string> = {
  approved: '④b 自检通过：spec 自带的参考实现满足它自己的全部断言。'
    + '这只排除了内部矛盾 —— 若解法从一开始就理解错题，这一关照样全绿，仍需对照原卷。',
  rejected: '④b 自检未过：spec 自己的参考实现满足不了它自己的断言，或者没有参考实现验不了。'
    + '这道题不会进 ⑤ 生成动画。',
  draft: '还没跑 ④b 自检。这些断言没有被任何东西检验过。',
}

/**
 * 一段模型给出的解法。
 *
 * 这个组件的重点不是把讲解排得好看，而是**让读者知道这段东西有多可信**。
 * 可视化和讲解最擅长掩盖错误：一段条理清晰的推导讲错了，读者会信。
 * 所以三样东西必须和结论同框出现，不能折叠、不能省略：
 *
 *   · 它是模型生成的，没有经过人审
 *   · 模型自己的置信度
 *   · 它自己补上的、题面没给的前提（assumptions）
 *
 * 最后一条尤其关键。阶段④ 的物理断言就架在这些假设上 —— 假设错了，
 * 断言会「错得自洽」，门禁全绿而物理是错的。读者能看见假设，才有机会发现这件事。
 */
export default function SolutionBody({ s }: { s: Solution }) {
  const conf = CONF[s.confidence] ?? CONF.low
  const checked = s.nInvariants > 0

  return (
    <div className="sol">
      <div className="sol-hd">
        <span className="pill a">模型生成 · 未经人审</span>
        <span className={conf.cls}>{conf.label}</span>
        {checked ? (
          <span className="pill" title={SPEC_NOTE[s.specStatus ?? ''] ?? ''}>
            {s.nInvariants} 条物理断言
            {s.specStatus === 'approved' && ' · 自检自洽'}
            {s.specStatus === 'rejected' && ' · 自检未过'}
            {s.specStatus === 'draft' && ' · 尚未检验'}
          </span>
        ) : (
          <span className="pill">无断言 · 未被检验</span>
        )}
        {s.scenePassed === true && (
          <span className="pill g">动画 · 已过门禁（{s.sceneRounds} 轮）</span>
        )}
        {/* 「做不了」和「没必要」是两件事，页面上要分得清 —— 读者问的是
            「这道题为什么没有动画」，两种答案完全不同 */}
        {s.animatable === false && (
          <span className="pill" title={s.whyNot ?? ''}>不适合做动画</span>
        )}
        {s.animatable !== false && s.worth === false && (
          <span className="pill" title={s.worthWhy ?? ''}>未选做动画</span>
        )}
        {s.model && <span className="sol-model">{s.model}</span>}
      </div>

      {s.answer && (
        <div className="sol-ans">
          <span className="sol-ans-lbl">答案</span>
          <span><RichText text={s.answer} /></span>
        </div>
      )}

      <ol className="sol-steps">
        {s.steps.map((x, i) => <li key={i}><RichText text={x} /></li>)}
      </ol>

      {s.assumptions.length > 0 && (
        <div className="sol-asm">
          <b>解题时自行补充的前提（题面未给出）</b>
          <ul>{s.assumptions.map((x, i) => <li key={i}><RichText text={x} /></li>)}</ul>
          <p>这些不是题目条件，是模型自己补的。结论正确与否取决于它们成不成立。</p>
        </div>
      )}
    </div>
  )
}
