# -*- coding: utf-8 -*-
"""借库书人审卡的「AI 首选」：CNN 原型检索，或与像素首选 RRF 融合（2026-09-27）。

任务书：overview `控制台统一/任务书-C-借库书人审首选改CNN原型.md`；根因见 R 道
`inbox/R-全唐文借库失效/20260927-2206-done.md`。

**背景**：全唐文借四庫字形库，像素比对（5-a，`glyph_match`）在用户人裁难例上首选
只对 52.4%——全唐文笔画相对字身只有四庫约六成粗、刻工字样也不同，像素覆盖度的
排名跟着歪（以→取、令→今、平→乎……整批认反）。同一个借来的库，r5 embedding
按字取均值原型后做检索，首选 94.2%，且几乎严格优于像素（像素对而 CNN 错只 3–5
格/3000）。审卡上的默认字原先就是像素那一路，整理那边报的「AI 首选大面积错」
主要是它。

**只对借库书生效**：书 yaml 书级开关，缺省关——

    params:
      review:
        first_pick: rrf      # 或 cnn；不写 / off = 关，卡片与改前逐字节一样

**原型来源可切换**（用户 09-27 22:20Z 定：借库只作冷启动，新书最终只用自己的字形）：

    params:
      review:
        first_pick: rrf
        own_db: output/glyph_own.db   # 本书自有库（H 道在建）；相对路径锚工作区根
        borrow_db: /path/to/siku/glyph.db  # 借来的库（缺省 = glyph_match 用的那个库）
        borrow_fallback: true         # 本书库缺的字回退借库原型；false = 只用本书库

某字在本书库里有刻例 → 该字原型只用本书刻例；没有 → 回退借来的库（`review_db_path`，
与像素那一路同一个库）；`borrow_fallback: false` 时缺的字干脆不进字集。没配 `own_db`
= 全用借库（冷启动）。卡片 `first.proto_src` 记 CNN 首位的原型来自哪边（own/borrow）。

`params:` 是 `{step_id: {…}}` 的书级覆盖（`core/book.py::BookSpec.params`）；
`review` 不是 Step id，引擎只按 `step.spec.id` 取，**不进任何 Step 的参数与指纹**，
开关只影响审卡装配，产物一个字节都不动。

**不碰放行**：只影响人审卡的默认字、排序、两路一致标记；`seed_admit` / `context_decide`
一行未改。「两路一致」精确率达不到 1% 门槛（R 实测维基集 97.6%、难例 90.7%），
**不许**拿它当放行通道（任务书「不做」）。

口径与 R 的 `research/qtw_libfail/a5_cnn.py` 相同：库里全部 exemplar
的 `derived.norm` → r5 embedding → 按字取均值再单位化；查询字块 → `normalize_patch`
缺省参数 → embedding，与全部原型取余弦。字集 = 库里的字（闭集）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

MODES = ("cnn", "rrf")
#: RRF 常数（Cormack 2009 的 60）。与 `cnn_candidates` 5-b 的融合同一个惯例值。
RRF_K = 60
#: 卡片上留几个 CNN 候选（与 `db.candidates[:5]` 对齐）。
CNN_TOPK = 5


def first_pick_mode(book_spec) -> str | None:
    """书 yaml `params.review.first_pick` → `"cnn"` / `"rrf"` / `None`（关）。

    写错了（不是 cnn/rrf/off/空）直接报错，不静默当关——开关写错却以为开着，
    审卡照旧给像素首选，正是这件事要修的那个错。
    """
    cfg = ((getattr(book_spec, "params", None) or {}).get("review") or {})
    v = cfg.get("first_pick")
    if v in (None, "", False, "off"):
        return None
    if v not in MODES:
        raise ValueError(f"书 yaml params.review.first_pick 只认 {MODES} 或 off，得到 {v!r}")
    return v


def _ws_path(v: str) -> str:
    """书 yaml 里的库路径：相对路径按工作区根解释（没有工作区按仓根），同 `core.workspace._resolve`。"""
    p = Path(v).expanduser()
    if not p.is_absolute():
        from ..core.workspace import REPO_ROOT, workspace_root
        p = (workspace_root() or REPO_ROOT) / p
    return str(p)


def review_db_path(book_spec) -> str:
    """借来的库（CNN 原型的回退来源）。优先级：

    1. `params.review.borrow_db`——**借库单独指**（2026-09-28）：服务器上 qtw-draft 的
       `output/glyph.db` 已换成全唐文自有库，四庫库得另给路径。放在 `review` 下而不是
       改 `glyph_match.db_path`，是因为后者进 Step5 参数指纹，一改全书 glyph_match 过期；
       `review` 不是 Step id，不进任何指纹。
    2. `params.glyph_match.db_path`（像素那一路显式配的库）；
    3. 同 `glyph_match` 的缺省解析（`GUJI_GLYPH_DB` → 工作区 `output/glyph.db`）。

    相对路径按工作区根解释。
    """
    params = getattr(book_spec, "params", None) or {}
    rv = params.get("review") or {}
    if rv.get("borrow_db"):
        return _ws_path(str(rv["borrow_db"]))
    gm = params.get("glyph_match") or {}
    if gm.get("db_path"):
        return str(gm["db_path"])
    from ..core.workspace import glyph_db_path
    return str(glyph_db_path())


def proto_sources(book_spec) -> tuple[str | None, bool]:
    """→ (本书自有库路径或 None, 缺字是否回退借库)。`own_db` 相对路径按工作区根解释。"""
    cfg = ((getattr(book_spec, "params", None) or {}).get("review") or {})
    own = cfg.get("own_db") or None
    if own:
        own = _ws_path(str(own))
    fb = cfg.get("borrow_fallback", True)
    if not isinstance(fb, bool):
        raise ValueError(f"书 yaml params.review.borrow_fallback 要 true/false，得到 {fb!r}")
    if own is None and not fb:
        raise ValueError("params.review：没配 own_db 又关了 borrow_fallback，原型一个字都没有")
    return own, fb


def merge_protos(own: tuple[list[str], np.ndarray] | None,
                 borrow: tuple[list[str], np.ndarray] | None,
                 fallback: bool = True) -> tuple[list[str], np.ndarray, list[str]]:
    """按字合并两套原型：本书库有的字用本书的，缺的字（`fallback` 时）用借库的。
    → (字表, 原型矩阵, 每字来源 'own'/'borrow')。纯函数。"""
    chars: list[str] = []
    rows: list[np.ndarray] = []
    src: list[str] = []
    have = set()
    if own is not None:
        for ch, v in zip(own[0], own[1]):
            chars.append(ch); rows.append(v); src.append("own"); have.add(ch)
    if fallback and borrow is not None:
        for ch, v in zip(borrow[0], borrow[1]):
            if ch not in have:
                chars.append(ch); rows.append(v); src.append("borrow")
    d = (own[1].shape[1] if own is not None and own[1].ndim == 2 else
         borrow[1].shape[1] if borrow is not None and borrow[1].ndim == 2 else 256)
    mat = np.stack(rows).astype(np.float32) if rows else np.zeros((0, d), np.float32)
    return chars, mat, src


# ── 纯函数：融合、标注（不碰 IO / 模型，单测直接喂数）────────────────────


def rrf_fuse(pixel: list, cnn: list, k: int = RRF_K) -> list[tuple[str, float]]:
    """像素候选（`[(字, cov), …]`，已按 cov 降序）与 CNN 候选（`[(字, cos), …]`）
    按名次做 RRF：`Σ 1/(k+名次)`。同分时 **CNN 名次靠前的赢**——R 实测 CNN
    几乎严格优于像素，平局交给更可靠的一路。同一个字在一路里出现多次只算最好名次。
    """
    def ranks(lst):
        out: dict[str, int] = {}
        for i, (ch, _s) in enumerate(lst or []):
            out.setdefault(ch, i + 1)
        return out
    rp, rc = ranks(pixel), ranks(cnn)
    score = {ch: 0.0 for ch in (*rp, *rc)}
    for ch, r in rp.items():
        score[ch] += 1.0 / (k + r)
    for ch, r in rc.items():
        score[ch] += 1.0 / (k + r)
    big = 10 ** 6
    order = sorted(score, key=lambda ch: (-score[ch], rc.get(ch, big), rp.get(ch, big)))
    return [(ch, round(score[ch], 6)) for ch in order]


def pick_first(pixel: list, cnn: list, mode: str) -> str | None:
    """默认首选字。`cnn`：CNN 首位（CNN 没出就退像素首位）；`rrf`：融合首位。"""
    if mode == "cnn":
        if cnn:
            return cnn[0][0]
        return pixel[0][0] if pixel else None
    if mode == "rrf":
        fused = rrf_fuse(pixel, cnn)
        return fused[0][0] if fused else None
    raise ValueError(f"未知 first_pick 模式 {mode!r}")


def first_view(pixel: list, cnn: list, mode: str, proto_src: str | None = None) -> dict:
    """卡片上的 `first` 字段：默认首选、两路各自首位、是否一致。

    `agree`：像素首位 == CNN 首位。任一路没出候选时是 `None`（无从谈一致），
    排序时与「不一致」一起排前面——没有第二路佐证的同样该先看。
    """
    p1 = pixel[0][0] if pixel else None
    c1 = cnn[0][0] if cnn else None
    return {
        "char": pick_first(pixel, cnn, mode),
        "mode": mode,
        "pixel": p1,
        "cnn": c1,
        "agree": (p1 == c1) if (p1 is not None and c1 is not None) else None,
        "cnn_candidates": [[ch, round(float(s), 4)] for ch, s in (cnn or [])[:CNN_TOPK]],
        # CNN 首位的原型来自本书自有库（own）还是借来的库（borrow）；没 CNN 候选为 None
        "proto_src": proto_src if cnn else None,
    }


def sort_disagree_first(cards: list[dict]) -> list[dict]:
    """不一致（含一路缺席）的排前面，其余保持原顺序（稳定排序）。没有 `first` 的卡不动位置档。"""
    def k(c):
        f = c.get("first")
        return 0 if (f is not None and f.get("agree") is not True) else 1
    return sorted(cards, key=k)


# ── 原型索引 ─────────────────────────────────────────────────────────


def _db_content_key(db_path: str) -> str:
    from ..steps.glyph_match import db_fingerprint
    return db_fingerprint(db_path)


def _load_exemplar_norms(db_path: str) -> dict[str, list[np.ndarray]]:
    from ..clustering.glyph_db import _unpng
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = c.execute(
            """SELECT g.char, d.data FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
               JOIN derived d ON d.instance_id=e.instance_id AND d.kind='norm'""").fetchall()
    finally:
        c.close()
    by: dict[str, list[np.ndarray]] = {}
    for ch, d in rows:
        by.setdefault(ch, []).append(_unpng(d).astype(np.uint8))
    return by


def build_protos(by_char: dict[str, list[np.ndarray]], embed, chunk: int = 256
                 ) -> tuple[list[str], np.ndarray]:
    """{字: [归一图…]} → (字表, 单位化均值原型矩阵 (n_char, d))。`embed` 注入，单测可换假的。"""
    chars = sorted(ch for ch, v in by_char.items() if v)
    protos = []
    for ch in chars:
        imgs = by_char[ch]
        acc = None
        for i in range(0, len(imgs), chunk):
            e = np.asarray(embed(imgs[i:i + chunk]), np.float64).sum(0)
            acc = e if acc is None else acc + e
        m = acc / len(imgs)
        protos.append((m / (np.linalg.norm(m) + 1e-9)).astype(np.float32))
    mat = np.stack(protos) if protos else np.zeros((0, 256), np.float32)
    return chars, mat


def rank_protos(emb: np.ndarray, chars: list[str], protos: np.ndarray, k: int = CNN_TOPK
                ) -> list[list[tuple[str, float]]]:
    """查询 embedding (N, d)（已单位化）× 原型 → 每条 top-k `[(字, 余弦)]`。"""
    if len(chars) == 0 or emb.shape[0] == 0:
        return [[] for _ in range(emb.shape[0])]
    S = emb @ protos.T
    kk = min(k, len(chars))
    out = []
    for row in S:
        idx = np.argpartition(-row, kk - 1)[:kk]
        idx = idx[np.argsort(-row[idx])]
        out.append([(chars[i], float(row[i])) for i in idx])
    return out


#: 一批过网络的图数。256 时 v006 冷算峰值 RSS +700~970 MB（卷积激活按批放大），
#: 服务器 2 核 7.5G、控制台 MemoryHigh 3.5G，几个请求并发就被节流（#166 加急，#167）。
EMBED_BATCH = 64


def _exemplar_rows(db_path: str) -> list[tuple[str, str]]:
    """库里全部 (字, 例键)，**不取图**。例键 = `instance_id:derived.rowid`——刻例归一图
    重算（`INSERT OR REPLACE`）会换 rowid，键跟着变；同一例同一张图键不变。"""
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [(ch, f"{iid}:{rid}") for ch, iid, rid in c.execute(
            """SELECT g.char, e.instance_id, d.rowid FROM exemplars e
               JOIN glyphs g ON g.glyph_id=e.glyph_id
               JOIN derived d ON d.instance_id=e.instance_id AND d.kind='norm'""")]
    finally:
        c.close()


def _norms_by_rowid(db_path: str, rowids: list[int]) -> dict[int, np.ndarray]:
    from ..clustering.glyph_db import _unpng
    out: dict[int, np.ndarray] = {}
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for s in range(0, len(rowids), 500):
            part = rowids[s:s + 500]
            q = f"SELECT rowid, data FROM derived WHERE rowid IN ({','.join('?' * len(part))})"
            for rid, d in c.execute(q, part):
                out[int(rid)] = _unpng(d).astype(np.uint8)
    finally:
        c.close()
    return out


def _npz_load(f: Path) -> dict[str, np.ndarray]:
    try:
        z = np.load(f, allow_pickle=False)
        return dict(zip(json.loads(str(z["keys"])), z["mat"]))
    except Exception:           # noqa: BLE001 — 没有/坏了当空
        return {}


def _npz_save(f: Path, d: dict[str, np.ndarray], dim: int = 256) -> None:
    import os
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f".{os.getpid()}.tmp.npz")
        keys = list(d)
        np.savez(tmp, keys=json.dumps(keys, ensure_ascii=False),
                 mat=(np.stack([d[k] for k in keys]) if keys else np.zeros((0, dim))
                      ).astype(np.float32))
        os.replace(tmp, f)
    except OSError:
        pass


class ProtoIndex:
    """库 → 按字均值原型。两层落 `cache_root()/review_protos/`：

    1. `protos_<库内容指纹|ckpt>.npz`：整份原型，库没变就直接读（秒开）；
    2. `inst_<库路径哈希>_<ckpt>.npz`：**逐例** embedding（键见 `_exemplar_rows`）。库一变
       （H 道每消费一条人裁就往本书库进刻例，指纹就变）不再整库重跑 CNN——只给新进的
       例过网络，其余读盘，按字取均值即得新原型。#166 加急：服务器上正是「每次请求都
       整库重建」把 cards 拖过 180 s、RSS 顶到 3.27G。

    内存里只留**每个库路径最新一份**（旧指纹那份丢掉，库一直在变时不会越积越多）。"""

    _mem: dict[str, tuple[str, tuple[list[str], np.ndarray]]] = {}

    @classmethod
    def get(cls, db_path: str, cnn) -> tuple[list[str], np.ndarray]:
        from ..clustering import cnn_candidates as cc
        from ..core.workspace import cache_root
        ck = cc.fingerprint(cnn.ckpt)
        key = hashlib.sha1(f"{_db_content_key(db_path)}|{ck}".encode()).hexdigest()[:16]
        hit = cls._mem.get(db_path)
        if hit and hit[0] == key:
            return hit[1]
        root = Path(cache_root()) / "review_protos"
        f = root / f"protos_{key}.npz"
        got = None
        if f.exists():
            try:
                z = np.load(f, allow_pickle=False)
                got = (json.loads(str(z["chars"])), z["mat"])
            except Exception:       # noqa: BLE001 — 坏缓存当没有，重建
                got = None
        if got is None:
            got = cls._build(db_path, cnn, root, ck)
            try:
                root.mkdir(parents=True, exist_ok=True)
                tmp = f.with_suffix(".tmp.npz")
                np.savez(tmp, chars=json.dumps(got[0], ensure_ascii=False), mat=got[1])
                tmp.replace(f)
            except OSError:
                pass
        cls._mem[db_path] = (key, got)
        return got

    @staticmethod
    def _build(db_path: str, cnn, root: Path, ck: str) -> tuple[list[str], np.ndarray]:
        rows = _exemplar_rows(db_path)
        pf = hashlib.sha1(str(Path(db_path).resolve()).encode()).hexdigest()[:12]
        inst_f = root / f"inst_{pf}_{ck}.npz"
        have = _npz_load(inst_f)
        need = sorted({int(k.rsplit(":", 1)[1]) for _, k in rows if k not in have})
        if need:
            rid2key = {int(k.rsplit(":", 1)[1]): k for _, k in rows}
            for s in range(0, len(need), 2000):
                imgs = _norms_by_rowid(db_path, need[s:s + 2000])
                ids = list(imgs)
                for t in range(0, len(ids), EMBED_BATCH):
                    part = ids[t:t + EMBED_BATCH]
                    for rid, e in zip(part, cnn.embed([imgs[r] for r in part])):
                        have[rid2key[rid]] = np.asarray(e, np.float32)
        live = {k for _, k in rows}
        _npz_save(inst_f, {k: v for k, v in have.items() if k in live})
        by: dict[str, list[np.ndarray]] = {}
        for ch, k in rows:
            if k in have:
                by.setdefault(ch, []).append(have[k])
        chars = sorted(by)
        protos = []
        for ch in chars:
            m = np.asarray(by[ch], np.float64).mean(0)
            protos.append((m / (np.linalg.norm(m) + 1e-9)).astype(np.float32))
        mat = np.stack(protos) if protos else np.zeros((0, 256), np.float32)
        return chars, mat


class EmbCache:
    """按格的 r5 embedding 落盘缓存（overview #166，2026-09-28）。

    审卡结果缓存（`review/cards.py::cached_cards`）的键里有事件水位，人裁一写入就整份
    失效；下次载入要给全书待审格重算 embedding——v006 4182 格实测占冷算 63 s 里的
    约 43 s（读图归一 12.6 s + CNN 前向 30 s），而这些字块图根本没变。这里按格记住：

    键 = 格 id + 该页 `cell_shrink` 产物的 sha256（字块图是它的纯函数；重切 / 重跑
    Step4 就换键），文件按 checkpoint 指纹分开（换模型整份作废）。落
    `cache_root()/review_emb/<书>/<ckpt 指纹>.npz`。只是算过的结果记下来，同一张图
    同一个模型给同一个向量，首选与放行逻辑一个字不动。
    """

    def __init__(self, book: str, store, ckpt_fp: str):
        from ..core.workspace import cache_root
        from ..feedback.events import EventLog
        self.book, self.store = book, store
        self.path = (Path(cache_root()) / "review_emb" / EventLog.safe_batch_name(book)
                     / f"{ckpt_fp}.npz")
        self._page_sha: dict[int, str | None] = {}
        self._new: dict[str, np.ndarray] = {}
        self._have: dict[str, np.ndarray] = {}
        if self.path.exists():
            try:
                z = np.load(self.path, allow_pickle=False)
                self._have = dict(zip(json.loads(str(z["keys"])), z["mat"]))
            except Exception:           # noqa: BLE001 — 坏缓存当没有
                self._have = {}

    def _key(self, card: dict) -> str | None:
        pg = card["page"]
        if pg not in self._page_sha:
            from ..core.spec import page_key
            try:
                ent = self.store.manifest(self.book, "cell_shrink").get(page_key(pg))
                self._page_sha[pg] = getattr(ent, "sha256", None)
            except Exception:           # noqa: BLE001 — 取不到产物指纹就不缓存这页
                self._page_sha[pg] = None
        sha = self._page_sha[pg]
        return f"{card['id']}|{sha}" if sha else None

    def get(self, card: dict) -> np.ndarray | None:
        k = self._key(card)
        return None if k is None else self._have.get(k)

    def put(self, card: dict, vec: np.ndarray) -> None:
        k = self._key(card)
        if k is not None:
            self._new[k] = np.asarray(vec, np.float32)

    def save(self) -> None:
        """并进已有的再原子写回；写不了（盘满/只读）就算了，下次重算。"""
        if not self._new:
            return
        import os
        allk = {**self._have, **self._new}
        keys = list(allk)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp.npz")
            np.savez(tmp, keys=json.dumps(keys, ensure_ascii=False),
                     mat=np.stack([allk[k] for k in keys]).astype(np.float32))
            os.replace(tmp, self.path)
            self._have, self._new = allk, {}
        except OSError:
            pass


# ── 装配：给卡片挂 `first` ───────────────────────────────────────────


def load_index(borrow_db: str | None, cnn, own_db: str | None = None, fallback: bool = True
               ) -> tuple[list[str], np.ndarray, dict[str, str]]:
    """两个库 → 合并后的原型索引 + {字: 来源}。本书库文件不存在（H 还没建）时当空库，
    有回退就全走借库，不报错。"""
    own = ProtoIndex.get(own_db, cnn) if own_db and Path(own_db).exists() else None
    borrow = ProtoIndex.get(borrow_db, cnn) if (fallback and borrow_db) else None
    chars, mat, src = merge_protos(own, borrow, fallback)
    return chars, mat, dict(zip(chars, src))


def cnn_ranks_for_patches(norm_patches: list, db_path: str | None, cnn=None, k: int = CNN_TOPK,
                          own_db: str | None = None, fallback: bool = True,
                          index: tuple | None = None, emb_out: list | None = None
                          ) -> list[list[tuple[str, float]]]:
    """归一化 64² 图（可含 `None`＝缺图）→ 每条 CNN 原型 top-k。缺图的给 `[]`。
    评测脚本与卡片装配共用这一条，量的就是线上跑的那份代码。
    `db_path` = 借来的库；`own_db` = 本书自有库（见模块头）。`index` 可直接传
    `(字表, 原型矩阵)`（评测里模拟本书库用），此时不读库。

    `emb_out`：给一个与 `norm_patches` 等长的列表，顺手把每条的 embedding 填进去
    （缺图留 `None`）——批审组内聚簇（#166）直接复用，不再过第二遍网络。"""
    from ..clustering import cnn_candidates as cc
    cnn = cnn or cc.shared()
    out: list[list] = [[] for _ in norm_patches]
    if not cnn.available:
        return out
    if index is not None:
        chars, protos = index[0], index[1]
    else:
        chars, protos, _ = load_index(db_path, cnn, own_db, fallback)
    idx = [i for i, p in enumerate(norm_patches) if p is not None]
    for s in range(0, len(idx), EMBED_BATCH):
        part = idx[s:s + EMBED_BATCH]
        emb = cnn.embed([norm_patches[i] for i in part])
        for i, r in zip(part, rank_protos(emb, chars, protos, k)):
            out[i] = r
        if emb_out is not None:
            for j, i in enumerate(part):
                emb_out[i] = np.asarray(emb[j], np.float32)
    return out


