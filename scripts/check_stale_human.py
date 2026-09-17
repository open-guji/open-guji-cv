# -*- coding: utf-8 -*-
"""查「切分改动后过期的人裁字位」——人裁钉住的那一格已经不是当初看的那一格。

## 为什么需要它

`seed_admit` 的纪律是「人裁一票定案，任何自动通道不许改写」。前提是那一格没变。
切分改一次（Step2 去框、Step3 候选池/U-Net 裁判…），格重新分、slot 号整体偏移，
旧裁决就钉到了错误的格上，`human` 通道压过库匹配与上下文，**整段跟着错且不报错**。

2026-09-17 vol02 实测：61 条这种位，撤掉与整理本不一致的 56 条后，全书一致率
97.43% → 97.61%、`sub.other` 335 → 288。

## 签名

**人裁位的字 == 列内上一位的字**。错位一格的直接后果就是重字。这个签名会有少量
误报（原文确实叠字，如「自自」「一一」），所以再拿整理本对齐做第二道：与整理本
一致的不算过期。两条都中才报。

    python scripts/check_stale_human.py --book vol02
    python scripts/check_stale_human.py --book vol02 --retire    # 改 provenance，撤下

撤下 = `admissions.provenance` 从 `human` 改成 `human_stale_<今天>`；不删账，
`_human_shapes` 只认 `'human'`，所以这些位回到自动通道。要恢复把 provenance 改回去。
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from collections import Counter

from open_guji_cv.core.step import page_key
from open_guji_cv.core.workspace import glyph_db_path
from open_guji_cv.products import kinds as _k  # noqa: F401
from open_guji_cv.products.store import ProductStore


def find(book: str, store: ProductStore | None = None) -> list[dict]:
    """返回疑似过期的人裁位：[{id, page, col, slot, char, prev, ref}]。"""
    st = store or ProductStore()
    dup: list[dict] = []
    for pg in range(1, 1000):
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            if not cc.ok:
                continue
            chars = sorted(cc.chars, key=lambda r: (r.slot, r.sub or ""))
            for i, r in enumerate(chars):
                if r.channel != "human" or not i:
                    continue
                prev = chars[i - 1].char
                if r.char is not None and r.char == prev:
                    dup.append({"id": r.id, "page": pg, "col": cc.col, "slot": r.slot,
                                "char": r.char, "prev": prev})
    if not dup:
        return []
    # 第二道：整理本怎么说
    from open_guji_cv.gold.v2_align import align_book
    refs: dict[str, str] = {}
    for g in align_book(book, sorted({d["page"] for d in dup}), st):
        if g.anchored:
            for c in g.chars:
                if c.reading:
                    refs[c.id] = c.reading
    for d in dup:
        d["ref"] = refs.get(d["id"])
    return dup


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--retire", action="store_true", help="把命中的 provenance 改成 human_stale_<今天>")
    a = ap.parse_args()

    dup = find(a.book)
    stale = [d for d in dup if d["ref"] is not None and d["ref"] != d["char"]]
    keep = [d for d in dup if d not in stale]
    print(f"{a.book}：人裁位与上一位重字 {len(dup)} 条；"
          f"其中与整理本不一致（判为过期）{len(stale)}，一致或没锚上（保留）{len(keep)}")
    if stale:
        print("按页：", Counter(d["page"] for d in stale).most_common(12))
        for d in stale[:15]:
            print(f"  {d['id']:18s} 人裁 {d['char']} / 整理本 {d['ref']}  (上一位 {d['prev']})")
        if len(stale) > 15:
            print(f"  … 其余 {len(stale) - 15} 条")
    if not a.retire or not stale:
        if stale:
            print("\n（只报不改；加 --retire 才撤下）")
        return 1 if stale else 0

    prov = f"human_stale_{time.strftime('%Y%m%d')}"
    ids = [f"v2:{d['id']}" for d in stale]
    con = sqlite3.connect(glyph_db_path())
    n = con.execute(
        "UPDATE admissions SET provenance=? WHERE instance_id IN (%s) AND provenance='human'"
        % ",".join("?" * len(ids)), [prov] + ids).rowcount
    con.commit()
    print(f"\n已撤下 {n} 条（provenance → {prov}）。重跑 Step5 起这些页即可生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
