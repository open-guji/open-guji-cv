"""字组离线回放（2026-10-24，A24「强化于千子干等形近判别」）：拿现有产物（`guji products pack fetch` 的布局）只对点名的组重跑字组流程，
不重跑管线。用法：

  python replay_groups.py <产物根> <册,册…> <输出 jsonl> --groups zy,yz,guan --redo zy,qg [--tables <目录>] [--patches]

- `--redo`：产物里由这些组判过的格先退回进组前的状态（补放的退回待审、降审的退回原通道放行），再由新组重判。
  并组、改组时用（千干 qg 并进 zy：产物里 qg／zy 的结论都作废）。
- `--tables`：L3 答案表目录，`<组>.json`；没给的组只有 L1。
- `--models`：L2 模型小头目录，`<组>.json`（`ctx_model/1`，`l2model_train.py` 出）。L3 在线不回放（要密钥、花钱）。
- `--patches`：方法要字块时现算（`RunContext.image`，要工作区与原图，同 `research/m7/bench/materialize_patches.py`）；
  不给则字块一律缺（看图的方法弃权）。
- `--codepoints <工作区 config/codepoints.yaml>`：书级码位归一（码位法组 `codepoint` 要它，同线上 `canon`）。
- `--raw <原图根>`：不要工作区，字块按 `cell_shrink` 的 `bbox_page` 从 `<原图根>/<册>/<页>.png` 裁（同 build_shape_pair.py 建库的取法）。
- `--codepoints 䝉=𫎇,𨽾=隷`：书级码位（同工作区 `config/codepoints.yaml`，也可给 yaml 路径），整理本字与组员按它归一（同线上 `canon`）。
输出每个进了流程的格一行：前后的放行状态、结论、各方法留痕、窗口。
"""
import argparse, json, sys
from pathlib import Path
from types import SimpleNamespace

from open_guji_cv.groups.context import WIDTH
from open_guji_cv.groups.flow import FlowConfig, group_flow_pass
from open_guji_cv.groups.registry import FLOW_GROUPS, flow_names
from open_guji_cv.steps.seed_admit import (_GROUP_FLOW_HARD, _GROUP_FLOW_OWN_DOUBTS, _GROUP_FLOW_OWN_GUARDS, _clf_ctx,
                                           _hard_blocked)
from open_guji_cv.utils.jiazhu_order import sort_by_reading

ap = argparse.ArgumentParser()
ap.add_argument("root"); ap.add_argument("vols"); ap.add_argument("out")
ap.add_argument("--groups", required=True); ap.add_argument("--redo", default="")
ap.add_argument("--tables", default=None); ap.add_argument("--patches", action="store_true")
ap.add_argument("--raw", default=None); ap.add_argument("--models", default=None)
ap.add_argument("--codepoints", default="", help="工作区 config/codepoints.yaml，或 `䝉=𫎇,𨽾=隷`：码位法组与补放互证按它归一（不给则码位法组只会弃权）")
a = ap.parse_args()
if a.codepoints.endswith((".yaml", ".yml")):
    import yaml
    CP = {str(k): str(v) for k, v in ((yaml.safe_load(open(a.codepoints, encoding="utf-8")) or {}).get("codepoints") or {}).items()}
else:
    CP = dict(kv.split("=", 1) for kv in a.codepoints.split(",") if kv)


def canon(c):
    return CP.get(c, c)

root = Path(a.root)
groups = flow_names(a.groups.split(","))
redo = set(a.redo.split(",")) - {""}
tables = {}
if a.tables:
    for g in groups:
        t = Path(a.tables) / f"{g}.json"
        if t.exists():
            tables[g] = str(t)
models = {g: str(Path(a.models) / f"{g}.json") for g in groups if a.models and (Path(a.models) / f"{g}.json").exists()}
canon = canon if CP else None
cfg = FlowConfig(groups=groups, l2_tables=tables, l2_models=models, l2_drift=2, joint=True, canon=canon)
FIELDS = ("id", "char", "admit", "channel", "provenance", "doubts", "evidence", "slot", "sub")


def undo(c: dict) -> None:
    """产物里 `redo` 组判过的格退回进组前（补放 → 待审；降审 → 原通道放行；改字 → 原字）。"""
    ev = c.get("evidence") or {}
    grp = ev.get("group") or {}
    if grp.get("id") not in redo:
        return
    dec = grp.get("decision")
    if dec == "admit":
        c.update(admit=False, channel=None, provenance="")
    elif dec == "demote":
        c.update(admit=True, channel=(ev.get("demoted_from") or {}).get("channel"))
    elif dec == "fix":
        c.update(char=(ev.get("fixed_from") or {}).get("char"), channel=(ev.get("fixed_from") or {}).get("channel"))
    c["doubts"] = [d for d in (c.get("doubts") or []) if not str(d).startswith("group_flow_")]
    c["evidence"] = {k: v for k, v in ev.items() if k not in ("group", "demoted_from", "fixed_from")}


