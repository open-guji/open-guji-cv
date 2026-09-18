# -*- coding: utf-8 -*-
"""度量损失实验的数据层：**留出字种**（held-out class）切分。

## 为什么要留出字种，而不是用现成的 unseen

`cache/glyph_bench` 的 unseen 档禁的是「该字的**本书刻例**」，但字种本身
**在 4,654 类表里**——分类头见过它（靠字体渲染），embedding 也见过它的模板。
所以那个集**量不出类外泛化**（overview 06 卡坑 2 的原话）。

本实验把一批字**整体从类表里挖掉**：
- 类表 = (四庫字表 ∪ bench 字种) − HELDOUT
- 这批字的任何图（真刻例 / 字体渲染 / 康熙 / 字统网）都不进训练
- 评测时它们当查询，模板库是**同样留出的**康熙/字统网图（另一张）

这才是「换一本书，遇到类表外生僻字」的真实处境。

## 数据源规模（2026-09-17 实测）

| 源 | 图数 | 字种 | 类表外字种 |
|---|---|---|---|
| 康熙自切（crossval pass 白名单） | 13,707 | 13,418 | 10,285 |
| 字统网 p1+p2（排除「當代」） | 322,538 | 36,675 | 32,091 |
| 四庫真刻例（siku glyph.db） | 17,377 | 2,604 | 25 |
| 北行日錄真刻例 | 20,683 | 2,018 | 282 |
| 北行刻本真刻例 | 4,128 | 1,164 | 106 |

**四庫真刻例只有 25 个类表外字种**——它的字表**就是**类表的来源，
所以真刻例这条路天花板极低。规模在康熙/字统网（合计三万+类表外字种）。
"""
from __future__ import annotations

import collections
import hashlib
import json
import random
import sqlite3
import sys
import unicodedata
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

KANGXI_DIR = Path("D:/data/glyph-sources/kangxi/crops")
KANGXI_CROSSVAL = Path("D:/data/glyph-sources/kangxi/crossval/report.tsv")
ZITOOLS_DIRS = [Path("D:/data/glyph-sources/zitools/p1"),
                Path("D:/data/glyph-sources/zitools/p2")]
WORKSPACES = {
    "siku": Path("D:/workspace/siku-zongmu-workspace/output/glyph.db"),
    "bxrl": Path("D:/workspace/beixingrilu-workspace/output/glyph.db"),
    "bxgb": Path("D:/workspace/beixing-guben-workspace/output/glyph.db"),
}
REAL_STATUS = ("align", "context", "human", "match")
CACHE = Path("experiments/metric_loss/out/cache")
SIZE = 64


def is_han(ch: str) -> bool:
    if len(ch) != 1:
        return False
    try:
        return unicodedata.category(ch) == "Lo"
    except Exception:  # noqa: BLE001
        return False


# ── 源：康熙自切（只取 crossval pass 白名单） ─────────────────────
def kangxi_pass_files() -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = collections.defaultdict(list)
    with open(KANGXI_CROSSVAL, encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6 or p[5] != "pass":
                continue
            ch, fn = p[0], p[1]
            if not is_han(ch):
                continue
            out[ch].append(KANGXI_DIR / fn)
    return dict(out)


# ── 源：字统网（排除「當代」= 现代字体，那是字体不是刻本） ─────────
def zitools_files(styles: set[str] | None = None) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = collections.defaultdict(list)
    for d in ZITOOLS_DIRS:
        man = d / "manifest.tsv"
        if not man.exists():
            continue
        with open(man, encoding="utf-8") as f:
            next(f)
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) < 8 or p[7].startswith("rows="):
                    continue
                gch, dyn, style, rel = p[1], p[2], p[3], p[7]
                if dyn == "當代" or not is_han(gch):
                    continue
                if styles and style not in styles:
                    continue
                out[gch].append(d / rel)
    return dict(out)


