# -*- coding: utf-8 -*-
"""
官方解答过程必须到得了页面。

它在库里躺着（get_paper 查了这一列），但 /api/papers/{name} 的投影里漏了 ——
而「答题卡诊断」承诺的核心产出就是它：官方的解答过程，比 AI 解出来的可信。
只做到库里不算完成。
"""
from unittest.mock import patch

from pipeline import api


def _question(**kw):
    q = {"n": 11, "type": "", "points": None, "section": None, "pages": [1, 1],
         "stem": "", "options": [], "figures": [],
         "ref_answer": "2BIL / MP", "ref_answer_src": "answer_file",
         "ref_solution": "由安培力公式 F=BIL，导轨两侧各一根…"}
    q.update(kw)
    return q


def _call(questions):
    with (
        patch.object(api, "mine", return_value="答案卷"),
        patch.object(api.store, "get_paper",
                     return_value={"sections": [], "warnings": [],
                                   "sourceKind": "answers_only",
                                   "questions": questions}),
        patch.object(api, "scenes_for", return_value={}),
        patch.object(api.store, "paper_solutions", return_value={}),
        patch.object(api.store, "paper_solution_failures", return_value={}),
        patch.object(api.store, "assembled",
                     return_value={"path": None, "at": None, "fresh": False}),
        patch.object(api.store, "progress", return_value=None),
        patch.object(api, "active_job_for", return_value=None),
        patch.object(api.os.path, "exists", return_value=False),
    ):
        return api.paper("答案卷", user={"id": 7})


def test_官方解答过程出现在返回里():
    got = _call([_question()])["questions"][0]
    assert got["refSolution"].startswith("由安培力公式")


def test_没有解答过程时是null不是空串():
    """
    「参考答案上这道题没有过程」和「读出来是一段空文本」在页面上是两句话。
    参考答案的版式就是只有大题给详解，选择题没有过程是常态、不是缺陷
    """
    got = _call([_question(ref_solution=None)])["questions"][0]
    assert got["refSolution"] is None


def test_模式也一并给出():
    assert _call([_question()])["mode"]["code"] == "sheet"
