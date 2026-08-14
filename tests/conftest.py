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


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch, request):
    """
    **测试里永远不许真调模型。** 自动生效，不用每个测试自己记得。

    这条是踩出来的：`run_sheet_pipeline` 从「只到 Ⓢ」扩到整条链的那一刻，
    两条早先写的测试（它们只想验切图）顺着往下走进了 Ⓑ，**真的去调了火山方舟**
    —— 全量测试从 9 秒变成 175 秒，而且每跑一次都在花钱。它没有报错，
    只是慢，所以很容易被当成「测试变多了自然变慢」。

    被这道闸拦下时不要把它注掉：要么给那个测试打桩（`monkeypatch.setattr`
    某个模块的 `ask_raw`），要么它本来就不该走到模型那一步。

    **挡在 `urllib.request.urlopen` 上，不是挡某个模块的某个函数。**

    第一版挡的是 `mathvlm.post_doubao`，看着够用 —— 直到 `sheetadvice` 落地：
    它像 `kpmark`/`spec`/`solve`/`pick`/`outline`/`scene`/`llm_segment` 一样
    **自己拿 urllib 出网**，一条也没经过 mathvlm。全量测试当场挂住去真调模型，
    和第一次那回一模一样。`pipeline/` 下有十二个模块各自出网，
    一个个去堵是堵不完的 —— **闸要设在唯一的出口上。**

    （更早还错过一版：挡 `mathvlm.ask_raw` 本身，把
    `test_mathvlm_backend` 里那几条**正是在测 `ask_raw`** 的测试一起打死了。）

    **本地回环放行。** `tests/test_arkshim_ensure.py` 会真起一个本地垫片、
    再用 urllib 去探它 —— 那是在测我们自己的进程，不是调模型。
    一刀切连 127.0.0.1 一起堵，会把那几条正当的测试打死。

    真要跑实拨的验收，用 `-m allow_model` 单独跑，或者直接跑管线脚本。
    """
    if "allow_model" in request.keywords:
        return
    import urllib.request

    real = urllib.request.urlopen

    def guard(url, *a, **k):
        host = getattr(url, "host", None) or str(getattr(url, "full_url", url))
        if "127.0.0.1" in host or "localhost" in host or host.startswith("file:"):
            return real(url, *a, **k)
        raise AssertionError(
            "这个测试真去联网调模型了（%s）。测试里不许 —— 给它打桩，"
            "或者确认它本来就不该走到这一步。"
            "（实拨验收请标 @pytest.mark.allow_model）" % str(host)[:80])

    monkeypatch.setattr(urllib.request, "urlopen", guard)
    # claude CLI 那条路不走 urllib，单独挡
    import mathvlm
    monkeypatch.setattr(mathvlm, "CLI", None)
