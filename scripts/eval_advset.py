"""3a 子基准 A2「库外拒识」：库外形近字对抗集上，匹配层把库里没有的字判成 same 的比例（A23，2026-11-23）。

分片：open-guji-dataset `glyph-match/advset-<书>/`（`items.jsonl` + 自带归一图 `crops/`，
由 dataset `scripts/build_glyph_advset.py` 从 ai-team 11-15 的对抗集冻结而来，打分不碰字形库）。
每题＝一张「留出字」刻例（这个字库里没有）＋一组候选（形近对家 3 例×至多 8 家＋生产粗排 HOG 前 15）。
用**生产的逐对判官**判每个候选（`verify_pair_elastic`；给了 `--sim-model` 再加 CnnVerifier 一路／fuse 一路），
有任何候选判 same 就算这题误认——生产里这格会被认成那个形近字。

分两层报（Sheldon 11-15：同形异码／异体不算同一个字、逐码位判）：
  形近层：候选去掉异体刻例；头条「形近误认率」。
  异体层：只看异体候选（只有带这类候选的题参与）；预期判不开，看的是匹配层有没有对它们下 same。

    python scripts/eval_advset.py <分片目录> [--sim-model models/glyph_sim_qtw/model.pt] [--out r.json] [--against old.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

_P: dict[str, np.ndarray] = {}


def _load(shard: Path):
    from open_guji_cv.clustering.glyph_db import _unpng
    items = [json.loads(x) for x in (shard / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    ids = sorted({it["query_id"] for it in items} | {c["id"] for it in items for c in it["candidates"]})
    P = {i: _unpng((shard / "crops" / (i.replace(":", "_") + ".png")).read_bytes()) for i in ids}
    return items, P


def _cov_job(it):
    from open_guji_cv.clustering.verify import verify_pair_elastic
    a = _P[it["query_id"]]
    out = []
    for c in it["candidates"]:
        v = verify_pair_elastic(a, _P[c["id"]])
        out.append((v.verdict == "same", float(v.f1)))
    return out


def _init(P):
    global _P
    _P = P


def _score(items, P, sim_model: str | None, workers: int):
    ways = {}
    with Pool(workers, initializer=_init, initargs=(P,)) as pool:
        ways["cov"] = pool.map(_cov_job, items, chunksize=8)
    if sim_model:
        from open_guji_cv.clustering.sim_cnn import CnnVerifier, SimModelConfig
        for name, fuse in (("cnn", ""), ("cnn+fuse", "mean")):
            ids = sorted(P)
            pats = [P[i] for i in ids]
            try:
                ver = CnnVerifier(SimModelConfig(path=sim_model, fuse=fuse), pats)
            except ValueError as e:      # 没有校准表就没有 fuse 一路
                print(f"跳过 {name}：{e}")
                continue
            if fuse:
                cov_s = ways["cov"]
                res = []
                for it, cs in zip(items, cov_s):
                    a = P[it["query_id"]]
                    r = []
                    for c, (_, cvs) in zip(it["candidates"], cs):
                        s = ver.score(a, P[c["id"]])
                        r.append(((s + cvs) / 2 >= ver.same, (s + cvs) / 2))
                    res.append(r)
                # fuse 另要 wmax ≤ 12：和 cov 路同一判官，cov 判 same 前提里已含；这里补上
                ways[name] = _fuse_wmax(items, P, res)
            else:
                ways[name] = [[(ver.score(P[it["query_id"]], P[c["id"]]) >= ver.same,
                                ver.score(P[it["query_id"]], P[c["id"]])) for c in it["candidates"]] for it in items]
    return ways


def _fuse_wmax(items, P, res):
    """fuse 判 same 的对再查一次 wmax（生产 CnnVerifier fuse 分支的第二条件）。只算 fuse 过线的对，量很少。"""
    from open_guji_cv.clustering.verify import MISS_WMAX, verify_pair_elastic
    out = []
    for it, r in zip(items, res):
        a = P[it["query_id"]]
        o = []
        for c, (same, s) in zip(it["candidates"], r):
            if same:
                same = verify_pair_elastic(a, P[c["id"]]).diff_blob_ratio <= MISS_WMAX
            o.append((same, s))
        out.append(o)
    return out


def _report(items, ways):
    res, flips = {}, {}
    held = np.array([it["held"] for it in items])
    for name, sc in ways.items():
        r = {}
        for layer in ("形近", "异体"):
            hits, part_hits, n, bad = 0, 0, 0, []
            for it, s in zip(items, sc):
                keep = [(c, x) for c, x in zip(it["candidates"], s) if c["variant"] == (layer == "异体")]
                if not keep:
                    continue
                n += 1
                same = [(c, x) for c, x in keep if x[0]]
                if same:
                    hits += 1
                    c, x = max(same, key=lambda t: t[1][1])
                    bad.append(f'{it["query_id"]}|{it["held"]}→{c["char"]}|{c["id"]}')
                if any(x[0] for c, x in keep if c["partner"]):
                    part_hits += 1
            r[layer] = dict(n_query=n, n_held=len({it["held"] for it, s in zip(items, sc)}),
                            false_same=hits, false_same_rate=hits / n if n else None,
                            partner_false_same=part_hits)
            flips[f"{name}|{layer}"] = sorted(bad)
        res[name] = r
    return res, flips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shard")
    ap.add_argument("--sim-model", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None)
    ap.add_argument("--against", default=None, help="上一版 --out，列出误认题的新增／消失")
    a = ap.parse_args()
    shard = Path(a.shard)
    info = json.loads((shard / "info.json").read_text(encoding="utf-8"))
    items, P = _load(shard)
    ways = _score(items, P, a.sim_model, a.workers)
    res, flips = _report(items, ways)
    print(f"== advset {info['book']}：{len(items)} 题／{info['n_held']} 个留出字（库外字） ==")
    for name, r in res.items():
        x, v = r["形近"], r["异体"]
        print(f"  {name:9s} 形近误认 {x['false_same']}/{x['n_query']}（{100 * (x['false_same_rate'] or 0):.2f}%，"
              f"其中对家 {x['partner_false_same']}）  异体下 same {v['false_same']}/{v['n_query']}")
    head = res["cnn+fuse"] if "cnn+fuse" in res else res["cov"]
    out = dict(shard=str(shard), book=info["book"], n=len(items), crops_from=info.get("crops_from"),
               sim_model=a.sim_model, result=res, flips=flips,
               headline=dict(way="cnn+fuse" if "cnn+fuse" in res else "cov",
                             near_false_same=head["形近"]["false_same"],
                             near_false_same_rate=head["形近"]["false_same_rate"],
                             variant_false_same=head["异体"]["false_same"]))
    if a.against:
        old = json.loads(Path(a.against).read_text(encoding="utf-8")).get("flips", {})
        for k, v in flips.items():
            o = set(old.get(k, []))
            add, gone = sorted(set(v) - o), sorted(o - set(v))
            if add or gone:
                print(f"  翻转 {k}：新增 {len(add)} 消失 {len(gone)}")
                for x in add[:20]:
                    print(f"    + {x}")
                for x in gone[:20]:
                    print(f"    - {x}")
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
