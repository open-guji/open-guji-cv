# -*- coding: utf-8 -*-
"""把「影子≠现字」审查页（Artifact）上的人裁收回来，写成人裁事件。幂等。

    # 1. 先把线上那页读到本地（Artifact action="read"，大页会落成本地文件）
    # 2. 收回
    python scripts/harvest_shadow_review.py PAGE.html \
        --cards artifacts/vol03_shadow_review_cards.jsonl \
        --feedback-dir <ws>/feedback \
        --batch vol03-shadow-review-0929 [--dry-run]

裁决 → 事件（`step=seed_admit, unit=cell, kind=confirm`，与 `vol03-all-decide` 同一口径）：

| 页上 | 事件 payload |
|---|---|
| `a` / `b`（所选的字，卡片映射取自 `--cards`） | `v=confirm, shape=<所选字>` |
| `neither`（都不是） | `v=seg_defect, quality=truncated, shape=""` |
| `idk`（拿不准） / 没裁 | **不写** |

**幂等**：以 `target.key` 为准，本批次里已经有这一格的事件就跳过（不管裁决是否相同）。
用户以后接着裁剩下的卡，重复跑只会追加新裁的；已写过的格若页上裁决变了，只报告、不改
（事件日志只追加，要改走 `EventLog.compact` / 追加更正事件，由 H 道决定）。

`target.anchor` 口径同控制台写入路径（`console/routers/feedback.py::_product_anchor`）：
`{"product_key": {"step": "seed_admit", "key": "p0068", "fingerprint": …}}`。指纹优先取工作区
产物清单里 seed_admit 该页的现值；工作区没有产物（云端只有事件，无 products/）时，取
**同一页、同 step 已有事件里带的指纹**（同一次 seed_admit 产物上裁的）；两者都没有就不写
`fingerprint`（anchor 仍在，绑定表按「无指纹」处理）。每条事件的 `anchor.fp_source`
记指纹来源，事后可查。不重算任何产物。

写入走 `EventLog.append`（同一把写锁、同一套字形合法性校验），不手拼 JSON。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STEP = "seed_admit"
_DATA = re.compile(r'<script[^>]*id="data"[^>]*>(.*?)</script>', re.S)


def load_verdicts(html_path: Path) -> dict:
    m = _DATA.search(html_path.read_text(encoding="utf-8"))
    if not m:
        sys.exit("这页里没有 #data —— 确认读的是审查页本身，不是它的摘要")
    return (json.loads(m.group(1).replace("<\\/", "</")).get("verdicts")) or {}


def load_cards(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[d["id"]] = d
    return out


def sibling_fingerprints(feedback_dir: Path, book: str) -> dict[str, str]:
    """`{pNNNN: fingerprint}`：该书已有事件里 seed_admit 页级产物指纹（后写的覆盖先写的）。"""
    fps: dict[str, str] = {}
    evdir = feedback_dir / "events"
    for f in sorted(evdir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                t = json.loads(line).get("target") or {}
            except ValueError:
                continue
            pk = ((t.get("anchor") or {}).get("product_key")) or {}
            if t.get("book") == book and pk.get("step") == STEP and pk.get("fingerprint"):
                fps[pk["key"]] = pk["fingerprint"]
    return fps


def live_fingerprint(book: str, page: int) -> str | None:
    """工作区产物清单里的现值；没有产物/读不到 → None。"""
    try:
        from open_guji_cv.core.spec import page_key
        from open_guji_cv.products.store import ProductStore
        man = ProductStore().manifest(book, STEP)
        rec = man.get(page_key(page)) if man else None
        return getattr(rec, "fingerprint", None) or None
    except Exception:  # noqa: BLE001 — anchor 是附加信息，不拦写入
        return None


def book_codepoints(ws: Path | None, book: str) -> dict[str, str]:
    if not ws:
        return {}
    import yaml
    y = ws / "books" / f"{book}.yaml"
    if not y.exists():
        return {}
    return {str(k): str(v) for k, v in ((yaml.safe_load(y.read_text(encoding="utf-8")) or {})
                                        .get("codepoints") or {}).items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html", help="Artifact read 读回的审查页 HTML")
    ap.add_argument("--cards", default=str(ROOT / "artifacts" / "vol03_shadow_review_cards.jsonl"))
    ap.add_argument("--feedback-dir", required=True, help="工作区 feedback/ 目录（事件写到其 events/ 下）")
    ap.add_argument("--batch", default="vol03-shadow-review-0929")
    ap.add_argument("--ws", help="工作区根（读 books/<book>.yaml 的 codepoints 做冲突自检；可省）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    from open_guji_cv.feedback.anchor import parse_cell_key

    verdicts, cards = load_verdicts(Path(a.html)), load_cards(Path(a.cards))
    fdir = Path(a.feedback_dir)
    log = EventLog(root=fdir)
    have = {e.target.key: e for e in log.read(a.batch)}
    seq0 = log.latest_seq(a.batch)
    sib_cache: dict[str, dict[str, str]] = {}

    new, skipped, changed, unknown = [], Counter(), [], []
    for cid, v in verdicts.items():
        card, verdict = cards.get(cid), v.get("v")
        pk = parse_cell_key(cid)
        if card is None or pk is None:
            unknown.append(cid)
            continue
        if verdict not in ("a", "b", "neither"):
            skipped[verdict or "空"] += 1
            continue
        book, page, col, slot, sub = pk
        if verdict == "neither":
            payload = {"v": "seg_defect", "quality": "truncated", "shape": ""}
        else:
            payload = {"v": "confirm", "shape": card[verdict]}
        prior = have.get(cid)
        if prior is not None:
            pp = prior.payload
            if (pp.get("v"), pp.get("shape")) != (payload["v"], payload["shape"]):
                changed.append((cid, pp.get("v"), pp.get("shape"), payload["v"], payload["shape"]))
            skipped["已写过"] += 1
            continue
        pkey = f"p{page:04d}"
        fp = live_fingerprint(book, page)
        src = "manifest"
        if not fp:
            sib = sib_cache.setdefault(book, sibling_fingerprints(fdir, book))
            fp, src = sib.get(pkey), "sibling_event"
        pk_d = {"step": STEP, "key": pkey}
        if fp:
            pk_d["fingerprint"] = fp
        anchor = {"product_key": pk_d, "fp_source": src if fp else "none"}
        payload.update({"via": "shadow-review", "client_ts": v.get("t")})
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((v.get("t") or 0) / 1000)) if v.get("t") else None
        target = EventTarget(step=STEP, unit="cell", key=cid, book=book, page=page, col=col,
                             slot=slot, anchor=anchor)
        new.append((cid, target, payload, ts))

    # 按裁决时间排，seq 稳定可复现
    new.sort(key=lambda x: (x[3] or "", x[0]))
    events = [make_event(a.batch, seq0 + i + 1, "confirm", tg, pl, actor="user", ts=ts)
              for i, (_, tg, pl, ts) in enumerate(new)]

    cp = book_codepoints(Path(a.ws) if a.ws else None, "vol03")
    conflicts = sorted({(e.payload["shape"], cp[e.payload["shape"]])
                        for e in events if e.payload.get("shape") in cp})

    print(f"页上已裁 {len(verdicts)}；新写 {len(events)}；跳过 {dict(skipped)}")
    if unknown:
        print(f"⚠ 卡片映射里找不到/键解析不了：{unknown}")
    for c in changed:
        print(f"⚠ 页上裁决与已写事件不同（未改，仅报告）：{c}")
    nfp = sum(1 for e in events if "fingerprint" not in e.target.anchor["product_key"])
    if nfp:
        print(f"⚠ {nfp} 条事件没找到 seed_admit 指纹（anchor 无 fingerprint）")
    if conflicts:
        print(f"⚠ 码位冲突（所选刻形会被本书 codepoints 归一）：{conflicts}")
    elif cp:
        print(f"码位自检：所选刻形均不在本书 codepoints {cp} 的被统一项里，无冲突")
    if a.dry_run:
        print("dry-run，未写入")
        return
    n = log.append(events)
    print(f"→ 写入 {n} 条 → {log.batch_path(a.batch)}")


if __name__ == "__main__":
    main()
