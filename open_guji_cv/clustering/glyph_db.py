"""GlyphDB：跨書字形數據庫（SQLite 單檔，M8 字形庫升級）。

設計見 .claude/doc/char_clustering_design.md 第 19 節。要點：

- 原始字形 PNG 是唯一不可變真源；歸一化/骨架/特徵是帶版本的派生物；
- 字形層（char=精確異體字形）與語義層（semantic=正字）分離；
- glyphs 按 edition_tag 分域，同字不同版永不合併；
- 簇號只存在於 cluster_run 作用域，可累積標註只掛實例 id；
- 用戶反饋事件 (source,batch,seq) 冪等入庫，狀態=重放；
- exemplar 政策：K_MIN=3 / K_MAX=12，medoid + 最遠點採樣，
  近重複剔除（f1>0.95），用戶改判過的邊界例強制保留。
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

from .canonical import canonical_png
from .extractor import load_index
from .feedback import load_events, remap_events, replay_events
from .features import DEFAULT_FEATURE, get_feature
from .normalize import normalize_patch, skeletonize
from .variants import VariantMap
from .verify import verify_pair

K_MIN = 3            # 低於 → glyph 標 sparse
K_MAX = 12           # 每字形類 exemplar 上限（該版總數 ≤ 上限則全留）
DUP_F1 = 0.95        # 近重複判定
ALGO_VERSIONS = {"norm": "n1", "skeleton": "s1", "feat": "f1"}

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
CREATE TABLE IF NOT EXISTS admissions (
    -- 逐实例准入审计（种子协议 §3.5）：provenance + 完整判定证据。
    -- 主键即幂等闸：同一实例只准入一次，重复事件/重跑不重复进库。
    instance_id TEXT PRIMARY KEY,
    char TEXT NOT NULL,
    provenance TEXT NOT NULL,
    evidence TEXT,
    admitted_at TEXT NOT NULL
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

    def close(self) -> None:
        self.conn.close()

    # ── 導入 ─────────────────────────────────────────────

    def import_book(self, book_out_dir: str | Path,
                    edition_tag: str | None = None,
                    source_meta: dict | None = None,
                    k_max: int = K_MAX) -> dict:
        """一本書處理收尾後全量入庫（冪等，可重跑）。"""
        book_dir = Path(book_out_dir)
        source_id = book_dir.name
        edition = edition_tag or source_id
        meta = source_meta or {}
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO sources (source_id, collection, title, volume,
                 edition_tag, script_style, era, cols_per_page, chars_per_col,
                 pipeline_version, notes, kind, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET
                 edition_tag=excluded.edition_tag,
                 collection=COALESCE(excluded.collection, collection),
                 script_style=COALESCE(excluded.script_style, script_style)""",
            (source_id, meta.get("collection"), meta.get("title"),
             meta.get("volume"), edition, meta.get("script_style"),
             meta.get("era"), meta.get("cols_per_page"),
             meta.get("chars_per_col"), meta.get("pipeline_version"),
             meta.get("notes"), meta.get("kind", "woodblock"), _now()))

        instances = load_index(book_dir / "phase4_chars")
        pos_of = {i.id: k for k, i in enumerate(instances)}
        with open(book_dir / "phase5_clusters" / "clusters.json",
                  encoding="utf-8") as f:
            payload = json.load(f)
        clusters = payload["clusters"]
        members_of = {c["cluster_id"]: c["members"] for c in clusters}
        cluster_of = {m: cid for cid, ms in members_of.items() for m in ms}
        reps_of = {c["cluster_id"]: c.get("reps", []) for c in clusters}

        # 事件：冪等入庫 + 重綁重放
        raw_events = load_events(book_dir / "phase7_review" / "labels.jsonl")
        n_events = 0
        for ev in raw_events:
            ev_json = json.dumps(ev, ensure_ascii=False)
            batch, seq = ev.get("batch"), ev.get("seq")
            if batch is None or seq is None:
                # SQLite UNIQUE 视 NULL 各不相同——无批次号的事件
                # （本地 review 界面产生）按 payload 内容判重
                dup = cur.execute(
                    "SELECT 1 FROM events WHERE source_id=? AND payload=?",
                    (source_id, ev_json)).fetchone()
                if dup:
                    continue
            cur.execute(
                "INSERT OR IGNORE INTO events "
                "(source_id, batch, seq, ts, op, payload) "
                "VALUES (?,?,?,?,?,?)",
                (source_id, batch, seq, ev.get("ts"), ev.get("op", "?"),
                 ev_json))
            n_events += cur.rowcount
        events, _ = remap_events(raw_events, cluster_of)
        state = replay_events(events)

        # 聚類運行
        run_id = f"{source_id}:{payload.get('stats', {}).get('n_clusters', len(clusters))}:{len(instances)}"
        cur.execute("INSERT OR REPLACE INTO cluster_runs VALUES (?,?,?,?,?)",
                    (run_id, source_id,
                     json.dumps(payload.get("params", {}), ensure_ascii=False),
                     json.dumps(payload.get("stats", {}), ensure_ascii=False),
                     _now()))
        cur.executemany(
            "INSERT OR REPLACE INTO cluster_members VALUES (?,?,?)",
            [(run_id, m, cid) for cid, ms in members_of.items() for m in ms])

        # 實例（圖塊統一轉 canonical 格式後為真源，見 canonical.py）
        vmap = VariantMap.load()
        n_inst = n_labeled = 0
        for inst in instances:
            p = book_dir / "phase4_chars" / inst.patch_path
            if not p.exists():
                continue
            raw = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8),
                               cv2.IMREAD_GRAYSCALE)
            label = state.label_of(inst.id, cluster_of.get(inst.id))
            status = None
            if label:
                status = ("confirmed" if inst.id in state.instance_labels
                          else "propagated")
                n_labeled += 1
            sem = vmap.semantic(label) if label else None
            cp = ord(label) if label and len(label) == 1 else None
            cur.execute(
                """INSERT INTO instances (instance_id, source_id, page, col,
                     idx, bbox, patch_png, ink_ratio, width, height,
                     quality_flags, label, label_status, label_confidence,
                     semantic, unicode_cp, ids, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(instance_id) DO UPDATE SET
                     label=excluded.label,
                     label_status=excluded.label_status,
                     semantic=excluded.semantic,
                     unicode_cp=excluded.unicode_cp,
                     quality_flags=excluded.quality_flags,
                     updated_at=excluded.updated_at""",
                (inst.id, source_id, inst.page, inst.col, inst.idx,
                 json.dumps(list(inst.bbox)), canonical_png(raw),
                 inst.ink_ratio, inst.width, inst.height,
                 json.dumps(inst.flags, ensure_ascii=False),
                 label, status, 1.0 if label else None,
                 sem, cp, None, _now()))
            n_inst += 1

        # 字形類 + exemplars + 派生物
        npz = np.load(book_dir / "phase5_clusters" / "features.npz")
        patches, feats = npz["patches"], npz["feats"]
        boundary = set(state.instance_labels)
        for cid, moved in state.removed.items():
            boundary |= moved
        for cid, flag in state.cluster_flags.items():
            if flag == "impure":
                boundary |= set(members_of.get(cid, []))

        by_char: dict[str, list[str]] = {}
        for inst in instances:
            label = state.label_of(inst.id, cluster_of.get(inst.id))
            if label and inst.id in pos_of:
                by_char.setdefault(label, []).append(inst.id)

        n_glyphs = n_ex = 0
        for char, ids in by_char.items():
            chosen = self._select_exemplars(ids, pos_of, patches, feats,
                                            boundary, k_max)
            sem = vmap.semantic(char)
            cp = ord(char) if len(char) == 1 else None
            status = "sparse" if len(ids) < K_MIN else "stable"
            cur.execute(
                """INSERT INTO glyphs (edition_tag, char, semantic,
                     unicode_cp, ids, status, n_confirmed, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(edition_tag, char) DO UPDATE SET
                     n_confirmed=excluded.n_confirmed,
                     status=excluded.status,
                     updated_at=excluded.updated_at""",
                (edition, char, sem, cp, None, status, len(ids), _now()))
            gid = cur.execute(
                "SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
                (edition, char)).fetchone()[0]
            n_glyphs += 1
            for iid, role in chosen:
                cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,?,?)",
                            (gid, iid, role, _now()))
                self._write_derived(cur, iid, patches[pos_of[iid]])
                n_ex += 1

        n_pairs = self._extract_pairs(cur, state, members_of, reps_of,
                                      pos_of, source_id)
        self.conn.commit()
        return {"source": source_id, "edition": edition,
                "instances": n_inst, "labeled": n_labeled,
                "events_new": n_events, "glyphs": n_glyphs,
                "exemplars": n_ex, "pairs_new": n_pairs}

    def _select_exemplars(self, ids, pos_of, patches, feats,
                          boundary, k_max) -> list[tuple[str, str]]:
        """medoid + 邊界例強制 + FPS 補足；近重複剔除。"""
        f = np.stack([feats[pos_of[i]] for i in ids])
        if len(ids) <= k_max:
            base = [(i, "boundary" if i in boundary else "diverse")
                    for i in ids]
            med = int(np.argmin(((f[:, None] - f[None]) ** 2).sum(-1).mean(1)))
            base[med] = (ids[med], "medoid")
            return base
        d2 = ((f[:, None] - f[None]) ** 2).sum(-1)
        order = [int(np.argmin(d2.mean(1)))]              # medoid
        forced = [k for k, i in enumerate(ids)
                  if i in boundary and k != order[0]]
        order += forced[:max(0, k_max - 1)]
        rejected: set[int] = set()                         # 近重複，永久排除
        while len(order) < k_max:                          # FPS
            rest = [k for k in range(len(ids))
                    if k not in order and k not in rejected]
            if not rest:
                break
            far = max(rest, key=lambda k: min(d2[k][o] for o in order))
            # 近重複剔除：與最近選入的幾個 verify 過高則排除該候選
            pk = patches[pos_of[ids[far]]]
            if any(verify_pair(pk, patches[pos_of[ids[o]]]).f1 > DUP_F1
                   for o in order[-3:]):
                rejected.add(far)
            else:
                order.append(far)
        out = []
        for pos, k in enumerate(order):
            role = ("medoid" if pos == 0
                    else "boundary" if ids[k] in boundary else "diverse")
            out.append((ids[k], role))
        return out

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

    def _extract_pairs(self, cur, state, members_of, reps_of,
                       pos_of, source_id) -> int:
        n = 0
        def put(a, b, rel, origin):
            nonlocal n
            a, b = sorted((a, b))
            cur.execute("INSERT OR IGNORE INTO pairs VALUES (?,?,?,?,?,?)",
                        (a, b, rel, origin, source_id, _now()))
            n += cur.rowcount
        # diff：split 移出 vs 原簇代表
        for cid, moved in state.removed.items():
            reps = [r for r in reps_of.get(cid, []) if r in pos_of]
            for m in moved:
                if reps and m in pos_of:
                    put(reps[0], m, "diff", "split")
        # diff：impure 簇內兩兩（截頂 15 對/簇——错绑到大簇时
        # C(n,2) 会生成上万毒化对，见 feedback.remap_events 法定人数注）
        for cid, flag in state.cluster_flags.items():
            if flag != "impure":
                continue
            ms = [m for m in members_of.get(cid, []) if m in pos_of]
            got = 0
            for i in range(len(ms)):
                if got >= 15:
                    break
                for j in range(i + 1, len(ms)):
                    if got >= 15:
                        break
                    put(ms[i], ms[j], "diff", "impure_flag")
                    got += 1
        # same：確認簇內兩兩（截頂 6 對/簇）
        for cid, char in state.cluster_labels.items():
            ms = [m for m in members_of.get(cid, [])
                  if m in pos_of and state.label_of(m, cid) == char]
            got = 0
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    if got >= 6:
                        break
                    put(ms[i], ms[j], "same", "confirm_same")
                    got += 1
        return n

    # ── 單實例準入（種子協議 §3.5）───────────────────────

    def admit_instance(self, instance_id: str, char: str, patch_png: bytes,
                       norm: np.ndarray, *, provenance: str,
                       evidence: dict | None = None,
                       edition_tag: str | None = None,
                       page: str = "", col: int = 0, idx: int = 0,
                       bbox: list | None = None,
                       ink_ratio: float | None = None,
                       width: float | None = None,
                       height: float | None = None,
                       semantic: str | None = None) -> bool:
        """單個已裁決實例進庫（逐頁種子流程用，區別於 import_book 全量）。

        寫入：原始圖塊（真源）、派生表示（norm/skeleton/feat）、glyph
        條目（n_confirmed 累加）、exemplar（role='seed'，逐實例可檢索）、
        admissions 審計行（provenance + evidence JSON——設計 §3 紀律 1：
        逐實例證據，不做盲傳播；改判時憑它重放）。

        冪等：同一 instance_id 第二次調用直接返回 False，什麼都不寫。
        """
        cur = self.conn.cursor()
        if cur.execute("SELECT 1 FROM admissions WHERE instance_id=?",
                       (instance_id,)).fetchone():
            return False
        source_id = instance_id.split(":")[0]
        edition = edition_tag or source_id
        cur.execute(
            "INSERT OR IGNORE INTO sources (source_id, edition_tag, created_at)"
            " VALUES (?,?,?)", (source_id, edition, _now()))
        sem = semantic or char
        cp = ord(char) if len(char) == 1 else None
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
             char, provenance, 1.0, sem, cp, None, _now()))
        self._write_derived(cur, instance_id, norm)
        cur.execute(
            f"""INSERT INTO glyphs (edition_tag, char, semantic, unicode_cp,
                  ids, status, n_confirmed, updated_at)
                VALUES (?,?,?,?,?,'sparse',1,?)
                ON CONFLICT(edition_tag, char) DO UPDATE SET
                  n_confirmed = n_confirmed + 1,
                  status = CASE WHEN n_confirmed + 1 >= {K_MIN}
                           THEN 'stable' ELSE status END,
                  updated_at=excluded.updated_at""",
            (edition, char, sem, cp, None, _now()))
        gid = cur.execute(
            "SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
            (edition, char)).fetchone()[0]
        cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,?,?)",
                    (gid, instance_id, "seed", _now()))
        cur.execute("INSERT INTO admissions VALUES (?,?,?,?,?)",
                    (instance_id, char, provenance,
                     json.dumps(evidence, ensure_ascii=False)
                     if evidence is not None else None, _now()))
        self.conn.commit()
        return True

    def refresh_instance_patch(self, instance_id: str, patch_png: bytes,
                               norm: np.ndarray,
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
        cur.execute(
            "UPDATE instances SET patch_png=?, bbox=?, updated_at=? "
            "WHERE instance_id=?",
            (patch_png, json.dumps(bbox) if bbox is not None else None,
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
        cur.execute("DELETE FROM sources WHERE edition_tag=?", (edition_tag,))
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

    def dump(path: Path, rows, key=None) -> int:
        recs = [dict(r) for r in rows]
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
    counts["pairs"] = dump(
        out / "pairs.jsonl",
        cur.execute("SELECT * FROM pairs ORDER BY inst_a, inst_b, relation"))

    # 事件與實例按書分檔：一本書一個檔，審查增量只動一個檔
    n_ev = n_inst = n_png = 0
    written: set[str] = set()
    # kind='font' 的來源不導出：字形由字體檔 + 字表確定性重生成，
    # 進 Git 只是把幾萬張可再生的圖塞進版本歷史（另見字體外框版權）。
    for (src,) in db.conn.execute(
            "SELECT source_id FROM sources WHERE COALESCE(kind,'woodblock') "
            "!= 'font' ORDER BY 1"):
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
            png = d.pop("patch_png")
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


def rebuild_from_store(store_dir: str | Path, db_path: str | Path,
                       feature_backend: str = DEFAULT_FEATURE) -> dict:
    """Git 導出目錄 → SQLite 索引（派生表示按當前算法重算）。"""
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

    for r in read(store / "sources.jsonl"):
        cols = ",".join(r)
        cur.execute(f"INSERT OR REPLACE INTO sources ({cols}) "
                    f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
    n_inst = n_der = 0
    for meta_file in sorted((store / "instances").glob("*.jsonl")):
        for r in read(meta_file):
            png = store / "patches" / f"{_safe(r['instance_id'])}.png"
            if not png.exists():
                continue
            raw = png.read_bytes()
            r = {**r, "patch_png": raw}
            cols = ",".join(r)
            cur.execute(f"INSERT OR REPLACE INTO instances ({cols}) "
                        f"VALUES ({','.join('?' * len(r))})",
                        tuple(r.values()))
            n_inst += 1
            # 派生表示重算（原始圖 → 歸一化 → 骨架 / 特徵）
            gray = cv2.imdecode(np.frombuffer(raw, np.uint8),
                                cv2.IMREAD_GRAYSCALE)
            db._write_derived(cur, r["instance_id"], normalize_patch(gray))
            n_der += 3
    for f in sorted((store / "events").glob("*.jsonl")):
        for r in read(f):
            cur.execute("INSERT OR IGNORE INTO events "
                        "(source_id, batch, seq, ts, op, payload) "
                        "VALUES (?,?,?,?,?,?)",
                        (r["source_id"], r.get("batch"), r.get("seq"),
                         r.get("ts"), r.get("op"), r.get("payload")))
    for r in read(store / "glyphs.jsonl"):
        cols = ",".join(r)
        cur.execute(f"INSERT OR REPLACE INTO glyphs ({cols}) "
                    f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
    n_ex = 0
    for r in read(store / "exemplars.jsonl"):
        row = cur.execute(
            "SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
            (r["edition_tag"], r["char"])).fetchone()
        if row is None:
            continue
        cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,?,?)",
                    (row[0], r["instance_id"], r["role"], r["added_at"]))
        n_ex += 1
    for r in read(store / "pairs.jsonl"):
        cols = ",".join(r)
        cur.execute(f"INSERT OR REPLACE INTO pairs ({cols}) "
                    f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
    db.conn.commit()
    stats = db.stats()
    db.close()
    return {"instances": n_inst, "derived_recomputed": n_der,
            "exemplars": n_ex, **stats}
