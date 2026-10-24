"""字组统一评测（S1，规范见 doc/字组/README.md）。

吃 dataset `char-groups/<组>/items.jsonl`，调**同一批适配器**（`open_guji_cv/groups/backends.py`），按册、按真值档报
dataset README 规定的「分类器层」三个数：**给字率 / 给字准确率 / 弃权率**，分子分母都写，带 Wilson 95% 区间。
另有两个对照臂：`ref`（整理本对位字，组内才算给字）与 `admit`（现行管线的放行字，已放行且在组内才算给字）——
任何新后端都要跟它们比（README：`baseline.json` 是分类器接进来之前的现行数，之后每个新方法都跟它比）。

用法（不依赖工作区与快照，只要 dataset 在本地）::

    python -m open_guji_cv.eval.groups jys --dataset ../open-guji-dataset/char-groups --backend rule
    python -m open_guji_cv.eval.groups ry  --dataset ... --backend table:<group_clf/1 表>
    python -m open_guji_cv.eval.groups rr  --dataset ... --backend image[:<模型 npz>] --splits val
    python -m open_guji_cv.eval.groups jys --dataset ... --backend rule --backend ctx_table --json out.json

口径（照 dataset README「评测口径」）：
- 只在强真值上数：`A_human`、`B_vision`；`C_weak`（证人一致，对 match_ref 是循环的）不数；两档分开报；
- 按册报、不合并；`split`（dev／val／pool／extra）可筛；默认只取 `core` 格；
- 强真值格多是机器拿不准才送人看的难例，**不是随机样本**，错率偏高——这里的数只能和同一份集子里的别的臂比，不能外推全书；
- 真值不在组内的格（`gold` 不是本组成员）不进准确率分母，单独计数。

本模块只读 dataset、只写 stdout／`--json`，不碰工作区、产物、事件、字形库。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..groups import GROUPS, GroupSpec, GroupVerdict, JudgeInput, PatchUnavailable, window_from_text

STRONG_TIERS = ("A_human", "B_vision")


# ------------------------------------------------------------------ 载入
def load_items(path: str | Path, *, core_only: bool = True, splits: set[str] | None = None) -> list[dict]:
    """读 `items.jsonl`（传目录则读目录下的 items.jsonl）。"""
    p = Path(path)
    if p.is_dir():
        p = p / "items.jsonl"
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        it = json.loads(line)
        if core_only and not it.get("core", True):
            continue
        if splits and it.get("split") not in splits:
            continue
        out.append(it)
    return out


def _crop_path(item: dict, group_dir: Path | None) -> Path | None:
    c = item.get("crop")
    if not c or group_dir is None:
        return None
    for cand in (group_dir / c, group_dir / "crops" / Path(c).name):
        if cand.exists():
            return cand
    return None


def item_to_cell(item: dict, group_dir: Path | None = None) -> JudgeInput:
    """一行 `items.jsonl` → 判别输入。窗口用数据集里现成的 `left`/`right`（与生产 `_clf_ctx` 同口径：
    邻格已放行字，否则整理本字，否则 □，各 30 字）；字块惰性读，缺图抛 `PatchUnavailable`。"""
    cp = _crop_path(item, group_dir)

    def patch():
        if cp is None:
            raise PatchUnavailable(item.get("id", "?"))
        import cv2
        import numpy as np
        g = cv2.imdecode(np.fromfile(str(cp), np.uint8), cv2.IMREAD_GRAYSCALE)
        if g is None:
            raise PatchUnavailable(str(cp))
        return g

    return JudgeInput(id=item["id"], ref=item.get("ref"),
                      window=window_from_text(item.get("left") or "", item.get("right") or ""), patch=patch)


# ------------------------------------------------------------------ 评测
@dataclass
class Result:
    id: str
    book: str
    split: str | None
    tier: str
    gold: str
    pick: str | None          # None＝弃权
    why: str = ""
    conf: float | None = None


def eligible(items: list[dict], spec: GroupSpec, tiers=STRONG_TIERS) -> tuple[list[dict], dict]:
    """筛出能数准确率的格，并计数被筛掉的：弱真值／无真值／真值不在组内。"""
    keep, skipped = [], {"weak_or_no_tier": 0, "no_gold": 0, "gold_outside_group": 0}
    for it in items:
        if it.get("gold_tier") not in tiers:
            skipped["weak_or_no_tier"] += 1
        elif not it.get("gold"):
            skipped["no_gold"] += 1
        elif it["gold"] not in spec.members:
            skipped["gold_outside_group"] += 1
        else:
            keep.append(it)
    return keep, skipped


def _result(it: dict, pick, why="", conf=None) -> Result:
    return Result(id=it["id"], book=it.get("book", "?"), split=it.get("split"), tier=it["gold_tier"],
                  gold=it["gold"], pick=pick, why=why, conf=conf)


def run_backend(items: list[dict], spec: GroupSpec, backend, group_dir: Path | None = None) -> list[Result]:
    out = []
    for it in items:
        try:
            v: GroupVerdict = backend.judge(spec, item_to_cell(it, group_dir))
            out.append(_result(it, v.char, v.why, v.conf))
        except PatchUnavailable:                       # 缺图不静默弃权：单列原因，汇总里能看到
            out.append(_result(it, None, "patch_missing"))
    return out


def arm_ref(items: list[dict], spec: GroupSpec) -> list[Result]:
    """对照臂：整理本对位字（在组内才算给字）。"""
    return [_result(it, it["ref"] if it.get("ref") in spec.members else None, "ref") for it in items]


def arm_admit(items: list[dict], spec: GroupSpec) -> list[Result]:
    """对照臂：现行管线的放行字（已放行且在组内才算给字）。"""
    return [_result(it, it["char"] if it.get("admit") and it.get("char") in spec.members else None, "admit") for it in items]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 区间；n=0 → (0,1)。"""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


