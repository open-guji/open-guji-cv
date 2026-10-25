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
         写一行台账（ledger.py），加 --sync 再 `guji db sync` 推进中心库，成功后触发网站 proofing-sync（publish）。
         雪碧图（改名带内容哈希、`sprites[]` 写进单子）在这里按 sha256 传进 R2；proofing-sync 再把图
         和单子一起发到 COS（GUJI-675）。产物包标 main、book-text 换文本这两样还要另做，push 末尾逐条打出来。
         动手之前先过两道门（GUJI-730）：单子引用的图都登记在 `sprites[]` 里；旧单上的票都落成了人裁。

**文本和待审单要一起换**：新单的格号按新切分排，网站显示的还是 book-text 的旧文本就会对不上。
所以 prep 要 --export-dir（同一次导出的 char／cord／pages），push 前先把同一次导出推到 book-text。

别人已经跑好、存成产物包的结果，不用重跑：`from-pack` 一条命令拉库、取包、核人裁绑定、导出、prep，
纯机器约 3 分钟（vol05 实测）。人裁怎么和新切分合并：产物里的 seed_admit 跑时已按锚框重绑了所有人裁
（`feedback/bindings.py`），出单前再核一遍——包跑完之后才来的人裁、按格号扣会扣错的格都列进差异单。

用法：
  python scripts/zhengli/republish.py from-pack --book vol05 -w $WS --label <包标签> --book-text <book-text 仓>
  python scripts/zhengli/republish.py prep --book vol06 -w $WS --export-dir $WS/reports/vol06/_export [--recheck <复审清单>]
  python scripts/zhengli/republish.py push --book vol06 -w $WS --rev 006-r3 --yes [--sync] [--book-text <book-text 仓>]
  python scripts/zhengli/republish.py add-alt --book vol05 -w $WS [--yes --sync]   # 线上单漏了相似字：原地补，不换 rev
  python scripts/zhengli/republish.py add-sprites --book vol05 -w $WS --export-dir <cord 所在目录> [--yes --sync]
                                                                      # 线上单的雪碧图没上 R2：重建、核坐标不变、传 R2、原地补 sprites[]
一条命令（M10 复盘第 3 项）：出单、过门、传图、推库、只发这一章、等网站发布、冒烟，一次做完：
  python scripts/zhengli/republish.py issue --book vol06 -w $WS --label <包标签> --book-text <book-text 仓> [--recheck <复审清单>]
  python scripts/zhengli/republish.py issue --book vol06 -w $WS --export-dir <导出目录> [--recheck …]
推库要 `.[datastore]`（psycopg、websockets）和能写 main 的令牌。
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
sys.path.insert(0, str(HERE))
import sprite_pub


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


SITE = "https://www.openguji.com"


def old_rev_votes(ws: Path, text_id: str, rev: str) -> tuple[list[dict], str]:
    """旧 rev 上的全部精校票。有 CELLREVIEW_TOKEN 就直接读网站 KV（刚投的票每日同步还没并进中心库），
    否则读数据目录里每日同步存下的 `feedback/lists/web/<书>/<rev>.jsonl`。返回 (票, 来源)。"""
    tok = os.environ.get("CELLREVIEW_TOKEN")
    if tok:
        import urllib.parse
        import urllib.request
        items, cursor = [], ""
        while True:
            q = {"rev": rev, "book": text_id, "limit": "256", **({"cursor": cursor} if cursor else {})}
            req = urllib.request.Request(f"{SITE}/api/cellreview?{urllib.parse.urlencode(q)}",
                                         headers={"Authorization": f"Bearer {tok}", "User-Agent": "open-guji-cv/republish"})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
            if not d.get("success"):
                sys.exit(f"✗ 读网站票失败：{d.get('error')}")
            items += d.get("items") or []
            cursor = d.get("cursor") or ""
            if not d.get("hasMore") or not cursor:
                return items, "网站 KV"
    f = data_dir(ws) / "feedback" / "lists" / "web" / text_id / f"{rev}.jsonl"
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []
    return rows, "中心库快照（每日同步之后的票看不到，设 CELLREVIEW_TOKEN 读 KV）"


