# -*- coding: utf-8 -*-
"""字形库自检：拿本书的每个刻例去和「本书其余刻例 / 另一本书的刻例 / 字体」比。

正本见 overview 仓 项目进展/图片初步数字化/进度/字形库/03-库自检与审阅台.md。

## 与 `audit.py` 的关系

`audit.shape_audit` 只在**本书内部**做留一比对（outlier 同字离群 / rival 形似他字），
这里沿用同一把尺子（HOG 召回 + `verify_pair_elastic` 精验，阈值 0.90 同口径），
再加两个参照面：

- **另一本书的刻例**（`rival_xbook`）：本例形上贴死另一本书里一个**别的字**的刻例，
  且比所有同字刻例（两本书都算）都贴。两本书共有 1,026 个字，互为对方的第二意见。
- **字体渲染**（`font_rival`）：本例与自己所定字的字体渲染不像，却与另一个字的渲染
  明显更像——对应「选了个相近字，Unicode 里其实有更像的」。字体是标准字形，
  刻本常有异写，所以这一路只作**弱信号**，要拉开 `FONT_MARGIN` 才标。

另有两个**不看形、只看来路**的加权（排序用，不单独出卡）：人裁 × 人裁冲突（手误嫌疑）、
`context` 放行（Step6 n-gram 会背整理本，见总览/14）。

全部只是**怀疑**，裁决归人（控制台字形库页「体检」tab），走 `glyph_audit` 事件。

## 语义分组

「同字」按 `VariantMap.semantic` 判（异体算同字），与 `audit.py` 一致：卽/即 的刻例
互为同字参照，不会互相标成 rival。
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .glyph_db import _unpng
from .glyph_ledger import _prov_class, cell_key, connect_ro

TH_OUTLIER = 0.90          # 同字留一最优低于此 → 离群（audit.TH_OUTLIER 同值）
TH_RIVAL = 0.90            # 异字达到此档且反超同字 → 形似他字（audit.TH_RIVAL 同值）
TH_RIVAL_SINGLE = 0.97     # 没有任何同字参照时，异字要贴到这档才标
FONT_TH = 0.90             # 字体异字 cov 至少到这档才算「更像别的字」
FONT_MARGIN = 0.15         # 且要比本字字体 cov 高出这么多（字体是标准形，刻本常异写；
                           # 北行 400 例小集：0.80/0.08 标 11 例几乎全是 三→亖、早→旱 这类噪声）
KNN_GLOBAL = 8             # 全池 HOG 近邻数
KNN_SAME = 3               # 同字补验（本书、他书各取）
KNN_FONT = 4               # 字体 HOG 近邻数

FLAG_LABELS = {
    "rival": "形似本书他字",
    "rival_xbook": "形似他书他字",
    "outlier": "同字离群",
    "font_rival": "更像另一个字的字体",
}


#: 拿来比「本字」的几套字体（2026-09-25，多字体）。Unicode 不给标准字形，码表是各来源的
#: 代表字形；能合法拿来逐像素比的全量字形只有字体。**只和一套不像多半是刻本异写，
#: 和每一套都不像才值得怀疑**——`font_rival` 因此看最优那套。字体档在引擎仓 `fonts/`：
#: iming 传承字形、jigmo 全 Unicode（CC0）、源流/源雲/源樣明體 TC（OFL）、康熙字典体（商业，
#: 只在本机比对，不进任何产物）。
FONT_SETS = {
    "iming": ("iming/I.Ming-8.10.ttf",),
    "jigmo": ("jigmo/Jigmo.ttf", "jigmo/Jigmo2.ttf", "jigmo/Jigmo3.ttf"),
    "genryu": ("genmin/GenRyuMin2TC-R.otf",),
    "genwan": ("genmin/GenWanMin2TC-R.otf",),
    "genyo": ("genmin/GenYoMin2TC-R.otf",),
    "kangxi": ("kangxi/TypeLand-KhangXiDict.otf",),
}
FONT_FAR = 0.80            # 本字在所有字体里的最优 cov 都低于此 = 「与哪套字体都不像」


def _font_root() -> Path:
    import os
    env = os.environ.get("GUJI_FONT_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "fonts"


_RENDERERS: dict = {}


def font_renderer(font: str):
    """一套字体的渲染器（缓存；读 cmap 要一两秒）。字体档不在返回 False。"""
    r = _RENDERERS.get(font)
    if r is None:
        from .font_glyphs import FontRenderer
        paths = [_font_root() / x for x in FONT_SETS[font]]
        paths = [x for x in paths if x.exists()]
        r = FontRenderer(paths) if paths else False
        _RENDERERS[font] = r
    return r


def font_norm(font: str, ch: str):
    """某套字体里一个字的归一图（渲染→canonical→归一，同 font_glyphs 导入口径）；缺字 None。"""
    key = (font, ch)
    if key in _RENDERERS:
        return _RENDERERS[key]
    from .normalize import normalize_patch
    r = font_renderer(font)
    out = None
    if r and len(ch) == 1:
        canon = r.render(ch)
        if canon is not None:
            n = normalize_patch(canon, strip_lines=False)
            out = n if n.any() else None
    _RENDERERS[key] = out
    return out


@dataclass
class Entry:
    instance_id: str
    char: str
    semantic: str
    norm: np.ndarray
    provenance: str
    origin: str                 # "" = 本书；否则 = 兄弟工作区 id


@dataclass
class Finding:
    instance_id: str
    char: str
    provenance: str
    flags: list[str] = field(default_factory=list)
    n_same_self: int = 0                  # 本书同字其他刻例数（按格）
    best_same: float = -1.0               # 同字最优（本书或他书）
    best_same_self: float = -1.0          # 本书同字最优（离群只看本书）
    same_peer: str | None = None
    same_peer_ws: str = ""
    rival: float = 0.0                    # 本书异字最优
    rival_char: str | None = None
    rival_peer: str | None = None
    rival_prov: str | None = None
    xrival: float = 0.0                   # 他书异字最优
    xrival_char: str | None = None
    xrival_peer: str | None = None
    xrival_ws: str = ""
    font_own: float | None = None         # 与本字各字体渲染的**最优** cov（都没这个字 = None）
    font_own_by: dict = field(default_factory=dict)   # {字体: cov}，见 FONT_SETS
    font_best: float = 0.0
    font_char: str | None = None
    font_peer: str | None = None
    human_conflict: bool = False          # 人裁 × 人裁互为 rival：手误嫌疑

    @property
    def score(self) -> float:
        """排序用怀疑分：形证据为主，来路加权。"""
        s = 0.0
        if "rival" in self.flags:
            s += 4 + (self.rival - TH_RIVAL) * 10
        if "rival_xbook" in self.flags:
            s += 3 + (self.xrival - TH_RIVAL) * 10
        if "outlier" in self.flags:
            s += 2
        if "font_rival" in self.flags:
            s += 1
        if self.human_conflict:
            s += 1.5
        if self.provenance == "context":
            s += 1
        return round(s, 3)

    def key(self) -> str:
        """白名单键：同一实例、同一组旗、同一对手——对手变了要重新出卡。"""
        peer = self.rival_peer or self.xrival_peer or self.font_char or ""
        return f"{self.instance_id}|{','.join(sorted(self.flags))}|{peer}"


def assign_flags(f: Finding) -> Finding:
    """由量出的分数定旗。与量分分开，改阈值不必重跑比对（小集迭代用）。"""
    f.flags = []
    best_same = max(f.best_same, 0.0)
    # 没有任何同字参照（单例字，两本书都没有）时，「最像的别的字」到 0.90 很平常
    # （樗/榜、俶/俄），要贴到 TH_RIVAL_SINGLE 才算可疑（北行 400 例小集标定）
    th = TH_RIVAL if f.best_same >= 0 else TH_RIVAL_SINGLE
    if f.n_same_self and f.best_same_self < TH_OUTLIER:
        f.flags.append("outlier")
    if f.rival >= th and f.rival > best_same:
        f.flags.append("rival")
    if f.xrival >= th and f.xrival > best_same:
        f.flags.append("rival_xbook")
    if (f.font_own is not None and f.font_best >= FONT_TH
            and f.font_best >= f.font_own + FONT_MARGIN):
        f.flags.append("font_rival")
    f.human_conflict = ("rival" in f.flags and f.provenance == "human"
                        and f.rival_prov == "human")
    return f


def load_entries(db_path: str | Path, origin: str = "", vmap=None) -> list[Entry]:
    """一个库的本书套刻例（非字体来源），带归一图。"""
    if vmap is None:
        from .variants import VariantMap
        vmap = VariantMap.load()
    c = connect_ro(db_path)
    try:
        fe = {r[0] for r in c.execute("SELECT edition_tag FROM sources WHERE kind='font'")}
        rows = c.execute(
            "SELECT e.instance_id, g.char, g.edition_tag, d.data, a.provenance "
            "FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id "
            "JOIN derived d ON d.instance_id=e.instance_id AND d.kind='norm' "
            "LEFT JOIN admissions a ON a.instance_id=e.instance_id").fetchall()
    finally:
        c.close()
    out = []
    for iid, ch, ed, data, prov in rows:
        if ed in fe or str(ed).startswith("font:"):
            continue
        out.append(Entry(iid, ch, vmap.semantic(ch), _unpng(data), _prov_class(prov), origin))
    return out


def load_font(db_path: str | Path, edition: str | None = None) -> tuple[list[str], np.ndarray] | None:
    """字体域的 (字表, 归一图堆)。库里没有字体域返回 None。"""
    c = connect_ro(db_path)
    try:
        eds = [r[0] for r in c.execute("SELECT edition_tag FROM sources WHERE kind='font'")]
        if not eds:
            return None
        ed = edition if edition in eds else eds[0]
        rows = c.execute(
            "SELECT g.char, d.data FROM glyphs g JOIN exemplars e ON e.glyph_id=g.glyph_id "
            "JOIN derived d ON d.instance_id=e.instance_id AND d.kind='norm' "
            "WHERE g.edition_tag=?", (ed,)).fetchall()
    finally:
        c.close()
    if not rows:
        return None
    return [r[0] for r in rows], np.stack([_unpng(r[1]) for r in rows])


def _hog(stack: np.ndarray) -> np.ndarray:
    from .features import get_feature
    F = np.asarray(get_feature("hog").extract(stack), dtype=np.float32)
    n = np.linalg.norm(F, axis=1, keepdims=True)
    return F / np.maximum(n, 1e-6)


def run_selfcheck(db_path: str | Path,
                  others: list[tuple[str, str | Path]] = (),
                  font_db: str | Path | None = None,
                  only: set[str] | None = None,
                  progress: bool = False) -> dict:
    """体检一本书的库。`others` = [(工作区 id, 库路径)]；`only` 只查这些实例（小集迭代用）。"""
    from .variants import VariantMap
    from .verify import verify_pair_elastic

    t0 = time.time()
    vmap = VariantMap.load()
    mine = load_entries(db_path, "", vmap)
    pool = list(mine)
    for ws, p in others:
        pool.extend(load_entries(p, ws, vmap))
    F = _hog(np.stack([e.norm for e in pool]))
    n_self = len(mine)

    # 本书 v1/v2 同格去重：同一格的另一份不能当自己的同字参照
    c = connect_ro(db_path)
    v1 = {r[0] for r in c.execute("SELECT source_id FROM sources WHERE pipeline_version='v1'")}
    c.close()
    cells = [cell_key(e.instance_id, v1) if not e.origin else f"{e.origin}|{e.instance_id}"
             for e in pool]

    by_sem: dict[tuple[str, str], list[int]] = {}
    for i, e in enumerate(pool):
        by_sem.setdefault((e.origin, e.semantic), []).append(i)

    font = load_font(font_db) if font_db else None
    if font:
        fchars, fnorms = font
        FF = _hog(fnorms)
        fidx = {ch: i for i, ch in enumerate(fchars)}

    cache: dict[tuple[int, int], float] = {}

    def cov(i: int, j: int) -> float:
        k = (i, j) if i < j else (j, i)
        if k not in cache:
            cache[k] = float(verify_pair_elastic(pool[i].norm, pool[j].norm).f1)
        return cache[k]

    findings: list[Finding] = []
    todo = [i for i in range(n_self) if only is None or pool[i].instance_id in only]
    for n, i in enumerate(todo):
        e = pool[i]
        sims = F @ F[i]
        order = np.argsort(-sims)
        neigh = [int(j) for j in order[: KNN_GLOBAL + 4]
                 if int(j) != i and cells[int(j)] != cells[i]][:KNN_GLOBAL]
        same_self = [j for j in by_sem.get(("", e.semantic), []) if cells[j] != cells[i]]
        for grp in [same_self] + [by_sem.get((ws, e.semantic), []) for ws, _ in others]:
            for j in sorted(grp, key=lambda j: -float(sims[j]))[:KNN_SAME]:
                if j not in neigh and j != i:
                    neigh.append(j)

        f = Finding(e.instance_id, e.char, e.provenance, n_same_self=len(same_self))
        for j in neigh:
            o = pool[j]
            v = cov(i, j)
            if o.semantic == e.semantic:
                if not o.origin and v > f.best_same_self:
                    f.best_same_self = v
                if v > f.best_same:
                    f.best_same, f.same_peer, f.same_peer_ws = v, o.instance_id, o.origin
            elif not o.origin:
                if v > f.rival:
                    f.rival, f.rival_char, f.rival_peer, f.rival_prov = v, o.char, o.instance_id, o.provenance
            elif v > f.xrival:
                f.xrival, f.xrival_char, f.xrival_peer, f.xrival_ws = v, o.char, o.instance_id, o.origin
        # 本字 × 每套字体（字不在某套里就跳过那套）
        for fname in FONT_SETS:
            fn = font_norm(fname, e.char)
            if fn is None and e.semantic != e.char:
                fn = font_norm(fname, e.semantic)
            if fn is not None:
                f.font_own_by[fname] = round(float(verify_pair_elastic(e.norm, fn).f1), 4)
        if f.font_own_by:
            f.font_own = max(f.font_own_by.values())
        if font:
            fs = FF @ F[i] if FF.shape[1] == F.shape[1] else None
            if fs is not None:
                for k in np.argsort(-fs)[:KNN_FONT]:
                    ch = fchars[int(k)]
                    if ch == e.char or vmap.semantic(ch) == e.semantic:
                        continue
                    v = float(verify_pair_elastic(e.norm, fnorms[int(k)]).f1)
                    if v > f.font_best:
                        f.font_best, f.font_char, f.font_peer = v, ch, f"font:{ch}"
        assign_flags(f)
        findings.append(f)
        if progress and (n + 1) % 500 == 0:
            print(f"  {n + 1}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)

    # 本书每个字与字体的距离：刻例对本字最优字体 cov 的中位数。整字都低 = 本书这个字的
    # 写法与哪套字体都不同——「最近似码位 / 刻本异写」的首选排查对象（按字，不按例出卡）
    per_char: dict[str, list[float]] = {}
    per_font: dict[str, list[float]] = {}
    for f in findings:
        if f.font_own is not None:
            per_char.setdefault(f.char, []).append(f.font_own)
        for k, v in f.font_own_by.items():
            per_font.setdefault(k, []).append(v)
    char_font = {ch: round(float(np.median(v)), 4) for ch, v in per_char.items()}
    best_font_count: dict[str, int] = {}
    for f in findings:
        if f.font_own_by:
            k = max(f.font_own_by, key=f.font_own_by.get)
            best_font_count[k] = best_font_count.get(k, 0) + 1

    flagged = [f for f in findings if f.flags]
    flagged.sort(key=lambda f: -f.score)
    counts: dict[str, int] = {}
    for f in flagged:
        for fl in f.flags:
            counts[fl] = counts.get(fl, 0) + 1
    return {
        "db": str(db_path),
        "others": [ws for ws, _ in others],
        "font_db": str(font_db) if font_db else None,
        "n_checked": len(findings),
        "n_flagged": len(flagged),
        "flag_counts": counts,
        "human_conflict": sum(f.human_conflict for f in flagged),
        "singletons_no_peer": sum(1 for f in findings if f.n_same_self == 0),
        "fonts": {k: {"n": len(v), "median": round(float(np.median(v)), 4),
                      "p10": round(float(np.percentile(v, 10)), 4),
                      "best_for": best_font_count.get(k, 0)} for k, v in per_font.items()},
        "no_font": sum(1 for f in findings if f.font_own is None),
        "char_font": char_font,
        "chars_font_far": sorted((ch for ch, v in char_font.items() if v < FONT_FAR),
                                 key=lambda c: char_font[c]),
        "params": {"TH_OUTLIER": TH_OUTLIER, "TH_RIVAL": TH_RIVAL,
                   "TH_RIVAL_SINGLE": TH_RIVAL_SINGLE, "FONT_TH": FONT_TH,
                   "FONT_MARGIN": FONT_MARGIN, "KNN_GLOBAL": KNN_GLOBAL,
                   "KNN_SAME": KNN_SAME, "KNN_FONT": KNN_FONT, "FONT_FAR": FONT_FAR,
                   "FONT_SETS": list(FONT_SETS)},
        "seconds": round(time.time() - t0, 1),
        "findings": flagged,
        "all": findings,
    }


# ── 落盘与白名单 ─────────────────────────────────────────


def out_dir() -> Path:
    from ..core.workspace import glyph_db_path
    return Path(glyph_db_path()).parent / "glyph_selfcheck"


def save(result: dict, out: Path | None = None) -> Path:
    out = out or out_dir()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "findings.jsonl", "w", encoding="utf-8") as fh:
        for f in result["findings"]:
            d = asdict(f)
            d["score"] = f.score
            d["key"] = f.key()
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    meta = {k: v for k, v in result.items() if k not in ("findings", "all")}
    meta["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (out / "summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return out


def load_findings(out: Path | None = None) -> tuple[dict, list[dict]]:
    out = out or out_dir()
    meta_p, f_p = out / "summary.json", out / "findings.jsonl"
    if not f_p.exists():
        return {}, []
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    with open(f_p, encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    return meta, rows


def decisions(out: Path | None = None) -> dict[str, dict]:
    """已裁的卡：{key: 最后一条裁决}（`glyph_audit` 消费者写的 decisions.jsonl）。"""
    p = (out or out_dir()) / "decisions.jsonl"
    got: dict[str, dict] = {}
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            for l in fh:
                if l.strip():
                    d = json.loads(l)
                    got[d["key"]] = d
    return got


def sibling_libraries() -> list[tuple[str, Path]]:
    """兄弟工作区的字形库 [(工作区 id, 库路径)]，不含当前工作区。"""
    from ..console.routers.workspace import discover_workspaces
    from ..core.workspace import GLYPH_DB_REL, workspace_root
    cur = workspace_root()
    cur = cur.resolve() if cur else None
    out = []
    for w in discover_workspaces(cur):
        p = Path(w["path"])
        if cur is not None and p.resolve() == cur:
            continue
        if (p / GLYPH_DB_REL).exists():
            out.append((w["id"], p / GLYPH_DB_REL))
    return out


def pick_font_db(*dbs) -> Path | None:
    """第一个带字体域的库（字体字形与书无关，哪本书的库里导过都一样）。"""
    for p in dbs:
        c = connect_ro(p)
        try:
            if c.execute("SELECT 1 FROM sources WHERE kind='font' LIMIT 1").fetchone():
                return Path(p)
        finally:
            c.close()
    return None
