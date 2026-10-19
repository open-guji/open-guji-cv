"""中心库副本的 glyph.db 三件事：指纹、导出、重建（``datastore.workcopy.GlyphHooks`` 的实现）。

datastore 在第 1 层，不 import 聚类；这里（第 4 层）把聚类层的函数装进去，供 ``guji db``、
``guji store``、``close-check`` 共用。"""
from __future__ import annotations

from pathlib import Path


def _db_path(ws_dir: Path) -> Path:
    from ..core.workspace import glyph_db_path, reset_workspace_override, set_workspace_override
    tok = set_workspace_override(str(ws_dir))
    try:
        return Path(glyph_db_path())
    finally:
        reset_workspace_override(tok)


def rebuild_db(ws_dir: Path, store: Path, db_path: Path) -> dict:
    """同 ``guji glyph-db rebuild --no-replay --no-borrow --store <store>``。"""
    import yaml
    from ..clustering.glyph_db import assert_db_not_silently_empty, rebuild_from_store
    wcfg = yaml.safe_load((Path(ws_dir) / "workspace.yaml").read_text(encoding="utf-8")) or {}
    if ((wcfg.get("glyph_lib") or {}).get("borrow")):
        raise SystemExit("workspace.yaml 配了 glyph_lib.borrow（借库）：db pull 暂不支持借库，"
                         "请先用 guji glyph-db rebuild")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    summary = rebuild_from_store(store, db_path)
    assert_db_not_silently_empty(db_path, store)
    return summary


def export_db(db_path: Path, store: Path) -> dict:
    """同 ``guji glyph-db export``（`guji store commit` 用的同一个函数）。"""
    from ..clustering.glyph_db import GlyphDB, export_store
    db = GlyphDB(db_path)
    try:
        return export_store(db, store)
    finally:
        db.close()


def export_signature(db: Path) -> str:
    """glyph.db 里会导出成字形库账本的那部分内容的哈希（字体域不导出，也不算）；库不存在 → ""。

    「要不要先导出再比」靠它。不能用匹配器的库指纹（``glyph_match.db_fingerprint``）：只标了／撤了近似字、
    改了实例的 label／ids 时匹配器指纹不变，账本却要变，用它就会漏推。原是 ``scripts/glyph_store_sync.py``
    的 ``db_signature``（该脚本随 GUJI-611 退役）。"""
    import hashlib
    import sqlite3
    if not Path(db).exists():
        return ""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    h = hashlib.sha256()
    try:
        fe = {r[0] for r in c.execute("SELECT edition_tag FROM sources WHERE kind='font'")}
        for q in ("SELECT e.instance_id, g.edition_tag, g.char FROM exemplars e "
                  "JOIN glyphs g USING(glyph_id) ORDER BY e.instance_id",
                  "SELECT instance_id, label, semantic, unicode_cp, ids, updated_at, "
                  "length(patch_png) FROM instances ORDER BY instance_id",
                  "SELECT instance_id, char, provenance, admitted_at FROM admissions ORDER BY instance_id",
                  "SELECT edition_tag, char, semantic, unicode_cp, ids, status, n_confirmed FROM glyphs "
                  "ORDER BY edition_tag, char",
                  "SELECT * FROM sources ORDER BY source_id"):
            for row in c.execute(q):
                if any(isinstance(v, str) and v in fe for v in row[:2]):
                    continue
                h.update(repr(row).encode("utf-8"))
        for q in ("SELECT key, value FROM meta WHERE key NOT LIKE 'font_manifest:%' ORDER BY key",
                  "SELECT instance_id, label, ids, note, created_at FROM approx_labels ORDER BY instance_id",
                  "SELECT instance_id, at FROM approx_clears ORDER BY instance_id, at"):
            try:
                for row in c.execute(q):
                    h.update(repr(row).encode("utf-8"))
            except sqlite3.OperationalError:
                pass                                # 旧库没有这张表
    finally:
        c.close()
    return h.hexdigest()


def glyph_hooks(ws_dir: Path):
    from ..datastore.workcopy import GlyphHooks
    return GlyphHooks(fingerprint=export_signature, export=export_db, rebuild=rebuild_db,
                      db_path=_db_path(ws_dir))


