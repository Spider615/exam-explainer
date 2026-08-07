#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kp.py —— 知识点受控词表

    python pipeline/kp.py            校验词表并打印每章条数

为什么要受控词表
----------------
薄弱知识点这个产出的全部价值在于**能跨题聚合**：「动量守恒错了 2 次」这句话
成立的前提是两道题挂的是同一个名字。让模型自由发挥，第 3 题会挂「动量守恒」，
第 6 题会挂「动量守恒定律」，聚合出来是两个各错一次的点 —— 看起来都不严重。

code 是稳定代号而不是自增 id：词表是版本管理的种子数据，重灌一次自增 id
就全漂了，code 不会。

resolve 不做模糊匹配
--------------------
找不到就是找不到。「最接近的那个」会把一个错标签洗成看起来合理的标签，
而没有任何人能从结果里看出它是洗出来的。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "kp_seed.json")

CHAPTERS = ("运动学", "相互作用与牛顿运动定律", "曲线运动与万有引力", "功和能",
            "动量", "机械振动与机械波", "静电场", "恒定电流", "磁场", "电磁感应",
            "交变电流", "热学", "光学", "近代物理", "实验与数据处理")

CODE_RE = re.compile(r"[a-z0-9_.]+")

_by_code = None
_index = None


def validate(entries):
    """返回问题描述列表；空列表表示词表合法。"""
    probs, seen = [], set()
    for i, e in enumerate(entries):
        where = "第%d条" % (i + 1)
        for k in ("code", "chapter", "name"):
            if not str(e.get(k) or "").strip():
                probs.append("%s缺 %s" % (where, k))
        code = e.get("code")
        if code in seen:
            probs.append("%s code 重复：%s" % (where, code))
        seen.add(code)
        if code and not CODE_RE.fullmatch(str(code)):
            probs.append("%s code 只许小写 ASCII、数字、点、下划线：%s" % (where, code))
        if e.get("chapter") not in CHAPTERS:
            probs.append("%s 章名不在受控集合里：%s" % (where, e.get("chapter")))
        if not isinstance(e.get("aliases", []), list):
            probs.append("%s aliases 必须是数组" % where)
    return probs


def load():
    """code → 条目。第一次调用时校验，词表坏了直接抛 —— 它是种子数据，
    不该在运行时静默降级。"""
    global _by_code, _index
    if _by_code is None:
        entries = json.load(open(SEED, encoding="utf-8"))
        probs = validate(entries)
        if probs:
            raise ValueError("kp_seed.json 不合法：\n  " + "\n  ".join(probs))
        _by_code = {e["code"]: e for e in entries}
        _index = {}
        for e in entries:
            for key in [e["code"], e["name"]] + list(e.get("aliases", [])):
                _index[str(key).strip()] = e["code"]
    return _by_code


def resolve(s):
    """按 code / 名字 / 别名**精确**找 code。找不到回 None，不猜。"""
    if not s:
        return None
    load()
    return _index.get(str(s).strip())


def catalog_text():
    """喂给模型的词表全文，按章分组。"""
    by_ch = {}
    for e in load().values():
        by_ch.setdefault(e["chapter"], []).append(e)
    out = []
    for ch in CHAPTERS:
        out.append("【%s】" % ch)
        for e in by_ch.get(ch, []):
            out.append("  %s  %s" % (e["code"], e["name"]))
    return "\n".join(out)


def main():
    entries = json.load(open(SEED, encoding="utf-8"))
    probs = validate(entries)
    if probs:
        print("✗ 词表不合法：")
        for p in probs:
            print("  ·", p)
        return 1
    by_ch = {}
    for e in entries:
        by_ch[e["chapter"]] = by_ch.get(e["chapter"], 0) + 1
    print("✓ 词表合法，共 %d 条" % len(entries))
    for ch in CHAPTERS:
        print("   %-16s %d" % (ch, by_ch.get(ch, 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