def _card_patch(ctx, card: dict):
    from ..clustering.normalize import normalize_patch
    from ..core.spec import cell_key
    key = cell_key(card["page"], card["col"], card["slot"]) + (card.get("sub") or "")
    try:
        img = ctx.image("char_patch", key)
    except Exception:           # noqa: BLE001 — 缺图就这张卡没有 CNN 那一路
        return None
    return normalize_patch(img)


def annotate(book: str, cards: list[dict], store, mode: str, bk=None,
             emb_out: dict | None = None) -> dict:
    """给每张卡挂 `first`（见 `first_view`），原地改。返回摘要（一致率等，供面板/日志）。

    CNN 不可用（没装 torch / 缺 checkpoint）时 CNN 一路为空：`cnn` 模式退像素首位，
    `rrf` 模式等于像素排名——不报错、不挡审卡，`summary.cnn_ready=False` 讲明白。

    `emb_out`：给一个 dict 就顺手填 `{卡片 id: r5 embedding}`（缺图的卡不填），供批审
    组内聚簇（#166）复用；不进卡片、不改返回值。
    """
    from ..clustering import cnn_candidates as cc
    from ..core.book import load_book
    from ..core.step import RunContext
    from ..products.cache import ImageCache
    bk = bk or load_book(book)
    cnn = cc.shared()
    own_db, fallback = proto_sources(bk)
    ranks: list[list] = [[] for _ in cards]
    src_of: dict[str, str] = {}
    if cnn.available and cards:
        ctx = RunContext(bk, store, ImageCache(), log=lambda *_: None)
        chars, protos, src_of = load_index(review_db_path(bk), cnn, own_db, fallback)
        ec = EmbCache(book, store, cc.fingerprint(cnn.ckpt))
        embs: list = [ec.get(c) for c in cards]
        need = [i for i, e in enumerate(embs) if e is None]
        if need:
            fresh: list = [None] * len(need)
            cnn_ranks_for_patches([_card_patch(ctx, cards[i]) for i in need], None, cnn,
                                  index=(chars, protos), emb_out=fresh)
            for i, e in zip(need, fresh):
                if e is not None:
                    embs[i] = e
                    ec.put(cards[i], e)
            ec.save()
        ok = [i for i, e in enumerate(embs) if e is not None]
        if ok:
            for i, r in zip(ok, rank_protos(np.stack([embs[i] for i in ok]), chars, protos)):
                ranks[i] = r
        if emb_out is not None:
            emb_out.update({c["id"]: e for c, e in zip(cards, embs) if e is not None})
    n_agree = n_both = 0
    n_own = 0
    for c, cr in zip(cards, ranks):
        pixel = [tuple(x) for x in ((c.get("db") or {}).get("candidates") or [])]
        c["first"] = first_view(pixel, cr, mode, src_of.get(cr[0][0]) if cr else None)
        n_own += c["first"]["proto_src"] == "own"
        if c["first"]["agree"] is not None:
            n_both += 1
            n_agree += bool(c["first"]["agree"])
    return {"mode": mode, "cnn_ready": bool(cnn.available), "n": len(cards),
            "n_both": n_both, "n_agree": n_agree,
            "own_db": own_db, "borrow_db": review_db_path(bk) if fallback else None,
            "borrow_fallback": fallback,
            "n_own_chars": sum(v == "own" for v in src_of.values()),
            "n_borrow_chars": sum(v == "borrow" for v in src_of.values()),
            "n_first_from_own": n_own}
