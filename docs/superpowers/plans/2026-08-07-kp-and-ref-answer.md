# 期一：知识点标注与标准答案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给每道题挂上受控词表里的知识点标签、抽出卷子自带的标准答案，并在试卷页上显示出来。

**Architecture:** 新增两个管线阶段，都照 `outline.py`（③b）的形状写 —— 整卷一次调用、纯函数与网络调用分离、缺了就留空不编。③c `kpmark.py` 挂知识点（调 DeepSeek），②c `refans.py` 抽标准答案（纯代码为主）。两者写回 `questions` 表的三个新列，`api.py` 带给前端，`QuestionCard` 显示。

**Tech Stack:** Python 3 + psycopg 3 + Postgres；DeepSeek `/chat/completions`（走 `urllib`，无 SDK）；React + TypeScript（Vite）；pytest（本期新引入）。

## Global Constraints

这些约束来自规格，**每个任务都隐含包含**：

- **只能从词表挑 code。** 模型编出来的 code 一律丢掉，不做模糊匹配、不找「最接近的」。
- **一道题最多挂 3 个知识点。** 超过就截断到前 3 个。
- **挂不上就留空。** `kps` 为 `[]`，页面明说「这道题没挂上知识点」。不硬塞最接近的一个 —— 塞进去的标签会污染薄弱点统计，而且没人看得出来它是塞的。
- **抽不到标准答案就 `ref_answer_src='none'`。** 不留空猜，不拿 AI 答案顶上。
- **不引 sympy。** 本期比答案只做归一化字符串比。
- `why` 是针对**这道题**的一句话（「用动量守恒求碰后速度」），不是知识点定义。
- 所有新的 Python 模块放 `pipeline/`，测试放 `tests/`，与现有布局一致。
- 注释和输出一律中文，与现有代码风格一致。
- **`import api` 需要 `web/dist` 存在**（`api.py` 在模块顶层把 `StaticFiles` 挂在 `/`，目录不存在时构造就抛）。Task 8、Task 9 的测试会 import 它。仓库里现在有这个目录；万一没有，先跑一次 `cd web && npm run build`。

## 本期不做

②c 的「老师另传答案文件」分支、图片试卷、答题卡、诊断报告 —— 分别在期二、期三、期四。

## 一个必须先知道的事实

库里 22 份卷子**一份都没有参考答案段落**（全文「答案」二字合计只出现 6 次，全在题干里）。所以：

- ②c 在现有语料上的**正确行为是 22 卷全部回 `none`**。这不是失败，是本期最强的一道反幻觉门禁（Task 7）。
- 切分逻辑靠合成样本测（Task 6）。真实版式的规则要等拿到一份真正带答案的卷子再补，那属于期三。

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `requirements-dev.txt` | 开发期依赖（pytest）。**不进 `requirements.txt`** —— 那是运行时依赖 | 1 |
| `tests/conftest.py` | 把 `pipeline/` 放进 `sys.path`；建一次性测试库并灌 schema | 1 |
| `pipeline/kp_seed.json` | 受控词表种子数据，15 章 154 条 | 2 |
| `pipeline/kp.py` | 词表的加载、校验、按 code/name/alias 解析 | 2 |
| `pipeline/schema.sql` | 加三列 | 3 |
| `pipeline/store.py` | `put_kps` / `put_ref_answer` / `get_paper` 带出三列 / `progress` 数 kps | 3, 9 |
| `pipeline/kpmark.py` | ③c 知识点标注 | 4 |
| `pipeline/run.py` | 命令行链加 ③c | 5 |
| `pipeline/api.py` | 网页链加 ③c；`stage_of` 加一格；`paper()` 带出三列 | 5, 8, 9 |
| `pipeline/refans.py` | ②c 标准答案抽取 | 6, 7 |
| `web/src/types.ts` | `Question` 加 `kps` / `refAnswer` / `refAnswerSrc` / `refAnswerAgrees` | 8 |
| `web/src/components/QuestionCard.tsx` | 知识点标签、标准答案行、不一致标记 | 8 |

---

### Task 1: 测试地基

