# ⑤ 提速：代码接管物理与面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `probe`、读数面板、figcaption 从 ⑤ 的 agent 手里拿走交给代码，让 L4 与 L1 结构性成立；顺带把拖时间轴做出来。

**Architecture:** `pipeline/scenegen.py` 读 spec，用现成的 `speccheck.run_reference()` 拿到 401 点数值表，生成骨架 JS（表 + `probe` + 面板更新 + `step`/`seek`/`reset`）与面板 SVG 片段与 figcaption；agent 只写 `figure.html` 和 `draw.js`（`PERIOD` + `READOUTS` + `drawFrame` + `drawReset`）；`harness/build.py` 把两边拼成 ⑥ 要验的产物。

**Tech Stack:** Python 3.14 + pytest；生成的是 ES5 JavaScript；⑥ 用系统 Chrome 无头。

设计文档：`specs/2026-08-08-scene-codegen-design.md`（含实测数据与两轮自我挑刺记录）。

## Global Constraints

- **agent 碰不到 `probe`。** 不是叮嘱它别改，是分文件 + allow-list 让它够不着。
- **表全精度不截断。** 实测 gzip 后 4–37KB。截断会破坏「采样点上逐位相等」，那是这次改动的全部价值。
- **生成的 JS 必须是 ES5**：不用 `let/const/=>/class/模板字符串/解构`，`node --check` 要过。
- **没有 `reference` 的 spec 退回现有 agent 流程**，不许硬跑。
- **⑥ 检查的对象一律是 build 之后的产物**（面板的 id 只在 build 后存在）。
- **`figcaption` 拼全部 `must_contain` 原文**，不改写、不省略 —— L1 查的是原文在不在。
- 新模块放 `pipeline/`，门禁工具放 `harness/`，测试放 `tests/`，注释与输出一律中文。
- **前四个任务一个 token 都不烧。** 第五个才实跑。

## 本期不做

「文字压图形」门禁（L6）—— 代码生成会改变文字分布，现在标的阈值到时候不作数。
见设计文档「质量」一节。

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `pipeline/scenegen.py` | spec → 数值表 / 骨架 JS / 面板 SVG / figcaption | 1, 2 |
| `harness/build.py` | 拼装两个产物 + 静态检查 | 3 |
| `harness/CONTRACT.md` | agent 的新契约 | 4 |
| `pipeline/scene.py` | allow-list、提示词、build 前置、`gen` 落库 | 4 |
| `pipeline/schema.sql` `store.py` | `scenes.gen` 一列 | 4 |
| `web/src/components/SceneMount.tsx` | 时间轴、键盘、倍速、case 切换 | 6 |
| `harness/_runtime.js` | 离线页的同一套控件 | 6 |

---

### Task 1: 数值表与 probe 骨架

**Files:**
- Create: `pipeline/scenegen.py`
- Create: `tests/test_scenegen_table.py`

**Interfaces:**
- Produces:
  - `scenegen.table_of(spec) -> dict` — `{case: {量名: [N 个值]}}`，直接调 `speccheck.run_reference`
  - `scenegen.const_keys(table) -> set[str]` — 全程不变的量（`max == min`）
  - `scenegen.probe_js(spec, table) -> str` — 骨架里 `CASES`/`N`/`T`/`probe`/`probeAll` 那一段
  - `scenegen.can_codegen(spec) -> tuple[bool, str]` — 能不能走这条路，不能就说为什么

- [ ] **Step 1: 写失败的测试**

`tests/test_scenegen_table.py`：

