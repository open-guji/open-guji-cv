# -*- coding: utf-8 -*-
"""控制台 · 字形库总览（`/:ws/glyphlib/`）。

正本见 overview 仓 项目进展/图片初步数字化/进度/字形库/02-控制台字形库总览.md。
此前字形库页只嵌了一个要先跑任务才出内容的异体组视图，打开是空的；这里给它
「这本书收了哪些字形」的只读口径。

口径全在 `clustering/glyph_ledger.py`（CLI `glyph-db stats` 同一份）：一个
glyph.db 的全部非字体来源 = 本书套，按字聚合、按格去重。路由体只做
「解析工作区 → 调 ledger → 返回」。全部只读打开 db，不跟跑批抢写锁。

跨书：单字页顺带列出**兄弟工作区**（`discover_workspaces()`，与工作区下拉框
同一份白名单）库里同一个字的刻例，图片 URL 带对方的 `ws=`，由中间件切过去取。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from ..errors import maps_http

router = APIRouter()


def _paths():
    from ...core.workspace import glyph_db_path, glyph_store_path
    db = glyph_db_path()
    if not Path(db).exists():
        raise HTTPException(404, f"这个工作区没有字形库：{db}")
    return db, glyph_store_path()


def _siblings() -> list[dict]:
    """其它工作区的字形库：[{ws, name, db}]，不含当前这个。"""
    from ...core.workspace import GLYPH_DB_REL, workspace_root
    from .workspace import discover_workspaces
    cur = workspace_root()
    cur = cur.resolve() if cur else None
    out = []
    for w in discover_workspaces():
        p = Path(w["path"])
        if cur is not None and p.resolve() == cur:
            continue
        db = p / GLYPH_DB_REL
        if db.exists():
            out.append({"ws": w["id"], "name": w["name"], "db": db})
    return out


@router.get("/api/glyphlib/summary")
@maps_http
def api_glyphlib_summary() -> dict:
    """总账：各来源、本书套（字种/刻例/来路/单例）、字体覆盖、store 漂移。
    另附兄弟工作区的字种数与共有字数（跨书比对的素材量）。"""
    from ...clustering.glyph_ledger import char_table, library_summary
    db, store = _paths()
    s = library_summary(db, store)
    mine = {r["char"] for r in char_table(db)}
    others = []
    for o in _siblings():
        try:
            theirs = {r["char"] for r in char_table(o["db"])}
        except Exception as e:           # 别的库坏了不该拖垮本页
            others.append({"ws": o["ws"], "name": o["name"], "error": str(e)})
            continue
        others.append({"ws": o["ws"], "name": o["name"], "chars": len(theirs),
                       "common": len(mine & theirs)})
    s["others"] = others
    return s


@router.get("/api/glyphlib/chars")
@maps_http
def api_glyphlib_chars() -> dict:
    """字表：一字一行（刻例数按格去重、来路分布、字头所在来源、字体里有没有）。
    过滤与排序在前端做——两本书都只有几千行。另附兄弟工作区的字集，
    供「只看本书独有 / 与某书共有」过滤。"""
    from ...clustering.glyph_ledger import char_table
    from ...clustering.glyph_selfcheck import load_findings
    db, _ = _paths()
    rows = char_table(db)
    # 体检算过的「本字与各字体的最优相似度」（按字取刻例中位）；没跑过体检就没有
    char_font = (load_findings()[0] or {}).get("char_font", {})
    for r in rows:
        r["font_sim"] = char_font.get(r["char"])
    shared: dict[str, list[str]] = {}
    for o in _siblings():
        try:
            for r in char_table(o["db"]):
                shared.setdefault(r["char"], []).append(o["ws"])
        except Exception:
            continue
    for r in rows:
        r["also_in"] = shared.get(r["char"], [])
    return {"chars": rows}


@router.get("/api/glyphlib/char/{char}")
@maps_http
def api_glyphlib_char(char: str, others: int = 12) -> dict:
    """单字页：本书全部刻例（按来路）＋ 字体渲染 ＋ 兄弟工作区同字刻例（各取前 N）。"""
    from ...clustering.glyph_ledger import char_detail
    db, _ = _paths()
    d = char_detail(db, char)
    d["others"] = []
    for o in _siblings():
        try:
            od = char_detail(o["db"], char)
        except Exception:
            continue
        if od["exemplars"]:
            d["others"].append({"ws": o["ws"], "name": o["name"],
                                "n": len(od["exemplars"]),
                                "exemplars": od["exemplars"][:others]})
    return d


def _crop_to_ink(png: bytes, pad: float = 0.12) -> bytes:
    """显示用：裁到墨迹外接正方形再留一圈白边。库里的 canonical 字只占画布四成上下
    （北行 0.3），缩略图里字就小得看不清（用户 2026-09-25）。只改显示，不动库。"""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return png
    ys, xs = np.where(img < 128)
    if len(ys) == 0:
        return png
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    side = int(max(y1 - y0, x1 - x0) * (1 + 2 * pad)) + 2
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    canvas = np.full((side, side), 255, np.uint8)
    sy0, sx0 = cy - side // 2, cx - side // 2
    ay0, ax0 = max(sy0, 0), max(sx0, 0)
    ay1, ax1 = min(sy0 + side, img.shape[0]), min(sx0 + side, img.shape[1])
    canvas[ay0 - sy0:ay1 - sy0, ax0 - sx0:ax1 - sx0] = img[ay0:ay1, ax0:ax1]
    return cv2.imencode(".png", canvas)[1].tobytes()


@router.get("/api/glyphlib/patch/{instance_id}.png")
@maps_http
def api_glyphlib_patch(instance_id: str, crop: bool = True) -> Response:
    """刻例图块（库里存的 canonical 原图，不是归一化图——人看的是原形）。"""
    import sqlite3
    db, _ = _paths()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = c.execute("SELECT patch_png FROM instances WHERE instance_id=?",
                        (instance_id,)).fetchone()
    finally:
        c.close()
    if row is None:
        raise HTTPException(404, f"库里没有这个实例：{instance_id}")
    png = bytes(row[0])
    return Response(_crop_to_ink(png) if crop else png, media_type="image/png",
                    headers={"Cache-Control": "max-age=300"})


# ── 体检（字形库 03）────────────────────────────────────


@router.get("/api/glyphlib/audit")
@maps_http
def api_glyphlib_audit(all: bool = False) -> dict:
    """体检结果（`glyph-db selfcheck` 落的 findings.jsonl）＋ 裁决账。
    默认只回未裁的卡；`all=1` 连已裁的一起回（带 `decision`）。"""
    from ...clustering.glyph_selfcheck import FLAG_LABELS, decisions, load_findings, out_dir
    import sqlite3
    db, _ = _paths()
    meta, rows = load_findings()
    dec = decisions()
    # 体检之后撤掉的实例（别处撤库、同格副本清理）不再出卡
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        alive = {r[0] for r in c.execute("SELECT instance_id FROM exemplars")}
    finally:
        c.close()
    n_gone = sum(1 for r in rows if r["instance_id"] not in alive)
    rows = [r for r in rows if r["instance_id"] in alive]
    for r in rows:
        r["decision"] = dec.get(r["key"])
    todo = [r for r in rows if r["decision"] is None]
    return {"meta": meta, "flag_labels": FLAG_LABELS, "out": str(out_dir()), "n_gone": n_gone,
            "n_total": len(rows), "n_decided": len(rows) - len(todo),
            "findings": rows if all else todo}


class AuditDecideIn(BaseModel):
    key: str
    instance_id: str
    v: str                      # ok | near_form | evict | relabel | fidelity
    target: str | None = None   # evict 撤哪个（本例或本书里的对手）
    char: str | None = None     # relabel 改成什么字
    char_self: str | None = None
    peer: str | None = None
    peer_char: str | None = None
    flags: list[str] = []
    fidelity: str | None = None  # exact | nearest | unencoded（字形库 04）
    ids: str | None = None       # nearest / unencoded 时刻例的实际结构
    targets: list[str] = []      # fidelity 一次标多例
    force: bool = False          # nearest/unencoded 的 IDS 在 Unicode 里已有同结构字时，人确认仍要这样标


@router.post("/api/glyphlib/audit/decide")
@maps_http
def api_glyphlib_audit_decide(d: AuditDecideIn) -> dict:
    """写一条 `glyph_audit` 事件并立即消费（撤库 / 改字 / 白名单）。

    批次固定 `glyphlib-audit`：与定字（`*-decide`）、复核（`*-collate`）分开记账。"""
    from ...feedback.consumers import route_and_consume
    from ...feedback.events import EventTarget, make_event
    from ...feedback.routes import RouteTable
    from .. import deps

    if d.v not in ("ok", "near_form", "evict", "relabel", "fidelity"):
        return {"ok": False, "error": f"不认识的裁决 {d.v}"}
    batch = "glyphlib-audit"
    log = deps.event_log()
    ev = make_event(batch, log.latest_seq(batch) + 1, "glyph_audit",
                    EventTarget(step="glyph_audit", unit="cell", key=d.instance_id),
                    d.model_dump())
    log.append([ev])
    out = {"ok": True, "event": ev.id}
    try:
        table = RouteTable.load(log.root / "routes.yaml")
        res = route_and_consume(log, batch, table, deps.verdict_store())
        got = [x for x in res["results"] if x["consumer"] == "glyph_audit"]
        out["consumed"] = got
        if got and got[0]["errors"]:
            out["ok"] = False
            out["error"] = "；".join(got[0]["errors"][:2])
    except Exception as exc:                       # noqa: BLE001
        out["consume_error"] = f"{type(exc).__name__}: {exc}"
    return out


@router.get("/api/glyphlib/font/{char}.png")
@maps_http
def api_glyphlib_font(char: str, font: str = "", crop: bool = True) -> Response:
    """一个字的字体渲染图。

    给了 `font`（`glyph_selfcheck.FONT_SETS` 里的名字：iming / jigmo / genryu / genwan /
    genyo / kangxi）就现场用引擎仓 `fonts/` 的字体档渲染；不给就取库里字体域的那张——
    本库没导就去兄弟工作区的库里找（四庫的库没导，北行的库导了 I.Ming）。"""
    import sqlite3
    if font:
        import cv2
        from ...clustering.glyph_selfcheck import FONT_SETS, font_renderer
        if font not in FONT_SETS:
            raise HTTPException(404, f"没有这套字体：{font}")
        r = font_renderer(font)
        img = r.render(char) if r and len(char) == 1 else None
        if img is None:
            raise HTTPException(404, f"{font} 里没有「{char}」")
        png = cv2.imencode(".png", img)[1].tobytes()
        return Response(_crop_to_ink(png) if crop else png, media_type="image/png",
                        headers={"Cache-Control": "max-age=86400"})
    db, _ = _paths()
    for p in [db] + [o["db"] for o in _siblings()]:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            row = c.execute(
                "SELECT i.patch_png FROM glyphs g JOIN exemplars e ON e.glyph_id=g.glyph_id "
                "JOIN instances i ON i.instance_id=e.instance_id "
                "WHERE g.edition_tag LIKE 'font:%' AND g.char=? LIMIT 1", (char,)).fetchone()
        finally:
            c.close()
        if row:
            png = bytes(row[0])
            return Response(_crop_to_ink(png) if crop else png, media_type="image/png",
                            headers={"Cache-Control": "max-age=3600"})
    raise HTTPException(404, f"没有找到「{char}」的字体渲染")


@router.get("/api/glyphlib/ids-lookup")
@maps_http
def api_glyphlib_ids_lookup(q: str, near: int = 12) -> dict:
    """IDS 反查（`clustering/ids_lookup.py`）：这条结构 Unicode 里有没有字。
    标「最近似码位 / 无码」之前先查——很多「没有」的字其实在扩展区有编码。
    每个命中另标本书库里有没有这个字（`in_book`）。"""
    import sqlite3
    from ...clustering.ids_lookup import lookup
    r = lookup(q, near=near)
    try:
        db, _ = _paths()
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            have = {row[0] for row in c.execute(
                "SELECT DISTINCT char FROM glyphs WHERE edition_tag NOT LIKE 'font:%'")}
        finally:
            c.close()
    except HTTPException:
        have = set()
    for h in r["hits"]:
        h["in_book"] = h["char"] in have
    return r
