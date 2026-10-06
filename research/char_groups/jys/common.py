# -*- coding: utf-8 -*-
"""己已巳分类器离线评测的公共件（overview#443）。只读 dataset char-groups/jys，不碰管线。

口径（dataset char-groups/README「评测口径」）：强真值 = A_human + B_vision，按册报；
dev = vol01(extra)/02/03，val = vol04（留出，定型前不看错例、不调参），vol05 = pool 里有 19 格人裁，单列。
给字率 = 给了字的格 / 强真值格；给字准确率 = 给对 / 给了字的格；弃权率 = 1 - 给字率。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DATASET = Path(os.environ.get("GUJI_DATASET", "/home/user/open-guji-dataset"))
JYS_DIR = DATASET / "char-groups" / "jys"
FAM = "己已巳"
STRONG = ("A_human", "B_vision")
DEV = ("vol01", "vol02", "vol03")
VAL = ("vol04",)
POOL_GOLD = ("vol05",)


def load_items() -> list[dict]:
    return [json.loads(l) for l in (JYS_DIR / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def strong(items: list[dict]) -> list[dict]:
    """core 格、强真值、真值在组内（排除「巴」这类组外字）。"""
    return [x for x in items if x["core"] and x["gold_tier"] in STRONG and x["gold"] in FAM]


def ctx(x: dict, n: int = 30) -> tuple[str, str]:
    """刻本读序前/后各 n 字（□ 保留，表示未知）。"""
    return (x.get("left") or "")[-n:], (x.get("right") or "")[:n]


def metrics(rows: list[dict], pred: dict[str, str | None]) -> dict:
    """rows：强真值格；pred：id → 字或 None（弃权）。"""
    n = len(rows)
    given = [x for x in rows if pred.get(x["id"])]
    ok = [x for x in given if pred[x["id"]] == x["gold"]]
    return {"n": n, "given": len(given), "ok": len(ok), "wrong": len(given) - len(ok),
            "give_rate": round(len(given) / n, 3) if n else None,
            "acc": round(len(ok) / len(given), 3) if given else None,
            "abstain": round(1 - len(given) / n, 3) if n else None}


def by_book(rows: list[dict], pred: dict[str, str | None], books=None) -> dict:
    out = {}
    for b in sorted({x["book"] for x in rows}):
        if books and b not in books:
            continue
        out[b] = metrics([x for x in rows if x["book"] == b], pred)
    return out


def fmt(m: dict) -> str:
    return (f"给字 {m['given']}/{m['n']}（{m['give_rate']:.0%}）  对 {m['ok']}  错 {m['wrong']}  "
            f"准确率 {('%.1f%%' % (100 * m['acc'])) if m['acc'] is not None else '—'}  弃权 {m['abstain']:.0%}")
