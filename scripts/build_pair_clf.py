# -*- coding: utf-8 -*-
"""建一本书的形近字对分类器（5a.3，`groups.pair_clf`）。每跑完一批册重建一次，训练只要几秒。

    python scripts/build_pair_clf.py --labels 刻例.json --emb 嵌入.npz --out <数据目录>/config/groups/pair_clf.json \\
        [--context 己已 已巳 己巳] [--prev 旧版.json] [--snapshot <刻例快照号>] [--sim-model <嵌入模型 sha>]

- `刻例.json`：{"甲乙": {"<格 id>": "<这格刻的字>", …}, …}。只收独立证据定下的格（人裁、文意与整理本两路一致、
  聚类后人定名的类）；由本分类器定字的格不要收（见 `pair_clf` 模块头「不自我复制」）。
- `嵌入.npz`：`ids`（格 id）、`E`（相似度 CNN 嵌入，与书配置 `sim_model` 同一个模型、L2 归一）。
- 折按册分：格 id 第一段是册号，`--folds`（缺省 3）取册号的序号对折数取余。
- `--prev`：给了就比新旧两版的档位，退档的对列出来；`--keep-prev-on-regress` 时退步的对沿用旧版。

打印各档对数、归文意的对、档位变化。验收标准与量法见 doc/design/形近字组-按对分类器.md。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_guji_cv.groups import pair_clf  # noqa: E402

_ORDER = {"context": -1, 0: 0, 1: 1, 2: 2, 3: 3}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", required=True)
    ap.add_argument("--emb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--context", nargs="*", default=[])
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--prev")
    ap.add_argument("--keep-prev-on-regress", action="store_true")
    ap.add_argument("--snapshot", default="")
    ap.add_argument("--sim-model", default="")
    a = ap.parse_args(argv)

    labels = json.loads(Path(a.labels).read_text(encoding="utf-8"))
    z = np.load(a.emb, allow_pickle=True)
    emb = dict(zip([str(i) for i in z["ids"]], np.asarray(z["E"], dtype=np.float32)))
    vols = sorted({i.split(":", 1)[0] for cells in labels.values() for i in cells})
    vol_fold = {v: k % a.folds for k, v in enumerate(vols)}
    prev = json.loads(Path(a.prev).read_text(encoding="utf-8")) if a.prev else None
    out = pair_clf.build(labels, emb, lambda i: vol_fold[i.split(":", 1)[0]], context=a.context,
                         version=(prev or {}).get("version", 0) + 1, snapshot=a.snapshot, sim_model=a.sim_model)
    if prev:
        for k, p in sorted(out["pairs"].items()):
            q = prev.get("pairs", {}).get(k)
            if q is None:
                continue
            if _ORDER[p["tier"]] != _ORDER[q["tier"]]:
                print(f"档位变化 {k}: {q['tier']} → {p['tier']}  刻例 {q.get('n')} → {p.get('n')}  留出 {p.get('held')}")
            if a.keep_prev_on_regress and _ORDER[p["tier"]] < _ORDER[q["tier"]] and p["tier"] != "context":
                out["pairs"][k] = q
                print(f"  退步，沿用旧版：{k}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("版本", out["version"], "各档对数", pair_clf.tier_counts(out), "人定归文意", out["context"])
    print("机器定归文意（刻例够了仍分不开）:", [k for k, p in out["pairs"].items() if p["tier"] == "context"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
