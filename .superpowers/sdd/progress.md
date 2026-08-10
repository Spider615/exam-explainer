# 答题卡步二 —— 执行台账

计划：`docs/superpowers/plans/2026-08-10-answer-sheet-step2.md`
设计：`docs/superpowers/specs/2026-08-06-answer-sheet-diagnosis-design.md`

**恢复现场先读这个文件，别凭记忆推断进度。** 这里写着 complete 的任务就是做完了，
不要重跑；从第一个没标 complete 的往下接。commit 号在 git 里查得到。

## 前置（不在计划的 10 个任务里，但已经做完并提交）

- 探针：5 组实测，结论进设计文档（`fd61a8d` `65f7f1c` `9b14af6`）
- 对抗性检查：4 路 + 1 路收敛，40 条 → 存活 18 条，全部落进计划（`37b4b46`）
- `ee93d32` 页脚不再撒谎（Ⓔ 做完后那句写死的话不成立了）
- `6c932c3` 同名 PDF 会把答案卷整卷覆盖 —— API 层改名护栏
- `9f54c75` 删题和整卷覆盖都不许带走学生作答 —— FK 改 SET NULL + publish 底闸

## 任务

- [x] Task 1: `sheetcut.py`（Ⓢ）　complete（commit `f29ae14`，10 条测试，真材料跑过）
- [x] Task 2: 数据模型 —— 分数列、partial、判据只留一份　complete（commit 见 git log，25 条测试）
- [x] Task 3: 答题卡的进度和失败要有自己的出口　complete（10 条测试）
- [x] Task 4: 上传入口 + 两道零成本闸门 + 按卡存料　complete（19 条测试；run_sheet_pipeline 目前只到 Ⓢ）
- [x] Task 5: `sheetread.py`（Ⓑa/Ⓑb/Ⓑc）　complete（32 条测试；模型那一跑在 Task 7 接管线时验）
- [x] Task 6: `sheetverdict.py`（Ⓒ 判定、题号绑定、互校）　complete（26 条测试）
- [x] Task 7: 落库 + 接进管线　complete（10 条测试 + conftest 加了「不许真调模型」的闸）
- [ ] Task 8: 页面 —— 答题卡列表与详情
- [ ] Task 9: 改判
- [ ] Task 10: 拿真材料端到端跑一遍

## 测试基线

714 passed（Task 7 之后）。569 是本轮开工时的数。
