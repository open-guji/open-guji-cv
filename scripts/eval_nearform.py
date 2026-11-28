"""3a 子基准 A6「形近字组」：人裁过的形近字对格上，库匹配首位是不是对家字（CV3，2026-11-23）。

分片：open-guji-dataset `glyph-match/nearform-qtw/`（`items.jsonl` 一行一个「字对×格」，`crops.npz` 自带归一图；
由 dataset `scripts/build_nearform_qtw.py` 从 OCR 研究 11-18 的形近字组基准冻结，标签是三轮人裁合并后的最终标签）。

量法：用生产的相似度嵌入（`--sim-model`，全唐文是 models/glyph_sim_qtw/model.pt）把字形库全部刻例与查询格嵌入，
余弦近邻。**同一物理格的库刻例去掉**（库号 v2:<格号> 与查询格号相同）。两种口径：
  全库首位：首位字＝金标算对；首位字＝本对对家字算「对家误认」（头条，护栏）。
  两字间：只在本对两字的刻例里比最像的一例，看判对没有（形近判别本身的上限）。
只报 label_src∈{人裁, 放行字} 的格；「文意」三对（千干、日曰、天夭）标签由文意定、刻形未必对得上，单列不进头条。
按册奇偶报 dev／test，逐对列表与 flips（"对家误认" 的格号）供 --against 比对。

    python scripts/eval_nearform.py <分片目录> --db <glyph.db> --sim-model models/glyph_sim_qtw/model.pt [--out r.json] [--against old.json]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402


def _load(shard: Path):
    items = [json.loads(x) for x in (shard / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    z = np.load(shard / "crops.npz")
    shape = tuple(int(s) for s in z["shape"])
    N = np.unpackbits(z["norm"], axis=-1)[..., :shape[-1]].reshape(shape)
    return items, {str(i): N[k] for k, i in enumerate(z["ids"])}


def _embed(net, patches, batch=1024):
    import torch
    out = []
    with torch.no_grad():
        for i in range(0, len(patches), batch):
            x = torch.from_numpy(np.stack(patches[i:i + batch]).astype(np.float32))[:, None]
            out.append(net.embed(x).numpy())
    return np.concatenate(out)


def _rate(n, d):
    return round(100.0 * n / d, 2) if d else None


def report(items, top1, pair_ok):
    """items 与 top1（全库首位字）、pair_ok（两字间判对）逐行对应。"""
    res, flips = {}, {}
    groups = {"全部": lambda it: it["label_src"] != "文意", "文意三对": lambda it: it["label_src"] == "文意"}
    for gname, keep in groups.items():
        for split in ("全部", "dev", "test"):
            sel = [k for k, it in enumerate(items) if keep(it) and (split == "全部" or it["split"] == split)]
            if not sel:
                continue
            n = len(sel)
            ok = sum(top1[k] == items[k]["gold"] for k in sel)
            other = [k for k in sel if top1[k] == (items[k]["b"] if items[k]["gold"] == items[k]["a"] else items[k]["a"])]
            pok = sum(bool(pair_ok[k]) for k in sel)
            res[f"{gname}|{split}"] = dict(n=n, top1=_rate(ok, n), pair_confuse=len(other),
                                         pair_confuse_rate=_rate(len(other), n), two_way=_rate(pok, n))
            if split == "全部":
                flips[f"{gname}|对家误认"] = sorted(f"{items[k]['pair']}|{items[k]['id']}" for k in other)
    per_pair = collections.defaultdict(lambda: [0, 0, 0, 0])
    for k, it in enumerate(items):
        p = per_pair[it["pair"]]
        p[0] += 1
        p[1] += top1[k] == it["gold"]
        p[2] += top1[k] == (it["b"] if it["gold"] == it["a"] else it["a"])
        p[3] += bool(pair_ok[k])
    pairs = {pk: dict(n=v[0], top1=_rate(v[1], v[0]), pair_confuse=v[2], two_way=_rate(v[3], v[0]))
             for pk, v in sorted(per_pair.items(), key=lambda kv: -kv[1][2])}
    return res, pairs, flips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shard")
    ap.add_argument("--db", default=os.environ.get("GUJI_GLYPH_DB"))
    ap.add_argument("--sim-model", required=True)
    ap.add_argument("--out")
    ap.add_argument("--against")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if not a.db:
        raise SystemExit("要 --db 或 GUJI_GLYPH_DB（全唐文字形库）")
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    from open_guji_cv.clustering.sim_cnn import load_net

    shard = Path(a.shard)
    items, P = _load(shard)
    if a.limit:
        items = items[:a.limit]
    m, _ = load_matcher_from_db(GlyphDB(a.db), knn_k=15)
    lib_ids, lib_chars = list(m._ids), list(m._chars)
    net = load_net(str(Path(a.sim_model).resolve()))
    t = time.perf_counter()
    E = _embed(net, list(m._patches))
    qids = sorted({it["id"] for it in items})
    Q = _embed(net, [P[i] for i in qids])
    print(f"嵌入：库 {len(E)}、查询 {len(Q)}，{time.perf_counter() - t:.0f}s", flush=True)
    qpos = {i: k for k, i in enumerate(qids)}
    lpos = {i: k for k, i in enumerate(lib_ids)}
    by_char = collections.defaultdict(list)
    for k, c in enumerate(lib_chars):
        by_char[c].append(k)
    chars = np.array(lib_chars)
    top1_of, self_hits = {}, 0
    for s in range(0, len(qids), 2048):
        S = Q[s:s + 2048] @ E.T
        for r, qi in enumerate(qids[s:s + 2048]):
            j = lpos.get("v2:" + qi)
            if j is not None:
                S[r, j] = -9
                self_hits += 1
            top1_of[qi] = str(chars[int(np.argmax(S[r]))])
    top1, pair_ok = [], []
    for it in items:
        q = Q[qpos[it["id"]]]
        top1.append(top1_of[it["id"]])
        best = {}
        for c in (it["a"], it["b"]):
            ks = [k for k in by_char.get(c, ()) if lib_ids[k] != "v2:" + it["id"]]
            best[c] = float(np.max(E[ks] @ q)) if ks else -9.0
        pick = it["a"] if best[it["a"]] >= best[it["b"]] else it["b"]
        pair_ok.append(None if min(best.values()) <= -9 else pick == it["gold"])
    res, pairs, flips = report(items, top1, pair_ok)
    h = res.get("全部|全部", {})
    out = dict(protocol="A6 形近字组·全唐文（CV3 2026-11-23）", db=os.path.basename(a.db), sim_model=a.sim_model,
               self_excluded=self_hits,
               headline=dict(n=h.get("n"), pair_confuse=h.get("pair_confuse"), pair_confuse_rate=h.get("pair_confuse_rate"),
                             top1=h.get("top1"), two_way=h.get("two_way")),
               result=res, pairs=pairs, flips=flips)
    for k, v in res.items():
        print(f"{k:<14} n={v['n']:<6} 首位对 {v['top1']}%  对家误认 {v['pair_confuse']}（{v['pair_confuse_rate']}%）  两字间 {v['two_way']}%")
    print("对家误认最多的对：", ", ".join(f"{pk} {v['pair_confuse']}/{v['n']}" for pk, v in list(pairs.items())[:10]))
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.against:
        old = json.loads(Path(a.against).read_text(encoding="utf-8")).get("flips", {})
        for k, v in flips.items():
            o = set(old.get(k, []))
            print(f"{k}: 新增 {len(set(v) - o)}，消失 {len(o - set(v))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
