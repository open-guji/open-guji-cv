"""字组总表（2026-10-24，sheldon「形近字处理规范化」）：由注册表生成 `doc/字组/字组总表.md`，人不手改。

类型只分两类（sheldon 10-24 定）：**同义**（异体，同一个字的不同写法，`kind="variant"`）与**不同义**（形近，`kind="near_form"`）。
怎么判全看这一组的方法数组（`FlowSpec.methods`），不另分方法类。

    python -m open_guji_cv.groups.catalog            # 重写 doc/字组/字组总表.md
    python -m open_guji_cv.groups.catalog --check    # 只比对，不一致退出码 1

`tests/test_groups_catalog.py` 守住「注册表改了总表就得重生成」。只读注册表与 `config/groups/<组>/` 下的文件名、
模板库的 `source`，不被任何 Step 引用，不影响产物指纹。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import registry as R

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "doc" / "字组" / "字组总表.md"
KIND = {"variant": "同义", "near_form": "不同义"}


def _table_of(gid: str) -> str:
    if gid in R.CODEPOINT_GROUPS:
        return "CODEPOINT_GROUPS"
    if gid in R.SHAPE_GROUPS:
        return "SHAPE_GROUPS"
    return "GROUPS"


def _flags(fl) -> str:
    out = []
    if fl.review:
        out.append("复核改字" if fl.review_fix else ("复核改字(强)" if fl.review_fix_strong else "复核降审"))
    if fl.review_methods:
        out.append("复核只跑 " + " → ".join(R.describe(m) for m in fl.review_methods))
    if fl.review_abstain:
        out.append("弃权也降审")
    if fl.pair:
        out.append("相邻成对 " + "".join(fl.pair))
    if fl.lift_needs:
        out.append("补放须 " + "/".join(fl.lift_needs))
    if fl.lift_ref_agree:
        out.append("补放须与整理本同字")
    if fl.tolerate:
        out.append("陪衬 " + "".join(sorted(fl.tolerate)))
    if fl.families:
        out.append("两段判 " + "｜".join(fl.families))
    return "；".join(out)


def _bank(gid: str) -> str:
    p = ROOT / "config" / "groups" / gid / "ids_bank.json"
    if not p.exists():
        return ""
    d = json.loads(p.read_text(encoding="utf-8"))
    n = "／".join(f"{k}{len(v)}" for k, v in sorted(d.get("templates", {}).items()))
    lab = str((d.get("source") or {}).get("labels", "")).split("；")[0]
    return f"{n}（{lab}）"


def _files(gid: str) -> str:
    d = ROOT / "config" / "groups" / gid
    return " ".join(sorted(p.name for p in d.iterdir())) if d.is_dir() else ""


def rows() -> list[dict]:
    out = []
    for gid, g in R.FLOW_GROUPS.items():
        out.append({"id": gid, "name": g.name, "members": "".join(sorted(g.members)), "kind": KIND[g.kind],
                    "table": _table_of(gid), "methods": g.flow.describe(), "combine": g.flow.combine,
                    "flags": _flags(g.flow), "files": _files(gid), "bank": _bank(gid),
                    "overlaps": " ".join(g.overlaps), "note": g.note})
    return out


def render() -> str:
    rs = rows()
    n = {k: sum(1 for r in rs if r["kind"] == k) for k in KIND.values()}
    head = [
        "# 字组总表",
        "",
        "> **由 `python -m open_guji_cv.groups.catalog` 从 `groups/registry.py` 生成，不要手改。** 规范见 [README.md](README.md)；"
        "各组的来龙去脉、负结果、人工数据见同目录 `<组 id>.md`；各组成绩见 dataset 仓 `char-groups/status/`。",
        "",
        f"共 {len(rs)} 组：同义（异体）{n['同义']} 组，不同义（形近）{n['不同义']} 组。",
        "方法数组读法：`→` 依次试、第一个给字的说了算（combine=first）；`＋` 都跑、给字的须一致（combine=agree）；"
        "`[a → b]` 是子数组；`composite(crop(x0,x1,y0,y1) → hog)` 取局部框再做整字 HOG。",
        "",
        "| 组 | 名 | 类型 | 方法数组 | 复核与门 | 配置文件 | 模板库（各字条数，标签来源） | 共用成员 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    body = [f"| {r['id']} | {r['name']} | {r['kind']} | `{r['methods']}` | {r['flags']} | {r['files']} | {r['bank']} | {r['overlaps']} |"
            for r in rs]
    notes = ["", "## 注册表里的说明（`GroupSpec.note`）", ""] + [f"- **{r['id']}** {r['name']}：{r['note']}" for r in rs if r["note"]]
    return "\n".join(head + body + notes) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = render()
    if "--check" in argv:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("字组总表与注册表一致" if same else f"字组总表过期：跑 python -m open_guji_cv.groups.catalog 重生成 {OUT}")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print("写", OUT, len(rows()), "组")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
