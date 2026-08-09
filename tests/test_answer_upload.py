# -*- coding: utf-8 -*-
"""
答题卡模式的上传入口。

这条链以前在页面上根本没有入口，只能命令行跑。闸门的口径要和 /api/upload
一致：同一份卷子不许同时跑两条（两条链写同一个构建目录、烧双份额度）。
"""
import pytest
from fastapi import HTTPException

from pipeline import api


def test_保留图片扩展名():
    assert api.safe_image_name("IMG_0123.JPG") == "IMG_0123.JPG"
    assert api.safe_image_name("第 1 页.png").endswith(".png")


def test_保留pdf扩展名():
    assert api.safe_image_name("参考答案.pdf").endswith(".pdf")


def test_挡掉路径穿越():
    assert "/" not in api.safe_image_name("../../etc/passwd.png")
    assert ".." not in api.safe_image_name("../../etc/passwd.png")


def test_不认识的类型当场拒():
    """口径必须和 pages.normalize 一致 —— 那边只收图片和 PDF"""
    with pytest.raises(HTTPException) as e:
        api.safe_image_name("木马.exe")
    assert e.value.status_code == 400


# ---------------------------------------------------------------- 卷名
def test_卷名不能是空的():
    with pytest.raises(HTTPException) as e:
        api.answer_paper_name("   ", user_id=7, claimed={})
    assert e.value.status_code == 400


def test_卷名只剩非法字符也算空():
    with pytest.raises(HTTPException) as e:
        api.answer_paper_name("///", user_id=7, claimed={})
    assert e.value.status_code == 400


def test_自己的答案卷重名就是重跑(monkeypatch):
    monkeypatch.setattr(api.store, "paper_owner", lambda n: (True, 7))
    monkeypatch.setattr(api.store, "source_kind_of", lambda n: "answers_only")
    assert api.answer_paper_name("期末卷", user_id=7, claimed={}) == "期末卷"


def test_撞上自己的解析试卷要改名(monkeypatch):
    """不覆盖、不转模式 —— 那份跑了一小时的卷子不能被就地改掉"""
    monkeypatch.setattr(api.store, "paper_owner", lambda n: (True, 7))
    monkeypatch.setattr(api.store, "source_kind_of", lambda n: "pdf")
    monkeypatch.setattr(api.store, "free_name", lambda b, also_taken=(): b + " (2)")
    assert api.answer_paper_name("期末卷", user_id=7, claimed={}) == "期末卷 (2)"


def test_撞上别人的卷子要改名(monkeypatch):
    monkeypatch.setattr(api.store, "paper_owner", lambda n: (True, 99))
    monkeypatch.setattr(api.store, "source_kind_of", lambda n: "answers_only")
    monkeypatch.setattr(api.store, "free_name", lambda b, also_taken=(): b + " (2)")
    assert api.answer_paper_name("期末卷", user_id=7, claimed={}) == "期末卷 (2)"


def test_正在跑的名字也算被占(monkeypatch):
    """卷子要跑完才入库，那几分钟里只有 CLAIMS 知道这个名字已经开跑了"""
    monkeypatch.setattr(api.store, "paper_owner", lambda n: (False, None))
    monkeypatch.setattr(api.store, "source_kind_of", lambda n: None)
    monkeypatch.setattr(api.store, "free_name", lambda b, also_taken=(): b + " (2)")
    assert api.answer_paper_name("期末卷", user_id=7,
                                 claimed={"期末卷": 99}) == "期末卷 (2)"


# ---------------------------------------------------------------- run_answer_pipeline
#
# 这条链失败时会不会删卷子，是本轮唯一能毁掉用户数据的分支：sheet_answers（学生
# 的作答）以 ON DELETE CASCADE 挂在 questions 上，删错一次连作答记录一起没，
# 不可恢复。下面几条把「什么时候该删、什么时候绝对不能删」钉死。
from unittest.mock import patch


def _fresh_job(jid, owner_id=7):
    """
    造一条 run_answer_pipeline 期望能在 api.JOBS 里找到的记录，形状照抄
    /api/answer-papers 建任务时写的那份。api.JOBS 是模块级全局 dict，
    调用方用完必须 pop 掉，否则会串到别的测试里。
    """
    api.JOBS[jid] = {"state": "running", "step": "排队中", "name": "期末卷",
                     "owner_id": owner_id, "log": []}


def test_读参考答案失败_新建的空壳要删掉():
    """
    新建卷子这一步就没读出任何题目：空壳留着的话，页面上会冒出一份 0 题、
    没人知道来源的卷子，必须跟着这次失败一起清掉。
    """
    jid = "job-created-fail"
    _fresh_job(jid)
    try:
        with patch.object(api, "run_step", return_value=False), \
             patch.object(api.store, "delete_papers") as mock_delete:
            api.run_answer_pipeline(jid, [], "期末卷", 7, created=True)
        mock_delete.assert_called_once_with(["期末卷"], 7)
        assert api.JOBS[jid]["state"] == "error"
    finally:
        api.JOBS.pop(jid, None)


def test_读参考答案失败_重跑已有卷子绝不能删():
    """
    重跑一份已经存在、已经有学生作答挂在上面的卷子，这一步失败了也绝不能删——
    误删会连 sheet_answers 里那些不可恢复的学生作答一起带走。这是所有测试里
    最要紧的一条。
    """
    jid = "job-existing-fail"
    _fresh_job(jid)
    try:
        with patch.object(api, "run_step", return_value=False), \
             patch.object(api.store, "delete_papers") as mock_delete:
            api.run_answer_pipeline(jid, [], "期末卷", 7, created=False)
        mock_delete.assert_not_called()
    finally:
        api.JOBS.pop(jid, None)


def test_知识点挂不上不算整个任务失败():
    """
    挂知识点失败是常态（页面上逐题写「没挂上知识点」），不该把整份已经读出来
    的卷子标成 error，更不该被当成失败去删——那样一次挂标签的网络抖动就会
    把刚读出来的题目连带清空。
    """
    jid = "job-kpmark-fail"
    _fresh_job(jid)
    try:
        with patch.object(api, "run_step", side_effect=[True, False]), \
             patch.object(api.store, "get_paper",
                          return_value={"questions": [{"n": 1}, {"n": 2}]}), \
             patch.object(api.store, "delete_papers") as mock_delete:
            api.run_answer_pipeline(jid, [], "期末卷", 7, created=True)
        assert api.JOBS[jid]["state"] != "error"
        mock_delete.assert_not_called()
    finally:
        api.JOBS.pop(jid, None)
