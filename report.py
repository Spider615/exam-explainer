#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report.py —— 汇总一次端到端实验的结果

读取每个 runs/<id>/_verify_log.jsonl（门禁自己写的，不依赖被测方自觉），
输出：迭代轮次、每轮失败的断言、首轮通过率、最终通过率、只读输入完整性。
"""
import os, json, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(ROOT, "runs")


def readonly_intact():
    """核对 harness/ 与 specs/ 是否被改过 —— 沙箱不许给自己放水"""
    base = os.path.join(ROOT, ".readonly.sha256")
    if not os.path.exists(base):
        return None, "没有基线哈希文件"
    want = {}
    for line in open(base, encoding="utf-8"):
        h, p = line.strip().split(None, 1)
        want[p] = h
    bad = []
    for p, h in want.items():
        full = os.path.join(ROOT, p)
        if not os.path.exists(full):
            bad.append(p + " (已删除)"); continue
        got = subprocess.run(["shasum", "-a", "256", full],
                             capture_output=True, text=True).stdout.split()[0]
        if got != h:
            bad.append(p + " (已修改)")
    return (not bad), ("完整，%d 个文件未被改动" % len(want) if not bad else "被篡改: " + ", ".join(bad))


def main():
    print("═" * 68)
    print("端到端实验汇总")
    print("═" * 68)

    okro, msg = readonly_intact()
    mark = "✓" if okro else ("?" if okro is None else "✗")
    print("\n只读输入完整性  %s  %s\n" % (mark, msg))

    scenes = sorted(d for d in os.listdir(RUNS) if os.path.isdir(os.path.join(RUNS, d)))
    rows, total_rounds, n_pass, n_first = [], 0, 0, 0

    for sid in scenes:
        logp = os.path.join(RUNS, sid, "_verify_log.jsonl")
        if not os.path.exists(logp):
            rows.append((sid, 0, "未运行", "—")); continue
        entries = [json.loads(l) for l in open(logp, encoding="utf-8") if l.strip()]
        if not entries:
            rows.append((sid, 0, "无记录", "—")); continue

        final = entries[-1]["verdict"]
        n = len(entries)
        total_rounds += n
        if final == "PASS":
            n_pass += 1
        # 「首轮即过」看第一次验收的结果，而不是总轮次是否为 1——
        # 门禁后来加了新层，会让已完成的场景多出几轮复验。
        if entries[0]["verdict"] == "PASS":
            n_first += 1

        spec = json.load(open(os.path.join(ROOT, "specs", sid + ".spec.json"), encoding="utf-8"))
        rows.append((sid, n, final, "%d 条断言 / %d 个 case"
                     % (len(spec["invariants"]), len(spec["cases"]))))

        print("── %s  (%s)  %d 轮  →  %s" % (sid, spec.get("difficulty", "?"), n, final))
        for e in entries:
            if e["verdict"] == "PASS":
                print("   第%d轮  PASS" % e["round"])
            else:
                codes = []
                for f in e["fails"]:
                    codes.append("%s/%s" % (f["layer"], f["code"]))
                print("   第%d轮  FAIL ×%d  %s" % (e["round"], e["n_fail"], "  ".join(codes)))
        # 失败层级分布
        dist = {}
        for e in entries:
            for f in e["fails"]:
                dist[f["layer"]] = dist.get(f["layer"], 0) + 1
        if dist:
            print("   失败分布：%s" % ", ".join("%s×%d" % kv for kv in sorted(dist.items())))
        print()

    print("─" * 68)
    print("场景数 %d ｜ 最终通过 %d ｜ 首轮即过 %d ｜ 总验收轮次 %d ｜ 平均 %.1f 轮"
          % (len(rows), n_pass, n_first, total_rounds,
             total_rounds / len(rows) if rows else 0))
    print("─" * 68)

    # 最难的断言：跨场景统计各断言 id 被判失败的次数
    tally = {}
    for sid in scenes:
        logp = os.path.join(RUNS, sid, "_verify_log.jsonl")
        if not os.path.exists(logp):
            continue
        for line in open(logp, encoding="utf-8"):
            if not line.strip():
                continue
            for f in json.loads(line)["fails"]:
                if f["layer"] == "L4":
                    tally[(sid, f["code"])] = tally.get((sid, f["code"]), 0) + 1
    if tally:
        print("\n最常失败的物理断言（L4）：")
        for (sid, code), n in sorted(tally.items(), key=lambda kv: -kv[1])[:12]:
            print("   %-5s %-24s ×%d" % (sid, code, n))
    else:
        print("\n没有任何 L4 物理断言失败过。")


if __name__ == "__main__":
    main()
