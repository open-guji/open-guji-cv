# -*- coding: utf-8 -*-
"""补标签两批（L3，2026-10-01）：本地一条命令出批次 → 控制台点卡 → 一条命令收割进 dataset。

背景：overview #323 第一批结论——学习模型卡在「干净标签太少」。用户 10-01 同意出两批卡：

| 批 | 命令 | 控制台入口 | 收割进 dataset |
|---|---|---|---|
| A 切线金标（页面坐标口径）| `guji label-batch make cutline-gold <册> --n 200` | Step3「拖切线」页码框填 `list:<批次id>` | `char-segmentation/touching-cuts`（新增条目，不改旧条目）|
| B 列端版框分档 | `guji label-batch make column-end <册> --n 240` | Step1 页「Step2 上下版框核校」页码框填 `batch:<批次id>` | `char-segmentation/column-end-class`（新分片）|

**只读现行产物**：没有正式产物（`border_detect`/`column_warp`/`row_segment`）就清楚报错，
不现算、不写 products。出卡时冻结的东西（抽样权重、分层、产物指纹、页面坐标锚、图像指纹）
全落在 `<批次>_cards.jsonl`——收割时按它回填，所以「出卡之后产物又被重跑」不会让金标丢锚。

## 抽样与无偏估计

难例超采样（否则 200 张里九成是「一眼就对」的切点，攒不出能用的错例），所以**不能直接数比例**。
每张卡记 `stratum` / `stratum_weight = N_h / n_h`（Horvitz–Thompson 权重：该层总体数 / 该层抽样数），
全书错误率 = Σ w_i·err_i / Σ w_i。收割时权重原样写进金标条目的 `stratum_weight`。
总体 `N_h` 与各层抽样数另存 `<批次>_sampling.json`。

## 坐标口径

- 切线：金标 `y` 仍是列图行号（评测沿用），**另记页面坐标**——`expected.page_x_tr/page_y`
  （`raw_page_px@top-right`，与 `CellRec.quad_page` 同系）和 `anchor.space`。控制台写切线事件时已带
  `page_x/page_y`（那是**左上原点**的原图像素，`eval/colgeom.py` 口径），收割时换成右上原点：
  `x_tr = page_w - 1 - page_x`。
- 列端：锚 = 该端裁剪区在原图上的四角（右上原点）+ 端裁剪图指纹。
"""
from __future__ import annotations

import base64
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from ..errors import ProductMissing

SPACE_TR = "raw_page_px@top-right"
CUTLINE_SHARD = "char-segmentation/touching-cuts"
COLEND_SHARD = "char-segmentation/column-end-class"
SOURCE = "L3-batch"

#: 列端统一类别（用户 10-01）：none 无框 / trim 框可整段削 / glued 框粘字 / double 双层框 / idk 拿不准
END_CLASSES = ("none", "trim", "glued", "double", "idk")

#: 旧事件（`border_class`，README 定义「clean=有框墨且与首字有间隙」）→ 新类别。
#: clean 的定义就是「框与字之间有间隙、可以整段削」，与 trim 同义；glued/none/idk 同名同义。
#: 旧体系没有 double 档——旧 clean 里若有双层框，只能由人重标，这里不猜。
LEGACY_END_MAP = {"clean": "trim", "glued": "glued", "none": "none", "idk": "idk"}


# ═══ 通用：分层抽样 ═══════════════════════════════════════════════════

def allocate(pops: dict[str, int], total: int, floor: int = 4,
             tier_of: dict[str, str] | None = None,
             tier_share: dict[str, float] | None = None) -> dict[str, int]:
    """把 `total` 张名额分给各层。

    先按 `tier_share`（难度档占比，缺省不分档）切到各档，档内按 √N_h 比例分、每层至少 `floor`
    （层小于 floor 就全取）；名额有余/不足时按 √N_h 余量回填。返回 {层: n_h}，Σ ≤ min(total, ΣN_h)。
    √ 比例是折中：纯比例分配会让大层吃光名额，等量分配又会在小层上抽干。
    """
    keys = [k for k, v in pops.items() if v > 0]
    if not keys:
        return {}
    total = min(total, sum(pops[k] for k in keys))
    out = {k: 0 for k in keys}

    def fill(ks: list[str], quota: int) -> None:
        if not ks or quota <= 0:
            return
        for k in ks:                                   # 地板
            take = min(pops[k] - out[k], max(0, floor - out[k]), quota)
            out[k] += take
            quota -= take
        while quota > 0:                               # 按 √N 余量回填
            room = {k: pops[k] - out[k] for k in ks if pops[k] - out[k] > 0}
            if not room:
                break
            wsum = sum(math.sqrt(pops[k]) for k in room)
            given = 0
            for k in sorted(room, key=lambda k: -pops[k]):
                give = min(room[k], max(1, int(quota * math.sqrt(pops[k]) / wsum)))
                give = min(give, quota - given)
                out[k] += give
                given += give
                if given >= quota:
                    break
            if given == 0:
                break
            quota -= given

    if tier_of and tier_share:
        left = total
        tiers = list(tier_share)
        for i, t in enumerate(tiers):
            ks = [k for k in keys if tier_of.get(k) == t]
            quota = left if i == len(tiers) - 1 else int(round(total * tier_share[t]))
            before = sum(out.values())
            fill(ks, min(quota, left))
            left -= sum(out.values()) - before
        # 某档小于配额留下的缺口，全局回填
        fill(keys, total - sum(out.values()))
    else:
        fill(keys, total)
    return {k: v for k, v in out.items() if v > 0}


