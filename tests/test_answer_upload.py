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
