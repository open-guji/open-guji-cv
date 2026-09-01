"""刻本字形库体检（glyphdb-audit skill 的核心）。

进库的每个字形都被当作后续匹配的证据，错一个毒一片，所以要能随时
体检。三路互相独立的怀疑信号（都只是**怀疑**，裁决归人）：

- **outlier 形离群**：同字的刻例应当互相很像。留一法：本例与同字
  其余刻例的最优 verify cov 低于阈 → 可疑（选错字/图块脏/重切漏网）。
- **rival 竞争字**：本例与**别的字**的刻例 cov 反超同字最优且到高档
  → 形上更像别人，标错的典型形态（audit 首轮实锤：14:9:14 標成
  紀，形上 0.97 貼死庫内「絕」）。
- **ocr OCR 异议**：RapidOCR top1（s2t + 语义归一）≠ 库内字且置信高。
  OCR 校准不可靠（三信号分析里 45%），单独只算弱信号，与前两路
  叠加时权重高。

体检输出审查页（复用种子页三层持久化），人裁两个动作：

- ``evict`` 撤库重审：删 admissions/exemplars/derived/instances，
  队列行退回 pending_review（note=audit_evict）→ 下次导出重新出卡；
- ``ok`` 没问题：进白名单（audit_ok.json），下轮体检不再骚扰。

单例字（全库只有一个刻例）没有同字参照，只有 ocr 信号可用——报告里
单独列出，别误读成「没问题」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .features import get_feature
from .verify import verify_pair_elastic

# 形离群阈：同字最优 cov 低于此才怀疑。同字同刻工的覆盖率天然 ≥0.95
# 档（match_solo 标定），0.90 以下已经是「不太像同一个刻字」的水位。
# 判据 2026-08-24 起随匹配栈换成 elastic——体检必须和匹配器用同一把尺，
# 否则体检打的旗是匹配器早已不犯的错。elastic 的分数经分位校准回
# coverage 刻度（verify.py），下面三个阈的操作点因此照旧。
TH_OUTLIER = 0.90
# 竞争字达标线：异字 cov 要到这个档才算「形上更像别人」（低档的
# 异字相似遍地都是，不构成怀疑）。
TH_RIVAL = 0.90
# OCR 异议置信线：top1 prob 低于此的异议不采（垃圾输出居多）。
TH_OCR = 0.80
# 留一验证的邻居数：全局 top-K 特征近邻 + 同字 top-M 补验
KNN_GLOBAL = 8
KNN_SAME = 3


@dataclass
class AuditEntry:
    instance_id: str
    char: str
    semantic: str
    norm: np.ndarray             # 64×64 {0,1}
    provenance: str | None = None


@dataclass
class AuditFinding:
    instance_id: str
    char: str
    flags: list[str] = field(default_factory=list)
    best_same: float = 0.0       # 同字留一最优 cov（无同字参照 = -1）
    same_peer: str | None = None
    best_other: float = 0.0
    other_char: str | None = None
    other_peer: str | None = None
    ocr_char: str | None = None
    ocr_prob: float = 0.0

    @property
    def score(self) -> int:
        """怀疑等级，排序用：rival+ocr > rival > outlier+ocr > outlier > ocr。"""
        s = 0
        if "rival" in self.flags:
            s += 4
        if "outlier" in self.flags:
            s += 2
        if "ocr" in self.flags:
            s += 1
        return s


def shape_audit(entries: list[AuditEntry],
                knn_global: int = KNN_GLOBAL,
                knn_same: int = KNN_SAME) -> dict[str, AuditFinding]:
    """留一法形状体检。返回 {instance_id: AuditFinding}（全量，含未标旗的）。

    全局特征 top-K 近邻做 verify（顺带量出竞争字），再补验同字特征
    top-M（保证同字参照一定被量到——全局近邻可能全被别的字占掉）。
    """
    feat = get_feature("hog")
    F = feat.extract(np.stack([e.norm for e in entries]))
    F = np.asarray(F, dtype=np.float32)
    by_sem: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        by_sem.setdefault(e.semantic, []).append(i)

    out: dict[str, AuditFinding] = {}
    cache: dict[tuple[int, int], float] = {}

    def cov(i: int, j: int) -> float:
        k = (i, j) if i < j else (j, i)
        if k not in cache:
            cache[k] = float(verify_pair_elastic(entries[i].norm,
                                                 entries[j].norm).f1)
        return cache[k]

    for i, e in enumerate(entries):
        sims = F @ F[i]
        order = np.argsort(-sims)
        neigh = [int(j) for j in order if int(j) != i][:knn_global]
        peers = [j for j in by_sem[e.semantic] if j != i]
        peers.sort(key=lambda j: -float(sims[j]))
        for j in peers[:knn_same]:
            if j not in neigh:
                neigh.append(j)

        f = AuditFinding(e.instance_id, e.char, best_same=-1.0)
        for j in neigh:
            c = cov(i, j)
            if entries[j].semantic == e.semantic:
                if c > f.best_same:
                    f.best_same, f.same_peer = c, entries[j].instance_id
            else:
                if c > f.best_other:
                    f.best_other = c
                    f.other_char = entries[j].char
                    f.other_peer = entries[j].instance_id
        if peers and f.best_same < TH_OUTLIER:
            f.flags.append("outlier")
        if f.best_other >= TH_RIVAL and f.best_other > max(f.best_same, 0.0):
            f.flags.append("rival")
        out[e.instance_id] = f
    return out


def apply_ocr(findings: dict[str, AuditFinding],
              readings: dict[str, tuple[str, float]],
              semantic_fn, th_ocr: float = TH_OCR) -> None:
    """把 OCR 读数并进体检结果：top1 语义 ≠ 库内字且 prob 过线 → ocr 旗。"""
    for iid, f in findings.items():
        r = readings.get(iid)
        if not r:
            continue
        ch, prob = r
        f.ocr_char, f.ocr_prob = ch, prob
        if ch and prob >= th_ocr and semantic_fn(ch) != semantic_fn(f.char):
            f.flags.append("ocr")


def evict_instance(db, instance_id: str) -> str | None:
    """撤库：删四表行 + 修正字头（n_confirmed 减一，最后一个刻例撤掉就删字头）。

    返回原字（不存在返回 None）。

    2026-08-25 修：原来那条清壳 SQL 一次都没生效过。它写的是

        DELETE FROM glyphs WHERE glyph_id NOT IN (SELECT ... FROM exemplars)
          AND glyph_id NOT IN (SELECT DISTINCT glyph_id FROM instances
                               WHERE glyph_id IS NOT NULL)

    而 `instances` **根本没有 glyph_id 列**——SQLite 于是把子查询里的
    `glyph_id` 解析成外层 `glyphs.glyph_id`（相关子查询），子查询对每个
    instance 行都返回外层那个值，`NOT IN` 恒为假，整条 DELETE 永不删任何行。
    没报错，只是默默不干活：撤库一轮下来库里攒了 34 个零刻例的空壳字头，
    `n_confirmed` 也还停在 1。改成只按 exemplars 判，并同步 n_confirmed。
    """
    row = db.conn.execute(
        """SELECT g.glyph_id, g.char FROM exemplars e
           JOIN glyphs g ON g.glyph_id=e.glyph_id WHERE e.instance_id=?""",
        (instance_id,)).fetchone()
    for t in ("admissions", "exemplars", "derived", "instances"):
        db.conn.execute(f"DELETE FROM {t} WHERE instance_id=?", (instance_id,))
    if row:
        gid = row[0]
        left = db.conn.execute(
            "SELECT count(*) FROM exemplars WHERE glyph_id=?", (gid,)).fetchone()[0]
        if left:
            db.conn.execute(
                "UPDATE glyphs SET n_confirmed=? WHERE glyph_id=?", (left, gid))
        else:
            db.conn.execute("DELETE FROM glyphs WHERE glyph_id=?", (gid,))
    db.conn.commit()
    return row[1] if row else None
