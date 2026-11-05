# -*- coding: utf-8 -*-
"""从三本书的中心库人裁冻结 5a/5b 金标分片（2026-11-05，A23「修评测链」第二项）。

## 为什么要

11-04 修好评测链后量出来：5a、5b 的金标**全部出自殿本 vol01–02**，而且是 9 月的老库、
老图源。史記、全唐文的 L 类（字形库）待审率是殿本的 4 倍、17 倍，却一条金标都没有；
rare-char 只有 21 条，一两条就差 5 个点。所以从三本书现有的**人裁**各冻一份。

## 出什么

每本书一个 char-clustering 形状的分片 `char-clustering/samples/<NNN>-<书>-human/`：

- `crops/*.png`：64×64 归一图（与 001/002/003 同口径，`normalize_patch(gray)*255`），
  图块从当时库里的 `instances.patch_png` 解出、冻在数据集仓，**不再引用本机路径**；
- `expected.json`：`instances`（按整页抽，上限 `--max-instances`）+ `hard_pairs`
  （形近家族异字对 + 墨色两极同字对，都与判据无关），给 `eval_db_match --shards`、
  `build_match_pairs_dataset.py --shards` 用——这是 **5a**；
- `rare.jsonl`：5b 用的字位，两档（可同时属于两档）：
  - `unseen`：本书人裁里这个字 ≤2 例——新书开头所有字都是这个处境；
  - `oov`：字不在 CNN r5 的 4,654 类里——分类头恒 0，只能靠 embedding。
  行格式同 `cache/oov_bench/items.jsonl`（`{char, png, src, book, id, tier}`），
  `eval_oov.py --bench <分片目录> --items rare.jsonl` 直接读。

## 抽样纪律

1. **只收人裁**（`admissions.provenance='human'`），不收 align／match／context 自动入库的；
2. **只收本书自己的刻例**：借来的（`borrowed` 表）不收；殿本只收 `v2:` 新图源
   （旧号 v1/volNN 的人裁按 A31 规矩不采信）；
3. 5a 分片**按整页抽**到上限（按字抽会改字频分布，见 build_clustering_dataset.py 头）；
   5b 的 `rare.jsonl` 不抽样，全收——它本来就稀；
4. 难例对线索与判据无关：异字对取 `NEVER_MATCH_FAMILIES`（人裁来源的形近家族），
   同字对取墨色两极（`ink_ratio` 按图算），不拿 verify 分数挑。

## 已知局限（写进 info.json）

- 人裁本身有噪声：11-04 首次体检，史記人裁×人裁冲突 383/4,615、全唐文 99/28,077。
  有体检结果的书，`--selfcheck <findings.jsonl>` 把被标的字位打 `selfcheck_flag`，
  评测可以分层或剔除，**不在建集时悄悄删**；
- 人裁是被审查流程挑出来的字位（待审格），比全书随机字难——这正是要量的那批，
  但不能拿它的数当全书准确率。

用法：
    PYTHONPATH=. python scripts/build_book_human_shards.py \
        --book 004-siku-v2:<殿本 glyph.db>:96mid1ogzk \
        --book 005-shiji:<史記 glyph.db>:988g3f0wsu \
        --book 006-qtw:<全唐文 glyph.db>:995ejelvk0 \
        --dataset ../open-guji-dataset/char-clustering
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.clustering.crop_quality import assess_crop  # noqa: E402
from open_guji_cv.clustering.match import NEVER_MATCH_FAMILIES  # noqa: E402
from open_guji_cv.clustering.normalize import (MARGIN_RATIO, NOISE_AREA,  # noqa: E402
                                               NORM_SIZE, normalize_patch)

MAX_FAMILY_PAIRS = 3       # 每个形近家族最多几对
MAX_INK_PAIRS = 60         # 墨色两极同字对上限
UNSEEN_MAX = 2             # 本书人裁 ≤ 这么多例算 unseen


def crop_name(iid: str) -> str:
    return iid.replace(":", "_") + ".png"


def page_of(iid: str) -> str:
    """`v2:<册>:<页>:<列>:<格>` → `<册>:<页>`（抽样单位是整页）。"""
    p = iid.split(":")
    return ":".join(p[1:3]) if p[0] == "v2" else ":".join(p[:2])


def page_ord(iid: str) -> int:
    """整数页序（册×10000＋页）：eval_db_match 的册内增量协议按 `int(page)` 排序、逐页长库。"""
    import re
    vol, pg = page_of(iid).split(":")
    return int(re.sub(r"\D", "", vol) or 0) * 10000 + int(pg)


def cnn_classes() -> set[str]:
    import torch
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT
    return set(torch.load(DEFAULT_CKPT, map_location="cpu", weights_only=False)["classes"])


def load_human(db: Path, v2_only: bool) -> list[dict]:
    con = sqlite3.connect(str(db))
    has_b = con.execute("select 1 from sqlite_master where name='borrowed'").fetchone()
    q = ("select a.instance_id, a.char, i.patch_png from admissions a join instances i using(instance_id) "
         "where a.provenance='human' and i.patch_png is not null")
    if has_b:
        q += " and a.instance_id not in (select instance_id from borrowed)"
    rows = []
    for iid, ch, blob in con.execute(q):
        if v2_only and not iid.startswith("v2:"):
            continue
        if not ch or len(ch) != 1:
            continue
        gray = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None or gray.size == 0:
            continue
        rows.append({"instance_id": iid, "char": ch, "gray": gray})
    con.close()
    rows.sort(key=lambda r: r["instance_id"])
    return rows


def selfcheck_flags(path: Path | None) -> dict[str, str]:
    """体检 findings.jsonl → {instance_id: 标记}。只认实例级标记，读不懂的行跳过。"""
    if not path or not path.exists():
        return {}
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        iid = d.get("instance_id")
        flags = list(d.get("flags") or []) + (["human_conflict"] if d.get("human_conflict") else [])
        if iid and flags:
            out[iid] = ",".join(sorted(set(out.get(iid, "").split(",") + flags) - {""}))
    return out


def pick_pages(rows: list[dict], max_instances: int, seed: int) -> set[str]:
    per_page: Counter = Counter(page_of(r["instance_id"]) for r in rows)
    pages = sorted(per_page)
    random.Random(seed).shuffle(pages)
    chosen, total = set(), 0
    for p in pages:
        if total >= max_instances:
            break
        chosen.add(p)
        total += per_page[p]
    return chosen


def build_one(shard: str, db: Path, book_id: str, out_root: Path, classes: set[str],
              max_instances: int, seed: int, sc: dict[str, str]) -> dict:
    v2_only = book_id == "96mid1ogzk"
    rows = load_human(db, v2_only)
    out = out_root / "samples" / shard
    crops = out / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    for old in crops.glob("*.png"):
        old.unlink()

    n_of = Counter(r["char"] for r in rows)
    chosen = pick_pages(rows, max_instances, seed)

    written: dict[str, dict] = {}

    def freeze(r: dict) -> dict:
        iid = r["instance_id"]
        if iid in written:
            return written[iid]
        norm = normalize_patch(r["gray"])
        name = crop_name(iid)
        cv2.imwrite(str(crops / name), (norm * 255).astype(np.uint8))
        q = assess_crop(r["gray"])          # 库里 v2 刻例没存 bbox，边距按缺省估
        rec = {"instance_id": iid, "crop": f"crops/{name}", "char": r["char"],
               "label_origin": "human", "label_status": "admitted",
               "page": str(page_ord(iid)), "page_key": page_of(iid), "ink_ratio": round(float(norm.mean()), 4),
               "hw_ratio": round(r["gray"].shape[0] / max(r["gray"].shape[1], 1), 4),
               "tier": q.tier, "tier_detail": q.to_dict(),
               "book_count": n_of[r["char"]], "in_cnn_classes": r["char"] in classes}
        if iid in sc:
            rec["selfcheck_flag"] = sc[iid]
        written[iid] = rec
        return rec

    instances = [freeze(r) for r in rows if page_of(r["instance_id"]) in chosen]

    # 难例对：形近家族异字对 + 墨色两极同字对（都不用 verify 分数挑）
    by_char: dict[str, list[dict]] = defaultdict(list)
    for i in instances:
        by_char[i["char"]].append(i)
    pairs, seen = [], set()
    for c1, c2 in NEVER_MATCH_FAMILIES:
        a, b = by_char.get(c1, []), by_char.get(c2, [])
        for k in range(min(MAX_FAMILY_PAIRS, len(a), len(b))):
            key = frozenset((a[k]["instance_id"], b[k]["instance_id"]))
            if key not in seen:
                seen.add(key)
                pairs.append({"a": a[k]["instance_id"], "b": b[k]["instance_id"],
                              "relation": "diff", "origin": "near_form",
                              "note": f"NEVER_MATCH_FAMILIES {c1}/{c2}"})
    ink_cands = sorted(((max(v, key=lambda x: x["ink_ratio"]), min(v, key=lambda x: x["ink_ratio"]))
                        for v in by_char.values() if len(v) >= 2),
                       key=lambda ab: -(ab[0]["ink_ratio"] - ab[1]["ink_ratio"]))
    for hi, lo in ink_cands[:MAX_INK_PAIRS]:
        pairs.append({"a": hi["instance_id"], "b": lo["instance_id"], "relation": "same",
                      "origin": "ink_extreme",
                      "note": f"墨色 {hi['ink_ratio']:.3f} vs {lo['ink_ratio']:.3f}"})

    # 5b：不抽样，全收
    rare = []
    for r in rows:
        strata = [s for s, hit in (("unseen", n_of[r["char"]] <= UNSEEN_MAX),
                                   ("oov", r["char"] not in classes)) if hit]
        if not strata:
            continue
        rec = freeze(r)
        rare.append({"char": r["char"], "png": rec["crop"], "src": "human", "book": book_id,
                     "id": r["instance_id"], "strata": strata, "tier": rec["tier"],
                     "book_count": n_of[r["char"]],
                     **({"selfcheck_flag": rec["selfcheck_flag"]} if "selfcheck_flag" in rec else {})})

    db_sha = hashlib.sha256(db.read_bytes()).hexdigest()
    expected = {
        "source_item": book_id, "book": book_id, "label_origin": "human",
        "shard_id": f"{book_id}/human", "schema_version": 1,
        "pipeline_version": f"glyph.db sha256 {db_sha[:16]}",
        "feature_backend": "hog",
        "norm_params": {"size": NORM_SIZE, "margin_ratio": MARGIN_RATIO,
                        "noise_area": NOISE_AREA, "stroke_width": None},
        "instances": instances, "hard_pairs": pairs,
    }
    (out / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")
    (out / "rare.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rare),
                                    encoding="utf-8")
    n_sc = sum(1 for i in instances if "selfcheck_flag" in i)
    info = {
        "id": shard, "source": book_id, "source_item": book_id, "book": book_id,
        "created": _dt.date.today().isoformat(),
        "description": f"{book_id} 中心库人裁冻结：5a 分片 {len(instances)} 实例 / "
                       f"{len({i['char'] for i in instances})} 字；5b rare.jsonl {len(rare)} 条",
        "tags": ["human", "central-db", book_id],
        "sampling": f"admissions.provenance='human'，本书自有刻例"
                    f"{'（只收 v2: 新图源）' if v2_only else ''}；5a 按整页抽到 {max_instances}（seed {seed}），"
                    f"5b 全收（unseen=本书人裁 ≤{UNSEEN_MAX} 例；oov=不在 CNN r5 类表）",
        "bias": "人裁字位是审查流程挑出来的待审格，比全书随机字难；数不能当全书准确率读",
        "known_limitation": (f"人裁有噪声，体检标出的 {n_sc} 个实例带 selfcheck_flag，评测时分层或剔除"
                             if sc else "这本书建集时没有体检结果，人裁噪声未标"),
        "glyph_db_sha256": db_sha,
        "build_command": "python scripts/build_book_human_shards.py",
        "stats": {
            "n_human_total": len(rows), "n_instances": len(instances),
            "n_chars": len({i["char"] for i in instances}), "n_pages": len(chosen),
            "n_hard_pairs": len(pairs),
            "hard_pairs_by_origin": dict(Counter(p["origin"] for p in pairs)),
            "tiers": dict(Counter(i["tier"] for i in instances)),
            "rare": {"n": len(rare), "n_chars": len({x["char"] for x in rare}),
                     "unseen": sum("unseen" in x["strata"] for x in rare),
                     "oov": sum("oov" in x["strata"] for x in rare)},
            "n_selfcheck_flagged": n_sc,
        },
    }
    (out / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", action="append", required=True,
                    help="<分片名>:<glyph.db 路径>:<书 ID>[:<体检 findings.jsonl>]，可重复")
    ap.add_argument("--dataset", default="../open-guji-dataset/char-clustering")
    ap.add_argument("--max-instances", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    classes = cnn_classes()
    for spec in a.book:
        parts = spec.split(":")
        shard, db, book_id = parts[0], Path(parts[1]), parts[2]
        sc = selfcheck_flags(Path(parts[3])) if len(parts) > 3 else {}
        info = build_one(shard, db, book_id, Path(a.dataset), classes, a.max_instances, a.seed, sc)
        print(shard, json.dumps(info["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
