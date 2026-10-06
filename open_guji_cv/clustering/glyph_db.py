"""GlyphDB：跨書字形數據庫（SQLite 單檔，M8 字形庫升級）。

設計見 doc/design/char_clustering_design.md 第 19 節。要點：

- 原始字形 PNG 是唯一不可變真源；歸一化/骨架/特徵是帶版本的派生物；
- 字形層（char=精確異體字形）與語義層（semantic=正字）分離；
- glyphs 按 edition_tag 分域，同字不同版永不合併；
- 簇號只存在於 cluster_run 作用域，可累積標註只掛實例 id；
- 用戶反饋事件 (source,batch,seq) 冪等入庫，狀態=重放；
- exemplar 政策：K_MIN=3 以下標 sparse；入庫一律走 admit_instance（逐實例準入，
  v1 的 import_book 全量入庫與 medoid/FPS 選例隨 overview#418 刪除）。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .canonical import encode_png, to_canonical
from .features import DEFAULT_FEATURE, get_feature
from .normalize import normalize_patch, skeletonize
from .verify import verify_pair

K_MIN = 3            # 低於 → glyph 標 sparse
ALGO_VERSIONS = {"norm": "n1", "skeleton": "s1", "feat": "f1"}

# 「易混字組」——同一組內的字在刻本裡經常混用（技術限制/書手習慣），字形
# 分不出組內具體是哪個字，準入只能靠文意判斷（見 `admit_instance` 與
# `clustering.seeding` 的用法）。目前只有一組：己/已/巳（用戶 2026-09-11
# 定，推翻此前「己是真的另一個字」的舊考據——見 doc/charset_and_lm.md §四）。
# 結構特意留成「元組的元組」而非兩兩一對，將來加「日/曰」之類新組直接追加。
CONFUSABLE_GROUPS: tuple[frozenset[str], ...] = (frozenset({"己", "已", "巳"}),)
CONFUSABLE_CHARS: frozenset[str] = frozenset(
    c for group in CONFUSABLE_GROUPS for c in group)
# 易混字組每個字形只需要少量樣本就夠字形匹配層認出「這是這一組裡的某個
# 形」——組內具體是哪個字不由字形定，樣本再多也不增加判斷力，反而白佔庫
# 空間、稀釋检索。達到這個數之後 `admit_instance` 對這一組字不再新增
# exemplar（但審計行 `admissions`/`instances` 仍照常寫，準入計數不受影響，
# 見該函式實現）。用戶 2026-09-11 定「每個積累 5 個左右就夠」。
CONFUSABLE_SAMPLE_CAP = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    collection TEXT, title TEXT, volume TEXT,
    edition_tag TEXT NOT NULL,
    script_style TEXT, era TEXT,
    cols_per_page INTEGER, chars_per_col INTEGER,
    pipeline_version TEXT, notes TEXT,
    -- kind 決定這個來源的可信度與去留：
    --   woodblock 人工確認的刻本字形（精確字形層，導出進 Git）
    --   scan      字典/掃描件字形（語義候選層，導出進 Git）
    --   font      字體渲染字形（語義候選層，**不導出**——由字體檔 +
    --             字表確定性重生成，見 font_glyphs.py）
    kind TEXT NOT NULL DEFAULT 'woodblock',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS instances (
    instance_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    page TEXT NOT NULL, col INTEGER NOT NULL, idx INTEGER NOT NULL,
    bbox TEXT,
    patch_png BLOB NOT NULL,
    ink_ratio REAL, width REAL, height REAL,
    quality_flags TEXT,
    label TEXT, label_status TEXT, label_confidence REAL,
    semantic TEXT, unicode_cp INTEGER, ids TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instances_label
    ON instances(label) WHERE label IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_instances_source ON instances(source_id);
CREATE TABLE IF NOT EXISTS derived (
    instance_id TEXT NOT NULL REFERENCES instances(instance_id),
    kind TEXT NOT NULL,
    algo_version TEXT NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (instance_id, kind, algo_version)
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    batch TEXT, seq INTEGER, ts TEXT,
    op TEXT NOT NULL, payload TEXT NOT NULL,
    UNIQUE(source_id, batch, seq)
);
CREATE TABLE IF NOT EXISTS cluster_runs (
    run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    params TEXT, stats TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cluster_members (
    run_id TEXT NOT NULL REFERENCES cluster_runs(run_id),
    instance_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    PRIMARY KEY (run_id, instance_id)
);
CREATE TABLE IF NOT EXISTS glyphs (
    glyph_id INTEGER PRIMARY KEY AUTOINCREMENT,
    edition_tag TEXT NOT NULL,
    char TEXT NOT NULL,
    semantic TEXT, unicode_cp INTEGER, ids TEXT,
    status TEXT NOT NULL DEFAULT 'sparse',
    n_confirmed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(edition_tag, char)
);
CREATE TABLE IF NOT EXISTS exemplars (
    glyph_id INTEGER NOT NULL REFERENCES glyphs(glyph_id),
    instance_id TEXT NOT NULL REFERENCES instances(instance_id),
    role TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (glyph_id, instance_id)
);
CREATE TABLE IF NOT EXISTS pairs (
    inst_a TEXT NOT NULL, inst_b TEXT NOT NULL,
    relation TEXT NOT NULL,
    origin TEXT NOT NULL,
    source_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (inst_a, inst_b, relation)
);
CREATE TABLE IF NOT EXISTS meta (
    -- 库级设置（2026-09-25）。book_edition：这个库是一本书的库，刻本字形一律归这个
    -- edition（`set_book_edition` 写入）。没有这一行 = 旧行为（edition = 实例 id 前缀）。
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS admissions (
    -- 逐实例准入审计（种子协议 §3.5）：provenance + 完整判定证据。
    -- 主键即幂等闸：同一实例只准入一次，重复事件/重跑不重复进库。
    instance_id TEXT PRIMARY KEY,
    char TEXT NOT NULL,
    provenance TEXT NOT NULL,
    evidence TEXT,
    admitted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evictions (
    -- 撤例审计（2026-09-28，overview#234）：`evict_instance` 删四表行时连 admissions 一起删，
    -- 库里原本不留「这例是被撤的」痕迹，`glyph_store_sync` 分不清「db 撤了」和「db 根本没见过
    -- 别人进的」（09-28 事故：服务器旧库导出冲掉 main 上 14 例「聞」）。每撤一例记一行，
    -- 随 store 导出（evictions.jsonl），同步的删除护栏只放行有这里记录的删除。
    instance_id TEXT NOT NULL,
    char TEXT,
    reason TEXT,
    at TEXT NOT NULL,
    PRIMARY KEY (instance_id, at)
);
CREATE TABLE IF NOT EXISTS approx_labels (
    -- 近似字（2026-09-29，overview#276）：人裁勾了「无匹配（近似字）」——Unicode 里没有真正
    -- 对应的字，所定的 `label` 只是字形最像、意思最近的那个。**稀疏侧表**：只有勾过的实例才有行，
    -- `instances`/`glyphs` 的 schema 不动。`ids` 实际结构、`note` 备注都可空。
    -- 随 store 导出（approx_labels.jsonl），跟着实例走：撤例 / 同步替换时一起删。
    instance_id TEXT PRIMARY KEY REFERENCES instances(instance_id),
    label TEXT NOT NULL,
    ids TEXT,
    note TEXT,
    reviewer TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approx_clears (
    -- 近似标记撤销审计（与 `evictions` 同一用意）：人后来改口「不是近似字」时 approx_labels 删行、
    -- 这里记一笔，随 store 导出（approx_clears.jsonl）。`glyph_store_sync` 的删除护栏靠它分清
    -- 「db 撤了近似标记」和「db 根本没见过别人标的近似」。
    instance_id TEXT NOT NULL,
    label TEXT,
    at TEXT NOT NULL,
    PRIMARY KEY (instance_id, at)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _png(arr01: np.ndarray) -> bytes:
    """{0,1} 二值圖 → 白底黑字 PNG bytes。"""
    ok, buf = cv2.imencode(".png", (255 - arr01 * 255).astype(np.uint8))
    if not ok:
        raise RuntimeError("PNG 編碼失敗")
    return buf.tobytes()


def _unpng(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    return (img < 128).astype(np.uint8)


@dataclass
class DBHit:
    char: str
    edition_tag: str
    instance_id: str
    f1: float
    verdict: str
    sparse: bool
    kind: str = "woodblock"   # 來源類別：woodblock / scan / font


class GlyphDB:
    def __init__(self, db_path: str | Path,
                 feature_backend: str = DEFAULT_FEATURE):
        # 特徵後端由庫自持：入庫一律用本庫後端重算，不沿用各書聚類時
        # 用的後端——否則 raw(256維) 的書混進 hog(1764維) 的庫，
        # 檢索時維度對不上（而且錯得無聲無息）。
        self.feature_name = feature_backend
        self._feature = get_feature(feature_backend)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """補上舊索引檔缺的列。

        SQLite 的 CREATE TABLE IF NOT EXISTS 不會給既有表加列，而這個檔
        雖然是可重建索引（rebuild 即可），也不該以 OperationalError 的
        形式告知用戶。
        """
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(sources)")}
        if "kind" not in have:
            self.conn.execute("ALTER TABLE sources ADD COLUMN kind TEXT "
                              "NOT NULL DEFAULT 'woodblock'")
        # 字形可信度（2026-09-25，字形库 04）：这个刻例与所定码位的通行字形
        # 一致到什么程度——exact 完全一致 / nearest Unicode 里没有同形字、存的是
        # 最近似码位（ids 写实际结构）/ unencoded 部件都对不上。NULL = 未评。
        # 「刻的是另一个有码位的异体」不存：label ≠ semantic 即是，现算。
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(instances)")}
        if "fidelity" not in have:
            self.conn.execute("ALTER TABLE instances ADD COLUMN fidelity TEXT")
        if "fidelity_by" not in have:
            self.conn.execute("ALTER TABLE instances ADD COLUMN fidelity_by TEXT")

    def close(self) -> None:
        self.conn.close()

    def _feat_kind(self) -> str:
        return f"feat_{self.feature_name}"

    def _write_derived(self, cur, iid, norm_patch) -> None:
        feat = self._feature.extract(norm_patch[None, ...])[0]
        rows = [
            (iid, "norm", ALGO_VERSIONS["norm"], _png(norm_patch)),
            (iid, "skeleton", ALGO_VERSIONS["skeleton"],
             _png(skeletonize(norm_patch))),
            (self._feat_kind(), ALGO_VERSIONS["feat"], feat),
        ]
        rows[2] = (iid, self._feat_kind(), ALGO_VERSIONS["feat"],
                   feat.astype(np.float32).tobytes())
        cur.executemany("INSERT OR REPLACE INTO derived VALUES (?,?,?,?)",
                        rows)

    # ── 近似字侧表（overview#276）──────────────────────────

    def set_approx(self, instance_id: str, label: str, *, ids: str | None = None,
                   note: str | None = None, reviewer: str | None = None,
                   at: str | None = None) -> bool:
        """给库里一例记「近似字」（覆盖旧值）。实例不在库里 → False，不写（外键）。

        内容（label/ids/note）与已有行完全相同时不动 `created_at`——同一条裁决重放不该让
        store 平白改动、也不该让同步的冲突裁决以为这边「刚改过」。
        """
        if not self.conn.execute("SELECT 1 FROM instances WHERE instance_id=?",
                                 (instance_id,)).fetchone():
            return False
        ids, note = (ids or None), (note or None)
        old = self.conn.execute("SELECT label, ids, note FROM approx_labels WHERE instance_id=?",
                                (instance_id,)).fetchone()
        if old is not None and tuple(old) == (label, ids, note):
            return True
        self.conn.execute(
            "INSERT OR REPLACE INTO approx_labels (instance_id, label, ids, note, reviewer, created_at) "
            "VALUES (?,?,?,?,?,?)", (instance_id, label, ids, note, reviewer, at or _now()))
        self.conn.commit()
        return True

    def clear_approx(self, instance_id: str, at: str | None = None) -> bool:
        """撤掉一例的近似标记（人改口）。有行才删、才记 `approx_clears`；返回删没删。"""
        row = self.conn.execute("SELECT label FROM approx_labels WHERE instance_id=?",
                                (instance_id,)).fetchone()
        if row is None:
            return False
        self.conn.execute("DELETE FROM approx_labels WHERE instance_id=?", (instance_id,))
        self.conn.execute("INSERT OR IGNORE INTO approx_clears (instance_id, label, at) VALUES (?,?,?)",
                          (instance_id, row[0], at or _now()))
        self.conn.commit()
        return True

    def approx_of(self, instance_id: str) -> dict | None:
        cur = self.conn.execute("SELECT * FROM approx_labels WHERE instance_id=?", (instance_id,))
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None

    # ── 單實例準入（種子協議 §3.5）───────────────────────

    def admit_instance(self, instance_id: str, char: str, patch_png: bytes,
                       *, provenance: str,
                       evidence: dict | None = None,
                       edition_tag: str | None = None,
                       page: str = "", col: int = 0, idx: int = 0,
                       bbox: list | None = None,
                       ink_ratio: float | None = None,
                       width: float | None = None,
                       height: float | None = None,
                       semantic: str | None = None,
                       shape: str | None = None) -> bool:
        """單個已裁決實例進庫（逐頁種子流程用；v1 全量入庫 import_book 已刪）。

        寫入：canonical 圖塊（真源，256×256 質心居中——十九輪起與
        此前種子路徑存的是原始裁切，全庫展示/
        比較不可比）、派生表示（norm/skeleton/feat，一律從 canonical
        圖重算——單一標準，不收調用方的 norm）、glyph 條目
        （n_confirmed 累加）、exemplar（role='seed'，逐實例可檢索）、
        admissions 審計行（provenance + evidence JSON——設計 §3 紀律 1：
        逐實例證據，不做盲傳播；改判時憑它重放）。

        ``char`` 是釋讀（這個字位「說的是什麼」，寫進 ``admissions.char``、
        且是 ``semantic`` 缺省值的來源——絕大多數字符字形=釋讀，兩者
        本就同值）；``shape`` 是字形識別鍵（餵給 ``glyphs``/``exemplars``/
        ``GlyphMatcher`` 索引的那個），缺省等於 ``char``。二者只在
        「同詞異寫、字形不重要」的窄類（``CONFUSABLE_GROUPS``，目前只有
        己/已/巳）才會分岔——那類字用文意判釋讀，但字形庫必須按刻本上
        實際刻的形狀分類，否則未來一個真的刻成巳形、該讀巳的實例會錯誤
        繼承這次的釋讀（2026-08-26 用戶定：「字形是什麼我們就錄什麼，
        這幾個字才按語意改，但這個修改不能污染字形匹配層」）。

        ``shape`` 屬於 ``CONFUSABLE_CHARS`` 且該 ``(edition_tag, shape)``
        已有 ``CONFUSABLE_SAMPLE_CAP`` 個 exemplar 時，跳過 ``glyphs``/
        ``exemplars`` 的寫入（字形匹配層不再為這一組字繼續累積樣本——
        組內具體是哪個字不由字形定，見 ``CONFUSABLE_SAMPLE_CAP`` 注釋），
        但 ``instances``/``admissions`` 照常寫，準入審計與冪等閘不受影響
        （用戶 2026-09-11 定）。

        冪等：同一 instance_id 第二次調用直接返回 False，什麼都不寫。
        """
        cur = self.conn.cursor()
        if cur.execute("SELECT 1 FROM admissions WHERE instance_id=?",
                       (instance_id,)).fetchone():
            return False
        source_id = instance_id.split(":")[0]
        edition = edition_tag or source_id
        # 一本书一个 edition（2026-09-25，用户：「v2 应该是整个四库目录，是整一个新的
        # edition」）。实例 id 前缀（vol01 / v2 / bxgb）是**命名空间**不是版本：库声明了
        # 本书 edition（meta.book_edition）时，新进的刻本字形一律归它。字体（font:*）与
        # 现代链播种域（modern:*，匹配器按它过滤）不动。
        if not edition.startswith(("font:", "modern:")):
            edition = self.book_edition() or edition
        cur.execute(
            "INSERT OR IGNORE INTO sources (source_id, edition_tag, created_at)"
            " VALUES (?,?,?)", (source_id, edition, _now()))
        shape = shape or char
        sem = semantic or char
        cp = ord(shape) if len(shape) == 1 else None
        raw = cv2.imdecode(np.frombuffer(patch_png, np.uint8),
                           cv2.IMREAD_GRAYSCALE)
        canon = to_canonical(raw)
        patch_png = encode_png(canon)
        norm = normalize_patch(canon)
        cur.execute(
            """INSERT INTO instances (instance_id, source_id, page, col, idx,
                 bbox, patch_png, ink_ratio, width, height, quality_flags,
                 label, label_status, label_confidence, semantic, unicode_cp,
                 ids, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(instance_id) DO UPDATE SET
                 label=excluded.label,
                 label_status=excluded.label_status,
                 semantic=excluded.semantic,
                 unicode_cp=excluded.unicode_cp,
                 updated_at=excluded.updated_at""",
            (instance_id, source_id, page, col, idx,
             json.dumps(bbox) if bbox is not None else None, patch_png,
             ink_ratio, width, height, None,
             shape, provenance, 1.0, sem, cp, None, _now()))
        self._write_derived(cur, instance_id, norm)
        capped = False
        if shape in CONFUSABLE_CHARS:
            row = cur.execute(
                "SELECT n_confirmed FROM glyphs WHERE edition_tag=? AND char=?",
                (edition, shape)).fetchone()
            capped = bool(row) and row[0] >= CONFUSABLE_SAMPLE_CAP
        if not capped:
            cur.execute(
                f"""INSERT INTO glyphs (edition_tag, char, semantic, unicode_cp,
                      ids, status, n_confirmed, updated_at)
                    VALUES (?,?,?,?,?,'sparse',1,?)
                    ON CONFLICT(edition_tag, char) DO UPDATE SET
                      n_confirmed = n_confirmed + 1,
                      status = CASE WHEN n_confirmed + 1 >= {K_MIN}
                               THEN 'stable' ELSE status END,
                      -- 字头 semantic/unicode_cp 首次插入即冻结；早期事件把拼音
                      -- 首字母写进过 semantic（麗→l），这里遇到非汉字旧值就让新值
                      -- 顶上，码位缺了就补（glyph_ledger.repair_glyph_heads 修存量）
                      semantic = CASE WHEN semantic IS NULL
                                        OR length(semantic) != 1
                                        OR unicode(semantic) < {0x2E80}
                                      THEN excluded.semantic ELSE semantic END,
                      unicode_cp = COALESCE(unicode_cp, excluded.unicode_cp),
                      updated_at=excluded.updated_at""",
                (edition, shape, sem, cp, None, _now()))
            gid = cur.execute(
                "SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
                (edition, shape)).fetchone()[0]
            cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,?,?)",
                        (gid, instance_id, "seed", _now()))
        cur.execute("INSERT INTO admissions VALUES (?,?,?,?,?)",
                    (instance_id, char, provenance,
                     json.dumps(evidence, ensure_ascii=False)
                     if evidence is not None else None, _now()))
        self.conn.commit()
        return True

    def book_edition(self) -> str | None:
        """这个库声明过的「本书 edition」（`set_book_edition` 写进 meta）；没声明返回 None。

        要显式声明、不按「来源恰好只有一个 edition」自动推：同一个库里放几本书的
        情形（样本库、测试夹具）照样存在，自动推会把别的书并进来。"""
        r = self.conn.execute("SELECT value FROM meta WHERE key='book_edition'").fetchone()
        return r[0] if r and r[0] else None

    def set_book_edition(self, edition: str, title: str | None = None,
                         dry_run: bool = False) -> dict:
        """把库里全部刻本字形并到一个 edition（一本书一套）。

        `glyphs` 以 (edition_tag, char) 为键，同字在两个 edition 各一行的要合并：
        刻例挂到目标行、确认数相加、够 K_MIN 升 stable；字头 semantic/ids/码位取目标行
        已有的、没有就取被并的。`sources.edition_tag` 一并改掉，以后新进的刻例
        （`admit_instance`）自动归这个 edition。实例 id 与 `instances.source_id` 不动——
        v1/v2 前缀是坐标命名空间（idx 从 0 / slot 从 1），不是版本。
        """
        if edition.startswith(("font:", "modern:")):
            raise ValueError("书的 edition 不能以 font: / modern: 开头")
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT glyph_id, edition_tag, char, semantic, unicode_cp, ids, n_confirmed "
            "FROM glyphs WHERE edition_tag NOT LIKE 'font:%' AND edition_tag NOT LIKE 'modern:%' "
            "AND edition_tag != ?", (edition,)).fetchall()
        merged = moved = 0
        seen: set[str] = set()        # 试算时记「已挪过去的字」，第二行同字才算合并
        for gid, ed, ch, sem, cp, ids, n in rows:
            tgt = cur.execute("SELECT glyph_id, n_confirmed FROM glyphs "
                              "WHERE edition_tag=? AND char=?", (edition, ch)).fetchone()
            if tgt is None and dry_run and ch in seen:
                merged += 1
                continue
            if tgt is None:
                seen.add(ch)
                if not dry_run:
                    cur.execute("UPDATE glyphs SET edition_tag=?, updated_at=? WHERE glyph_id=?",
                                (edition, _now(), gid))
                moved += 1
                continue
            merged += 1
            if dry_run:
                continue
            tid, tn = tgt
            total = int(tn or 0) + int(n or 0)
            cur.execute(f"""UPDATE glyphs SET n_confirmed=?,
                             status=CASE WHEN ? >= {K_MIN} THEN 'stable' ELSE status END,
                             semantic=COALESCE(semantic, ?), unicode_cp=COALESCE(unicode_cp, ?),
                             ids=COALESCE(NULLIF(ids,''), ?), updated_at=?
                           WHERE glyph_id=?""", (total, total, sem, cp, ids, _now(), tid))
            cur.execute("UPDATE OR IGNORE exemplars SET glyph_id=? WHERE glyph_id=?", (tid, gid))
            cur.execute("DELETE FROM exemplars WHERE glyph_id=?", (gid,))
            cur.execute("DELETE FROM glyphs WHERE glyph_id=?", (gid,))
        n_src = cur.execute(
            "SELECT COUNT(*) FROM sources WHERE COALESCE(kind,'woodblock') != 'font' "
            "AND edition_tag NOT LIKE 'font:%'").fetchone()[0]
        if not dry_run:
            # 刻本来源一律改过来——含 bxgb 那条历史上记成 modern:bxgb、而字形早已是 bxgb 的
            cur.execute("UPDATE sources SET edition_tag=? WHERE COALESCE(kind,'woodblock') != 'font' "
                        "AND edition_tag NOT LIKE 'font:%'", (edition,))
            if title:
                cur.execute("UPDATE sources SET title=? WHERE COALESCE(kind,'woodblock') != 'font'",
                            (title,))
            cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('book_edition', ?)",
                        (edition,))
            self.conn.commit()
        return {"edition": edition, "dry_run": dry_run, "glyph_rows_moved": moved,
                "glyph_rows_merged": merged, "sources": n_src}

    def refresh_instance_patch(self, instance_id: str, patch_png: bytes,
                               bbox: list | None = None) -> bool:
        """已進庫實例的圖塊被重切後，刷新庫裡的真源與全部派生。

        重切（人工改 bbox 重裁）發生在進庫**之後**時，庫裡存的還是錯位的
        舊圖塊——當 exemplar 被檢索到的是它，等於拿錯形當範例。這裡把
        instances.patch_png/bbox、derived（norm/skeleton/feat）整套換掉，
        並觸碰 exemplars.added_at 讓特徵矩陣常駐緩存失效（緩存戳含
        MAX(added_at)，只換 derived 它不會察覺）。

        admissions 審計行**不動**：進庫決定本身沒變，變的是圖塊。
        返回是否確有此實例。
        """
        cur = self.conn.cursor()
        if not cur.execute("SELECT 1 FROM instances WHERE instance_id=?",
                           (instance_id,)).fetchone():
            return False
        raw = cv2.imdecode(np.frombuffer(patch_png, np.uint8),
                           cv2.IMREAD_GRAYSCALE)
        canon = to_canonical(raw)
        norm = normalize_patch(canon)
        cur.execute(
            "UPDATE instances SET patch_png=?, bbox=?, updated_at=? "
            "WHERE instance_id=?",
            (encode_png(canon), json.dumps(bbox) if bbox is not None else None,
             _now(), instance_id))
        self._write_derived(cur, instance_id, norm)
        cur.execute("UPDATE exemplars SET added_at=? WHERE instance_id=?",
                    (_now(), instance_id))
        self.conn.commit()
        return True

    # ── 檢索 ─────────────────────────────────────────────

    def _exemplar_matrix(self):
        """全部 exemplar 的特徵矩陣（常駐緩存）。

        原先每次 query 都把整張特徵表從 SQLite 讀出來重新 stack——庫小時
        看不出來，到幾十萬字形就是每查一次搬幾 GB。這裡一次加載常駐。

        失效判據取 (條數, 最新 added_at)：只看條數的話，覆寫式重導入
        （條數不變、內容變了）會讀到陳舊特徵。
        """
        stamp = self.conn.execute(
            "SELECT COUNT(*), MAX(added_at) FROM exemplars").fetchone()
        if getattr(self, "_cache_stamp", None) == stamp:
            return self._cache_feats, self._cache_rows, self._cache_norms
        rows = self.conn.execute(
            """SELECT g.char, g.edition_tag, g.status, e.instance_id,
                      COALESCE(s.kind, 'woodblock'), d.data
               FROM exemplars e
               JOIN glyphs g ON g.glyph_id = e.glyph_id
               JOIN derived d ON d.instance_id = e.instance_id AND d.kind = ?
               JOIN instances i ON i.instance_id = e.instance_id
               LEFT JOIN sources s ON s.source_id = i.source_id""",
            (self._feat_kind(),)).fetchall()
        if rows:
            # 預分配後逐行填充：np.stack 要先攢齊 N 個小數組再拷一份，
            # 幾十萬行時峰值內存翻倍
            dim = len(rows[0][5]) // 4
            feats = np.empty((len(rows), dim), dtype=np.float32)
            for i, r in enumerate(rows):
                feats[i] = np.frombuffer(r[5], np.float32)
        else:
            feats = np.zeros((0, 1), dtype=np.float32)
        self._cache_stamp = stamp
        self._cache_rows = [r[:5] for r in rows]
        self._cache_feats = feats
        self._cache_norms = (feats ** 2).sum(1)
        self._cache_edition = np.array([r[1] for r in rows], dtype=object)
        self._cache_kind = np.array([r[4] for r in rows], dtype=object)
        self._cache_iid = np.array([r[3] for r in rows], dtype=object)
        return feats, self._cache_rows, self._cache_norms

    def query(self, norm_patch: np.ndarray,
              edition_hint: str | None = None, k: int = 5,
              editions: Sequence[str] | None = None,
              kinds: Sequence[str] | None = None,
              exclude: Sequence[str] | None = None) -> list[DBHit]:
        """exemplar 特徵 kNN 粗排 → verify_pair 精驗。

        特徵由庫內部按自持後端計算——調用方只需給歸一化圖塊，
        不必知道（也不會弄錯）特徵後端。

        來源過濾（**在 kNN 粗排之前**生效，這很要緊：字體來源動輒
        數萬字形，不先濾掉會把百來個刻本 exemplar 直接淹沒）：

        - ``edition_hint``：單一版本（舊參數，等價於 ``editions=[hint]``）
        - ``editions``：版本白名單，只在這幾個 edition_tag 裡檢索
        - ``kinds``：來源類別白名單（woodblock/scan/font），跨版本按
          可信度分層檢索用

        三者可疊加（取交集）。返回的 :class:`DBHit` 帶 ``edition_tag``
        與 ``kind``，調用方據此區分命中來自哪個庫。

        ``exclude``：排除指定 instance_id（留一法評測用）。**必須在這裡
        排除，不能拿返回結果過濾**——每個 (edition, char) 只留最高分，
        自身命中若排第一，事後過濾會連帶把那個字整個抹掉。
        """
        feat = self._feature.extract(norm_patch[None, ...])[0]
        cur = self.conn.cursor()
        feats, rows, norms = self._exemplar_matrix()
        if not rows:
            return []
        wanted = list(editions) if editions else []
        if edition_hint:
            wanted.append(edition_hint)
        # 過濾在粗排之前生效：字體來源動輒數萬字形，不先濾會把刻本
        # exemplar 淹沒。用 numpy 掩碼而不是 SQL——矩陣常駐，重查 SQLite
        # 才是慢的那一頭
        mask = np.ones(len(rows), dtype=bool)
        if wanted:
            mask &= np.isin(self._cache_edition, wanted)
        if kinds:
            mask &= np.isin(self._cache_kind, list(kinds))
        if exclude:
            mask &= ~np.isin(self._cache_iid, list(exclude))
        if not mask.any():
            return []
        # ‖a−b‖² = ‖a‖² − 2a·b + ‖b‖²：矩陣向量乘，不為每次查詢分配
        # 一個 N×D 的臨時大數組（D=1764 時那是幾 GB）。省掉的 ‖b‖² 對
        # 所有行是同一個常數，不影響排序（這裡只要名次，不要距離值）。
        d2 = norms - 2.0 * (feats @ feat)
        d2[~mask] = np.inf
        n_take = min(max(k * 3, 12), int(mask.sum()))
        # argpartition 不保證組內有序，但粗排只負責選出候選，
        # 最終次序由下面的 f1 決定
        cand = (np.argpartition(d2, n_take - 1)[:n_take] if n_take < len(d2)
                else np.argsort(d2))
        hits: list[DBHit] = []
        for idx in cand:
            char, edition, status, iid, kind = rows[int(idx)]
            row = cur.execute(
                "SELECT data FROM derived WHERE instance_id=? AND kind='norm'",
                (iid,)).fetchone()
            if row is None:
                continue
            v = verify_pair(norm_patch, _unpng(row[0]))
            hits.append(DBHit(char=char, edition_tag=edition,
                              instance_id=iid, f1=v.f1, verdict=v.verdict,
                              sparse=(status == "sparse"), kind=kind))
        hits.sort(key=lambda h: -h.f1)
        # 每字形只留最高分
        seen, out = set(), []
        for h in hits:
            key = (h.edition_tag, h.char)
            if key not in seen:
                seen.add(key)
                out.append(h)
        return out[:k]

    # ── 剪庫 ─────────────────────────────────────────────

    def drop_edition(self, edition_tag: str) -> dict:
        """刪掉一個來源的整條鏈（glyphs/exemplars/derived/instances/sources）。

        用於剪掉不再需要的字體庫或導入到一半的殘局。只認 kind='font' 之外
        的來源時要當心：刻本來源的真源在 glyph_store/，這裡刪的只是索引，
        `rebuild` 會把它們拉回來——真要棄掉刻本來源得動導出目錄。

        **`admissions` 準入台賬一併刪掉**（2026-09-16 補）：`admit_instance` 靠
        台賬判重，台賬留著而實例沒了，重播時整批被當成 duplicate 跳過——庫看著
        「播過了」其實是空的，而且不報錯。北行日錄踩過：1001 個字位重播只進了
        114 個字頭，其餘 887 全被跳過，查了半天才發現是台賬沒清。
        """
        cur = self.conn.cursor()
        iids = [r[0] for r in cur.execute(
            """SELECT i.instance_id FROM instances i
               JOIN sources s ON s.source_id = i.source_id
               WHERE s.edition_tag = ?""", (edition_tag,))]
        n_gly = cur.execute(
            "SELECT COUNT(*) FROM glyphs WHERE edition_tag=?",
            (edition_tag,)).fetchone()[0]
        cur.execute("""DELETE FROM exemplars WHERE glyph_id IN
                       (SELECT glyph_id FROM glyphs WHERE edition_tag=?)""",
                    (edition_tag,))
        cur.execute("DELETE FROM glyphs WHERE edition_tag=?", (edition_tag,))
        for i in range(0, len(iids), 500):
            chunk = iids[i:i + 500]
            ph = ",".join("?" * len(chunk))
            cur.execute(f"DELETE FROM derived WHERE instance_id IN ({ph})",
                        chunk)
            cur.execute(f"DELETE FROM instances WHERE instance_id IN ({ph})",
                        chunk)
            # 台賬跟著實例一起走，否則重播全被判重跳過（見 docstring）
            cur.execute(f"DELETE FROM admissions WHERE instance_id IN ({ph})",
                        chunk)
            cur.execute(f"DELETE FROM approx_labels WHERE instance_id IN ({ph})",
                        chunk)
        cur.execute("DELETE FROM sources WHERE edition_tag=?", (edition_tag,))
        # 撤例审计（overview#234）：否则下一轮 glyph_store_sync 的删除护栏会拦下这批删除
        at = _now()
        cur.executemany("INSERT OR IGNORE INTO evictions (instance_id, char, reason, at) "
                        "VALUES (?,?,?,?)",
                        [(i, None, f"drop_edition {edition_tag}", at) for i in iids])
        self.conn.commit()
        self._cache_stamp = None          # 特徵緩存必須失效
        return {"edition": edition_tag, "glyphs": n_gly,
                "instances": len(iids)}

    # ── 統計 ─────────────────────────────────────────────

    def stats(self) -> dict:
        cur = self.conn.cursor()
        one = lambda q: cur.execute(q).fetchone()[0]
        by_status = dict(cur.execute(
            "SELECT status, COUNT(*) FROM glyphs GROUP BY status").fetchall())
        by_rel = dict(cur.execute(
            "SELECT relation, COUNT(*) FROM pairs GROUP BY relation").fetchall())
        return {
            "sources": one("SELECT COUNT(*) FROM sources"),
            "instances": one("SELECT COUNT(*) FROM instances"),
            "labeled": one("SELECT COUNT(*) FROM instances WHERE label IS NOT NULL"),
            "events": one("SELECT COUNT(*) FROM events"),
            "glyphs": by_status,
            "exemplars": one("SELECT COUNT(*) FROM exemplars"),
            "pairs": by_rel,
            "db_bytes": self.db_path.stat().st_size,
        }


# ── 導出 / 重建（持久化）────────────────────────────────
#
# 容器是臨時的，SQLite 檔本身不能當長期存放處。真源改為 **Git 可追蹤的
# 導出目錄**，SQLite 降級為可隨時重建的索引：
#
#   glyph_store/                 ← 提交進倉庫，這是真源
#     sources.jsonl  glyphs.jsonl  exemplars.jsonl  pairs.jsonl
#     events/<source>.jsonl
#     instances/<source>.jsonl   ← 只含已標註/代表實例的元數據
#     patches/<safe_id>.png      ← 只含上述實例的原始字形
#   glyphdb.sqlite               ← 不提交，rebuild 生成
#
# 不導出的東西及理由：未標註實例（34MB 圖塊，無積累價值，可從掃描件
# 重跑得到）、derived（norm/skeleton/feat 都是原始圖的純函數，帶
# algo_version 重算即可——算法升級時反而必須重算）、cluster_members
# （聚類是可重跑的過程）。

EXPORT_TABLES = ("sources", "glyphs", "exemplars", "pairs")


def _safe(instance_id: str) -> str:
    return instance_id.replace(":", "_")


def export_store(db: "GlyphDB", out_dir: str | Path) -> dict:
    """SQLite → Git 友好的文本 + PNG 目錄（冪等覆寫）。"""
    out = Path(out_dir)
    (out / "events").mkdir(parents=True, exist_ok=True)
    (out / "instances").mkdir(parents=True, exist_ok=True)
    (out / "patches").mkdir(parents=True, exist_ok=True)
    cur = db.conn.cursor()
    cur.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    # 借来的库（`rebuild_from_store(extra_stores=...)`）不导出：真源只收本书自己的刻例
    b_ids, b_eds, b_srcs = _borrowed(db)

    def keep(r: dict) -> bool:
        return not (r.get("instance_id") in b_ids or r.get("edition_tag") in b_eds
                    or (r.get("key") or "").startswith("borrowed_"))

    def dump(path: Path, rows, key=None) -> int:
        recs = [d for d in (dict(r) for r in rows) if keep(d)]
        if key:
            recs.sort(key=key)
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False,
                                   sort_keys=True) + "\n")
        return len(recs)

    # 字體來源整條鏈（sources / glyphs / exemplars / instances / patches）
    # 都不導出，見下面 kind='font' 的註解
    fe = tuple(r[0] for r in cur.execute(
        "SELECT DISTINCT edition_tag FROM sources WHERE kind='font'"))
    ph = ",".join("?" * len(fe))

    def not_font(col: str, keyword: str = "WHERE") -> str:
        return f" {keyword} {col} NOT IN ({ph})" if fe else ""

    counts["sources"] = dump(
        out / "sources.jsonl",
        cur.execute("SELECT * FROM sources WHERE COALESCE(kind,'woodblock') "
                    "!= 'font' ORDER BY source_id"))
    # glyph_id 是本地自增代理鍵，導出時剔除——重建時按
    # (edition_tag, char) 重新分配，跨機器/跨克隆才不會衝突
    counts["glyphs"] = dump(
        out / "glyphs.jsonl",
        [{k: v for k, v in dict(r).items() if k != "glyph_id"}
         for r in cur.execute(
             "SELECT * FROM glyphs" + not_font("edition_tag")
             + " ORDER BY edition_tag, char", fe)])
    counts["exemplars"] = dump(
        out / "exemplars.jsonl",
        [{"edition_tag": r["edition_tag"], "char": r["char"],
          "instance_id": r["instance_id"], "role": r["role"],
          "added_at": r["added_at"]}
         for r in cur.execute(
             "SELECT g.edition_tag, g.char, e.instance_id, e.role, e.added_at "
             "FROM exemplars e JOIN glyphs g ON g.glyph_id = e.glyph_id"
             + not_font("g.edition_tag")
             + " ORDER BY g.edition_tag, g.char, e.instance_id", fe)])
    counts["meta"] = dump(out / "meta.jsonl",
                          cur.execute("SELECT * FROM meta ORDER BY key"))
    # 撤例审计（overview#234）：别的机器（服务器 / 云端）靠它知道「这例是被撤的、不是漏了」
    counts["evictions"] = dump(
        out / "evictions.jsonl",
        cur.execute("SELECT * FROM evictions ORDER BY instance_id, at"))
    # 近似字侧表（overview#276）：只导出库里还在、且非字体来源的实例（借来的由 keep() 挡掉）
    counts["approx_labels"] = dump(
        out / "approx_labels.jsonl",
        cur.execute(
            "SELECT x.* FROM approx_labels x JOIN instances i ON i.instance_id = x.instance_id "
            "  JOIN sources s ON s.source_id = i.source_id "
            " WHERE COALESCE(s.kind,'woodblock') != 'font' ORDER BY x.instance_id"))
    counts["approx_clears"] = dump(
        out / "approx_clears.jsonl",
        cur.execute("SELECT * FROM approx_clears ORDER BY instance_id, at"))
    counts["pairs"] = dump(
        out / "pairs.jsonl",
        cur.execute("SELECT * FROM pairs ORDER BY inst_a, inst_b, relation"))
    # admissions 是**進庫審計行**（設計 §3 紀律 1：每條進庫都要留 provenance +
    # evidence）。它不是派生物——provenance='human' 的那些是人裁決定，庫外
    # 沒有第二份；events 表在生產庫裡是空的，重算也算不回來。首版導出漏了它，
    # 於是 rebuild 出來的庫 admissions=0，審計鏈整條斷掉（2026-09-06 為了把
    # sqlite 移出 Git 歷史做 export→rebuild 無損校驗時發現）。
    counts["admissions"] = dump(
        out / "admissions.jsonl",
        cur.execute(
            "SELECT a.* FROM admissions a JOIN instances i "
            "  ON i.instance_id = a.instance_id "
            "  JOIN sources s ON s.source_id = i.source_id "
            " WHERE COALESCE(s.kind,'woodblock') != 'font' "
            " ORDER BY a.instance_id"))

    # 事件與實例按書分檔：一本書一個檔，審查增量只動一個檔
    n_ev = n_inst = n_png = 0
    written: set[str] = set()
    # kind='font' 的來源不導出：字形由字體檔 + 字表確定性重生成，
    # 進 Git 只是把幾萬張可再生的圖塞進版本歷史（另見字體外框版權）。
    for (src,) in db.conn.execute(
            "SELECT source_id FROM sources WHERE COALESCE(kind,'woodblock') "
            "!= 'font' ORDER BY 1"):
        if src in b_srcs:
            continue
        n_ev += dump(out / "events" / f"{src}.jsonl", cur.execute(
            "SELECT source_id, batch, seq, ts, op, payload FROM events "
            "WHERE source_id=? ORDER BY COALESCE(seq, event_id)", (src,)))
        rows = cur.execute(
            """SELECT * FROM instances WHERE source_id=? AND (label IS NOT NULL
                 OR instance_id IN (SELECT instance_id FROM exemplars))
               ORDER BY instance_id""", (src,)).fetchall()
        meta = []
        for r in rows:
            d = dict(r)
            if d["instance_id"] in b_ids:
                continue
            png = d.pop("patch_png")
            # 可信度两列是 2026-09-25 加的：未评（NULL）就不写，免得每次导出给
            # 全部旧行都添一对 null 键、store 平白整片改动
            for k in ("fidelity", "fidelity_by"):
                if d.get(k) is None:
                    d.pop(k, None)
            name = f"{_safe(d['instance_id'])}.png"
            (out / "patches" / name).write_bytes(png)
            written.add(name)
            n_png += 1
            meta.append(d)
        n_inst += dump(out / "instances" / f"{src}.jsonl", meta)
    # 清孤兒：上輪導出遺留、已不被任何實例引用的 PNG（冪等覆寫的補全）
    n_orphan = 0
    for f in (out / "patches").glob("*.png"):
        if f.name not in written:
            f.unlink()
            n_orphan += 1
    counts.update(events=n_ev, instances=n_inst, patches=n_png,
                  orphans_removed=n_orphan)

    # 統計不含 glyphdb.sqlite——它是可重建索引，不進版本控制
    counts["bytes"] = sum(f.stat().st_size for f in out.rglob("*")
                          if f.is_file() and f.suffix != ".sqlite")
    (out / "README.md").write_text(
        "# 字形庫（真源）\n\n"
        "本目錄是跨書字形庫的**持久真源**，隨倉庫版本管理。\n"
        "`glyphdb.sqlite` 是可重建的索引，不納入版本控制。\n\n"
        "```\npython -m open_guji_cv glyph-db rebuild --store glyph_store\n```\n\n"
        "未導出：未標註實例的圖塊（可從掃描件重跑）、派生表示\n"
        "（norm/skeleton/feat 是原始圖的純函數，算法升級時必須重算）、\n"
        "聚類成員（過程資產）。\n",
        encoding="utf-8")
    return counts


BORROWED_TABLE = """CREATE TABLE IF NOT EXISTS borrowed (
    -- 借来的库（`rebuild_from_store(extra_stores=...)`，2026-09-27 全唐文书级库）：
    -- 这些实例只为匹配而装进本库，真源在别的工作区。`export_store` 跳过它们，
    -- 否则一次导出就把四庫刻例抄进全唐文的真源。
    instance_id TEXT PRIMARY KEY,
    store TEXT
)"""


def _borrowed(db: "GlyphDB") -> tuple[set[str], set[str], set[str]]:
    """(借来的实例 id, 借来的 edition, 只属于借来库的 source_id)；普通库三个空集。"""
    cur = db.conn.cursor()
    if not cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='borrowed'"
                       ).fetchone():
        return set(), set(), set()
    ids = {r[0] for r in cur.execute("SELECT instance_id FROM borrowed")}
    meta = dict(cur.execute("SELECT key, value FROM meta WHERE key IN "
                            "('borrowed_editions','borrowed_sources')").fetchall())
    eds = set(json.loads(meta.get("borrowed_editions") or "[]"))
    srcs = set(json.loads(meta.get("borrowed_sources") or "[]"))
    return ids, eds, srcs


def rebuild_from_store(store_dir: str | Path, db_path: str | Path,
                       feature_backend: str = DEFAULT_FEATURE,
                       extra_stores: "tuple | list" = ()) -> dict:
    """Git 導出目錄 → SQLite 索引（派生表示按當前算法重算）。

    ``extra_stores``（2026-09-27，全唐文书级库）：再把别的工作区的真源**借**进来，
    只为匹配（`glyph_match` 只读一个库文件）。借来的部分：
    - 刻例、字头照原 edition 装（四庫是 ``siku-zongmu``），与本书 edition 分开；
    - `meta`（含 ``book_edition``）、`events`、`pairs` 不装——库的身份仍是第一个 store 的；
    - 实例 id 记进 ``borrowed`` 表，`export_store` 导出时跳过，真源不会被借来的刻例污染；
    - 与本书同 id 的实例不覆盖（本书优先）。
    """
    store = Path(store_dir)
    db_file = Path(db_path)
    if db_file.exists():
        db_file.unlink()
    db = GlyphDB(db_file, feature_backend=feature_backend)
    cur = db.conn.cursor()

    def read(path: Path):
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def load(st: Path, borrowed: bool) -> tuple[int, int, int]:
        verb = "INSERT OR IGNORE" if borrowed else "INSERT OR REPLACE"
        new_src: list[str] = []
        for r in read(st / "sources.jsonl"):
            cols = ",".join(r)
            cur.execute(f"{verb} INTO sources ({cols}) "
                        f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
            if borrowed and cur.rowcount:
                new_src.append(r["source_id"])
        n_inst = n_der = 0
        for meta_file in sorted((st / "instances").glob("*.jsonl")):
            for r in read(meta_file):
                png = st / "patches" / f"{_safe(r['instance_id'])}.png"
                if not png.exists():
                    continue
                raw = png.read_bytes()
                r = {**r, "patch_png": raw}
                cols = ",".join(r)
                cur.execute(f"{verb} INTO instances ({cols}) "
                            f"VALUES ({','.join('?' * len(r))})",
                            tuple(r.values()))
                if borrowed:
                    if not cur.rowcount:
                        continue          # 本书已有同 id 实例：本书优先
                    cur.execute("INSERT OR IGNORE INTO borrowed VALUES (?,?)",
                                (r["instance_id"], str(st)))
                n_inst += 1
                # 派生表示重算（原始圖 → 歸一化 → 骨架 / 特徵）
                gray = cv2.imdecode(np.frombuffer(raw, np.uint8),
                                    cv2.IMREAD_GRAYSCALE)
                db._write_derived(cur, r["instance_id"], normalize_patch(gray))
                n_der += 3
        if not borrowed:
            for f in sorted((st / "events").glob("*.jsonl")):
                for r in read(f):
                    cur.execute("INSERT OR IGNORE INTO events "
                                "(source_id, batch, seq, ts, op, payload) "
                                "VALUES (?,?,?,?,?,?)",
                                (r["source_id"], r.get("batch"), r.get("seq"),
                                 r.get("ts"), r.get("op"), r.get("payload")))
        eds: set[str] = set()
        for r in read(st / "glyphs.jsonl"):
            if borrowed:
                eds.add(r["edition_tag"])
            cols = ",".join(r)
            cur.execute(f"{verb} INTO glyphs ({cols}) "
                        f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
        n_ex = 0
        for r in read(st / "exemplars.jsonl"):
            if borrowed and not cur.execute("SELECT 1 FROM borrowed WHERE instance_id=?",
                                            (r["instance_id"],)).fetchone():
                continue
            row = cur.execute(
                "SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
                (r["edition_tag"], r["char"])).fetchone()
            if row is None:
                continue
            cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,?,?)",
                        (row[0], r["instance_id"], r["role"], r["added_at"]))
            n_ex += 1
        for r in read(st / "admissions.jsonl"):
            cols = ",".join(r.keys())
            cur.execute(f"{verb} INTO admissions ({cols}) "
                        f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
        if not borrowed:
            for r in read(st / "meta.jsonl"):
                cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                            (r["key"], r["value"]))
            for r in read(st / "pairs.jsonl"):
                cols = ",".join(r)
                cur.execute(f"INSERT OR REPLACE INTO pairs ({cols}) "
                            f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
            for r in read(st / "evictions.jsonl"):
                cur.execute("INSERT OR IGNORE INTO evictions (instance_id, char, reason, at) "
                            "VALUES (?,?,?,?)",
                            (r["instance_id"], r.get("char"), r.get("reason"), r["at"]))
            for r in read(st / "approx_clears.jsonl"):
                cur.execute("INSERT OR IGNORE INTO approx_clears (instance_id, label, at) "
                            "VALUES (?,?,?)", (r["instance_id"], r.get("label"), r["at"]))
        # 近似字侧表：借来的库也装（匹配到借来的近似例同样不该自动放行），但只装本次真装进来的实例
        for r in read(st / "approx_labels.jsonl"):
            if not cur.execute("SELECT 1 FROM instances WHERE instance_id=?",
                               (r["instance_id"],)).fetchone():
                continue
            if borrowed and not cur.execute("SELECT 1 FROM borrowed WHERE instance_id=?",
                                            (r["instance_id"],)).fetchone():
                continue
            cols = ",".join(r)
            cur.execute(f"{verb} INTO approx_labels ({cols}) "
                        f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
        if borrowed:
            own = db.book_edition()
            if own and own in eds:
                raise ValueError(f"借来的库 {st} 与本书同 edition {own!r}，分不开，拒绝合并")
            srcs = set(new_src)
            for k, v in (("borrowed_editions", eds), ("borrowed_sources", srcs)):
                old = cur.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
                v = sorted(v | set(json.loads(old[0]) if old else []))
                cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                            (k, json.dumps(v, ensure_ascii=False)))
        return n_inst, n_der, n_ex

    n_inst, n_der, n_ex = load(store, borrowed=False)
    n_borrowed = 0
    if extra_stores:
        cur.execute(BORROWED_TABLE)
        for extra in extra_stores:
            n_borrowed += load(Path(extra), borrowed=True)[0]
    db.conn.commit()
    stats = db.stats()
    db.close()
    out = {"instances": n_inst, "derived_recomputed": n_der,
           "exemplars": n_ex, **stats}
    if extra_stores:
        out["borrowed_instances"] = n_borrowed
    return out


def assert_db_not_silently_empty(db_path: str | Path,
                                 store_dir: str | Path | None = None) -> None:
    """自检（库路径 P0）：库打开后若 `instances` 为 0、而真源非空，直接报错。

    这个 bug 的伤害全部来自「空库不报错」——库路径解析错了，`glyph_match` /
    `seed_admit` 会对着一个空库（或压根是另一个文件）跑，产物看着全过
    （exit 0、ok N/N），逐字判 diff、候选全空，唯一露出来的破绽是单页耗时
    0.1~0.2 秒（真在算距离时是 7~21 秒），而没有任何东西会去看这个数字。

    只在「库存在但是空的」时才可能误判——真源不存在或本来就没有实例
    （如全新工作区、单测里的临时空库）不算异常，直接放行。
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
            n = c.execute("SELECT COUNT(*) FROM instances").fetchone()[0]
    except sqlite3.Error:
        return  # 打不开/表还没建，不是本检查的职责——下游自己会报更明确的错
    if n > 0:
        return
    if store_dir is None:
        from ..core.workspace import glyph_store_path
        store_dir = glyph_store_path()
    store = Path(store_dir)
    store_nonempty = store.exists() and any(store.glob("instances/*.jsonl"))
    if not store_nonempty:
        return
    raise RuntimeError(
        f"字形库为空（instances=0）：{db_path}\n"
        f"但真源 glyph_store 非空：{store}\n"
        "多半是库路径解析错了——写库（rebuild/import）与读库（glyph_match/"
        "seed_admit）用的不是同一个文件。查 GUJI_GLYPH_DB / GUJI_WORKSPACE 是否"
        "一致，或重新 `glyph-db rebuild` 一次。"
    )
