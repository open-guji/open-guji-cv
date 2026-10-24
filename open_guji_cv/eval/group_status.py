"""字组状态报告（2026-10-24，sheldon「形近字处理规范化」）：一轮产物 × 人工数据 → 每组做得怎么样。

    guji groups status --prod <产物根>[,<产物根>…] --labels <dataset>/char-groups/labels/unified.jsonl \\
        [--codepoints <工作区>/config/codepoints.yaml] --out <dataset>/char-groups/status [--tag main-v0.5.10]

产物根下是 `<册>/seed_admit/p*.json`（`guji products pack fetch` 的布局，或工作区的 `products/`）。只读，不跑管线。
写 `<日期>-<tag>.json`（每组 × 每册全量）与同名 `.md`（总表）。口径（规范见 `doc/字组/README.md` 第四节）：

- **出现格**：放行字在组里的格，加上进过组流程（`evidence.group.id`＝本组）的格。一个字可属多组（日：ry、rm），各组各算。
- **组判**：进过组流程的格；**给字**：组流程给出了字（`group.pick`）。组判率＝给字 ÷ 组判。
- **放行／送审**：出现格里最终放行、送审的格数。
- **人裁核对**：已放行、非人裁通道、且 `unified.jsonl` 里有刻形（`shape`，没有就用文意 `reading`）的格；
  **不一致**＝放行字与人裁字不同（给了 `--codepoints` 时两边先按它归一，码位差不算）。不一致不等于错：
  人裁可能晚于产物，要逐格看；明细在 json 的 `mismatch`。
- **人工数据**：`unified.jsonl` 里 `form` 属于本组的行，按 `kind`（shape 刻形／reading 文意／cut 切线／parts 部件）计；
  另计有中心库来源（`in_central`，流水线读得到）的条数；**数据准不准**：多来源（`verified.n>1`）条数、其中被更正过
  （`corrected_from`，来源之间结论不同）的条数。
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

from ..groups import registry as R

KIND = {"variant": "同义", "near_form": "不同义"}


def _members() -> dict[str, list[str]]:
    of: dict[str, list[str]] = defaultdict(list)
    for gid, g in R.FLOW_GROUPS.items():
        for ch in g.members:
            of[ch].append(gid)
    return of


def load_labels(path: Path | None) -> tuple[dict, dict]:
    """→ (格 id → {kind: 字}, 组 → Counter)。"""
    by_id: dict[str, dict] = defaultdict(dict)
    per: dict[str, Counter] = defaultdict(Counter)
    if path is None or not Path(path).exists():
        return by_id, per
    of = _members()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        f = r.get("form")
        for gid in of.get(f or "", []):
            per[gid][r["kind"]] += 1
            if r.get("in_central", str(r.get("src", "")).startswith("central:")):
                per[gid]["central"] += 1
            v = r.get("verified") or {}
            if v.get("n", 1) > 1:
                per[gid]["multi"] += 1
            if r.get("corrected_from"):
                per[gid]["corrected"] += 1
        if f and r["kind"] in ("shape", "reading"):
            by_id[r["id"]][r["kind"]] = f
    return by_id, per


def load_codepoints(path: Path | None) -> dict[str, str]:
    if path is None or not Path(path).exists():
        return {}
    import yaml
    d = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (d.get("codepoints") or {}).items()}


def collect(prods: list[Path], labels: Path | None = None, codepoints: Path | None = None) -> dict:
    of = _members()
    lab, lab_per = load_labels(labels)
    cp = load_codepoints(codepoints)
    canon = lambda c: cp.get(c, c)  # noqa: E731
    st: dict = defaultdict(lambda: defaultdict(Counter))
    mismatch: dict = defaultdict(list)
    books = set()
    for root in prods:
        for f in sorted(glob.glob(str(Path(root) / "*" / "seed_admit" / "p*.json"))):
            book = Path(f).parts[-3]
            books.add(book)
            for col in json.loads(Path(f).read_text(encoding="utf-8"))["seed_admit"]["columns"]:
                for r in col["chars"]:
                    gr = (r.get("evidence") or {}).get("group") or {}
                    gs = set(of.get(r.get("char") or "", []))
                    if gr.get("id") in R.FLOW_GROUPS:
                        gs.add(gr["id"])
                    for gid in gs:
                        c = st[gid][book]
                        c["occ"] += 1
                        c["admit" if r.get("admit") else "review"] += 1
                        if gr.get("id") == gid:
                            c["flow"] += 1
                            c["pick"] += bool(gr.get("pick"))
                            c[f"decision:{gr.get('decision')}"] += 1
                        h = lab.get(r["id"])
                        if h and r.get("admit") and r.get("channel") != "human":
                            hc = h.get("shape") or h.get("reading")
                            c["checked"] += 1
                            if canon(hc) != canon(r["char"]):
                                c["mismatch"] += 1
                                mismatch[gid].append({"id": r["id"], "admit": r["char"], "label": hc, "channel": r.get("channel")})
    groups = {}
    for gid, g in R.FLOW_GROUPS.items():
        tot = Counter()
        for c in st[gid].values():
            tot.update(c)
        groups[gid] = {"name": g.name, "kind": KIND[g.kind], "methods": g.flow.describe(),
                       "total": dict(tot), "by_book": {b: dict(c) for b, c in sorted(st[gid].items())},
                       "labels": dict(lab_per.get(gid, {})), "mismatch": mismatch.get(gid, [])}
    return {"books": sorted(books), "groups": groups}


def _pct(a: int, b: int) -> str:
    return f"{a / b:.1%}" if b else "—"


def render_md(d: dict, tag: str, date: str) -> str:
    out = [f"# 字组状态 {date}（{tag}）", "",
           f"产物：{len(d['books'])} 册（{'、'.join(d['books'])}）。口径见 cv 仓 `open_guji_cv/eval/group_status.py` 模块头；"
           "每组 × 每册明细在同名 json。", "",
           "| 组 | 名 | 类型 | 出现格 | 放行率 | 送审 | 组判 | 组判率 | 人裁核对 | 不一致 | 人工数据 刻形/文意/切线/部件（中心库） | 多来源／更正过 | 方法数组 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for gid, g in d["groups"].items():
        t, lb = g["total"], g["labels"]
        out.append(f"| {gid} | {g['name']} | {g['kind']} | {t.get('occ', 0)} | {_pct(t.get('admit', 0), t.get('occ', 0))} | "
                   f"{t.get('review', 0)} | {t.get('flow', 0)} | {_pct(t.get('pick', 0), t.get('flow', 0))} | "
                   f"{t.get('checked', 0)} | {t.get('mismatch', 0)} | "
                   f"{lb.get('shape', 0)}/{lb.get('reading', 0)}/{lb.get('cut', 0)}/{lb.get('parts', 0)}（{lb.get('central', 0)}） | "
                   f"{lb.get('multi', 0)}／{lb.get('corrected', 0)} | "
                   f"`{g['methods']}` |")
    return "\n".join(out) + "\n"


def run(prods: list[Path], out: Path, labels: Path | None = None, codepoints: Path | None = None,
        tag: str = "", date: str | None = None) -> tuple[Path, Path]:
    date = date or _dt.date.today().isoformat()
    d = collect(prods, labels, codepoints)
    d.update({"date": date, "tag": tag, "prods": [str(p) for p in prods],
              "labels": str(labels) if labels else None, "codepoints": str(codepoints) if codepoints else None})
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{date}-{tag}" if tag else date
    pj, pm = out / f"{stem}.json", out / f"{stem}.md"
    pj.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    pm.write_text(render_md(d, tag or "—", date), encoding="utf-8")
    return pj, pm
