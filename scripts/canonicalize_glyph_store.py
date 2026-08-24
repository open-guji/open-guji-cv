"""把 glyph_store/patches/ 一次性迁移到 canonical 统一格式。

做三件事（幂等，可重跑）：
1. 被 instances/*.jsonl 引用的图块 → to_canonical()（200×200 灰度、
   等比缩放、质心居中），原地覆写；
2. 删孤儿 PNG（不被任何实例引用的遗留文件，含旧 GlyphLibrary 时代的
   g_*.png 64×64 二值遗留物）；
3. 迁移前后各算一遍派生归一图，用 pairs.jsonl 金标对比 verify 判定
   有没有翻转（same/unsure/diff），并报告逐实例自相似度——量化迁移
   对匹配层的扰动。加 --dry-run 只看报告不写文件。

用法：
    python scripts/canonicalize_glyph_store.py [--store glyph_store] [--dry-run]
迁移后需要 `python -m open_guji_cv glyph-db rebuild` 重建索引。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.clustering.canonical import is_canonical, to_canonical  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair, verify_pair_cov  # noqa: E402


def _safe(instance_id: str) -> str:
    return instance_id.replace(":", "_")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="glyph_store")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    store = Path(args.store)

    referenced: dict[str, str] = {}   # 文件名 → instance_id
    for f in sorted((store / "instances").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                iid = json.loads(line)["instance_id"]
                referenced[f"{_safe(iid)}.png"] = iid

    old_norm: dict[str, np.ndarray] = {}
    new_norm: dict[str, np.ndarray] = {}
    canon: dict[str, np.ndarray] = {}
    n_already = 0
    for name, iid in referenced.items():
        p = store / "patches" / name
        if not p.exists():
            print(f"[warn] 缺图块：{name}")
            continue
        gray = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8),
                            cv2.IMREAD_GRAYSCALE)
        if is_canonical(gray):
            n_already += 1
        c = to_canonical(gray)
        old_norm[iid] = normalize_patch(gray)
        new_norm[iid] = normalize_patch(c)
        canon[name] = c

    # ── 报告 1：逐实例自扰动（旧归一图 vs 新归一图应判 same）──
    worst: list[tuple[float, str, str]] = []
    for iid in old_norm:
        v = verify_pair(old_norm[iid], new_norm[iid])
        worst.append((v.f1, v.verdict, iid))
    worst.sort()
    n_self_bad = sum(1 for _, verdict, _ in worst if verdict != "same")
    print(f"实例 {len(old_norm)} 个（其中 {n_already} 个已是 canonical）")
    print(f"自相似（旧归一 vs 新归一）非 same：{n_self_bad}")
    for f1, verdict, iid in worst[:5]:
        print(f"  最差 f1={f1:.3f} {verdict}  {iid}")

    # ── 报告 2：pairs 金标判定翻转 ──
    flips = {"overlap": 0, "coverage": 0}
    n_pairs = 0
    pairs_file = store / "pairs.jsonl"
    if pairs_file.exists():
        for line in pairs_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            a, b = r["inst_a"], r["inst_b"]
            if a not in old_norm or b not in old_norm:
                continue
            n_pairs += 1
            for key, fn in (("overlap", verify_pair), ("coverage", verify_pair_cov)):
                vo = fn(old_norm[a], old_norm[b])
                vn = fn(new_norm[a], new_norm[b])
                if vo.verdict != vn.verdict:
                    flips[key] += 1
                    print(f"  [{key}翻转] {r['relation']}: {a} vs {b} "
                          f"{vo.verdict}({vo.f1:.3f}) → {vn.verdict}({vn.f1:.3f})")
    print(f"pairs 金标 {n_pairs} 对：overlap 翻转 {flips['overlap']}，"
          f"coverage 翻转 {flips['coverage']}")

    orphans = [f for f in (store / "patches").glob("*.png")
               if f.name not in referenced]
    print(f"孤儿 PNG：{len(orphans)} 个"
          + (f"（示例 {orphans[0].name}）" if orphans else ""))

    if args.dry_run:
        print("[dry-run] 未写任何文件")
        return 0

    for name, img in canon.items():
        ok, buf = cv2.imencode(".png", img)
        assert ok
        (store / "patches" / name).write_bytes(buf.tobytes())
    for f in orphans:
        f.unlink()
    print(f"已覆写 {len(canon)} 个图块，删除 {len(orphans)} 个孤儿。"
          f"请运行 python -m open_guji_cv glyph-db rebuild 重建索引。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
