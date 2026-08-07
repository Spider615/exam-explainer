# -*- coding: utf-8 -*-
def test_测试库连得上而且不是真库(conn):
    import store
    assert "exam_explainer_test" in store.DSN, "测试连到真库上了"
    row = conn.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='questions'").fetchone()
    assert row[0] == 1
