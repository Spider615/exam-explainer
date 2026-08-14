# 全站 UI 重设计实施计划：暖纸色的「学术编辑台」

**Goal:** 把 `web/` 从「验证性后台」改成面向老师的学术编辑台 —— 暖纸色、深墨蓝、
朱砂点睛；登录、两种上传、两个任务库、试卷详情、答题卡详情全部重做，**业务、接口、
Hash 路由一行不改**。

**Architecture:** 一层设计令牌（`styles.css` 顶部）+ 一层页面壳（`AppShell`）+
若干纯展示组件（`PageIntro`/`StatusBadge`/`MetricCard`/`JobProgress`/`LibraryTable`/
`PaperSidebar`/`SheetResultRow`）。业务组件（`Upload`/`SheetUpload`/`PaperView`/
`SheetView`/`SheetDetail`/`SceneMount`）保留自己的状态机与话术，只换外观与骨架。

**Tech Stack:** React 18 + TypeScript + Vite + 手写 CSS。**不引入 UI 框架、
不引入状态管理库、不引入前端测试框架**（与 2026-08-10 那份计划一致）。

**设计文档：** `docs/superpowers/specs/2026-08-14-ui-redesign-design.md`

---

## Global Constraints

- **一任务一 commit。** 每个任务收尾都要 `cd web && npm run build` 通过，
  且 `.venv/bin/python -m pytest tests/ -q` 不掉队（基线 781 passed）。
- **不改后端**：`pipeline/` 一行不动。不改 `#/paper`、`#/sheet`、`#/sheet/<卷>/s<id>`、
  老地址 `#/p/<卷名>` 的任何规则。
- **不删任何真信息。** 现有页面上每一句「为什么没有」「哪一步没读到」「这是模型写的」
  都要在新版面里找得到位置。收起来可以（`<details>`），删掉不行。
- **失败不许被 UI 掩盖。** 「没读清」不许写成「学生没作答」；「没有产物」不许画成空白；
  动画起不来退回静态首帧 + 明确错误。
- **状态不许只靠颜色说。** 每个状态都要有文字，必要时加符号（`✓` `—` `◐`）。
- **深色模式白拿。** 颜色一律走 `:root` 变量，不许在组件里写死浅色 —— 这个文件顶上
  有一整套 `prefers-color-scheme: dark` 覆盖，绕过它等于只做了一半。
- **动效尊重 `prefers-reduced-motion`**，但**不许因此删掉唯一的运行状态信号**
  （转圈换成半透明静态圈，呼吸点换成常亮）。
- **`:focus-visible` 必须可见**：所有按钮、文件槽、展开项、场景控件。
- 不许 `git add web/dist/`。

## 本期不做

- 手动主题开关（深色仍只跟随系统）。
- 班级、学生账号、分享协作、运营数据。
- 前端测试框架。**每个任务的验收是**：`npm run build` 通过 + 静态版面在
  1440/1024/390 三个宽度上截图核对 + 全量 Python 测试不破。
- 合并 `PaperView` 与 `SheetView`，或把两种上传塞进同一个组件。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `web/src/styles.css` **重写** | 设计令牌、页面骨架、可复用状态组件 |
| `web/src/components/AppShell.tsx` **新建** | 品牌「析题。」、模式导航、账号、页面宽度 |
| `web/src/components/PageIntro.tsx` **新建** | 页面标题、一句说明、右侧辅助动作 |
| `web/src/components/StatusBadge.tsx` **新建** | 成功/运行/停止/警告/失败五种语义，文本必填 |
| `web/src/components/MetricCard.tsx` **新建** | 摘要数字（试卷与答题卡共用） |
| `web/src/components/JobProgress.tsx` **新建** | 上传任务 running/solving/finishing/done/error 的稳定位置 |
| `web/src/components/LibraryTable.tsx` **新建** | 两种任务库共享表面与窄屏退化 |
| `web/src/components/PaperSidebar.tsx` **新建** | 题号目录与快速跳转 |
| `web/src/components/SheetResultRow.tsx` **新建** | 逐题结果行与展开详情（从 `SheetDetail` 拆出） |
| `web/src/App.tsx` 改 | 改用 `AppShell`，路由逻辑不动 |
| `web/src/components/Login.tsx` 改 | 品牌与版面 |
| `web/src/components/Upload.tsx` 改 | 上传卡 + `JobProgress`，日志默认折叠 |
| `web/src/components/SheetUpload.tsx` 改 | 三个材料槽 + `JobProgress`，原地转运行态 |
| `web/src/components/PaperList.tsx` / `SheetList.tsx` 改 | 改用 `LibraryTable` + `StatusBadge` |
| `web/src/components/PaperView.tsx` 改 | 两栏骨架、`MetricCard`、`PaperSidebar` |
| `web/src/components/QuestionCard.tsx` 改 | 题目卡片六段顺序，动画升为主舞台 |
| `web/src/components/SceneMount.tsx` 改 | **只改外观**：画框、控件条、失败态 |
| `web/src/components/SheetView.tsx` / `Sheets.tsx` / `AnswerQuestionCard.tsx` 改 | 统一到新语言 |
| `web/src/components/SheetDetail.tsx` 改 | 先结论后证据：摘要 → 告警一行 → 可筛选逐题 |

