# -*- coding: utf-8 -*-
"""按人裁的**分类**结论重排排除名单：把没证据的那几类放回来。

    PYTHONPATH=. python scripts/retighten_crop_exclusions.py [--apply]

## 依据

`config/crop_exclusions.jsonl` 里 pipeline-suspect / gate / position 三档是
启发式旗标，从没验过。「排除名单复核台」按 (来源, 旗标) 分 10 类各抽 10 张
人裁（98/98 全裁完），结果分得非常干净：

    类别                       抽   该排除率   全库
    空隙偏大 wide_gap          10     100%     131
    边界墨 + 空隙              10     100%      50
    重心偏 off_center           8     100%       8
    被截断 truncated           10      60%      34
    残余 residue               10      30%      59
    ----------------------------------------------  以上保留
    墨压边界 boundary_ink      10      10%    1004
    下边框 frame_bar_bottom    10       0%      41
    列首 idx=0                 10       0%      50
    列尾 idx=19                10       0%     148
    列尾外 idx=20              10       0%      24
    ----------------------------------------------  以上释放

两条要害：

1. **`wide_gap` 才是真信号，`boundary_ink` 不是。** 复合旗标
   「边界墨+空隙」100% 该排除，那 100% 全是 wide_gap 带来的——单独的
   `boundary_ink` 只有 10%，而它一个人就占了候选的 65%（1004 条）。
2. **位置规则三类全是 0%。** 「列首列尾是切分惯犯」当初是从**旗标命中率**
   推的，不是从缺陷率推的——旗标爱在列尾响，不等于列尾的图块坏。

`frame_bar_bottom` 0/10 也值得上游看一眼：闸说「吃到下边框」，人看全是好字，
要么检测器有问题，要么边框早被裁掉了。

## 纪律

释放不是删除：放回来的条目原样搬进 `config/crop_exclusions_released.jsonl`，
带上「凭哪一类的人裁放的、那类抽了几张」。将来重扫或者哪类翻案，一条条拿得
回来。样本就是每类 10 张，**别拿这些比例当精确值**——它只够支撑「这一类有没有
证据」这个粗判断。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.exclusions import load_exclusions  # noqa: E402

ROUND = "category_review_r1"
SRC = "https://claude.ai/code/artifact/faf12f8f-4ede-41ce-8b4f-bd7254d003b9"

# 人裁清白、可以整类放回来的旗标组合。**只列复核台真的抽到过的那些**——
# 没验过的旗标（rule_bar_left、frame_bar_top…）数量都是个位数，留着不动，
# 宁可继续排除，也不拿没证据的类去赌。
RELEASE_EXACT: set[tuple[str, tuple[str, ...]]] = {
    ("pipeline-suspect", ("boundary_ink",)),
    ("gate", ("frame_bar_bottom",)),
}
RELEASE_ORIGIN = {"position"}          # idx=0/19/20 三类都是 0/10


def key(r: dict) -> tuple[str, tuple[str, ...]]:
    return r["origin"], tuple(sorted(r.get("evidence") or []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--list", default="config/crop_exclusions.jsonl")
    ap.add_argument("--released", default="config/crop_exclusions_released.jsonl")
    a = ap.parse_args()

    rows = load_exclusions(a.list)
    keep, release = {}, {}
    for iid, r in rows.items():
        o, ev = key(r)
        if o in RELEASE_ORIGIN or (o, ev) in RELEASE_EXACT:
            release[iid] = {**r, "released_round": ROUND,
                            "released_date": str(date.today()),
                            "released_source": SRC,
                            "released_why": f"复核台「{o}|{','.join(ev)}」一类抽 10 张"
                                            f"人裁，该排除率 ≤10%——没证据，放回来"}
        else:
            keep[iid] = r

    print(f"{len(rows)} 条 → 留 {len(keep)} / 放 {len(release)}")
    print("  放回来的构成：", Counter(f"{k[0]}|{','.join(k[1])}"
                                      for k in map(key, release.values())).most_common())
    print("  留下的构成：  ", Counter(f"{k[0]}|{','.join(k[1])}"
                                      for k in map(key, keep.values())).most_common(8))
    if not a.apply:
        print("试跑，没写。加 --apply 落盘。")
        return

    def dump(path: str, d: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for iid in sorted(d):
                f.write(json.dumps(d[iid], ensure_ascii=False, sort_keys=True) + "\n")

    dump(a.list, keep)
    old = load_exclusions(a.released) if Path(a.released).exists() else {}
    dump(a.released, {**old, **release})
    print(f"→ {a.list} {len(keep)} 条　→ {a.released} {len(old) + len(release)} 条")


if __name__ == "__main__":
    main()
