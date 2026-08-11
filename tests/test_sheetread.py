# -*- coding: utf-8 -*-
"""
Ⓑ 的三段纯函数：切条、合并、对总分。模型调用不在这里测。

Ⓑ 是**两遍**：
  Ⓑa 整页原分辨率 → `{n, y, answer, mark}`（实测作答 10/10、符号 10/10）
  Ⓑb 按 y 切条、放大 3× → `{n, filled, got, full, red}`（填涂 8/8、得分 8/8）
  Ⓑc 单独一小块读总分（**必须和逐题得分不同源**，否则那条校验是自证）

为什么不是「整页读一遍」：整页那一遍在两处必然丢东西 —— 选择题填涂 8 道全
认不出（模型自己标 `conf: low`，是老实的），得分 10 条错 2 条，而错的那条正是
12(3) 的 `1分(满分2分)` 被读成 `1分(满分1分)`，把「半对」抹成了「全对」。

为什么不是「固定横条」：切口从大题中间穿过时，模型只看得见 `(1)` 看不见 `13.`，
13 题四个小问的题号全裸奔；得分还漏了一半，墙钟更长。**框得由第一遍的 y 给。**
"""
import sheetread


# ---------------------------------------------------------------- 切条

# 探针在真材料上读出来的那一页（`20260807-234347` 左半，750px 高）。
# 拿真值当样本，别用编的 —— 编的 y 分布会把切条规则测成另一回事。
REAL = [(1, 0.355), (2, 0.368), (3, 0.381), (4, 0.394), (5, 0.407),
        (6, 0.420), (7, 0.433), (8, 0.446), (9, 0.490), (10, 0.530),
        (11, 0.568), (1201, 0.638), (1202, 0.680), (1203, 0.718),
        (1301, 0.788), (1302, 0.828), (1304, 0.868), (1305, 0.905)]


def test_一条最多装八道题():
    """上限来自探针里成功的两个裁块，都是 8 行"""
    got = sheetread.strips(REAL, 750)
    assert all(len(ns) <= 8 for ns, _, _ in got), [ns for ns, _, _ in got]


def test_一条不许大到退化成整页():
    """
    真正要守的是这个：条一大就等于「整页读一遍」，而那条路探针已经否掉了
    （选择题填涂全丢、得分错 2 条）。

    注意条的下边界会**延到下一组的开头**，所以它比「组内跨度」大一截；
    断言写成「组内跨度 ≤ 上限」才是对的口径，而整条的高度另有一条更松的上限。
    """
    got = sheetread.strips(REAL, 750)
    assert all(bot - top < 0.6 * 750 for _, top, bot in got), \
        [(bot - top) for _, top, bot in got]


def test_真实那一页切成三到四条():
    """
    不能整页一条（那是被探针否掉的路），也不能一题一条（一页十几次调用）。
    实测这一页 18 道题，按 8 道/260px 打包落在 3-4 条。
    """
    got = sheetread.strips(REAL, 750)
    assert 3 <= len(got) <= 4, len(got)


def test_选择题那八道装在同一条里():
    """
    它们的 y 只差 0.013（750px 上约 10px），必须并在一起 ——
    一题一条的话每条才 10px，而并起来约 100px、放大 3× 正好就是探针里
    拿了 8/8 的那个裁法。
    """
    got = sheetread.strips(REAL, 750)
    first = got[0][0]
    assert first[:8] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_每道题都落在某一条里():
    """漏掉一道题就是漏掉一道题的分数和填涂，而且没人会报错"""
    got = sheetread.strips(REAL, 750)
    covered = [n for ns, _, _ in got for n in ns]
    assert covered == [n for n, _ in REAL]


def test_条与条允许重叠():
    """
    得分标注印在作答行的**上方**，pad 不够会把标注切给上一条
    （实测第 11 题那条里带着 12(1) 的「1分(满分1分)」）。

    重叠在这里无害，**因为 Ⓑ 的条和 Ⓔ 的条性质不同**：Ⓔ 切出来的图是给人看的
    成品（贴在页面上当题干），多带一道题就是版面缺陷；Ⓑ 的条只是喂给模型的
    输入，而且提示词已经写明这一条要读哪几道题。
    """
    got = sheetread.strips(REAL, 750)
    assert got[1][1] < got[0][2], "第二条的上边应该落在第一条里面"


def test_上边留得比读题干那一步多():
    """得分标注在作答行上方约 20-30px，pad=0.012（Ⓔ 的值）不够"""
    (_, top, _), = sheetread.strips([(9, 0.5)], 1000)
    assert 0.5 * 1000 - top >= 30