def ticket_ledger(ws: Path, book: str, text_id: str, rev: str, votes: list[dict], held=None) -> dict:
    """一张单的票账（1.0 发布标准 G0）：每格最后一票归到 写入／与已有人裁一致／看不出／挂起／未落 之一。

    写入 = 该格有晚于这一票的定字人裁；一致 = 该格的定字人裁早于这一票（cellvotes 判一致跳过）；
    看不出 = 只投了「看不出」；挂起 = 在 cellvotes draft 的挂起清单（held.tsv 第一列）里；其余未落——
    包括缺省挂起却没记进清单的「无字」。账要平：有效票格数 = 五项之和。"""
    import datetime as dt
    sys.path.insert(0, str(CV))
    from open_guji_cv.feedback.web_votes import latest_votes
    from pending_route import cell_of, deciding
    latest, dropped = latest_votes(votes, text_id, rev)
    held = set(held or ())
    last: dict[str, float] = {}                 # 格 → 最晚一条定字人裁的时刻（秒）
    for f in sorted((data_dir(ws) / "feedback" / "events").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            c = cell_of(e, book) if deciding(e) else None
            if c:
                try:
                    t = dt.datetime.fromisoformat(str(e.get("ts")).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    t = 0.0
                last[c] = max(last.get(c, 0.0), t)
    rows = {"写入": [], "与已有人裁一致": [], "看不出": [], "挂起": [], "未落": []}
    for v in latest:
        a, ts = v["a"], float(v.get("ts") or 0)
        ts = ts / 1000 if ts > 1e11 else ts       # KV 里是毫秒
        if v["choice"] == "unsure":
            rows["看不出"].append(v)
        elif a in last:
            rows["写入" if last[a] >= ts else "与已有人裁一致"].append(v)
        elif a in held:
            rows["挂起"].append(v)
        else:
            rows["未落"].append(v)
    return {"rev": rev, "votes": len(latest), "dropped": dropped, "rows": rows,
            "counts": {k: len(x) for k, x in rows.items()}}


def ledger_md(led: dict) -> str:
    c = led["counts"]
    ok = "账平" if sum(c.values()) == led["votes"] else "账不平"
    s = (f"票账 {led['rev']}：有效 {led['votes']} 格 = 写入 {c['写入']} ＋ 一致 {c['与已有人裁一致']} ＋ 看不出 {c['看不出']}"
         f" ＋ 挂起 {c['挂起']} ＋ 未落 {c['未落']}（{ok}）")
    if c["未落"]:
        s += "；未落：" + " ".join(f"{v['a']}({v['choice']})" for v in led["rows"]["未落"][:20])
    return s


def unlanded_votes(ws: Path, book: str, text_id: str, rev: str, votes: list[dict], held=None) -> list[dict]:
    """旧单上还没落成人裁的票（G0；第五册 168 票就是新单先上、票后落才漂了格位）。见 `ticket_ledger` 的「未落」。"""
    return ticket_ledger(ws, book, text_id, rev, votes, held)["rows"]["未落"]


def votes_gate(ws: Path, book: str, text_id: str, old_rev: str | None, new_rev: str, a) -> None:
    """换单门（GUJI-730 P0-3）：旧单上的票没落完不换新单，免得格号漂（换了切分，旧票就对不上格）。"""
    if not old_rev or old_rev == new_rev:
        return
    votes, src = old_rev_votes(ws, text_id, old_rev)
    hf = getattr(a, "held_file", None)
    held = [ln.split("\t")[0] for ln in Path(hf).read_text(encoding="utf-8").splitlines()[1:] if ln.strip()] if hf else []
    led = ticket_ledger(ws, book, text_id, old_rev, votes, held)
    left = led["rows"]["未落"]
    print(f"旧单 {old_rev} 的票（{src}）：{ledger_md(led)}")
    if not left:
        return
    cells = " ".join(f"{v['a']}({v['choice']})" for v in left[:20])
    if getattr(a, "ack_unlanded_votes", None):
        print(f"⚠ 未落的票照换（--ack-unlanded-votes：{a.ack_unlanded_votes}）：{cells}")
        return
    sys.exit(f"✗ 旧单 {old_rev} 还有 {len(left)} 格的票没落成人裁：{cells}\n"
             f"  先 guji cellvotes draft/write 把票落了再换单；确要照换加 --ack-unlanded-votes \"<原因>\"")

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
            "added": [{"cell": c, "cls": n[c].get("cause") or n[c].get("cls")} for c in sorted(set(n) - set(o), key=_key)],
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


def recheck_md(doc: dict, missing_tsv: Path) -> str:
    """差异单「复审格」一节：哪些格是按复审清单放回来的、说明是什么；现行切分里没有的列出来交人另想办法。"""
    rc = [c for c in doc.get("cells", []) if c.get("recheck")]
    miss = [ln.split("\t") for ln in missing_tsv.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()] \
        if missing_tsv.exists() else []
    lines = ["", f"## 复审格（--recheck）：上单 {len(rc)} 格，现行切分里没有 {len(miss)} 格", "",
             "| 格 | 说明 | 已有人裁 |", "|---|---|---|"]
    lines += [f"| `{c['cell']}` | {c.get('note', '')} | {(c.get('prior') or {}).get('c', '')} |" for c in rc]
    if miss:
        lines += ["", "现行切分里没有这几格（多半重切过），没放上单：" + "、".join(f"`{m[0]}`" for m in miss)]
    return "\n".join(lines) + "\n"


def add_causes(pending: Path, products: Path, book: str) -> None:
    """每格并入主成因码 `cause`／`cause_detail`（`review/causes.py`，GUJI-668）；`cls` 照旧不动（M10 还在用）。"""
    sys.path.insert(0, str(CV))
    from open_guji_cv.review.causes import book_causes
    if not pending.exists():
        return
    res = book_causes(products, book)
    doc = json.loads(pending.read_text(encoding="utf-8"))
    for c in doc.get("cells", []):
        if c["cell"] in res:
            c["cause"] = res[c["cell"]]["cause"]
            if res[c["cell"]]["detail"]:
                c["cause_detail"] = res[c["cell"]]["detail"]
    pending.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def run(cmd, **kw) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    print("$ " + " ".join(cmd), flush=True)
    p = subprocess.run(cmd, text=True, capture_output=True, **kw)
    sys.stdout.write((p.stdout or "")[-2000:])
    if p.returncode:
        sys.stderr.write((p.stderr or "")[-3000:])
    return p


WEB_REPO = "open-guji/kaiyuanguji-web"


def publish_web(a) -> bool:
    """推库成功后马上触发网站 proofing-sync（publish），不等每天一次的定时（GUJI-730 P0-1）。

    用本机 `gh`（会话的 GitHub 授权，或环境变量 GH_TOKEN，要对 kaiyuanguji-web 有 actions 写权限）。
    触发不了只打印手动做法，不算失败：单子已在中心库，每日定时兜底。"""
    if getattr(a, "no_publish_web", False):
        return False
    if not shutil.which("gh"):
        print("⚠ 没有 gh，网站 proofing-sync 没触发：等每日定时，或手动跑 proofing-sync.yml（production、publish、dry_run=false）")
        return False
    base = ["gh", "workflow", "run", "proofing-sync.yml", "-R", WEB_REPO, "--ref", "main",  # 带 --ref：云端会话没有 GraphQL，查不了默认分支
            "-f", "target=production", "-f", "parts=publish", "-f", "dry_run=false"]
    only = getattr(a, "publish_only", None)
    # 只发这一章（kaiyuanguji-web#584 起有 only 输入）：一两分钟上线，不等全站；网站还没这个输入就退回全站发布
    p = run(base + ["-f", f"only={only}"]) if only else None
    if p is None or p.returncode:
        p = run(base)
    if p.returncode:
        print("⚠ 网站 proofing-sync 触发失败（见上），等每日定时或手动跑")
        return False
    print(f"已触发网站 proofing-sync（publish）：gh run list -R {WEB_REPO} -w proofing-sync.yml 看进度，约 3 分钟上线")
    return True


def sprites_gate(doc: dict, a) -> None:
    """出单门（GUJI-730 P0-2）：单子引用的每张图都要登记在 `sprites[]` 里，否则网站上就是 404（册 004–007 的 alt 图）。
    不过就停；确知要带缺图上线才加 --ack-missing-sprites。"""
    miss = sprite_pub.missing(doc)
    if not miss:
        return
    msg = f"单子引用了 {len(miss)} 张没登记进 sprites[] 的图：{' '.join(miss[:10])}"
    if getattr(a, "ack_missing_sprites", False):
        print(f"⚠ {msg}（--ack-missing-sprites，照推）")
        return
    sys.exit(f"✗ {msg}。先用 add-sprites 补齐（会连相似字图一起重建），或加 --ack-missing-sprites")

def pack_label(rev: str) -> str:
    return f"rev-{rev}"


def pack_rev(a, ws: Path, book: str, rev: str) -> str | None:
    """出单版产物存成包 `rev-<rev>`（GUJI-730 P1-1）：落这张单上的票时 `guji cellvotes draft --pack rev-<rev>`
    直接取回当锚，不用重跑，格号也不会漂。存不成只告警（落票退回老办法：重跑有票的页）。"""
    if getattr(a, "no_pack", False):
        return None
    label = pack_label(rev)
    p = run([sys.executable, "-m", "open_guji_cv.cli_v2", "products", "pack", "push", book, "--label", label,
             "--root", products_root(ws), "--no-record", "--note", f"待审单 {rev} 出单版（republish push）"],
            cwd=CV, env={**os.environ, "GUJI_WORKSPACE": str(ws)})
    if p.returncode:
        print(f"⚠ 出单版产物包 {label} 没存成（见上）：落票时只能重跑有票的页算锚")
        return None
    return label

def sync_and_publish(a, ws: Path) -> bool:
    """`guji db sync`，成功了再触发网站发布。返回是否已触发。"""
    p = run([sys.executable, "-m", "open_guji_cv.cli_v2", "db", "sync", "-w", ws], cwd=CV,
            env={**os.environ, "GUJI_WORKSPACE": str(ws)})
    if p.returncode:
        print("✗ guji db sync 失败，没触发网站发布")
        return False
    return publish_web(a)


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


def cmd_prep(a, bind: dict | None = None, pack: str | None = None) -> int:
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
        cards.unlink(missing_ok=True)             # 上一次的卡不能顶替这一次（格号可能已变）
        rc_extra = ["--extra", a.recheck] if getattr(a, "recheck", None) else []
        if run([py, "-m", "open_guji_cv.cli_v2", "audit", "alt", book, "-w", ws] + (["--fetch-zi"] if a.fetch_zi else []) + rc_extra,
               cwd=CV, env=env).returncode:
            # 10-21 殿本重发时这步静默出了 0 格相似字，单子照发，网站卡片上相似字全没了；现在出不来就停
            sys.exit("✗ guji audit alt 没出相似字（见上面的原因）；确实要出没有相似字的单子加 --no-alt")
    raw = out / "raw"
    cmd = [py, HERE / "pending_list.py", "--products", products, "--book", book, "--chapter", chapter, "--rev", rev,
           "--cv-commit", a.cv_commit or git_head(), "--out", raw]
    if a.cv_version or cv_version():
        cmd += ["--cv-version", a.cv_version or cv_version()]
    if cards.exists() and not a.no_alt:
        cmd += ["--cards", cards]
    if getattr(a, "recheck", None):
        cmd += ["--recheck", a.recheck]
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
    if bind and bind["id_mismatch"]:              # 人裁绑到了别的格／绑不上：原格号上的人裁不算这一格定了字
        keep = out / "keep.txt"
        keep.write_text("\n".join(bind["id_mismatch"]) + "\n", encoding="utf-8")
        cmd += ["--keep", keep]
    if run(cmd, env=env).returncode:
        return 1
    public = routed / f"{chapter}.pending.json"
    add_causes(public, products, book)
    add_causes(routed / f"{chapter}.team.pending.json", products, book)
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
    if final.parent == out / "sprites" and (out / "sprites" / "assets.json").exists():
        new, _ = sprite_pub.attach(new, out / "sprites")     # 图改名带哈希、sprites[] 写进单子（GUJI-675）
        (out / f"{chapter}.pending.json").write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        shutil.copyfile(final, out / f"{chapter}.pending.json")
    raw_doc = json.loads((raw / f"{chapter}.pending.json").read_text(encoding="utf-8"))
    pub_cells = {c["cell"] for c in json.loads(public.read_text(encoding="utf-8"))["cells"]}
    dropped = [c for c in raw_doc["cells"] if c["cell"] not in pub_cells]
    team = json.loads((routed / f"{chapter}.team.pending.json").read_text(encoding="utf-8"))["cells"]
    dropped = [c for c in dropped if c["cell"] not in {t["cell"] for t in team}]
    reflow = max(0, len((routed / f"{chapter}.reflow.tsv").read_text(encoding="utf-8").splitlines()) - 1)
    d = diff(old, new, dropped, cell_states(products, book), web_votes(ws, text_id, (old or {}).get("rev")))
    (out / "diff.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    md = diff_md(book, d, len(team), reflow)
    if getattr(a, "recheck", None):
        md += recheck_md(new, raw / "recheck_missing.tsv")
    if pack:
        md = md.replace("\n\n## 去掉的格", f"\n- 产物包 `{pack}`\n\n## 去掉的格", 1)
    if bind:
        md += "\n".join(bind_md(bind)) + "\n"
        d["bind"] = bind
        (out / "diff.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "差异单.md").write_text(md, encoding="utf-8")
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
    doc_new = json.loads(Path(plan["pending"]).read_text(encoding="utf-8"))
    online = Path(plan["online"])
    old_rev = json.loads(online.read_text(encoding="utf-8")).get("rev") if online.exists() else None
    sprites_gate(doc_new, a)                                     # 两道门都在动任何东西之前
    votes_gate(ws, book, plan.get("text_id") or text_id_of(ws), old_rev, a.rev, a)
    if a.book_text:
        d = json.loads((out / "diff.json").read_text(encoding="utf-8"))
        bump_book_text(Path(a.book_text), plan, a.note or f"{book} 换最新产物：待审 {d['old']}→{d['new']}，待审单 {a.rev}")
    if doc_new.get("sprites"):                                   # 图先进 R2，单子再写：单上线时图一定取得到
        stats = sprite_pub.upload(doc_new["sprites"], Path(plan["sprites"]) / "pub")
        print(f"雪碧图 {len(doc_new['sprites'])} 张 → R2：{stats}")
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
    label = pack_rev(a, ws, book, a.rev) if a.sync else None
    published = sync_and_publish(a, ws) if a.sync else False
    if a.sync:                                                   # 后台「文本整理」的人审进度（所有册），失败不挡
        import progress_report
        progress_report.try_run(book, plan.get("text_id") or text_id_of(ws))
    todo = [] if a.sync else [f"guji db sync -w {ws}   # 推进中心库，网站每日 proofing-sync 才拿得到"]
    if label:
        print(f"出单版产物包：{label}；落这张单的票用 guji cellvotes draft … --rev {a.rev} --pack {label}")
    elif a.sync:
        todo.append(f"guji products pack push {book} --label {pack_label(a.rev)}   # 出单版产物包，落票免重跑")
    if not a.book_text:
        todo += [f"book-text：同一次导出（{plan['export_dir']}）的 char／cord／norm 用 bump_original.py --pr TBD 升版，提交到 dev（文本与单子要一起换）"]
    if not published:
        todo += ["网站别等每日定时（待审单 21:23 UTC 先于文本 21:43 UTC，每天差 20 分钟）：单子推了就手动跑 kaiyuanguji-web 的 "
                 "proofing-sync.yml（target=production、parts=publish、dry_run=false）；加 --sync 时本脚本自动触发"]
    todo += ["book-text 每日合并进 main 之后跑 kaiyuanguji-web 的 data.yml（flow=text），网站文本才换新",
             (f"guji products pack promote {book} --label {label}   # 这一版是正式结果就标 main" if label else
              f"guji products pack push {book} --change <改动名> --main   # 产物包标 main，标签记 rev={a.rev}")]
    if doc_new.get("sprites"):
        todo.append("雪碧图已进 R2，单子里的 sprites[] 会随 guji db sync 进中心库；网站 proofing-sync（publish）发布时一并传到 COS")
    elif plan.get("sprites"):
        todo.append("⚠ 这次出了雪碧图目录，但单子里没有 sprites[]：网站取不到图（见 sprite_pub.py）")
    print("\n还要做：\n" + "\n".join(f"- {t}" for t in todo))
    return 0


DATA = "https://data.openguji.com"


def _http(url: str, method: str = "GET", timeout: int = 30):
    import urllib.request
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "open-guji-cv/republish"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, (r.read() if method == "GET" else b"")


def wait_publish(since: str, timeout_s: int = 1800, poll_s: int = 20) -> str | None:
    """等 issue 触发的那次 proofing-sync 跑完（REST 查 run，会话里没有 GraphQL）。返回 conclusion；等不到返回 None。"""
    import time
    t_end = time.time() + timeout_s
    run_id = None
    while time.time() < t_end:
        q = ["gh", "api", f"repos/{WEB_REPO}/actions/workflows/proofing-sync.yml/runs?event=workflow_dispatch&per_page=5",
             "--jq", f'[.workflow_runs[] | select(.created_at >= "{since}")] | sort_by(.created_at) | .[0] | "\\(.id) \\(.status) \\(.conclusion)"']
        p = subprocess.run(q, capture_output=True, text=True)
        out = (p.stdout or "").strip()
        rid, status, concl = (out.split() + ["", "", ""])[:3]
        if p.returncode == 0 and rid not in ("", "null"):   # 刚触发时还查不到 run，jq 吐 "null null null"
            if run_id != rid:
                run_id = rid
                print(f"网站发布 run {rid}：https://github.com/{WEB_REPO}/actions/runs/{rid}")
            if status == "completed":
                return concl
        time.sleep(poll_s)
    return None


def smoke(text_id: str, chapter: str, rev: str, tries: int = 10, wait_s: int = 60) -> list[str]:
    """读者侧冒烟：线上单 rev 是新的、单上引用的每张图都取得到（CDN 刚清，旧单可能还要一会儿才换掉）。返回问题列表。

    最多等约 10 分钟：册006 r5（10-24）发布跑完后新图 403 了 3 分钟以上，过一会儿全是 200（CDN 生效慢）。"""
    import time
    for i in range(tries):
        bad = []
        try:
            _, body = _http(f"{DATA}/proof/{text_id}/{chapter}.pending.json")
            doc = json.loads(body)
        except Exception as e:  # noqa: BLE001
            doc, bad = {}, [f"取不到线上单：{e}"]
        if doc and doc.get("rev") != rev:
            bad = [f"线上单还是 {doc.get('rev')}，不是 {rev}"]
        elif doc:
            for name in sorted(sprite_pub.refs(doc)):
                try:
                    code, _ = _http(f"{DATA}/proof/{text_id}/{chapter}/{name}", method="HEAD")
                except Exception as e:  # noqa: BLE001
                    code = str(e)
                if code != 200:
                    bad.append(f"{name} → {code}")
        if not bad:
            return []
        if i < tries - 1:
            time.sleep(wait_s)
    return bad


def cmd_issue(a) -> int:
    """一条命令出单（M10 复盘第 3 项）：出单（有 --pack 走 from-pack）→ 两道门 → 传图、写单、台账 → 存出单版包 → 推库
    → 只发这一章 → 等网站发布跑完 → 读者侧冒烟。相似字图（alt-<章>.webp）由 prep 的 alt_build＋sprite_pub.attach
    自动登记进 sprites[]，出单门再核一遍。复审格用 --recheck（cellvotes draft 的 recheck.tsv 直接给）。"""
    import datetime as dt
    ws, book = Path(a.workspace).resolve(), a.book
    chapter, text_id = a.chapter or chapter_of(book), a.text_id or text_id_of(ws)
    rc = cmd_from_pack(a) if a.label else cmd_prep(a)
    if rc:
        return rc
    online = proofing_path(ws, text_id, chapter)
    old = json.loads(online.read_text(encoding="utf-8")) if online.exists() else None
    a.rev = a.rev or next_rev((old or {}).get("rev"), chapter)
    out = Path(a.out) if a.out else ws / "reports" / book / "_publish" / a.rev
    d = json.loads((out / "diff.json").read_text(encoding="utf-8"))
    if not d["new"] and not a.allow_empty:
        print(f"ⓘ 新单 {a.rev} 一格都没有：不推（线上单 {d['old_rev']} 照旧）。确要换成空单加 --allow-empty")
        return 0
    a.yes, a.sync = True, True
    a.publish_only = f"{text_id}/{chapter}"
    since = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rc = cmd_push(a)
    if rc or a.no_publish_web or a.no_wait:
        return rc
    concl = wait_publish(since)
    if concl != "success":
        print(f"✗ 网站发布没成（{concl or '等超时'}）：单子已在中心库，每日定时兜底；看上面的 run 链接")
        return 1
    bad = smoke(text_id, chapter, a.rev)
    if bad:
        print(f"✗ 读者侧冒烟不过（{len(bad)} 处）：" + "；".join(bad[:10]))
        return 2          # 单子已推、网站已发：调用方据此继续开文本 PR，冒烟另查
    print(f"✓ {a.rev} 已上线：{d['new']} 格，单子和 {len(sprite_pub.refs(json.loads(online.read_text(encoding='utf-8'))))} 张图都取得到"
          f"（https://www.openguji.com/proofing/{text_id}/{chapter}）")
    return 0


def bind_check(products: Path, book: str) -> dict:
    """定字人裁按锚框绑到现行切分（同 seed_admit 回放），看合并有没有冲突。

    - `newer`：包跑完之后才来的人裁（产物里还没有），出单时 pending_route 按格号扣；
    - `id_mismatch`：原格号还在待审里、但这条人裁绑到了别的格或绑不上——按格号扣会扣错，要人看；
    - `unbound`：绑不上（review／void），这些格会以失效老裁决再出卡。"""
    sys.path.insert(0, str(CV))
    import datetime as dt
    from collections import defaultdict
    from open_guji_cv.exp.rough_bench import _NoCache, _split_key
    from open_guji_cv.feedback.bindings import compute_page
    from open_guji_cv.feedback.events import EventLog, counts_as_human, iter_events_readonly
    from open_guji_cv.products.store import ProductStore
    sys.path.insert(0, str(HERE))
    from pending_route import deciding

    ran: dict[int, float] = {}
    mf = products / book / "seed_admit" / "_manifest.jsonl"
    for line in (mf.read_text(encoding="utf-8").splitlines() if mf.exists() else []):
        r = json.loads(line)
        pg = int(re.sub(r"\D", "", r["key"]))
        ran[pg] = max(ran.get(pg, 0), r.get("ts") or 0)
    states = {f"{book}:{k}": v[0] for k, v in cell_states(products, book).items()}
    by_page: dict[int, list] = defaultdict(list)
    for e in sorted(iter_events_readonly(EventLog()), key=lambda e: (e.ts, e.batch, e.seq)):
        if e.kind != "confirm" or e.target.unit != "cell" or not counts_as_human(e):
            continue
        if not deciding({"kind": e.kind, "payload": e.payload or {}}):
            continue
        try:
            b, pg, *_ = _split_key(e.target.key)
        except ValueError:
            continue
        if b == book:
            by_page[pg].append(e)
    st = ProductStore(products)
    out = {"events": 0, "status": Counter(), "newer": [], "id_mismatch": [], "unbound": [], "decided_not_admitted": []}
    for pg, evs in sorted(by_page.items()):
        ev = {e.id: e for e in evs}
        for row in compute_page(book, pg, evs, store=st, cache=_NoCache(), backfill={}):
            e = ev[row["event"]]
            out["events"] += 1
            out["status"][row["status"]] += 1
            bound = row.get("bound") if row["status"] in ("valid", "rebound") else None
            key = e.target.key
            ts = dt.datetime.fromisoformat(e.ts.replace("Z", "+00:00")).timestamp()
            if ts > ran.get(pg, 0):
                out["newer"].append(key)
            if not bound:
                out["unbound"].append(key)
            if states.get(key) == "review" and bound != key:
                out["id_mismatch"].append(key)
            elif bound and states.get(bound) == "review" and ts <= ran.get(pg, 0):
                out["decided_not_admitted"].append(bound)
    out["status"] = dict(out["status"])
    return out


def bind_md(b: dict) -> list[str]:
    s = b["status"]
    lines = ["", "## 人裁合并", "",
             f"- 定字人裁 {b['events']} 条，按锚框绑到新切分：" + "、".join(f"{k} {v}" for k, v in sorted(s.items())),
             f"- 包跑完之后才来的 {len(b['newer'])} 条（按格号扣）；原格号上有人裁、但人裁绑到别处或绑不上的 {len(b['id_mismatch'])} 格不扣，照旧留在单上"
             + ("：" + "、".join(f"`{k}`" for k in b["id_mismatch"][:20]) if b["id_mismatch"] else "")]
    if b["unbound"]:
        lines.append(f"- 绑不上的 {len(b['unbound'])} 条（以失效老裁决再出卡）：" + "、".join(f"`{k}`" for k in b["unbound"][:20]))
    if b["decided_not_admitted"]:
        lines.append(f"- 人裁过、产物里机器还没放行的 {len(b['decided_not_admitted'])} 格（不上单，文本里是机器读法）："
                     + "、".join(f"`{k}`" for k in b["decided_not_admitted"][:20]))
    return lines


def book_text_dir(repo: Path, text_id: str) -> Path:
    hit = sorted(Path(repo).glob(f"Book/*/*/*/{text_id}/default"))
    if not hit:
        sys.exit(f"✗ {repo} 里没有 Book/…/{text_id}/default")
    return hit[0]


def online_text_version(repo: Path, text_id: str, chapter: str) -> str:
    idx = json.loads((book_text_dir(repo, text_id) / "index.json").read_text(encoding="utf-8"))
    for c in idx.get("chapters", []):
        if str(c.get("file")) == chapter or f"{c.get('n', 0):03d}" == chapter:
            if c.get("text_version"):
                return c["text_version"]
    sys.exit(f"✗ book-text index.json 里 {chapter} 没有 text_version（首次入库用 --text-version 0.1.0）")


def pack_manifest(products: Path, book: str) -> dict:
    """seed_admit 末行清单（cv_commit／cv_version／db_rev）。"""
    mf = products / book / "seed_admit" / "_manifest.jsonl"
    lines = mf.read_text(encoding="utf-8").splitlines() if mf.exists() else []
    return json.loads(lines[-1]) if lines else {}


def cmd_from_pack(a) -> int:
    """取别人跑好的产物包直接出单：拉库 → 取包 → 核人裁绑定 → 导出 → prep。不重跑任何 Step。"""
    ws, book = Path(a.workspace).resolve(), a.book
    chapter, text_id = a.chapter or chapter_of(book), a.text_id or text_id_of(ws)
    if not os.environ.get("GUJI_PRODUCTS_DIR"):
        sys.exit("✗ 先设沙箱 GUJI_PRODUCTS_DIR：取包会整册覆盖 <产物根>/<册>，不碰正式 products/")
    products = products_root(ws)
    os.environ["GUJI_WORKSPACE"] = str(ws)        # bind_check 在本进程读人裁（EventLog 只认环境变量）
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    py = sys.executable
    guji = [py, "-m", "open_guji_cv.cli_v2"]
    if not a.no_pull and run([*guji, "db", "pull", "-w", ws], cwd=CV, env=env).returncode:
        return 1
    if (products / book).exists():
        shutil.rmtree(products / book)
    if run([*guji, "products", "pack", "fetch", book, "--label", a.label, "--to", products, "-w", ws],
           cwd=CV, env=env).returncode:
        return 1
    tv = a.text_version or (online_text_version(Path(a.book_text), text_id, chapter) if a.book_text else None)
    if not tv:
        sys.exit("✗ 要 --book-text <book-text 仓>（读线上文本版本）或 --text-version")
    export = (Path(a.out_root) if a.out_root else ws / "reports" / book / "_publish") / f"export-{a.label}"
    cmd = [py, CV / "scripts/export_guji_format.py", "--products", products, "--book", book, "--chapter", chapter,
           "--out", export, "--format", "char-cord", "--keys", "cv", "--text-version", tv]
    for flag, f in (("--meta", CV / f"doc/formats/samples/guji_format_v0.1/meta_{book}.json"),
                    ("--split-table", CV / "doc/formats/samples/guji_page_v0.2/split_table_siku.json")):
        if f.exists():
            cmd += [flag, f]
    if run(cmd, cwd=CV, env=env).returncode:
        return 1
    b = bind_check(products, book)
    print(f"人裁绑定：{b['events']} 条 {b['status']}；包后新到 {len(b['newer'])}、按格号会扣错 {len(b['id_mismatch'])}")
    a.export_dir = str(export)
    man = pack_manifest(products, book)            # 单子头记包的 cv 版本，不是本机的
    a.cv_commit = a.cv_commit or man.get("cv_commit")
    a.cv_version = a.cv_version or man.get("cv_version")
    rc = cmd_prep(a, bind=b, pack=a.label)
    if rc == 0 and b["id_mismatch"]:
        print(f"ⓘ {len(b['id_mismatch'])} 格人裁绑到了别的格或绑不上，照旧留在单上（差异单「人裁合并」一节）")
    return rc


def cmd_add_alt(a) -> int:
    """线上单原地补相似字：不换 rev、不动格子，只给缺 `alt` 的格挂上（网站已投的票照旧有效）。

    给出单时漏了相似字的单子补救用（10-21 殿本 vol04–10）。卡片取 `guji audit alt` 的输出，
    必须是出这张单的那个产物包算的（格号要对得上）；对不上的格不补，打出来。
    相似字字形图（`alt[].g`）不补：网站没有字形图时直接显示文字。"""
    sys.path.insert(0, str(CV))
    from open_guji_cv.review.proof_fields import pending_fields
    ws, book = Path(a.workspace).resolve(), a.book
    chapter, text_id = a.chapter or chapter_of(book), a.text_id or text_id_of(ws)
    online = proofing_path(ws, text_id, chapter)
    doc = json.loads(online.read_text(encoding="utf-8"))
    src = Path(a.cards) if a.cards else ws / "reports" / book / f"{book}.cards.alt.json"
    raw = json.loads(src.read_text(encoding="utf-8"))
    alt = {}
    for c in (raw["cards"] if isinstance(raw, dict) else raw):
        if c.get("alt") and ":" in str(c.get("id")):
            alt[c["id"].split(":", 1)[1]] = pending_fields({"alt": c["alt"]})["alt"]
    cells = doc.get("cells") or []
    todo = [c for c in cells if c.get("review") != "human" and (a.replace or not c.get("alt"))]
    miss = [c["cell"] for c in todo if c["cell"] not in alt]
    changed = []
    for c in todo:
        if c["cell"] in alt:
            old = [x.get("c") for x in c.get("alt") or []]
            if old != [x["c"] for x in alt[c["cell"]]]:
                changed.append(c["cell"])
            c["alt"] = alt[c["cell"]]
    n = len(todo) - len(miss)
    print(f"{book} {doc.get('rev')}：{'重算' if a.replace else '缺相似字'} {len(todo)} 格，补上 {n} 格，相似字有变的 {len(changed)} 格"
          + (f"（{' '.join(changed[:20])}）" if a.replace and changed else "")
          + (f"；卡片里没有的 {len(miss)} 格：{' '.join(miss[:20])}" if miss else ""))
    out = Path(a.out) if a.out else ws / "reports" / book / "_publish" / f"{doc.get('rev')}-alt"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{chapter}.pending.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    if not a.yes:
        print(f"补好的单 → {out / f'{chapter}.pending.json'}；确认后加 --yes 写回数据目录")
        return 0
    sprites_gate(doc, a)
    shutil.copyfile(online, out / f"online.{doc.get('rev')}.pending.json")
    shutil.copyfile(out / f"{chapter}.pending.json", online)
    print(f"已写回 {online}")
    if a.sync:
        sync_and_publish(a, ws)
    else:
        print(f"还要：guji db sync -w {ws}；加 --sync 会顺带触发网站 proofing-sync（publish）")
    return 0


def book_text_to_dev(repo: Path) -> None:
    """book-text 切到最新的 dev（2026-10-24 起流程化小改直接提交 dev，每天合一次 main）。工作区要干净。

    显式 refspec：单分支克隆里 `git fetch origin dev` 不更新 origin/dev。"""
    if run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo).stdout.strip():
        sys.exit(f"✗ book-text（{repo}）工作区有未提交的改动，先处理")
    for cmd in (["git", "fetch", "-q", "origin", "+refs/heads/dev:refs/remotes/origin/dev"],
                ["git", "checkout", "-q", "-B", "dev", "origin/dev"]):
        if run(cmd, cwd=repo).returncode:
            sys.exit(f"✗ book-text 切 dev 失败：{' '.join(cmd)}")


def push_book_text_dev(repo: Path, tries: int = 4) -> bool:
    """推 dev；别的会话先推了就 rebase 再推（改的是各自的册，一般不冲突）。"""
    for _ in range(tries):
        if run(["git", "push", "-q", "origin", "HEAD:refs/heads/dev"], cwd=repo).returncode == 0:
            return True
        if run(["git", "pull", "-q", "--rebase", "origin", "dev"], cwd=repo).returncode:
            run(["git", "rebase", "--abort"], cwd=repo)
            return False
    return False


def bump_book_text(repo: Path, plan: dict, note: str) -> None:
    """同一次导出的 char／cord／norm 拷进 book-text 的 dev、文本线升 minor、本地校验（--dev），提交并推 dev。

    2026-10-24 用户定：流程化小改直接提交 dev，不开 PR；`index/texts` 不在 dev 上提交，CHANGES 的 PR 列写 #TBD，
    每日合并（book-text `scripts/daily_merge.py`）时重建索引、换成当天合并 PR 的号。"""
    book_text_to_dev(repo)
    d = book_text_dir(repo, plan["text_id"])
    ch = plan["chapter"]
    for t in ("char", "cord", "norm"):
        src = Path(plan["export_dir"]) / f"{ch}.{t}.json"
        if src.exists():
            shutil.copyfile(src, d / f"{ch}.{t}.json")
    for cmd in ([sys.executable, "scripts/book-text/bump_original.py", d, "--line", "text", "--level", "minor",
                 "--chapter", ch, "--note", note, "--pr", "TBD"],
                [sys.executable, "scripts/local_check.py", "--dev"],
                ["git", "add", "-A", str(d)],
                ["git", "commit", "-qm", f"{note}"]):
        if run(cmd, cwd=repo).returncode:
            sys.exit(f"✗ book-text 这步失败：{' '.join(map(str, cmd))}")
    if not push_book_text_dev(repo):
        sys.exit("✗ book-text 推 dev 失败（rebase 冲突或网络）：提交在本地 dev 上，处理后 git push origin HEAD:dev")
    print("book-text 已提交并推到 dev：每日合并（洛杉矶 03:30）进 main，CHANGES 的 #TBD 届时换成 PR 号")


def _img_key(img):
    """核坐标用：线上单的 `s` 可能已是哈希名（`p0001.<sha8>.webp`），重建出来是 `p0001.webp`，比之前去掉哈希。"""
    if not img:
        return None
    return {**img, "s": sprite_pub.unhashed(img["s"])} if isinstance(img.get("s"), str) else img


def cmd_add_sprites(a) -> int:
    """线上单的雪碧图没上 R2（GUJI-675 之前出的单）：重建、核坐标不变、传 R2、原地补 `sprites[]` 并把 `img.s` 换成哈希名。

    重建用 `sprite_build.py` 在线上单上跑一遍（同一份 cord、同一批原图、同一个格序，坐标应当逐格相同）；
    只要有一格 `img` 的坐标对不上就整个不动，打出对不上的格——说明手上的 cord／原图不是出这张单时的那份。
    单子上有相似字（`alt`）的，同一目录再跑 `alt_build.py` 重出相似字字形图，一起登记进 `sprites[]`
    （册 004–007 的 `alt-<章>.webp` 就是漏了这一步才 404）。已有 `sprites[]` 但还缺图的单子也走这里重建。"""
    ws, book = Path(a.workspace).resolve(), a.book
    chapter, text_id = a.chapter or chapter_of(book), a.text_id or text_id_of(ws)
    online = proofing_path(ws, text_id, chapter)
    doc = json.loads(online.read_text(encoding="utf-8"))
    if doc.get("sprites") and not sprite_pub.missing(doc):
        print(f"{book} {doc.get('rev')}：单子已有 sprites[] {len(doc['sprites'])} 张，引用的图都登记了，不用补")
        return 0
    cord = Path(a.export_dir) / f"{chapter}.cord.json"
    rd = raw_dir(ws, book)
    if not cord.exists() or not rd:
        sys.exit(f"✗ 要有 {cord} 和原图目录（{ws}/data_full/*/{book}）")
    out = Path(a.out) if a.out else ws / "reports" / book / "_publish" / f"{doc.get('rev')}-sprites"
    out.mkdir(parents=True, exist_ok=True)
    src = out / "online.pending.json"
    src.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    sp = out / "sprites"
    if run([sys.executable, HERE / "sprite_build.py", "--cord", cord, "--pending", src, "--raw-dir", rd,
            "--book", text_id, "--vol", chapter[-2:], "--out", sp]).returncode:
        return 1
    rebuilt = {c["cell"]: c.get("img") for c in json.loads((sp / "pending.with-img.json").read_text(encoding="utf-8"))["cells"]}
    bad = [c["cell"] for c in doc["cells"] if _img_key(c.get("img")) != _img_key(rebuilt.get(c["cell"]))]
    if bad:
        sys.exit(f"✗ {len(bad)} 格重建出的 img 坐标和线上单不一样（{' '.join(bad[:20])}）：手上的 cord／原图不是出这张单时的那份，不动")
    base = json.loads((sp / "pending.with-img.json").read_text(encoding="utf-8"))
    if any(c.get("alt") for c in base.get("cells") or ()):
        if run([sys.executable, HERE / "alt_build.py", "--pending", sp / "pending.with-img.json", "--chapter", chapter,
                "--out", sp]).returncode:
            return 1
        base = json.loads((sp / "pending.with-alt.json").read_text(encoding="utf-8"))
    base.pop("sprites", None)
    new, entries = sprite_pub.attach(base, sp)
    sprites_gate(new, a)
    (out / f"{chapter}.pending.json").write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    print(f"{book} {doc.get('rev')}：{len(doc['cells'])} 格的坐标全部一致，雪碧图 {len(entries)} 张，"
          f"{sum(e['bytes'] for e in entries) / 1e6:.1f} MB；补好的单 → {out / f'{chapter}.pending.json'}")
    if not a.yes:
        print("确认后加 --yes：传 R2、写回数据目录")
        return 0
    stats = sprite_pub.upload(entries, sp / "pub")
    print(f"雪碧图 → R2：{stats}")
    shutil.copyfile(online, out / f"online.{doc.get('rev')}.pending.json.bak")
    shutil.copyfile(out / f"{chapter}.pending.json", online)
    print(f"已写回 {online}")
    if a.sync:
        sync_and_publish(a, ws)
    else:
        print(f"还要：guji db sync -w {ws}；加 --sync 会顺带触发网站 proofing-sync（publish）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("add-alt", help="线上单原地补相似字（不换 rev）")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p.add_argument("--cards", help="guji audit alt 的输出，缺省 <工作区>/reports/<册>/<册>.cards.alt.json")
    p.add_argument("--chapter")
    p.add_argument("--text-id")
    p.add_argument("--out")
    p.add_argument("--replace", action="store_true", help="已有相似字的格也换成这次算的（相似字规则改了之后用）")
    p.add_argument("--yes", action="store_true", help="写回数据目录")
    p.add_argument("--sync", action="store_true", help="写完再 guji db sync 推进中心库")
    p.add_argument("--no-publish-web", action="store_true", help="--sync 后不触发网站 proofing-sync")
    p.add_argument("--ack-missing-sprites", action="store_true", help="单子引用的图没全登记也照推（会 404）")
    p = sp.add_parser("add-sprites", help="线上单补雪碧图（传 R2、写 sprites[]，不换 rev）")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p.add_argument("--export-dir", required=True, help="出这张单时那次导出的 cord 所在目录")
    p.add_argument("--chapter")
    p.add_argument("--text-id")
    p.add_argument("--out")
    p.add_argument("--yes", action="store_true", help="传 R2、写回数据目录")
    p.add_argument("--sync", action="store_true", help="写完再 guji db sync 推进中心库")
    p.add_argument("--no-publish-web", action="store_true", help="--sync 后不触发网站 proofing-sync")
    p.add_argument("--ack-missing-sprites", action="store_true", help="单子引用的图没全登记也照推（会 404）")
    for name in ("prep", "push", "from-pack", "issue"):
        p = sp.add_parser(name)
        p.add_argument("--book", required=True)
        p.add_argument("-w", "--workspace", required=True)
        p.add_argument("--rev", help="新单 rev；prep 缺省按线上单加一（006-r2 → 006-r3）" if name == "prep" else "prep 打出的 rev",
                       required=name == "push")
        p.add_argument("--out", help="出单目录，缺省 <工作区>/reports/<册>/_publish/<rev>")
        if name in ("from-pack", "issue"):
            p.add_argument("--label", required=name == "from-pack",
                           help="产物包标签（guji products pack list <册>）" + ("；issue 给了就走 from-pack，不给就要 --export-dir" if name == "issue" else ""))
            p.add_argument("--book-text", help="book-text 仓：读线上文本版本" + ("；issue 还会拷同一次导出、文本线升 minor、提交到新分支" if name == "issue" else ""))
            p.add_argument("--text-version", help="不给 --book-text 时手给线上文本版本")
            p.add_argument("--no-pull", action="store_true", help="不先 guji db pull")
            p.add_argument("--out-root", help="缺省 <工作区>/reports/<册>/_publish")
        if name in ("prep", "from-pack", "issue"):
            if name in ("prep", "issue"):
                p.add_argument("--export-dir", required=name == "prep", help="同一份产物导出的 char／cord／pages 所在目录")
            p.add_argument("--chapter")
            p.add_argument("--text-id")
            p.add_argument("--cv-commit")
            p.add_argument("--cv-version")
            p.add_argument("--team-pages", help="只给团队的页，如 1-3,150")
            p.add_argument("--page-types", help="{页: 页型} JSON；不是 body 的页进团队单")
            p.add_argument("--no-alt", action="store_true", help="不跑 guji audit alt（单子上没有相似字）")
            p.add_argument("--fetch-zi", action="store_true", help="audit alt 去字统网补缓存（首次慢）")
            p.add_argument("--no-sprite", action="store_true")
            p.add_argument("--recheck", help="复审清单（格号<TAB>说明<TAB>旧人裁 id<TAB>旧人裁的字）：这些格不论放没放行、"
                                             "人裁过没有都放回单上，网站卡片头上显示说明；cellvotes draft 的 recheck.tsv 可直接给")
        if name == "issue":
            p.add_argument("--note", help="book-text CHANGES 一行的说明（给了 --book-text 才升版）")
            p.add_argument("--no-publish-web", action="store_true", help="不触发网站发布")
            p.add_argument("--no-wait", action="store_true", help="触发网站发布后不等、不冒烟")
            p.add_argument("--no-pack", action="store_true", help="不存出单版产物包 rev-<rev>")
            p.add_argument("--allow-empty", action="store_true", help="新单 0 格也换上去")
            p.add_argument("--ack-missing-sprites", action="store_true", help="单子引用的图没全登记也照推（会 404）")
            p.add_argument("--ack-unlanded-votes", metavar="原因", help="旧单上的票没落完也照换（写明原因）")
            p.add_argument("--held-file", help="cellvotes draft 的 held.tsv：里面的格已记为挂起，换单门不拦")
        if name == "push":
            p.add_argument("--yes", action="store_true", help="看过差异单、确认推")
            p.add_argument("--book-text", help="book-text 仓：拷同一次导出、文本线升 minor、提交到新分支")
            p.add_argument("--note", help="book-text CHANGES 一行的说明")
            p.add_argument("--sync", action="store_true", help="写完再 guji db sync 推进中心库，并触发网站 proofing-sync")
            p.add_argument("--no-publish-web", action="store_true", help="--sync 后不触发网站 proofing-sync")
            p.add_argument("--no-pack", action="store_true", help="--sync 时不存出单版产物包 rev-<rev>")
            p.add_argument("--ack-missing-sprites", action="store_true", help="单子引用的图没全登记也照推（会 404）")
            p.add_argument("--ack-unlanded-votes", metavar="原因", help="旧单上的票没落完也照换（写明原因）")
            p.add_argument("--held-file", help="cellvotes draft 的 held.tsv：里面的格已记为挂起，换单门不拦")
    a = ap.parse_args(argv)
    if a.cmd == "issue" and not a.label and not a.export_dir:
        ap.error("issue 要 --label（产物包）或 --export-dir（已导出的 char／cord）")
    return {"prep": cmd_prep, "push": cmd_push, "from-pack": cmd_from_pack, "issue": cmd_issue,
            "add-alt": cmd_add_alt, "add-sprites": cmd_add_sprites}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
