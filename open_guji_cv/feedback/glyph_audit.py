# -*- coding: utf-8 -*-
"""字形库体检裁决的消费者：`glyph_audit` 事件 → 撤库 / 改字 / 白名单。

卡从 `clustering/glyph_selfcheck.py` 来（控制台字形库页「体检」tab），问的是
「库里这个刻例定的字对不对」。四种裁决（`payload.v`）：

| v | 做什么 |
|---|---|
| `ok` | 没问题，只记账——下轮体检同一张卡（同实例、同旗、同对手）不再出 |
| `near_form` | 两个都没错，只是形近 / 异体——记账，并记进 `near_forms.jsonl`（形近字对的本书人裁证据） |
| `evict` | 撤库：`payload.target` 那个实例（本例或本书里的对手）删出库，下次跑到那一格重新出卡 |
| `relabel` | 本例其实是 `payload.char`：撤掉旧的、以人裁身份按新字重进库（同 id、同图块） |
| `fidelity` | 标一致程度（字形库 04）：`payload.fidelity` ∈ exact / nearest / unencoded / 空（撤销），`nearest`/`unencoded` 必带 `payload.ids`（刻例的实际结构），且这条 IDS 在 Unicode 里反查不到同结构字（`ids_lookup`），查到了要人确认后带 `force`；`payload.targets` 可一次标多例 |

`relabel` 也可以顺带 `fidelity`/`ids`（「改成 X，但只是最近似」）。

所有裁决都写 `<库目录>/glyph_selfcheck/decisions.jsonl`（后到覆盖）。撤库与改字
改的是 glyph.db，裁完要 `glyph-db export` 把真源带进 git（总账页会亮 store 漂移）。
对手在**别的工作区**的，这里不动它的库——去那本书的字形库页处理。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .consumers import ConsumeResult


def glyph_audit(events, db_path: str | None = None, dry_run: bool = False, **kw) -> ConsumeResult:
    from ..clustering.audit import evict_instance
    from ..clustering.glyph_db import GlyphDB
    from ..core.workspace import glyph_db_path

    res = ConsumeResult("glyph_audit", n_events=len(events))
    if dry_run:
        res.added = len(events)
        return res
    dbp = Path(glyph_db_path(db_path))
    out = dbp.parent / "glyph_selfcheck"
    out.mkdir(parents=True, exist_ok=True)
    db = GlyphDB(str(dbp))
    try:
        for e, _d in events:
            p = e.payload
            v = p.get("v")
            iid = p.get("instance_id") or e.target.key
            rec = {"key": p.get("key") or iid, "instance_id": iid, "v": v, "event": e.id,
                   "ts": e.ts, "flags": p.get("flags"), "peer": p.get("peer"),
                   "peer_char": p.get("peer_char")}
            if v in ("ok", "near_form"):
                pass
            elif v == "fidelity":
                fid = p.get("fidelity") or None
                err = _check_fidelity(fid, p.get("ids"), p.get("force"))
                if err:
                    res.errors.append(f"{e.id}: {err}")
                    res.skipped += 1
                    continue
                targets = p.get("targets") or [iid]
                n = _set_fidelity(db, targets, fid, p.get("ids"), e.id)
                rec.update(fidelity=fid, ids=p.get("ids"), targets=targets, n=n)
            elif v == "evict":
                target = p.get("target") or iid
                if not db.conn.execute("SELECT 1 FROM instances WHERE instance_id=?",
                                       (target,)).fetchone():
                    res.errors.append(f"{e.id}: 库里没有 {target}（已撤？或在别的工作区）")
                    res.skipped += 1
                    continue
                rec["target"] = target
                rec["old_char"] = evict_instance(db, target)
            elif v == "relabel":
                ch = p.get("char") or ""
                if len(ch) != 1 or ord(ch) < 0x2E80:
                    res.errors.append(f"{e.id}: 改字要给一个汉字，拿到 {ch!r}")
                    res.skipped += 1
                    continue
                row = db.conn.execute(
                    "SELECT patch_png, page, col, idx, bbox FROM instances WHERE instance_id=?",
                    (iid,)).fetchone()
                if row is None:
                    res.errors.append(f"{e.id}: 库里没有 {iid}")
                    res.skipped += 1
                    continue
                png, page, col, idx, bbox = row
                rec["old_char"] = evict_instance(db, iid)
                rec["char"] = ch
                db.admit_instance(iid, ch, bytes(png), provenance="human", shape=ch,
                                  evidence={"event": e.id, "batch": e.batch, "via": "glyph_audit",
                                            "old_char": rec["old_char"]},
                                  page=page, col=col, idx=idx,
                                  bbox=json.loads(bbox) if bbox else None)
                if p.get("fidelity"):
                    err = _check_fidelity(p["fidelity"], p.get("ids"), p.get("force"))
                    if err:
                        res.errors.append(f"{e.id}: 字已改，一致程度没标：{err}")
                    else:
                        _set_fidelity(db, [iid], p["fidelity"], p.get("ids"), e.id)
                        rec.update(fidelity=p["fidelity"], ids=p.get("ids"))
            else:
                res.errors.append(f"{e.id}: 不认识的裁决 {v!r}")
                res.skipped += 1
                continue
            with open(out / "decisions.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if v == "near_form" and p.get("peer_char"):
                with open(out / "near_forms.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"pair": sorted([p.get("char_self") or "", p["peer_char"]]),
                                         "instance_id": iid, "peer": p.get("peer"),
                                         "event": e.id, "ts": time.strftime("%Y-%m-%d")},
                                        ensure_ascii=False) + "\n")
            res.added += 1
    finally:
        db.close()
    return res


FIDELITY_SET = ("exact", "nearest", "unencoded")


def _check_fidelity(fid: str | None, ids: str | None, force: bool = False) -> str | None:
    if fid is None:
        return None                       # 撤销
    if fid not in FIDELITY_SET:
        return f"一致程度只认 {FIDELITY_SET}，拿到 {fid!r}"
    if fid in ("nearest", "unencoded"):
        if not (ids or "").strip():
            return f"{fid} 要给 IDS（刻例实际怎么写）"
        # 「Unicode 里没有」之前先反查：同结构的字已有编码就该改字，不是标最近似
        # （人看过候选、确认都不是时带 force）
        if not force:
            from ..clustering.ids_lookup import encoded_match
            got = encoded_match(ids)
            if got:
                return f"IDS {ids.strip()} 在 Unicode 里已有同结构的字：{'、'.join(got[:5])}——该改字；确认都不是再带 force"
    return None


def _set_fidelity(db, targets: list[str], fid: str | None, ids: str | None, event_id: str) -> int:
    by = json.dumps({"event": event_id, "at": time.strftime("%Y-%m-%d")}, ensure_ascii=False)
    n = 0
    for t in targets:
        if fid in ("nearest", "unencoded"):
            cur = db.conn.execute("UPDATE instances SET fidelity=?, fidelity_by=?, ids=? "
                                  "WHERE instance_id=?", (fid, by, ids.strip(), t))
        else:
            cur = db.conn.execute("UPDATE instances SET fidelity=?, fidelity_by=? "
                                  "WHERE instance_id=?", (fid, by if fid else None, t))
        n += cur.rowcount
    db.conn.commit()
    return n


GLYPH_AUDIT_CONSUMERS = {"glyph_audit": glyph_audit}