def test_y不递增就整页不切():
    """位置读乱了，切出来每一条都对不上题号 —— 宁可这一页不切"""
    assert sheetread.strips([(9, 0.7), (10, 0.3)], 750) == []


def test_题号没排好也不切():
    assert sheetread.strips([(11, 0.3), (9, 0.7)], 750) == []


def test_没有标记就不切():
    assert sheetread.strips([], 750) == []


def test_越界的y丢掉():
    got = sheetread.strips([(9, 0.5), (10, 1.7)], 750)
    assert [ns for ns, _, _ in got] == [[9]]


def test_最后一条切到页底():
    (_, _, bot), = sheetread.strips([(9, 0.5)], 750)
    assert bot == 750


# ---------------------------------------------------------------- 合并

def test_两遍逐字段取非空():
    rows, clash = sheetread.merge(
        [{"n": 9, "answer": "不变 / 17190", "mark": "right"}],
        [{"n": 9, "got": 3, "full": 3}])
    assert rows[0]["answer"] == "不变 / 17190"
    assert rows[0]["got"] == 3 and rows[0]["mark"] == "right"
    assert clash == []


def test_先到先得是错的():
    """
    实测踩过：同一题两条记录，一条有 got/full 一条没有，按先到先得合并
    **把有分数的那条丢了**。
    """
    rows, _ = sheetread.merge([{"n": 11, "mark": "wrong"}],
                              [{"n": 11, "got": 0, "full": 3}])
    assert rows[0]["got"] == 0 and rows[0]["full"] == 3


def test_两边都非空且不等要记冲突():
    _, clash = sheetread.merge([{"n": 9, "answer": "17190"}],
                               [{"n": 9, "answer": "17180"}])
    assert len(clash) == 1 and clash[0]["n"] == 9


def test_冲突了也不许悄悄挑一个():
    """挑一个就等于替后端下了结论，而两边都可能是错的"""
    rows, clash = sheetread.merge([{"n": 9, "answer": "17190"}],
                                  [{"n": 9, "answer": "17180"}])
    assert clash and "17190" in clash[0]["why"] and "17180" in clash[0]["why"]


def test_读不出来不算冲突():
    """
    `unreadable` / `blank` 是**读取状态**，不是作答内容。选择题上 Ⓑa 必然回
    `unreadable`、Ⓑb 回 8/8 —— 按「两边不等就记冲突」的话，8 道选择题每一道
    都会冒一条假警告，而**永远亮着的警告等于没有警告**。
    """
    rows, clash = sheetread.merge([{"n": 1, "answer": "unreadable"}],
                                  [{"n": 1, "filled": "D"}])
    assert rows[0]["answer"] == "D"
    assert clash == []


def test_空着也让位给真读出来的():
    rows, clash = sheetread.merge([{"n": 1, "answer": "blank"}],
                                  [{"n": 1, "filled": "D"}])
    assert rows[0]["answer"] == "D" and clash == []


def test_两边都读不出来就还是读不出来():
    rows, _ = sheetread.merge([{"n": 1, "answer": "unreadable"}], [{"n": 1}])
    assert rows[0]["answer"] == "unreadable"


def test_老师红笔写的不许混进学生作答():
    """
    整页放大 2× 那一版就是这么错的：题 6 把老师红笔写的正确答案 BC
    当成了学生的作答报回来。两样必须分成两个字段。
    """
    rows, _ = sheetread.merge([{"n": 6, "answer": "unreadable"}],
                              [{"n": 6, "filled": "AC", "red": "BC"}])
    assert rows[0]["answer"] == "AC" and rows[0]["red"] == "BC"


def test_第二遍冒出第一遍没有的题号要报出来():
    """
    那说明切条切歪了。

    （函数名里不许写 `Ⓑ` —— 带圈字母不是 Python 合法标识符，
    仓库 STATUS 的「踩过的坑」第 6 条记着这一条。）
    """
    _, clash = sheetread.merge([{"n": 9}], [{"n": 9}, {"n": 99}])
    assert any(c["n"] == 99 for c in clash)


def test_第一遍有第二遍没有的不算异常():
    """Ⓑb 只补细节，某一条没补上是常态（那一条本来就没有分数标注）"""
    _, clash = sheetread.merge([{"n": 9}, {"n": 10}], [{"n": 9}])
    assert clash == []


def test_合并后按题号排好():
    rows, _ = sheetread.merge([{"n": 11}, {"n": 9}], [{"n": 10}, {"n": 9}])
    assert [r["n"] for r in rows] == [9, 10, 11]