```python
# -*- coding: utf-8 -*-
import json, os, subprocess, sys
import scenegen

SPEC = {
    "id": "t1",
    "cases": [{"id": "c1", "label": "甲"}, {"id": "c2", "label": "乙"}],
    "sample_points": 5,
    "probe_keys": ["u", "x", "k"],
    "probe_key_meaning": {"u": "进度", "x": "位移", "k": "常量"},
    "invariants": [],
    "reference": (
        "def probe(u, case):\n"
        "    k = 2.0\n"
        "    x = u * (1.0 if case == 'c1' else 2.0)\n"
        "    return {'u': u, 'x': x, 'k': k}\n"),
}


def test_表的形状():
    t = scenegen.table_of(SPEC)
    assert set(t) == {"c1", "c2"}
    assert set(t["c1"]) == {"u", "x", "k"}
    assert len(t["c1"]["x"]) == 5


def test_采样点是均匀的0到1():
    t = scenegen.table_of(SPEC)
    assert t["c1"]["u"] == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_不同case值不同():
    t = scenegen.table_of(SPEC)
    assert t["c1"]["x"][-1] == 1.0 and t["c2"]["x"][-1] == 2.0


def test_认得出常量列():
    """全程不变的量不该占读数面板的行"""
    assert scenegen.const_keys(scenegen.table_of(SPEC)) == {"k"}


def test_没有reference就说清楚不能走():
    ok, why = scenegen.can_codegen({**SPEC, "reference": ""})
    assert not ok and "reference" in why
    ok, why = scenegen.can_codegen(SPEC)
    assert ok


def test_reference跑不起来也说清楚():
    ok, why = scenegen.can_codegen({**SPEC, "reference": "def probe(u, case):\n    1/0\n"})
    assert not ok and "跑不起来" in why


def test_生成的probe是ES5且能跑():
    """拿 node 直接跑一遍生成的 probe，和 Python 侧的表逐位比"""
    t = scenegen.table_of(SPEC)
    js = scenegen.probe_js(SPEC, t)
    prog = js + """
var bad = 0;
var T2 = %s;
for (var c in T2) for (var k in T2[c]) for (var i = 0; i < T2[c][k].length; i++) {
  var u = i / (N - 1), got = probe(u, c)[k];
  if (got !== T2[c][k][i]) bad++;
}
console.log(bad === 0 ? "SAME" : "DIFF " + bad);
""" % json.dumps(t)
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert r.stdout.strip() == "SAME", r.stdout


def test_生成的js过node_check(tmp_path):
    js = scenegen.probe_js(SPEC, scenegen.table_of(SPEC))
    p = tmp_path / "t.js"
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-300:]


def test_不许出现ES6语法():
    js = scenegen.probe_js(SPEC, scenegen.table_of(SPEC))
    for bad in ("let ", "const ", "=>", "`"):
        assert bad not in js, "生成的骨架里有 ES6 语法：%r" % bad
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_scenegen_table.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'scenegen'`

- [ ] **Step 3: 写 `pipeline/scenegen.py` 的表与 probe 部分**

模块文档要写清三件事：

- **为什么查表不转译**：33 份 `reference` 里有 88 个 `if`、12 个 `for`、2 个 `while`、
  58 个嵌套函数；转译是编译器项目，而且**转错了是静默的**。
- **为什么全精度不截断**：⑥ 在同样的 `sample_points` 上采样，逐位相等是这次改动的
  全部价值；实测 gzip 后才 4–37KB。
- **`can_codegen` 为什么要单独一个函数**：没有 `reference` 的 spec 要**退回 agent 流程**，
  不是硬跑然后失败。

`table_of` 直接调 `speccheck.run_reference(spec)`（现成的，跑在带超时的子进程里）。

`probe_js` 生成的那段见设计文档「生成的骨架」。注意：

- `T` 用 `json.dumps(table, separators=(",", ":"))`，**不 round**。
- 数组下标插值那段要处理 `u >= 1` 的边界（`i` 会越界）。
- 变量名不许和 agent 的 `draw.js` 撞：骨架里的都加前缀或放在闭包最外层，
  而 `draw.js` 只准定义 `PERIOD` / `READOUTS` / `drawFrame` / `drawReset` ——
  **这条由 `build.py` 静态检查**（Task 3）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_scenegen_table.py -v`
Expected: `8 passed`

- [ ] **Step 5: 拿真 spec 跑一遍，量体积**

```bash
.venv/bin/python -c "
import sys, json, gzip; sys.path.insert(0,'pipeline'); import scenegen
for n in ('q4-gen3','q19','q1-gen2'):
    s = json.load(open('specs/%s.spec.json' % n, encoding='utf-8'))
    ok, why = scenegen.can_codegen(s)
    if not ok: print('%-10s 走不了：%s' % (n, why)); continue
    js = scenegen.probe_js(s, scenegen.table_of(s))
    print('%-10s %6.0f KB (gzip %5.0f KB)' % (n, len(js)/1024, len(gzip.compress(js.encode()))/1024))"
```

Expected: q4-gen3 约 21KB / gzip 4KB；q19 约 105KB / gzip 37KB。**跟设计文档里的实测数对得上**。

- [ ] **Step 6: 提交**

```bash
git add pipeline/scenegen.py tests/test_scenegen_table.py
git commit -m "feat: scenegen 第一步 —— 数值表与 probe 骨架

probe 不再由 agent 写，改成由 spec 的 reference 预计算成 401 点数值表。
测试拿 node 真跑一遍生成的 probe，和 Python 侧的表逐位比，不是看着像对。

不转译成 JS 的理由：33 份 reference 里有 88 个 if、12 个 for、2 个 while、
58 个嵌套函数，转译是编译器项目而且转错了是静默的。

没有 reference 的 spec 由 can_codegen 挡下来退回 agent 流程，不硬跑。"
```

