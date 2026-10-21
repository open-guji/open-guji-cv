#!/usr/bin/env python3
"""粗校基准（M9 D6-5，GUJI-669）：在冻结的页与标签上量「人审率变化」和「错放数」。

    python scripts/eval_rough_bench.py <测试集仓>/rough-bench [--var B.yaml …] [--from seed_admit] \\
        [--snapshot <快照根>] [-w <工作区>] [--root <实验根>] [--jobs 2] [--out report.json]

- 不给 `--var`：只跑现行代码（基线），和基准目录里 `report.json` 记的建库时基线数比——
  送审率高出 0.2 个百分点以上、或有标签的错放格比记的多，算回归。
- 给 `--var`（`guji exp` 的变体 yaml：`params: {seed_admit: {…}}`）：基线与变体各跑一遍，报送审率差和
  **新增错放**（基线对、变体错），新增错放必须为 0；另出 `guji exp` 的完整报告（区间、翻转、按通道）。
- 快照缺哪册就按 `bench.yaml` 记的包标签从 R2 取（要读令牌），缺省放在 `<实验根>/_snapshot/`。

口径与标签怎么来的见 `open_guji_cv/exp/rough_bench.py` 模块头。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.exp import rough_bench as RB  # noqa: E402

REVIEW_TOL = 0.002          # 只跑基线时：送审率比记的基线高出这么多才算回归


def regressions(res: dict, baseline: dict | None) -> list[str]:
    """只跑基线时和建库基线比；有变体时看新增错放。"""
    out = []
    vs = res["variants"]
    names = list(vs)
    if len(names) > 1:
        for v in names[1:]:
            if vs[v]["new_wrong"]:
                out.append(f"{v} 新增错放 {len(vs[v]['new_wrong'])} 格：{', '.join(vs[v]['new_wrong'][:10])}")
        return out
    if not baseline:
        return out
    cur, ref = vs[names[0]], (baseline.get("variants") or {}).get("A") or {}
    if ref.get("review_rate_body") is not None and cur["review_rate_body"] is not None \
            and cur["review_rate_body"] > ref["review_rate_body"] + REVIEW_TOL:
        out.append(f"正文送审率 {ref['review_rate_body']:.4%} → {cur['review_rate_body']:.4%}")
    if cur["wrong_admits"] > ref.get("wrong_admits", cur["wrong_admits"]):
        new = sorted(set(cur["wrong_cells"]) - set(ref.get("wrong_cells") or []))
        out.append(f"有标签的错放 {ref['wrong_admits']} → {cur['wrong_admits']}（新的：{', '.join(new[:10])}）")
    return out


def main(argv=None) -> int:
    import yaml
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shard")
    ap.add_argument("--var", action="append", default=[], help="变体 yaml（params: {步: {开关: 值}}），可多次")
    ap.add_argument("--from", dest="from_step", default="seed_admit")
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("-w", "--workspace", default=os.environ.get("GUJI_WORKSPACE"))
    ap.add_argument("--root", default=None, help="实验根；缺省 <工作区>/experiments")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--name", default=None)
    ap.add_argument("--out", default=None, help="报告 json")
    a = ap.parse_args(argv)
    if a.workspace:
        os.environ["GUJI_WORKSPACE"] = a.workspace
    shard = Path(a.shard)
    root = Path(a.root) if a.root else (Path(a.workspace) / "experiments" if a.workspace else None)
    if root is None:
        raise SystemExit("要给 -w 工作区或 --root 实验根")
    snap = Path(a.snapshot) if a.snapshot else root / "_snapshot"
    variants = {}
    for f in a.var:
        d = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
        variants[Path(f).stem] = d
    res = RB.run(shard, snap, ws=a.workspace, variants=variants, from_step=a.from_step, root=root,
                 jobs=a.jobs, name=a.name)
    base_f = shard / "report.json"
    baseline = json.loads(base_f.read_text(encoding="utf-8")) if base_f.exists() else None
    bad = regressions(res, baseline)
    res["regressions"] = bad
    for v, r in res["variants"].items():
        line = f"{v}：正文 {r['cells_body']} 格，送审 {r['review_body']}（{r['review_rate_body']:.4%}）；" \
               f"有标签可判 {r['labelled_judged']} 格，错放 {r['wrong_admits']}"
        if "new_wrong" in r:
            line += f"；送审率差 {r['review_rate_diff']:+.4%}，新增错放 {len(r['new_wrong'])}，改对 {len(r['fixed_wrong'])}"
        print(line)
    print("回归门：" + ("通过" if not bad else "未过 —— " + "；".join(bad)))
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