@dataclass
class Row:
    key: tuple
    n: int = 0
    gave: int = 0
    correct: int = 0
    abstain: int = 0
    patch_missing: int = 0
    wrong_ids: list = field(default_factory=list)

    @property
    def wrong(self) -> int:
        return self.gave - self.correct

    def to_dict(self) -> dict:
        lo, hi = wilson(self.correct, self.gave)
        return {**{"key": list(self.key)}, "n": self.n, "gave": self.gave, "correct": self.correct, "wrong": self.wrong,
                "abstain": self.abstain, "patch_missing": self.patch_missing,
                "give_rate": self.gave / self.n if self.n else None,
                "accuracy": self.correct / self.gave if self.gave else None,
                "accuracy_ci95": [lo, hi], "wrong_ids": self.wrong_ids}


def summarize(results: list[Result], by=("book", "tier")) -> list[Row]:
    rows: dict[tuple, Row] = {}
    for r in results:
        for key in (tuple(getattr(r, b) for b in by), ("全部",) * len(by)):
            row = rows.setdefault(key, Row(key))
            row.n += 1
            if r.pick is None:
                row.abstain += 1
                row.patch_missing += r.why == "patch_missing"
                continue
            row.gave += 1
            if r.pick == r.gold:
                row.correct += 1
            else:
                row.wrong_ids.append(r.id)
    return sorted(rows.values(), key=lambda x: (x.key == ("全部",) * len(by), x.key))


