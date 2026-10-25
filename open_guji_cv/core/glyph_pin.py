"""册钉字形库（glyph_pin）：册 yaml 写 `glyph_pin: N`，这一册用**第 N 版字形库的内容**跑（GUJI-727）。

设计见 `doc/design/字形库按版本钉-细设计.md`。三种状态：

| 册 | 读哪个库 | 指纹 |
|---|---|---|
| 没钉 | 当前 `glyph.db` | 一字不变 |
| 钉了 N，没有快照 g<N>（旧做法，10-19 起） | 当前 `glyph.db` | `PIN_FIELDS` 换成 `glyph-gN`，只钉指纹 |
| 钉了 N，有快照 g<N> | `output/glyph-g<N>.db` | 见 `with_glyph_pin` |

**快照**（`guji glyph-db snapshot`，`ops/glyph_snapshot.py`）：数据目录 `config/glyph-pack/g<N>/manifest.json`，
登记本书字形库真源（`output/glyph_store/`）和借来的字形库每个文件的路径与 sha256；随 `config/` 进中心库，
文本按 sha 进 R2，刻例图本来就在 R2。一个号只写一次。`digest` 是条目内容的哈希，不带版本号——
号加一而内容没变时指纹不变（同语料库 10-21 口径）。

**有快照时**读字形库的步改读 `glyph-g<N>.db`（`pinned_db_path`，每个版本一个文件，同一工作区里各册互不干扰），
跟字形库内容有关的指纹换成快照 digest，于是同一册任何一页、任何时候跑，用的都是同一份库：

- `glyph_match`：`db_path`；`db_fingerprint`（软参数，只记不判过期）；`borrow_fingerprint` 取清单里记的；
- `seed_admit`：`db_path`（人裁形状、铁证、近似字、共识升档都读它）；`human_fingerprint`、`approx_fingerprint`；
- `row_segment`（只在 `roster_glyph_refine` 开时）：`roster_glyph_db`、`roster_glyph_fingerprint`（软）。

`rare_candidates.db_font_fingerprint` 不换：字体域在不在是真差别，快照库的字体域是从当前库拷的同一份。
只换按工作区解析出来的缺省库路径；书 yaml `params:` 显式指了别的库的不动。参数只读清单、不开库。

**人裁**照常写当前库；本格的裁决经事件通道（`feedback.lookup.human_chars`）立即生效，经字形库传播到别的格的
要等出新号、改钉才进本册。旧做法的由来（10-19 夜别处人裁让 vol04–10 的 seed_admit 全部过期）见设计文档。
"""
from __future__ import annotations

from pathlib import Path

#: 旧做法（没快照）里来自字形库内容、钉住后换成钉号的参数字段（只换已经有值的）。
#: 不含 `rare_candidates.db_font_fingerprint`：字体域在不在是真差别（没导字体时 Step5-b 退化），不能钉掉。
#: 不含 `glyph_match.db_fingerprint`：它本来就是软参数，不进指纹。
PIN_FIELDS: tuple[str, ...] = ("human_fingerprint", "approx_fingerprint")


def parse_pin(v) -> int | None:
    """册 yaml 的 `glyph_pin:`：`1`／`"1"`／`"g1"` → 1；空 → None。"""
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    s = s[1:] if s.startswith("g") else s
    if not s.isdigit() or int(s) < 1:
        raise ValueError(f"册 yaml 的 glyph_pin: 应是正整数（如 1 或 g1），收到 {v!r}")
    return int(s)


def pin_token(v: int) -> str:
    return f"glyph-g{int(v)}"


# ── 快照清单 ───────────────────────────────────────────────────────────────────

#: 清单目录（数据根下）：``config/glyph-pack/g<N>/manifest.json``
PACK_DIR = "config/glyph-pack"
#: 清单条目的根：本书字形库真源；借来的字形库写 ``borrow:<名字>``
OWN_ROOT = "gs"
BORROW_ROOT = "borrow:"
#: 钉版库 ``meta`` 表里记快照身份的键（``{n, digest, build}``）
META_KEY = "glyph_pin"


def pack_root(ws: Path) -> Path:
    """清单目录。迁到中心库的工作区在数据目录里（随 ``config/`` 进中心库），没迁的在工作区里。"""
    from .workspace import data_root
    return (data_root(Path(ws)) or Path(ws)) / PACK_DIR


def manifest_path(ws: Path, version: int) -> Path:
    return pack_root(ws) / f"g{int(version)}" / "manifest.json"


def versions(ws: Path) -> list[int]:
    d = pack_root(ws)
    if not d.is_dir():
        return []
    return sorted(int(x.name[1:]) for x in d.iterdir()
                  if x.is_dir() and x.name.startswith("g") and x.name[1:].isdigit() and (x / "manifest.json").exists())


_MAN_CACHE: dict[str, tuple[tuple, dict]] = {}


def load_manifest(ws: Path, version: int) -> dict | None:
    """g<N> 的清单；没有返回 None。按 (大小, 修改时间) 缓存：``params_for`` 每步都来问。"""
    import json
    mp = manifest_path(ws, version)
    try:
        st = mp.stat()
    except OSError:
        return None
    sig = (st.st_size, st.st_mtime_ns)
    hit = _MAN_CACHE.get(str(mp))
    if hit and hit[0] == sig:
        return hit[1]
    man = json.loads(mp.read_text(encoding="utf-8"))
    _MAN_CACHE[str(mp)] = (sig, man)
    return man


