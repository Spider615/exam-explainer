import RichText from './RichText'
import type { Question } from '../types'

/** 1201 → 12（主题号）。小问的编号约定是 主题号*100+小问号 */
export function mainOf(n: number) {
  return n >= 100 ? Math.floor(n / 100) : n
}

/** 1201 → 1（第几小问）。不是小问回 0 */
function subOf(n: number) {
  return n >= 100 ? n % 100 : 0
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
 * 答题卡模式的一道**大题**（含它下面所有小问）。
 *
 * **一道大题一张卡，不是一个小问一张卡。** 原来是按题号逐条渲染，于是第 13 题
 * 的 4 个小问各占一张卡，而它们共用同一段题干、同一张原卷截图 —— 那张整页宽
 * 的截图被重复贴了 4 遍，屏幕上翻半天还在同一道题里。
 *
 * 合起来之后：截图只出现一次，下面按小问列各自的标准答案和知识点 ——
 * 那两样本来就是逐小问不同的（13(4) 挂的是「误差与有效数字」，13(1) 不是）。
 *
 * **和解析试卷那张卡是两个组件，故意的。** 这边没有 AI 解法、没有动画、
 * 没有重跑按钮；这边的答案是**老师给的参考答案**，不是模型算出来的 ——
 * 两套话术缠在一个组件里，迟早会有一句串到另一边去（判卷的话出现在
 * 一份高考真题上，已经发生过一次）。
 */
export default function AnswerQuestionCard({ main, parts }: {
  main: number
  /** 这道大题下的小问，按题号排好。没有小问的题就是它自己一条 */
  parts: Question[]
}) {
  // 小问共用同一段题干和同一张截图（Ⓔ 是按主题号回填的），取有的那一个
  const shot = parts.find((p) => p.stemImage)?.stemImage ?? null
  const stem = parts.find((p) => p.stem)?.stem ?? null
  const split = parts.length > 1 || parts.some((p) => p.n >= 100)
  // 一道大题里一条官方解答都没有时，只说一次；逐小问各说一遍是纯噪音
  const anySolution = parts.some((p) => p.refSolution)

  return (
    <section className="acard" id={`q${main}`} tabIndex={-1}>
      <h3>第 {main} 题{split && <em>{parts.length} 小问</em>}</h3>

      {/* 题目这一栏优先给**原卷截图**，不给转写的题干。

          转写那一段不显示，理由是它比截图差在两头：Ⓔ 的提示词明确要求
          「插图只用一句话描述、不要转写坐标刻度」（逐点转写一张受力分析图，
          错了没人看得出来），所以它**把图丢了**；而它带回来的 LaTeX 又是
          `$\Delta U_{AB}=\frac{3}{2}p_0V_0+Q$` 这种源码 —— 一道题四个选项
          全是公式的时候，读起来还不如不给。原卷截图两样都有，而且是原件。

          **转写的题干没有被删掉，只是不显示**：③c 判「这道题考什么」靠的就是
          它（Ⓔ 存在的全部理由），库里那一列照旧。

          只有在切不出截图时才退回文字（模型把位置读乱了会整页不切）——
          那时候一片空白比一段源码更糟。 */}
      <div className="acard-q">
        {shot ? (
          <a href={shot} target="_blank" rel="noreferrer" title="点开看大图">
            <img className="stemshot" src={shot} alt={`第 ${main} 题在原卷上的样子`} />
          </a>
        ) : stem ? (
          <>
            {/* 只把 `$$` 收成 `$`，**不套 normalizeMath**：那个函数会把
                「整串没有 $ 但含 \ 」的文本整个包成公式，而题干大半是中文
                散句（「如图所示，A\to B 为等压过程」），包起来会被 KaTeX
                拿去硬解析中文和标点。答案那一格几乎全是公式，题干不是 */}
            <RichText text={stem.replace(/\$\$/g, '$')} />
            <p className="dim">（这道题没切出原卷截图，上面是转写的文字）</p>
          </>
        ) : (
          /* 留白会被读成「这道题本来就没有题目」。要明说它为什么没有 */
          <p className="dim">还没有这道题的题目 —— 把原卷传进「原卷」那一栏就能读到</p>
        )}
      </div>

      {parts.map((q) => (
        <dl key={q.n} className={split ? 'sub' : undefined}>
          {split && <dt className="sub-n">（{subOf(q.n) || 1}）</dt>}
          {split && <dd />}

          <dt>标准答案</dt>
          <dd className="ans">
            {q.refAnswer
              ? <RichText text={normalizeMath(q.refAnswer)} />
              /* 留白会被读成「这道题本来就没有」——这是全页面最要紧的一格。
                 「读取失败」是替后端下结论，「暂无」等于没说，所以老老实实
                 说清楚是哪一步没认出来 */
              : <span className="dim">这道题没有标准答案 —— Ⓐ 读参考答案时没认出来</span>}
          </dd>

          {/* 有解答过程才占一行。一道大题四个小问都没有时，下面统一说一句 */}
          {q.refSolution && (
            <>
              <dt>官方解答</dt>
              <dd><RichText text={normalizeMath(q.refSolution)} /></dd>
            </>
          )}

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
        </dl>
      ))}

      {/* 「参考答案上没有」和「我们没读出来」是两句话。参考答案的版式就是
          只有大题给详解，把它说成读取失败是冤枉这份材料 */}
      {!anySolution && (
        <p className="acard-nosol">参考答案上这道题没有解答过程（通常只有大题才有）</p>
      )}
    </section>
  )
}
