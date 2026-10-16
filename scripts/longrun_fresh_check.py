# -*- coding: utf-8 -*-
"""longrun 的「验证命令」帮手：读 `guji status <册> -w <ws> --pages all --json` 的 stdout，
要求给定各步的每一页都是 fresh（挡住「guji pipeline rc 0 但有页失败／缺页」）。
用法：guji status vol03 -w $WS --pages all --json 2>/dev/null | python3 -I scripts/longrun_fresh_check.py border_detect,column_warp
rc 0＝全 fresh；1＝有 stale／missing／failed／blocked（打印逐步计数）；2＝输入不是 status JSON。"""
import json, sys
steps = [s for s in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if s]
try:
    d = json.loads(sys.stdin.read())
except ValueError:
    print("输入不是 status JSON", file=sys.stderr); sys.exit(2)
n = len(d.get("pages", [])); bad = False
for s in steps or d["steps"]:
    c = d["steps"].get(s, {}).get("counts")
    if c is None:
        print(f"{d.get('book')}: 没有步骤 {s}"); bad = True; continue
    ok = c.get("fresh") == n
    print(f"{d.get('book')} {s}: fresh {c.get('fresh')}/{n} stale {c.get('stale')} missing {c.get('missing')} failed {c.get('failed')} blocked {c.get('blocked')}" + ("" if ok else "  ✗"))
    bad |= not ok
sys.exit(1 if bad else 0)
