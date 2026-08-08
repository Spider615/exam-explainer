#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check.py —— 拼装 + 门禁，一条命令

    python3 harness/check.py <id>

为什么要合成一条
----------------
契约里写的是 `build.py && verify.py`，但实测 agent 会**只跑后半句**：
一次 54 轮的会话里 `verify.py` 跑了 12 次、`build.py` 只跑了 3 次。
改完 `draw.js` 不重拼就去验，验的是上一次拼出来的旧 `<id>.js` ——
它在追一堆自己已经改掉的错，那 9 次全白跑。

**靠嘱咐不如靠门禁**：合成一条命令之后，「只验不拼」在结构上就不存在了。

末行仍然是 `VERDICT: PASS` / `VERDICT: FAIL`，与 `verify.py` 一致 ——
上层判绿灯的逻辑一个字都不用改。
"""
import json, os, subprocess, sys

HARNESS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HARNESS)


def main():
    if len(sys.argv) < 2:
        print("用法：python3 harness/check.py <id>")
        return 2
    sid = sys.argv[1]
    py = os.path.join(ROOT, ".venv", "bin", "python")
    py = py if os.path.exists(py) else sys.executable

    # 只有代码生成那条路才需要拼装；老路没有 draw.js，直接验
    if os.path.exists(os.path.join(os.getcwd(), sid + ".draw.js")):
        r = subprocess.run([py, os.path.join(HARNESS, "build.py"), sid])
        if r.returncode != 0:
            print("\n拼装没过，门禁没跑。先按上面的问题改 figure.html 或 draw.js。")
            print("VERDICT: FAIL")
            return 1

    return subprocess.run([py, os.path.join(HARNESS, "verify.py"), sid]).returncode


if __name__ == "__main__":
    sys.exit(main())