# ── 源：真刻例（三本书的 glyph.db） ────────────────────────────────
def real_instances() -> dict[str, list[tuple[str, bytes]]]:
    """{字: [(来源, patch_png bytes), ...]}，只取非 rendered 的标签。"""
    out: dict[str, list[tuple[str, bytes]]] = collections.defaultdict(list)
    ph = ",".join("?" * len(REAL_STATUS))
    for name, db in WORKSPACES.items():
        if not db.exists():
            continue
        c = sqlite3.connect(f"{db}")
        q = (f"select label, patch_png from instances where label is not null and label!='' "
             f"and patch_png is not null and label_status in ({ph})")
        for lab, png in c.execute(q, REAL_STATUS):
            if is_han(lab):
                out[lab].append((name, png))
        c.close()
    return dict(out)


# ── 归一化 ───────────────────────────────────────────────────────
def norm_file(p: Path, size: int = SIZE) -> np.ndarray | None:
    from open_guji_cv.clustering.normalize import normalize_patch
    try:
        buf = np.fromfile(str(p), dtype=np.uint8)
    except OSError:
        return None
    img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE) if buf.size else None
    if img is None or img.size == 0:
        return None
    try:
        n = normalize_patch(img, size=size)
    except Exception:  # noqa: BLE001
        return None
    return n.astype(np.uint8) if n.any() else None


def norm_png_bytes(b: bytes, size: int = SIZE) -> np.ndarray | None:
    from open_guji_cv.clustering.normalize import normalize_patch
    img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or img.size == 0:
        return None
    try:
        n = normalize_patch(img, size=size)
    except Exception:  # noqa: BLE001
        return None
    return n.astype(np.uint8) if n.any() else None


# ── 切分 ─────────────────────────────────────────────────────────
def base_classes() -> list[str]:
    """现役类表：四庫字表 ∪ bench 字种（= r4 的 4,654 类）。"""
    from open_guji_cv.clustering.font_candidates import book_charset
    from open_guji_cv.core.workspace import corpus_path
    bc = set(book_charset(str(corpus_path("zongmu_wuyingdian_reference.txt"))))
    items = [json.loads(l) for l in
             open("cache/glyph_bench/items.jsonl", encoding="utf-8")]
    return sorted(bc | {i["char"] for i in items})


def build_split(n_heldout: int = 1200, seed: int = 20260917,
                min_imgs: int = 2) -> dict:
    """挑 n_heldout 个「类表外 + 外部源有 ≥min_imgs 张」的字当留出类。

    注意：留出字取自**类表外**（本来就不在 4,654 里），所以「挖掉」这件事
    对类表没影响——类表仍是 4,654。这样基线就是现役 r4 的配置，
    改的只有损失函数，delta 干净。

    这批字对模型是彻底的陌生字：不在类表、任何图都不进训练。
    """
    rng = random.Random(seed)
    cls = set(base_classes())
    kx = kangxi_pass_files()
    zt = zitools_files()
    pool = {}
    for ch in set(kx) | set(zt):
        if ch in cls:
            continue
        n = len(kx.get(ch, [])) + len(zt.get(ch, []))
        if n >= min_imgs:
            pool[ch] = n
    chars = sorted(pool)
    rng.shuffle(chars)
    held = sorted(chars[:n_heldout])
    return {"classes": sorted(cls), "heldout": held,
            "pool_size": len(pool), "seed": seed}


def _cache_key(*parts) -> Path:
    h = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]
    return CACHE / f"{h}.npz"


#: 模板与 query 只用「同书写体系」的字体档。
#: 2026-09-17 踩过的坑：第一版模板回落到 `篆/甲骨/金`（篆书、甲骨文、金文），
#: 于是「印刷体 query × 甲骨文模板」——那测的是**跨书体识别**，
#: 不是类外泛化，基线被压到 34.7%。刻本下游只会遇到印刷体/楷书，
#: 所以两侧一律限定 印/楷（必要时加 隸/行）。
PRINT_STYLES = {"印", "楷"}


