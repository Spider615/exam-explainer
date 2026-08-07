#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py —— 一条命令跑完管线

    python pipeline/run.py <试卷.pdf> [-o work/<name>] [--no-solve] [--crosscheck]

等价于依次执行：
    ingest.py     ① PDF → doc.json + 插图 + 整页渲染
    segment.py    ② doc.json → questions.json
    mathvlm.py    ②b 含公式的选项 → 视觉模型 → LaTeX（按图哈希缓存）
    store.publish ②c 构建产物 → 库（此后一切以库为准）
    refans.py     ②d 卷子自带的「参考答案」段落 → 每题的标准答案（纯代码）
    solve.py      ③ 解题（DeepSeek 盲试 → 看不到图才升级视觉模型）
    outline.py    ③b 整卷一次调用 → 每题的短标题与短答案（目录/速览用）
    kpmark.py     ③c 整卷一次调用 → 每题挂上受控词表里的知识点
    pick.py       ④c 动画选题：一次调用判整卷「哪些题值得做动画」
    spec.py       ④ 只给选中的题写 spec 与物理断言（--picked）
    speccheck.py  ④b 拿 spec 自己的参考实现验它自己的断言，自洽才放行进 ⑤
    scene.py      ⑤ 沙箱 agent 写动画，⑥ 门禁判定绿灯
    assemble.py   ⑦ → 自包含 out.html

和网页上传**跑的是同一串**。两条入口必须一样长，否则「上传的卷子」和
「命令行跑的卷子」会在页面上呈现出两种完成度，而没有任何东西能提示这件事。

⑤ 前面那道闸门是换掉了、不是拆掉：原来要人审 `specs.status` 才放行，
现在由 ④b 顶上 —— 拿 spec 自带的可执行受力方程跑一遍，满足不了自己的断言
就判 rejected，进不了 ⑤。**这不是又问一个模型，是一次计算。**
但它只查 spec 内部矛盾：③ 理解错题、④ 忠实地写成自洽的错 spec，这一关全绿。
那要对照原卷，是人的活。

⑤ 很贵：一题几分钟到几十分钟，一卷可能几个钟头。只想拿到题目和解法就加 --no-scene。

缺什么就在页面上显式写出来，不拿占位内容充数：没解的题写「尚未生成」，
没断言的解法标「无断言 · 未被检验」，模型自评低的、复核不一致的都标出来。
"""
import argparse, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable


def step(n, name, cmd):
    print("\n\033[1m▸ 阶段%s %s\033[0m" % (n, name))
    t0 = time.time()
    r = subprocess.run(cmd)
    dt = time.time() - t0
    if r.returncode != 0:
        print("\n✗ 阶段%s 失败（退出码 %d），管线中止" % (n, r.returncode))
        sys.exit(r.returncode)
    print("   （%.1fs）" % dt)
    return dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--strict", action="store_true", help="切分有告警就中止")
    ap.add_argument("--title", default=None)
    ap.add_argument("--no-solve", action="store_true",
                    help="只跑到装配，不调解题与断言（纯代码、零模型调用）")
    ap.add_argument("--no-scene", action="store_true",
                    help="跳过 ⑤ 生成场景（它一卷可能要跑几个钟头）")
    ap.add_argument("--crosscheck", action="store_true",
                    help="解题时独立解两遍，不一致就降为 low 并标记")
    ap.add_argument("-j", "--jobs", type=int, default=4, help="解题并行度")
    a = ap.parse_args()

    name = os.path.basename(a.pdf).rsplit(".", 1)[0]
    work = a.out or os.path.join(ROOT, "work", name)
    out = os.path.join(work, "out.html")

    print("═" * 62)
    print("exam-explainer 管线　%s" % os.path.basename(a.pdf))
    print("═" * 62)

    total = 0
    total += step("①", "PDF 摄入", [PY, os.path.join(HERE, "ingest.py"), a.pdf, "-o", work])
    seg = [PY, os.path.join(HERE, "segment.py"), work]
    if a.strict:
        seg.append("--strict")
    total += step("②", "题目切分", seg)
    # ②b 公式识别：只对「选项区里有横线」的题调用视觉模型，按图哈希缓存。
    # 不能省 —— 缺了它选项只有被压平的一维文本，下游解题看不懂公式
    total += step("②b", "公式识别", [PY, os.path.join(HERE, "mathvlm.py"), work])
    # 发布：构建产物 → 库。之后所有环节都以库为准，work/ 只是中间目录。
    #
    # 命令行这条路没有登录态，卷子落库时是**无主**的 —— 而页面按账号隔离，
    # 无主的卷子在页面上谁都看不到。所以 .env 里可以写 EXAM_OWNER_EMAIL
    # 指定归谁；没写就先留着无主，之后 `store.py claim <邮箱>` 收。
    total += step("②c", "发布入库",
                  [PY, "-c", "import os,sys;sys.path.insert(0,%r);import store;"
                             "u=store.get_user_by_email(os.environ.get('EXAM_OWNER_EMAIL',''));"
                             "print(store.publish(%r, owner_id=u and u['id']));"
                             "print('归属：' + (u['email'] if u else "
                             "'无主（.env 里设 EXAM_OWNER_EMAIL，或事后 store.py claim）'))"
                             % (HERE, work)])

    # ②d 标准答案：纯代码，读 doc.json 找「参考答案」段落按题号切。
    # 抽不到就全记 none —— 高考真题本来就不带答案，那不是失败。
    # （编号用 ②d 而不是 ②c：②c 已经是「发布入库」了）
    total += step("②d", "标准答案抽取",
                  [PY, os.path.join(HERE, "refans.py"), name])

    if not a.no_solve:
        total += step("③", "解题", [PY, os.path.join(HERE, "solve.py"), name,
                                    "-j", str(a.jobs)] +
                                   (["--crosscheck"] if a.crosscheck else []))
        total += step("③b", "目录（短标题与短答案）",
                      [PY, os.path.join(HERE, "outline.py"), name])
        # ③c 知识点：排在 ③ 之后是因为用得上解法。整卷一次调用，几十秒
        total += step("③c", "知识点标注",
                      [PY, os.path.join(HERE, "kpmark.py"), name])
        # ④c 在 ④ 之前：28 秒的筛子必须排在 6 分钟一道的活前面
        total += step("④c", "动画选题", [PY, os.path.join(HERE, "pick.py"), name])
        total += step("④", "写 spec 与断言（只做选中的题）",
                      [PY, os.path.join(HERE, "spec.py"), name, "--picked"])
        # ④b 是 ⑤ 的准入闸门：纯计算，不调模型。自己的参考实现满足不了
        # 自己的断言就判 rejected，进不了 ⑤
        total += step("④b", "spec 自检",
                      [PY, os.path.join(HERE, "speccheck.py"), name, "--apply"])
        if not a.no_scene:
            total += step("⑤", "生成场景（带反馈的循环，多题并行）",
                          [PY, os.path.join(HERE, "scene.py"), name])

    asm = [PY, os.path.join(HERE, "assemble.py"), name, "-o", out]
    if a.title:
        asm += ["--title", a.title]
    total += step("⑦", "装配成页", asm)

    print("\n" + "─" * 62)
    print("完成，合计 %.1fs　→ %s" % (total, out))
    if a.no_scene:
        print("跳过了 ⑤。要补动画：.venv/bin/python pipeline/scene.py %s" % name)
    print("─" * 62)


if __name__ == "__main__":
    main()
