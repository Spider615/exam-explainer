# -*- coding: utf-8 -*-
"""
`EXAM_READONLY=1`：这一次运行不许改库，由 **Postgres 自己**拒绝。

为什么要这道门禁
----------------
反复踩的坑是「**本意只是看看，结果动了真东西**」：想看看 ⑤ 的清单，结果它把
一道题真跑了；想冒烟试试 ④c 通不通，结果它把整卷的选题判定重写了一遍。
两次都不是不知道会写库，是**顺手拿生产命令当查看工具**。

「下次注意」不是修复。这里把它变成结构上做不到：设了这个变量之后，
`store.connect()` 开出来的会话是 `TRANSACTION READ ONLY`，任何
INSERT / UPDATE / DELETE 由数据库直接拒绝 —— 不依赖某个脚本记得加 `--dry-run`，
也不依赖我记得加。

**严格 opt-in**：不设这个变量时，行为一个字都不变。
"""
import os
import sys

import psycopg
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import store


@pytest.fixture
def ro(monkeypatch):
    monkeypatch.setattr(store, "READONLY", True)


def test_默认不是只读_行为一个字不变(db):
    assert store.READONLY is False
    c = store.connect()
    c.execute("CREATE TEMP TABLE t_rw (x int)")
    c.execute("INSERT INTO t_rw VALUES (1)")
    c.commit()
    assert c.execute("SELECT count(*) FROM t_rw").fetchone()[0] == 1
    c.close()


def test_只读时读得动(db, ro):
    c = store.connect()
    assert c.execute("SELECT 1").fetchone()[0] == 1
    c.close()


def test_只读时写会被数据库拒绝(db, ro):
    """
    拒的是**数据库**，不是 Python 里的一句 if —— 所以绕不过去：
    任何路径、任何脚本、任何忘记加的开关都拦得住。
    """
    c = store.connect()
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        c.execute("CREATE TABLE t_should_not_exist (x int)")
    c.close()


def test_只读时_store_的写函数也进不去(db, ro):
    """走正常入口（不是裸 SQL）同样拦得住。"""
    c = store.connect()
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        c.execute("INSERT INTO papers (name) VALUES ('不该出现的卷子')")
    c.close()


def test_环境变量怎么读的(monkeypatch):
    """`EXAM_READONLY=1` 打开；空、0、没设 都是关。"""
    assert store.readonly_from({"EXAM_READONLY": "1"}) is True
    assert store.readonly_from({"EXAM_READONLY": "true"}) is True
    assert store.readonly_from({"EXAM_READONLY": "0"}) is False
    assert store.readonly_from({"EXAM_READONLY": ""}) is False
    assert store.readonly_from({}) is False
