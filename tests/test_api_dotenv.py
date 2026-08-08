# -*- coding: utf-8 -*-
"""
管线子进程要按**磁盘上当前的** .env 跑，不是按后端启动那一刻的快照。

为什么会错
----------
`store.py` 读 .env 用的是 `os.environ.setdefault` —— 后端一启动，那时的 .env
就被烤进了它自己的 os.environ。而 `run_step` 把 `dict(os.environ)` 整个传给
子进程，子进程里那句 `setdefault` 于是成了空操作：键已经在了，改不动。

结果：改完 .env 从页面点一下重跑，**跑的还是后端启动时那套后端和模型**。
实测过 —— 把 ⑤ 切到方舟之后，页面上跑的仍然是订阅，日志里一个字的提示都没有。
「不报错、结果看着像对的」这一类。

所以 .env 对子进程有最终解释权，并且漂移了要在**任务日志里说出来**（那是
页面上看得见的地方），不能只让它悄悄生效。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import api


@pytest.fixture
def dotenv(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    monkeypatch.setattr(api, "DOTENV", str(p))
    return p


def test_按第一个等号切_值里的等号要留住(dotenv):
    dotenv.write_text("A=1\nDATABASE_URL=postgresql://u:p=q@h/db\n", encoding="utf-8")
    assert api.dotenv_now() == {"A": "1", "DATABASE_URL": "postgresql://u:p=q@h/db"}


def test_整行注释和空行跳过(dotenv):
    dotenv.write_text("# 说明\n\nA=1\n   # 缩进的注释\n", encoding="utf-8")
    assert api.dotenv_now() == {"A": "1"}


def test_不认行尾注释_跟_store_的读法一致(dotenv):
    """.env 里白纸黑字写着这条。两处读法不一致比读错更难查。"""
    dotenv.write_text("SMTP_PORT=465  # 说明\n", encoding="utf-8")
    assert api.dotenv_now()["SMTP_PORT"] == "465  # 说明"


def test_没有_env_文件时回空字典(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DOTENV", str(tmp_path / "不存在"))
    assert api.dotenv_now() == {}


def test_子进程环境以磁盘上的_env_为准(dotenv, monkeypatch):
    """这是整条修复的要害：启动时烤进 os.environ 的旧值不能赢。"""
    monkeypatch.setenv("EXAM_SCENE_BACKEND", "subscription")   # 后端启动时的旧快照
    dotenv.write_text("EXAM_SCENE_BACKEND=ark-cli\n", encoding="utf-8")
    assert api.step_env()["EXAM_SCENE_BACKEND"] == "ark-cli"


def test_子进程环境仍然掀掉_python_的块缓冲(dotenv):
    dotenv.write_text("", encoding="utf-8")
    assert api.step_env()["PYTHONUNBUFFERED"] == "1"


def test_env_里没写的键照旧从进程环境继承(dotenv, monkeypatch):
    monkeypatch.setenv("PATH_LIKE_THING", "保留我")
    dotenv.write_text("A=1\n", encoding="utf-8")
    assert api.step_env()["PATH_LIKE_THING"] == "保留我"


def test_漂移要报出来_键和新旧值都要有(dotenv, monkeypatch):
    monkeypatch.setenv("EXAM_SCENE_BACKEND", "subscription")
    monkeypatch.setenv("EXAM_SCENE_JOBS", "3")
    dotenv.write_text("EXAM_SCENE_BACKEND=ark-cli\nEXAM_SCENE_JOBS=3\n", encoding="utf-8")
    d = api.dotenv_drift()
    assert d == [("EXAM_SCENE_BACKEND", "subscription", "ark-cli")]   # 没变的不报


def test_漂移里的密钥要打码(dotenv, monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "ark-old-1234567890abcd")
    dotenv.write_text("ARK_API_KEY=ark-new-1234567890wxyz\n", encoding="utf-8")
    (k, old, new), = api.dotenv_drift()
    assert k == "ARK_API_KEY"
    assert "1234567890abcd" not in old and "1234567890wxyz" not in new
    assert old != new          # 打了码也要看得出「变了」


def test_一致时不报漂移(dotenv, monkeypatch):
    monkeypatch.setenv("A", "1")
    dotenv.write_text("A=1\n", encoding="utf-8")
    assert api.dotenv_drift() == []
