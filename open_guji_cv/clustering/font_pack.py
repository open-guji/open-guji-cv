"""字体域预建件（2026-10-20，GUJI-647 第 3 项）：新容器不再渲染字体域，整表拷进 glyph.db。

## 为什么

`glyph-db rebuild` 会删掉重建 `glyph.db`，之后要 `import-font` 把两套字体（jigmo、iming）按字表
逐字渲染、归一、提特征再入库：云端 4 核 12–15 分钟，glyph.db 从约 230 MB 涨到约 3.1 GB。
每个新容器、每次重建都付一遍，而字体域与书无关，是「字体文件 + 字表 + 渲染／归一／特征代码」的
确定性函数——同样的输入，哪台机器渲染都是同一批行。

## 做法

- **键**（`pack_key`）：字体文件 sha256、字表 sha256、是否竖排、渲染链上各模块的代码指纹
  （`font_glyphs`／`canonical`／`normalize`／`features`／`glyph_db`，同 `engine.code_hash_of_module`）、
  派生算法版本（`glyph_db.ALGO_VERSIONS`）、PIL／FreeType／OpenCV／numpy 版本。任一样变了键就变，旧包碰不到。
  按整个模块算是有意的保守：`font_glyphs` 里不碰渲染的改动（比如导入流程）也会换键，宁可白渲一次，不让改过的
  渲染代码拷到旧字形。所以**这几个模块合进来之后，在一台机器上渲一次、`font-pack-push` 推一次**，别的机器才命中。
- **包**：一个只装这套字体行的 SQLite（`sources`／`instances`／`glyphs`／`exemplars`／`derived`／
  `font_manifests` 六张表，结构抄 glyph.db），本机放 `cache_root()/fontdb/<edition>-<键>.sqlite`，
  R2 放 `derived/fontdb/<同名>`（gzip，`datastore.packs.push_file`）。
- **导入**（`import_pack`）：`ATTACH` 包，逐表 `INSERT … SELECT`；`glyph_id` 是目标库自增的，
  `exemplars` 按 `(edition_tag, char)` 换成目标库的 id。冲突时的写法与 `font_glyphs.import_font`
  逐字入库时相同（实例、字形只更新图与时间；派生、样例整行替换），所以拷进来的行与现渲染的
  逐列相同，只有时间戳是包里的。`font_domain_fingerprint` 只看 `font_manifests`，同样逐字相同，
  读字体域的步（Step5-b）不因换了来源而过期。
- **推**：手动（`guji glyph-db font-pack push`，正式令牌），同语言模型（用户 10-20 定）。**取**：`import-font`
  先找本机包，再找 R2（要 `GUJI_DATA_TOKEN`，读令牌就够；`GUJI_DERIVED_FETCH=0` 关），都没有才渲染。

本模块不在任何 Step 的 `code_deps` 里，改它不让各册过期。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

PACK_V = 1
#: 渲染 → 归一 → 提特征 → 入库这一路上的模块：任一改了，渲出来的行就可能不同
CODE_MODULES = ("open_guji_cv.clustering.font_glyphs", "open_guji_cv.clustering.canonical",
                "open_guji_cv.clustering.normalize", "open_guji_cv.clustering.features",
                "open_guji_cv.clustering.glyph_db")
TABLES = ("sources", "instances", "glyphs", "exemplars", "derived")
R2_DIR = "fontdb"


def _sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _lib_versions() -> dict:
    import cv2
    import numpy as np
    import PIL
    from PIL import features
    return {"PIL": PIL.__version__, "freetype": features.version("freetype2"),
            "cv2": cv2.__version__, "numpy": np.__version__}


def pack_key(spec, chars, vertical: bool) -> str:
    """这套字体、这份字表、这版代码渲出来的字体域的内容键（见模块头）。"""
    from ..core.engine import code_hash_of_module
    from .glyph_db import ALGO_VERSIONS
    doc = {"v": PACK_V, "edition": spec.edition_tag,
           "fonts": [[Path(p).name, _sha_file(Path(p))] for p in spec.font_paths],
           "chars": hashlib.sha256("".join(chars).encode("utf-8")).hexdigest(),
           "vertical": bool(vertical), "code": {m: code_hash_of_module(m) for m in CODE_MODULES},
           "algo": ALGO_VERSIONS, "libs": _lib_versions()}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def pack_name(edition: str, key: str) -> str:
    return f"{re.sub(r'[^A-Za-z0-9_.-]', '_', edition)}-{key}.sqlite"


def local_dir() -> Path:
    from ..core.workspace import cache_root
    return cache_root() / "fontdb"


def _schema(conn, table: str) -> str:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not row:
        raise ValueError(f"glyph.db 里没有表 {table}")
    return row[0]


def export_pack(db, edition: str, dest: Path) -> dict:
    """把库里 `edition` 这套字体的行导成一个包（覆盖 `dest`）。返回 `{instances, bytes}`。"""
    from .glyph_fp import FONT_TABLE, FONT_TABLE_SQL
    conn = db.conn
    if not conn.execute("SELECT 1 FROM sources WHERE source_id=? AND kind='font'", (edition,)).fetchone():
        raise ValueError(f"库里没有字体域 {edition}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.tmp{os.getpid()}")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(tmp)
    for t in TABLES:
        out.execute(_schema(conn, t))
    out.execute(FONT_TABLE_SQL)
    out.commit()
    out.close()
    conn.commit()
    conn.execute("ATTACH DATABASE ? AS p", (str(tmp),))
    try:
        conn.execute("INSERT INTO p.sources SELECT * FROM main.sources WHERE source_id=?", (edition,))
        conn.execute("INSERT INTO p.instances SELECT * FROM main.instances WHERE source_id=?", (edition,))
        conn.execute("INSERT INTO p.glyphs SELECT * FROM main.glyphs WHERE edition_tag=?", (edition,))
        conn.execute("INSERT INTO p.exemplars SELECT e.* FROM main.exemplars e "
                     "JOIN main.glyphs g ON g.glyph_id=e.glyph_id WHERE g.edition_tag=?", (edition,))
        conn.execute("INSERT INTO p.derived SELECT d.* FROM main.derived d "
                     "JOIN main.instances i ON i.instance_id=d.instance_id WHERE i.source_id=?", (edition,))
        conn.execute(f"INSERT INTO p.{FONT_TABLE} SELECT * FROM main.{FONT_TABLE} WHERE edition_tag=?", (edition,))
        n = conn.execute("SELECT count(*) FROM p.instances").fetchone()[0]
        conn.commit()
    except BaseException:
        conn.rollback()
        conn.execute("DETACH DATABASE p")
        tmp.unlink(missing_ok=True)
        raise
    conn.execute("DETACH DATABASE p")
    os.replace(tmp, dest)
    return {"instances": int(n), "bytes": dest.stat().st_size}


def _cols(conn, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def import_pack(db, path: Path, edition: str) -> dict:
    """把包里 `edition` 的行拷进 `db`（见模块头「导入」）。返回 `{edition, glyphs}`。"""
    from .glyph_fp import FONT_TABLE, FONT_TABLE_SQL
    conn = db.conn
    conn.commit()
    conn.execute(FONT_TABLE_SQL)
    conn.execute("ATTACH DATABASE ? AS p", (str(path),))
    try:
        if not conn.execute("SELECT 1 FROM p.sources WHERE source_id=?", (edition,)).fetchone():
            raise ValueError(f"包 {path.name} 里没有 {edition}")
        # 列按名字对：目标库可能比包多出后加的列（如 instances.fidelity），缺的留缺省
        src_cols = {t: set(_cols(conn, "p", t)) for t in TABLES}
        cols = {t: [c for c in _cols(conn, "main", t) if c in src_cols[t]] for t in TABLES}
        cols["glyphs"].remove("glyph_id")               # 目标库自增，exemplars 下面按 (edition, char) 换

        def ins(table: str, where: str, tail: str) -> None:
            cl = ", ".join(cols[table])
            conn.execute(f"INSERT INTO main.{table} ({cl}) SELECT {cl} FROM p.{table} WHERE {where} {tail}",
                         (edition,))
        ins("sources", "source_id=?",
            "ON CONFLICT(source_id) DO UPDATE SET title=excluded.title, notes=excluded.notes, "
            "script_style=excluded.script_style, kind='font'")
        ins("instances", "source_id=?",
            "ON CONFLICT(instance_id) DO UPDATE SET patch_png=excluded.patch_png, updated_at=excluded.updated_at")
        ins("glyphs", "edition_tag=?", "ON CONFLICT(edition_tag, char) DO UPDATE SET updated_at=excluded.updated_at")
        conn.execute("INSERT OR REPLACE INTO main.exemplars (glyph_id, instance_id, role, added_at) "
                     "SELECT mg.glyph_id, e.instance_id, e.role, e.added_at FROM p.exemplars e "
                     "JOIN p.glyphs pg ON pg.glyph_id=e.glyph_id "
                     "JOIN main.glyphs mg ON mg.edition_tag=pg.edition_tag AND mg.char=pg.char "
                     "WHERE pg.edition_tag=?", (edition,))
        dl = ", ".join(cols["derived"])
        conn.execute(f"INSERT OR REPLACE INTO main.derived ({dl}) SELECT {', '.join('d.' + c for c in cols['derived'])} "
                     "FROM p.derived d JOIN p.instances i ON i.instance_id=d.instance_id WHERE i.source_id=?",
                     (edition,))
        conn.execute(f"INSERT OR REPLACE INTO main.{FONT_TABLE} SELECT * FROM p.{FONT_TABLE} WHERE edition_tag=?",
                     (edition,))
        n = conn.execute("SELECT count(*) FROM p.instances WHERE source_id=?", (edition,)).fetchone()[0]
        conn.commit()
    except BaseException:
        conn.rollback()                                 # 半截不留；也让下面的 DETACH 不被锁住
        raise
    finally:
        conn.execute("DETACH DATABASE p")
    return {"edition": edition, "glyphs": int(n)}


def find_pack(spec, chars, vertical: bool, fetch: bool = True) -> tuple[Path | None, bool]:
    """`(包路径, 是否刚从 R2 取来)`：本机有同键的包就用；没有且 `fetch` 就去 R2 取；
    都没有返回 `(None, False)`，调用方照旧渲染。刚取来的导完就删（一套 1–1.7 GB，云端盘紧）。"""
    name = pack_name(spec.edition_tag, pack_key(spec, chars, vertical))
    f = local_dir() / name
    if f.exists():
        return f, False
    if fetch:
        from ..core.derived import fetch_derived
        if fetch_derived(R2_DIR, name, f):
            return f, True
    return None, False


def save_pack(db, spec, chars, vertical: bool) -> Path:
    """把库里这套字体导成本机包（键按当前字体文件、字表、代码算）。"""
    f = local_dir() / pack_name(spec.edition_tag, pack_key(spec, chars, vertical))
    export_pack(db, spec.edition_tag, f)
    return f
