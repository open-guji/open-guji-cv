"""本书重训 IDS 整字模板（M3，cv#897 三系统五层：书自训的模板进本书 `ids_model`，本书优先，没训的组按 sha 引用殿本）。

殿本模板库不贴别的刻本的刻风时（全唐文 men／chuo／xjz 在 `ids_whole` 的 `low_margin` 大量弃权），用**本书自己的**已放行格和人裁重训：

    python -m open_guji_cv.groups.ids_retrain men chuo xjz  --ws ../ws      # 换书一条命令：取包、拉原图、重训、写进本书数据目录
    python -m open_guji_cv.groups.ids_retrain men chuo xjz --prod <产物根> --imgs <原图根> --out <本书数据目录>/config/groups/ids   # 已有数据时
    之后 `guji db sync -w <工作区>` 推中心库；用本书模板的册从 seed_admit 起重跑（模板库进了 group_flow 指纹）。

产物根下是 `<册>/seed_admit/p*.json` 与 `<册>/cell_shrink/p*.json`（`guji products pack fetch` 的布局），原图根下是 `<册>/<页>.png`
（`guji source pull --to`）。每组做五件事：

1. **取标签**：本书已放行格的放行字（通道 `human`／`match_ref`／`ref_lib`／`book_knn`／`near_knn`／`match_replace`／`match_solo`，无疑问），
   每册每字 ≤ `per_vol`、每字 ≤ `cap`，人裁优先。组外陪衬字取殿本模板库里的非组员类（判成它们＝弃权）。
2. **清标签**：按册留出，被**别的类高把握推翻**（判成另一字且 margin ≥ `drop_margin`）的格去掉，重复到不再有（≤ `rounds` 轮）。
   人裁格不自动去，只列进报告待看图。去掉的格全进报告（`dropped`），要抽检。
3. **按册留出验证**：判某册时模板不含该册；错＝判成**另一个组员字**（判成陪衬或弃权不算错）。
4. **定门槛**：最大错例 margin ×1.1（不低于 `floor`），即留出 0 错；同格对比殿本模板库的给字数与错数。
5. **独立审计**：不进训练的通道（文意、坐标兜底、证人、稀见字）放行格拿最终模板库判，判成另一组员字的 margin 抬高门槛
   （看图确认是整理本标错的格进 `--audit-ok`，不抬）。训练格都是别的通道已放行的容易格，只做按册留出会高估。
6. **写模板库**到 `--out/<组>.json`（门槛写进文件的 `spec.min_margin`，`ids_online.judge` 读到就覆盖 `SPECS`），报告写 `--report`。

分层 L2：只依赖 numpy、cv2 与同包 `ids_whole`／`ids_online`／`registry`。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import random
from pathlib import Path

import numpy as np

OK_CHANNELS = ("human", "match_ref", "ref_lib", "book_knn", "near_knn", "match_replace", "match_solo")


def gather(prod: Path, imgs: Path, g: str, per_vol: int = 10, cap: int = 100, channels=OK_CHANNELS, extras: str = ""):
    """本书已放行格 → `[{form, gray, book, id, ch}]`（字块用原图按 cell_shrink 的 bbox_page 裁，灰度）。"""
    import cv2
    from ..core.anchor import crop_patch
    from .registry import FLOW_GROUPS as GROUPS
    classes = set(GROUPS[g].members) | set(extras)
    random.seed(0)
    by: dict = collections.defaultdict(list)
    for vd in sorted(glob.glob(str(prod / "*"))):
        book = Path(vd).name
        for f in sorted(glob.glob(f"{vd}/seed_admit/p*.json")):
            for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
                for r in col["chars"]:
                    if r.get("admit") and r.get("char") in classes and r.get("channel") in channels and not r.get("doubts"):
                        by[(book, r["char"])].append(r)
    pool: dict = collections.defaultdict(list)
    for (book, ch), rs in by.items():
        rs.sort(key=lambda r: (r["channel"] != "human", random.random()))
        pool[ch] += [(book, r) for r in rs[:per_vol]]
    want = []
    for ch, l in pool.items():
        l.sort(key=lambda t: (t[1]["channel"] != "human", random.random()))
        want += l[:cap]
    pages: dict = collections.defaultdict(list)
    for book, r in want:
        pages[(book, int(r["id"].split(":")[1]))].append(r)
    cells = []
    for (book, page), rs in sorted(pages.items()):
        sh = prod / book / "cell_shrink" / f"p{page:04d}.json"
        img = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
        if img is None or not sh.exists():
            continue
        box = {c["id"]: c["bbox_page"] for col in json.load(open(sh, encoding="utf-8"))["char_index"]["columns"] for c in col["chars"]}
        for r in rs:
            if box.get(r["id"]):
                cells.append(dict(form=r["char"], gray=crop_patch(img, tuple(box[r["id"]])).copy(), book=book, id=r["id"], ch=r["channel"]))
    return cells


AUDIT_CHANNELS = ("context", "ref_ctx", "coord_fallback", "witness3", "rare_ref", "group_flow")


def audit_cells(prod: Path, imgs: Path, g: str, n: int = 700):
    """**独立审计格**：不进训练的通道（文意、坐标兜底、证人、稀见字、殿本模板放行）里放行字是组员的格，随机 ≤ n。
    训练格全是「别的通道已放行」的容易格，按册留出会高估；审计格没参与定标签，判成别字就是真问题（或整理本标错，看图）。"""
    import cv2
    from ..core.anchor import crop_patch
    from .registry import FLOW_GROUPS as GROUPS
    mem = GROUPS[g].members
    rows = []
    for vd in sorted(glob.glob(str(prod / "*"))):
        for f in glob.glob(f"{vd}/seed_admit/p*.json"):
            for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
                rows += [(Path(vd).name, r) for r in col["chars"] if r.get("admit") and r.get("char") in mem and r.get("channel") in AUDIT_CHANNELS]
    random.Random(1).shuffle(rows)
    out = []
    for book, r in rows[:n]:
        page = int(r["id"].split(":")[1])
        sh = prod / book / "cell_shrink" / f"p{page:04d}.json"
        img = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
        if img is None or not sh.exists():
            continue
        box = {c["id"]: c["bbox_page"] for col in json.load(open(sh, encoding="utf-8"))["char_index"]["columns"] for c in col["chars"]}
        if box.get(r["id"]):
            out.append(dict(form=r["char"], gray=crop_patch(img, tuple(box[r["id"]])).copy(), id=r["id"], ch=r["channel"]))
    return out


def lovo(g: str, cells, sp, bank=None):
    """按册留出：→ `[{form, pick, m, id, ch}]`。`bank` 给了（殿本模板库 dict）就用它判、不留出（对照用）。"""
    from . import ids_online as O, ids_whole
    prep = [(c["form"], ids_whole.clean_patch(c["gray"]) if sp.clean else c["gray"], c["book"], c["id"]) for c in cells]
    d = ids_whole.build(g, prep, sp.size)
    tpl = {k: [O._dec(s, sp.size) for s in v] for k, v in d["templates"].items()}
    books, keys = d["source"]["books"], d["source"]["keys"]
    ch_of = {c["id"]: c["ch"] for c in cells}
    res = []
    for bk in sorted({b for v in books.values() for b in v}):
        sub = bank if bank is not None else {n: [t for j, t in enumerate(tpl[n]) if books[n][j] != bk] for n in tpl}
        for f in tpl:
            for i, x in enumerate(tpl[f]):
                if books[f][i] == bk:
                    ch, m, _ = ids_whole.score_norm(x, sub, sp.whole, tuple(sp.region), sp.lam)
                    ok = ch is not None and len(sub.get(ch, ())) >= sp.min_class
                    res.append(dict(form=f, pick=ch if ok else None, m=float(m), id=keys[f][i], ch=ch_of[keys[f][i]]))
    return res


def _wrong(r, members) -> bool:
    return r["pick"] in members and r["pick"] != r["form"]


def clean(g: str, cells, sp, members, drop_margin: float = 0.3, rounds: int = 3):
    """迭代去离群标签。→ (留下的格, 去掉的 [{id, form, pick, m, round}], 待看图的人裁格)。"""
    dropped, human = [], []
    for k in range(rounds):
        res = lovo(g, cells, sp)
        bad = {r["id"]: r for r in res if r["pick"] is not None and r["pick"] != r["form"] and r["m"] >= drop_margin
               and (r["pick"] in members or r["form"] in members)}
        if not bad:
            break
        seen = {h["id"] for h in human}
        for i, r in bad.items():
            if r["ch"] == "human" and i in seen:
                continue
            (human if r["ch"] == "human" else dropped).append(dict(id=i, form=r["form"], pick=r["pick"], m=round(r["m"], 3), round=k, ch=r["ch"]))
        if all(r["ch"] == "human" for r in bad.values()):
            break
        cells = [c for c in cells if c["id"] not in bad or c["ch"] == "human"]
    return cells, dropped, human


def retrain(g: str, prod: Path, imgs: Path, out: Path, report: Path, per_vol=10, cap=100, drop_margin=0.3, rounds=3, floor=0.5,
            audit_ok: dict | None = None, audit: int = 700) -> dict:
    from dataclasses import replace
    from . import ids_online as O, ids_whole
    from .registry import FLOW_GROUPS as GROUPS
    sp, members = O.SPECS[g], set(GROUPS[g].members)
    audit_ok = audit_ok or {}
    base_path = O._ROOT / (GROUPS[g].config_dir or f"config/groups/{g}") / "ids_bank.json"
    base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else None
    extras = "".join(sorted(k for k in (base or {}).get("templates", {}) if k not in members))
    cells = gather(prod, imgs, g, per_vol, cap, extras=extras)
    n0 = len(cells)
    kept, dropped, human = clean(g, cells, sp, members, drop_margin, rounds)
    res = lovo(g, kept, sp)
    full = lovo(g, cells, sp)         # 未清标签的留出（含被去掉的格）：诚实地报「含标签噪声」的错数
    mw = max([r["m"] for r in res if _wrong(r, members)], default=0.0)
    thr_lovo = round(max(floor, mw * 1.1), 2)
    prep = [(c["form"], ids_whole.clean_patch(c["gray"]) if sp.clean else c["gray"], c["book"], c["id"]) for c in kept]
    d = ids_whole.build(g, prep, sp.size, {"labels": f"本书已放行格放行字＋人裁（每册每字 ≤{per_vol}、每字 ≤{cap}），按册留出去离群标签 {len(dropped)} 格"})
    # 独立审计：最终模板库判审计格（不设门槛），判成另一个组员字的 margin 抬高门槛
    bank = {k: [O._dec(x, sp.size) for x in v] for k, v in d["templates"].items()}
    aud_diff, aud_n = [], 0
    for c in (audit_cells(prod, imgs, g, audit) if audit else []):
        aud_n += 1
        v = O.judge_with(g, c["gray"], bank, replace(sp, min_margin=0.0))
        if v.char is not None and v.char != c["form"]:
            aud_diff.append(dict(id=c["id"], form=c["form"], pick=v.char, m=round(float(v.conf), 3), ch=c["ch"], ok=c["id"] in audit_ok))
    am = max([x["m"] for x in aud_diff if not x["ok"]], default=0.0)
    thr = round(max(thr_lovo, am * 1.1), 2)
    inmem = [r for r in res if r["form"] in members]
    give = [r for r in inmem if r["pick"] in members and r["m"] >= thr]
    card = {"group": g, "cells_before": n0, "cells_after": len(kept), "dropped": len(dropped), "human_flagged": len(human),
            "threshold": thr, "threshold_lovo": thr_lovo, "max_wrong_margin": round(mw, 3), "audit_cells": aud_n,
            "audit_diff": len(aud_diff), "audit_max_diff_margin": round(am, 3),
            "audit_wrong_at_thr": sum(1 for x in aud_diff if not x["ok"] and x["m"] >= thr),
            "member_cells": len(inmem), "give": len(give), "give_wrong": sum(r["pick"] != r["form"] for r in give),
            "uncleaned_wrong_at_thr": sum(1 for r in full if _wrong(r, members) and r["m"] >= thr), "human_give": sum(1 for r in give if r["ch"] == "human"),
            "classes": dict(sorted(collections.Counter(c["form"] for c in kept).items()))}
    if base is not None:
        cmp = lovo(g, kept, sp, bank={k: [O._dec(x, int(base["size"])) for x in v] for k, v in base["templates"].items()})
        bg = [r for r in cmp if r["form"] in members and r["pick"] in members and r["m"] >= sp.min_margin]
        card["dianben_bank"] = {"threshold": sp.min_margin, "give": len(bg), "wrong": sum(r["pick"] != r["form"] for r in bg)}
    d["source"]["retrain"] = {k: card[k] for k in ("cells_before", "cells_after", "dropped", "threshold", "give", "give_wrong", "audit_cells", "audit_wrong_at_thr")}
    d["spec"] = {"min_margin": thr}
    out.mkdir(parents=True, exist_ok=True)
    O.write_bank(d, out / f"{g}.json")
    report.mkdir(parents=True, exist_ok=True)
    (report / f"{g}.json").write_text(json.dumps({**card, "dropped_cells": dropped, "human_cells_to_review": human, "audit_diff_cells": aud_diff},
                                                 ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return card


def prepare(ws: Path, work: Path, vols: list | None = None) -> tuple[Path, Path]:
    """换书一条命令的取数一步：每册取中心库里最新的产物包（`guji products pack list` 按时间取最后一个标签）、拉原图。
    → (产物根, 原图根)。已取过的册跳过。需要装 guji-manager。"""
    import re
    import subprocess
    def guji(*a):
        return subprocess.run(["guji", *a], capture_output=True, text=True, check=True).stdout
    prod, imgs = work / "prod", work / "imgs"
    latest: dict = {}
    for line in guji("products", "pack", "list", "-w", str(ws)).splitlines():
        m = re.match(r"\s*products/[^/]+/([^/]+)/(\S+)\t(\d+)\t(\S+)", line)
        if m:
            v, label, _size, ts = m.groups()
            if v not in latest or ts > latest[v][1]:
                latest[v] = (label, ts)
    for v, (label, _) in sorted(latest.items()):
        if vols and v not in vols:
            continue
        if not (prod / v / "seed_admit").exists():
            guji("products", "pack", "fetch", v, "-w", str(ws), "--label", label, "--to", str(prod))
        if not (imgs / v).exists():
            src = json.loads((prod / v / "_source.json").read_text(encoding="utf-8"))
            guji("source", "pull", "--book-id", src["book_id"], "--vol", v, "--rev", str(src["rev"]), "--to", str(imgs / v), "-w", str(ws))
    return prod, imgs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="本书重训 IDS 整字模板（M3）")
    ap.add_argument("groups", nargs="+")
    ap.add_argument("--prod", type=Path, default=None)
    ap.add_argument("--imgs", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None, help="本书数据目录 config/groups/ids；用 --ws 时缺省就是它")
    ap.add_argument("--ws", type=Path, default=None, help="一条命令：工作区；自动取各册最新产物包与原图（落 --work），输出进它的数据目录")
    ap.add_argument("--work", type=Path, default=Path("retrain-work"))
    ap.add_argument("--vols", nargs="*", default=None, help="只用这几册（缺省有产物包的全部）")
    ap.add_argument("--report", type=Path, default=Path("retrain-report"))
    ap.add_argument("--per-vol", type=int, default=10)
    ap.add_argument("--cap", type=int, default=100)
    ap.add_argument("--drop-margin", type=float, default=0.3)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--audit-ok", type=Path, default=None, help="json {格 id: 理由}：独立审计里看图确认是整理本标错的格，不抬门槛")
    ap.add_argument("--audit", type=int, default=700, help="独立审计格数上限，0＝不审计")
    ap.add_argument("--floor", type=float, default=0.5, help="门槛下限（留出 0 错的最小值再低也不低于它，留余量）")
    a = ap.parse_args(argv)
    if a.ws:
        from ..core.workspace import ws_config_dir
        a.prod, a.imgs = prepare(a.ws, a.work, a.vols)
        a.out = a.out or ws_config_dir(a.ws) / "groups" / "ids"
    if not (a.prod and a.imgs and a.out):
        ap.error("要么给 --ws，要么同时给 --prod --imgs --out")
    for g in a.groups:
        c = retrain(g, a.prod, a.imgs, a.out, a.report, a.per_vol, a.cap, a.drop_margin, a.rounds, a.floor,
                    json.loads(a.audit_ok.read_text(encoding="utf-8")) if a.audit_ok else None, a.audit)
        print(json.dumps({k: v for k, v in c.items() if k != "classes"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