**为什么 `SheetResultRow` 单独拆出来**：那一行带着改判、展开详情、原图、半对分数
四套状态，留在 `SheetDetail` 里会让那个文件继续膨胀，而它是全站信息密度最高的一块。

---

## Task 1: 设计令牌与页面壳

**Files:**
- Modify: `web/src/styles.css`（顶部令牌层 + 基础排版 + 焦点 + 动效常量）
- Create: `web/src/components/AppShell.tsx`
- Modify: `web/src/App.tsx`

**做什么：**

1. 令牌层重写。暖纸底、深墨蓝正文、朱砂强调、墨绿成功、琥珀警告、砖红失败；
   标题宋体系、正文人文无衬线、数字等宽；间距按 4px 步进；圆角 10–16px（控件 6–8px）；
   两级阴影；三档动效时长（`--t-fast` 160ms / `--t-mid` 200ms / `--t-slow` 240ms）。
2. `prefers-color-scheme: dark` 改成同品牌的「深墨夜色」，**不改布局与层级**。
3. `AppShell`：品牌「析题**。**」（句点朱砂）+ 两个一级模式（当前项底部朱砂短线）+
   右侧账号与退出。品牌点击回当前模式的任务库。
4. `App.tsx` 把 `.top` / `.modes` / `.wrap` 那三段换成 `<AppShell>`，
   **路由、清理残留、轮询、删除、登出的逻辑一行不动**。

**验收：** 构建通过；四种页面（两个库、两个详情）共用同一层壳；朱砂只出现在
当前模式与主动作上；键盘 Tab 能看见焦点圈；390px 下导航不溢出。

---

## Task 2: 登录页

**Files:** Modify `web/src/components/Login.tsx`、`web/src/styles.css`

**做什么：** 左栏品牌换成「析题。」+ 一句价值说明 + 那条阶段链；右栏表单卡改成
暖纸色系。**验证码那一格的行为一个字不改**（6 位自动提交、固定高度的提示行、
60 秒重发倒计时、后端 hint 原样显示）。`exam-explainer` 退到页脚小字。

**验收：** 邮箱 → 验证码 → 错误 → 重发四条路径都在；390px 下左栏收起、表单占满；
错误出现时按钮不被顶走。

---

## Task 3: 首页与两种上传

**Files:**
- Create: `web/src/components/PageIntro.tsx`、`web/src/components/JobProgress.tsx`
- Modify: `Upload.tsx`、`SheetUpload.tsx`、`App.tsx`、`styles.css`

**做什么：**

1. `PageIntro`：一句说明当前工作流价值的标题 + 说明 + 右侧辅助动作位。
2. `JobProgress`：把两个上传组件里那几段 `banner` 收成**一个稳定位置**的运行卡 ——
   当前步骤、已处理页数/已识别题数、下一步是什么、原始日志 `<details>` 默认折叠。
   **失败时日志入口提升**（默认展开）。
3. `Upload`：单文件上传卡；点完之后卡片原地转运行态，不跳空页。
4. `SheetUpload`：三个材料槽保留（**不许合并成一个智能分类入口**），每槽显示
   用途、必填/建议/选填、已选文件与页序、移除入口；「开始分析」后原地转运行态。

**保留不动：** `follow()` 的轮询与退避、`explainLost()` 的三种句柄失效话术、
撞名改名提示、页序 `byPageOrder`（必须和 `pipeline/pages.py` 一致）、
跑完带答题卡时直接跳结果页。

**验收：** 上传 → 运行 → 完成 → 失败 → 刷新后句柄恢复五条路径的文案都在原位置；
正常态看不到技术日志，失败态一眼能点开。

---

## Task 4: 两个任务库

**Files:**
- Create: `web/src/components/StatusBadge.tsx`、`web/src/components/LibraryTable.tsx`
- Modify: `PaperList.tsx`、`SheetList.tsx`、`styles.css`

