"""排除清单跟着重切走：`guji products exclusions <册> --a <重切前产物根> [--b <重切后>] [--apply]`。

为什么：`config/crop_exclusions.jsonl` 按格号（`<册>:<页>:<列>:<格>`）记，不像人裁那样带框。
切分一变（layout_prior、重切某几列），同一个号可能换成别的字：排除落到好字上把它从文本里藏掉，
真正切坏／不是字的那格却回到流程里。人裁靠绑定表（`feedback/bindings.py`）按框找回格子，名单没有。

做法（用户 10-20 同意方向）：拿**重切前**那份产物（基线，名单是对着它定的）上这个号的框，
到**重切后**的同一页找框重合（IoU ≥ `IOU_SAME`，与绑定表「框几乎没动」同一口径）的格：

| 结果 | 条件 | 名单里怎么改 |
|---|---|---|
| `same` | 同号的现格框没动 | 不动 |
| `moved` | 框没动的是另一个号（列内多切／少切一格后顺移） | 改成新号，记 `rekey_from`、`rekey_note` |
| `gone` | 没有框重合的格（切开、并格、切没了） | 撤到 `crop_exclusions_retired.jsonl`（`retired_by: rebind:gone`），那格回到正常流程，多半送人审 |
| `no_old` | 基线里找不到这个号（名单比基线旧、或那页没产物） | 不动，报出来 |
| `dup` | 改号后与名单里已有的号重了 | 撤掉这条（已有那条留着） |

缺省只出计划不写；`--apply` 改的是本机数据目录里的名单，之后 `guji db sync` 推回中心库。
名单内容一变，各册 seed_admit 都会因 `exclusions_fingerprint` 过期（名单向来如此）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

IOU_SAME = 0.85


def _iou(p, q) -> float:
    if not p or not q:
        return 0.0
    ix = max(0.0, min(p[2], q[2]) - max(p[0], q[0]))
    iy = max(0.0, min(p[3], q[3]) - max(p[1], q[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    ua = (p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - inter
    return inter / ua if ua > 0 else 0.0


def page_boxes(root: Path, book: str, page: int) -> dict[str, list[float]] | None:
    """一页所有格（含非字格）的 `bbox_page`：{格号: 框}。没有 cell_shrink 产物 → None。"""
    f = Path(root) / book / "cell_shrink" / f"p{page:04d}.json"
    if not f.is_file():
        return None
    ci = json.loads(f.read_text(encoding="utf-8")).get("char_index") or {}
    return {r["id"]: [float(v) for v in r["bbox_page"]]
            for col in ci.get("columns") or [] for r in col.get("chars") or [] if r.get("bbox_page")}


def _page_of(iid: str) -> int | None:
    parts = iid.split(":")
    try:
        return int(parts[1])
    except (IndexError, ValueError):
        return None


def read_lines(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def plan(book: str, old_root: Path, new_root: Path, ex_path: Path) -> list[dict]:
    """名单里本册每条的去向：[{iid, status, new, iou}]，按名单原顺序。"""
    lines = read_lines(ex_path)
    cache: dict[tuple[str, int], dict | None] = {}

    def boxes(root, pg):
        k = (str(root), pg)
        if k not in cache:
            cache[k] = page_boxes(root, book, pg)
        return cache[k]

    out = []
    for r in lines:
        iid = r.get("instance_id", "")
        if not iid.startswith(book + ":"):
            continue
        pg = _page_of(iid)
        old = boxes(old_root, pg) if pg is not None else None
        bb = (old or {}).get(iid)
        if bb is None:
            out.append({"iid": iid, "status": "no_old", "new": None, "iou": None})
            continue
        new = boxes(new_root, pg) or {}
        same = _iou(bb, new.get(iid))
        if same >= IOU_SAME:
            out.append({"iid": iid, "status": "same", "new": iid, "iou": round(same, 3)})
            continue
        best, bid = 0.0, None
        for k, q in new.items():
            v = _iou(bb, q)
            if v > best:
                best, bid = v, k
        if best >= IOU_SAME:
            out.append({"iid": iid, "status": "moved", "new": bid, "iou": round(best, 3)})
        else:
            out.append({"iid": iid, "status": "gone", "new": None, "iou": round(best, 3)})
    # 改号后撞上：已有那条（同号留着或别的条改过来）优先，后来的撤掉
    taken = {p["new"] for p in out if p["status"] in ("same", "no_old")} | \
            {p["iid"] for p in out if p["status"] == "no_old"}
    for p in out:
        if p["status"] == "moved":
            if p["new"] in taken:
                p["status"] = "dup"
            else:
                taken.add(p["new"])
    return out


def apply(rows: list[dict], ex_path: Path, today: str | None = None) -> dict:
    """按计划改名单：moved 改号、gone／dup 撤到 retired。返回各状态条数。"""
    today = today or time.strftime("%Y-%m-%d")
    ex_path = Path(ex_path)
    by = {p["iid"]: p for p in rows}
    keep, retire = [], []
    for r in read_lines(ex_path):
        p = by.get(r.get("instance_id"))
        if p is None or p["status"] in ("same", "no_old"):
            keep.append(r)
        elif p["status"] == "moved":
            keep.append({**r, "instance_id": p["new"], "rekey_from": r["instance_id"],
                         "rekey_note": f"重切后按框跟过来 {today}（IoU {p['iou']}）"})
        else:
            retire.append({**r, "retired": today, "retired_by": f"rebind:{p['status']}",
                           "retired_note": f"重切后找不到框重合的格（最大 IoU {p['iou']}）" if p["status"] == "gone"
                           else f"改号后与 {p['new']} 重复"})
    tmp = ex_path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8")
    tmp.replace(ex_path)
    if retire:
        with open(ex_path.with_name("crop_exclusions_retired.jsonl"), "a", encoding="utf-8") as f:
            for r in retire:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return counts(rows)


def counts(rows: list[dict]) -> dict:
    c: dict[str, int] = {}
    for p in rows:
        c[p["status"]] = c.get(p["status"], 0) + 1
    return c
