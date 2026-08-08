# -*- coding: utf-8 -*-
"""
「继续执行」：从卷子停下的地方接着往下跑。

为什么需要它
------------
`JOBS` 是**进程内的 dict**，驱动整条链的是一个线程。后端一重启，那个线程就没了——
而 `run_step` 起子进程用了 `start_new_session`，子进程反而活着，把手上那一步跑完
写进库，然后**没有人接着启动下一步**。页面上就停在「④b 自检 已停止 5/6」。

`api.py` 早就写过这件事：「真正断掉的是驱动链条的那个线程……要修得让任务状态
可恢复，不是去杀子进程。」这就是那个「可恢复」。

不是重跑，是接着跑
------------------
每一步都跳过已经做完的活：③ 按 `solution_fresh` 跳、⑤ 按「已经有通过门禁的动画」
跳（见 `scene.plan`）。所以「继续执行」在一份已经跑完的卷子上应该几乎立刻结束，
而不是把整卷重做一遍。**这一条是这个功能能不能用的分水岭** ——
重做一遍整卷 ⑤ 是几个小时和一大笔额度。

接不上的那一段
--------------
①摄入 / ②切分 / ②b 公式识别 接不上：它们要原始 PDF，而上传的原件在整条链结束时
就删了。不过卷子只要进了库，这三步按定义已经过去了；真挂在这三步的话卷子根本
不在库里，页面上也就没有这个按钮。这条限制要说出来，不能假装能续。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import api


def test_从库里读得到的卷子都能续():
    """
    能续的起点是 ②d —— 它之后的每一步只依赖库，不依赖 work/ 里的中间文件。
    """
    assert api.RESUME_FROM == "refans"


def test_续跑的步骤顺序和整条链一致():
    """
    两条入口跑出来的东西必须一样。顺序错了会出现「④ 写断言」排在「④c 选题」
    前面这种事 —— ④c 是便宜的筛子，必须排在贵的 ④ 前面。
    """
    assert api.RESUME_STEPS == ["refans", "solve", "finish"]


class TestGate:
    """开跑前的闸门。每一条挡的都是「两个进程做同一件事」。"""

    def test_没有这份卷子回_404(self, monkeypatch):
        monkeypatch.setattr(api.store, "progress", lambda name: None)
        with pytest.raises(api.HTTPException) as e:
            api.resume_gate("查无此卷", busy=False, done=False)
        assert e.value.status_code == 404

    def test_正在跑就拦住_409(self):
        with pytest.raises(api.HTTPException) as e:
            api.resume_gate("卷甲", busy=True, done=False, exists=True)
        assert e.value.status_code == 409
        assert "在跑" in e.value.detail

    def test_已经跑完了也拦住_409(self):
        """
        跑完了还点，只会白等一圈。**更要紧的是它会重跑 ⑦ 装配**，
        而页面上那个按钮本来就不该出现在跑完的卷子上。
        """
        with pytest.raises(api.HTTPException) as e:
            api.resume_gate("卷甲", busy=False, done=True, exists=True)
        assert e.value.status_code == 409
        assert "已经完成" in e.value.detail

    def test_停下来的卷子放行(self):
        assert api.resume_gate("卷甲", busy=False, done=False, exists=True) is None
