"""段分：任意一段列图（页面坐标 y0–y1）当作「一个字」，和钉死的库快照比，给前 k 名 (字, cov)。

给史記备选切线挑路用（CV3，2026-11-25；CV0 口径）：**离线工具**，不是 Step，不读 glyph_match／Step5a 产物，
也**不读运行时 glyph.db**——库刻例的嵌入在导出时一次算好存成 npz「库快照」，快照头记模型 sha 与口径版本，
调用方把这两个 sha 记进自己的表头／指纹。换库＝出新快照。

口径（SCORE_VERSION）：
* 查询图＝列条（页面像素，x 取 `x_range` 右上原点）的 y0:y1 → `to_canonical` → `normalize_patch`（与入库、Step4 同一套）→ SimNet 嵌入；
* 库刻例＝快照里每例的嵌入（`normalize_patch(patches/*.png)` → 同一网络）；
* 字 c 的分＝该字**最近 3 个刻例**余弦均值，不足 3 个用「近邻窗最后一名」补（偏高估，只许同列内比较）；
  有 `calib.json` 时按 `sim_cnn.load_calib` 映到 cov 尺度，`raw` 另给原始余弦；
* 近邻窗 `K_NEIGHBORS` 内没出现的字不上榜。

只给分，不挑路；不看参校本字。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCORE_VERSION = "segscore-1"
K_NEIGHBORS = 60
N_NEAREST = 3


@dataclass
class Snapshot:
    E: np.ndarray            # (N,128) float32，已归一
    chars: list[str]         # 每例的字
    ids: list[str]
    meta: dict               # model_sha / calib_sha / score_version / exclude / store_note / n

    @property
    def sha(self) -> str:
        h = hashlib.sha256()
        h.update(np.ascontiguousarray(self.E).tobytes())
        h.update("\n".join(self.chars).encode("utf-8"))
        h.update(json.dumps({k: self.meta[k] for k in ("model_sha", "calib_sha", "score_version")},
                            sort_keys=True).encode())
        return h.hexdigest()


def _sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build_snapshot(store_dir: "str | Path | list", model_path: str, out_npz: str | Path, *,
                   exclude_prefixes: tuple[str, ...] = (), only_live: bool = True) -> Snapshot:
    """从字形库导出目录（`glyph_store/`：exemplars.jsonl + patches/）算快照。

    `exclude_prefixes`：刻例 id 以这些开头的不进快照（回放时排除被测册，防自匹配，如 `("v2:42:",)`）。"""
    import cv2
    from .normalize import normalize_patch
    from .sim_cnn import embed, load_net, resolve_model

    stores = [Path(x) for x in (store_dir if isinstance(store_dir, (list, tuple)) else [store_dir])]
    rows = []
    for st in stores:                       # 多库（借库）：每行带来源库目录
        for l in (st / "exemplars.jsonl").read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l); r["_store"] = st; rows.append(r)
    mp = resolve_model(model_path)
    net = load_net(model_path)
    ids, chars, patches = [], [], []
    for r in rows:
        iid = r["instance_id"]
        if any(iid.startswith(p) for p in exclude_prefixes):
            continue
        f = r["_store"] / "patches" / (iid.replace(":", "_") + ".png")
        if not f.is_file():
            continue
        g = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        ids.append(iid)
        chars.append(r["char"])
        patches.append(normalize_patch(g))
    E = embed(net, patches)
    cal = mp.parent / "calib.json"
    meta = dict(model_sha=_sha_file(mp), calib_sha=_sha_file(cal) if cal.is_file() else "",
                score_version=SCORE_VERSION, exclude=list(exclude_prefixes), n=len(ids),
                stores=[s.parent.parent.name for s in stores])
    snap = Snapshot(E, chars, ids, meta)
    meta["snapshot_sha"] = snap.sha
    np.savez_compressed(out_npz, E=E, chars=np.array(chars), ids=np.array(ids), meta=json.dumps(meta, ensure_ascii=False))
    return snap


def load_snapshot(npz: str | Path) -> Snapshot:
    z = np.load(npz, allow_pickle=False)
    return Snapshot(z["E"].astype(np.float32), [str(x) for x in z["chars"]], [str(x) for x in z["ids"]],
                    json.loads(str(z["meta"])))


def crop_segment(page_gray: np.ndarray, x_range: tuple[float, float], y0: float, y1: float) -> np.ndarray:
    """页面灰度图（原图，左上原点）上取一段列条：`x_range` 是右上原点的 (x0,x1)，y 从上量。"""
    H, W = page_gray.shape[:2]
    X0, X1 = int(round(W - x_range[1])), int(round(W - x_range[0]))
    a, b = int(round(max(0, y0))), int(round(min(H, y1)))
    return page_gray[a:b, max(0, X0):min(W, X1)]


def query_embeddings(crops: list[np.ndarray], model_path: str) -> np.ndarray:
    from .canonical import to_canonical
    from .normalize import normalize_patch
    from .sim_cnn import embed, load_net
    net = load_net(model_path)
    ps = []
    for c in crops:
        if c.size == 0 or min(c.shape[:2]) < 2:
            ps.append(np.zeros((64, 64), np.uint8))
        else:
            ps.append(normalize_patch(to_canonical(c)))
    return embed(net, ps)


def score_embeddings(snap: Snapshot, Q: np.ndarray, *, topk: int = 5, calib=None, window: int = K_NEIGHBORS) -> list[dict]:
    """一批查询嵌入 → 每个 `{topk:[(字,cov)], lead, top1, raw1}`；calib＝`sim_cnn.load_calib` 的结果或 None。"""
    out = []
    S = Q @ snap.E.T
    k = min(window, S.shape[1])
    chars = snap.chars
    for i in range(len(Q)):
        row = S[i]
        idx = np.argpartition(-row, k - 1)[:k]
        idx = idx[np.argsort(-row[idx])]
        floor = float(row[idx[-1]])
        per: dict[str, list[float]] = {}
        for j in idx:
            per.setdefault(chars[j], []).append(float(row[j]))
        sc = []
        for c, v in per.items():
            v = (v + [floor] * N_NEAREST)[:N_NEAREST]
            sc.append((c, float(np.mean(v))))
        sc.sort(key=lambda t: -t[1])
        if calib is not None:
            sc = [(c, float(np.interp(s, *calib))) for c, s in sc]
        top = sc[:topk]
        out.append(dict(topk=[(c, round(s, 4)) for c, s in top],
                        lead=round(top[0][1] - top[1][1], 4) if len(top) > 1 else None,
                        top1=top[0][1], raw1=float(row[idx[0]])))
    return out


def ink_info(crop: np.ndarray) -> dict:
    """墨迹信息：墨占比、墨的纵向范围占段高、上下留白占段高（Otsu 二值，只做参考）。"""
    import cv2
    if crop.size == 0 or min(crop.shape[:2]) < 2:
        return dict(ink=0.0, h_frac=0.0, top_gap=1.0, bot_gap=1.0)
    g = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(g, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    rows = np.where(bw.sum(1) > 0)[0]
    H = bw.shape[0]
    if not len(rows):
        return dict(ink=0.0, h_frac=0.0, top_gap=1.0, bot_gap=1.0)
    return dict(ink=round(float(bw.mean()), 4), h_frac=round((rows[-1] - rows[0] + 1) / H, 4),
                top_gap=round(rows[0] / H, 4), bot_gap=round((H - 1 - rows[-1]) / H, 4))


def score_segments(snap: Snapshot, model_path: str, segs: list[tuple], get_page, *, topk: int = 5,
                   batch: int = 256) -> list[dict]:
    """segs＝[(vol, page, col, y0, y1, x0, x1)]（页面像素，右上原点，x0/x1＝列的左右）；
    get_page(vol, page) → 页面灰度图。结果与 segs 同序、确定；调用方自己按
    (snapshot_sha, model_sha, SCORE_VERSION, 取整后的 seg) 缓存。"""
    from .sim_cnn import load_calib
    calib = load_calib(model_path)
    res: list[dict] = []
    for s in range(0, len(segs), batch):
        part = segs[s:s + batch]
        crops = [crop_segment(get_page(v, p), (x0, x1), y0, y1) for (v, p, c, y0, y1, x0, x1) in part]
        r = score_embeddings(snap, query_embeddings(crops, model_path), topk=topk, calib=calib)
        for rr, cr in zip(r, crops):
            rr.update(ink_info(cr))
        res.extend(r)
    return res