def stratified_sample(pool: dict[str, list], n: int, seed: int = 0, floor: int = 4,
                      tier_of: dict[str, str] | None = None,
                      tier_share: dict[str, float] | None = None
                      ) -> tuple[list[tuple[str, object, float]], dict[str, dict]]:
    """pool: {层: [个体]} → ([(层, 个体, 权重)], {层: {N, n, weight}})。层内简单随机（seed 定）。"""
    pops = {k: len(v) for k, v in pool.items()}
    alloc = allocate(pops, n, floor=floor, tier_of=tier_of, tier_share=tier_share)
    rng = random.Random(seed)
    picked, table = [], {}
    for k in sorted(alloc):
        items = list(pool[k])
        # 先按稳定键排序再抽，保证同 seed 同产物结果一致（与 dict/glob 顺序无关）
        items.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        take = rng.sample(items, alloc[k])
        w = round(len(items) / alloc[k], 4)
        table[k] = {"N": len(items), "n": alloc[k], "weight": w}
        picked += [(k, x, w) for x in take]
    return picked, table


# ═══ 批次落盘 ═════════════════════════════════════════════════════════

def is_label_batch(batch_id: str, root: Path | None = None) -> bool:
    """这个批次是 L3 补标签批吗（出批次时冻结了 `<id>_cards.jsonl`）。控制台据此跳过自动消费。"""
    try:
        return cards_path(batch_id, root).exists()
    except Exception:                                      # noqa: BLE001
        return False


def cards_path(batch_id: str, root: Path | None = None) -> Path:
    from .batches import default_batches_root
    return (Path(root) if root else default_batches_root()) / f"{batch_id}_cards.jsonl"


def sampling_path(batch_id: str, root: Path | None = None) -> Path:
    from .batches import default_batches_root
    return (Path(root) if root else default_batches_root()) / f"{batch_id}_sampling.json"


def read_cards(batch_id: str, root: Path | None = None) -> list[dict]:
    p = cards_path(batch_id, root)
    if not p.exists():
        raise FileNotFoundError(f"批次 {batch_id} 没有冻结卡片文件：{p}（先 `guji label-batch make`）")
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_batch(batch_id: str, title: str, step: str, kind: str, book: str, shard: str,
                 cards: list[dict], sampling: dict, options: list[str], notes: str,
                 root: Path | None = None) -> dict:
    from .batches import Batch, BatchStore
    store = BatchStore(root)
    if store.get(batch_id):
        raise FileExistsError(f"批次 {batch_id} 已存在（换个 --id，或先 `guji batch show {batch_id}` 看进度）")
    cp = cards_path(batch_id, root)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cards) + "\n", encoding="utf-8")
    sampling_path(batch_id, root).write_text(json.dumps(sampling, ensure_ascii=False, indent=1), encoding="utf-8")
    b = Batch(id=batch_id, title=title, step=step, kind=kind, book=book, shard=shard,
              cards_ref=cp.name, n_cards=len(cards), options=options, status="open", notes=notes)
    store.save(b)
    return {"batch": batch_id, "n_cards": len(cards), "cards_file": str(cp), "strata": sampling["strata"]}


def _need_products(store, book: str, step: str, kind: str, pages: list[int]) -> list[int]:
    """返回确有该产物的页；一页都没有就清楚报错（不现算、不碰正式 products）。"""
    from ..core.spec import page_key
    have = []
    for pg in pages:
        try:
            if store.read(book, step, page_key(pg), kind) is not None:
                have.append(pg)
        except Exception:                                   # noqa: BLE001
            continue
    if not have:
        raise ProductMissing(
            f"{book} 在所选页范围内没有现行 `{step}/{kind}` 产物——本命令只读现行产物、不现算。"
            f"先在本机跑 `guji pipeline <管线> {book}`（或 `guji step {step} {book}`），再出批次。"
            f"（本机产物目录：`guji status {book}` 可查）")
    return have


