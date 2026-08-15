"""
进度卡上那句状态词，说的必须是**眼下真正在跑的那一步**。

2026-08-15 实跑撞出来的：一份卷子在跑 Ⓑ 读批改（4 页答题卡），页面顶上写的却是
「③c 知识点 0/26 · 0/26 题判过 · 已用时 32 分 46 秒」。用户原话：
「怎么分析知识点这么久啊，不对吧」—— 他是对的，知识点那一步根本没在跑。

两边各自都没错，错在接线：

- `_stage_of_sheet` **有意不看答题卡**（modes.py 里写着理由：给它加一格，
  没传答题卡的卷子就永远走不到「已完成」）。所以卷子级阶段停在 ③c 是对的。
- 任务表里 `step` 写的是 "Ⓑ 读批改 · 第 2 页 a"，那才是实况。

而进度卡的标题取的是**推断出来的卷子阶段**，把实况挤到了底下一行小字。
推断本来就是「没人上报时的兜底」（见 `stage_of` 的说明：命令行跑的、
重启过的也看得见）—— 有人上报的时候，上报的那份该赢。

`sheet` 是判据：**不靠认字符串**。任务建出来的那一刻就写了 `sheet=<卡 id>`
（api.py 里那两条起答题卡链的路都写），认它就等于认「这个活干的是答题卡」。
"""

import unittest
from unittest.mock import patch

from pipeline import api

from tests.test_progress import progress


class ActiveJobCarriesSheet(unittest.TestCase):
    def setUp(self):
        api.JOBS.clear()
        self.addCleanup(api.JOBS.clear)

    def test_sheet_job_reports_which_sheet_it_is_reading(self):
        """答题卡那条链的活任务要带出 `sheet` —— 页面据此知道标题该听谁的。"""
        api.JOBS["j1"] = {
            "state": "running", "name": "卷子", "sheet": 12,
            "step": "Ⓑ 读批改 · 第 2 页 a", "pageDone": 2, "pageTotal": 4,
            "log": ["✓ 切出 4 页答题卡，已存好"],
        }

        live = api.active_job_for("卷子")

        self.assertEqual(12, live["sheet"])
        self.assertEqual("Ⓑ 读批改 · 第 2 页 a", live["step"])
        self.assertEqual((2, 4), (live["pageDone"], live["pageTotal"]))

    def test_paper_pipeline_job_has_no_sheet(self):
        """
        整卷那条链没有 `sheet`。**这一条不能少** —— 它钉住的是「别把
        ③④⑤ 的进度也当成答题卡」：那几步的 `stage` 是对的，标题不该改口径。
        """
        api.JOBS["j2"] = {
            "state": "solving", "name": "卷子",
            "step": "解题 3/16", "log": [],
        }

        live = api.active_job_for("卷子")

        self.assertIsNone(live["sheet"])

    def test_progress_endpoint_passes_sheet_through(self):
        """
        `/progress` 得把它带到前端。进度卡只认这个端点，
        `active_job_for` 给了而这里漏掉，等于没给。
        """
        api.JOBS["j3"] = {
            "state": "running", "name": "卷子", "sheet": 12,
            "step": "Ⓑ 读批改 · 第 1 页 a", "pageDone": 1, "pageTotal": 4,
            "log": [],
        }

        with (
            patch.object(api, "mine", return_value="卷子"),
            patch.object(api.store, "progress", return_value=progress(busy=True)),
            patch.object(api, "pipeline_running", return_value=False),
            patch.object(api, "mode_block", return_value={}),
        ):
            out = api.paper_progress("卷子", user={"id": 7})

        self.assertEqual(12, out["sheet"])
        self.assertEqual("Ⓑ 读批改 · 第 1 页 a", out["step"])
        # 卷子级阶段照旧下发 —— 上面那排格子还要用它，
        # 这次改的只是「标题听谁的」，不是把推断拆掉
        self.assertIn("stage", out)


if __name__ == "__main__":
    unittest.main()
