# -*- coding: utf-8 -*-
"""把钉在 502fa04d0c 的冻结集迁到当前管线的键空间。

    PYTHONPATH=. python scripts/migrate_frozen_to_current.py \
        --map config/rekey_502fa04d0c_to_current.json [--apply]

## 为什么迁

`glyph-match/*` 与 `char-clustering/*` 钉死在 `pipeline_version=502fa04d0c`，
上游后来一直在重切并重键（`confusable-context`、`char-segmentation/*`、
`truncation` 都用当前键）。**同一个 id 在两边指着不同的格位**，跨集按 id
联接会安静地给出错答案——已经踩过一次（照 instances 的人裁标补了 148 条排除
名单，后来撤回）。迁完之后两边同一个键空间，上游的校对数据才用得上。

## 迁什么、不迁什么

迁的是**键与图**：instance_id 换成新键，crop/patch 从当前管线重新生成。
**人裁下的判断一个字不改**（金标字、改标历史、难例对、排除名单），它们跟着
键走。这不是重新标注，是换坐标系。

配不上的（`unmatched`，408/6085 = 6.7%）**不硬迁**：从集里剔除并落进回执，
牵涉到它们的对/三元组一并剔除。硬迁一条配不上的金标，等于凭空造一条错标。

## 不在本次范围

当前管线比冻结版多切出来的**新格位**不会自动进集——那要重跑 align 才有金标，
是另一件事。所以迁完实例数只减不增，集的覆盖面没变，只是键对上了。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402

NEW_REV = "1158da9093"
OLD_REV = "502fa04d0c"
ROUND = "rekey_to_current_r1"


def patch_path(root: Path, iid: str) -> Path:
    b, p, c, i = iid.split(":")
    return root / b / "phase4_chars" / "patches" / p / f"{c}_{i}.png"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="config/rekey_502fa04d0c_to_current.json")
    ap.add_argument("--new-root", default="output")
    ap.add_argument("--dataset", default="../open-guji-dataset")
    ap.add_argument("--receipt", default="output/rekey_receipt.jsonl")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    M = json.loads(Path(a.map).read_text(encoding="utf-8"))["map"]
    new_of = {k: v["new_id"] for k, v in M.items() if v.get("new_id")}
    root, ds = Path(a.new_root), Path(a.dataset)
    log: list[str] = []
    receipt: list[dict] = []

    def prov(extra: dict | None = None) -> dict:
        return {"round": ROUND, "date": str(date.today()), "from": OLD_REV,
                "to": NEW_REV, "map": a.map, "method": "同页内归一化图块 IoU + 匈牙利指派",
                **(extra or {})}

    # ---- 1. char-clustering 两个分片 ----
    for shard in ("001-vol01-body", "002-vol02-body"):
        p = ds / f"char-clustering/samples/{shard}/expected.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        crops = p.parent / "crops"
        keep, dropped = [], 0
        for r in d["instances"]:
            n = new_of.get(r["instance_id"])
            if not n:
                dropped += 1
                receipt.append({"set": shard, "instance_id": r["instance_id"],
                                "action": "dropped", "why": "unmatched"})
                continue
            old_id = r["instance_id"]
            r["instance_id"] = n
            r["crop"] = f"crops/{n.replace(':', '_')}.png"
            r["page"] = n.split(":")[1]
            r.setdefault("rekey_history", []).append({"from": old_id, **prov()})
            keep.append(r)
        hp, hp_drop = [], 0
        for h in (d.get("hard_pairs") or []):
            if h.get("a") in new_of and h.get("b") in new_of:
                h["a"], h["b"] = new_of[h["a"]], new_of[h["b"]]
                hp.append(h)
            else:
                hp_drop += 1
        d["instances"], d["pipeline_version"] = keep, NEW_REV
        if "hard_pairs" in d:
            d["hard_pairs"] = hp
        d["rekey"] = prov({"dropped_unmatched": dropped, "dropped_hard_pairs": hp_drop})
        log.append(f"{shard}: 实例 {len(keep)}（剔 {dropped}）　难例对 {len(hp)}（剔 {hp_drop}）")
        if a.apply:
            shutil.rmtree(crops, ignore_errors=True)
            crops.mkdir(parents=True, exist_ok=True)
            for r in keep:
                g = cv2.imread(str(patch_path(root, r["instance_id"])), cv2.IMREAD_GRAYSCALE)
                cv2.imwrite(str(p.parent / r["crop"]), normalize_patch(g) * 255)
            p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- 2. glyph-match/pairs ----
    p = ds / "glyph-match/pairs/expected.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    keep, dropped = [], 0
    for r in d["instances"]:
        n = new_of.get(r["instance_id"])
        if not n:
            dropped += 1
            receipt.append({"set": "pairs", "instance_id": r["instance_id"],
                            "action": "dropped", "why": "unmatched"})
            continue
        old_id = r["instance_id"]
        r["instance_id"], r["crop"] = n, f"crops/{n.replace(':', '_')}.png"
        r.setdefault("rekey_history", []).append({"from": old_id, **prov()})
        keep.append(r)
    d["instances"], d["pipeline_version"] = keep, NEW_REV
    d["rekey"] = prov({"dropped_unmatched": dropped})
    live = {r["instance_id"] for r in keep}
    pj = ds / "glyph-match/pairs/pairs.jsonl"
    rows = [json.loads(l) for l in pj.read_text(encoding="utf-8").splitlines() if l.strip()]
    prs, pdrop = [], 0
    for r in rows:
        if r["a"] in new_of and r["b"] in new_of:
            r["a"], r["b"] = new_of[r["a"]], new_of[r["b"]]
            prs.append(r)
        else:
            pdrop += 1
    d["n_pairs"] = len(prs)
    log.append(f"pairs: 实例 {len(keep)}（剔 {dropped}）　对 {len(prs)}（剔 {pdrop}）")
    if a.apply:
        crops = p.parent / "crops"
        shutil.rmtree(crops, ignore_errors=True)
        crops.mkdir(parents=True, exist_ok=True)
        for r in keep:
            g = cv2.imread(str(patch_path(root, r["instance_id"])), cv2.IMREAD_GRAYSCALE)
            cv2.imwrite(str(p.parent / r["crop"]), normalize_patch(g) * 255)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        pj.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in prs) + "\n",
                      encoding="utf-8")

    # ---- 3. glyph-match/triplets（图块是**原始灰度**，归一化属于被测算法）----
    p = ds / "glyph-match/triplets/expected.json"
    tri = json.loads(p.read_text(encoding="utf-8"))
    kept_t, tdrop = [], 0
    for t in tri:
        ids = (t["anchor"], t["same"], t["other"])
        if all(i in new_of for i in ids):
            t["anchor"], t["same"], t["other"] = (new_of[i] for i in ids)
            kept_t.append(t)
        else:
            tdrop += 1
    log.append(f"triplets: {len(kept_t)}（剔 {tdrop}）　子集 "
               + str(dict(Counter(t["subset"] for t in kept_t))))
    if a.apply:
        pat = p.parent / "patches"
        shutil.rmtree(pat, ignore_errors=True)
        pat.mkdir(parents=True, exist_ok=True)
        for t in kept_t:
            for iid in (t["anchor"], t["same"], t["other"]):
                dst = pat / f"{iid.replace(':', '_')}.png"
                if not dst.exists():
                    shutil.copy(patch_path(root, iid), dst)
        p.write_text(json.dumps(kept_t, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        m = json.loads((p.parent / "metadata.json").read_text(encoding="utf-8"))
        m["total_samples"] = len(kept_t)
        m["subset_distribution"] = dict(Counter(t["subset"] for t in kept_t))
        m["rekey"] = prov({"dropped_unmatched": tdrop})
        (p.parent / "metadata.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- 4. 排除名单两份 ----
    for name in ("config/crop_exclusions.jsonl", "config/crop_exclusions_released.jsonl"):
        f = REPO / name
        if not f.exists():
            continue
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        out, drop = [], 0
        for r in rows:
            n = new_of.get(r["instance_id"])
            if not n:
                drop += 1
                receipt.append({"set": name, "instance_id": r["instance_id"],
                                "action": "dropped", "why": "unmatched"})
                continue
            r["rekey_from"], r["instance_id"] = r["instance_id"], n
            out.append(r)
        log.append(f"{name}: {len(out)}（剔 {drop}）")
        if a.apply:
            f.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True)
                                   for r in out) + "\n", encoding="utf-8")

    print(("【已写】" if a.apply else "【试跑】") + "\n" + "\n".join("  " + s for s in log))
    if a.apply:
        Path(a.receipt).parent.mkdir(parents=True, exist_ok=True)
        Path(a.receipt).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in receipt) + "\n",
            encoding="utf-8")
        print(f"  回执 {a.receipt}（{len(receipt)} 条）")
    else:
        print("  试跑，没写。加 --apply 落盘。")


if __name__ == "__main__":
    main()