# ═══ A 切线金标 ═══════════════════════════════════════════════════════

def _cut_difficulty(cp, escalate_blob: int) -> tuple[str, dict]:
    """一个切点的难度档与描述量。"""
    cands = list(getattr(cp, "candidates", None) or [])
    ch = cands[cp.chosen] if (cp.chosen is not None and 0 <= cp.chosen < len(cands)) else None
    dis = getattr(ch, "dis_unet", None) if ch is not None else None
    agree = getattr(ch, "agree", None) if ch is not None else None
    kinds = sorted({c.kind for c in cands})
    info = dict(n_cand=len(cands), chosen_kind=getattr(ch, "kind", None), dis_unet=dis, agree=agree,
                cand_kinds=kinds, escalate=bool(getattr(cp, "escalate", False)),
                chosen_by=getattr(cp, "chosen_by", None), origin=getattr(cp, "origin", None))
    if info["escalate"] or (dis is not None and dis >= escalate_blob):
        return "hard", info
    if len(cands) >= 2 or (dis is not None and dis > 0) or (agree is not None and agree < 0.8):
        return "mid", info
    return "easy", info


def cutline_population(store, book: str, pages: list[int], exclude_ids: set[str]) -> tuple[dict[str, list[dict]], dict]:
    """现行 Step3 产物里的全部「字–字」切点，按 层=上下文|难度 分组。

    上下文：`jiazhu`（上下任一格是单行小注）/ `tail`（下格是本列末格）/ `seal`（遮挡块里）/ `body`。
    切点个体 = `{id, page, col, ...}`；id = `book:页:列:上格slot`（与控制台切线卡同一规则）。
    不含：上下任一格是 blank、带 a/b 小注的（切线卡按 sub=None 配格，出不了卡）、已在金标里的。
    """
    from ..core.spec import page_key
    from ..utils.cut_select import PENDING_BLOB
    pool: dict[str, list[dict]] = defaultdict(list)
    n_all = 0
    skipped = defaultdict(int)
    for pg in pages:
        cells = store.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        seal = _seal_cells(book, pg)
        for cc in cells.columns:
            if not cc.ok:
                skipped["column_not_ok"] += 1
                continue
            cmap = {c.slot: c for c in cc.cells if c.sub is None}
            last_slot = max((c.slot for c in cc.cells if c.sub is None), default=None)
            cps = {cp.slot_above: cp for cp in (cc.cut_candidates or [])}
            for slot, up in sorted(cmap.items()):
                dn = cmap.get(slot + 1)
                if dn is None:
                    continue
                if up.kind == "blank" or dn.kind == "blank":
                    skipped["blank"] += 1
                    continue
                cid = f"{book}:{pg}:{cc.col}:{slot}"
                if cid in exclude_ids:
                    skipped["already_gold"] += 1
                    continue
                n_all += 1
                cp = cps.get(slot)
                if cp is not None:
                    diff, info = _cut_difficulty(cp, PENDING_BLOB)
                else:
                    diff, info = "easy", dict(n_cand=0, chosen_kind=None, dis_unet=None, agree=None,
                                              cand_kinds=[], escalate=False, chosen_by=None, origin=None)
                if "jiazhu" in (up.kind, dn.kind) or up.kind.startswith("jiazhu") or dn.kind.startswith("jiazhu"):
                    ctx = "jiazhu"
                elif (cc.col, slot) in seal or (cc.col, slot + 1) in seal:
                    ctx = "seal"
                elif slot + 1 == last_slot:
                    ctx = "tail"
                else:
                    ctx = "body"
                pool[f"{ctx}|{diff}"].append(dict(
                    id=cid, page=pg, col=cc.col, slot_above=slot, slot_below=slot + 1,
                    ctx=ctx, diff=diff, kind_up=up.kind, kind_dn=dn.kind, **info))
    return pool, {"n_population": n_all, "skipped": dict(skipped)}


def _seal_cells(book: str, page: int) -> set[tuple[int, int]]:
    """该页被印章/遮挡块盖住的 (col, slot)；判据同定字入库闸（`feedback.consumers._occluded_lookup`）。取不到 → 空集。"""
    try:
        from ..feedback.consumers import _occluded_lookup
        return {(c, s) for c, s, _sub in _occluded_lookup(book, page)}
    except Exception:                                      # noqa: BLE001
        return set()


