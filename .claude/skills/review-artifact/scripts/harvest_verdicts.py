# -*- coding: utf-8 -*-
"""把审查页里的裁决抠出来。

    python harvest_verdicts.py page.html [-o verdicts.jsonl]

先用 `Artifact action:"read"` 把线上那份 HTML 读到本地（页大的时候工具会直接
落成文件并把路径告诉你），再喂给这个脚本。裁决就嵌在 `#data` 的 `verdicts`
里，形如 `{id: {"v": 裁决, "t": 时间戳}}`。

`-o` 出 JSONL，一行一条 `{"id": …, "verdict": …, "t": …}`，方便直接进数据集。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PAT = re.compile(
    r'<script[^>]*id="data"[^>]*>(.*?)</script>', re.S)


def load(html: str) -> dict:
    m = PAT.search(html)
    if not m:
        sys.exit("这页里没有 #data —— 确认读的是审查页本身，不是它的截图或摘要")
    return json.loads(m.group(1).replace("<\\/", "</"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    d = load(Path(a.html).read_text(encoding="utf-8"))
    verdicts = d.get("verdicts") or {}
    rows = d.get("rows") or []
    tally = Counter(v.get("v") for v in verdicts.values())
    print(f"{len(verdicts)} / {len(rows)} 已裁　" +
          "　".join(f"{k} {n}" for k, n in tally.most_common()))
    # 没裁的那些也值得说一句：人是没看到，还是看到了拿不准？两件事不一样。
    if len(verdicts) < len(rows):
        print(f"　还有 {len(rows) - len(verdicts)} 张没裁")

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            for k, v in verdicts.items():
                f.write(json.dumps({"id": k, "verdict": v.get("v"),
                                    "t": v.get("t")}, ensure_ascii=False) + "\n")
        print(f"→ {a.out}")


if __name__ == "__main__":
    main()