def ctx_for(book: str):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    return RunContext(load_book(book), ProductStore(root), ImageCache(), log=lambda s: None)


out = open(a.out, "w", encoding="utf-8")
for v in a.vols.split(","):
    rc = ctx_for(v) if a.patches else None
    for f in sorted((root / v / "seed_admit").glob("p*.json")):
        d = json.load(open(f, encoding="utf-8"))["seed_admit"]
        page = int(d["page"])
        ar = json.load(open(root / v / "align_ref" / f.name, encoding="utf-8"))["align_ref"]
        amap = {c["id"]: (c["align_char"], c.get("align_op")) for c in ar["chars"]}
        coord = {c["id"]: c["ref_char"] for c in ar.get("coord") or []}
        gm = {c["id"]: c for col in json.load(open(root / v / "glyph_match" / f.name, encoding="utf-8"))["glyph_match"]["columns"]
              for c in col["chars"]}
        cols = []
        for col in sorted(d["columns"], key=lambda c: c["col"]):
            recs = []
            for c in col["chars"]:
                undo(c)
                recs.append(SimpleNamespace(**{k: c.get(k) for k in FIELDS}, col=col["col"]))
            cols.append(recs)
        seq = [r for recs in cols for r in sort_by_reading(recs) if not (r.doubts and "excluded" in r.doubts)]
        before = {r.id: (r.admit, r.char, r.channel) for r in seq}
        mem = set().union(*(FLOW_GROUPS[g].members for g in groups))
        win = {r.id: (_clf_ctx(seq, amap, i, -1, WIDTH), _clf_ctx(seq, amap, i, 1, WIDTH)) for i, r in enumerate(seq)
               if r.char in mem or any(c in mem for c, _ in ((gm.get(r.id) or {}).get("candidates") or [])[:4])}

        def blocked(r):
            guard = (gm.get(r.id) or {}).get("guard")
            if guard in _GROUP_FLOW_OWN_GUARDS:
                guard = None
            ds = [x for x in (r.doubts or []) if isinstance(x, str) and x not in _GROUP_FLOW_OWN_DOUBTS]
            return _hard_blocked(ds, guard) or any(x in _GROUP_FLOW_HARD for x in ds)

        patch_fn = None
        if rc is not None:
            from open_guji_cv.core.spec import cell_key
            slots = {r.id: (r.col, r.slot, r.sub) for r in seq}

            def patch_fn(cid):
                col, slot, sub = slots[cid]
                try:
                    return rc.image("char_patch", cell_key(page, col, slot) + (sub or ""))
                except Exception:          # noqa: BLE001 —— 回放：缺图就当缺（方法弃权），不停
                    return None
        if a.raw:
            import cv2
            from open_guji_cv.core.anchor import crop_patch
            img = cv2.imread(str(Path(a.raw) / v / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
            sh = root / v / "cell_shrink" / f.name
            box = ({c["id"]: c["bbox_page"] for col in json.load(open(sh, encoding="utf-8"))["char_index"]["columns"]
                    for c in col["chars"]} if sh.exists() else {})

            def patch_fn(cid, img=img, box=box):
                return crop_patch(img, tuple(box[cid])) if img is not None and cid in box else None
        group_flow_pass(seq, amap, lambda cid: list((gm.get(cid) or {}).get("candidates") or []), blocked, cfg,
                        ctx_fn=lambda s, i, step: _clf_ctx(s, amap, i, step, WIDTH), patch_fn=patch_fn,
                        veto_refs=coord, **({"canon": canon} if canon else {}))
        for i, r in enumerate(seq):
            grp = (r.evidence or {}).get("group")
            if not grp or grp.get("id") not in groups:
                continue
            out.write(json.dumps(dict(id=r.id, group=grp["id"], mode=grp["mode"], decision=grp["decision"], pick=grp["pick"],
                                      why=grp["why"], solvers=grp["solvers"], before=before[r.id], after=(r.admit, r.char, r.channel),
                                      ref=(amap.get(r.id) or (None,))[0], cands=(gm.get(r.id) or {}).get("candidates", [])[:4],
                                      left=win.get(r.id, (None, None))[0], right=win.get(r.id, (None, None))[1]),
                                 ensure_ascii=False) + "\n")
    print(v, "done", file=sys.stderr, flush=True)
