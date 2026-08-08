# -*- coding: utf-8 -*-
"""
③ 盲试那一级走哪个端点。

为什么要单独的覆盖变量
----------------------
`DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL` 是**五处共用**的：
③ 解题、③b 目录、③c 知识点、④c 选题、② 的 LLM 兜底。后三处早就各有各的
`EXAM_OUTLINE_* / EXAM_KP_* / EXAM_PICK_*` 覆盖，只有 ③ 没有 —— 于是想给 ③
换个端点，只能去改那三个全局变量，把另外四步一起拖下水。

而 ③ 恰恰是最不该跟着别人走的一步：**它的答案会被 ④ 冻成物理断言**，
换脑子的影响一路传到动画，而且是静默的。所以它要能单独钉住。

命名跟隔壁三个模块一致（`EXAM_<阶段>_KEY/BASE/MODEL`），不另造一套。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import solve


def pick(env):
    """按 solve.py 顶上那三行的规则求一次值。"""
    return (env.get("EXAM_SOLVE_KEY") or env.get("DEEPSEEK_API_KEY", ""),
            env.get("EXAM_SOLVE_BASE") or env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            env.get("EXAM_SOLVE_MODEL") or env.get("DEEPSEEK_MODEL", "deepseek-v4-pro"))


def test_没设覆盖时跟着全局的_deepseek_走():
    """不设新变量，行为一个字都不能变。"""
    assert pick({"DEEPSEEK_API_KEY": "k", "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                 "DEEPSEEK_MODEL": "deepseek-v4-pro"}) == \
        ("k", "https://api.deepseek.com", "deepseek-v4-pro")


def test_三个全都没有时的默认值():
    assert pick({}) == ("", "https://api.deepseek.com", "deepseek-v4-pro")


def test_覆盖变量赢过全局():
    got = pick({"DEEPSEEK_API_KEY": "old", "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
                "EXAM_SOLVE_KEY": "ark", "EXAM_SOLVE_MODEL": "deepseek-v4-flash-ga-260731",
                "EXAM_SOLVE_BASE": "https://ark.cn-beijing.volces.com/api/v3"})
    assert got == ("ark", "https://ark.cn-beijing.volces.com/api/v3",
                   "deepseek-v4-flash-ga-260731")


def test_三个可以分别覆盖():
    """只换模型、端点仍走全局，这种半换的组合要成立。"""
    got = pick({"DEEPSEEK_API_KEY": "k", "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "DEEPSEEK_MODEL": "deepseek-v4-pro", "EXAM_SOLVE_MODEL": "别的模型"})
    assert got == ("k", "https://api.deepseek.com", "别的模型")


def test_模块里的三个常数就是按这个规则求的():
    """
    上面那些验的是规则，这条验 solve.py 真的照这个规则写了 ——
    否则规则测得再全，模块里写成别的样子也一样白搭。
    """
    assert (solve.DS_KEY, solve.DS_BASE, solve.DS_MODEL) == pick(os.environ)


def test_跑完那行要说清楚盲试走的是谁():
    """
    「跑完都不知道钱记在哪边」这件事在 ⑤ 上踩过。③ 同样要能一眼看出
    盲试用的是哪个模型 —— 它是整条链里唯一决定答案对错的一步。
    """
    assert callable(solve.blind_banner)
    assert "deepseek-v4-flash-ga-260731" in solve.blind_banner(
        "https://ark.cn-beijing.volces.com/api/v3", "deepseek-v4-flash-ga-260731")
    assert "火山方舟" in solve.blind_banner(
        "https://ark.cn-beijing.volces.com/api/v3", "deepseek-v4-flash-ga-260731")
    assert "DeepSeek 官方" in solve.blind_banner(
        "https://api.deepseek.com", "deepseek-v4-pro")