这个仓库现在**一个测试都没有**，也没装 pytest。后面每个任务都要写测试，先把地基铺好。

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_conftest_smoke.py`
- Modify: `.gitignore`（加 `.pytest_cache/`）

**Interfaces:**
- Consumes: 无
- Produces: pytest fixture `db`（一次性测试库，session 级），fixture `conn`（一条 `psycopg` 连接，函数级，用完回滚）

- [ ] **Step 1: 装 pytest**

```bash
cat > requirements-dev.txt <<'EOF'
# 开发期依赖。运行时不需要，所以不进 requirements.txt。
#     .venv/bin/pip install -r requirements-dev.txt
pytest==8.3.4
EOF
.venv/bin/pip install -r requirements-dev.txt
```

Expected: `Successfully installed pytest-8.3.4 ...`

- [ ] **Step 2: 写 conftest**

`tests/conftest.py`：

```python
# -*- coding: utf-8 -*-
"""
测试地基。

**必须在 import store 之前设好 DATABASE_URL** —— store.py 在模块顶层就把
DSN 读成了常量，import 之后再改环境变量没有任何作用，测试会安安静静地
连到真库上去，这正是这个项目最不能接受的那种错。
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DB = "exam_explainer_test"
os.environ["DATABASE_URL"] = "postgresql:///" + TEST_DB
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

import pytest
import psycopg


@pytest.fixture(scope="session")
def db():
    """建一个一次性测试库，灌 schema，跑完删掉。"""
    admin = psycopg.connect("postgresql:///postgres", autocommit=True)
    admin.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % TEST_DB)
    admin.execute('CREATE DATABASE "%s"' % TEST_DB)
    admin.close()

    import store
    store.init_schema()
    yield TEST_DB

    admin = psycopg.connect("postgresql:///postgres", autocommit=True)
    admin.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % TEST_DB)
    admin.close()


@pytest.fixture
def conn(db):
    """一条连接，测完回滚 —— 每个测试看到的是同一张干净的库。"""
    c = psycopg.connect("postgresql:///" + db)
    yield c
    c.rollback()
    c.close()
```

- [ ] **Step 3: 写冒烟测试**

`tests/test_conftest_smoke.py`：

```python
# -*- coding: utf-8 -*-
def test_测试库连得上而且不是真库(conn):
    import store
    assert "exam_explainer_test" in store.DSN, "测试连到真库上了"
    row = conn.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='questions'").fetchone()
    assert row[0] == 1
```

- [ ] **Step 4: 跑测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: `1 passed`

- [ ] **Step 5: 忽略缓存目录**

在 `.gitignore` 末尾追加：

```
.pytest_cache/
```

- [ ] **Step 6: 提交**

```bash
git add requirements-dev.txt tests/ .gitignore
git commit -m "test: 加 pytest 地基与一次性测试库

这个仓库此前一个测试都没有。conftest 在 import store 之前就把
DATABASE_URL 指到一次性库，因为 store.py 在模块顶层把 DSN 读成常量 ——
import 之后再改环境变量会安静地连到真库上。"
```

---

### Task 2: 受控词表

**Files:**
- Create: `pipeline/kp_seed.json`
- Create: `pipeline/kp.py`
- Create: `tests/test_kp.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `kp.CHAPTERS` — `tuple[str, ...]`，15 个受控章名
  - `kp.load() -> dict[str, dict]` — code → `{code, chapter, name, aliases}`
  - `kp.validate(entries: list[dict]) -> list[str]` — 问题列表，空表示合法
  - `kp.resolve(s: str) -> str | None` — 按 code / name / alias 精确找 code，找不到回 `None`
  - `kp.catalog_text() -> str` — 喂给模型的词表全文

- [ ] **Step 1: 写词表数据**

`pipeline/kp_seed.json`，一个 JSON 数组，每条 `{"code", "chapter", "name", "aliases"}`。

`code` 的写法：`<章前缀>.<拼音或英文短名>`，全小写，只用 `[a-z0-9_.]`。章前缀固定如下表。

**完整清单（15 章 154 条）**，按 `章前缀 | 章名 | 知识点名（逗号分隔）` 给出。逐条转成 JSON，`aliases` 至少给常见简称，想不出就给 `[]`：

| 前缀 | chapter | name |
|---|---|---|
| `kin` | 运动学 | 参考系与质点、位移速度与加速度、匀变速直线运动规律、v-t 图像、x-t 图像、自由落体运动、竖直上抛运动、追及与相遇问题、平均速度与瞬时速度、多过程直线运动 |
| `dyn` | 相互作用与牛顿运动定律 | 重力与弹力、胡克定律、摩擦力、力的合成与分解、共点力平衡、牛顿第一定律与惯性、牛顿第二定律、牛顿第三定律、超重与失重、连接体问题、传送带模型、板块模型 |
| `circ` | 曲线运动与万有引力 | 运动的合成与分解、平抛运动、斜抛运动、匀速圆周运动、向心力与向心加速度、竖直平面内的圆周运动、水平面内的圆周运动、万有引力定律、天体质量与密度的估算、卫星的运行规律、第一宇宙速度、双星与多星系统、卫星变轨与能量 |
| `energy` | 功和能 | 恒力做功、变力做功、功率、动能定理、重力势能、弹性势能、机械能守恒定律、功能关系、摩擦生热、能量守恒定律 |
| `mom` | 动量 | 冲量与动量定理、动量守恒定律、弹性碰撞、完全非弹性碰撞、爆炸与反冲、人船模型、碰撞中的能量分析 |
| `wave` | 机械振动与机械波 | 简谐运动、单摆、简谐运动的图像、受迫振动与共振、机械波的形成与传播、波长频率与波速的关系、波的图像、波的叠加与干涉、波的衍射、多普勒效应 |
| `estat` | 静电场 | 电荷守恒与库仑定律、电场强度、电场线、电势与电势能、等势面、电势差与场强的关系、静电感应与静电屏蔽、带电粒子在匀强电场中的运动、电容器、示波管原理 |
| `circuit` | 恒定电流 | 电流的定义式、欧姆定律、电阻定律、串联与并联电路、电功与电功率、焦耳定律、闭合电路欧姆定律、电源的效率、电表的改装、伏安特性曲线 |
| `mag` | 磁场 | 磁感应强度、磁感线、安培力、洛伦兹力、带电粒子在匀强磁场中的圆周运动、速度选择器、质谱仪、回旋加速器、磁电式电表原理、复合场中的运动 |
| `emi` | 电磁感应 | 磁通量、法拉第电磁感应定律、楞次定律、右手定则、导体棒切割磁感线、自感与互感、涡流、单棒导轨模型、双棒导轨模型、电磁感应中的能量转化 |
| `ac` | 交变电流 | 交变电流的产生、峰值与有效值、变压器原理、远距离输电、感抗与容抗、交变电流的图像 |
| `thermo` | 热学 | 分子动理论、布朗运动、分子间作用力、阿伏加德罗常数的应用、温度与内能、气体实验定律、理想气体状态方程、热力学第一定律、热力学第二定律、饱和汽与湿度、固体液体与晶体 |
| `optics` | 光学 | 光的折射定律、全反射与光导纤维、光的色散、光的干涉、双缝干涉、薄膜干涉、光的衍射、光的偏振、透镜成像、光速的测定 |
| `modern` | 近代物理 | 光电效应、光子说与普朗克常量、康普顿效应、玻尔原子模型、氢原子能级跃迁、原子核的组成、放射性衰变、半衰期、核反应方程、质能方程与结合能、核裂变与核聚变、波粒二象性与物质波 |
| `exp` | 实验与数据处理 | 打点计时器与纸带处理、游标卡尺与螺旋测微器读数、探究弹力与形变量的关系、验证牛顿第二定律、验证机械能守恒、验证动量守恒、测定电源电动势与内阻、描绘小灯泡伏安特性曲线、测定金属丝的电阻率、用单摆测重力加速度、用双缝干涉测光的波长、误差与有效数字、图像法处理数据 |

头三条长这样，其余照此格式：

```json
[
  {"code": "kin.frame",  "chapter": "运动学", "name": "参考系与质点",
   "aliases": ["参考系", "质点"]},
  {"code": "kin.svа",    "chapter": "运动学", "name": "位移速度与加速度",
   "aliases": ["位移", "速度", "加速度"]},
  {"code": "dyn.newton2","chapter": "相互作用与牛顿运动定律", "name": "牛顿第二定律",
   "aliases": ["牛二", "动力学基本方程", "F=ma"]}
]
```

注意：`code` 只许 `[a-z0-9_.]`，上面第二条里的 `kin.svа` 是示意，实际请写 `kin.sva`（纯 ASCII）—— Step 3 的测试会把非 ASCII 的 code 判红。

- [ ] **Step 2: 写失败的测试**

`tests/test_kp.py`：

```python
# -*- coding: utf-8 -*-
import json, re
import kp


def test_词表自身合法():
    entries = json.load(open(kp.SEED, encoding="utf-8"))
    assert kp.validate(entries) == []


def test_每章都有知识点():
    entries = json.load(open(kp.SEED, encoding="utf-8"))
    got = {e["chapter"] for e in entries}
    assert got == set(kp.CHAPTERS), "缺章：%s" % (set(kp.CHAPTERS) - got)


def test_code_只用小写ascii():
    for code in kp.load():
        assert re.fullmatch(r"[a-z0-9_.]+", code), code


def test_按名字和别名都找得到():
    assert kp.resolve("dyn.newton2") == "dyn.newton2"
    assert kp.resolve("牛顿第二定律") == "dyn.newton2"
    assert kp.resolve("牛二") == "dyn.newton2"
    assert kp.resolve(" 牛顿第二定律 ") == "dyn.newton2"


def test_编出来的一律找不到():
    # **不做模糊匹配。** 「最接近的那个」会把错标签洗成看起来合理的标签
    assert kp.resolve("mech.newton_second_law") is None
    assert kp.resolve("牛顿第二定律的应用") is None
    assert kp.resolve("") is None
    assert kp.resolve(None) is None


def test_validate_抓得到重复的code():
    bad = [{"code": "a.b", "chapter": kp.CHAPTERS[0], "name": "甲", "aliases": []},
           {"code": "a.b", "chapter": kp.CHAPTERS[0], "name": "乙", "aliases": []}]
    assert any("重复" in p for p in kp.validate(bad))


def test_validate_抓得到野章名():
    bad = [{"code": "a.b", "chapter": "玄学", "name": "甲", "aliases": []}]
    assert any("章" in p for p in kp.validate(bad))
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_kp.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'kp'`

- [ ] **Step 4: 写 `pipeline/kp.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kp.py —— 知识点受控词表

    python pipeline/kp.py            校验词表并打印每章条数

为什么要受控词表
----------------
薄弱知识点这个产出的全部价值在于**能跨题聚合**：「动量守恒错了 2 次」这句话
成立的前提是两道题挂的是同一个名字。让模型自由发挥，第 3 题会挂「动量守恒」，
第 6 题会挂「动量守恒定律」，聚合出来是两个各错一次的点 —— 看起来都不严重。

code 是稳定代号而不是自增 id：词表是版本管理的种子数据，重灌一次自增 id
就全漂了，code 不会。

resolve 不做模糊匹配
--------------------
找不到就是找不到。「最接近的那个」会把一个错标签洗成看起来合理的标签，
而没有任何人能从结果里看出它是洗出来的。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "kp_seed.json")

CHAPTERS = ("运动学", "相互作用与牛顿运动定律", "曲线运动与万有引力", "功和能",
            "动量", "机械振动与机械波", "静电场", "恒定电流", "磁场", "电磁感应",
            "交变电流", "热学", "光学", "近代物理", "实验与数据处理")

CODE_RE = re.compile(r"[a-z0-9_.]+")

_by_code = None
_index = None


def validate(entries):
    """返回问题描述列表；空列表表示词表合法。"""
    probs, seen = [], set()
    for i, e in enumerate(entries):
        where = "第%d条" % (i + 1)
        for k in ("code", "chapter", "name"):
            if not str(e.get(k) or "").strip():
                probs.append("%s缺 %s" % (where, k))
        code = e.get("code")
        if code in seen:
            probs.append("%s code 重复：%s" % (where, code))
        seen.add(code)
        if code and not CODE_RE.fullmatch(str(code)):
            probs.append("%s code 只许小写 ASCII、数字、点、下划线：%s" % (where, code))
        if e.get("chapter") not in CHAPTERS:
            probs.append("%s 章名不在受控集合里：%s" % (where, e.get("chapter")))
        if not isinstance(e.get("aliases", []), list):
            probs.append("%s aliases 必须是数组" % where)
    return probs


def load():
    """code → 条目。第一次调用时校验，词表坏了直接抛 —— 它是种子数据，
    不该在运行时静默降级。"""
    global _by_code, _index
    if _by_code is None:
        entries = json.load(open(SEED, encoding="utf-8"))
        probs = validate(entries)
        if probs:
            raise ValueError("kp_seed.json 不合法：\n  " + "\n  ".join(probs))
        _by_code = {e["code"]: e for e in entries}
        _index = {}
        for e in entries:
            for key in [e["code"], e["name"]] + list(e.get("aliases", [])):
                _index[str(key).strip()] = e["code"]
    return _by_code


def resolve(s):
    """按 code / 名字 / 别名**精确**找 code。找不到回 None，不猜。"""
    if not s:
        return None
    load()
    return _index.get(str(s).strip())


def catalog_text():
    """喂给模型的词表全文，按章分组。"""
    by_ch = {}
    for e in load().values():
        by_ch.setdefault(e["chapter"], []).append(e)
    out = []
    for ch in CHAPTERS:
        out.append("【%s】" % ch)
        for e in by_ch.get(ch, []):
            out.append("  %s  %s" % (e["code"], e["name"]))
    return "\n".join(out)


def main():
    entries = json.load(open(SEED, encoding="utf-8"))
    probs = validate(entries)
    if probs:
        print("✗ 词表不合法：")
        for p in probs:
            print("  ·", p)
        return 1
    by_ch = {}
    for e in entries:
        by_ch[e["chapter"]] = by_ch.get(e["chapter"], 0) + 1
    print("✓ 词表合法，共 %d 条" % len(entries))
    for ch in CHAPTERS:
        print("   %-16s %d" % (ch, by_ch.get(ch, 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_kp.py -v`
Expected: `7 passed`

Run: `.venv/bin/python pipeline/kp.py`
Expected: `✓ 词表合法，共 154 条`，随后 15 行每章条数

- [ ] **Step 6: 提交**

```bash
git add pipeline/kp.py pipeline/kp_seed.json tests/test_kp.py
git commit -m "feat: 加知识点受控词表（15 章 154 条）

薄弱知识点能聚合的前提是两道题挂的是同一个名字。让模型自由发挥，
第3题挂「动量守恒」、第6题挂「动量守恒定律」，聚合出来是两个各错
一次的点 —— 看起来都不严重。

resolve 不做模糊匹配：找不到就是找不到。「最接近的那个」会把错标签
洗成看起来合理的标签，而没人能从结果里看出它是洗出来的。"
```

---

### Task 3: 三个新列与读写

**Files:**
- Modify: `pipeline/schema.sql`（文件末尾追加）
- Modify: `pipeline/store.py`（`get_paper` 的 SELECT 列表；文件内新增两个函数）
- Create: `tests/test_store_kps.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `store.put_kps(qid: int, kps: list[dict]) -> None` — 写 `questions.kps`，`kps` 形如 `[{"code": str, "why": str}]`
  - `store.put_ref_answer(qid: int, text: str | None, src: str) -> None` — `src` ∈ `{"paper", "answer_file", "none"}`
  - `store.get_paper(name)` 返回的每道题多出 `kps` / `ref_answer` / `ref_answer_src` 三个键

- [ ] **Step 1: 写失败的测试**

这里要测的核心是**重新发布不能把这三列冲掉** —— `label` 已经有过这个先例，`publish` 的 upsert 只更新它列出来的那些列。新列必须同样不被列进去。

`tests/test_store_kps.py`：

```python
# -*- coding: utf-8 -*-
import json, os
import store


def _make_work(tmp_path, name="测试卷", ns=(1, 2)):
    """造一个最小的构建产物目录，够 publish 用。"""
    d = tmp_path / name
    d.mkdir()
    (d / "questions.json").write_text(json.dumps({
        "source": "x.pdf", "sections": [], "warnings": [],
        "questions": [{"n": n, "type": "单选题", "stem": "第%d题题干" % n,
                       "options": [], "tables": [], "figures": []} for n in ns],
    }, ensure_ascii=False), encoding="utf-8")
    return str(d)


def test_写得进去也读得回来(db, tmp_path):
    work = _make_work(tmp_path, "kps卷A")
    store.publish(work, name="kps卷A")
    paper = store.get_paper("kps卷A")
    q1 = paper["questions"][0]
    assert q1["kps"] == []
    assert q1["ref_answer"] is None
    assert q1["ref_answer_src"] is None

    store.put_kps(q1["id"], [{"code": "mom.conserve", "why": "用动量守恒求碰后速度"}])
    store.put_ref_answer(q1["id"], "BD", "paper")

    q1 = store.get_paper("kps卷A")["questions"][0]
    assert q1["kps"] == [{"code": "mom.conserve", "why": "用动量守恒求碰后速度"}]
    assert q1["ref_answer"] == "BD"
    assert q1["ref_answer_src"] == "paper"


def test_重新发布不冲掉这三列(db, tmp_path):
    """label 已经有过这个先例：publish 的 upsert 只更新它列出来的列。
    新列一旦被列进 DO UPDATE SET，重跑一次 ② 就把 ③c 的产出全冲没了。"""
    work = _make_work(tmp_path, "kps卷B")
    store.publish(work, name="kps卷B")
    qid = store.get_paper("kps卷B")["questions"][0]["id"]
    store.put_kps(qid, [{"code": "kin.free_fall", "why": "自由落体求时间"}])
    store.put_ref_answer(qid, "0.4 m", "paper")

    store.publish(work, name="kps卷B")          # 再发布一次

    q1 = store.get_paper("kps卷B")["questions"][0]
    assert q1["id"] == qid, "重新发布不该换 id"
    assert q1["kps"] == [{"code": "kin.free_fall", "why": "自由落体求时间"}]
    assert q1["ref_answer"] == "0.4 m"


def test_抽不到答案记成none(db, tmp_path):
    work = _make_work(tmp_path, "kps卷C")
    store.publish(work, name="kps卷C")
    qid = store.get_paper("kps卷C")["questions"][0]["id"]
    store.put_ref_answer(qid, None, "none")
    q1 = store.get_paper("kps卷C")["questions"][0]
    assert q1["ref_answer"] is None
    assert q1["ref_answer_src"] == "none", "抽不到也要留痕，不能是 NULL"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_store_kps.py -v`
Expected: FAIL，`AttributeError: module 'store' has no attribute 'put_kps'`

- [ ] **Step 3: 加三列**

在 `pipeline/schema.sql` **文件末尾**追加：

```sql
-- ---------------------------------------------------------------- 期一：知识点与标准答案
-- kps 用 jsonb 存 [{code, why}] 而不是关联表：范围是单人单卷十几道题，
-- 聚合在应用层做就够。代价是 code 没有外键保护，所以 ③c 写入时要拿
-- kp_catalog 校一遍（见 kpmark.keep），挂不上的明说挂不上。
ALTER TABLE questions ADD COLUMN IF NOT EXISTS kps jsonb NOT NULL DEFAULT '[]';
-- 卷子上的标准答案。ref_answer_src 三个值：
--   paper        从题目那份文件里抽出来的
--   answer_file  老师另传的答案文件（期三）
--   none         抽不到。**这一列不许留 NULL** —— 「没抽到」和「还没跑过 ②c」
--                是两件事，页面上要分得出来
ALTER TABLE questions ADD COLUMN IF NOT EXISTS ref_answer     text;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS ref_answer_src text;
```

- [ ] **Step 4: 加两个写函数**

在 `pipeline/store.py` 里 `put_outline` 函数**之后**插入：

```python
def put_kps(qid, kps):
    """
    写这道题的知识点标签。`kps` 形如 `[{"code": ..., "why": ...}]`。

    整体替换而不是追加：③c 是整卷一次调用，每次都给出这道题的完整清单，
    追加会让重跑一次就变成两倍标签。
    """
    with connect() as c:
        c.execute("UPDATE questions SET kps=%s WHERE id=%s",
                  (json.dumps(kps, ensure_ascii=False), qid))
        c.commit()


def put_ref_answer(qid, text, src):
    """
    写卷子上的标准答案。`src` 必须是 paper / answer_file / none 之一。

    抽不到也要写一行（text=None, src='none'）—— 「抽不到」和「还没跑过 ②c」
    在页面上是两句不同的话，靠这一列区分。
    """
    if src not in ("paper", "answer_file", "none"):
        raise ValueError("ref_answer_src 只能是 paper/answer_file/none，给的是 %r" % src)
    with connect() as c:
        c.execute("UPDATE questions SET ref_answer=%s, ref_answer_src=%s WHERE id=%s",
                  (text, src, qid))
        c.commit()
```

- [ ] **Step 5: 让 `get_paper` 带出这三列**

在 `pipeline/store.py` 的 `get_paper` 里，把 SELECT 的列清单

```python
                              quality_reason, n_chars, pages, label,
                              anim_worth, anim_why,
```

改成

```python
                              quality_reason, n_chars, pages, label,
                              anim_worth, anim_why,
                              kps, ref_answer, ref_answer_src,
```

（`qs` 是用 `cur.description` 动态建的字典，加了列就自动带出来，不用改别处。）

- [ ] **Step 6: 灌 schema 并跑测试**

```bash
.venv/bin/python pipeline/store.py init
.venv/bin/pytest tests/test_store_kps.py -v
```

Expected: `3 passed`

- [ ] **Step 7: 提交**

```bash
git add pipeline/schema.sql pipeline/store.py tests/test_store_kps.py
git commit -m "feat: questions 加 kps / ref_answer / ref_answer_src 三列

三列都不进 publish 的 DO UPDATE SET —— label 已经有过这个先例，
列进去的话重跑一次 ② 就把 ③c 的产出全冲没了。测试直接盯这一点。

ref_answer_src 不许留 NULL：「抽不到」和「还没跑过 ②c」是两件事。"
```

---

### Task 4: ③c 知识点标注

照 `outline.py`（③b）的形状写：整卷一次调用、纯函数与网络调用分开、缺了留空不编。

**Files:**
- Create: `pipeline/kpmark.py`
- Create: `tests/test_kpmark.py`

**Interfaces:**
- Consumes: `kp.load()`、`kp.resolve()`、`kp.catalog_text()`、`store.get_paper()`、`store.paper_solutions()`、`store.put_kps()`
- Produces:
  - `kpmark.keep(rows: list[dict], valid_ns: set[int]) -> dict[int, list[dict]]` — 纯函数，过滤模型的原始输出
  - `kpmark.mark(name: str, force: bool = False, verbose: bool = True) -> int` — 跑一次，返回写了几题（`-1` = 没跑成）

- [ ] **Step 1: 写失败的测试**

`tests/test_kpmark.py` —— 只测纯函数 `keep`，不碰网络：

```python
# -*- coding: utf-8 -*-
import kpmark

NS = {1, 2, 3}


def test_正常一条():
    rows = [{"n": 1, "kps": [{"code": "mom.conserve", "why": "碰后速度靠动量守恒"}]}]
    assert kpmark.keep(rows, NS) == {
        1: [{"code": "mom.conserve", "why": "碰后速度靠动量守恒"}]}


def test_编出来的code直接丢掉():
    rows = [{"n": 1, "kps": [{"code": "mom.动量守恒", "why": "x"},
                             {"code": "mom.conserve", "why": "y"}]}]
    assert kpmark.keep(rows, NS) == {1: [{"code": "mom.conserve", "why": "y"}]}


def test_按名字给的也认():
    # 模型有时会回名字而不是 code。kp.resolve 精确匹配得到，就收
    rows = [{"n": 2, "kps": [{"code": "牛顿第二定律", "why": "求加速度"}]}]
    assert kpmark.keep(rows, NS) == {2: [{"code": "dyn.newton2", "why": "求加速度"}]}


def test_最多三个():
    codes = ["kin.free_fall", "dyn.newton2", "mom.conserve", "energy.ke_theorem"]
    rows = [{"n": 1, "kps": [{"code": c, "why": "第%d个" % i}
                             for i, c in enumerate(codes)]}]
    got = kpmark.keep(rows, NS)[1]
    assert len(got) == 3
    assert [g["code"] for g in got] == codes[:3]


def test_重复的code只留一个():
    rows = [{"n": 1, "kps": [{"code": "mom.conserve", "why": "甲"},
                             {"code": "动量守恒定律", "why": "乙"}]}]
    assert kpmark.keep(rows, NS) == {1: [{"code": "mom.conserve", "why": "甲"}]}


def test_卷子里没有的题号丢掉():
    rows = [{"n": 99, "kps": [{"code": "mom.conserve", "why": "x"}]}]
    assert kpmark.keep(rows, NS) == {}


def test_why为空的丢掉():
    # why 是这道题的说明，不是知识点定义。给不出来就说明模型没在看这道题
    rows = [{"n": 1, "kps": [{"code": "mom.conserve", "why": "  "}]}]
    assert kpmark.keep(rows, NS) == {}


def test_一个都挂不上就不出现在结果里():
    rows = [{"n": 1, "kps": []}, {"n": 2, "kps": [{"code": "编的", "why": "x"}]}]
    assert kpmark.keep(rows, NS) == {}


def test_烂数据不炸():
    rows = [{"n": "甲", "kps": []}, {"kps": []}, {"n": 1}, {"n": 1, "kps": "不是数组"},
            {"n": 1, "kps": [None, "字符串", {"code": "mom.conserve", "why": "好的"}]}]
    assert kpmark.keep(rows, NS) == {1: [{"code": "mom.conserve", "why": "好的"}]}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_kpmark.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'kpmark'`

- [ ] **Step 3: 写 `pipeline/kpmark.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kpmark.py —— 阶段③c 整卷知识点标注

    python pipeline/kpmark.py <卷名> [--force]

给每道题挂上受控词表里的知识点。诊断报告里「这个学生哪个知识点弱」这句话
就架在这一步的产出上。

为什么排在 ③ 之后
-----------------
用得上解法。知道这道题**怎么解的**，比只看题干更判得准它考什么 ——
一道「小球从斜面滑下」的题，看题干像运动学，看解法才知道考的是动能定理。

为什么整卷一次调用
------------------
和 ③b 同一个理由：模型同时看得见 16 道题，标签的粒度才对得齐。逐题各标各的，
同一卷里「动量守恒」和「碰撞问题」这种粗细不一的标签会混在一起 ——
而这一步的全部价值就在于**能聚合**，粒度不齐等于没标。

挂不上就留空
------------
模型编出来的 code 一律丢掉，不做模糊匹配、不找最接近的。塞进去的标签会污染
薄弱点统计，而且没有任何人能从结果里看出它是塞的。页面上明说「这道题没挂上
知识点」比挂一个错的强。
"""
import argparse, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kp
import store