def build_cutline_gold(book: str, n: int = 200, batch_id: str | None = None, pages: str = "body",
                       seed: int = 0, store=None, batches_root: Path | None = None,
                       lists_root: Path | None = None, exclude_ids: set[str] | None = None) -> dict:
    """出 A 批：从现行产物按分层抽样选 ~n 个切点，写批次登记 + 卡片冻结文件 + 控制台清单。"""
    from ..core.book import load_book
    from ..core.spec import page_key
    from ..core.workspace import feedback_root
    from ..eval import touching as T
    from ..eval.colgeom import current_geom
    from ..products.store import ProductStore
    store = store or ProductStore()
    bk = load_book(book)
    pgs = T.std_grid_pages(book) if pages in ("body", "std") else bk.resolve_pages(pages)
    pgs = _need_products(store, book, "row_segment", "cells", pgs)
    if exclude_ids is None:
        exclude_ids = T.gold_ids()
    pool, meta = cutline_population(store, book, pgs, exclude_ids)
    if not pool:
        raise ProductMissing(f"{book} 的现行 Step3 产物里没有可出卡的字–字切点（已在金标里的 {meta['skipped'].get('already_gold', 0)} 个已排除）")
    tier_of = {k: k.split("|")[1] for k in pool}
    picked, table = stratified_sample(
        pool, n, seed=seed, floor=6, tier_of=tier_of,
        tier_share={"hard": 0.4, "mid": 0.35, "easy": 0.25})
    batch_id = batch_id or f"L3-cutline-{book}-{time.strftime('%m%d')}"
    cards, no_geom = [], 0
    for stratum, it, w in picked:
        g = current_geom(store, book, it["page"], it["col"])
        if g is None:
            no_geom += 1
            continue
        pw = store.read(book, "column_warp", page_key(it["page"]), "column_windows").page_size[0]
        cells = store.read(book, "row_segment", page_key(it["page"]), "cells")
        cc = cells.column(it["col"])
        cmap = {c.slot: c for c in cc.cells if c.sub is None}
        up, dn = cmap[it["slot_above"]], cmap[it["slot_below"]]
        bbox = _pair_bbox(up, dn)
        cards.append({**it, "book": book, "stratum": stratum, "stratum_weight": w,
                      "page_w": int(pw), "geom_sig": g.sig, "space": SPACE_TR, "bbox": bbox,
                      "product_key": _fp(store, book, "row_segment", it["page"]),
                      "y_engine": round(float(up.y1), 2)})
    cards.sort(key=lambda c: (c["page"], c["col"], c["slot_above"]))
    sampling = {"kind": "cutline-gold", "book": book, "seed": seed, "n_requested": n,
                "n_cards": len(cards), "n_dropped_no_geom": no_geom, "pages": pages,
                "n_pages_with_product": len(pgs), **meta, "strata": table,
                "estimator": "Horvitz-Thompson：全书率 = Σ w_i·x_i / Σ w_i，w = stratum_weight",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    out = _write_batch(batch_id, f"切线金标 {book}（分层 {len(cards)} 个切点）", "row_segment", "cutline",
                       book, CUTLINE_SHARD, cards, sampling, ["ok", "moved", "overlap", "seam_ok", "idk"],
                       "L3 补标签 A 批：页面坐标口径；收割 `guji label-batch harvest <id>`", batches_root)
    lists = Path(lists_root) if lists_root else feedback_root() / "lists"
    lists.mkdir(parents=True, exist_ok=True)
    lp = lists / f"{batch_id}.txt"
    lp.write_text("# L3 切线金标清单（由 `guji label-batch make cutline-gold` 生成）\n"
                  + "\n".join(c["id"] for c in cards) + "\n", encoding="utf-8")
    out.update(list_file=str(lp), console_pages=f"list:{batch_id}")
    return out


def _fp(store, book: str, step: str, page: int) -> dict | None:
    from ..core.spec import page_key
    try:
        man = store.manifest(book, step)
        rec = man.get(page_key(int(page))) if man else None
        fp = getattr(rec, "fingerprint", None)
        return {"step": step, "key": page_key(int(page)), "fingerprint": fp} if fp else None
    except Exception:                                      # noqa: BLE001
        return None


def _pair_bbox(*cells) -> list[float] | None:
    xs, ys = [], []
    for c in cells:
        for p in (c.quad_page or []):
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)] if xs else None


# ═══ B 列端版框分档 ═══════════════════════════════════════════════════

CROP_ROWS = 220


