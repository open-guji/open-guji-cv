"""Step0 预清理：把扫描件上的坏区修好，产物落盘，Step1 起自动读修好的那张。

**默认整本书什么都不做。** 只有在 books/<book>.yaml 里 `preclean:` 段登记过的页才处理 ——
坏页是人工确认的，位置也是人工（或 scripts/scan_inverted_bands.py 辅助）定的，
当作参数写进 yaml，不猜。

三件事分开
---------
1. **磁盘原图永不改写**（raw_dir 里那张是唯一真相）；
2. 修好的图落在 `precleaned/<book>/<page>.png`，由 `python -m open_guji_cv.cli_v2 preclean`
   显式生成 —— 这是个可重跑、可删掉重来的产物，不是缓存（不会被 LRU 清掉）；
3. `RunContext.raw_page` 优先读 precleaned 里那张；没有就读原图。
   所以 Step1 及其下游一行代码都不用改，未登记的页也完全不受影响。

两种坏区：`inverted_band`（梯形带）与 `inverted_rect`（矩形）
------------------------------------------------------------
挑哪个看**坏区的形状**，不是看大小：

- `inverted_band` —— 边界是多段梯形、要逐列量出来的（扫描时的横向故障）；
- `inverted_rect` —— 边界本来就是齐整矩形（抬头框整格被翻，如 vol07 p46 的
  「勅祇」两格，四边就是框线本身）。这种**不能**用 band：band 靠「列间纸列在
  区内是一整段纯黑」定上下沿，格内的字笔画会把那段黑截断，量出来的沿顺着笔画跑，
  实测把「祇」啃成几块黑斑。规则形状直接给四个数，不要去"量"。

下面讲的是 `inverted_band`
--------------------------
一条横带内**黑白是反的**（纸成黑、字成白）。不是墨污 —— 是扫描/二值化在这一带翻了极性，
所以修法是把带内的点整体反回来，字迹一笔不少地还原（抹除法会连笔画一起抹掉，是有损的）。

带的边界是**多段梯形**：上沿一级级抬高，下沿基本平，中间可能断开。所以不能用一对固定的 y，
得逐列量。量的办法是找**列间纸列** —— 上下文都无墨、本该全白的那些列；带内它们是纯黑的
一段，且黑得干净（没有笔画混进来），一量一个准。量到的点中值滤波去异常，再线性内插到整段。

实测（vol02 p151，原图 2307×3049）：
  反色前带内墨占比 0.806（纸被翻成黑）→ 反色后 0.194，正文正常水平 0.152，对上了。
  逐字核对整理本「真卿所見者四卷全本…傳寫者諱其殘缺因於書名增入卦爻二字」，
  所見 / 者 / 缺因 笔画完整。p152 同理，对上「周易要義十卷…宋魏了翁撰…僉書樞密院事」。

出口闸0：修好了没有，不再靠人眼看图
------------------------------------
上面那句「正文正常水平 0.152」原来是人量一次写进文档的读数，不是分布，闸不能拍在
一个单点上。`apply_preclean` 现在自己算带内墨占比（修前/修后），跟 `BODY_INK_GATE`
比——过了算过闸，没过就抛 `PrecleanGateError`。`BODY_INK_GATE` 的来历见下面常量区，
换书要重新标，用 `sample_body_baseline` 或 `cli_v2 preclean <book> --calibrate`。

**个别页可以单页放宽闸**（`gate_override` + `gate_reason`，见 `_check_gate`），
但**不许为了让某页过闸去调 `BODY_INK_GATE`** —— 那是全局闸，调松了别的页修坏了
也拦不住。单页的例外就单页记，记在 yaml 里，日志上看得见。

已登记的反色带（2026-09-12，十册 1695 页全扫后）
------------------------------------------------
共 14 页：vol01 p48；vol02 p136/151/152/153；vol04 p17；vol05 p22/p178；
vol07 p46（`inverted_rect`）/p78；vol08 p13；vol09 p174/p175；vol10 p135。
各册本底墨占比分布高度一致（中位 0.167-0.185 / p99 0.240-0.255），
所以 `BODY_INK_GATE=0.25` 各册通用，不必按册重标。两处例外走单页 `gate_override`：
vol05 p178（带压在字最粗的一段上，0.267 → 闸 0.28）、
vol07 p46（矩形把抬头框的框线圈了进来，那是真墨，0.290 → 闸 0.30）。

找候选用 `scripts/scan_inverted_bands.py`（判据已改成按页自量，不含固定像素；
**贴着版框的带是它的已知盲区，要另跑 `--edge`**）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
from scipy.ndimage import median_filter

# 修好的图落在这里。是产物不是缓存：显式生成、可删掉重来、不会被 LRU 清掉。
PRECLEANED_DIRNAME = "precleaned"


class PrecleanGateError(ValueError):
    """带内墨占比修完仍未回落到正文本底量级——闸拦下，不放行。"""


# ── 出口闸0：带内墨占比要回落到正文本底量级 ──────────────────────────
# 阈值有分布依据，不是拍的。2026-09-09 标定（vol02，183 个正常页 3-188，
# 去掉登记过 preclean 的 151/152/153）：正文区（四边各掐掉
# BASELINE_Y_MARGIN/BASELINE_X_MARGIN 的边）切成高 BASELINE_WINDOW_H px 的横条，
# 共 1953 条 —— 中位 0.183，p95 0.226，p99 0.245，最大 0.297。
# 闸阈值 BODY_INK_GATE 卡在 p99 之上留一点余量：p151/152 修复后 ≈0.19 稳稳过闸；
# p153 带更薄更淡，修复后 0.23，高于 p95 但仍在这 183 页的自然波动之内——
# 拿 p95 当阈值会把 153 误拦，所以不能卡那么紧。跟真正修不好的场景
# （残墨比例 0.5 起）比，0.25 仍留着数量级的差距。
# ⚠️ 换书这些数字要重新标：跑 `python -m open_guji_cv.cli_v2 preclean <book> --calibrate`。
BASELINE_WINDOW_H = 220
BASELINE_Y_MARGIN = 0.10
BASELINE_X_MARGIN = 0.13
BASELINE_SAMPLE_PAGES = 183
BASELINE_SAMPLE_WINDOWS = 1953
BODY_INK_MEDIAN = 0.183
BODY_INK_P95 = 0.226
BODY_INK_P99 = 0.245
BODY_INK_GATE = 0.25


def _trace_band(b: np.ndarray, y_lo: int, y_hi: int, y_probe: int,
                ctx: int, smooth: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """用列间纸列量出带的上下沿。返回 (量到的 x, 上沿, 下沿)。

    列间纸列 = 带上方 ctx 行与带下方 ctx 行都无墨的列。带内这些列是纯黑的一段，
    取包含 y_probe 的那段连续黑，就是带在该列的上下沿。
    """
    above = b[y_lo - ctx:y_lo].any(axis=0)
    below = b[y_hi:y_hi + ctx].any(axis=0)
    paper = ~above & ~below

    w = b.shape[1]
    top = np.full(w, -1, int)
    bot = np.full(w, -1, int)
    for x in np.flatnonzero(paper):
        col = b[y_lo:y_hi, x].astype(np.uint8)
        idx = np.flatnonzero(np.diff(np.r_[0, col, 0]))
        for a, c in zip(idx[::2], idx[1::2]):
            if y_lo + a <= y_probe <= y_lo + c - 1:
                top[x] = y_lo + a
                bot[x] = y_lo + c - 1
                break
    xs = np.flatnonzero(top >= 0)
    if xs.size == 0:
        raise ValueError("没量到带：检查 y_lo/y_hi/y_probe 是否框住了污渍带")
    t = median_filter(top[xs].astype(float), size=smooth, mode="nearest")
    bo = median_filter(bot[xs].astype(float), size=smooth, mode="nearest")
    return xs, t, bo


def _polygon_mask(shape: tuple[int, int], segments: list[list[int]],
                  xs: np.ndarray, top: np.ndarray, bot: np.ndarray) -> np.ndarray:
    """量到的 (xs, top, bot) 内插到 segments 覆盖的每一列，铺成整块布尔 mask。"""
    mask = np.zeros(shape, bool)
    for x0, x1 in segments:
        gx = np.arange(x0, x1 + 1)
        tt = np.round(np.interp(gx, xs, top)).astype(int)
        bb = np.round(np.interp(gx, xs, bot)).astype(int)
        for x, a, c in zip(gx, tt, bb):
            mask[a:c + 1, x] = True
    return mask


def band_boundary(gray: np.ndarray, *, y_lo: int, y_hi: int, y_probe: int,
                  ink_threshold: int = 128, ctx: int = 170,
                  smooth: int = 31) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """量出带的上下沿，不铺 mask。供控制台画"当初判定的这条带在哪"用——
    比 `band_mask` 早一步，画图只需要边界折线，不需要整块布尔图。
    """
    b = gray < ink_threshold
    return _trace_band(b, y_lo, y_hi, y_probe, ctx, smooth)


def band_mask(gray: np.ndarray, *, segments: list[list[int]],
             y_lo: int, y_hi: int, y_probe: int,
             ink_threshold: int = 128, ctx: int = 170,
             smooth: int = 31) -> np.ndarray:
    """量出带的多段梯形区域，只返回布尔 mask（不反转）。供闸0核算带内墨占比用，
    入参与 `invert_band` 同一套，量出来的边界也一样。
    """
    xs, t, bo = band_boundary(gray, y_lo=y_lo, y_hi=y_hi, y_probe=y_probe,
                              ink_threshold=ink_threshold, ctx=ctx, smooth=smooth)
    return _polygon_mask(gray.shape, segments, xs, t, bo)


def band_ink_ratio(gray: np.ndarray, mask: np.ndarray, ink_threshold: int = 128) -> float:
    """mask 圈住的那块区域里，墨占比是多少。"""
    return float((gray[mask] < ink_threshold).mean())


def invert_band(gray: np.ndarray, *, segments: list[list[int]],
                y_lo: int, y_hi: int, y_probe: int,
                ink_threshold: int = 128, ctx: int = 170,
                smooth: int = 31) -> np.ndarray:
    """把多段梯形围出的区域整体黑白反转，返回新图；入参不改。

    segments  横向分段 [[x0, x1], ...]，闭区间；带中间断开的地方要分开写。
    y_lo/y_hi 搜索窗（带一定落在窗内），y_probe 窗内一定在带里的一行。
    ctx       量列间纸列时，往带上下各看多少行。
    """
    mask = band_mask(gray, segments=segments, y_lo=y_lo, y_hi=y_hi, y_probe=y_probe,
                     ink_threshold=ink_threshold, ctx=ctx, smooth=smooth)
    out = gray.copy()
    out[mask] = 255 - gray[mask]
    return out


def invert_rect(gray: np.ndarray, *, x0: int, x1: int, y0: int, y1: int,
                ink_threshold: int = 128) -> np.ndarray:
    """把一个**矩形**区域整体黑白反转，返回新图；入参不改。四边都是闭区间。

    什么时候用它而不是 `inverted_band`：坏区边界本来就是**齐整的矩形**时。
    典型是抬头框整格被翻（vol07 p46 的「勅祇」两格）——那种坏区的四边就是
    框线本身，不是「一级级抬高的梯形」。

    `inverted_band` 的逐列量法在这种区上会**把字啃坏**：它靠「列间纸列在带内
    是一整段纯黑」定上下沿，而矩形内的字笔画会把那段黑截断，量出来的沿就顺着
    笔画跑（实测 p46 的「祇」被啃成几块黑斑）。矩形是已知的规则形状，直接给
    四个数，不要去"量"。
    """
    out = gray.copy()
    out[y0:y1 + 1, x0:x1 + 1] = 255 - gray[y0:y1 + 1, x0:x1 + 1]
    return out


def rect_mask(shape: tuple[int, int], *, x0: int, x1: int,
              y0: int, y1: int) -> np.ndarray:
    """`invert_rect` 反转的那块区域，布尔 mask。供闸0核算墨占比用。"""
    m = np.zeros(shape, bool)
    m[y0:y1 + 1, x0:x1 + 1] = True
    return m


_OPS = {"inverted_band": invert_band, "inverted_rect": invert_rect}


def _check_gate(kind: str, before: float, after: float,
                override: float | None, reason: str | None) -> str:
    """闸0核对。过闸返回说明；没过抛 `PrecleanGateError`。

    `gate_override` 是**单页**放宽的阈值，必须同时写 `gate_reason` 说明为什么 ——
    否则拒绝放行。设它的前提是已经证明「超阈不是修复不彻底，是这一带本来字就密」：
    办法是把同形状 mask 平移到上下无带的正常文本区量一遍，若量得同量级，
    那这点墨就是字本身的，不是残留（vol05 p178 就是这么定的，见其 yaml note）。

    **不要为了让某页过闸去调 `BODY_INK_GATE`**：那是全局闸，调松了别的页
    修坏了也拦不住。单页的例外就单页记，记在 yaml 里，看得见。
    """
    gate = BODY_INK_GATE
    tag = ""
    if override is not None:
        if not reason:
            raise PrecleanGateError(
                f"{kind} 写了 gate_override={override} 却没写 gate_reason —— "
                f"单页放宽闸必须说明理由（并先证明超阈不是修复不彻底），不放行。"
            )
        if override < BODY_INK_GATE:
            raise PrecleanGateError(
                f"{kind} 的 gate_override={override:.3f} 比全局闸 "
                f"{BODY_INK_GATE:.3f} 还严 —— 这个字段是用来单页**放宽**的，"
                f"要收紧请直接改全局常量。"
            )
        gate = float(override)
        tag = f"（单页放宽至 {gate:.3f}：{reason}）"

    note = (f"{kind}: 带内墨占比 {before:.3f} -> {after:.3f}"
            f"（本底中位 {BODY_INK_MEDIAN:.3f} / p95 {BODY_INK_P95:.3f} / "
            f"闸 {gate:.3f}） {'过闸' if after <= gate else '✗ 超阈未过闸'}{tag}")
    if after > gate:
        raise PrecleanGateError(
            f"闸0未过：{kind} 修完带内墨占比仍是 {after:.3f}，高于阈值 "
            f"{gate:.3f}（本底中位 {BODY_INK_MEDIAN:.3f} / "
            f"p99 {BODY_INK_P99:.3f}）—— 修复没有把带内墨量带回正文水平。"
        )
    return note


def apply_preclean(gray: np.ndarray, rules: list[dict]) -> tuple[np.ndarray, list[str]]:
    """按 book.yaml 里登记的规则依次处理一页。返回 (新图, 每条规则的说明)。

    `inverted_band` 会核对闸0：带内墨占比修完要回落到 `BODY_INK_GATE` 以内，
    没回落就抛 `PrecleanGateError`（拦下，不放行）——阈值来历见模块顶部常量区。

    个别页可以用 `gate_override` 单页放宽闸（见 `_check_gate`）——**只能单页放宽，
    不许改全局常量**：闸是给所有页的，为一页调松了，别的页修坏了就拦不住。
    """
    notes: list[str] = []
    out = gray
    for r in rules:
        kind = r.get("kind", "inverted_band")
        fn = _OPS.get(kind)
        if fn is None:
            raise ValueError(f"未知的 preclean 类型: {kind}（可用: {sorted(_OPS)}）")
        kw = {k: v for k, v in r.items()
              if k not in ("kind", "page", "note", "gate_override", "gate_reason")}
        th = kw.get("ink_threshold", 128)

        if kind in ("inverted_band", "inverted_rect"):
            if kind == "inverted_band":
                mask = band_mask(out, segments=kw["segments"], y_lo=kw["y_lo"],
                                 y_hi=kw["y_hi"], y_probe=kw["y_probe"], ink_threshold=th,
                                 ctx=kw.get("ctx", 170), smooth=kw.get("smooth", 31))
            else:
                mask = rect_mask(out.shape, x0=kw["x0"], x1=kw["x1"],
                                 y0=kw["y0"], y1=kw["y1"])
            before = band_ink_ratio(out, mask, th)
            out = fn(out, **kw)
            after = band_ink_ratio(out, mask, th)
            notes.append(_check_gate(kind, before, after,
                                     r.get("gate_override"), r.get("gate_reason")))
        else:
            before = float((out < th).mean())
            out = fn(out, **kw)
            after = float((out < th).mean())
            notes.append(f"{kind}: 全页墨占比 {before:.3f} -> {after:.3f}")
    return out, notes


def sample_body_baseline(book, pages: list[int], *, window_h: int = BASELINE_WINDOW_H,
                         y_margin: float = BASELINE_Y_MARGIN,
                         x_margin: float = BASELINE_X_MARGIN,
                         ink_threshold: int = 128) -> np.ndarray:
    """在给定书的一批「正常页」（没有登记 preclean 的页）上量正文本底的墨占比分布。

    正常页没有带，量不了「带内」墨占比——所以退而求其次：正文区（四边各掐掉
    y_margin/x_margin 的边，避开版框与装订边空白）切成高 window_h 的横条，
    逐条量墨占比，凑一批样本出来。`BODY_INK_GATE` 等常量就是这样标定的，
    换书要用这批新页重新跑一遍，数字对不上时别改这里的代码，改模块顶部的常量。
    """
    from cv2 import imread

    ratios: list[float] = []
    for page in pages:
        img = imread(str(book.raw_path(page)), 0)
        if img is None:
            continue
        h, w = img.shape
        y0, y1 = int(h * y_margin), int(h * (1 - y_margin))
        x0, x1 = int(w * x_margin), int(w * (1 - x_margin))
        b = img[:, x0:x1] < ink_threshold
        for y in range(y0, y1 - window_h, window_h):
            ratios.append(float(b[y:y + window_h].mean()))
    return np.array(ratios)


# ── 产物落盘 ────────────────────────────────────────────────────────
def precleaned_root(repo_root: Path | None = None) -> Path:
    base = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    return base / PRECLEANED_DIRNAME


def precleaned_path(book_id: str, page: int, repo_root: Path | None = None) -> Path:
    return precleaned_root(repo_root) / book_id / f"{page}.png"


def effective_raw_path(book, page: int, *, log: Callable[[str], None] | None = None,
                       repo_root: Path | None = None) -> Path:
    """这一页该从哪读：登记过预清理且产物已生成的，读修好的那张；否则读原图。

    `RunContext.raw_page`（Step1 及下游管线）与叠图 `render.overlay.overlay`
    （控制台展示）**必须读同一张图**——叠图画的是"管线实际处理的产物"，
    不能悄悄换成原图，否则登记过 preclean 的页会出现"叠图看着不对、
    实跑却是对的"这种两边对不上的假象（2026-09-12 发现：Step1 起的叠图
    一直在读原图，没走这条判断）。
    """
    if page in (getattr(book, "preclean", {}) or {}):
        p = precleaned_path(book.id, page, repo_root)
        if p.exists():
            return p
        if log:
            log(f"[Step0] {book.id} p{page} 登记了预清理但产物不存在，"
                f"先用原图；跑 `python -m open_guji_cv.cli_v2 preclean {book.id}` 生成")
    return book.raw_path(page)


def build_precleaned(book, pages=None, *, force: bool = False,
                     log=print, repo_root: Path | None = None) -> list[Path]:
    """按 book.preclean 生成修好的页图，返回写出的文件。

    只处理登记过的页；已存在且非 force 就跳过。**不碰 raw_dir 里的原图。**
    """
    from cv2 import imread, imwrite

    rules_by_page = getattr(book, "preclean", {}) or {}
    todo = sorted(rules_by_page) if pages is None else [p for p in pages if p in rules_by_page]
    if pages is not None:
        missing = [p for p in pages if p not in rules_by_page]
        if missing:
            log(f"这些页没在 {book.id}.yaml 的 preclean 段里登记，跳过: {missing}")

    written: list[Path] = []
    for page in todo:
        dst = precleaned_path(book.id, page, repo_root)
        if dst.exists() and not force:
            log(f"  p{page} 已有，跳过（--force 可重做）: {dst}")
            continue
        src = book.raw_path(page)
        img = imread(str(src), 0)
        if img is None:
            raise FileNotFoundError(f"原图缺失: {src}")
        out, notes = apply_preclean(img, rules_by_page[page])
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not imwrite(str(dst), out):
            raise IOError(f"写盘失败: {dst}")
        for n in notes:
            log(f"  p{page} {n}")
        log(f"  p{page} -> {dst}")
        written.append(dst)
    return written