---

### Task 2: 面板、figcaption 与完整骨架

**Files:**
- Modify: `pipeline/scenegen.py`
- Create: `tests/test_scenegen_panel.py`

**Interfaces:**
- Produces:
  - `scenegen.pick_readouts(spec, table, declared=None) -> list[str]`
  - `scenegen.panel_svg(spec, keys) -> tuple[str, dict]` — `(SVG 片段, 面板矩形)`
  - `scenegen.caption(spec) -> str` — figcaption 内容
  - `scenegen.skeleton(spec) -> dict` — `{"js": …, "panel": …, "caption": …, "rect": …}`

- [ ] **Step 1: 写失败的测试**

`tests/test_scenegen_panel.py`：

```python
# -*- coding: utf-8 -*-
import re
import scenegen
from test_scenegen_table import SPEC

FULL = {**SPEC, "units": "位移x：m；u为无量纲进度",
        "disclosures": [
            {"why": "w1", "must_contain": "当前位移x的数值"},
            {"why": "w2", "must_contain": "本题原题未给出任何数值，画面中的 m,k 均为便于演示设定的示例参数，非原题条件"},
        ]}


# ---------------------------------------------------------------- 显示哪些量
def test_声明了就用声明的():
    assert scenegen.pick_readouts(FULL, scenegen.table_of(FULL), ["x"]) == ["x"]


def test_没声明就自动挑():
    """排除 u 和全程不变的常量列"""
    got = scenegen.pick_readouts(FULL, scenegen.table_of(FULL))
    assert "u" not in got and "k" not in got and "x" in got


def test_声明了不存在的键要当场炸():
    try:
        scenegen.pick_readouts(FULL, scenegen.table_of(FULL), ["nope"])
    except ValueError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("READOUTS 里有 probe_keys 之外的键，必须当场失败")


def test_最多四行():
    t = scenegen.table_of(FULL)
    many = {**FULL, "probe_keys": list("abcdefgh")}
    t2 = {c: {k: [i * 1.0 for i in range(5)] for k in "abcdefgh"} for c in t}
    assert len(scenegen.pick_readouts(many, t2)) <= 4


# ---------------------------------------------------------------- figcaption
def test_caption包含全部must_contain原文():
    """L1 查的是原文在不在产物里。拼进去就必然在 —— 这是 L1 恒真的做法"""
    cap = scenegen.caption(FULL)
    for d in FULL["disclosures"]:
        assert d["must_contain"] in cap


def test_caption不改写不省略():
    long = FULL["disclosures"][1]["must_contain"]
    assert long in scenegen.caption(FULL), "长句不许截断，截了 L1 就不认了"


# ---------------------------------------------------------------- 面板
def test_面板给出矩形():
    svg, rect = scenegen.panel_svg(FULL, ["x"])
    for k in ("x", "y", "w", "h"):
        assert isinstance(rect[k], (int, float))
    assert rect["w"] > 0 and rect["h"] > 0


def test_每个读数一行且带稳定id():
    svg, rect = scenegen.panel_svg(FULL, ["x", "u"])
    assert svg.count("<text") >= 2
    assert re.search(r'id="[^"]*-ro-x"', svg) and re.search(r'id="[^"]*-ro-u"', svg)


def test_行距不小于字盒高():
    """CONTRACT §1.5：行距按盒高算，不是按字号算。代码排就不该压字"""
    svg, rect = scenegen.panel_svg(FULL, ["x", "u"])
    ys = sorted(float(m) for m in re.findall(r'<text[^>]*\by="([\d.]+)"', svg))
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    assert gaps and min(gaps) >= scenegen.LINE_H


def test_骨架四样齐全():
    sk = scenegen.skeleton(FULL)
    assert set(sk) >= {"js", "panel", "caption", "rect"}
    assert "@@DRAW@@" in sk["js"], "必须留出给 draw.js 的插入点"
    for name in ("probe", "probeAll", "updatePanel", "seek", "duration", "cases"):
        assert name in sk["js"], name
```

- [ ] **Step 2: 跑测试确认失败** → **Step 3: 实现** → **Step 4: 跑绿**

实现要点：

- `LINE_H` 取自 `CONTRACT.md` §1.5 的实测盒高（`.n` 类 12.6px），留 2px 余量。
- `caption` 把 `must_contain` 用 `。` 连接，**原文照抄**。
- `panel_svg` 用 `class="n"`（等宽、11px）画数值，`class="u"` 画标签；
  每行两个 `<text>`：标签、数值（`id="<sid>-ro-<key>"`）。
