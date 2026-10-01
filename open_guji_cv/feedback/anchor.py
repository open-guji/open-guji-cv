# -*- coding: utf-8 -*-
"""人裁的「锚」：裁决时这一格在原图上的位置 + 那块字块图，让裁决在重切之后还认得出是哪个字。

设计见 overview `进度/总览/15-人裁锚定与重切后重绑定.md`。

## 为什么需要

人裁按字位编号 `book:page:col:slot[a|b]` 记。编号是 Step3 切分的**输出**，不是字的身份：
列内多切或少切一格，这一处以下整列顺移一位，编号就指向了相邻的另一个字（vol02 2026-09-25 实测
约 220 / 1,417 条挂错或失效，一部分已被当人裁写进文本）。锚记下「当时看的是原图上哪块、长什么样」，
`bindings.py` 据此在重切后把裁决找回到现在对应的格。

## 锚的内容（写进 `EventTarget.anchor`，字段早就有、此前一直是空的）

| 键 | 含义 |
|---|---|
| `v` | 锚格式版本 |
| `space` | 坐标系：`raw_page_px@top-right`（原始扫描页像素，右上原点——与 `CellRec.quad_page` 同一套） |
| `bbox` | 这一格在原图上的外接框 `[x0, y0, x1, y1]`（取自 Step3 `quad_page`；原图不变，重切前后可比） |
| `quad` | 原样的四角，备查 |
| `content_sha` | 当时字块图（Step4 `char_patch`）的 sha1；图本身按内容存 `feedback/anchor_patches/<book>/` |
| `ctx` | 当时本页读序里前后各 2 个字（`[前, 后]`），辅助判断整列错位 |
| `product_key` | 当时 Step3 产物的 sha256（知道这条裁决是按哪一版切分做的） |
| `source` | `live`（裁决当时取的）或 `backfill:<来源>`（老裁决事后补的，见 `bindings.py`） |
| `evidence` | **人当时看到的图的凭证**（2026-10-01，D2/#323）：`fp`（`gold/drift.fingerprint` 口径的图像指纹）+ `fp_size` + `fp_of`（`char_patch`/`column_image`）+ `step`/`key`/`sha256`/`params_hash`/`manifest_fp`（当时产物版本）。见 `evidence_for`；`bindings.py` 判「还挂得上吗」时优先比它 |

`evidence` 与其余键**互相独立、可单独存在**：旧事件没有它照常可读；`enrich_events` 对已有锚（如控制台
`_product_anchor` 写的只含 `product_key` 的锚）**合并补键、不覆盖已有键**。
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

ANCHOR_VERSION = 1
SPACE = "raw_page_px@top-right"
_KEY = re.compile(r"^(?P<book>[^:]+):(?P<page>\d+):(?P<col>\d+):(?P<slot>-?\d+)(?P<sub>[ab]?)$")


def parse_cell_key(key: str) -> tuple[str, int, int, int, str] | None:
    m = _KEY.match(key or "")
    if not m:
        return None
    return m["book"], int(m["page"]), int(m["col"]), int(m["slot"]), m["sub"]


def patch_key(page: int, col: int, slot: int, sub: str = "") -> str:
    return f"p{page:04d}c{col:02d}s{slot}{sub}"


def quad_bbox(quad) -> list[float] | None:
    if not quad:
        return None
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return [min(xs), min(ys), max(xs), max(ys)]


def patches_root() -> Path:
    from ..core.workspace import feedback_root
    return feedback_root() / "anchor_patches"


def store_patch(book: str, src: Path) -> str:
    """字块图按内容存一份（裁决后图块缓存会被重切覆盖，锚要自带当时那张）→ sha1。"""
    data = Path(src).read_bytes()
    sha = hashlib.sha1(data).hexdigest()
    dst = patches_root() / book / sha[:2] / f"{sha}.png"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return sha


def patch_path(book: str, sha: str) -> Path:
    return patches_root() / book / sha[:2] / f"{sha}.png"


def cell_anchor(key: str, store=None, cache=None, with_ctx: bool = True) -> dict | None:
    """按**当前**产物给一格造锚；这一格不存在/没有几何 → None（不报错：锚是附加信息）。"""
    from ..core.spec import page_key
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    from ..report.slots import CELLS_KIND, cells_step
    pk = parse_cell_key(key)
    if pk is None:
        return None
    book, page, col, slot, sub = pk
    store = store or ProductStore()
    step = cells_step(book)
    try:
        cells = store.read(book, step, page_key(page), CELLS_KIND)
    except Exception:
        return None
    if cells is None:
        return None
    cell = next((c for cc in cells.columns if cc.col == col for c in cc.cells
                 if c.slot == slot and (c.sub or "") == sub), None)
    if cell is None or not cell.quad_page:
        return None
    a = {"v": ANCHOR_VERSION, "space": SPACE, "quad": [list(map(float, p)) for p in cell.quad_page],
         "bbox": quad_bbox(cell.quad_page), "source": "live",
         "product_key": {step: store.sha(book, step, page_key(page))}}
    path = (cache or ImageCache()).get(book, "char_patch", patch_key(page, col, slot, sub))
    if path is not None:
        try:
            a["content_sha"] = store_patch(book, path)
        except OSError:
            pass
    if with_ctx:
        try:
            from ..report.slots import page_slots
            seq = [s for s in page_slots(store, book, page) if s.is_text]
            i = next(k for k, s in enumerate(seq) if s.id == key)
            t = lambda xs: "".join((s.char or "□") for s in xs)  # noqa: E731
            a["ctx"] = [t(seq[max(0, i - 2):i]), t(seq[i + 1:i + 3])]
        except Exception:
            pass
    return a


EVIDENCE_VERSION = 1
CUTLINE_FP_HALF = 64       # 切线凭证：以切线为中心上下各取这么多行的列图（整列宽）


def _manifest_evidence(store, book: str, step: str, key: str) -> dict:
    """当时这一页产物是哪一版：step + key + 产物 sha256 + params_hash + manifest 指纹。取不到的键留空。"""
    out: dict = {"step": step, "key": key}
    try:
        ent = store.manifest(book, step).get(key)
    except Exception:
        ent = None
    if ent is not None:
        for src, dst in (("sha256", "sha256"), ("params_hash", "params_hash"),
                         ("fingerprint", "manifest_fp")):
            v = getattr(ent, src, None)
            if v:
                out[dst] = v
    return out


def _gray_fp(path: Path, size) -> str | None:
    import cv2
    from ..gold.drift import fingerprint
    from ..utils.image_io import imread
    img = imread(str(path), cv2.IMREAD_GRAYSCALE)
    return None if img is None else fingerprint(img, size)


def evidence_for(event, store=None, cache=None) -> dict | None:
    """这条事件**当前**能拿到的凭证；无从取（既不是逐格也不是切线、产物/图都没有）→ None。

    - 逐格（`unit=cell` 且 key 是格键）：`char_patch` 的指纹 + 产物版本（Step3 cells 步）；
    - `cutline`（有 page/col、payload.y）：列图 `column_image` 里切线上下 `CUTLINE_FP_HALF` 行的指纹
      + `column_warp` 产物版本。人拖线时看的正是这一段。
    指纹口径复用 `gold/drift.py::fingerprint`（`FP_SIZE`），`fp_size` 随凭证存、比的时候照它的来。
    """
    from ..core.spec import column_key, page_key
    from ..gold.drift import FP_SIZE
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    t = event.target
    ev: dict | None = None
    is_cutline = event.kind == "cutline"      # 切线与字位裁决 key 形状相同、unit 不同：先认 kind
    if not is_cutline and t.unit == "cell" and parse_cell_key(t.key) is not None:
        book, page, col, slot, sub = parse_cell_key(t.key)
        from ..report.slots import cells_step
        store = store or ProductStore()
        ev = _manifest_evidence(store, book, cells_step(book), page_key(page))
        path = (cache or ImageCache()).get(book, "char_patch", patch_key(page, col, slot, sub))
        if path is not None:
            fp = _gray_fp(path, FP_SIZE)
            if fp:
                ev.update(fp=fp, fp_size=list(FP_SIZE), fp_of="char_patch")
    elif is_cutline and t.page is not None and t.col is not None \
            and (event.payload or {}).get("y") is not None:
        import cv2
        from ..gold.drift import fingerprint
        from ..utils.image_io import imread
        book = t.book or ""
        store = store or ProductStore()
        ev = _manifest_evidence(store, book, "column_warp", page_key(t.page))
        path = (cache or ImageCache()).get(book, "column_image", column_key(t.page, t.col))
        img = None if path is None else imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            y = int(round(float(event.payload["y"])))
            seg = img[max(0, y - CUTLINE_FP_HALF):y + CUTLINE_FP_HALF]
            if seg.size:
                ev.update(fp=fingerprint(seg, FP_SIZE), fp_size=list(FP_SIZE), fp_of="column_image",
                          y0=max(0, y - CUTLINE_FP_HALF))
    if not ev or len(ev) <= 2 and "fp" not in ev:
        return None                      # 只剩 step/key 两个空壳：不如不写
    ev["v"] = EVIDENCE_VERSION
    return ev


def enrich_events(events, store=None, cache=None) -> int:
    """给逐格/切线事件补锚与凭证（写事件日志之前调）。→ 补上了东西的事件数。失败的留空，不拦写入。

    已有锚**合并补键、不覆盖**：控制台写入口先放的 `product_key` 锚（只有产物指纹、没有框与图）
    原先会让这里整条跳过，于是线上事件的 bbox/content_sha 一直是空的（2026-10-01 修）。
    """
    n = 0
    for e in events:
        t = e.target
        a = dict(t.anchor or {})
        before = set(a)
        if t.unit == "cell" and parse_cell_key(t.key) is not None and not a.get("bbox"):
            try:
                live = cell_anchor(t.key, store=store, cache=cache)
            except Exception:
                live = None
            for k, v in (live or {}).items():
                if k == "product_key" and isinstance(a.get(k), dict):
                    a[k] = {**v, **a[k]}          # 两种 product_key 形状并存，已有的不动
                else:
                    a.setdefault(k, v)
        if "evidence" not in a:
            try:
                ev = evidence_for(e, store=store, cache=cache)
            except Exception:
                ev = None
            if ev:
                a["evidence"] = ev
        if set(a) != before or (t.anchor or {}) != a:
            if a:
                t.anchor = a
                n += 1
    return n
