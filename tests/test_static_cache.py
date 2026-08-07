# -*- coding: utf-8 -*-
"""
前端静态资源的缓存头。

这条测试是为了一个真实发生过的现象：后端更新了、构建也做了，**页面上
什么都没变，普通刷新也没用**。原因是 index.html 里写着当前那一版 JS 的
文件名，而它自己被浏览器按启发式规则缓存住了 —— 拿到的还是旧文件名，
新包永远加载不进来。
"""
import os
import api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPE = {"type": "http", "method": "GET", "headers": []}


def _headers(rel):
    p = os.path.join(ROOT, "web", "dist", rel)
    st = os.stat(p)
    return api.SPAStatic(directory=os.path.join(ROOT, "web", "dist")) \
             .file_response(p, st, SCOPE).headers


def test_index必须每次回源验():
    cc = _headers("index.html").get("cache-control", "")
    assert "no-cache" in cc, "index.html 被缓存住，新版本就永远加载不进来"


def test_带hash的资源可以长缓存():
    name = next(f for f in os.listdir(os.path.join(ROOT, "web", "dist", "assets"))
                if f.startswith("index-") and f.endswith(".js"))
    cc = _headers("assets/" + name).get("cache-control", "")
    # 文件名里带内容哈希，内容变了名字就变，所以可以放心长缓存
    assert "immutable" in cc and "max-age=" in cc


def test_不认识的文件不乱加头():
    """只对 .html 和 assets/ 表态。其余的维持原样，别顺手改掉别人的行为。"""
    p = os.path.join(ROOT, "web", "dist", "index.html")
    st = os.stat(p)
    s = api.SPAStatic(directory=os.path.join(ROOT, "web", "dist"))
    # 伪造一个既不是 html 也不在 assets 下的路径
    fake = os.path.join(ROOT, "web", "dist", "favicon.ico")
    if not os.path.exists(fake):
        return
    assert "cache-control" not in s.file_response(fake, os.stat(fake), SCOPE).headers
