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


def glyph_hooks(ws_dir: Path):
    from ..datastore.workcopy import GlyphHooks
    from ..steps.glyph_match import db_fingerprint

    def fp(p: Path) -> str:
        return db_fingerprint(p) if Path(p).exists() else ""
    return GlyphHooks(fingerprint=fp, export=export_db, rebuild=rebuild_db, db_path=_db_path(ws_dir))