# ---------------------------------------------------------------- 对总分

def test_加起来对得上就过():
    rows = [{"n": 9, "got": 3}, {"n": 11, "got": 0}, {"n": 15, "got": 7.5}]
    ok, _ = sheetread.checksum(rows, 10.5)
    assert ok


def test_对不上要说出来():
    ok, why = sheetread.checksum([{"n": 9, "got": 3}], 10.5)
    assert not ok and "10.5" in why and "3" in why


def test_没读到总分就跳过这条校验():
    ok, why = sheetread.checksum([{"n": 9, "got": 3}], None)
    assert ok and "没读到总分" in why


def test_小数不许被浮点误差判成对不上():
    rows = [{"n": i, "got": 0.1} for i in range(10)]
    assert sheetread.checksum(rows, 1.0)[0]


def test_对调两题的得分它查不出来():
    """
    **这条测的是判据的边界，不是缺陷。** Σ 对调换天然免疫 ——
    把它当成「读串的防线」会让人以为有防线而其实没有。

    读串靠另外三条：两遍对账（上面那条）、题号清单对账（Ⓒ 那一步）、
    满分对账（`full` 要对得上参考答案上印的分值）。
    """
    a = [{"n": 9, "got": 3}, {"n": 10, "got": 1}]
    b = [{"n": 9, "got": 1}, {"n": 10, "got": 3}]
    assert sheetread.checksum(a, 4)[0] and sheetread.checksum(b, 4)[0]


def test_没有分数的行不进求和():
    """卷子上就没印分数的题，不该被当成 0 分拉低总和"""
    ok, _ = sheetread.checksum([{"n": 9, "got": 3}, {"n": 10}], 3)
    assert ok


# ---------------------------------------------------------------- 勾叉两遍都读
#
# 2026-08-10 端到端实跑逼出来的：选择题 6/7/8 判成了「说不清」。作答读对了
# （AC/BC/D），但那三行**没有印分数**，而 Ⓑa 这一次没给出它们的勾叉 —— 退无可退。
# 1-5 同样没分数却判对了，说明这是模型逐行的不稳定，不是代码路径问题。
#
# 治法：**Ⓑb 也报 mark**。它看的是放大 3 倍的条，探针在同一块上勾叉读了 8/8。
# 两遍都读，合并时谁读到算谁的。

def test_第二遍读到的勾叉能补上第一遍的空():
    rows, clash = sheetread.merge([{"n": 6, "answer": "AC"}],
                                  [{"n": 6, "mark": "wrong"}])
    assert rows[0]["mark"] == "wrong"
    assert clash == []


def test_没看见不许盖过看见了():
    """
    `mark: "none"` 是「这一行我没看见批改符号」，不是「这一行确实没有符号」——
    拿它盖掉另一遍**看见了**的读数，正好把有信息的那条丢了。
    实跑里 1-5 判对而 6/7/8 说不清，差别就在这一栏。
    """
    rows, clash = sheetread.merge([{"n": 7, "mark": "none"}],
                                  [{"n": 7, "mark": "right"}])
    assert rows[0]["mark"] == "right"
    assert clash == [], "「没看见」和「看见了」不算两遍矛盾"


def test_反过来也一样():
    rows, _ = sheetread.merge([{"n": 7, "mark": "right"}],
                              [{"n": 7, "mark": "none"}])
    assert rows[0]["mark"] == "right"


def test_两遍都看见了但不一样才算矛盾():
    _, clash = sheetread.merge([{"n": 7, "mark": "right"}],
                               [{"n": 7, "mark": "wrong"}])
    assert len(clash) == 1


def test_两遍都没看见就还是没看见():
    rows, _ = sheetread.merge([{"n": 7, "mark": "none"}], [{"n": 7}])
    assert rows[0]["mark"] == "none"


# ---------------------------------------------------------------- 差额要有归属

def test_对不上时点名说哪几道没有分数():
    """
    实跑：Σ 差 28 分，而那 28 正好是选择题 1-8 的总分 —— 它们在答题卡上
    **本来就不印每题得分**。只说「差 28」会让人以为读错了；
    点名说出「这 8 道没有分数标注」，差额就有了归属。
    """
    rows = [{"n": 9, "got": 3}] + [{"n": i} for i in range(1, 9)]
    ok, why = sheetread.checksum(rows, 31)
    assert not ok
    assert "8 道没有分数标注" in why
    assert "1" in why and "8" in why


def test_全都有分数时不说这句多余的话():
    ok, why = sheetread.checksum([{"n": 9, "got": 3}], 5)
    assert not ok and "没有分数标注" not in why