- 面板矩形 = 右上角，宽度按 `最长标签宽 + 最长数值宽` 用字宽表算。

- [ ] **Step 5: 拿真 spec 目视一眼生成的面板**

```bash
.venv/bin/python -c "
import sys, json; sys.path.insert(0,'pipeline'); import scenegen
s = json.load(open('specs/q1-gen2.spec.json', encoding='utf-8'))
sk = scenegen.skeleton(s)
print(sk['panel']); print('矩形', sk['rect']); print('caption:', sk['caption'][:150])"
```

**人看一眼**标签有没有词不达意、数值格式对不对。

- [ ] **Step 6: 提交**

---

### Task 3: `harness/build.py` 拼装与静态检查

**Files:**
- Create: `harness/build.py`
- Create: `tests/test_build.py`

**Interfaces:**
- `build.assemble(workdir, sid, spec) -> list[str]` — 回问题列表，空表示成功
- 产出：覆盖写 `<id>.figure.html`（面板已注入）与 `<id>.js`（骨架 + draw.js）

- [ ] **Step 1: 写失败的测试**

`tests/test_build.py` 要盖住这些（每条一个测试）：

| 检查 | 为什么 |
|---|---|
| 正常路径：拼出来的 `<id>.js` 能过 `node --check` | 基本 |
| `figure.html` 里没有 `<g id="__panel__"/>` → 失败 | 面板没地方放 |
| `draw.js` 缺 `drawFrame` 或 `drawReset` → 失败 | 骨架会引用它们 |
| `draw.js` 里定义了 `probe`/`probeAll`/`updatePanel` → 失败 | **agent 想绕过骨架，必须当场挡住** |
| `READOUTS` 里有 `probe_keys` 之外的键 → 失败 | 面板会生成一个永远是 undefined 的行 |
| `PERIOD` 缺失 → 用默认 6.0，**不失败** | 周期是表现，缺了有合理默认 |
| `PERIOD` 不是正数 → 失败 | `t % PERIOD` 会炸 |
| 有图元的坐标落在面板矩形内 → 失败 | 靠门禁不靠嘱咐 |
| 拼装是幂等的：连跑两次结果一样 | agent 每轮都会跑 |
| `figure.html` 里已有面板（上一轮注入的）→ 覆盖而不是叠加 | 否则每轮多一层面板 |

- [ ] **Step 2-4: 红 → 实现 → 绿**

**幂等**的做法：面板注入到 `<g id="__panel__">…</g>` 里，注入前先清空它的内容。
这样连跑 N 次结果相同。

- [ ] **Step 5: 提交**

---

### Task 4: 接进 ⑤ 的链路

**Files:**
- Modify: `harness/CONTRACT.md`
- Modify: `pipeline/scene.py`
- Modify: `pipeline/schema.sql` `pipeline/store.py`
- Modify: `harness/.readonly.sha256`
- Create: `tests/test_scene_gen_column.py`

- [ ] **Step 1: `scenes` 加 `gen` 一列**

```sql
-- 这个场景是哪套流程产的：agent（模型全写）/ codegen（物理与面板由代码生成）。
-- 两套并存期间出了问题要分得清是谁的锅
ALTER TABLE scenes ADD COLUMN IF NOT EXISTS gen text NOT NULL DEFAULT 'agent';
```

`store.put_scene` 多收一个 `gen` 参数，默认 `'agent'`。**测试盯住：不传时老行为不变。**

- [ ] **Step 2: 改 `CONTRACT.md`**

改动集中在两处：

- §2 `<id>.js` → 改成 `<id>.draw.js`，只准定义 `PERIOD` / `READOUTS` / `drawFrame` / `drawReset`，
  **明写「`probe` 由代码生成，你写了也会被 build.py 挡下来」**。
- §4 验收方式 → `python3 ../../harness/build.py <id> && python3 ../../harness/verify.py <id>`。

§1.5 版面那一节**不动** —— 它管的是 agent 画的部分，仍然有效。
新增一小节：**面板矩形是禁区**，坐标由提示词给出。

- [ ] **Step 3: 改 `scene.py`**

- allow-list：`{sid + ".figure.html", sid + ".draw.js"}`
- 开跑前调 `scenegen.can_codegen(spec)`：不行就**退回现有 agent 流程**并在日志里说原因
- 能走就先把骨架/面板/caption 写进工作目录，并把**面板矩形**拼进提示词
- 沙箱那条路：agent 自己跑 `build.py`；方舟那条路：我们替它跑
- 落库时带上 `gen='codegen'`

