"""字形库的内容指纹（GUJI-609，v0.4.0）：与库是怎么建出来的无关，只看步骤真正读到的内容。

写入切换（GUJI-608）后 glyph.db 是数据目录里字形库账本的派生物：每次拉到新字形库就整库重建。
旧指纹取 ``(条数, 最大 rowid, 最新时间戳)``，在长期增量写的库上够用，换成「重建」就不对了——
重建时 rowid 按插入顺序重排，机器准入多一条，排在它后面的人裁行 rowid 全跟着挪，
``seed_admit`` 的人裁指纹于是跟着变，各册白白过期。这里改成对**步骤读到的那份数据**
排序后取哈希：

- ``human_shapes_fingerprint``：``seed_admit`` 人裁通道读的 ``(实例 id, 字头)``
  （``admissions.provenance='human'`` 经 exemplars 连 glyphs，取 glyphs 的字头——字头改判也算），
  与 ``seed_admit._human_shapes`` 同一条查询。复制、VACUUM、重建、撤后同字重进都不变；
  人裁进库、撤裁、字头改判才变。各机器同一份库账本得到同一个值。
- ``font_domain_fingerprint``：库里字体域（``sources.kind='font'``）的清单哈希。
  ``glyph-db import-font`` 导入时在 ``font_manifests`` 表记一行（字体文件 sha256、字表 sha256、渲染成功数；
  这张表不导出进字形库账本，字体域本来就不进中心库）；更早导入、没有这条记录的退回 ``(edition, 实例数)``。库里没有字体域 → ``"none"``，
  于是「带不带字体域」在指纹里看得见（中心库重建的 glyph.db 不含字体域，要另跑 import-font）。

设计里写的是「库版本号 rev」。没用 rev 的原因：产物在各自机器上，同一份内容在不同机器、
不同时候拉到的 rev 不同；本地人裁写进 glyph.db 还没推时也没有 rev；推完 rev 变了而内容没变，
又会白白过期一次。内容哈希没有这些问题，精度相同。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

HUMAN_SQL = ("SELECT a.instance_id, g.char FROM admissions a "
             "  JOIN exemplars e ON e.instance_id = a.instance_id "
             "  JOIN glyphs g ON g.glyph_id = e.glyph_id "
             " WHERE a.provenance = 'human' AND a.instance_id LIKE 'v2:%'")
FONT_TABLE = "font_manifests"
FONT_TABLE_SQL = (f"CREATE TABLE IF NOT EXISTS {FONT_TABLE} "
                  "(edition_tag TEXT PRIMARY KEY, manifest TEXT NOT NULL)")


def _ro(path: str | Path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _digest(rows) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(list(r), ensure_ascii=False).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def human_shapes_fingerprint(path: str | Path) -> str:
    """``h1:<条数>:<哈希>``；库不存在 → ``"nodb"``，读不了 → ``"unreadable"``。"""
    p = Path(path)
    if not p.exists():
        return "nodb"
    try:
        with _ro(p) as c:
            rows = sorted(set(c.execute(HUMAN_SQL).fetchall()))
    except sqlite3.Error:
        return "unreadable"
    return f"h1:{len(rows)}:{_digest(rows)}"


def font_domain_manifest(path: str | Path) -> dict[str, dict]:
    """{edition: 清单}；没有字体域 → {}。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with _ro(p) as c:
            eds = [r[0] for r in c.execute(
                "SELECT edition_tag FROM sources WHERE kind = 'font' ORDER BY edition_tag")]
            out = {}
            for ed in eds:
                try:
                    row = c.execute(f"SELECT manifest FROM {FONT_TABLE} WHERE edition_tag = ?", (ed,)).fetchone()
                except sqlite3.OperationalError:            # 更早导入的库没有这张表
                    row = None
                if row and row[0]:
                    out[ed] = json.loads(row[0])
                else:
                    n = c.execute("SELECT count(*) FROM instances WHERE source_id = ?", (ed,)).fetchone()[0]
                    out[ed] = {"instances": int(n)}
            return out
    except (sqlite3.Error, ValueError):
        return {"?": {"unreadable": True}}


def font_domain_fingerprint(path: str | Path) -> str:
    man = font_domain_manifest(path)
    if not man:
        return "none"
    return f"f1:{'+'.join(sorted(man))}:{_digest(sorted((k, json.dumps(v, sort_keys=True)) for k, v in man.items()))}"
