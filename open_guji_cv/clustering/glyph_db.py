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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .extractor import load_index
from .feedback import load_events, remap_events, replay_events
from .normalize import skeletonize
from .variants import VariantMap
from .verify import verify_pair

K_MIN = 3            # 低於 → glyph 標 sparse
K_MAX = 12           # 每字形類 exemplar 上限（該版總數 ≤ 上限則全留）
DUP_F1 = 0.95        # 近重複判定
ALGO_VERSIONS = {"norm": "n1", "skeleton": "s1", "feat_hog": "hog1"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    collection TEXT, title TEXT, volume TEXT,
    edition_tag TEXT NOT NULL,
    script_style TEXT, era TEXT,
    cols_per_page INTEGER, chars_per_col INTEGER,
    pipeline_version TEXT, notes TEXT,
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


class GlyphDB:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

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
                 pipeline_version, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET
                 edition_tag=excluded.edition_tag,
                 collection=COALESCE(excluded.collection, collection),
                 script_style=COALESCE(excluded.script_style, script_style)""",
            (source_id, meta.get("collection"), meta.get("title"),
             meta.get("volume"), edition, meta.get("script_style"),
             meta.get("era"), meta.get("cols_per_page"),
             meta.get("chars_per_col"), meta.get("pipeline_version"),
             meta.get("notes"), _now()))

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

        # 實例（原始圖塊為真源）
        vmap = VariantMap.load()
        n_inst = n_labeled = 0
        for inst in instances:
            p = book_dir / "phase4_chars" / inst.patch_path
            if not p.exists():
                continue
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
                 json.dumps(list(inst.bbox)), p.read_bytes(),
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
                self._write_derived(cur, iid, patches[pos_of[iid]],
                                    feats[pos_of[iid]])
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

    def _write_derived(self, cur, iid, norm_patch, feat) -> None:
        rows = [
            (iid, "norm", ALGO_VERSIONS["norm"], _png(norm_patch)),
            (iid, "skeleton", ALGO_VERSIONS["skeleton"],
             _png(skeletonize(norm_patch))),
            (iid, "feat_hog", ALGO_VERSIONS["feat_hog"],
             feat.astype(np.float32).tobytes()),
        ]
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
        # diff：impure 簇內兩兩
        for cid, flag in state.cluster_flags.items():
            if flag != "impure":
                continue
            ms = [m for m in members_of.get(cid, []) if m in pos_of]
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    put(ms[i], ms[j], "diff", "impure_flag")
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

    # ── 檢索 ─────────────────────────────────────────────

    def query(self, norm_patch: np.ndarray, feat: np.ndarray,
              edition_hint: str | None = None, k: int = 5) -> list[DBHit]:
        """exemplar 特徵 kNN 粗排 → verify_pair 精驗。"""
        cur = self.conn.cursor()
        sql = """SELECT g.char, g.edition_tag, g.status, e.instance_id, d.data
                 FROM exemplars e
                 JOIN glyphs g ON g.glyph_id = e.glyph_id
                 JOIN derived d ON d.instance_id = e.instance_id
                   AND d.kind = 'feat_hog'"""
        args: tuple = ()
        if edition_hint:
            sql += " WHERE g.edition_tag = ?"
            args = (edition_hint,)
        rows = cur.execute(sql, args).fetchall()
        if not rows:
            return []
        feats = np.stack([np.frombuffer(r[4], np.float32) for r in rows])
        d2 = ((feats - feat[None]) ** 2).sum(1)
        hits: list[DBHit] = []
        for idx in np.argsort(d2)[:max(k * 3, 12)]:
            char, edition, status, iid, _ = rows[int(idx)]
            row = cur.execute(
                "SELECT data FROM derived WHERE instance_id=? AND kind='norm'",
                (iid,)).fetchone()
            if row is None:
                continue
            v = verify_pair(norm_patch, _unpng(row[0]))
            hits.append(DBHit(char=char, edition_tag=edition,
                              instance_id=iid, f1=v.f1, verdict=v.verdict,
                              sparse=(status == "sparse")))
        hits.sort(key=lambda h: -h.f1)
        # 每字形只留最高分
        seen, out = set(), []
        for h in hits:
            key = (h.edition_tag, h.char)
            if key not in seen:
                seen.add(key)
                out.append(h)
        return out[:k]

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