for _l in (open(os.path.join(ROOT, ".env"), encoding="utf-8")
           if os.path.exists(os.path.join(ROOT, ".env")) else []):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# 纯文本分类任务，DeepSeek 够用而且便宜。这一步不看图 —— 题干文字加 ③ 的解法
# 已经足够判断考什么。
KEY = os.environ.get("EXAM_KP_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
BASE = os.environ.get("EXAM_KP_BASE") or os.environ.get("DEEPSEEK_BASE_URL",
                                                        "https://api.deepseek.com/v1")
MODEL = os.environ.get("EXAM_KP_MODEL") or os.environ.get("DEEPSEEK_MODEL",
                                                          "deepseek-v4-pro")

MAX_KPS = 3

PROMPT_HEAD = """给一份物理试卷的每道题挂知识点标签。

下面先给你**受控词表**，再给你整卷每道题的题号、题型、题干和解法。

三条硬规则：

1. `code` **只能从词表里挑**。词表里没有的，哪怕你觉得更准确，也不许写 ——
   编出来的会被直接丢掉。
2. 一道题最多挂 %d 个，按重要性从高到低排。挂满等于没挂。
3. `why` 是针对**这道题**的一句话（「用动量守恒求碰后速度」），
   不是知识点的定义（「动量守恒定律是指…」）。给不出来就别挂这一条。

真判不出来就给空数组 `"kps": []`。**挂不上比挂错好** ——
这些标签会拿去统计学生的薄弱知识点，挂错一个就凭空造出一个假的薄弱点。

只输出 JSON 数组，不要代码块围栏、不要解释：
[{"n": 1, "kps": [{"code": "mom.conserve", "why": "用动量守恒求碰后速度"}]}, ...]

必须覆盖下面出现的每一个题号，一个都不能少。

════════════════ 受控词表 ════════════════
""" % MAX_KPS


def payload_for(paper, sols):
    parts = []
    for q in paper["questions"]:
        stem = re.sub(r"\s+", " ", (q.get("stem_latex") or q.get("stem") or "").strip())
        bits = ["【第%d题】%s" % (q["n"], q.get("type") or ""), "题干：" + stem[:260]]
        s = sols.get(q["n"])
        if s and s.get("steps"):
            bits.append("解法：" + re.sub(r"\s+", " ", " ".join(s["steps"]))[:400])
        elif s and s.get("answer"):
            bits.append("答案：" + re.sub(r"\s+", " ", s["answer"])[:200])
        else:
            bits.append("解法：（尚未解出，只能看题干判断）")
        parts.append("\n".join(bits))
    return "\n\n".join(parts)


def keep(rows, valid_ns):
    """
    把模型的原始输出过成可以入库的形状。**纯函数，不碰网络也不碰库** ——
    这一步所有的正确性判断都在这里，所以它必须能单独测。

    过滤规则：题号必须在这份卷子里、code 必须解析得到、why 必须非空、
    去重、最多 MAX_KPS 个。一条都不剩的题不出现在结果里（= 没挂上）。
    """
    out = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if n not in valid_ns:
            continue
        kept, seen = [], set()
        for item in (r.get("kps") if isinstance(r.get("kps"), list) else []):
            if not isinstance(item, dict):
                continue
            code = kp.resolve(item.get("code"))
            why = str(item.get("why") or "").strip()
            if not code or not why or code in seen:
                continue
            seen.add(code)
            kept.append({"code": code, "why": why[:80]})
            if len(kept) == MAX_KPS:
                break
        if kept:
            out[n] = kept
    return out


def ask(payload, tries=3):
    body = json.dumps({"model": MODEL, "max_tokens": 8000, "temperature": 0,
                       "messages": [{"role": "user", "content": payload}]}).encode()
    last = None
    for k in range(tries):
        try:
            r = urllib.request.Request(BASE + "/chat/completions", body,
                                       {"Authorization": "Bearer " + KEY,
                                        "Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(r, timeout=300).read())
            txt = d["choices"][0]["message"]["content"]
            m = re.search(r"\[.*\]", txt, re.S)
            if not m:
                raise ValueError("没有返回 JSON 数组：" + txt[:160])
            return json.loads(m.group(0))
        except Exception as e:
            last = e
            if k == tries - 1:
                raise
    raise last


def mark(name, force=False, verbose=True):
    """跑一次 ③c，返回写了几题（-1 = 没跑成，0 = 跳过）。"""
    log = print if verbose else (lambda *a, **k: None)
    paper = store.get_paper(name)
    if not paper:
        log("库里没有「%s」" % name)
        return -1
    if not KEY:
        log("没有 DEEPSEEK_API_KEY（或 EXAM_KP_KEY），跳过 ③c")
        return -1
    todo = [q for q in paper["questions"] if not q.get("kps")]
    if not todo and not force:
        log("── 知识点 %s：%d 题都挂过了，跳过" % (name, len(paper["questions"])))
        return 0

    sols = store.paper_solutions(name)
    valid = {q["n"]: q["id"] for q in paper["questions"]}
    rows = ask(PROMPT_HEAD + kp.catalog_text()
               + "\n\n════════════════ 试卷 ════════════════\n\n"
               + payload_for(paper, sols))
    got = keep(rows, set(valid))

    cat = kp.load()
    for n in sorted(got):
        store.put_kps(valid[n], got[n])
        log("   第%2d题 %s" % (n, "、".join(cat[k["code"]]["name"] for k in got[n])))

    miss = sorted(set(valid) - set(got))
    log("── 知识点 %s（%s）" % (name, MODEL))
    log("   挂上 %d 题，没挂上 %d 题" % (len(got), len(miss)))
    if miss:
        # 缺了就说缺了。页面上这些题会写「没挂上知识点」，不塞一个最接近的
        log("   ⚠ 没挂上：%s（页面上会明说，不塞占位标签）"
            % "、".join("第%d题" % n for n in miss))
    return len(got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--force", action="store_true", help="已经挂过的题也重挂")
    a = ap.parse_args()
    name = os.path.basename(os.path.normpath(a.paper))
    return 1 if mark(name, a.force) < 0 else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_kpmark.py -v`
Expected: `9 passed`

- [ ] **Step 5: 拿一份真卷子跑一次**

```bash
.venv/bin/python pipeline/kpmark.py 2025年高考北京卷物理真题
```

Expected: 逐题打印题号与知识点名，末尾 `挂上 N 题，没挂上 M 题`。人工看一眼前三题标得对不对。

- [ ] **Step 6: 提交**

```bash
git add pipeline/kpmark.py tests/test_kpmark.py
git commit -m "feat: 加 ③c 整卷知识点标注

排在 ③ 之后是因为用得上解法：一道「小球从斜面滑下」的题，看题干像
运动学，看解法才知道考的是动能定理。

整卷一次调用是为了粒度对齐 —— 这一步的全部价值在于能聚合，逐题各标
各的会混出「动量守恒」和「碰撞问题」两种粗细，等于没标。

正确性判断全在纯函数 keep 里，所以它能单独测：编的 code 丢掉、why 为空
丢掉、最多 3 个、去重、题号不在卷子里丢掉。"
```

---

### Task 5: 把 ③c 接进两条链

命令行链和网页链**必须一样长**。只接一条的话，「上传的卷子」和「命令行跑的卷子」会在页面上呈现两种完成度，而没有任何东西提示这件事。

**Files:**
- Modify: `pipeline/run.py`（`main()` 里 ③b 那一步之后）
- Modify: `pipeline/api.py`（`run_pipeline` 里 ③b 之后）

**Interfaces:**
- Consumes: `kpmark.mark`（经由 CLI）
- Produces: 无新接口

- [ ] **Step 1: 命令行链**

`pipeline/run.py` 里找到

```python
        total += step("③b", "目录（短标题与短答案）",
                      [PY, os.path.join(HERE, "outline.py"), name])
```

在它**之后**插入：

```python
        # ③c 知识点：排在 ③ 之后是因为用得上解法。整卷一次调用，几十秒
        total += step("③c", "知识点标注",
                      [PY, os.path.join(HERE, "kpmark.py"), name])
```

- [ ] **Step 2: 同步更新 run.py 的模块文档**

在 `run.py` 顶部 docstring 里，`outline.py` 那一行之后加一行：

```
    kpmark.py     ③c 整卷一次调用 → 每题挂上受控词表里的知识点
```

- [ ] **Step 3: 网页链**

`pipeline/api.py` 的 `run_pipeline` 里找到调用 ③b 的那一步（`outline.py`），在其**之后**加同样的一步：

```python
    if not run_step(jid, "③c 知识点标注",
                    step_path("kpmark.py") + [name], timeout=600):
        log("⚠ ③c 知识点标注没跑成，继续 —— 页面上这些题会写「没挂上知识点」")
```

**注意这一步失败不中止整条链。** 知识点缺了页面照样能看题、能看讲解；为了一个标签把已经跑了半小时的卷子判失败，代价不对等。

- [ ] **Step 4: 同步 `run_pipeline` 的 docstring**

把

```
    ① 摄入 → ② 切分 → ②b 公式 → ②c 入库 → ③ 解题 → ③b 目录 → ④ 断言
```

改成

```
    ① 摄入 → ② 切分 → ②b 公式 → ②c 入库 → ③ 解题 → ③b 目录 → ③c 知识点 → ④ 断言
```

- [ ] **Step 5: 验证两条链都认得这一步**

```bash
grep -n "kpmark" pipeline/run.py pipeline/api.py
```

Expected: `run.py` 两处（docstring + step），`api.py` 两处（docstring + run_step）

- [ ] **Step 6: 提交**

```bash
git add pipeline/run.py pipeline/api.py
git commit -m "feat: 把 ③c 接进命令行链和网页链

两条入口必须一样长，否则「上传的卷子」和「命令行跑的卷子」会在页面上
呈现两种完成度，而没有任何东西能提示这件事。

③c 失败不中止：知识点缺了页面照样能看题看讲解，为一个标签把跑了半小时
的卷子判失败，代价不对等。"
```

---

### Task 6: ②c 标准答案抽取（切分逻辑）

**Files:**
- Create: `pipeline/refans.py`
- Create: `tests/test_refans.py`

**Interfaces:**
- Consumes: `store.get_paper()`、`store.put_ref_answer()`
- Produces:
  - `refans.find_zone(text: str) -> int | None` — 参考答案区的起始下标，找不到回 `None`
  - `refans.split_answers(text: str, numbers: list[int]) -> dict[int, str]` — 题号 → 答案原文
  - `refans.extract(doc_text: str, numbers: list[int]) -> dict[int, str]` — 上面两个串起来
  - `refans.run(name: str, verbose: bool = True) -> tuple[int, int]` — `(抽到几题, 总题数)`

- [ ] **Step 1: 写失败的测试**

`tests/test_refans.py`：

```python
# -*- coding: utf-8 -*-
import refans

DOC = """一、单项选择题
1. 下列说法正确的是（ ）
A. 甲   B. 乙   C. 丙   D. 丁
2. 关于动量守恒，下列说法正确的是（ ）
A. 甲   B. 乙

参考答案
1. B
2. AC
3. 0.4 m/s，方向水平向右
"""


def test_找得到参考答案区():
    i = refans.find_zone(DOC)
    assert i is not None
    assert DOC[i:].startswith("参考答案")


def test_没有答案区就回None():
    assert refans.find_zone("一、单项选择题\n1. 下列说法正确的是（ ）\n") is None
    # 题干里的「答案」不算 —— 这是 22 卷语料里唯一出现「答案」的地方
    assert refans.find_zone("1. 计算结果，答案保留两位有效数字。") is None


def test_按题号切开():
    got = refans.split_answers(DOC[refans.find_zone(DOC):], [1, 2, 3])
    assert got == {1: "B", 2: "AC", 3: "0.4 m/s，方向水平向右"}


def test_只认卷子里有的题号():
    zone = "参考答案\n1. B\n7. 编出来的\n"
    assert refans.split_answers(zone, [1, 2]) == {1: "B"}


def test_题号顺序乱了也不猜():
    """答案区里题号必须**递增**。乱序多半是把正文当成了答案区，
    这时宁可一条都不给，也不能把错位的答案安到题上 —— 那会让做对的
    学生被判错，凭空造出一个假的薄弱知识点。"""
    zone = "参考答案\n3. C\n1. B\n2. A\n"
    assert refans.split_answers(zone, [1, 2, 3]) == {}


def test_多种题号写法():
    for zone in ("参考答案\n1．B\n2．AC\n", "参考答案\n1、B\n2、AC\n",
                 "参考答案\n【1】B\n【2】AC\n", "参考答案\n第1题 B\n第2题 AC\n"):
        assert refans.split_answers(zone, [1, 2]) == {1: "B", 2: "AC"}, zone


def test_extract串起来():
    assert refans.extract(DOC, [1, 2, 3]) == {1: "B", 2: "AC",
                                              3: "0.4 m/s，方向水平向右"}
    assert refans.extract("没有答案区的卷子\n1. 题干\n", [1]) == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_refans.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'refans'`

- [ ] **Step 3: 写 `pipeline/refans.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refans.py —— 阶段②c 标准答案抽取

    python pipeline/refans.py <卷名>

从卷子自带的「参考答案」段落里，按题号切出每道题的标准答案。

纯代码，不调模型
----------------
这一步的产出会拿去判学生的对错。模型抽错一道，做对这道题的学生就被判错，
凭空造出一个假的薄弱知识点，而页面上一切看起来都正常。所以这里只做
**不会静默出错**的事：找得到答案区就按题号切，找不到就明说找不到。

抽不到不是失败
--------------
库里 22 份高考真题**一份都没有参考答案段落** —— 真题 PDF 本来就不带答案。
所以「一题都没抽到」是这类卷子的正常结果，记 ref_answer_src='none'，
下游一律判 unsure（不算学生错）。

一条都不给，也不给错的
----------------------
答案区里的题号必须递增。乱序多半意味着把正文当成了答案区，这时宁可整片
放弃 —— 错位的答案安到题上，比没有答案坏得多。
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

# 答案区的起点。要求它**独占一行或紧跟换行**，否则题干里的
# 「答案保留两位有效数字」会被当成答案区起点 —— 那是 22 卷语料里
# 「答案」二字唯一出现的地方。
ZONE_RE = re.compile(r"(?:^|\n)\s*(参考答案|答案与解析|参考解答|答案速查|"
                     r"试题答案|答案详解)\s*(?:[:：])?\s*(?=\n|$)")

# 题号的几种写法：`1.` `1．` `1、` `【1】` `第1题`
NUM_RE = re.compile(r"(?:^|\n)\s*(?:第\s*(\d{1,2})\s*题|【\s*(\d{1,2})\s*】|"
                    r"(\d{1,2})\s*[.．、])\s*")


def find_zone(text):
    """参考答案区的起始下标（指向标题词本身）。找不到回 None。"""
    m = ZONE_RE.search(text)
    return m.start(1) if m else None


def split_answers(zone_text, numbers):
    """
    把答案区按题号切成 {题号: 答案原文}。

    `numbers` 是这份卷子真实的题号列表 —— 只认里面有的，认出来的题号
    必须**严格递增**，否则整片放弃（见模块开头）。
    """
    valid = set(numbers)
    hits = []
    for m in NUM_RE.finditer(zone_text):
        n = int(next(g for g in m.groups() if g))
        hits.append((n, m.end()))
    picked = [(n, e) for n, e in hits if n in valid]
    if not picked:
        return {}
    if any(b[0] <= a[0] for a, b in zip(picked, picked[1:])):
        return {}          # 题号没有严格递增：这多半不是答案区

    out = {}
    for i, (n, start) in enumerate(picked):
        end = picked[i + 1][1] if i + 1 < len(picked) else len(zone_text)
        # 下一条的 end 指向题号之后，要回退到它的行首
        if i + 1 < len(picked):
            end = zone_text.rfind("\n", start, picked[i + 1][1])
            if end < 0:
                end = picked[i + 1][1]
        ans = re.sub(r"\s+", " ", zone_text[start:end]).strip()
        if ans:
            out[n] = ans
    return out


def extract(doc_text, numbers):
    """整卷全文 → {题号: 标准答案}。没有答案区就回空字典。"""
    i = find_zone(doc_text)
    return split_answers(doc_text[i:], numbers) if i is not None else {}


def doc_text(name):
    """读构建产物里的整卷文本。没有 doc.json 就回 None。"""
    p = os.path.join(ROOT, "work", name, "doc.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    return "\n".join(pg["text"] for pg in d["pages"])


def run(name, verbose=True):
    """跑一次 ②c，返回 (抽到几题, 总题数)。"""
    log = print if verbose else (lambda *a, **k: None)
    paper = store.get_paper(name)
    if not paper:
        log("库里没有「%s」" % name)
        return (0, 0)
    qs = paper["questions"]
    txt = doc_text(name)
    if txt is None:
        log("── 标准答案 %s：没有 doc.json（构建产物已清理），跳过" % name)
        return (0, len(qs))

    got = extract(txt, [q["n"] for q in qs])
    for q in qs:
        if q["n"] in got:
            store.put_ref_answer(q["id"], got[q["n"]][:400], "paper")
        else:
            # 抽不到也要写一行。「抽不到」和「还没跑过 ②c」是两句不同的话
            store.put_ref_answer(q["id"], None, "none")
    log("── 标准答案 %s：抽到 %d / %d 题" % (name, len(got), len(qs)))
    if not got:
        log("   这份卷子里没有参考答案段落。这些题在判对错时一律记 unsure，"
            "不算学生错 —— 是卷子没给答案，不是学生的问题。")
    return (len(got), len(qs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    a = ap.parse_args()
    run(os.path.basename(os.path.normpath(a.paper)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_refans.py -v`
Expected: `7 passed`

- [ ] **Step 5: 提交**

```bash
git add pipeline/refans.py tests/test_refans.py
git commit -m "feat: 加 ②c 标准答案抽取（纯代码，不调模型）

这一步的产出会拿去判学生对错。抽错一道，做对的学生就被判错，凭空
造出一个假的薄弱知识点，而页面上一切看起来正常。所以只做不会静默
出错的事：找得到答案区就按题号切，找不到就明说找不到。

题号必须严格递增，否则整片放弃 —— 乱序多半是把正文当成了答案区，
错位的答案安到题上比没有答案坏得多。"
```

---

### Task 7: ②c 的全语料反幻觉门禁

库里 22 份卷子一份都没有参考答案段落。所以**②c 在这批语料上的正确行为是一条都不抽**。这条回归测试盯的就是它不许编。

**Files:**
- Create: `tests/test_refans_corpus.py`
- Modify: `pipeline/run.py`（②c 接进命令行链）
- Modify: `pipeline/api.py`（②c 接进网页链）

**Interfaces:**
- Consumes: `refans.extract`
- Produces: 无新接口

- [ ] **Step 1: 写全语料回归测试**

`tests/test_refans_corpus.py`：

```python
# -*- coding: utf-8 -*-
"""
全语料反幻觉门禁。

库里这 22 份都是高考真题 PDF，本来就不带参考答案。所以 ②c 在它们身上的
**正确行为是一条都不抽**。抽出来任何东西都说明规则太松，会把正文里的
「1. 下列说法正确的是」当成答案。
"""
import glob, json, os, re
import pytest
import refans

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = sorted(glob.glob(os.path.join(ROOT, "work", "*", "doc.json")))

pytestmark = pytest.mark.skipif(not DOCS, reason="没有 work/ 语料")


@pytest.mark.parametrize("path", DOCS, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_不带答案的卷子一条都不许抽出来(path):
    d = json.load(open(path, encoding="utf-8"))
    txt = "\n".join(pg["text"] for pg in d["pages"])
    # 题号取 1..25，比任何一份卷子的题数都多 —— 故意给最宽松的候选集，
    # 让规则在最容易误命中的条件下受检
    got = refans.extract(txt, list(range(1, 26)))
    assert got == {}, "从不带答案的卷子里抽出了 %d 条：%s" % (len(got), got)


def test_语料里确实没有参考答案段落():
    """这条是上面那批测试的前提。哪天语料换成带答案的卷子，
    这条会先红 —— 提醒去改上面的断言，而不是让上面静静地失去意义。"""
    for path in DOCS:
        d = json.load(open(path, encoding="utf-8"))
        txt = "\n".join(pg["text"] for pg in d["pages"])
        assert refans.find_zone(txt) is None, path
```

- [ ] **Step 2: 跑测试**

Run: `.venv/bin/pytest tests/test_refans_corpus.py -v`
Expected: `23 passed`（22 份卷子 + 1 条前提检查）。**有红的就回 Task 6 收紧规则**，不要放宽这里的断言。

- [ ] **Step 3: 命令行链接上 ②c**

`pipeline/run.py` 里，②b 之后、发布入库之前塞不进去（②c 要读库里的题号），所以放在**发布入库之后、③ 解题之前**。找到 `total += step("②c", "发布入库", ...)` 那一段，在它之后插入：

```python
    # ②c′ 标准答案：纯代码，读 doc.json 按题号切。抽不到就全记 none ——
    # 高考真题本来就不带答案，那不是失败
    total += step("②c′", "标准答案抽取",
                  [PY, os.path.join(HERE, "refans.py"), name])
```

- [ ] **Step 4: 网页链接上 ②c**

`pipeline/api.py` 的 `run_pipeline` 里，发布入库之后、③ 解题之前插入：

```python
    # 纯代码，几十毫秒。失败不中止 —— 没抽到答案的题下游一律判 unsure
    run_step(jid, "②c′ 标准答案抽取", step_path("refans.py") + [name], timeout=120)
```

- [ ] **Step 5: 拿一份真卷子跑一遍**

```bash
.venv/bin/python pipeline/refans.py 2025年高考北京卷物理真题
```

Expected:
```
── 标准答案 2025年高考北京卷物理真题：抽到 0 / 19 题
   这份卷子里没有参考答案段落。这些题在判对错时一律记 unsure，不算学生错 —— 是卷子没给答案，不是学生的问题。
```

- [ ] **Step 6: 提交**

```bash
git add tests/test_refans_corpus.py pipeline/run.py pipeline/api.py
git commit -m "test: ②c 全语料反幻觉门禁，并接进两条链

库里 22 份都是高考真题，本来就不带参考答案，所以 ②c 在它们身上的
正确行为是一条都不抽。抽出任何东西都说明规则太松。

多带一条「语料里确实没有答案段落」的前提检查：哪天语料换成带答案的
卷子，它会先红，提醒去改上面那批断言，而不是让它们静静地失去意义。"
```

---

### Task 8: 带到页面上

只做到库和 API 不算完成 —— 必须验证页面真的渲染出来了。

**Files:**
- Modify: `pipeline/api.py`（`paper()` 的每题字典）
- Modify: `web/src/types.ts`
- Modify: `web/src/components/QuestionCard.tsx`
- Modify: `web/src/styles.css`
- Create: `tests/test_answers_agree.py`

**Interfaces:**
- Consumes: `store.get_paper()` 带出的 `kps` / `ref_answer` / `ref_answer_src`
- Produces:
  - `api.answers_agree(a: str | None, b: str | None) -> bool | None` — 归一化后比；任一边为空回 `None`（= 比不了）
  - 接口新增字段 `kps: {code, name, chapter, why}[]`、`refAnswer: string | null`、`refAnswerSrc: string | null`、`refAnswerAgrees: boolean | null`

- [ ] **Step 1: 写 `answers_agree` 的失败测试**

`tests/test_answers_agree.py`：

```python
# -*- coding: utf-8 -*-
import api


def test_选择题字母():
    assert api.answers_agree("BD", "bd") is True
    assert api.answers_agree("B D", "BD") is True
    assert api.answers_agree("BD", "DB") is True      # 集合相等
    assert api.answers_agree("BD", "BC") is False


def test_全角半角和标点():
    assert api.answers_agree("０．４ m", "0.4 m") is True
    assert api.answers_agree("0.4 m。", "0.4 m") is True


def test_比不了就回None():
    # **不许把「比不了」压成 False。** 压成 False 就是在页面上说
    # 「AI 和卷子对不上」，而事实是其中一边根本没有
    assert api.answers_agree(None, "BD") is None
    assert api.answers_agree("BD", None) is None
    assert api.answers_agree("", "BD") is None
    assert api.answers_agree("  ", "  ") is None


def test_不做数值等价():
    # 本期不引 sympy，也不做 3/2 == 1.5。形式不同就是不同，
    # 页面上标出来让人看，比静默判等安全
    assert api.answers_agree("3/2", "1.5") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_answers_agree.py -v`
Expected: FAIL，`AttributeError: module 'api' has no attribute 'answers_agree'`

- [ ] **Step 3: 在 `pipeline/api.py` 里加 `answers_agree`**

放在 `paper()` 之前：

```python
_PUNCT = re.compile(r"[\s。，、；：．.,;:!？?（）()【】\[\]]+")


def answers_agree(a, b):
    """
    卷子上的标准答案与 ③ 的 AI 答案是不是一回事。

    **任一边为空回 None，不是 False。** 「比不了」和「对不上」在页面上是
    两句完全不同的话：前者是缺数据，后者是有一方错了。压成 False 等于
    在没有任何证据的情况下指认 AI 解错了。

    只做归一化字符串比与选择题的集合比 —— 本期不引 sympy（它解析带单位
    带下标的 LaTeX 会**静默**判错，正是这个项目最怕的错）。形式不同就报
    不同，让人去看，比静默判等安全。
    """
    def norm(s):
        if not s:
            return ""
        s = unicodedata.normalize("NFKC", str(s)).strip().upper()
        return _PUNCT.sub("", s)

    na, nb = norm(a), norm(b)
    if not na or not nb:
        return None
    if na == nb:
        return True
    # 选择题：只有 A-D 组成的，按集合比（"BD" 与 "DB" 是同一个答案）
    if re.fullmatch(r"[A-D]+", na) and re.fullmatch(r"[A-D]+", nb):
        return set(na) == set(nb)
    return False
```

在 `api.py` 的 import 行补上 `unicodedata`（`re` 已经有了；确认一下）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_answers_agree.py -v`
Expected: `4 passed`

- [ ] **Step 5: 接口带出四个字段**

在 `pipeline/api.py` 的 `paper()` 里，先在 `qs = []` 之前加一行拿词表：

```python
    cat = kp.load()
```

并在文件头部的 import 区加 `import kp`（和 `import store` 放一起）。

然后在每题的字典里，`"sceneId"` 那一行**之前**插入：

```python
            # ③c 挂的知识点。带上名字和章 —— 前端不该为了显示一个标签
            # 再去拉一份词表，而且词表是后端的种子数据
            "kps": [{"code": k["code"], "why": k.get("why", ""),
                     "name": cat[k["code"]]["name"] if k["code"] in cat else k["code"],
                     "chapter": cat[k["code"]]["chapter"] if k["code"] in cat else ""}
                    for k in (x.get("kps") or [])],
            # ②c 从卷子里抽的标准答案。src=None 表示还没跑过 ②c，
            # src='none' 表示跑过但这份卷子里没有答案 —— 两件事
            "refAnswer": x.get("ref_answer"),
            "refAnswerSrc": x.get("ref_answer_src"),
            # 白捡的红绿灯：卷子答案与 ③ 的 AI 答案比一次。不一致意味着
            # 要么 AI 解错了、要么那份答案有误，两种都必须让人看见。
            # None = 比不了（有一边没有），**不是**对不上
            "refAnswerAgrees": answers_agree(
                x.get("ref_answer"), sol and sol.get("short_answer")),
```

- [ ] **Step 6: 前端类型**

`web/src/types.ts` 里，`Question` 接口中 `sceneId` 之前加：

```ts
  /** ③c 挂的知识点。空数组 = 没挂上，页面要明说，不能不显示 */
  kps?: KnowledgePoint[]
  /** ②c 从卷子里抽的标准答案 */
  refAnswer?: string | null
  /** null = 还没跑过 ②c；'none' = 跑过但卷子里没有答案。两件事 */
  refAnswerSrc?: string | null
  /** 卷子答案与 AI 答案是否一致。**null = 比不了，不是对不上** */
  refAnswerAgrees?: boolean | null
```

并在文件里 `Question` 之前加：

```ts
export interface KnowledgePoint {
  code: string
  name: string
  chapter: string
  /** 针对这道题的一句话，不是知识点定义 */
  why: string
}
```

- [ ] **Step 7: 卡片上显示**

`web/src/components/QuestionCard.tsx`：

先在 `import type { Job, Question } from '../types'` 保持不变（`KnowledgePoint` 只在 `q.kps` 里用，不必单独引）。

在 `<div className="qbd">` 里，`<div className="stem"><StemBody q={q} /></div>` 那一行**之后**插入：

```tsx
        {/* 知识点。挂不上就明说 —— 不显示的话，「没挂上」和「还没跑 ③c」
            在页面上长得一模一样 */}
        <div className="kps">
          {q.kps?.length
            ? q.kps.map((k) => (
                <span className="pill kp" key={k.code} title={`${k.chapter} · ${k.why}`}>
                  {k.name}
                </span>
              ))
            : <span className="kp-none">这道题没挂上知识点</span>}
        </div>

        {/* 卷子上的标准答案。三种状态要分得出来 */}
        {q.refAnswerSrc && (
          <div className="refans">
            {q.refAnswer ? (
              <>
                <b>卷子上的答案：</b>{q.refAnswer}
                <span className="src">
                  （{q.refAnswerSrc === 'paper' ? '从这份卷子里抽的' : '老师上传的答案文件'}）
                </span>
                {q.refAnswerAgrees === false && (
                  <span className="pill w">与 AI 答案不一致</span>
                )}
              </>
            ) : (
              <span className="src">
                这份卷子里没有参考答案 —— 判学生对错时这道题会记「判不了」，不算错
              </span>
            )}
          </div>
        )}
```

- [ ] **Step 8: 样式**

`web/src/styles.css` 末尾追加：

```css
/* 知识点标签。挂不上时那句话要看得见但不抢眼 —— 它是常态，不是错误 */
.kps { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; align-items: center }
.pill.kp { background: #eef4ff; color: #2a4a8a; border-color: #c9dbff }
.kp-none { font-size: 12px; color: #8a8f98 }

.refans { margin: 8px 0; font-size: 14px; line-height: 1.7 }
.refans .src { color: #8a8f98; font-size: 12px; margin-left: 6px }
.refans .pill.w { margin-left: 8px }

@media (prefers-color-scheme: dark) {
  .pill.kp { background: #1d2942; color: #9dbcf5; border-color: #2c3f66 }
}
```

- [ ] **Step 9: 端到端验证**

```bash
.venv/bin/python pipeline/kpmark.py 2025年高考北京卷物理真题
.venv/bin/python pipeline/refans.py 2025年高考北京卷物理真题
curl -s localhost:8712/api/papers/2025年高考北京卷物理真题 \
  -b "$(cat /tmp/cookie 2>/dev/null || echo '')" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); q=d['questions'][0]; print(q['kps'], q['refAnswerSrc'], q['refAnswerAgrees'])"
```

Expected: 第一题的 `kps` 非空、`refAnswerSrc` 是 `none`、`refAnswerAgrees` 是 `None`。

然后打开试卷页，确认：**每道题下面有知识点标签，没挂上的题显示「这道题没挂上知识点」，并且有一行说这份卷子没有参考答案。** 截图或肉眼确认 —— 只做到 API 不算完成。

- [ ] **Step 10: 提交**

```bash
git add pipeline/api.py web/src/types.ts web/src/components/QuestionCard.tsx web/src/styles.css tests/test_answers_agree.py
git commit -m "feat: 页面上显示知识点与卷子上的标准答案

answers_agree 在任一边为空时回 None 而不是 False：「比不了」和「对不上」
在页面上是两句完全不同的话，压成 False 等于在没有证据的情况下指认
AI 解错了。

知识点挂不上时明说「这道题没挂上知识点」—— 不显示的话，「没挂上」和
「还没跑过 ③c」在页面上长得一模一样。"
```

---

### Task 9: 进度里加 ③c 那一格，并回填 22 卷

加了阶段就要在进度里体现，否则页面永远显示「已完成」而 ③c 一次都没跑过。

**这一步会让库里已经跑完的卷子集体退回「未完成」。这是对的** —— 它们确实没跑过 ③c。Step 5 把它们全部回填，几十秒一卷。

**Files:**
- Modify: `pipeline/store.py`（`progress()`）
- Modify: `pipeline/api.py`（`stage_of()`）
- Modify: `web/src/types.ts`（`Progress` 加 `kps`）
- Create: `tests/test_stage_of.py`

**Interfaces:**
- Consumes: `progress()` 返回的计数
- Produces: `progress()` 多一个键 `kps: int`；`stage_of` 多一个分支，`code` 为 `"kpmark"`

- [ ] **Step 1: 写失败的测试**

`tests/test_stage_of.py`：

```python
# -*- coding: utf-8 -*-
import api

BASE = dict(questions=16, solutions=16, labels=16, kps=16, judged=16, worth=6,
            specs=6, specsWorth=6, drafts=0, ready=6, sceneTried=6,
            assembledFresh=True)


def test_知识点没挂完就停在③c():
    code, label, short, cur, total = api.stage_of({**BASE, "kps": 9})
    assert code == "kpmark"
    assert label == "③c 知识点"
    assert (cur, total) == (9, 16)


def test_③c排在③b之后():
    """目录还没生成时，先报 ③b，不能跳到 ③c"""
    code, *_ = api.stage_of({**BASE, "labels": 3, "kps": 0})
    assert code == "outline"


def test_③c排在④c之前():
    code, *_ = api.stage_of({**BASE, "kps": 9, "judged": 0})
    assert code == "kpmark"


def test_都跑完了就是done():
    assert api.stage_of(BASE)[0] == "done"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_stage_of.py -v`
Expected: FAIL —— `test_知识点没挂完就停在③c` 报 `assert 'pick' == 'kpmark'`

- [ ] **Step 3: `progress()` 数 kps**

`pipeline/store.py` 的 `progress()` 里，找到数 label 的那一行：

```python
                   (SELECT count(*) FROM questions q WHERE q.paper_id=p.id AND q.label IS NOT NULL),
```

在它之后加一行：

```python
                   (SELECT count(*) FROM questions q WHERE q.paper_id=p.id AND jsonb_array_length(q.kps) > 0),
```

**解包顺序必须跟着改，错一位就静默串列**（`n_sol` 会拿到 kps 的计数，页面上「解题 12/16」是错的却看不出来）。把

```python
    (_pid, _nq, asm_at, started, n_q, n_label, n_sol, n_spec, n_appr, n_judged,
     n_worth, n_scene, n_spec_worth, n_draft, n_ready, n_scene_try, last, now) = r
```

整行替换成

```python
    (_pid, _nq, asm_at, started, n_q, n_label, n_kps, n_sol, n_spec, n_appr, n_judged,
     n_worth, n_scene, n_spec_worth, n_draft, n_ready, n_scene_try, last, now) = r
```

并在返回的字典里 `"labels": n_label,` 之后加：

```python
            "kps": n_kps,
```

- [ ] **Step 4: `stage_of()` 加一格**

`pipeline/api.py` 的 `stage_of` 里，找到

```python
    if pg["labels"] < q:
        return "outline", "③b 目录", "生成目录", pg["labels"], q
```

在它**之后**插入：

```python
    # ③c 知识点。分母是题数不是解出来的题数 —— 没解出来的题也该有知识点
    # （只看题干也判得出个大概），而诊断报告要拿它做聚合
    if pg.get("kps", 0) < q:
        return "kpmark", "③c 知识点", "标知识点", pg.get("kps", 0), q
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_stage_of.py -v`
Expected: `4 passed`

- [ ] **Step 6: 前端类型**

`web/src/types.ts` 的 `Progress` 接口里，`labels: number` 之后加：

```ts
  /** 挂上知识点的题数（③c）。分母是题数 */
  kps: number
```

- [ ] **Step 7: 回填库里所有卷子**

```bash
for p in $(.venv/bin/python -c "
import sys; sys.path.insert(0,'pipeline'); import store
print(' '.join(r['name'] for r in store.list_papers()))"); do
  echo "── $p"
  .venv/bin/python pipeline/refans.py "$p"
  .venv/bin/python pipeline/kpmark.py "$p"
done
```

Expected: 每份卷子打印 `抽到 0 / N 题` 和 `挂上 N 题`。全部跑完后刷新试卷库列表，**确认那些卷子重新显示「已完成」而不是卡在「③c 标知识点」**。

- [ ] **Step 8: 全量测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全绿

- [ ] **Step 9: 提交**

```bash
git add pipeline/store.py pipeline/api.py web/src/types.ts tests/test_stage_of.py
git commit -m "feat: 进度里加 ③c 那一格，并回填库里所有卷子

加了阶段不加进度格，页面会永远显示「已完成」而 ③c 一次都没跑过。

代价是已经跑完的卷子集体退回「未完成」——这是对的，它们确实没跑过。
回填一遍就回到完成态，几十秒一卷。"
```

---

## 自检

**规格覆盖**

| 规格条目 | 落在哪 |
|---|---|
| 受控词表 `kp_seed.json`，两级，含 aliases | Task 2 |
| ③c 整卷一次调用，用得上解法 | Task 4 |
| 只能从词表挑 code / 最多 3 个 / why 是这道题的一句话 | Task 4（`keep` + 测试） |
| 挂不上留空，页面明说 | Task 4 + Task 8 Step 7 |
| ②c 纯代码优先，按题号切 | Task 6 |
| ②c 抽不到记 `none`，下游判 unsure | Task 6（`run`）+ Task 8 Step 7 显示 |
| `questions` 补三列 | Task 3 |
| 白捡的红绿灯：卷子答案 vs AI 答案 | Task 8（`answers_agree`） |
| 试卷页显示知识点与标准答案 | Task 8 |
| 两条入口一样长 | Task 5 + Task 7 |

**本期有意不做**：②c 的「老师另传答案文件」分支（`ref_answer_src='answer_file'` 这个值在 Task 3 就留好了，期三填）、模型兜底抽答案（等拿到真实带答案的卷子再定规则，现在没有样本，写了也验不了）。

**已知会踩的两个坑，计划里都盯住了**

1. `publish` 的 upsert 冲掉新列 —— Task 3 有专门的测试。`label` 已经有过这个先例。
2. 加阶段导致已完成的卷子集体退回未完成 —— Task 9 Step 7 回填。

**一个悬着的事**：②c 的切分规则只在合成样本上验过。真实带答案的卷子长什么样还不知道，拿到样本后 `NUM_RE` / `ZONE_RE` 大概率要调，Task 6/7 的测试就是那时候的安全网。
