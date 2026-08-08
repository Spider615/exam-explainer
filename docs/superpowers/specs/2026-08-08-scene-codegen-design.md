# ⑤ 提速：让代码接管物理与读数面板

## 背景

阶段⑤ 是一个沙箱里的 claude agent：读 spec，写 `<id>.figure.html` 和 `<id>.js`，
自己跑 ⑥ 门禁，看报错，改，直到 PASS。一题几分钟到几十分钟，很费 token。

## 测量（这一节是事实，不是设计）

**门禁失败按层，47 次：**

| 层 | 次数 | 是什么 |
|---|---|---|
| **L4 物理断言** | **34** | agent 用 JS 重写了一遍物理，然后算错 |
| L1 静态检查 | 10 | 缺少 spec 要求的披露文字 |
| L3.5 渲染覆盖 | 3 | 有元素没动 / 被甩出画布 |

**产出规模**：36 个场景，`figure.html` 平均 4.2KB，`.js` 平均 177 行。

**轮数**：14 个有记录的场景里 12 个一轮就过。**所以慢不在重试，在单轮本身。**
（极端例子 q16 跨了 26 小时 6 轮。）

**spec 里已经有什么**：`reference` 是一段**可执行的 Python** `probe(u, case)`，
平均 37 行；`invariants` 是可执行断言；`probe_keys` / `probe_key_meaning` 给出量名与
含义；`disclosures[].must_contain` 给出必须显示的文字；`sample_points` = 401。

**结论**：agent 花掉的时间里，最容易出错的那部分（34/47）是在重抄一份
**已经写好、而且已经被 ④b 验证过**的东西。

## 目标

- 把 `probe` 和读数面板从 agent 手里拿走，交给代码确定性生成。
- L4 与 L1 从「靠 agent 写对」变成**结构性成立**。
- agent 的产出从「177 行 JS + 4.2KB SVG」缩到「一个 `drawFrame` + 物理场景图形」。

## 非目标

- **不改交付形式。** 仍然是浏览器里的交互式 SVG + `step(t)`，不换视频。
- **不动 ④ 与 ④b。** spec 的格式和自检一个字不改。
- **不做「连场景也声明式」。** 图元词汇预先定死会让特殊题型画不出来，那是以后的事。
- 不追求「所有题都秒出」—— 画图仍然要模型，仍然要时间。

## 关键决策

| 决策 | 取舍 |
|---|---|
| `probe` 由**预计算数值表**提供，不转译 | 39 份 `reference` 里有 88 个 `if`、12 个 `for`、2 个 `while`、58 个嵌套函数。转译是个编译器项目，而且**转错了是静默的**；查表没有这个风险 |
| 表在 `sample_points` 个点上生成 | ⑥ 就在这些点上采样，**逐位相等**，不是近似 |
| 读数面板由 `disclosures` + `probe_key_meaning` 生成 | 消掉 L1，而且面板恰好是 L5 版面层最容易压字的地方 |
| agent 仍然画物理场景 | 斜面、导轨、粒子、箭头的画法一题一个样，这才是它该干的活 |
| 骨架与绘图**分文件**，由代码拼装 | agent 碰不到 `probe`。「靠嘱咐不如靠门禁」—— 不是叮嘱它别改，是让它够不着 |

**代价**：读数面板全卷统一样式，不再一题一个样。这是有意的 —— 现在恰恰是各写各的面板在压字。

## 架构

```
④ spec ─┬─ reference ──► speccheck.run_reference()  ← 现成的，零新代码
        │                        │  {case: {量名: [401 个值]}}
        │                        ▼
        ├─ disclosures ──►  scenegen.py  ──►  <id>.skel.js
        │  probe_key_meaning                    · 数值表
        │                                       · probe(u,case) 查表+插值
        │                                       · updatePanel(p)
        │                                       · step(t) / reset()
        │                                       · /* @@DRAW@@ */ ← 占位
        │                                  ──►  <id>.panel.svg  读数面板片段
        │
        └─ scene_requirements ──► ⑤ agent ──►  <id>.figure.html  （含 <g id="__panel__"/>）
                                            ──►  <id>.draw.js     （只有 drawFrame + els）
                                                       │
                                    harness/build.py ──┴──►  <id>.figure.html（面板已注入）
                                                             <id>.js（骨架 + drawFrame）
                                                       │
                                                  ⑥ verify.py
```

**每一轮 agent 先 `build.py` 再 `verify.py`。** 它改的永远只有 `figure.html` 和 `draw.js`。

## 生成的骨架长什么样

