#!/usr/bin/env python3
"""一册重跑之后重发待审单（M9 D8，GUJI-680 第一步）：出新单、雪碧图、与线上单的差异单，人点头再推。

切分、形近字改进后整册重跑，很多格不用再审了，但网站上的待审单还是旧的。原来要手工串六个脚本，
rev 自己数、差异没人看。本脚本分两步，中间停下等人看差异单：

  prep   按现行产物出新单，不碰中心库（产出都在 <工作区>/reports/<册>/_publish/<rev>/）：
         1. `guji audit alt`：每格挂相似字（缺 torch 时它自己跳过，单子照出，只是没有 alt）
         2. pending_list.py：产物里没放行的格（＋卡片字段）
         3. pending_route.py：扣掉截止现在已经有人裁的格（中心库 events），分公众单、团队单
         4. sprite_build.py、alt_build.py：每格的字块图、相似字字形图（`img`、`alt[].g`）
         5. 差异单：对中心库现行单，去掉几格（人裁过／机器现在放行了／格号变了）、新增几格、留下几格；
            旧 rev 上已有的网站精校票也列出（它们不是人裁事件，扣不掉）
  push   人看过差异单、点了头才跑（要 --yes）：新单写进数据目录 proofing/<书>/<章>.pending.json，
         写一行台账（ledger.py），加 --sync 再 `guji db sync` 推进中心库。
         雪碧图上 COS／R2、产物包标 main、book-text 换文本这三样还要另做，push 末尾逐条打出来。

**文本和待审单要一起换**：新单的格号按新切分排，网站显示的还是 book-text 的旧文本就会对不上。
所以 prep 要 --export-dir（同一次导出的 char／cord／pages），push 前先把同一次导出推到 book-text。

用法：
  python scripts/zhengli/republish.py prep --book vol06 -w $WS --export-dir $WS/reports/vol06/_export
  python scripts/zhengli/republish.py push --book vol06 -w $WS --rev 006-r3 --yes [--sync]
产物根取 GUJI_PRODUCTS_DIR，没设就是 <工作区>/products（与引擎同口径）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

CV = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def chapter_of(book: str) -> str:
    return re.sub(r"\D", "", book).zfill(3)


def text_id_of(ws: Path) -> str:
    """book-text 条目 id = 书目录名 `<id>-<书名>` 的 id 段（四庫總目 96mid1ogzk）。"""
    return ws.name.split("-", 1)[0]


def next_rev(old: str | None, chapter: str) -> str:
    """`006-r2` → `006-r3`；没有旧单从 r0 起。"""
    m = re.fullmatch(r".+-r(\d+)", old or "")
    return f"{chapter}-r{int(m[1]) + 1 if m else 0}"


def products_root(ws: Path) -> Path:
    env = os.environ.get("GUJI_PRODUCTS_DIR")
    return Path(env).expanduser() if env else ws / "products"


def data_dir(ws: Path) -> Path:
    """迁了中心库的工作区是数据目录，没迁的就是工作区自己（`core.workspace.data_root`）。"""
    sys.path.insert(0, str(CV))
    from open_guji_cv.core.workspace import data_root
    return data_root(ws)


def proofing_path(ws: Path, text_id: str, chapter: str) -> Path:
    return data_dir(ws) / "feedback" / "lists" / "proofing" / text_id / f"{chapter}.pending.json"


def cell_states(products: Path, book: str) -> dict[str, tuple[str, str | None]]:
    """现行 seed_admit 每格的去向：`("admit", 放行字)`／`("excluded", None)`／`("review", None)`（差异单说原因用）。"""
    out: dict[str, tuple[str, str | None]] = {}
    for f in sorted((products / book / "seed_admit").glob("p*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))["seed_admit"]
        for col in s["columns"]:
            for ch in col["chars"]:
                st = "admit" if ch.get("admit") else ("excluded" if "excluded" in ch.get("doubts", []) else "review")
                out[ch["id"].split(":", 1)[1]] = (st, ch.get("char"))
    return out


def web_votes(ws: Path, text_id: str, rev: str | None) -> Counter:
    """旧 rev 上网站精校票按格计数（`feedback/lists/web/<书>/<rev>.jsonl`）。"""
    f = data_dir(ws) / "feedback" / "lists" / "web" / text_id / f"{rev}.jsonl"
    c: Counter = Counter()
    if rev and f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                cell = json.loads(line).get("a")       # 精校票的格号字段是 a（页:列:格）
            except ValueError:
                continue
            if cell:
                c[str(cell)] += 1
    return c


def diff(old: dict | None, new: dict, dropped: list[dict], states: dict, votes: Counter) -> dict:
    """新旧两张单逐格比：去掉的格按原因分（人裁过／机器放行了／排除名单／格号没了，多半是重切）。"""
    o = {c["cell"]: c for c in (old or {}).get("cells", [])}
    n = {c["cell"]: c for c in new.get("cells", [])}
    by_human = {c["cell"] for c in dropped}
    removed = sorted(set(o) - set(n), key=_key)
    why = {}
    for c in removed:
        st, ch = states.get(c, (None, None))
        why[c] = ("人裁过" if c in by_human else f"机器放行「{ch or '□'}」" if st == "admit"
                  else "排除名单（非字）" if st == "excluded" else "格号没了（多半重切）")
    return {"old_rev": (old or {}).get("rev"), "new_rev": new.get("rev"), "old": len(o), "new": len(n),
            "kept": len(set(o) & set(n)), "removed": [{"cell": c, "why": why[c]} for c in removed],
            "added": [{"cell": c, "cls": n[c].get("cls")} for c in sorted(set(n) - set(o), key=_key)],
            "removed_by": dict(Counter(v.split("「")[0] for v in why.values())),
            "votes_on_old": sum(votes.values()), "voted_cells_kept": sorted(set(votes) & set(n), key=_key)}


def _key(cell: str):
    """`12:3:5a` → (12, 3, 5, 'a')：按页、列、格排。"""
    nums = [int(x) for x in re.findall(r"\d+", cell)]
    return (*nums, cell[-1] if cell[-1:].isalpha() else "")


def diff_md(book: str, d: dict, team: int, reflow: int) -> str:
    lines = [f"# {book} 待审单差异：{d['old_rev'] or '（线上没有）'} → {d['new_rev']}", "",
             f"- 线上 {d['old']} 格 → 新单 {d['new']} 格（留下 {d['kept']}，去掉 {len(d['removed'])}，新增 {len(d['added'])}）",
             "- 去掉的原因：" + ("、".join(f"{k} {v}" for k, v in sorted(d["removed_by"].items(), key=lambda kv: -kv[1])) or "无"),
             f"- 团队单 {team} 格（不上网站）；回流单 {reflow} 格（成片同因，只列出）"]
    if d["votes_on_old"]:
        lines.append(f"- ⚠ 旧单上有网站精校票 {d['votes_on_old']} 张：它们不是人裁事件，扣不掉；"
                     f"其中 {len(d['voted_cells_kept'])} 格新单上还在，换 rev 后网站不再显示旧票")
    lines += ["", "## 去掉的格", "", "| 格 | 原因 |", "|---|---|"] + [f"| `{x['cell']}` | {x['why']} |" for x in d["removed"][:300]]
    if len(d["removed"]) > 300:
        lines.append(f"| … | 另 {len(d['removed']) - 300} 格见 diff.json |")
    lines += ["", "## 新增的格", "", "| 格 | 成因 |", "|---|---|"] + [f"| `{x['cell']}` | {x['cls'] or ''} |" for x in d["added"][:300]]
    if len(d["added"]) > 300:
        lines.append(f"| … | 另 {len(d['added']) - 300} 格见 diff.json |")
    return "\n".join(lines) + "\n"


def run(cmd, **kw) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    print("$ " + " ".join(cmd), flush=True)
    p = subprocess.run(cmd, text=True, capture_output=True, **kw)
    sys.stdout.write((p.stdout or "")[-2000:])
    if p.returncode:
        sys.stderr.write((p.stderr or "")[-3000:])
    return p


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=CV, capture_output=True, text=True).stdout.strip()


def cv_version() -> str | None:
    """读本仓 pyproject 的版本号（可编辑安装的包元数据装完就不更新，会落后）。"""
    import tomllib
    try:
        return tomllib.loads((CV / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError):
        return None


def raw_dir(ws: Path, book: str) -> Path | None:
    return next((p for p in sorted((ws / "data_full").glob(f"*/{book}")) if p.is_dir()), None)


def cmd_prep(a) -> int:
    ws, book = Path(a.workspace).resolve(), a.book
    chapter, text_id = a.chapter or chapter_of(book), a.text_id or text_id_of(ws)
    products, export = products_root(ws), Path(a.export_dir)
    cord = export / f"{chapter}.cord.json"
    if not cord.exists():
        sys.exit(f"✗ {cord} 不存在：先用同一份产物导出 char／cord（zl.py export 或 export_guji_format.py）")
    online = proofing_path(ws, text_id, chapter)
    old = json.loads(online.read_text(encoding="utf-8")) if online.exists() else None
    rev = a.rev or next_rev((old or {}).get("rev"), chapter)
    out = Path(a.out) if a.out else ws / "reports" / book / "_publish" / rev
    out.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    env = {**os.environ, "GUJI_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8"}

    cards = ws / "reports" / book / f"{book}.cards.alt.json"
    if not a.no_alt:
        run([py, "-m", "open_guji_cv.cli_v2", "audit", "alt", book, "-w", ws] + (["--fetch-zi"] if a.fetch_zi else []),
            cwd=CV, env=env)
    raw = out / "raw"
    cmd = [py, HERE / "pending_list.py", "--products", products, "--book", book, "--chapter", chapter, "--rev", rev,
           "--cv-commit", a.cv_commit or git_head(), "--out", raw]
    if a.cv_version or cv_version():
        cmd += ["--cv-version", a.cv_version or cv_version()]
    if cards.exists() and not a.no_alt:
        cmd += ["--cards", cards]
    if run(cmd, env=env).returncode:
        return 1
    events = data_dir(ws) / "feedback" / "events"
    st = json.loads((data_dir(ws) / ".central-state.json").read_text(encoding="utf-8")) \
        if (data_dir(ws) / ".central-state.json").exists() else {}
    routed = out / "routed"
    cmd = [py, HERE / "pending_route.py", "--pending", raw / f"{chapter}.pending.json", "--book", book,
           "--events", events, "--out", routed]
    if st.get("rev") is not None:
        cmd += ["--db-rev", str(st["rev"])]
    if a.team_pages:
        cmd += ["--team-pages", a.team_pages]
    if a.page_types:
        cmd += ["--page-types", a.page_types]
    if run(cmd, env=env).returncode:
        return 1
    public = routed / f"{chapter}.pending.json"
    final = public
    rd = raw_dir(ws, book)
    if rd and not a.no_sprite:
        sp = out / "sprites"
        if run([py, HERE / "sprite_build.py", "--cord", cord, "--pending", public, "--raw-dir", rd,
                "--book", text_id, "--vol", chapter[-2:], "--out", sp]).returncode == 0:
            final = sp / "pending.with-img.json"
            has_alt = any(c.get("alt") for c in json.loads(final.read_text(encoding="utf-8")).get("cells", []))
            if has_alt and run([py, HERE / "alt_build.py", "--pending", final, "--chapter", chapter, "--out", sp]).returncode == 0:
                final = sp / "pending.with-alt.json"
    elif not rd:
        print(f"ⓘ 没找到 {book} 的原图目录（{ws}/data_full/*/{book}），不出雪碧图，单子上没有 img")
    new = json.loads(final.read_text(encoding="utf-8"))
    shutil.copyfile(final, out / f"{chapter}.pending.json")
    raw_doc = json.loads((raw / f"{chapter}.pending.json").read_text(encoding="utf-8"))
    pub_cells = {c["cell"] for c in json.loads(public.read_text(encoding="utf-8"))["cells"]}
    dropped = [c for c in raw_doc["cells"] if c["cell"] not in pub_cells]
    team = json.loads((routed / f"{chapter}.team.pending.json").read_text(encoding="utf-8"))["cells"]
    dropped = [c for c in dropped if c["cell"] not in {t["cell"] for t in team}]
    reflow = max(0, len((routed / f"{chapter}.reflow.tsv").read_text(encoding="utf-8").splitlines()) - 1)
    d = diff(old, new, dropped, cell_states(products, book), web_votes(ws, text_id, (old or {}).get("rev")))
    (out / "diff.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "差异单.md").write_text(diff_md(book, d, len(team), reflow), encoding="utf-8")
    plan = {"book": book, "rev": rev, "chapter": chapter, "text_id": text_id, "pending": str(out / f"{chapter}.pending.json"),
            "team": str(routed / f"{chapter}.team.pending.json"), "sprites": str(out / "sprites") if (out / "sprites").exists() else None,
            "export_dir": str(export), "online": str(online)}
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{book} 待审单 {d['old_rev'] or '无'} {d['old']} 格 → {rev} {d['new']} 格（去掉 {len(d['removed'])}，新增 {len(d['added'])}）"
          f"\n差异单：{out / '差异单.md'}\n看过没问题再：python {Path(__file__).name} push --book {book} -w {ws} --rev {rev} --yes")
    return 0


def cmd_push(a) -> int:
    ws, book = Path(a.workspace).resolve(), a.book
    out = Path(a.out) if a.out else ws / "reports" / book / "_publish" / a.rev
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    if not a.yes:
        sys.exit(f"✗ 推上线前先看 {out / '差异单.md'}，确认后加 --yes")
    online = Path(plan["online"])
    if online.exists():
        bak = out / f"online.{json.loads(online.read_text(encoding='utf-8')).get('rev')}.pending.json"
        shutil.copyfile(online, bak)
        print(f"旧单备份 → {bak}")
    online.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plan["pending"], online)
    print(f"新单 → {online}")
    pages = Path(plan["export_dir"]) / f"{plan['chapter']}.pages.json"
    cmd = [sys.executable, HERE / "ledger.py", "--ws", ws, "--book", book, "--pending", online]
    if pages.exists():
        cmd += ["--pages-json", pages]
    run(cmd, env={**os.environ, "GUJI_WORKSPACE": str(ws)})
    if a.sync:
        run([sys.executable, "-m", "open_guji_cv.cli_v2", "db", "sync", "-w", ws], cwd=CV,
            env={**os.environ, "GUJI_WORKSPACE": str(ws)})
    todo = [] if a.sync else [f"guji db sync -w {ws}   # 推进中心库，网站每日 proofing-sync 才拿得到"]
    todo += [f"book-text：同一次导出（{plan['export_dir']}）的 char／cord／norm 用 bump_original.py 升版、开 PR（文本与单子要一起换）",
             f"guji products pack push {book} --change <改动名> --main   # 产物包标 main，标签记 rev={a.rev}"]
    if plan.get("sprites"):
        todo.append(f"雪碧图 {plan['sprites']} 上 COS／R2（GUJI-675 落地前手工传）")
    print("\n还要做：\n" + "\n".join(f"- {t}" for t in todo))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prep", "push"):
        p = sp.add_parser(name)
        p.add_argument("--book", required=True)
        p.add_argument("-w", "--workspace", required=True)
        p.add_argument("--rev", help="新单 rev；prep 缺省按线上单加一（006-r2 → 006-r3）" if name == "prep" else "prep 打出的 rev",
                       required=name == "push")
        p.add_argument("--out", help="出单目录，缺省 <工作区>/reports/<册>/_publish/<rev>")
        if name == "prep":
            p.add_argument("--export-dir", required=True, help="同一份产物导出的 char／cord／pages 所在目录")
            p.add_argument("--chapter")
            p.add_argument("--text-id")
            p.add_argument("--cv-commit")
            p.add_argument("--cv-version")
            p.add_argument("--team-pages", help="只给团队的页，如 1-3,150")
            p.add_argument("--page-types", help="{页: 页型} JSON；不是 body 的页进团队单")
            p.add_argument("--no-alt", action="store_true", help="不跑 guji audit alt（单子上没有相似字）")
            p.add_argument("--fetch-zi", action="store_true", help="audit alt 去字统网补缓存（首次慢）")
            p.add_argument("--no-sprite", action="store_true")
        else:
            p.add_argument("--yes", action="store_true", help="看过差异单、确认推")
            p.add_argument("--sync", action="store_true", help="写完再 guji db sync 推进中心库")
    a = ap.parse_args(argv)
    return cmd_prep(a) if a.cmd == "prep" else cmd_push(a)


if __name__ == "__main__":
    sys.exit(main())
