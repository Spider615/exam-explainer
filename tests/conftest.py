# -*- coding: utf-8 -*-
"""
测试地基。

**必须在 import store 之前设好 DATABASE_URL** —— store.py 在模块顶层就把
DSN 读成了常量，import 之后再改环境变量没有任何作用，测试会安安静静地
连到真库上去，这正是这个项目最不能接受的那种错。
"""
import os, sys

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