```js
window.Scenes["<id>"] = function (fig) {
  var svg = fig.querySelector('svg');

  // ── 以下到 @@DRAW@@ 之前，全部由 pipeline/scenegen.py 生成，不要手改 ──
  var CASE = "c1", PERIOD = 6.0, N = 401;
  var T = {"c1": {"u": [...], "alpha": [...], "Fres": [...]}};   // 数值表

  function probe(u, cid) {
    // 查表 + 线性插值。u 落在采样点上时**逐位等于** reference 的输出
    var col = T[cid] || T[CASE], x = u * (N - 1), i = Math.floor(x), f = x - i;
    if (i >= N - 1) { i = N - 2; f = 1; }
    var r = {};
    for (var k in col) r[k] = col[k][i] * (1 - f) + col[k][i + 1] * f;
    return r;
  }

  var panel = { alpha: svg.querySelector('#<id>-ro-alpha'), … };
  function updatePanel(p) { panel.alpha.textContent = p.alpha.toFixed(2); … }

  /* @@DRAW@@ */          // ← build.py 把 agent 的 draw.js 插在这里

  return {
    step: function (t) {
      var u = (t % PERIOD) / PERIOD, p = probe(u, CASE);
      updatePanel(p);
      drawFrame(p, u, svg);
    },
    reset: function () { drawReset(svg); },
    probe: probe
  };
};
```

agent 写的 `draw.js` 就两个函数：

```js
function drawFrame(p, u, svg) { … }   // 必需：把 p 里的物理量画成几何
function drawReset(svg) { }           // 必需：清掉轨迹之类的累积状态
```

## 为什么 L4 会恒真

1. ④b `speccheck.check()` 已经用 `spec.invariants` 验过 `spec.reference` —— 通不过的 spec
   根本进不了 ⑤。
2. 表由 `run_reference` 生成，**就是 `reference` 的输出**。
3. ⑥ 的 L4 在 `sample_points` 个点上调 `probe`，而表正是在这些点上生成的 —— 逐位相等。
4. 求值逻辑两处**逐字一致**（`speccheck.check` 的注释里已经写死了这条）。

所以断言不可能不过。**L4 仍然保留**，它的职责从「查 agent 写没写对」变成
「查表生成本身有没有 bug」—— 这是两码事，都要有人管。

## 数据量

401 点 × 平均 10 个量 × 8 字节 ≈ 32KB/场景（JSON 文本约 60KB，gzip 后约 8KB）。
现在 `.js` 平均 5KB，涨了一个量级。

**减小的办法先不做**（降采样、只存独立量在前端算派生量）：它们都会破坏「逐位相等」
这条结构性保证，而那是这次改动的全部价值。等真的嫌大了再说，届时先量再改。

## 面板怎么生成

从 `disclosures[].must_contain` 拿要显示的东西，从 `probe_key_meaning` 拿标签，
排成右上角一列：

```
α = 1.57 rad
F合 = 1.41 F
```

三条规则：

- **每个 `must_contain` 必须对应到一行**。对不上就在生成时报错，不生成 ——
  L1 要在**生成期**就成立，而不是等门禁去抓。
- 行距按实测字宽表算（`CONTRACT.md` §1.5 那张表），**代码排不会压字**。
- 面板占据的矩形区域写进骨架的一个常量，agent 画图时要避开它 —— 这是它唯一
  需要知道的面板信息。

## 迁移

**现有 36 个场景不动。** 它们已经过了门禁、已经在页面上跑。新骨架只对**新生成的**
场景生效。

`scenes` 表加一列 `gen` 记「这个场景是哪套流程产的」（`agent` / `codegen`），
出问题时分得清。

## 风险

| 风险 | 怎么办 |
|---|---|
| 插值在非采样点上与 `reference` 有微小偏差 | L4 只在采样点上跑，不受影响；`step` 渲染用不到那个精度 |
| 表太大拖慢页面 | 先量再改。gzip 后约 8KB，比一张插图小 |
| agent 不适应新契约，反而更容易失败 | **先拿一道已经过了的题重跑**（如 q19），对比轮数与耗时，再决定要不要铺开 |
| `reference` 跑不起来 | ④b 已经拦过一道；这里再拦一道，报错说清楚是 spec 的问题不是场景的问题 |

## 验收

**这次改动的成败只看两个数**，拿同一道题新旧各跑一次比：

1. **单轮耗时**（agent 写的东西少了多少）
2. **轮数**（L4/L1 是不是真的不再失败）

先跑 3 道题（一道简单、一道中等、一道曾经失败多轮的），数字不好看就停下来重想，
不要因为「方案听起来对」就铺开。

## 实施顺序

| 步 | 做什么 |
|---|---|
| 一 | `scenegen.py`：spec → 数值表 + probe + 面板 + 骨架。**纯代码，可单测** |
| 二 | `harness/build.py`：拼装 `figure.html` 与 `<id>.js`，并加静态检查（占位符在不在、面板行数对不对） |
| 三 | 改 `CONTRACT.md` 与 `scene.py` 的 allow-list，agent 只准写两个文件 |
| 四 | 拿 3 道题实跑对比，出数字 |
| 五 | 数字好看再铺开；不好看就停 |

第一步和第二步都是纯代码、可单测、不烧 token。**第四步之前不碰 ⑤ 的正式链路。**
