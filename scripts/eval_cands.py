# -*- coding: utf-8 -*-
"""识字候选 benchmark（open-guji-dataset/char-candidates，CV3 2026-11-27）。

三个量法（规格：Claude Doc「候选字线：待审格格式、3c／4b 接口与 benchmark」第五节）：

- **3c 按图**：字块图 → 候选，量金标在前 k 的比例（严格码位，只折叠 己已巳、日曰）。
  - `frozen_lib`：产物包里 3a glyph_match 前 5（冻结）；
  - `frozen_rare`：产物包里 3b rare_candidates（冻结，现行产线）；
  - `r5_full`：r5 向量对全字表余弦（现场算，3c 第一版算法）。
- **4b 按上下文**：
  - 固定池：池＝冻结的产线候选（3a 前 5 ∪ 3b），只比重排：原序、冻结的 context_decide、SikuRoBERTa 融合；
  - 串联：池＝r5_full 前 200，再融合；
  - 伤害率：对照组（金标＝池原首位）里重排把首位挤掉的比例。
- **卡片**（只乙层）：发卡时的按钮（近似：参校字＋库前 3，去重取 3）对比新排序前 3／参校字＋新排序前 2。

金标 `expected.status != "char"` 的格（切坏、非字、插图…）不进字的命中率，单报个数。

用法：
    PYTHONPATH=. python scripts/eval_cands.py <dataset>/char-candidates [--out report.json] [--against 旧report.json]
        [--part 3c,4b,card] [--no-mlm] [--limit N] [--w 0.005]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FOLD = {"己": "己", "已": "己", "巳": "己", "曰": "日"}
FLOOR = -12.0
NOISE_POOL = "之不也其而有以於為者曰人大天子日以所故無是何下上中公王"
LM_NAME, LM_REV = "SIKU-BERT/sikuroberta", "bb25260d5c321924fe4fb353c09191c0aaf5c5c6"


def eq(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and (a == b or FOLD.get(a, a) == FOLD.get(b, b))


def rank(lst, g) -> int | None:
    for i, c in enumerate(lst):
        if eq(c, g):
            return i + 1
    return None


# ───────────────────────── 图像 ─────────────────────────

class Image:
    def __init__(self, root: Path):
        from open_guji_cv.clustering.cnn_candidates import shared
        from open_guji_cv.clustering.emb_pack import load_current
        from open_guji_cv.clustering.normalize import normalize_patch
        self.root, self.norm = root, normalize_patch
        self.cnn = shared()
        if not self.cnn.available:
            raise SystemExit("r5 模型不可用（要装 torch 并取得权重）")
        self.pack = load_current(download=True)
        m = self.pack.mat.astype(np.float32)
        self.M = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        self.chars = self.pack.chars
        from open_guji_cv.hanzi.db import shared as hz
        _hz, _fc = hz(), {}

        def family(c):
            if c not in _fc:
                try:
                    _fc[c] = list(_hz.family(c).keys())
                except Exception:  # noqa: BLE001
                    _fc[c] = []
            return _fc[c]
        self.family = family

    def patch(self, r: dict) -> np.ndarray | None:
        p = self.root / r["crop"]["path"]
        g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if g is None:
            return None
        if r["crop"]["kind"] == "norm64":          # 已是 normalize_patch×255
            return (g > 127).astype(np.uint8)
        return self.norm(g)                        # 卡上单格图：照产线归一

    def sims(self, rows: list[dict], bs: int = 256) -> dict[str, np.ndarray]:
        out = {}
        for i in range(0, len(rows), bs):
            chunk = [(r["id"], self.patch(r)) for r in rows[i:i + bs]]
            chunk = [(k, p) for k, p in chunk if p is not None]
            if not chunk:
                continue
            e = self.cnn.embed([p for _, p in chunk])
            s = e @ self.M.T
            for (k, _), v in zip(chunk, s):
                out[k] = v
        return out


# ───────────────────────── 上下文 ─────────────────────────

class LM:
    def __init__(self):
        import torch
        from transformers import AutoModelForMaskedLM, AutoTokenizer
        from open_guji_cv.hanzi.db import shared as hz
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(LM_NAME, revision=LM_REV)
        self.model = AutoModelForMaskedLM.from_pretrained(LM_NAME, revision=LM_REV).eval()
        self.vocab = self.tok.get_vocab()
        vch = [(c, i) for c, i in self.vocab.items() if len(c) == 1 and ord(c) > 0x2E80]
        self.vchars = [c for c, _ in vch]
        self.vids = torch.tensor([i for _, i in vch])
        self.hz = hz()
        self._fam: dict[str, set] = {}

    def fam(self, c: str) -> set:
        if c not in self._fam:
            try:
                self._fam[c] = {c} | set(self.hz.family(c).keys())
            except Exception:  # noqa: BLE001
                self._fam[c] = {c}
        return self._fam[c]

    def logits(self, left: str, right: str):
        enc = self.tok(left + self.tok.mask_token + right, return_tensors="pt", truncation=True, max_length=128)
        mp = (enc.input_ids[0] == self.tok.mask_token_id).nonzero()
        if not len(mp):
            return None
        with self.torch.no_grad():
            return self.model(**enc).logits[0, mp[0, 0]].log_softmax(-1)

    def sem(self, lg, chars) -> dict[str, float]:
        """语义层：字或其异体族里在词表中的字，取最大 logp。"""
        out = {}
        for c in chars:
            vs = [float(lg[self.vocab[x]]) for x in self.fam(c) if x in self.vocab]
            if vs:
                out[c] = max(vs)
        return out

    def top(self, lg, n: int = 20) -> list[tuple[str, float]]:
        lv = lg[self.vids]
        idx = self.torch.argsort(lv, descending=True)[:n].tolist()
        return [(self.vchars[j], float(lv[j])) for j in idx]


def fuse(pool: list[tuple[str, float]], sem: dict[str, float], w: float) -> list[str]:
    """融合口径与产线 4b `context_rank` 同一份实现（`clustering.ctx_fill.fuse`）。"""
    from open_guji_cv.clustering.ctx_fill import fuse as _fuse
    return [c for c, _, _ in _fuse(pool, sem, w)]


# ───────────────────────── 主程序 ─────────────────────────

def pct(ranks, k, n) -> float:
    return round(100.0 * sum(1 for r in ranks if r is not None and r <= k) / n, 1) if n else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shard", type=Path, help="<dataset>/char-candidates")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--against", type=Path)
    ap.add_argument("--part", default="3c,4b,card")
    ap.add_argument("--no-mlm", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--w", type=float, default=0.005)
    ap.add_argument("--ctx-noise", type=float, default=0.0,
                    help="给前后文的字按这个概率随机换成别的常用字（模拟产线里邻格是机器猜的）；缺省 0＝测试集冻结的前后文")
    ap.add_argument("--extra-min-sim", type=float, default=0.70)
    a = ap.parse_args()
    t0 = time.time()
    root = a.shard.parent
    rows = [json.loads(x) for x in open(a.shard / "items.jsonl", encoding="utf-8")]
    if a.limit:
        rows = rows[:a.limit]
    parts = set(a.part.split(","))
    nonchar = collections.Counter((r["layer"], r["expected"]["status"]) for r in rows if r["expected"]["status"] != "char")
    rows = [r for r in rows if r["expected"]["status"] == "char" and r["expected"].get("char")
            and not r["stratum"].get("selfcheck_flag")]
    img = Image(root)
    S = img.sims(rows)
    lm = None if a.no_mlm or not ({"4b", "card"} & parts) else LM()

    per: list[dict] = []
    for i, r in enumerate(rows):
        g = r["expected"]["char"]
        s = S.get(r["id"])
        if s is None:
            continue
        pool_in = r["input"].get("pool") or {}
        # ⚠ 产物包里的 3a 是人裁入库之后现跑的，金标已在库里（泄漏）。乙层改用发卡时冻结的 lib_top；甲层不用 3a。
        if r["layer"] == "B":
            pool_in = dict(pool_in, lib=[[y["c"], y["s"]] for y in (r["input"].get("card") or {}).get("lib_top") or []])
        else:
            pool_in = dict(pool_in, lib=[])
        lib = [c for c, _ in pool_in.get("lib") or []]
        rare = [c[0] for c in pool_in.get("rare") or []]
        order = np.argsort(-s)[:200]
        full = [(img.chars[j], float(s[j])) for j in order]
        from open_guji_cv.steps.glyph_candidate import GlyphCandidateParams, rank_cell
        gp = GlyphCandidateParams()
        cand50, _fo = rank_cell(s, img.chars, img.pack.index, img.family, gp.topk, gp.fam_top, gp.fam_after)
        x = {"r_cand": rank([c for c, _ in cand50], g), "id": r["id"], "layer": r["layer"], "book": r["book_title"], "st": r["stratum"],
             "r_lib": rank(lib, g), "r_rare": rank(rare, g), "r_full": rank([c for c, _ in full], g)}
        # 固定池：产线 3a 前 5 ∪ 3b（原序：3a 在前），图像分现场算
        fixed = list(dict.fromkeys(lib + rare))
        libs = {c: float(v) for c, v in pool_in.get("lib") or []}
        def sim(c, s=s, libs=libs):
            """图像分＝max(3a 库匹配分, r5 字体模板余弦)（规格第四节）。"""
            j = img.pack.index.get(c)
            return max(libs.get(c, -1.0), float(s[j]) if j is not None else -1.0)
        x["fixed_n"] = len(fixed)
        x["r_fixed"] = rank(fixed, g)
        x["r_ctxd"] = rank([c for c, _ in (pool_in.get("ctx_ranked") or [])], g)
        ctx = r["input"].get("ctx")
        if ctx and a.ctx_noise > 0:
            import random
            rnd = random.Random(r["id"])
            noisy = lambda t: "".join(rnd.choice(NOISE_POOL) if rnd.random() < a.ctx_noise else ch for ch in t)  # noqa: E731
            ctx = {"left": noisy(ctx["left"]), "right": noisy(ctx["right"])}
        card = (r["input"].get("card") or {})
        refc = ((r["input"].get("ref") or {}).get("c")) or (card.get("ref") or {}).get("c")
        if lm is not None and ctx:
            lg = lm.logits(ctx["left"], ctx["right"])
            if lg is not None:
                cand = {c for c, _ in full} | set(fixed)
                sem = lm.sem(lg, cand)
                if fixed:
                    x["r_fixed_mlm"] = rank(fuse([(c, sim(c)) for c in fixed], sem, a.w), g)
                chain = list(dict.fromkeys(lib + [c for c, _ in full]))
                fz = fuse([(c, sim(c)) for c in chain], sem, a.w)
                x["r_chain_img"] = rank(sorted(chain, key=lambda c: -sim(c)), g)
                x["r_chain"] = rank(fz, g)
                # 补字：填空前 20 里不在图像前 50 的，映到族里图像最像的码位
                have = {c for c, _ in full[:50]}
                extra = []
                for c, lp in lm.top(lg, 20):
                    if c in have:
                        continue
                    best = max(((m, sim(m)) for m in lm.fam(c)), key=lambda t: t[1])
                    if best[1] >= a.extra_min_sim and best[0] not in have and best[0] not in extra:
                        extra.append(best[0])
                    if len(extra) >= 5:
                        break
                x["extra_n"] = len(extra)
                x["extra_hit"] = any(eq(c, g) for c in extra)
                if r["layer"] == "B":
                    new3 = fz[:3]
                    ref2 = ([refc] if refc and len(refc) == 1 else []) + [c for c in fz if c != refc]
                    x["card_new3"] = any(eq(c, g) for c in new3)
                    x["card_ref_new2"] = any(eq(c, g) for c in ref2[:3])
        if r["layer"] == "B":
            x["card_old3"] = any(eq(c, g) for c in card.get("shown_approx") or [])
            x["card_old_lib5"] = any(eq(c, g) for c in [y["c"] for y in card.get("lib_top") or []])
            x["card_old_alt"] = any(eq(y.get("c"), g) for y in card.get("alt") or [])
            x["gold_eq_ref"] = r["stratum"].get("gold_eq_ref")
        per.append(x)
        if i % 1000 == 0:
            print(f"  {i}/{len(rows)} {time.time() - t0:.0f}s", flush=True)

    rep: dict = {"n_rows": len(rows), "nonchar": {f"{k[0]}:{k[1]}": v for k, v in nonchar.items()},
                 "w": a.w, "lm": None if lm is None else f"{LM_NAME}@{LM_REV[:8]}",
                 "emb": getattr(img.pack, "version", None) or getattr(img.pack, "spec", None) and str(img.pack.spec),
                 "groups": {}}

    def summarize(name, xs):
        n = len(xs)
        if not n:
            return
        d: dict = {"n": n}
        if "3c" in parts:
            d["3c"] = {"3a前5": [pct([x["r_lib"] for x in xs], k, n) for k in (1, 5)],
                       "3b产线": [pct([x["r_rare"] for x in xs], k, n) for k in (1, 10)],
                       "r5全字表": [pct([x["r_full"] for x in xs], k, n) for k in (1, 10, 30, 50)],
                       "glyph_candidate(产线3c)": [pct([x["r_cand"] for x in xs], k, n) for k in (1, 10, 30, 50)]}
        if "4b" in parts:
            fx = [x for x in xs if x["fixed_n"]]
            hasctx = [x for x in fx if "r_fixed_mlm" in x]
            d["4b"] = {"固定池n": len(fx), "固定池金标在池": pct([x["r_fixed"] for x in fx], 999, len(fx)),
                       "原序": [pct([x["r_fixed"] for x in hasctx], k, len(hasctx)) for k in (1, 3)],
                       "context_decide": [pct([x["r_ctxd"] for x in hasctx], k, len(hasctx)) for k in (1, 3)],
                       "填空融合": [pct([x.get("r_fixed_mlm") for x in hasctx], k, len(hasctx)) for k in (1, 3)],
                       "有前后文n": len(hasctx)}
            ch = [x for x in xs if "r_chain" in x]
            if ch:
                d["4b"]["串联r5+融合"] = [pct([x["r_chain"] for x in ch], k, len(ch)) for k in (1, 3, 10)]
                d["4b"]["串联同格只看图"] = [pct([x["r_chain_img"] for x in ch], k, len(ch)) for k in (1, 3, 10)]
                miss = [x for x in ch if not (x["r_full"] and x["r_full"] <= 50)]
                d["4b"]["补字"] = {"图像前50没中": len(miss), "补字命中": sum(1 for x in miss if x.get("extra_hit")),
                                  "平均补几个": round(sum(x.get("extra_n", 0) for x in ch) / len(ch), 2)}
                ctl = [x for x in ch if x["r_chain_img"] == 1]
                d["4b"]["伤害率(图像首位已对)"] = round(100.0 * sum(1 for x in ctl if x["r_chain"] != 1) / len(ctl), 2) if ctl else None
                ctl2 = [x for x in hasctx if x["r_fixed"] == 1]
                d["4b"]["伤害率(固定池原首位已对)"] = round(100.0 * sum(1 for x in ctl2 if x.get("r_fixed_mlm") != 1) / len(ctl2), 2) if ctl2 else None
        if "card" in parts:
            cb = [x for x in xs if "card_old3" in x]
            if cb:
                def cp(key, ys):
                    return round(100.0 * sum(1 for y in ys if y.get(key)) / len(ys), 1) if ys else None
                hard = [y for y in cb if not y.get("gold_eq_ref")]
                hard2 = [y for y in cb if y["st"].get("rel") in ("lib2-5", "alt", "none")]
                withnew = [y for y in cb if "card_new3" in y]
                d["card"] = {"n": len(cb), "旧按钮3": cp("card_old3", cb), "旧库前5": cp("card_old_lib5", cb),
                             "旧相似字": cp("card_old_alt", cb),
                             "金标≠参校字n": len(hard), "金标≠参校字·旧按钮3": cp("card_old3", hard),
                             "有前后文n": len(withnew),
                             "同格·旧按钮3": cp("card_old3", withnew), "新前3": cp("card_new3", withnew),
                             "参校字+新前2": cp("card_ref_new2", withnew),
                             "金标≠参校字·同格旧/新前3/参校+新2": [cp(k, [y for y in withnew if not y.get("gold_eq_ref")])
                                                         for k in ("card_old3", "card_new3", "card_ref_new2")],
                             "难n": len(hard2),
                             "难·旧/新前3/参校+新2": [cp(k, [y for y in hard2 if k in y or k == "card_old3"])
                                               for k in ("card_old3", "card_new3", "card_ref_new2")]}
        rep["groups"][name] = d

    for lay in ("A", "B"):
        for bk in ("史記", "全唐文", "殿本"):
            summarize(f"{lay}·{bk}", [x for x in per if x["layer"] == lay and x["book"] == bk])
        summarize(f"{lay}·全部", [x for x in per if x["layer"] == lay])
    summarize("A·oov", [x for x in per if x["layer"] == "A" and "oov" in (x["st"].get("tags") or [])])
    summarize("A·扩B以后", [x for x in per if x["st"].get("block") == "extB+"])
    summarize("B·难(库首选与参校字都不对)", [x for x in per if x["layer"] == "B" and x["st"].get("rel") in ("lib2-5", "alt", "none")])
    rep["secs"] = round(time.time() - t0)
    txt = json.dumps(rep, ensure_ascii=False, indent=1)
    print(txt)
    if a.out:
        a.out.write_text(txt, encoding="utf-8")
    if a.against and a.against.exists():
        old = json.loads(a.against.read_text(encoding="utf-8"))
        print("\n与旧报告比（新 − 旧）：")
        for g, d in rep["groups"].items():
            o = old.get("groups", {}).get(g)
            if not o:
                continue
            for part in ("3c", "4b"):
                for k, v in (d.get(part) or {}).items():
                    ov = (o.get(part) or {}).get(k)
                    if isinstance(v, list) and isinstance(ov, list) and len(v) == len(ov):
                        dv = [round(p - q, 1) for p, q in zip(v, ov)]
                        if any(dv):
                            print(f"  {g} {part} {k}: {dv}")


if __name__ == "__main__":
    main()
