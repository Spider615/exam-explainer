import RichText from './RichText'
import type { Question } from '../types'

/** 1201 → 「12(1)」，11 → 「11」。小问的编号约定是 主题号*100+小问号 */
function showQnum(n: number) {
  return n >= 100 ? `${Math.floor(n / 100)}(${n % 100})` : String(n)
}

/**
 * 把 Ⓐ 读出来的公式定界符归一成 `RichText` 认得的样子。
 *
 * `RichText` 只认**成对的单 `$`**（`text.split('$')`，奇数段才当公式）。
 * 而 `pipeline/grade.py` 的 `norm_expr` 早就记下了实情：Ⓐ 读出来的答案
 * 定界符不统一——有的 `$…$`、有的裸写、有的 `$$…$$`，不去掉的话连互校
 * 都会全线误报。不归一的话，裸写的 `\frac{3mg}{5BL}` 会在页面上原样打出
 * 这串反斜杠；`$$…$$` 里的内容会落在偶数段，同样按纯文本打出来。标准答案
 * 是全页面最要紧的一格，不能是这个下场。
 *
 * 实测「端到端验收卷」（`EXAM_READONLY=1` 直接读库，样本见 sdd 报告）：
 * 单 `$…$`、以及「`$…$` 文字 `$…$`」这种两段各自配对的写法，`RichText`
 * 已经能正确切开，不用碰。真正会露源码的只有一种模式——**整串一个 `$`
 * 都没有，但含 `\` 命令**，比如 `\frac{27m^3g^2R^2}{50B^4L^4} /
 * \frac{9m^3g^2R^2}{25B^4L^4}`。纯文本答案（`AB`、`170 / A`、`288 K`）
 * 没有反斜杠，不会被误伤而包上 `$`；含 `/` 但没有反斜杠的整句解答（比如
 * 「方法一：Q = 27m^3g^2R^2/(50B^4L^4)」）本来就不是合法 LaTeX，同样不碰，
 * 包起来反而会被 KaTeX 当公式硬解析中文和标点。
 *
 * 不改 `RichText` 本身——它是解析试卷那条链也在用的共用组件，这条链自己的
 * 定界符怪癖不该传染过去。
 */
function normalizeMath(text: string): string {
  const t = text.replace(/\$\$/g, '$')
  return !t.includes('$') && t.includes('\\') ? `$${t}$` : t
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
          Ⓐ 的提示词就是让模型「公式用 LaTeX」，但读出来的定界符不统一
          （裸写、$…$、$$…$$ 都出现过），先经 normalizeMath 归一一遍
          （见上面函数的注释，含实测样本）。MathText 要的是后端版面解析器
          产出的 MathML 区间，这条链根本没有那个东西，传它只会原样打出反斜杠 */}
      <dl>
        <dt>标准答案</dt>
        <dd className="ans">
          {q.refAnswer
            ? <RichText text={normalizeMath(q.refAnswer)} />
            /* 留白会被读成「这道题本来就没有」——这是全页面最要紧的一格，
               唯独它之前没说话。「读取失败」是替后端下结论，「暂无」等于没说，
               所以老老实实说清楚是哪一步没认出来 */
            : <span className="dim">这道题没有标准答案 —— Ⓐ 读参考答案时没认出来</span>}
        </dd>

        <dt>官方解答</dt>
        <dd>
          {q.refSolution
            ? <RichText text={normalizeMath(q.refSolution)} />
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

        {/* 题目这一栏优先给**原卷截图**，不给转写的题干。

            转写那一段现在不显示了，理由是它比截图差在两头：Ⓔ 的提示词明确要求
            「插图只用一句话描述、不要转写坐标刻度」（逐点转写一张受力分析图，
            错了没人看得出来），所以它**把图丢了**；而它带回来的 LaTeX 又是
            `$\Delta U_{AB}=\frac{3}{2}p_0V_0+Q$` 这种源码 —— 一道题四个选项
            全是公式的时候，读起来还不如不给。原卷截图两样都有，而且是原件。

            **转写的题干没有被删掉，只是不显示**：③c 判「这道题考什么」靠的就是
            它（Ⓔ 存在的全部理由），库里那一列照旧。

            只有在切不出截图时才退回文字（模型把位置读乱了会整页不切）——
            那时候一片空白比一段源码更糟。退回时走 RichText，让 `$…$` 真的
            渲染成公式，别再打源码。 */}
        <dt>题目</dt>
        <dd>
          {q.stemImage ? (
            <a href={q.stemImage} target="_blank" rel="noreferrer" title="点开看大图">
              <img className="stemshot" src={q.stemImage}
                   alt={`第 ${q.n} 题在原卷上的样子`} />
            </a>
          ) : q.stem ? (
            <>
              {/* 只把 `$$` 收成 `$`，**不套 normalizeMath**：那个函数会把
                  「整串没有 $ 但含 \ 」的文本整个包成公式，而题干大半是中文
                  散句（「如图所示，A\to B 为等压过程」），包起来会被 KaTeX
                  拿去硬解析中文和标点。答案那一格几乎全是公式，题干不是 */}
              <RichText text={q.stem.replace(/\$\$/g, '$')} />
              <p className="dim">（这道题没切出原卷截图，上面是转写的文字）</p>
            </>
          ) : (
            /* 留白会被读成「这道题本来就没有题目」。要明说它为什么没有 */
            <span className="dim">
              还没有这道题的题目 —— 把原卷传进「原卷」那一栏就能读到
            </span>
          )}
        </dd>
      </dl>
    </section>
  )
}
