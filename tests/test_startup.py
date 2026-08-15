"""
服务启动那一刻做两件事，**顺序不能反**。

这条测试盯的是一个测试套件天生看不见的窟窿：`conftest` 自己会
`store.init_schema()`，所以**测试里库永远是最新的** —— 而真实的后端在这次之前
根本不建表（只有命令行 `store.py init` 会，`run.sh` 里没有这一步）。

于是「改了 schema.sql 但忘了手动迁移」的表现是：重启之后一切正常，直到有人
打开答题卡页面 —— `list_sheets` 撞上不存在的列，整页 500，而全套测试是绿的。

扫孤儿要读 `answer_sheets.status`，那一列可能正是这次加的 ——
所以迁移必须排在扫描前面。
"""
import asyncio
import unittest
from unittest.mock import patch

from pipeline import api


class StartupOrder(unittest.TestCase):
    def test_先迁库再扫孤儿(self):
        order = []

        async def run():
            with (
                patch.object(api.store, "init_schema",
                             side_effect=lambda: order.append("migrate")),
                patch.object(api.store, "sweep_running_sheets",
                             side_effect=lambda: (order.append("sweep"), 0)[1]),
            ):
                async with api.lifespan(api.app):
                    pass

        asyncio.run(run())

        self.assertEqual(["migrate", "sweep"], order)

    def test_扫不动孤儿不许拦住启动(self):
        """
        库连不上是另一回事，有它自己的报错路径。扫不动孤儿只该少一条信息 ——
        让整个服务起不来是把小事故放大成大事故。
        """
        async def run():
            with (
                patch.object(api.store, "init_schema"),
                patch.object(api.store, "sweep_running_sheets",
                             side_effect=RuntimeError("库正在重启")),
            ):
                async with api.lifespan(api.app):
                    pass

        asyncio.run(run())        # 不抛就是通过


if __name__ == "__main__":
    unittest.main()
