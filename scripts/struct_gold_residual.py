# -*- coding: utf-8 -*-
"""结构金标：把 300 张卡按「模型预测 vs IDS 表全部拆法」分三类，只把真有分歧的留给人裁。

    PYTHONIOENCODING=utf-8 python scripts/struct_gold_residual.py \
        [--emb cache/struct_probe/emb_<sha>.npz] [--probe cache/struct_probe/probe_mlp.pt] \
        [--verdicts artifacts/struct_gold_verdicts.jsonl] [--out artifacts/struct_gold_residual.json]

## 为什么有这一步（2026-09-22，用户裁了 46 张后的反馈）

头一版 T3 让人把 300 张卡一张张裁「表里的 IDS 拆法对不对」——出题出歪了：这些字的 IDS
表里本来就有，**只有模型和表说法不一致的那些卡，人裁的结果才会改变任何结论**。
其余的（模型 = 表主拆法，或 = 表的某个备选拆法）人再看一遍只是在给表盖章。

三类：
- `同主拆法`：模型顶层算符 = 表主拆法。不用人看（人裁出的非 ok 都是口径分歧，见 §13 ⑦）。
- `同备选拆法`：模型 = 表列的另一种写法（座 ⿸/⿱、裹 ⿱/⿴、𠀉 ⿱/⿷）。口径分歧，不用人看。
- `与表全部拆法都不同`：这才是「标签错 vs 模型错」要人来分的——**按字种去重**（同一个字
  的几张图结构判断相同），任何一张裁过的字种也剔掉（歴 的两张裁了 slot，⿸ 就算定了）。

模型预测的口径和 `probe_struct_heads.py` / 设计稿 §13 ④ 的「合成」一致：MLP 探针 softmax
×0.7 + 字体模板类均值 top-10 检索投票 ×0.3（λ=0.3）。嵌入直接读探针脚本的缓存，不重跑主干。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.ids_struct import SINGLE, _is_atomic, load_table, parse_ids, structure_of  # noqa: E402

CARDS = REPO / "artifacts/struct_gold_cards.jsonl"
LAM = 0.3
CLS_PRIMARY, CLS_ALT, CLS_NONE = "同主拆法", "同备选拆法", "与表全部拆法都不同"


def all_tops(tab, ch: str) -> set[str]:
    e = tab.get(ch)
    if e is None:
        return {SINGLE}
    out: set[str] = set()
    for s in e.alts:
        if _is_atomic(s, ch):
            out.add(SINGLE); continue
        t = parse_ids(s)
        out.add(SINGLE if t is None or t.leaf else t.op)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", default=None, help="probe_struct_heads.py 的嵌入缓存；缺省取 cache/struct_probe/emb_*.npz 最新")
    ap.add_argument("--probe", default=str(REPO / "cache/struct_probe/probe_mlp.pt"))
    ap.add_argument("--verdicts", default=str(REPO / "artifacts/struct_gold_verdicts.jsonl"))
    ap.add_argument("--out", default=str(REPO / "artifacts/struct_gold_residual.json"))
    a = ap.parse_args()
    import torch
    import torch.nn as nn

    emb = Path(a.emb) if a.emb else max((REPO / "cache/struct_probe").glob("emb_*.npz"), key=lambda p: p.stat().st_mtime)
    z = dict(np.load(emb, allow_pickle=True))          # 一次读全，别在循环里按 key 取（NpzFile 每次都重新解压）
    d = torch.load(a.probe, map_location="cpu", weights_only=False)
    classes = list(d["struct_classes"]); hid = d["hidden"]; scale = d["scale"]
    n_slot = d["state"]["slot.weight"].shape[0]
    if d["arch"] == "mlp":
        head = nn.ModuleDict({"trunk": nn.Sequential(nn.Linear(256, hid), nn.ReLU(), nn.Dropout(0.2)),
                              "struct": nn.Linear(hid, len(classes)), "slot": nn.Linear(hid, n_slot)})
        def logits(x): return head["struct"](head["trunk"](x))
    else:
        head = nn.ModuleDict({"struct": nn.Linear(256, len(classes)), "slot": nn.Linear(256, n_slot)})
        def logits(x): return head["struct"](x)
    head.load_state_dict(d["state"]); head.eval()

    cards = [json.loads(l) for l in CARDS.read_text(encoding="utf-8").splitlines() if l.strip()]
    verd: dict[str, str] = {}
    if Path(a.verdicts).exists():
        for l in Path(a.verdicts).read_text(encoding="utf-8").splitlines():
            if l.strip():
                x = json.loads(l); verd[x["id"]] = x["verdict"]

    # 卡片 id → 嵌入（与 probe_struct_heads.py 的枚举顺序一致：items.jsonl 顺序）
    emb_by: dict[str, np.ndarray] = {}
    for i, it in enumerate(json.loads(l) for l in (REPO / "cache/oov_bench/items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()):
        emb_by["oov:" + it["id"]] = z["oov_emb"][i]
    idx = {sp: 0 for sp in ("unseen", "seen_test", "seen_train", "mid")}
    for it in (json.loads(l) for l in (REPO / "cache/glyph_bench/items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()):
        sp = it["split"]
        if sp in idx:
            emb_by["gb:" + it["id"]] = z[f"{sp}_emb"][idx[sp]]; idx[sp] += 1

    uniq, inv = np.unique(z["font_chars"], return_inverse=True)
    means = np.zeros((len(uniq), 256), np.float32); np.add.at(means, inv, z["font_emb"])
    means /= np.linalg.norm(means, axis=1, keepdims=True)
    tops = [structure_of(c).top for c in uniq]
    cidx = {c: i for i, c in enumerate(classes)}
    tab = load_table()

    rows = []
    for c in cards:
        x = emb_by.get(c["id"])
        if x is None:
            print("无嵌入，跳过", c["id"]); continue
        with torch.no_grad():
            p = torch.softmax(logits(torch.tensor(x * scale)[None]), 1).numpy()[0]
        sims = means @ x; top = np.argsort(-sims)[:10]; w = np.exp(sims[top] * 16); w /= w.sum()
        v = np.zeros(len(classes))
        for j, wt in zip(top, w):
            v[cidx[tops[j]]] += wt
        pe = (1 - LAM) * p + LAM * v
        pred = classes[int(pe.argmax())]
        alts = all_tops(tab, c["char"])
        cls = CLS_PRIMARY if pred == c["top"] else CLS_ALT if pred in alts else CLS_NONE
        rows.append({"id": c["id"], "char": c["char"], "stratum": c["stratum"], "table": c["top"],
                     "table_alts": sorted(alts), "pred": pred, "conf": round(float(pe.max()), 3),
                     "cls": cls, "verdict": verd.get(c["id"])})

    by_cls = Counter(r["cls"] for r in rows)
    print("三类：", dict(by_cls), " 按层：", dict(Counter((r["stratum"], r["cls"]) for r in rows)))
    print("已裁 × 类：", dict(Counter((r["cls"], r["verdict"]) for r in rows if r["verdict"])))
    # 残差：与表全部拆法都不同、字种没裁过、每字种留一张（其余记在 also）
    # 同一字种只要有任何一张裁过，结构问题就已经定了（ok/slot = 表的结构对；struct:X = 结构是 X）
    judged_chars = {r["char"] for r in rows if r["verdict"]}
    residual: dict[str, dict] = {}
    for r in rows:
        if r["cls"] != CLS_NONE or r["char"] in judged_chars:
            continue
        if r["char"] in residual:
            residual[r["char"]]["also"].append(r["id"])
        else:
            residual[r["char"]] = {**r, "also": []}
    print(f"残差 {len(residual)} 字种（{sum(1 + len(x['also']) for x in residual.values())} 张）→ 需要人看")
    for x in residual.values():
        print(f"  {x['char']}  表 {x['table']} {x['table_alts']}  模型 {x['pred']} {x['conf']}  {x['id']}  +{len(x['also'])}")
    out = {"lam": LAM, "probe": Path(a.probe).name, "emb": emb.name, "classes": dict(by_cls),
           "rows": rows, "residual_ids": [x["id"] for x in residual.values()],
           "residual_also": {x["id"]: x["also"] for x in residual.values()}}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