def load_heldout_eval(held: list[str], max_per_char: int = 12,
                      seed: int = 0, styles: set[str] | None = None) -> dict:
    """留出字的评测数据：每字的图分成 query / template 两半。

    query 优先用真刻例（最像下游场景）；没有真刻例的字用外部源的图，
    但 **query 与 template 绝不同源同图**：
    - 有康熙图：康熙当 query（自切、原分辨率、最接近真刻），字统网当 template
    - 无康熙图：字统网内部切两半（同为 印/楷，随机分，互不重叠）

    一个字若凑不出「query + 至少一张不同图的 template」就整字丢掉——
    宁可集合小一点，也不要拿同一张图两边都用（那会把检索变成恒等匹配）。
    """
    styles = styles or PRINT_STYLES
    key = _cache_key("heldout_eval_v2", len(held), max_per_char, seed,
                     ",".join(sorted(styles)),
                     hashlib.sha1("".join(held).encode()).hexdigest()[:12])
    if key.exists():
        z = np.load(key, allow_pickle=True)
        return {"q_imgs": z["q_imgs"], "q_chars": z["q_chars"].tolist(),
                "t_imgs": z["t_imgs"], "t_chars": z["t_chars"].tolist(),
                "q_src": z["q_src"].tolist()}
    hs = set(held)
    kx = {c: v for c, v in kangxi_pass_files().items() if c in hs}
    zt = {c: v for c, v in zitools_files(styles).items() if c in hs}
    real = {c: v for c, v in real_instances().items() if c in hs}
    rng = random.Random(seed)

    q_imgs, q_chars, q_src, t_imgs, t_chars = [], [], [], [], []
    for ch in held:
        zlist = list(zt.get(ch, []))
        rng.shuffle(zlist)
        # --- query
        qs: list[tuple[str, np.ndarray]] = []
        for _src, png in real.get(ch, [])[:max_per_char]:
            im = norm_png_bytes(png)
            if im is not None:
                qs.append(("real", im))
        if not qs:
            for p in kx.get(ch, [])[:max_per_char]:
                im = norm_file(p)
                if im is not None:
                    qs.append(("kangxi", im))
        n_used = 0
        if not qs:
            # 字统网内部对半分：要留至少一张给模板，所以最多拿一半
            take = max(1, len(zlist) // 2)
            for p in zlist[:take]:
                im = norm_file(p)
                n_used += 1
                if im is not None:
                    qs.append(("zitools", im))
            if not qs:
                continue
        if not qs:
            continue
        # --- template（与 query 不同图；印/楷 档内）
        ts: list[np.ndarray] = []
        for p in zlist[n_used:]:
            im = norm_file(p)
            if im is not None:
                ts.append(im)
            if len(ts) >= max_per_char:
                break
        if not ts and qs[0][0] != "kangxi":
            for p in kx.get(ch, [])[:max_per_char]:
                im = norm_file(p)
                if im is not None:
                    ts.append(im)
        if not ts:
            continue
        for s, im in qs:
            q_imgs.append(im); q_chars.append(ch); q_src.append(s)
        for im in ts:
            t_imgs.append(im); t_chars.append(ch)
    out = {"q_imgs": np.stack(q_imgs), "q_chars": q_chars,
           "t_imgs": np.stack(t_imgs), "t_chars": t_chars, "q_src": q_src}
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(key, q_imgs=out["q_imgs"], q_chars=np.array(q_chars),
                        t_imgs=out["t_imgs"], t_chars=np.array(t_chars),
                        q_src=np.array(q_src))
    return out


if __name__ == "__main__":
    sp = build_split()
    print("pool(类表外 & 外部源>=2张):", sp["pool_size"])
    print("heldout:", len(sp["heldout"]), "".join(sp["heldout"][:40]))
    ev = load_heldout_eval(sp["heldout"])
    print("query", ev["q_imgs"].shape, "字种", len(set(ev["q_chars"])))
    print("template", ev["t_imgs"].shape, "字种", len(set(ev["t_chars"])))
    print("q_src:", collections.Counter(ev["q_src"]).most_common())
