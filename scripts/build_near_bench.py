"""冻结 3b 形近字组整体 benchmark 的一册（CV3，2026-11-28；方案稿 ai-team domain/CV/A24/形近字组整体方案 第八、十一节 D）。

## 为什么要

3b `glyph_near` 各方法（cnn_small、rr_shape、wu_shape、hou_shape、part_shape、pair_shape、book_knn、near_knn、stroke_veto）
只吃「3a 的候选＋字块图」，评测不必整册重跑：这里把一册的 3a 记录、标签、被触发格的字块图冻住，
`scripts/eval_near.py` 只读冻结的东西，几分钟跑完（触发量、覆盖率、方法间一致率、准确率／弃权率、ECE、耗时、指纹），
并能按册留出拟合临时校准表。

## 冻什么（`<shard>/<书>/<册>/`）

- `cells.jsonl.gz`：这一册**每一格**一行（不只触发的格，覆盖率与触发量要分母）：
  `{id, page, col, slot, sub, patch_key, a: {char, verdict, guard, cands: [[字, 分]…]}, label, img}`
  - `a`：产物包里 3a `glyph_match` 的首位、判档、护栏、全部候选（触发只看这些）；
  - `label`：`{char, channel, gold, src}`。`char`＝第四步 `seed_admit` 放行字（`admit` 为真才有），`channel` 是放行通道；
    `gold`＝人裁（放行通道 `human`，或 `--gold` 给的外部人裁表按格 id 对上，`src` 记来源）。没放行的格 `label` 为 null；
  - `img`：`{p: 字块图文件, r: 原图裁块文件}`，只有被 bench 配置里某组触发（`_guard` 的 `gap` 一路除外，量太大，
    只数不判）的格才有；`p`＝`char_patch`（rr_shape 等吃的），`r`＝原图按 `bbox_page` 裁的灰度块（cnn_small 吃的，只给挂了
    `patch: raw` 方法的组的格出）。
- `img/`：上面引用的 PNG（灰度，原样）。
- `meta.json`：包标签、cv 版本（出图用的）、页数、格数、触发数、标签统计。

## 纪律

- 包标签钉死：`bench.json` 里 `books.<书>.vols.<册>.pack`，工作区产物根里这册的 `.pack.json` 标签对不上就拒（先
  `guji products pack fetch <册> --label <标签> --to <产物根>`）。
- 字块图走 `RunContext.image("char_patch", …)`（缓存没有就按产物现算，要原图与书级代码），与管线读的同一张。
- 标签泄漏：产物包里的 3a 是人裁入库后现跑的（候选字线 11-27 的坑）——这里 3a 只拿来**触发**，不拿来评 3a 本身；
  book_knn／near_knn 的刻例库是本书已放行格建的、刻形模型按册训的，册在训练集里的方法准确率偏乐观（`bench.json`
  每个模型写了训练册，`eval_near` 报告里照抄）。

用法（`GUJI_WORKSPACE` 指书的工作区：册配置、产物根、原图、书级代码都要在；`GUJI_DATA_HOME` 指拉过中心库的数据目录）：

    PYTHONPATH=. python scripts/build_near_bench.py <shard> --book 995ejelvk0 --vol 046 [--gold unified.jsonl]
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def cv_version() -> str:
    """cv 的版本（装了包就取包版本，再接仓里 HEAD 短哈希）。"""
    import subprocess
    from importlib.metadata import PackageNotFoundError, version
    try:
        v = version("open-guji-cv")
    except PackageNotFoundError:
        v = "?"
    try:
        h = subprocess.run(["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10, check=False).stdout.strip()
    except Exception:  # noqa: BLE001
        h = ""
    return f"{v}+{h}" if h else v


def bench_groups(spec: dict, vol: str) -> dict:
    """bench.json 里这本书的 `groups`（3b 书配置写法）→ 按登记表展开 `ref`、守 `handling.methods` 后的组（同 `glyph_near.book_params`）。"""
    from open_guji_cv.groups.near_registry import resolve
    g, _skipped = resolve(dict(spec.get("groups") or {}), vol)
    return g


def load_gold(path: str | None, vol: str) -> dict:
    """外部人裁表（如 dataset `char-groups/labels/unified.jsonl`：`kind=shape`、`status=ok` 的 `form`）→ {格 id: (字, 来源)}。"""
    if not path:
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    for r in rows:
        if r.get("kind") != "shape" or r.get("status") != "ok" or not r.get("form"):
            continue
        if not str(r.get("id", "")).startswith(f"{vol}:"):
            continue
        out[r["id"]] = (r["form"], f"{Path(path).name}:{r.get('src', '')}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shard")
    ap.add_argument("--book", required=True, help="bench.json 里 books 的键（书 ID）")
    ap.add_argument("--vol", required=True)
    ap.add_argument("--gold", help="外部人裁表 jsonl（unified.jsonl 格式），按格 id 对")
    ap.add_argument("--pages", help="只冻这些页（调试用，逗号分隔）")
    ap.add_argument("--meta-only", action="store_true", help="只按已冻的 cells.jsonl.gz 重写 meta.json")
    a = ap.parse_args()

    from open_guji_cv.core.anchor import crop_patch
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.core.workspace import products_root
    from open_guji_cv.groups.near_methods import METHODS, parse_spec
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.steps.glyph_near import (
        GUARD_GROUP,
        cell_patch_key,
        trigger_groups,
    )

    shard = Path(a.shard)
    bench = json.loads((shard / "bench.json").read_text(encoding="utf-8"))
    bspec = bench["books"][a.book]
    vspec = bspec["vols"][a.vol]
    mark = products_root() / a.vol / ".pack.json"
    got = json.loads(mark.read_text(encoding="utf-8")).get("label") if mark.is_file() else None
    if got != vspec["pack"]:
        raise SystemExit(f"{a.vol} 产物包标签 {got!r} ≠ bench.json 钉的 {vspec['pack']!r}（{mark}）")

    groups = bench_groups(bspec, a.vol)
    raw_groups = set()
    for gid, g in groups.items():
        for name, sp in (g.get("methods") or {}).items():
            if getattr(METHODS[name], "patch", "raw") == "raw":
                raw_groups.add(gid)
            parse_spec(sp)

    out = shard / a.book / a.vol
    if a.meta_only:
        with gzip.open(out / "cells.jsonl.gz", "rt", encoding="utf-8") as f:
            rows = [json.loads(x) for x in f]
        write_meta(out, a, vspec, groups, sorted({r["page"] for r in rows}), rows,
                   sum(1 for r in rows if r.get("img")), sum(1 for r in rows if (r.get("img") or {}).get("p_error")))
        return
    bk = load_book(a.vol)
    store, cache = ProductStore(), ImageCache()
    ctx = RunContext(bk, store, cache)
    gold = load_gold(a.gold, a.vol)
    (out / "img").mkdir(parents=True, exist_ok=True)
    pages = [int(x) for x in a.pages.split(",")] if a.pages else bk.all_pages()
    rows, n_trig, n_img, n_miss = [], 0, 0, 0
    t0 = time.time()
    for pg in pages:
        pk = page_key(pg)
        match = store.read(a.vol, "glyph_match", pk, "glyph_match")
        chars = store.read(a.vol, "cell_shrink", pk, "char_index")
        if match is None or chars is None:
            continue
        admit = store.read(a.vol, "seed_admit", pk, "seed_admit")
        adm = {r.id: r for cc in (admit.columns if admit is not None else []) for r in cc.chars}
        crec = {r.id: r for cc in chars.columns for r in cc.chars}
        raw = None
        for cm in match.columns:
            for r in cm.chars:
                c = crec.get(r.id)
                if c is None or c.bbox_page is None:
                    continue
                key = c.patch_key or cell_patch_key(pg, cm.col, r.slot, r.sub)
                ad = adm.get(r.id)
                label = None
                if ad is not None and ad.admit and ad.char:
                    label = {"char": ad.char, "channel": ad.channel, "gold": ad.channel == "human",
                             "src": "seed_admit:human" if ad.channel == "human" else "seed_admit"}
                    if ad.channel == "human":
                        label["gold_char"] = ad.char
                if r.id in gold:
                    gch, gsrc = gold[r.id]
                    label = {**(label or {"char": None, "channel": None}), "gold_char": gch, "gold": True, "src": gsrc}
                rec = {"id": r.id, "page": pg, "col": cm.col, "slot": r.slot, "sub": r.sub, "patch_key": key,
                       "a": {"char": r.char, "verdict": r.verdict, "guard": r.guard,
                             "cands": [[str(ch), round(float(s), 4)] for ch, s in (r.candidates or [])]},
                       "label": label}
                ns = SimpleNamespace(guard=r.guard, verdict=r.verdict)
                hit = [(g, how) for g, how in trigger_groups(r.candidates, r.char, groups, ns)
                       if not (g == GUARD_GROUP and how == "gap")]
                if hit:
                    n_trig += 1
                    img = {}
                    try:
                        p = ctx.image("char_patch", key)
                        cv2.imwrite(str(out / "img" / f"{key}.p.png"), p)
                        img["p"] = f"img/{key}.p.png"
                    except Exception as e:  # noqa: BLE001 —— 记下来，评测按 patch_missing 数
                        img["p_error"] = f"{type(e).__name__}: {str(e)[:160]}"
                        n_miss += 1
                    if any(g in raw_groups for g, _ in hit):
                        if raw is None:
                            raw = ctx.raw_page(pg)
                        rp = crop_patch(raw, c.bbox_page)
                        if rp is not None and rp.size:
                            cv2.imwrite(str(out / "img" / f"{key}.r.png"), rp)
                            img["r"] = f"img/{key}.r.png"
                    rec["img"] = img
                    n_img += 1
                rows.append(rec)
        print(f"  {pk}: 累计 {len(rows)} 格，触发 {n_trig}（{time.time() - t0:.0f}s）", flush=True)
    with gzip.open(out / "cells.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    write_meta(out, a, vspec, groups, pages, rows, n_trig, n_miss)


def write_meta(out: Path, a, vspec: dict, groups: dict, pages: list, rows: list, n_trig: int, n_miss: int) -> None:
    lab = [r["label"] for r in rows if r["label"]]
    meta = {"book": a.book, "vol": a.vol, "pack": vspec["pack"], "render_cv": cv_version(),
            "pages": len(pages), "cells": len(rows), "triggered_frozen": n_trig, "patch_missing": n_miss,
            "labels": {"admit": sum(1 for x in lab if x.get("char")), "gold": sum(1 for x in lab if x.get("gold"))},
            "groups": sorted(groups), "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
