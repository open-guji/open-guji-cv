# -*- coding: utf-8 -*-
"""5b 升级档字表与异体族展开的评测（产线路径 `rare_panel.rare_for_batch`，2026-11-16）。

量两件事，都在三书人裁 5b 冻结集（`char-clustering/samples/00{4,5,6}-*-human/rare.jsonl`）上：

1. **升级档取哪一档**：`font.charset.escalate` 取 `unicode-ext-b`（缺省）还是 `unicode-all`
   （基集之外的全部已编码汉字，扩 B 到扩 F、扩 I）。不改册配置，评测里临时换规格。
2. **候选按异体族展开**（`clustering/rare_family.expand_family`）：前 k 名并上首位的族之后的召回与候选个数。

报：首位、族首位（首位是金标或金标的同族）、前 k、前 k＋族、平均候选个数、可达率（金标在基集∪升级档里）、
升级率（首位分低于阈值而并入升级档的格的比例）。己已巳、日曰折叠（`eval_fold`）。按 `strata` 分层。

口径：`book=None`、缺省语料，基集＝`unicode-cjk-a`＋缺省语料用字＋异体展开；三路融合照产线（库字体域没有，
分类头门控＋emb）。人裁格是送审难格，数不能当全书准确率读。

注意：`charset_spec._cjk` 只认到 U+2FFFF，扩 G 以后（U+30000 起，1.3 万字）进不了任何字表；
三书金标里只有殿本 9 格（𰜹 𱁪 𲄳）落在那里。

只读评测脚本，不进包、不改任何 Step 指纹。

    python scripts/eval_rare_escalate.py --shard 004-siku-v2-human --shard 005-shiji-human \
        --shard 006-qtw-human --dataset ../open-guji-dataset/char-clustering --out rare_escalate.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_fold import same  # noqa: E402


_PACK = None


def _prime(cnn, *charsets):
    """字表的 emb 索引从向量包（`config/hanzi/emb`，10.2 万字）直接取，放进进程内缓存，
    免得现渲染现建（7 万字要几十分钟）。包里没有的字现算。产线是 `guji cache pull-rare-index` 落盘，同一份向量。"""
    global _PACK
    from open_guji_cv.clustering import emb_pack
    cnn._ensure()
    if _PACK is None:
        _PACK = emb_pack.load_current(precision="fp32")
    for cs in charsets:
        if not cs or any(c is cs for c, _, _ in cnn._emb_cache):
            continue
        mat, names = _PACK.materialize(cs)
        cnn._emb_cache_put(cs, mat.astype("float32"), list(names))


def run_config(imgs, escalate, threshold, k):
    """临时换升级档规格跑一遍 `rare_for_batch`，返回（每格候选字表, 基集∪升级档字集, 升级率）。"""
    from open_guji_cv.clustering import charset_spec as CS
    from open_guji_cv.clustering import rare_panel as RP
    from open_guji_cv.clustering.cnn_candidates import shared

    orig = CS.spec_for_book

    def patched(book, edition="keben"):
        s = orig(book, edition)
        s["escalate"], s["escalate_threshold"] = escalate, threshold
        return s

    # 冻结集的裁图已经是归一化好的 64² 图（白＝墨），不能再过一遍 normalize_patch（与 eval_ref_verify 同口径）
    orig_norm = RP.normalize_patch
    RP.normalize_patch = lambda im: (im > 127).astype("uint8")
    CS.spec_for_book = patched
    RP.book_charsets.cache_clear()
    try:
        base, esc, _ = RP.book_charsets(None, None)
        _prime(shared(), base, esc)
        out, n_esc = [], 0
        for i in range(0, len(imgs), 256):
            chunk = imgs[i:i + 256]
            out += [[h["char"] for h in hits] for hits in RP.rare_for_batch(chunk, k)]
        # 升级率：基集首位分低于阈值的格（与 rare_for_batch 同一判据，单独算一遍只为报数）
        cnn = shared()
        for i in range(0, len(imgs), 256):
            norms = [RP.normalize_patch(im) for im in imgs[i:i + 256]]
            n_esc += sum(1 for e in cnn.emb_topk_batch(norms, base, k=1) if (not e) or e[0][1] < threshold)
        return out, set(base) | set(esc), (n_esc / len(imgs) if esc else 0.0)
    finally:
        CS.spec_for_book = orig
        RP.normalize_patch = orig_norm
        RP.book_charsets.cache_clear()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", action="append", required=True)
    ap.add_argument("--dataset", default="../open-guji-dataset/char-clustering")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--escalate", action="append", default=None,
                    help="要比的升级档，可多次；缺省 unicode-ext-b 与 unicode-all")
    ap.add_argument("--threshold", action="append", type=float, default=None,
                    help="escalate_threshold，可多次；缺省 0.85 与 0.95")
    ap.add_argument("--top-m", type=int, default=1, help="展开前几名的族")
    ap.add_argument("--cap", type=int, default=12)
    ap.add_argument("--no-cls", action="store_true",
                    help="分类头不进融合（权重置 0），只看 emb 一路经阶梯之后的结果；用来分开「阶梯」和「融合」各丢多少")
    ap.add_argument("--cls", action="append", default=None,
                    help="分类头进融合的方式，可多次：gate（现行软门控，缺省）、off（权重 0）、fixed:<w>（固定权重）、"
                         "hard（emb 首位在类外就关，topm=1）、hi:<w>（软门控但上限降到 w）")
    ap.add_argument("--source", choices=["rare", "expected"], default="rare",
                    help="rare＝rare.jsonl（送审难格）；expected＝expected.json 的全部实例（001/002 是整页所有格）")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    import cv2
    from open_guji_cv.clustering.charset_spec import is_simplified
    from open_guji_cv.clustering.rare_family import expand_family, family_hit

    from open_guji_cv.clustering import cnn_candidates as CC
    gate0 = CC.cls_gate_weight
    classes = CC.shared_classes()

    def set_cls(mode: str) -> None:
        if mode == "gate":
            CC.cls_gate_weight = gate0
        elif mode == "off":
            CC.cls_gate_weight = lambda *_a, **_k: 0.0
        elif mode == "hard":
            CC.cls_gate_weight = lambda emb_order, cl, **_k: gate0(emb_order, cl, topm=1)
        elif mode.startswith("fixed:"):
            w = float(mode[6:])
            CC.cls_gate_weight = lambda *_a, **_k: w
        elif mode.startswith("hi:"):
            w = float(mode[3:])
            CC.cls_gate_weight = lambda emb_order, cl, **_k: gate0(emb_order, cl, hi=w)
        else:
            raise SystemExit(f"--cls 不认识：{mode}")

    cls_modes = a.cls or (["off"] if a.no_cls else ["gate"])

    report = {}
    for shard in a.shard:
        d = Path(a.dataset) / "samples" / shard
        if a.source == "expected":
            items = [{"char": x["char"], "png": x["crop"]}
                     for x in json.loads((d / "expected.json").read_text(encoding="utf-8"))["instances"] if x.get("char")]
        else:
            items = [json.loads(l) for l in (d / "rare.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        if a.limit:
            items = items[:a.limit]
        imgs, kept = [], []
        for it in items:
            im = cv2.imread(str(d / it["png"]), cv2.IMREAD_GRAYSCALE)
            if im is not None:
                imgs.append(im)
                kept.append(it)
        items = kept
        groups = {"all": list(range(len(items)))}
        for i, it in enumerate(items):
            for st in it.get("strata", []):
                groups.setdefault(st, []).append(i)
            groups.setdefault("类内" if it["char"] in classes else "类外", []).append(i)   # 分类头训练字表内／外
        rep = {}
        for esc, th, mode in [(e, t, m) for e in (a.escalate or ["unicode-ext-b", "unicode-all"])
                              for t in (a.threshold or [0.85, 0.95]) for m in cls_modes]:
            if True:
                set_cls(mode)
                cands, reach, rate = run_config(imgs, esc, th, a.k)
                extra = [[c for c, _ in expand_family(cs, a.top_m, a.cap, keep=lambda c: not is_simplified(c))]
                         for cs in cands]
                key = f"{esc}@{th}" + ("" if mode == "gate" else f"/cls={mode}")
                rep[key] = {"escalate_rate": rate}
                for name, idx in groups.items():
                    n = len(idx)
                    g = [items[i]["char"] for i in idx]
                    hit = lambda cs, x: any(same(c, x) for c in cs)  # noqa: E731
                    row = {
                        "n": n,
                        "top1": sum(bool(cands[i]) and same(cands[i][0], x) for i, x in zip(idx, g)) / n,
                        "family_top1": sum(family_hit(cands[i], x) or (bool(cands[i]) and same(cands[i][0], x))
                                           for i, x in zip(idx, g)) / n,
                        "topk": sum(hit(cands[i], x) for i, x in zip(idx, g)) / n,
                        "topk_family": sum(hit(cands[i] + extra[i], x) for i, x in zip(idx, g)) / n,
                        "avg_cands_family": sum(len(cands[i]) + len(extra[i]) for i in idx) / n,
                        "reachable": sum(x in reach for x in g) / n,
                    }
                    rep[key][name] = row
                    print(f"[{shard}] {key:22s} {name:7s} n={n:5d} 首位 {row['top1']:.3f} 族首位 {row['family_top1']:.3f} "
                          f"前{a.k} {row['topk']:.3f} 前{a.k}＋族 {row['topk_family']:.3f}（平均 {row['avg_cands_family']:.1f} 字） "
                          f"可达 {row['reachable']:.3f} 升级率 {rate:.2f}", flush=True)
        report[shard] = rep
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