def items_digest(items: list[dict]) -> str:
    """清单条目（root、path、sha256）排序后的哈希：快照的内容指纹，**不含版本号**。"""
    import hashlib
    body = "\n".join(sorted(f'{i["root"]}\t{i["path"]}\t{i["sha256"]}' for i in items))
    return "glyph-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def pinned_db_path(version: int) -> Path:
    """g<N> 的库文件：与当前 ``glyph.db`` 同目录的 ``glyph-g<N>.db``（工作区本地，可重建）。"""
    from .workspace import glyph_db_path
    return Path(glyph_db_path()).with_name(f"glyph-g{int(version)}.db")


def pinned_db_meta(path: Path) -> dict | None:
    """钉版库里记的快照身份；库不存在、没有这一行 → None。"""
    import json
    import sqlite3
    if not Path(path).exists():
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (META_KEY,)).fetchone()
    except sqlite3.Error:
        return None
    return json.loads(row[0]) if row else None


def pin_state(book, ws: Path | None = None) -> dict | None:
    """这册钉字形库的情况（``guji status`` 等报）：没钉 → None；
    ``{n, snapshot: bool, digest, rev, db, db_ok}``。``db_ok``＝库文件在且就是这个快照建的。"""
    v = getattr(book, "glyph_pin", None)
    if not v:
        return None
    if ws is None:
        from .workspace import workspace_root
        ws = workspace_root()
    man = load_manifest(ws, v) if ws is not None else None
    if man is None:
        return {"n": v, "snapshot": False}
    db = pinned_db_path(v)
    meta = pinned_db_meta(db)
    return {"n": v, "snapshot": True, "digest": man["digest"], "rev": man.get("rev"), "db": str(db),
            "db_ok": bool(meta and meta.get("digest") == man["digest"])}


class GlyphPinMissing(RuntimeError):
    """册钉了有快照的字形库版本，但本机没有那一版的库文件（或不是那个快照建的）：拒跑。"""


def reads_pinned_db(p, version: int) -> bool:
    """这一步的参数读的是不是 g<N> 的库文件（`with_glyph_pin` 换过路径的步）。"""
    db = str(pinned_db_path(version))
    return getattr(p, "db_path", None) == db or (getattr(p, "roster_glyph_refine", False)
                                                 and getattr(p, "roster_glyph_db", None) == db)


def require_pinned_db(ws: Path | None, version: int) -> None:
    """起跑读字形库的步之前：有快照的钉号，库文件必须在且 digest 对得上。没快照（旧做法）不查。"""
    if ws is None:
        return
    man = load_manifest(ws, version)
    if man is None:
        return
    db = pinned_db_path(version)
    meta = pinned_db_meta(db)
    if not meta or meta.get("digest") != man["digest"]:
        raise GlyphPinMissing(f"册钉了字形库 g{version}（{man['digest']}），本机{'没有' if meta is None else '的库不是这一版建的：'}"
                              f"{db}；先 guji glyph-db pin-build -w {ws} --pin {version}")


# ── 册钉子：参数改写 ────────────────────────────────────────────────────────────


def with_glyph_pin(p, book):
    """册钉了字形库时改写参数（见模块头三种状态）；没钉原样返回。"""
    v = getattr(book, "glyph_pin", None)
    if not v:
        return p
    from .workspace import workspace_root
    ws = workspace_root()
    man = load_manifest(ws, v) if ws is not None else None
    if man is None:
        return _legacy_pin(p, v)
    return _snapshot_pin(p, v, man)


def _legacy_pin(p, v: int):
    """没有快照的钉号（旧做法）：只把 `PIN_FIELDS` 里已经有值的换成 `glyph-gN`，库照读当前的。"""
    fields = [f for f in PIN_FIELDS if getattr(p, f, "")]
    if not fields:
        return p
    tok = pin_token(v)
    return type(p)(**{**p.model_dump(), **{f: tok for f in fields}})


def _snapshot_pin(p, v: int, man: dict):
    """有快照的钉号：读字形库的路径换成 g<N> 的库文件，字形库指纹换成快照 digest。

    必须重新构造（参数类的派生指纹在 `model_post_init` 里按 `db_path` 填，非空才不重填）。
    不读字形库的参数类原样返回。"""
    from .workspace import glyph_db_path
    tok = man["digest"]
    live, db = str(glyph_db_path()), str(pinned_db_path(v))
    # 清单没记 fingerprints（g4 是 --no-build 出的）就读建库时写进库 meta 的那份
    fp = man.get("fingerprints") or (pinned_db_meta(Path(db)) or {}).get("fingerprints") or {}
    kw: dict = {}
    if hasattr(p, "db_path") and getattr(p, "db_path", None) == live:
        kw["db_path"] = db
        if hasattr(p, "db_fingerprint"):                      # glyph_match
            kw["db_fingerprint"] = tok
            if hasattr(p, "borrow_fingerprint"):
                kw["borrow_fingerprint"] = fp.get("borrow_fingerprint", "")
        if hasattr(p, "human_fingerprint"):                   # seed_admit
            kw["human_fingerprint"] = tok if p.human_fingerprint else ""
            kw["approx_fingerprint"] = tok if fp.get("approx") else ""
    elif any(getattr(p, f, "") for f in PIN_FIELDS):           # 显式指了别的库的 seed_admit：照旧做法只钉指纹
        return _legacy_pin(p, v)
    if getattr(p, "roster_glyph_refine", False) and getattr(p, "roster_glyph_db", None) == live:
        kw["roster_glyph_db"] = db
        kw["roster_glyph_fingerprint"] = tok
    if not kw:
        return p
    return type(p)(**{**p.model_dump(), **kw})
