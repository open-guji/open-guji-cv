# -*- coding: utf-8 -*-
"""一轮审阅的体检：四个判据 + 下一批页码。**结构化返回，不打印。**

判据与阈值的唯一事实源。`scripts/round_check.py` 把它印成命令行，
控制台 `/api/round` 把它渲染成卡片——两边共用这里，免得阈值各写一套、
过一阵子对不上。

判据含义与「什么时候修算法」见 `.claude/doc/review_loop_sop.md`。

## 灯的语义

- **绿**：继续跑下一批；
- **黄**：记着，别动算法——样本不够时改算法是在拟合噪声
  （IDS 护栏、频次加权都是这么被否掉的）；
- **红**：停下修。

## ⚠️ 判据 C2 存在的理由

用户 2026-09-04 审 p44-56 时标了 14 条 truncated，而「框外成段墨」只测出 1 条。
把图块拼出来一看：切一半的、糊成一团的、两个字连一块的都有——**损伤不在框与
格线之间，那个测法根本够不着**。真因是那几页字距极挤（字间隙中位 0~2px，
对照正常页 6~7px），字与字物理相连，任何墨谷判据都找不到零墨行。

这类页**不是算法能修的**（handbook §1：「能从图上分开的都分对，分不开的都
标出来」）。C2 提前把它们标出来，是为了两件事：让人知道这批人审会多，
以及**防止我把它误判成算法回退去乱改本来正常的代码**。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

DATASET = Path("../open-guji-dataset")

GREEN, YELLOW, RED = "green", "yellow", "red"

# 判据阈值（改这里就改了 CLI 与控制台两边）
ERR_GREEN, ERR_YELLOW = 0.0, 0.001        # A 自动放行错误率
REVIEW_GREEN, REVIEW_YELLOW = 0.015, 0.03  # B 人审率
CLUSTER_RED_N, CLUSTER_RED_PAGES = 6, 3    # C 缺陷聚集：≥N 条且横跨 ≥P 页
CLUSTER_YELLOW_N = 3
TIGHT_GAP_MED, TIGHT_NEAR_RATIO = 2, 0.6   # C2 挤排：间隙中位 ≤2px 或 60% 不足 5px
NEAR_PX = 5


def _light(v: float | None, green: float, yellow: float) -> str:
    """v 越小越好。"""
    if v is None:
        return "none"
    return GREEN if v <= green else (YELLOW if v <= yellow else RED)


def load_verdicts(book: str, root: Path | None = None) -> dict[str, str]:
    """用户 confirm 事件 → {字位: 字形}，后裁覆盖先裁。"""
    import json
    d = (root or DATASET) / "feedback" / "events"
    out: dict[str, str] = {}
    for p in sorted(d.glob(f"{book}-*.jsonl")) if d.exists() else []:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            pl = e.get("payload") or {}
            if e.get("actor") == "user" and e.get("kind") == "confirm" \
                    and pl.get("v") == "confirm" and pl.get("shape"):
                out[e["target"]["key"]] = pl["shape"]
    return out


def _same_char(a: str | None, b: str | None) -> bool:
    """互为异体就当同一个字——刻本刻「卽」而整理本作「即」，字形层照录是对的。"""
    if not a or not b:
        return False
    try:
        from ..variants import are_variants
        if are_variants(a, b):
            return True
    except Exception:
        pass
    # variants.json 没收的字形异体（㫖/旨 这类 UCV 认同形）：VariantMap 的语义归并兜底
    try:
        from ..clustering.variants import VariantMap
        vm = VariantMap.load()
        return vm.semantic(a) == vm.semantic(b)
    except Exception:
        return False


def accuracy(book: str, pages: list[int], store=None) -> dict:
    """自动放行对两路真值的准确率。**必须成对读**：放行的本来就是容易那批。"""
    from ..core.step import page_key
    from ..gold.v2_align import align_book
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore

    st = store or ProductStore()
    gold = {c.id: c for g in align_book(book, pages, st) if g.anchored for c in g.chars}
    truth = load_verdicts(book)
    okg = ng = okt = nt = 0
    errors: list[dict] = []
    for pg in pages:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                if not r.admit or not r.char:
                    continue
                g = gold.get(r.id)
                if g:
                    ng += 1
                    hit = (r.char == g.shape or r.char == g.reading
                           or _same_char(r.char, g.shape))
                    okg += hit
                    if not hit:
                        errors.append({"id": r.id, "pred": r.char,
                                       "gold": g.shape, "channel": r.channel})
                t = truth.get(r.id)
                if t:
                    nt += 1
                    okt += (r.char == t or _same_char(r.char, t))
    return {"gold": [okg, ng], "human": [okt, nt], "errors": errors[:10]}


def review_rate(book: str, pages: list[int], store=None) -> dict:
    from ..core.step import page_key
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore

    st = store or ProductStore()
    tot = auto = excluded = 0
    per: Counter = Counter()
    for pg in pages:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                # 排除名单命中的格**不进分母**：人已经判过「这块图不能用」，
                # 它既不是自动放行也不是待人点的活。算进人审率会让「标缺陷」
                # 看着像「人审变多」——判据 B 的意思就反了。
                if "excluded" in (r.doubts or []):
                    excluded += 1
                    continue
                tot += 1
                if r.admit:
                    auto += 1
                else:
                    per[pg] += 1
    return {"total": tot, "auto": auto, "review": tot - auto, "excluded": excluded,
            "rate": (tot - auto) / tot if tot else None,
            "by_page": [{"page": p, "n": per[p]} for p in pages if per[p]]}


def defect_clusters(root: Path | None = None) -> dict:
    """人裁标的切分缺陷按格位聚。**孤例是个案，扎堆才是系统性问题。**

    累计看（不只本轮）——slot 2 那个 17/33 的信号是攒了三批才看清的。
    """
    from ..gold.store import GoldStore
    gs = GoldStore(root or DATASET)
    ev = [i for i in gs.list("char-segmentation/instances")
          if i.source_events
          and i.expected.get("quality") in ("truncated", "contaminated")]
    by_slot: Counter = Counter()
    pages_of: dict = {}
    for i in ev:
        by_slot[i.anchor.slot] += 1
        pages_of.setdefault(i.anchor.slot, set()).add(i.anchor.page)
    rows = [{"slot": s, "n": n, "pages": len(pages_of.get(s, ()))}
            for s, n in by_slot.most_common(8)]
    worst = next((r for r in rows
                  if r["n"] >= CLUSTER_RED_N and r["pages"] >= CLUSTER_RED_PAGES), None)
    if worst:
        light = RED
    elif rows and rows[0]["n"] >= CLUSTER_YELLOW_N:
        light = YELLOW
    else:
        light = GREEN
    return {"total": len(ev), "rows": rows, "worst": worst, "light": light}


def tight_pages(book: str, pages: list[int], store=None) -> dict:
    """挤排页：字与字物理相连，切分做不到完美（见模块头 C2）。"""
    from ..core.step import page_key
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore

    st = store or ProductStore()
    out = []
    for pg in pages:
        c = st.read(book, "row_segment", page_key(pg), "cells")
        ci = st.read(book, "cell_shrink", page_key(pg), "char_index")
        if not c or not ci:
            continue
        gaps: list[float] = []
        for cc in c.columns:
            cic = [x for x in ci.columns if x.col == cc.col]
            if not cic:
                continue
            bys = {getattr(x, "slot", None): x for x in cic[0].chars}
            prev = None
            for ce in sorted(cc.cells, key=lambda z: z.slot):
                ch = bys.get(ce.slot)
                if ch is None:
                    continue
                if prev is not None:
                    gaps.append(ch.bbox_col[1] - prev)
                prev = ch.bbox_col[3]
        if not gaps:
            continue
        gaps.sort()
        med = gaps[len(gaps) // 2]
        near = sum(1 for g in gaps if g < NEAR_PX) / len(gaps)
        if med <= TIGHT_GAP_MED or near >= TIGHT_NEAR_RATIO:
            out.append({"page": pg, "median_gap": round(float(med), 1),
                        "near_ratio": round(near, 2)})
    return {"rows": out, "light": YELLOW if out else GREEN}


def rare_char_recall(root: Path | None = None, k: int = 10) -> dict:
    """判据 D：rare-char 集上「字体模板 + CNN 融合」的 top-k 命中率。

    集在 `rare-char/items.jsonl`（参考答案来自用户裁决）。没有集或没装字体就报
    `none`。CNN checkpoint 缺席时退回纯 HOG——数字会明显低，界面上要能看出来。
    """
    import json

    f = (root or DATASET) / "rare-char" / "items.jsonl"
    if not f.exists():
        return {"light": "none", "note": "没有 rare-char 集"}
    try:
        import cv2
        from ..clustering.cnn_candidates import (CNN_WEIGHT, EMB_WEIGHT, HOG_WEIGHT,
                                                 rrf, shared)
        from ..clustering.font_candidates import book_charset, candidates
        from ..clustering.normalize import normalize_patch
        from ..variants import are_variants
    except Exception as e:
        return {"light": "none", "note": f"依赖缺失：{e}"}
    items = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    cs = tuple(book_charset("corpus/zongmu_wuyingdian_reference.txt",
                            [i["expected"]["char"] for i in items]))
    cnn = shared()
    hit = n = 0
    for it in items:
        img = cv2.imread(it["input"]["patch"], cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        q = normalize_patch(img)
        hog = [h.char for h in candidates(q, cs, k=k)]
        cn = [c for c, _ in cnn.topk(q, cs, k=k)] if cnn.available else []
        em = [c for c, _ in cnn.emb_topk(q, cs, k=k)] if cnn.available else []
        order = (rrf(hog, cn, em, k=k, weights=(HOG_WEIGHT, CNN_WEIGHT, EMB_WEIGHT)) if (cn and em)
                 else (rrf(hog, cn, k=k, weights=(HOG_WEIGHT, CNN_WEIGHT)) if cn else hog))
        g = it["expected"]["char"]
        n += 1
        hit += any(c == g or are_variants(c, g) for c in order)
    rate = hit / n if n else None
    light = GREEN if (rate or 0) >= 0.75 else (YELLOW if (rate or 0) >= 0.60 else RED)
    return {"hit": hit, "n": n, "rate": rate, "light": light,
            "cnn": cnn.available, "note": "" if cnn.available else "无 CNN checkpoint，纯 HOG"}


def next_batch(book: str, n: int = 12, store=None) -> dict:
    """下一批页码：正文页里没跑过 seed_admit 的，顺序取 n 个。

    ⚠️ 不能按页号顺推——vol01 的 p89-113 是职名页、p61/159-182 是目录页，
    用正文的 21 格先验跑必然全灭（见 books/vol01.yaml 里 p119 的教训）。
    """
    import json

    from ..core.step import page_key
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore

    f = DATASET / "page-type" / "items.jsonl"
    if not f.exists():
        return {"error": "没有 page-type 金标，无法判断正文页"}
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    body = sorted(int(r["anchor"]["page"]) for r in rows
                  if str(r.get("anchor", {}).get("book")) == book
                  and (r.get("expected") or {}).get("page_type") == "body")
    st = store or ProductStore()
    todo = [p for p in body
            if st.read(book, "seed_admit", page_key(p), "seed_admit") is None]
    return {"body_total": len(body), "done": len(body) - len(todo),
            "todo": len(todo), "batch": todo[:n]}


FIDELITY_MIN_AUDIT = 50        # E：抽审不到这么多条，不亮灯
FIDELITY_GREEN, FIDELITY_YELLOW = 0.99, 0.97   # E：Wilson 下界


def _wilson_low(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return (c - r) / d


def form_fidelity(book: str, pages: list[int], store=None) -> dict:
    """判据 E（variant_strategy.md §4.5）：**字形保真率**——自动放行里，字形与人裁
    完全一致的比例。分母只取「异体位」：自动放行且 (reading ≠ char，或走了
    variant_form 定形)。这里**不许**用 `_same_char` 放水：整理本印 髮、刻本刻 髪，
    存成 髮 在判据 A 里算对（异体算同字），在这里就是错——保真量的正是这一层。

    分两层报：`form_auto`（variant_form 定的形）与其余（库 same 继承的形）。
    抽审不足 FIDELITY_MIN_AUDIT 条不亮灯——这个数只能靠组视图攒。
    """
    from ..core.step import page_key
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore

    st = store or ProductStore()
    truth = load_verdicts(book)
    n_var = n_open = 0
    hit = n = 0
    hit_auto = n_auto = 0
    errors: list[dict] = []
    for pg in pages:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                f = (r.evidence or {}).get("form") or {}
                if not r.admit:
                    n_open += f.get("state") == "open"
                    continue
                is_var = bool(r.reading and r.reading != r.char) \
                    or f.get("state") in ("fixed_lib", "fixed_form")
                if not is_var or not r.char:
                    continue
                n_var += 1
                t = truth.get(r.id)
                if not t:
                    continue
                n += 1
                ok = (r.char == t)
                hit += ok
                if f.get("state") in ("fixed_lib", "fixed_form"):
                    n_auto += 1
                    hit_auto += ok
                if not ok:
                    errors.append({"id": r.id, "pred": r.char, "human": t,
                                   "reading": r.reading, "state": f.get("state")})
    low = _wilson_low(hit, n)
    if n < FIDELITY_MIN_AUDIT:
        light = "none"
    else:
        light = GREEN if low >= FIDELITY_GREEN else (YELLOW if low >= FIDELITY_YELLOW else RED)
    if errors:
        light = RED
    return {"variant_admits": n_var, "form_open": n_open,
            "audited": n, "hit": hit, "rate": (hit / n if n else None),
            "wilson_low": round(low, 4),
            "form_auto": [hit_auto, n_auto],
            "errors": errors[:10], "light": light,
            "note": (f"抽审 {n} 条不足 {FIDELITY_MIN_AUDIT}，去组视图攒" if n < FIDELITY_MIN_AUDIT else "")}


def check(book: str, pages: list[int]) -> dict:
    """五个判据一次算完。"""
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore

    st = ProductStore()
    acc = accuracy(book, pages, st)
    worst_err = 0.0
    for o, n in (acc["gold"], acc["human"]):
        if n:
            worst_err = max(worst_err, 1 - o / n)
    rv = review_rate(book, pages, st)
    return {
        "book": book, "pages": pages,
        "A": {**acc, "light": _light(worst_err, ERR_GREEN, ERR_YELLOW)},
        "B": {**rv, "light": _light(rv["rate"], REVIEW_GREEN, REVIEW_YELLOW)},
        "C": defect_clusters(),
        "C2": tight_pages(book, pages, st),
        "D": rare_char_recall(),
        "E": form_fidelity(book, pages, st),
    }