- [ ] **Step 4: 重算 `.readonly.sha256`**

`build.py` 是新的门禁前置，**必须进守护清单**；`CONTRACT.md` 改了要重算基线。
不重算的话 `report.py` 会一直报警（它是真的比对哈希的）。

```bash
.venv/bin/python harness/report.py --rebaseline    # 若没有这个开关，按 report.py 里的写法手工重算
```

- [ ] **Step 5: 全量测试 + 提交**

---

### Task 5: 实跑三道题，出数字

**这是决定要不要铺开的那一步。烧 token 从这里开始。**

- [ ] **Step 1: 选题**

一道简单（`q4-gen3`，9 条文字 6 个图元）、一道中等（`q1-gen2`）、
一道曾经失败多轮的（`q16-gen2`，9 轮）。

- [ ] **Step 2: 各跑一次，记三个数**

```bash
.venv/bin/python pipeline/scene.py <卷名> --only <题号> 2>&1 | tee /tmp/codegen-<id>.log
```

记：**轮数**、**单轮耗时**、**门禁失败层**。

- [ ] **Step 3: 填这张表**

| 题 | 旧轮数 | 新轮数 | 旧耗时 | 新耗时 | 失败层变化 |
|---|---|---|---|---|---|
| q4-gen3 | | | | | |
| q1-gen2 | | | | | |
| q16-gen2 | 9 | | | | |

- [ ] **Step 4: 人工目检**

新旧两版并排看。**新的不许更难看。** 特别看：面板统一样式之后挤不挤、
读数选得对不对、figcaption 会不会太长。

- [ ] **Step 5: 判**

- 轮数与耗时都降、目检不差 → 继续 Task 6，之后铺开
- **任一项不达标 → 停下来，把数字写进设计文档，重想。不要因为「方案听起来对」就铺开。**

---

### Task 6: 播放控制

**依赖 Task 1（骨架给出 `duration`/`seek`/`cases`），不依赖 Task 5 的结论。**

**Files:**
- Modify: `web/src/components/SceneMount.tsx`
- Modify: `harness/_runtime.js`
- Modify: `web/src/styles.css`

**两处都要改** —— 离线页 `out.html` 用的是 `_runtime.js`，只改 React 那边的话导出的页面没有时间轴。

七条要求（设计文档「播放控制」一节）：

- [ ] 检测到 `seek`/`duration` 才画时间轴；检测不到退回播放/暂停，**不留拖不动的空条**
- [ ] 拖动时自动暂停，**松手后保持暂停**（演示时松手就跑，话没说完画面已经过去了）
- [ ] 续播对齐：从 `u` 继续时把内部计时置为 `u * duration`
- [ ] 键盘：空格播放/暂停、`←`/`→` 逐帧（±1/N）、`Home` 回 0
- [ ] 倍速 0.5× / 1× / 2×
- [ ] `cases.length > 1` 时给一排按钮切情形
- [ ] 时间轴能用手指拖（投影常配触屏一体机）

- [ ] **验证**：`npx tsc --noEmit` → `npm run build` → 重启后端 → **无头 Chrome 验渲染** → **请老师肉眼看一眼**

---

## 自检

**设计覆盖**

| 设计条目 | 落在哪 |
|---|---|
| 数值表全精度、`probe` 查表 | Task 1 |
| 多 case（`probeAll`） | Task 1 |
| `can_codegen` 退回 agent 流程 | Task 1 + Task 4 |
| figcaption 拼全部 `must_contain` | Task 2 |
| `READOUTS` 与自动挑选 | Task 2 |
| 面板排版按字宽表 | Task 2 |
| 面板矩形进提示词 + build 检查侵入 | Task 2 + Task 3 + Task 4 |
| `draw.js` 不许定义 `probe` | Task 3 |
| `.readonly.sha256` 与 `CONTRACT.md` | Task 4 |
| `scenes.gen` | Task 4 |
| 三个数 + 目检 | Task 5 |
| 播放控制七条、两处都改 | Task 6 |

**三个会踩的坑**

1. **拼装不幂等** —— agent 每轮都跑 build，面板会一层层叠。Task 3 有专门的测试。
2. **`draw.js` 与骨架变量名撞** —— Task 3 静态检查它只定义那四样。
3. **`.readonly.sha256` 忘了重算** —— `report.py` 会一直报警，Task 4 Step 4。

**一个悬着的事**：`PERIOD` 由 agent 定，但它看不到最终效果只能凭感觉。
第一版先这样；Task 5 目检时如果发现普遍太快或太慢，再考虑从 `process_endpoints`
里推一个默认值。