def end_fingerprint(crop: np.ndarray) -> str:
    """端裁剪图的 16×16 均值哈希（256 bit → base64）。『人当时看的那张图还在不在』的判据，同 column-warp 金标思路。"""
    import cv2
    g = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    s = cv2.resize(g, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
    bits = (s > s.mean()).astype(np.uint8).ravel()
    return base64.b64encode(np.packbits(bits).tobytes()).decode()


def end_difficulty(case: str, cls: str) -> str:
    """列端难度档。b/bi/c/e、多层、glued/idk 是难例；a/d 且 none/clean 是易例。"""
    layers = int("".join(ch for ch in case if ch.isdigit()) or 1)
    letter = case[:1]
    if layers >= 2 or letter in "bce" or cls in ("glued", "idk"):
        return "hard"
    if letter == "d" or cls == "clean":
        return "mid"
    return "easy"


def column_end_population(store, book: str, pages: list[int]) -> tuple[dict[str, list[dict]], dict]:
    from ..core.spec import page_key
    pool: dict[str, list[dict]] = defaultdict(list)
    n_all, skipped = 0, defaultdict(int)
    for pg in pages:
        wins = store.read(book, "column_warp", page_key(pg), "column_windows")
        if wins is None:
            continue
        try:                                        # 版心列（书口）不出卡，口径同 column_review
            li = store.read(book, "border_detect", page_key(pg), "line_index")
            margin = {i for i, ln in enumerate(li.lines, 1) if getattr(ln, "kind", "body") != "body"}
        except Exception:                           # noqa: BLE001
            margin = set()
        for w in wins.columns:
            if w.col in margin:
                skipped["margin_col"] += 1
                continue
            for end, trim, tcls in (("top", w.trim_top, w.triage.top_class if w.triage else "na"),
                                    ("bot", w.trim_bottom, w.triage.bot_class if w.triage else "na")):
                n_all += 1
                diff = end_difficulty(trim.case, tcls)
                pool[f"{trim.case}|{tcls}"].append(dict(
                    id=f"colborder:{book}:{pg}:{w.col}:{end}", page=pg, col=w.col, end=end,
                    trim_case=trim.case, trim_px=int(trim.px), end_class=tcls, diff=diff,
                    raised=bool(w.raised)))
    return pool, {"n_population": n_all, "skipped": dict(skipped)}


def build_column_end(book: str, n: int = 240, batch_id: str | None = None, pages: str = "body",
                     seed: int = 0, store=None, batches_root: Path | None = None) -> dict:
    """出 B 批：按现行 `column_border_trim` 档位（a~e+层数）× `triage end_class` 分层抽 ≥200 个列端。"""
    from ..core.book import load_book
    from ..core.spec import column_key, page_key
    from ..eval import touching as T
    from ..eval.colgeom import current_geom
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    from ..utils.column_projection import column_text_band, denoise_column
    from ..utils.image_io import imread as cv_imread
    import cv2
    store = store or ProductStore()
    bk = load_book(book)
    pgs = T.std_grid_pages(book) if pages in ("body", "std") else bk.resolve_pages(pages)
    pgs = _need_products(store, book, "column_warp", "column_windows", pgs)
    pool, meta = column_end_population(store, book, pgs)
    if not pool:
        raise ProductMissing(f"{book} 的现行 Step2 产物里没有列可出卡")
    diff_of = {k: v[0]["diff"] for k, v in pool.items()}
    # 同一层里个体的 diff 可能因 trim 层数而异；层定义已含 case（带层数后缀），所以一致
    picked, table = stratified_sample(
        pool, n, seed=seed, floor=6, tier_of=diff_of,
        tier_share={"hard": 0.5, "mid": 0.3, "easy": 0.2})
    batch_id = batch_id or f"L3-colend-{book}-{time.strftime('%m%d')}"
    cache = ImageCache()
    cards, dropped = [], defaultdict(int)
    for stratum, it, w in picked:
        raw_p = cache.get(book, "column_raw", column_key(it["page"], it["col"]))
        img = cv_imread(str(raw_p), cv2.IMREAD_GRAYSCALE) if raw_p else None
        if img is None:
            dropped["no_column_raw"] += 1
            continue
        crop = _end_crop(img, it["end"], denoise_column, column_text_band)
        wins = store.read(book, "column_warp", page_key(it["page"]), "column_windows")
        g = current_geom(store, book, it["page"], it["col"])
        cards.append({**it, "book": book, "kind": "colborder", "stratum": stratum, "stratum_weight": w,
                      "src": "raw", "space": SPACE_TR, "page_w": int(wins.page_size[0]),
                      "bbox": _end_bbox(g, it["end"], int(wins.page_size[0])) if g else None,
                      "geom_sig": g.sig if g else None,
                      "end_fingerprint": end_fingerprint(crop),
                      "product_key": _fp(store, book, "column_warp", it["page"]),
                      "img": (f"/api/border-review/img/{book}/{it['page']}.jpg"
                              f"?kind=colborder&col={it['col']}&side={it['end']}&src=raw")})
    cards.sort(key=lambda c: (c["page"], c["col"], c["end"]))
    sampling = {"kind": "column-end", "book": book, "seed": seed, "n_requested": n, "n_cards": len(cards),
                "n_dropped": dict(dropped), "pages": pages, "n_pages_with_product": len(pgs), **meta,
                "strata": table,
                "estimator": "Horvitz-Thompson：全书率 = Σ w_i·x_i / Σ w_i，w = stratum_weight；层 = 现行 trim 档(a~e+层数)|triage end_class",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return _write_batch(batch_id, f"列端版框分档 {book}（{len(cards)} 端）", "column_warp", "border_class",
                        book, COLEND_SHARD, cards, sampling, list(END_CLASSES),
                        "L3 补标签 B 批：none/trim/glued/double/idk；收割 `guji label-batch harvest <id>`", batches_root)


def _end_crop(img: np.ndarray, end: str, denoise, text_band) -> np.ndarray:
    """与 `border_cards.render_colborder_img(src='raw')` 同一裁法：去噪 → 文字带 → 取端 220 行（下端翻转）。"""
    dn = denoise(img)
    lo, hi = text_band(dn)
    core = dn[:, lo:hi]
    h = core.shape[0]
    return core[:CROP_ROWS] if end == "top" else core[max(0, h - CROP_ROWS):][::-1]


def _end_bbox(g, end: str, page_w: int) -> list[float] | None:
    """端裁剪区在原图上的外接框 `[x0,y0,x1,y1]`（右上原点）。"""
    try:
        rows = (0, CROP_ROWS) if end == "top" else (g.height - CROP_ROWS, g.height)
        pts = [g.row_to_page(r, u) for r in rows for u in (0.0, float(g.out_w))]
        xs = [page_w - 1 - p[0] for p in pts]                # 左上 → 右上原点
        ys = [p[1] for p in pts]
        return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]
    except Exception:                                      # noqa: BLE001
        return None


# ═══ 收割 ════════════════════════════════════════════════════════════

def _latest(events, kinds: tuple[str, ...]) -> dict[str, object]:
    """每个 target.key 取最后一条（同键后到覆盖，沿用事件日志纪律）。"""
    out = {}
    for e in sorted(events, key=lambda x: x.order):
        if e.kind in kinds:
            out[e.target.key] = e
    return out


def _event_fp(e) -> str | None:
    a = (e.target.anchor or {}).get("product_key") or {}
    return a.get("fingerprint")


def harvest_cutline(batch_id: str, events, cards: list[dict], dataset=None) -> dict:
    """切线事件 → touching-cuts 新条目（页面坐标口径，`source=L3-batch`）。不改旧条目、不覆盖同 id。"""
    from ..gold.item import Anchor, GoldItem
    from ..gold.store import GoldStore
    ds = dataset or GoldStore()
    by_id = {c["id"]: c for c in cards}
    evs = _latest(events, ("cutline",))
    existing = {i.id for i in ds.list(CUTLINE_SHARD)}
    items, rep = [], defaultdict(list)
    for key, e in evs.items():
        c = by_id.get(key)
        p = e.payload or {}
        if c is None:
            rep["not_in_batch"].append(key)
            continue
        if key in existing:
            rep["id_exists_kept_old"].append(key)
            continue
        verdict = p.get("verdict")
        if verdict is None or p.get("y") is None:
            rep["no_verdict"].append(key)
            continue
        pw = c["page_w"]
        exp = {k: p[k] for k in ("y", "y_old", "verdict", "bi", "slot_above", "slot_below", "col_h",
                                 "char_above", "char_below", "tags", "note", "polyline", "cand",
                                 "geom_sig", "page_x", "page_y", "page_polyline",
                                 "picked_source", "default_pick") if k in p}
        exp.setdefault("slot_above", c["slot_above"])
        exp.setdefault("slot_below", c["slot_below"])
        if p.get("page_x") is not None and p.get("page_y") is not None:
            # 控制台写的 page_x/page_y 是左上原点的原图像素；金标口径统一成右上原点
            exp["page_xy_space_legacy"] = "raw_page_px@top-left"
            exp["page_x_tr"] = round(pw - 1 - float(p["page_x"]), 2)
            exp["page_y"] = round(float(p["page_y"]), 2)
            exp["page_w"] = pw
            if p.get("page_polyline"):
                exp["page_polyline_tr"] = [[round(pw - 1 - x, 2), round(y, 2)] for x, y in p["page_polyline"]]
        elif verdict not in ("idk",):
            rep["no_page_coords"].append(key)       # 取不到几何：y 是列图坐标、没有页面锚——收但标 stale
        fp_click, fp_gen = _event_fp(e), (c.get("product_key") or {}).get("fingerprint")
        stale = "page_x_tr" not in exp and verdict != "idk"
        it = GoldItem(
            id=key,
            anchor=Anchor(book=c["book"], page=c["page"], col=c["col"], slot=c["slot_above"],
                          space=SPACE_TR, bbox=tuple(c["bbox"]) if c.get("bbox") else None,
                          product_key=c.get("product_key")),
            expected=exp,
            input={"source": SOURCE, "version": f"{SOURCE}:{batch_id}", "batch": batch_id,
                   "product_fp_at_generation": fp_gen, "product_fp_at_click": fp_click,
                   "fp_match": (fp_gen == fp_click) if (fp_gen and fp_click) else None,
                   "geom_sig_at_generation": c.get("geom_sig"),
                   "sampling": {"ctx": c["ctx"], "diff": c["diff"], "n_cand": c["n_cand"],
                                "dis_unet": c["dis_unet"], "agree": c["agree"], "chosen_kind": c["chosen_kind"],
                                "y_engine": c.get("y_engine")}},
            label_origin="human",
            pipeline_version=fp_gen,
            stratum=c["stratum"], stratum_weight=c["stratum_weight"],
            status="uncertain" if verdict in ("idk", "uncertain") else ("stale" if stale else "active"),
            source_events=[e.id])
        items.append(it)
    n_add = 0
    if items:
        n_add, _ = ds.upsert(CUTLINE_SHARD, items, why=f"{SOURCE} 收割 {batch_id}")
    return {"shard": CUTLINE_SHARD, "n_events": len(evs), "n_added": n_add,
            "n_cards": len(cards), "n_pending": len(cards) - len(evs),
            "skipped": {k: len(v) for k, v in rep.items()}, "skipped_ids": {k: v[:10] for k, v in rep.items()}}


def map_end_class(v: str | None) -> tuple[str | None, str | None]:
    """事件里的类别值 → (新类别, 旧值或 None)。

    `clean` 是旧体系独有的值（→ trim）；`none`/`glued`/`idk` 新旧同名同义；`trim`/`double` 是新值。
    认不出 → (None, v)，调用方计入「不认识」，不猜。
    """
    if v == "clean":
        return LEGACY_END_MAP["clean"], "clean"
    if v in END_CLASSES:
        return v, None
    return None, v


def harvest_column_end(batch_id: str, events, cards: list[dict], dataset=None) -> dict:
    """`border_class` 事件 → column-end-class 条目。旧批事件里的 clean 按 `LEGACY_END_MAP` 映射成 trim。"""
    from ..gold.item import Anchor, GoldItem
    from ..gold.store import GoldStore
    ds = dataset or GoldStore()
    by_id = {c["id"]: c for c in cards}
    evs = _latest(events, ("border_class",))
    existing = {i.id for i in ds.list(COLEND_SHARD)}
    items, rep = [], defaultdict(list)
    for key, e in evs.items():
        c = by_id.get(key)
        if c is None:
            rep["not_in_batch"].append(key)
            continue
        p = e.payload or {}
        raw = p.get("border_class") or p.get("verdict")
        cls, legacy = map_end_class(raw)
        if cls is None:
            rep["unknown_class"].append(f"{key}={raw}")
            continue
        iid = f"{c['book']}:{c['page']}:{c['col']}:{c['end']}"
        if iid in existing:
            rep["id_exists_kept_old"].append(iid)
            continue
        fp_click, fp_gen = _event_fp(e), (c.get("product_key") or {}).get("fingerprint")
        exp = {"class": cls, "end": c["end"], "engine_trim_case": c["trim_case"], "engine_trim_px": c["trim_px"],
               "engine_end_class": c["end_class"]}
        if legacy:
            exp["legacy_class"] = legacy
        it = GoldItem(
            id=iid,
            anchor=Anchor(book=c["book"], page=c["page"], col=c["col"], space=SPACE_TR,
                          bbox=tuple(c["bbox"]) if c.get("bbox") else None, product_key=c.get("product_key")),
            expected=exp,
            input={"source": SOURCE, "version": f"{SOURCE}:{batch_id}", "batch": batch_id,
                   "end_fingerprint": c["end_fingerprint"], "geom_sig": c.get("geom_sig"),
                   "product_fp_at_generation": fp_gen, "product_fp_at_click": fp_click,
                   "fp_match": (fp_gen == fp_click) if (fp_gen and fp_click) else None},
            label_origin="human", pipeline_version=fp_gen,
            stratum=c["stratum"], stratum_weight=c["stratum_weight"],
            status="uncertain" if cls == "idk" else "active", source_events=[e.id])
        items.append(it)
    n_add = 0
    if items:
        n_add, _ = ds.upsert(COLEND_SHARD, items, why=f"{SOURCE} 收割 {batch_id}")
    return {"shard": COLEND_SHARD, "n_events": len(evs), "n_added": n_add, "n_cards": len(cards),
            "n_pending": len(cards) - len(evs),
            "skipped": {k: len(v) for k, v in rep.items()}, "skipped_ids": {k: v[:10] for k, v in rep.items()}}


def harvest_batch(batch_id: str, dataset=None, log=None, batches_root: Path | None = None) -> dict:
    """按批次登记的 kind 分流。事件来自 EventLog（控制台已写入）。"""
    from ..feedback.events import EventLog
    from .batches import BatchStore
    b = BatchStore(batches_root).get(batch_id)
    if b is None:
        raise FileNotFoundError(f"没有批次 {batch_id}")
    cards = read_cards(batch_id, batches_root)
    events = (log or EventLog()).read(batch_id)
    if not events:
        raise FileNotFoundError(f"批次 {batch_id} 还没有任何裁决事件（控制台里点完卡再收割；"
                                "事件在 `feedback/events/<批次>.jsonl`，本机与云端的工作区不是同一份）")
    if b.kind == "cutline":
        out = harvest_cutline(batch_id, events, cards, dataset)
    elif b.kind == "border_class":
        out = harvest_column_end(batch_id, events, cards, dataset)
    else:
        raise ValueError(f"批次 {batch_id} 的 kind={b.kind} 不是 L3 两批之一")
    b.status, b.harvested_at, b.n_events = "harvested", time.time(), out["n_events"]
    BatchStore(batches_root).save(b)
    return out


# ═══ 旧 overview 104 张列端卡 → 新分片 ═══════════════════════════════

def migrate_legacy_overview(verdicts_jsonl: Path, book: str = "vol02", dataset=None,
                            cv_version: str = "92e75e3") -> dict:
    """overview `inbox/S-列尾抽查页/20260927-verdicts.jsonl`（104 条）里的**列端卡**（t=列尾 59 / h=列首 15，共 74 端）迁进新分片。

    ⚠️ 旧卡问的不是新分片的问题：旧卡展示的是**削完之后**的新旧两版，问「这一端干净/还有框线残留/
    字被切掉」（`clean`/`residual`/`cut<N>`），是**削后状态**，不是**削前的版框类别**。
    无法无损映射成 none/trim/glued/double，所以 `class` 一律记 `idk`，原值存 `expected.legacy_verdict`，
    并给 `legacy_hint`（只是提示、不进评测）。`bar_ok_char` 是 `l` 前缀的末字块卡（30 张，问的是
    字块上挂的横线，不是列端），**不迁**。
    """
    from ..gold.item import Anchor, GoldItem
    from ..gold.store import GoldStore
    import re
    ds = dataset or GoldStore()
    hint = {"clean": "削后干净：框当时可削（≈trim 或 none），削前类别未知",
            "residual": "削后仍有框线残留：≈glued/double/无法整段削，削前类别未知"}
    items, skipped = [], defaultdict(int)
    existing = {i.id for i in ds.list(COLEND_SHARD)}
    for ln in Path(verdicts_jsonl).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        m = re.match(r"^([thl])(\d+)_p(\d+)c(\d+)$", d["id"])
        if not m:
            skipped["bad_id"] += 1
            continue
        kind, _idx, page, col = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        if kind == "l":
            skipped["char_block_card_not_end"] += 1
            continue
        end = "bot" if kind == "t" else "top"
        iid = f"{book}:{page}:{col}:{end}"
        if iid in existing:
            skipped["id_exists"] += 1
            continue
        v = str(d["verdict"])
        items.append(GoldItem(
            id=iid, anchor=Anchor(book=book, page=page, col=col),
            expected={"class": "idk", "end": end, "legacy_verdict": v,
                      "legacy_hint": hint.get(v, "削后字被切掉/其它：削前类别未知"),
                      "legacy_card": d["id"], "legacy_question": "削后状态（干净/残留/切字），非削前类别"},
            input={"source": "legacy-overview", "version": f"legacy-overview:cv@{cv_version}",
                   "origin": "overview inbox/S-列尾抽查页/20260927-verdicts.jsonl",
                   "note": "无图像指纹、无产物指纹、无页面坐标锚（旧页只有卡片 id）；不得进评测，只作线索"},
            label_origin="human", status="uncertain"))
    n = 0
    if items:
        n, _ = ds.upsert(COLEND_SHARD, items, why="legacy-overview 迁入")
    return {"shard": COLEND_SHARD, "n_added": n, "skipped": dict(skipped)}
