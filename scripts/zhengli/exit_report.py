#!/usr/bin/env python3
"""粗校出口报告拼装（GUJI-556 / 设计 GUJI-543 §3.3 R1–R5）。

输入是一份 JSON（由 collect_exit.py 自动取数生成，也可手填），
输出固定格式 Markdown。不读 products，不写 cv。

输入示例（见同目录 sample_input.json）：
{"book":"vol01","cv_version":"9587e67c","generated":"10-16 22:30 PDT",
 "items":{"R1":{"result":"PASS","number":"stale=0 / 总页 209","cmd":"guji progress","attach":""},
          "R2":{...},"R3":{"result":"REPORT",...},"R4":{...},"R5":{...}}}
result 取值：PASS／FAIL／REPORT（仅 R3）。总判：R1、R2、R4、R5 全 PASS 且 R3 有数字与原因 → 可出 0.1.0。

用法：python3 exit_report.py input.json > 报告.md ；退出码 0＝可出 0.1.0，1＝不可。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = ["R1", "R2", "R3", "R4", "R5"]
TITLE = {
    "R1": "全部页步骤跑完，固定 CV 版本下无 stale",
    "R2": "三道闸失败列都有去向",
    "R3": "人审率（目标<1%，不卡出口，须写原因）",
    "R4": "异常清单都有结论",
    "R5": "导出过格式检查（close-check）",
}


def main(path: str) -> int:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    items = d["items"]
    out = [f"# {d['book']} 粗校出口报告 · cv_version={d['cv_version']} · 生成于 {d['generated']}", "",
           "| 项 | 内容 | 结果 | 数字 | 命令 | 附件 |", "|---|---|---|---|---|---|"]
    problems = []
    for k in ORDER:
        it = items.get(k)
        if not it:
            problems.append(f"{k} 缺")
            out.append(f"| {k} | {TITLE[k]} | 缺 | — | — | — |")
            continue
        res = it["result"]
        if k == "R3":
            if res != "REPORT" or not it.get("number") or not it.get("reason"):
                problems.append("R3 缺数字或原因")
            num = f"{it.get('number','')}；原因：{it.get('reason','')}"
        else:
            if res != "PASS":
                problems.append(f"{k} {res}")
            num = it.get("number", "")
        out.append(f"| {k} | {TITLE[k]} | {res} | {num} | {it.get('cmd','')} | {it.get('attach') or '—'} |")
    pins = d.get("pins") or {}
    if pins:                                   # 钉版只提示，不进 problems（GUJI-656）
        got = "、".join(f"{k}={pins[k]}" for k in ("cv_version", "corpus", "glyph_pin") if pins.get(k) is not None)
        out += ["", "钉版：" + (got or "无") + ("；⚠ " + "、".join(pins["warn"]) + "（提示，不挡出口）" if pins.get("warn") else "")]
    out += ["", "总判：" + ("可出 0.1.0" if not problems else "不可出 0.1.0（" + "；".join(problems) + "）")]
    print("\n".join(out))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