**做什么：** 名称、状态、题数、最重要结果排在一行；删除收进每行的「更多」菜单
（**确认框里仍要列出删的是哪几份**）；运行中/已完成/已停止/需留意同时用文字与颜色；
390px 下整行转成卡片，不横向滚动。空状态说清楚「还没有」而不是留白。

**保留不动：** 批量选择与 `bulkbar`、`Prog` 那套「失败/在跑/已完成/已停止 + 停在哪」
的判据、两个库不同的列（试卷库是插图/动画/告警，答题卡库是带解答/挂知识点）。

**验收：** 空、运行中、已完成、带告警、删除确认五种状态；390px 无横向溢出。

---

## Task 5: 试卷详情

**Files:**
- Create: `web/src/components/MetricCard.tsx`、`web/src/components/PaperSidebar.tsx`
- Modify: `PaperView.tsx`、`QuestionCard.tsx`、`SceneMount.tsx`、`styles.css`

**做什么：**

1. 桌面两栏：190–220px 固定目录 + 自适应正文；正文顶部只留卷名、阶段概述、
   少量统计（`MetricCard`）。手机端目录改成横向快速跳转，正文单列。
2. `QuestionCard` 严格按六段排：① 题号/题型/分值/可信度/原卷对照 → ② 题干与选项 →
   ③ 知识点与卷面参考答案 → ④ **动态讲解（有动画默认展开，紧跟题干）** →
   ⑤ 答案与解题步骤 → ⑥ 假设、失败原因、低频技术信息。
3. `SceneMount` **只改外观**：画布给正式画框，控件条（暂停/重播/时间轴/倍速/多情形）
   收成一条，失败时静态首帧 + 明确错误。
   **读数面板不另画** —— 它由 `scenegen` 生成在场景 SVG 内部（`panel_svg`），
   在外面再画一个等于凭空造第二份数值。
4. 全卷顶部保留「全部暂停/播放」。

**保留不动：** 阶段格子四态与它们的 `title` 话术、`jumpTo` 用 `scrollIntoView`
（**不许改成 `<a href="#q3">`**，那会被 hash 路由当成关掉卷子）、`shortOf` 五分支、
重跑动画的 409 处理、页脚那段 AI 声明、场景帧循环与键盘控制。

**验收：** 1440/1024 双栏；390 单列；有动画的题动画默认可见且控件可用；
动画失败退回静态首帧；目录跳转不改地址。

---

## Task 6: 答题卡诊断结果页

**Files:**
- Create: `web/src/components/SheetResultRow.tsx`
- Modify: `SheetDetail.tsx`、`styles.css`

**做什么：** 先回答「哪里丢分」，再逐题深挖：

1. 摘要：总分/满分、丢分、**逐题合计与卷面总分是否一致**、错题数、半对数、
   优先提升知识点（按丢分排）。
2. 需要留意的读取/绑定/对账问题**默认收成一行**（现有 `notes` 那套原样保留）。
3. 逐题结果可筛选：全部 / 错 / 半对 / 没读清 / 挂不上题。
4. 桌面一题一行：题号、原图切片、学生答案、正确答案、判定与得分、知识点、
   错因与建议、详情入口。**原图切片必须紧挨判定。** 390px 转一题一卡。
5. 展开后才出现：判定依据、老师红笔答案、官方解答、改判与撤回改判。

**保留不动：** 半对 `◐` 自成一档；「没读清」「空着」「挂不上题」三句不同的话；
改判要问半对得几分；`regrade` 成功后重新拉取；页脚那句「对错与分数来自老师批改」。

**验收：** 首屏能直接回答总分、丢分、错题、优先知识点；筛选后仍能看到原图；
改判与撤回可用；390px 无横向溢出。

---

## Task 7: 答题卡卷子页与全站收尾

**Files:** Modify `SheetView.tsx`、`Sheets.tsx`、`AnswerQuestionCard.tsx`、`styles.css`

**做什么：** 把这三块统一到新语言（`MetricCard`、`StatusBadge`、新的卡片表面）；
`Sheets` 那个「传一份新答题卡」的入口用和上传槽一致的外观。

**收尾清单：**
- 三个宽度（1440/1024/390）逐页扫一遍，确认没有横向溢出、遮挡、展开后够不着的操作；
- `prefers-reduced-motion` 下装饰性动效关掉、运行信号仍在；
- 辅助灰字对比度达标，图片有 `alt`，输入有 `label`，进度与错误有 `aria-live`；
- 移动端主要点击区域 ≥44px；
- `npm run build` + 全量 `pytest` 收尾。

**验收：** 设计文档「完成标准」六条逐条对照。
