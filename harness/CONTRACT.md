# 场景契约 v2（含 probe 物理探针）

你要产出**两个文件**，放在你的工作目录下：

```
<id>.figure.html    只含一个 <figure>…</figure>
<id>.js             只含一个 window.Scenes["<id>"] = function(fig){…}
```

`<id>` 由 spec 的 `id` 字段给出。

---

## 1. figure.html

```html
<figure data-scene="<id>"><svg viewBox="0 0 560 H" role="img" aria-label="…">
  …
</svg>
<div class="ctl">…可选的场景自有控件…</div>
<figcaption>…</figcaption></figure>
```

**硬性要求**

- 根元素必须是 `<figure data-scene="<id>">`，`data-scene` 与 `<id>` 完全一致。
- `viewBox` 宽度必须是 **560**；高度自定（建议 240–320）。
- 图内**不得**出现 `<script>`、`<style>`、任何外链（`http`、`https`、`//`、`url(`）。
- **不得**出现 SMIL 动画元素（`<animate>` `<animateTransform>` `<animateMotion>` `<set>`）。
- **不得**写死颜色（`#rrggbb` / `rgb(` / `hsl(`）。只能用下列 class 与 CSS 变量。
- 所有 `id` 必须以 `<id>-` 为前缀（例：`q16-blockA`），避免与同页其它场景冲突。
- 文本不得超出 viewBox。经验值：CJK 约 11–12 px/字，等宽 ASCII 约 6.6 px/字。
  一行文本从 x 起算，`x + 字数×字宽` 必须 < 548。

**可用的 class**

| 线条 | `sk` 主线(墨) `sh` 辅助线(浅) `sa` 强调(靛蓝) `sr` 重点(朱红) `sc` 作图虚线(青) |
| 填充 | `fk` `fa` `fr` `fc` |
| 淡填充 | `wash-a` `wash-r` `wash-c` |
| 文字 | 默认(斜体衬线，用于变量) `u`(中文说明) `n`(等宽数值) 附加色 `a` `r` `c` |

**可用的箭头 marker**：`url(#ak)` `url(#aa)` `url(#ar)` `url(#ac)`（分别对应墨/靛蓝/朱红/青）

**可用的 CSS 变量**：`var(--ink)` `var(--ink2)` `var(--ink3)` `var(--panel)` `var(--line)`
`var(--hair)` `var(--acc)` `var(--acc2)` `var(--cy)` `var(--cy2)` `var(--red)` `var(--red2)`

**控件**（可选）：放在 `<div class="ctl">` 里，用 `<button type="button" class="btn" id="<id>-xxx">`
或 `<input type="range" id="<id>-xxx">`。运行时会把这个 div 搬进控制条。

---

## 2. `<id>.js`

```js
window.Scenes["<id>"] = function (fig) {
  var svg = fig.querySelector('svg');
  // …建立引用、预计算…
  return {
    step: function (t) { … },     // 必需
    reset: function () { … },     // 必需
    probe: function (u, caseId) { … }   // 必需（见下）
  };
};
```

**硬性要求**

- ES5 风格：不用 `let/const/=>/class/模板字符串/解构`。`node --check` 必须通过。
- **禁止**在场景里使用 `requestAnimationFrame` / `setTimeout` / `setInterval` 驱动物理。
  帧循环由统一运行时负责，你只实现 `step(t)`。
- `step(t)`：`t` 是秒、单调递增、由运行时累加。循环/定格由你自己对 `t` 取模实现。
- `reset()`：把内部累积状态（轨迹点、已绘制的标记等）清空。
- 所有 `querySelector('#xxx')` 引用的 id **必须真实存在于你的 figure.html 中**。
  这是历史上最高频的低级错误，静态门禁会逐条检查。

---

## 3. `probe(u, caseId)` —— 本次新增，也是验收的核心

这是把「渲染」和「物理」分开的接口。断言只跑在 `probe` 的返回值上，不看像素。

```js
probe: function (u, caseId) {
  // u ∈ [0,1]：一次完整物理过程的归一化进度（0=过程开始，1=过程结束）
  // caseId：spec 里 cases[] 声明的情形 id
  // 返回：一个普通对象，键为 spec 的 probe_keys，值为该时刻的物理量（数值）
  return { t: …, d: …, vA: …, vB: … };
}
```

**要求**

1. `probe` 必须是**纯函数**：只依据 `(u, caseId)` 计算并返回，**不修改任何 DOM、不改内部状态**。
   连续调用 `probe(0.3,'c1')` 一百次必须返回一模一样的结果。
2. 返回值必须包含 spec `probe_keys` 里列出的**全部**键，每个都是有限数值（不能是 `NaN`/`Infinity`/`undefined`）。
3. **单位以 spec 的 `units` 字段为准**，不是屏幕像素。若 spec 说无量纲化，就返回无量纲值。
4. `u` 的含义是**物理过程进度**，不是屏幕播放时间。若你的动画里有定格、有回放停顿，
   那些不算在 `u` 里 —— `u=1` 必须正好对应物理过程终点（例如"细杆与 B 相碰的瞬间"）。
5. `step(t)` 画出来的东西必须和 `probe` 描述的是同一套物理。二者共用同一份计算最省事。

---

## 4. 验收方式

在工作目录运行：

```
python3 ../../harness/verify.py <id>
```

它会依次跑：**静态门禁 → 无头浏览器加载 → 渲染覆盖 → 逐 case 采样 probe → 逐条断言**，
输出机器可读的报告，最后一行是 `VERDICT: PASS` 或 `VERDICT: FAIL`。

**注意 L3.5 渲染覆盖**：断言只跑 `probe`，看不见你画成什么样。所以额外有一层检查——
figure 里**每个带 id 的元素，必须在某一采样时刻真的画在 viewBox 内**，且画面必须随时间变化。
`opacity=0` 的合法隐藏不会被误伤（`getBBox()` 依然有效，只查位置不查可见性），
但「整组元素被 transform 甩出画布」这类缺陷会被直接抓出来。

> 最常见的成因：把 `translate(cx,cy) rotate(θ)` 误写成 `rotate(θ cx cy)`。
> 这两者不等价——后者是在同一坐标系里绕点旋转，不会搬原点。

你的任务是**迭代直到 PASS**。

> ⚠️ `specs/` 和 `harness/` 下的所有文件都是**只读输入**。
> 不允许修改 spec、不允许修改 verify.py、不允许放宽断言容差、不允许跳过检查。
> 这些文件的哈希会在结束后被核对。如果断言你认为不可能满足，
> 在 `NOTES.md` 里写明理由并停止，而不是去改它。
