# -*- coding: utf-8 -*-
"""零样本正面对比：HOG 字体检索 vs CNN 分类 vs 两者融合。同一批样本、同一字表。

融合用倒数排名（RRF）：score = Σ 1/(60+rank)。不用分数相加——HOG 余弦与
softmax 概率量纲不同，RRF 只看名次，不用校准。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from open_guji_cv.core.workspace import corpus_path  # noqa: E402

BENCH = Path("cache/glyph_bench")


def main() -> int:
    ap = argparse.ArgumentParser()
    # 缺省跟现役 checkpoint 走（cnn_candidates.DEFAULT_CKPT），别再写死路径：
    # 2026-09-21 实锤——原缺省 `cache/glyph_cnn/best.pt` 是 09-05 的旧模型，本机一直
    # 留着这个文件，于是不带 --model 跑出来的「r5 基线」其实量的是它，不是 r5，
    # 而 eval_oov / eval_struct_rerank 缺省都是 DEFAULT_CKPT，三个脚本不同口径。
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT
    ap.add_argument("--model", default=str(DEFAULT_CKPT))
    ap.add_argument("--split", default="unseen")
    ap.add_argument("--n", type=int, default=0, help="0=全部")
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--rare", action="store_true", help="改测 rare-char 21 条")
    ap.add_argument("--corpus", default=str(corpus_path("zongmu_wuyingdian_reference.txt")))
    ap.add_argument("--tta", action="store_true", help="CNN 测试时增广：5 个视角平均 logits")
    ap.add_argument("--w-cnn", type=float, default=1.0, help="RRF 里 CNN 名次的权重（HOG=1）")
    ap.add_argument("--w-hog", type=float, default=1.0, help="RRF 里 HOG 名次的权重")
    ap.add_argument("--w-emb", type=float, default=1.0, help="RRF 里 embedding 检索名次的权重")
    ap.add_argument("--emb-mode", default="mean", choices=("mean", "max", "aug"),
                    help="模板向量：mean=4 字体均值（生产）；max=逐字体取最大相似；aug=均值里掺退化渲染")
    ap.add_argument("--emb", action="store_true",
                    help="第三源：CNN embedding 对字体模板做余弦检索（CCR-CLIP-lite）")
    ap.add_argument("--emb-extra", action="append", default=[],
                    help="外部真刻本模板源，可重复：kangxi:<dir> | zitools:<dir>[:印,楷]（见 clustering/extra_glyphs.py）")
    ap.add_argument("--emb-extra-only", action="store_true", help="模板只用 --emb-extra，不用字体渲染")
    ap.add_argument("--eval-chars", default=None,
                    help="只评这个文件里出现的字（UTF-8 文本）——做「外部源已覆盖的字」配对比较用")
    ap.add_argument("--variant-subset", action="store_true",
                    help="只评异体子集：char 在 config/charset/variants.tsv 里映射到别字的实例")
    ap.add_argument("--wear", type=float, default=0.0,
                    help="评测时给查询图加磨损：0=不加；0.5=腐蚀+抹白一次；1=两次")
    ap.add_argument("--real-proto", action="store_true",
                    help="开真刻例多原型档（R2/T11，cnn_candidates.REAL_PROTO_ENABLED，缺省关）；"
                         "只对 --emb-mode mean 且不带 --emb-extra 时生效（生产的接线）")
    ap.add_argument("--real-proto-store", action="append", default=[],
                    help="真刻例来源 store:<glyph_store 目录>，可重复；配合 --real-proto 用")
    a = ap.parse_args()

    import torch
    from open_guji_cv.clustering.font_candidates import book_charset, candidates
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.variants import are_variants

    if a.rare:
        items = [json.loads(l) for l in Path("../open-guji-dataset/rare-char/items.jsonl").read_text(encoding="utf-8").splitlines()]
        items = [{"png": i["input"]["patch"], "char": i["expected"]["char"]} for i in items]
    else:
        items = [json.loads(l) for l in (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines()]
        items = [i for i in items if i["split"] == a.split]
        if a.n:
            import random
            random.Random(1).shuffle(items)
            items = items[:a.n]
    if a.eval_chars:
        allow_ch = set(Path(a.eval_chars).read_text(encoding="utf-8"))
        items = [i for i in items if i["char"] in allow_ch]
        print(f"限定字表 {a.eval_chars}: n={len(items)}（{len({i['char'] for i in items})} 字种）")
    if a.variant_subset:
        vm = {}
        for l in Path("config/charset/variants.tsv").read_text(encoding="utf-8").splitlines():
            if l.strip() and not l.startswith("#"):
                r = l.split("	")
                if len(r) >= 2:
                    vm[r[0]] = r[1]
        items = [i for i in items if vm.get(i["char"], i["char"]) != i["char"]]
        print(f"异体子集 n={len(items)}（{len({i['char'] for i in items})} 字种）")
    cs = tuple(book_charset(a.corpus))

    ck = torch.load(a.model, map_location="cpu", weights_only=False)
    classes = ck["classes"]
    import torch.nn.functional as F
    # 网络结构以 cnn_candidates._build_net 为准（2026-09-21 起有可选的结构头/槽位头）：
    # 这里原来自己抄了一份 Net，r6 checkpoint 多了 struct/slot 两个键就 load 不进来。
    from open_guji_cv.clustering.cnn_candidates import _build_net
    net = _build_net(len(classes), len(ck["comps"]),
                     n_struct=len(ck.get("struct_classes") or ()),
                     n_slot=len(ck.get("slot_labels") or ()))
    net.load_state_dict(ck["state"]); net.eval()
    cs_idx = {c: i for i, c in enumerate(classes)}
    allowed = torch.tensor([cs_idx[c] for c in cs if c in cs_idx])

    emb_mat = None
    emb_chars: list[str] = []
    real_mat = None
    real_rows_idx = None
    if a.emb:
        # 复用 CnnCandidates 的落盘模板向量（按 checkpoint 指纹 + 字表），
        # 免得每个配置重算 4,636 × 4 张渲染——扫权重时这是 90% 的耗时。
        from open_guji_cv.clustering.cnn_candidates import CnnCandidates
        cc_ = CnnCandidates(a.model)
        cc_._ensure()
        cc_._net = cc_._net.to("cpu"); cc_._dev = "cpu"
        if a.emb_mode == "mean" and not a.emb_extra:
            emb_mat, emb_chars = cc_._emb_index(cs)
            emb_owner = None
            real_mat = real_rows_idx = None
            if a.real_proto:
                import open_guji_cv.clustering.cnn_candidates as _cc
                _cc.REAL_PROTO_ENABLED = True
                _cc.REAL_PROTO_SPECS = tuple(a.real_proto_store)
                # 留一法：这批评测字自己的物理格不许进它自己的真刻例模板
                # （同 5-a 的教训「自证不是证据」），见 `cnn_candidates._real_index`。
                real_loo = frozenset(it["id"] for it in items if it.get("id"))
                real = cc_._real_index(cs, emb_chars, real_loo)
                if real is not None:
                    real_mat, real_rows_idx, real_iids = real
                    print(f"真刻例多原型档：{len(real_mat)} 个原型 / "
                          f"{len(set(real_rows_idx.tolist()))} 字（留一法摘除 {len(real_loo)} 个物理格）")
                else:
                    print("真刻例多原型档：开了但没取到任何原型（检查 --real-proto-store）")
        elif a.emb_extra:
            # 外部真刻本模板：每字 = mean(字体渲染向量 ∪ 外部图向量)（--emb-extra-only 时只用外部图）
            from open_guji_cv.clustering.extra_glyphs import load_many
            from open_guji_cv.clustering.font_candidates import _font_files
            from open_guji_cv.clustering.synth import render_char
            extra = load_many(a.emb_extra, cs)
            n_ex = sum(len(v) for v in extra.values())
            print(f"外部模板 {n_ex} 张 / {len(extra)} 字（字表 {len(cs)} 字，覆盖 {len(extra)/len(cs):.1%}）")
            fonts = _font_files()
            vecs, owner = [], []
            with torch.no_grad():
                for ch in cs:
                    ims = []
                    if not a.emb_extra_only:
                        for fp in fonts:
                            try:
                                im = render_char(ch, fp, size=64)
                            except Exception:
                                continue
                            if im is not None and im.any():
                                ims.append(im.astype(np.uint8))
                    ims += extra.get(ch, [])
                    if not ims:
                        continue
                    x = torch.tensor(np.stack(ims)[:, None].astype(np.float32))
                    e, _, _ = net(x)
                    e = e / (e.norm(dim=1, keepdim=True) + 1e-9)
                    v = e.mean(0); vecs.append((v / (v.norm() + 1e-9)).numpy()); owner.append(ch)
            emb_mat = np.stack(vecs).astype(np.float32)
            emb_chars = owner
            emb_owner = owner
        else:
            # 实验用：不落盘。max = 每字体一条向量，检索时按字取最大相似；
            # aug = 每字 4 字体 × (原图 + 腐蚀 + 膨胀) 的均值——让模板分布更像刻本。
            from open_guji_cv.clustering.font_candidates import _font_files
            from open_guji_cv.clustering.synth import render_char
            fonts = _font_files()
            vecs, owner = [], []
            with torch.no_grad():
                for ch in cs:
                    ims = []
                    for fp in fonts:
                        try:
                            im = render_char(ch, fp, size=64)
                        except Exception:
                            continue
                        if im is not None and im.any():
                            ims.append(im.astype(np.uint8))
                    if not ims:
                        continue
                    if a.emb_mode == "aug":
                        ims = ims + [cv2.erode(x, np.ones((2, 2), np.uint8)) for x in ims]                                   + [cv2.dilate(x, np.ones((2, 2), np.uint8)) for x in ims]
                    x = torch.tensor(np.stack(ims)[:, None].astype(np.float32))
                    e, _, _ = net(x)
                    e = e / (e.norm(dim=1, keepdim=True) + 1e-9)
                    if a.emb_mode == "aug":
                        v = e.mean(0); vecs.append((v / (v.norm() + 1e-9)).numpy()); owner.append(ch)
                    else:
                        for row in e.numpy():
                            vecs.append(row); owner.append(ch)
            emb_mat = np.stack(vecs).astype(np.float32)
            emb_chars = owner
            emb_owner = owner
        print(f"embedding 模板 {emb_mat.shape[0]} 向量 / {len(set(emb_chars))} 字（{a.emb_mode}）")

    def wear(q: np.ndarray) -> np.ndarray:
        """评测用磨损：腐蚀一圈 + 横向抹白，模拟断墨。确定性（按图求种子）。"""
        if a.wear <= 0:
            return q
        import random
        rng = random.Random(int(q.sum()))
        x = cv2.erode(q, np.ones((2, 2), np.uint8))
        for _ in range(1 if a.wear < 1 else 2):
            y = rng.randint(6, 56)
            x[y:y + 2, :] = 0
        return x

    def hit(order, g):
        r = next((i + 1 for i, c in enumerate(order) if c == g or are_variants(c, g)), 999)
        return r

    def hit_strict(order, g):
        return next((i + 1 for i, c in enumerate(order) if c == g), 999)

    rk_strict = {k: Counter() for k in ("hog", "cnn", "emb", "rrf")}

    rk = {k: Counter() for k in ("hog", "cnn", "emb", "rrf")}
    n = 0
    with torch.no_grad():
        for it in items:
            # `items.jsonl` 是在 Windows 上建的（`build_glyph_bench.py`），`png` 路径带
            # `\`——云端跑在 Linux 上，`cv2.imread` 不认反斜杠分隔符，逐条文件读失败但
            # 不报错、只留 opencv 的 WARN 日志，图直接被判 None 跳过，n 悄悄归零。
            img = cv2.imread(str(it["png"]).replace("\\", "/"), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            q = wear(normalize_patch(img)); g = it["char"]; n += 1
            hog = [h.char for h in candidates(q, cs, k=a.k)]
            views = [q]
            if a.tta:
                for ang in (-4, 4):
                    M = cv2.getRotationMatrix2D((32, 32), ang, 1.0)
                    views.append(cv2.warpAffine(q, M, (64, 64), flags=cv2.INTER_NEAREST, borderValue=0))
                views.append(cv2.dilate(q, np.ones((2, 2), np.uint8)))
                views.append(cv2.erode(q, np.ones((2, 2), np.uint8)))
            x = torch.tensor(np.stack(views)[:, None].astype(np.float32))
            e_all, lg, _ = net(x)
            lg = torch.log_softmax(lg, dim=1).mean(0)
            emb_order: list[str] = []
            if emb_mat is not None:
                qe = e_all.mean(0); qe = (qe / (qe.norm() + 1e-9)).numpy()
                sims = emb_mat @ qe
                if real_mat is not None:
                    sr = real_mat @ qe
                    best = np.full(sims.shape[0], -2.0, np.float32)
                    np.maximum.at(best, real_rows_idx, sr)
                    sims = np.maximum(sims, best)
                if a.emb_mode == "max":
                    best: dict[str, float] = {}
                    for i in np.argsort(-sims):
                        ch_ = emb_chars[int(i)]
                        if ch_ not in best:
                            best[ch_] = float(sims[int(i)])
                            if len(best) >= a.k:
                                break
                    emb_order = list(best)
                else:
                    emb_order = [emb_chars[int(i)] for i in np.argsort(-sims)[:a.k]]
            sub = lg[allowed]
            top = sub.topk(a.k).indices
            cnn = [classes[int(allowed[i])] for i in top]
            fused = Counter()
            srcs = [(hog, a.w_hog), (cnn, a.w_cnn)] + ([(emb_order, a.w_emb)] if emb_order else [])
            for order, w in srcs:
                for r, c in enumerate(order):
                    fused[c] += w / (60 + r)
            rrf = [c for c, _ in fused.most_common(a.k)]
            pairs = [("hog", hog), ("cnn", cnn)] + ([("emb", emb_order)] if emb_order else []) + [("rrf", rrf)]
            for name, order in pairs:
                r = hit(order, g)
                rk[name]["t1"] += r == 1; rk[name]["t5"] += r <= 5; rk[name]["t10"] += r <= 10
                r = hit_strict(order, g)
                rk_strict[name]["t1"] += r == 1; rk_strict[name]["t5"] += r <= 5; rk_strict[name]["t10"] += r <= 10
    tag = "rare-char" if a.rare else f"{a.split}"
    print(f"{tag} n={n}（异体算对）")
    for name in ("hog", "cnn", "emb", "rrf"):
        c = rk[name]
        if not sum(c.values()) and name == "emb":
            continue
        print(f"  {name:4s} top1 {c['t1']/n:5.1%}  top5 {c['t5']/n:5.1%}  top10 {c['t10']/n:5.1%}")
    print(f"{tag} n={n}（严格：只认同一码位）")
    for name in ("hog", "cnn", "emb", "rrf"):
        c = rk_strict[name]
        if not sum(c.values()) and name == "emb":
            continue
        print(f"  {name:4s} top1 {c['t1']/n:5.1%}  top5 {c['t5']/n:5.1%}  top10 {c['t10']/n:5.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