# ------------------------------------------------------------------ 报告
def render_markdown(group: str, arms: dict[str, list[Row]], skipped: dict, n_items: int, by=("book", "tier")) -> str:
    L = [f"## 字组 `{group}` 分类器层评测（强真值；{'／'.join(by)}）", "",
         f"取格 {n_items}；筛掉：弱真值或无档 {skipped['weak_or_no_tier']}，无真值 {skipped['no_gold']}，真值不在组内 {skipped['gold_outside_group']}。",
         "强真值多是难例、不是随机样本，数只能与同一份集子里的别的臂比，不能外推全书。", ""]
    for name, rows in arms.items():
        L += [f"### 臂 `{name}`", "", f"| {' | '.join(by)} | 格数 | 给字 | 给字率 | 对 | 错 | 给字准确率（Wilson 95%） | 弃权 |",
              "|" + "---|" * (len(by) + 7)]
        for r in rows:
            d = r.to_dict()
            acc = "—" if d["accuracy"] is None else f"{r.correct}/{r.gave} = {d['accuracy']:.1%}（{d['accuracy_ci95'][0]:.1%}–{d['accuracy_ci95'][1]:.1%}）"
            rate = "—" if d["give_rate"] is None else f"{d['give_rate']:.1%}"
            ab = f"{r.abstain}" + (f"（缺图 {r.patch_missing}）" if r.patch_missing else "")
            L.append(f"| {' | '.join(map(str, r.key))} | {r.n} | {r.gave} | {rate} | {r.correct} | {r.wrong} | {acc} | {ab} |")
        L.append("")
    return "\n".join(L)


# ------------------------------------------------------------------ 命令行
def make_backend(spec_text: str, group: str):
    """`rule` | `ctx_table[:路径]` | `table:<路径>`（group_clf/1） | `image[:<模型>]`。"""
    from ..groups.backends import CtxTableBackend, GroupClfTableBackend, JysRuleBackend, RrImageBackend
    kind, _, arg = spec_text.partition(":")
    if kind == "rule":
        return JysRuleBackend()
    if kind == "ctx_table":
        return CtxTableBackend(path=arg or None)
    if kind == "image":
        return RrImageBackend(model_path=arg or None)
    if kind == "table":
        return GroupClfTableBackend(arg)
    raise SystemExit(f"未知后端 {spec_text!r}；可用：rule | ctx_table[:路径] | table:路径 | image[:模型]")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m open_guji_cv.eval.groups", description="字组统一评测（分类器层）")
    ap.add_argument("group", choices=sorted(GROUPS))
    ap.add_argument("--dataset", required=True, help="dataset 的 char-groups 目录")
    ap.add_argument("--backend", action="append", default=[], help="可重复；见模块头")
    ap.add_argument("--splits", default="", help="逗号分隔：dev,val,pool,extra；缺省全部")
    ap.add_argument("--tiers", default=",".join(STRONG_TIERS), help="真值档；缺省强真值 A_human,B_vision")
    ap.add_argument("--all-cells", action="store_true", help="含外围格（core=false）；缺省只取 core")
    ap.add_argument("--no-baseline", action="store_true", help="不跑 ref／admit 两个对照臂")
    ap.add_argument("--by", default="book,tier", help="分组键，逗号分隔，可选 book,tier,split")
    ap.add_argument("--json", default="", help="把机器可读的结果写到这个文件")
    a = ap.parse_args(argv)

    spec = GROUPS[a.group]
    gdir = Path(a.dataset) / a.group
    items = load_items(gdir, core_only=not a.all_cells, splits=set(filter(None, a.splits.split(","))) or None)
    keep, skipped = eligible(items, spec, tuple(a.tiers.split(",")))
    by = tuple(a.by.split(","))
    arms: dict[str, list[Row]] = {}
    if not a.no_baseline:
        arms["ref（整理本对位字）"] = summarize(arm_ref(keep, spec), by)
        arms["admit（现行放行字）"] = summarize(arm_admit(keep, spec), by)
    for b in a.backend:
        arms[b] = summarize(run_backend(keep, spec, make_backend(b, a.group), gdir), by)
    print(render_markdown(a.group, arms, skipped, len(keep), by))
    if a.json:
        Path(a.json).write_text(json.dumps({"group": a.group, "by": list(by), "skipped": skipped, "n": len(keep),
                                            "arms": {k: [r.to_dict() for r in v] for k, v in arms.items()}},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
