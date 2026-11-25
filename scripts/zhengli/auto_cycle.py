#!/usr/bin/env python3
"""标 main 之后无人值守重出线上单：对每册判断「要不要重出」→ 能自动就自动跑 proof_cycle plan＋apply。

不经任何人沟通，只看中心库里的三样东西：
  1. 册的 main 产物包（`guji products pack list` 里带 ★ 的那个）和它的时间；
  2. 线上单的 rev，以及这个 rev 的出单版包 `rev-<rev>` 的时间（republish issue 出单时存的）；
  3. 线上单的票（proof_cycle status：cells／voted／idle）。

判定（每册一个结论，见 decide()）：
  fresh      线上单的出单版包比 main 包新或同时 → 不用重出
  waiting    main 比线上单新，但线上单已有票且还没投完 → 等投完（status 的 done）再来；不动票
  go         main 比线上单新，且（零票，或票已投完，或加 --land-votes） → plan＋apply（有票时 plan 先把票落成人裁）
  no-main    册没有 main 包
  no-sheet   册没有线上单（首次出单走 republish issue，不归这里）
  blocked    plan／apply 任一步失败：写进汇总，不重试、不放宽任何门

用法（云端，需 GUJI_DATA_TOKEN／GH_TOKEN／CELLREVIEW_TOKEN，kaiyuanguji-web 的 actions 写权限）：
  python scripts/zhengli/auto_cycle.py --books vol20-vol98 -w $WS --book-text <book-text 仓> [--dry-run] [--only-decide]
结果追加到 <工作区>/reports/_auto_cycle/<日期>.tsv；每册一行：册、结论、旧 rev、新 rev、格数、原因。
全部册跑完后统一触发一次网站发布（proofing-sync，不限 only），等跑完，再对每个新单做读者侧冒烟。

断点续跑（A31 11-18，ZM 换单提速第 4–6 项）：
  * 状态写 <工作区>/reports/_auto_cycle/state.json（--state 可改）：每册结论、main 标签、新 rev、发布冒烟结果。
    同一条命令再跑：已 done 的册不再动；guard-stop／blocked 的册缺省跳过（--retry-blocked 重试）；
    上次跑到一半被杀（状态 running）的册先清 book-text 未提交改动和本册沙箱再重做。
  * --max-minutes N：到时不再开新册（后台命令 2 小时上限时给 100 左右），状态留着，同一条命令接着跑。
  * 网站只在「这次给的册全都有了结论」时统一发一次，发的是历次 done 而还没发布冒烟过的册；--publish-now 不等。
  * 每册沙箱只清本册（<工作区>/_packs/<标签>/<册>）：同标签各册共用 _packs/<标签>，以前清整个目录会删掉别的册的产物
    （vol43 吃过亏）。每册开跑前查盘：剩余空间不足 GUJI_CYCLE_MIN_FREE_GB（缺省 8）就停在这册之前；
    同一工作区同时只许一个 auto_cycle（reports/_auto_cycle/.lock）。
  * 守卫拦下（guard-stop）的册自动出「待重挂锚点清单」：reports/_auto_cycle/待重挂-<日期>.md（汇总，含修好后的补落命令）
    和 reports/<册>/_cycle/<rev>/待重挂锚点.tsv；修好后 `--resume-guard` 对这些册跑 `guji swap book-text --push --sheet`，
    推好的册算 done，最后随其它册一起发站冒烟。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CV = HERE.parents[1]
sys.path.insert(0, str(HERE))
import republish as rp  # noqa: E402
import proof_cycle as pc  # noqa: E402

GUJI = [sys.executable, "-m", "open_guji_cv.cli_v2"]
ENGINES = Path(os.environ.get("GUJI_ENGINES_DIR") or Path.home() / ".guji-engines")


def parse_books(spec: str) -> list[str]:
    out: list[str] = []
    for part in spec.split(","):
        m = re.fullmatch(r"vol(\d+)-vol(\d+)", part.strip())
        if m:
            out += [f"vol{i:02d}" for i in range(int(m[1]), int(m[2]) + 1)]
        elif part.strip():
            out.append(part.strip())
    return out


def pack_rows(ws: Path, book: str) -> list[dict]:
    """`guji products pack list <册>` → [{label, main, time, note}]，按列表顺序（时间升序）。"""
    p = subprocess.run([*GUJI, "products", "pack", "list", book, "-w", str(ws)], capture_output=True, text=True,
                       env={**os.environ, "GUJI_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8"}, cwd=CV)
    rows = []
    for ln in p.stdout.splitlines():
        f = ln.split("\t")
        if len(f) < 3 or "products/" not in f[0]:
            continue
        main = f[0].lstrip().startswith("★")
        label = f[0].replace("★", "").strip().split(f"/{book}/", 1)[-1]
        rows.append({"label": label, "main": main, "time": f[2], "note": f[-1] if len(f) > 4 else ""})
    return rows


def main_changed(ws: Path, book: str, prev: dict) -> bool:
    """状态文件按「册＋主包」算：上次 done 记的 main 与现在的 ★main 不同，就是新任务、要重做
    （全唐文 11-20 d2：d1 做完的 29 册被判「已做」跳过，线上仍是旧单）。没记 main 的旧状态、读不到现行 main 的，照旧跳过。"""
    was = prev.get("main")
    if not was:
        return False
    now = next((r["label"] for r in pack_rows(ws, book) if r["main"]), None)
    if now and now != was:
        print(f"{book}\t主包 {was} → {now}：状态文件里的「已做」作废，重做", flush=True)
        return True
    return False


#: manager `guji pipeline` 收尾（land --apply）落定时写：{digest, pack}（GM4 换包按条目对账，11-24）
LANDED = "_land/landed.json"


def landed_pack(ws: Path, book: str) -> str | None:
    """收尾按哪个产物包落定了待审条目（`reports/<册>/_land/landed.json` 的 pack）；没有、读不了 → None。"""
    try:
        return json.loads((Path(ws) / "reports" / book / LANDED).read_text(encoding="utf-8")).get("pack") or None
    except (OSError, ValueError, AttributeError):
        return None


def decide(ws: Path, book: str, land_votes: bool = False) -> dict:
    """返回 {verdict, why, main, online_rev, status}。只读。
    land_votes：线上单有票但没投完时不等，判 go，由 plan 把票落成人裁（落不了的由 apply 的票账门拦下，不丢票）。"""
    text_id, chapter = rp.text_id_of(ws), rp.chapter_of(book)
    online = rp.proofing_path(ws, text_id, chapter)
    if not online.exists():
        return {"verdict": "no-sheet", "why": "数据目录没有线上单"}
    rev = json.loads(online.read_text(encoding="utf-8")).get("rev")
    rows = pack_rows(ws, book)
    main = next((r for r in rows if r["main"]), None)
    if not main:
        return {"verdict": "no-main", "why": "册没有 main 产物包", "online_rev": rev}
    rev_pack = next((r for r in rows if r["label"] == rp.pack_label(rev)), None)
    base = {"online_rev": rev, "main": main["label"], "main_time": main["time"]}
    landed = landed_pack(ws, book)
    if landed and landed == main["label"]:      # 收尾已按这个 main 包对账落定（待审没变就不换 rev、不出 rev-<rev> 包）
        return {**base, "verdict": "fresh", "why": f"已按 main 包 {landed} 对账落定（{LANDED}），线上单 {rev}"}
    # 包的时间是它跑完存库的时间，不是标 main 的时间（r5 先存、后标 main 的情形会反过来），所以不比时间：
    # 出单版包的备注记了「基于 main 包 <标签>」，与现在的 ★main 标签相同才算新；备注里没有（旧单）一律当过期。
    m = re.search(r"基于 main 包 (\S+)", (rev_pack or {}).get("note", ""))
    if m and m.group(1) == main["label"]:
        return {**base, "verdict": "fresh", "why": f"线上单 {rev} 就是基于现在的 main 包出的"}
    st = None
    for _ in range(4):                       # 网站 KV 偶发连接被重置，隔几秒重试
        p = subprocess.run([sys.executable, HERE / "proof_cycle.py", "status", "--book", book, "-w", str(ws)],
                           capture_output=True, text=True, env={**os.environ, "GUJI_WORKSPACE": str(ws)}, cwd=CV)
        try:
            st = json.loads(p.stdout.strip().splitlines()[-1])
            break
        except Exception:  # noqa: BLE001
            time.sleep(5)
    if st is None:
        return {**base, "verdict": "blocked", "why": "status 读不出：" + (p.stdout + p.stderr).strip()[-200:]}
    base["status"] = st
    if st["voted"] == 0 or st["done"]:
        return {**base, "verdict": "go", "why": "零票" if st["voted"] == 0 else "票已投完"}
    if land_votes:
        return {**base, "verdict": "go", "why": f"线上单 {st['cells']} 格已投 {st['voted']}：先落票再换单"}
    return {**base, "verdict": "waiting", "why": f"线上单 {st['cells']} 格已投 {st['voted']}，还没投完"}


def engine_for(cv_commit: str) -> Path:
    """出单版 cv 的 worktree：~/.guji-engines/<commit 前 12 位>，没有就从本仓 add（缺提交先 fetch dev）。"""
    d = ENGINES / cv_commit[:12]
    if (d / ".git").exists():
        return d
    ENGINES.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["git", "cat-file", "-e", cv_commit + "^{commit}"], cwd=CV).returncode:
        subprocess.run(["git", "fetch", "-q", "--depth=500", "origin", "dev"], cwd=CV, check=False)
    r = subprocess.run(["git", "worktree", "add", "-f", str(d), cv_commit], cwd=CV, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"取不到引擎提交 {cv_commit[:9]}：{r.stderr.strip()[-200:]}")
    return d


TRANSIENT = ("Connection reset", "HTTP Error 5", "timed out", "Temporary failure", "RemoteDisconnected")


def sh(cmd, tries: int = 3, **kw) -> subprocess.CompletedProcess:
    """跑命令；输出里是网络瞬时错误（连接被重置、5xx）才重试，其余失败原样返回。"""
    for i in range(tries):
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
        if r.returncode == 0 or not any(t in (r.stdout + r.stderr) for t in TRANSIENT):
            return r
        time.sleep(10 * (i + 1))
    return r


def fail_reason(out: str, tail: int = 300) -> str:
    """失败输出里取真原因：最后一条以 ✗ 开头的行（连同它后面的几行）；没有就取末尾。以前取末尾 300 字，
    常是前面的提示行（殿本 vol02、vol16 的 why 抄成了「vol89 … 页表 rev 不符」，真原因单子体检在后面，ZM 11-17）。"""
    lines = out.strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].lstrip().startswith("✗"):
            return " ".join(x.strip() for x in lines[i:i + 4])[:tail]
    return out.strip()[-tail:]


PACK_MARK = ".pack.json"        # guji_manager.datastore.packs.MARK：取包核过 sha、解完才写
MIN_FREE_GB = float(os.environ.get("GUJI_CYCLE_MIN_FREE_GB") or 8)   # 一册沙箱 0.3–5.6GB，外加导出与 db sync
SKIP_DONE = ("done",)
SKIP_STOPPED = ("guard-stop", "blocked")


CELLS_DIRS = ("ai-team/domain/CV/图源迁移/siku-qiefen-v2/results/old_new_cells",)


def default_cells(book: str, given: str = "") -> str:
    """--cells 没给时找格级对照表目录（ZM 换单提速第 1 项：旧单出在换图源之前，票按表对新格）：
    GUJI_OLD_NEW_CELLS，或 ~/ai-team、/home/user/ai-team 下的 siku-qiefen-v2 对照表。只在目录里有本册的表时才用；
    只有旧单真出在换图源之前，republish 换单门才读它，别的册传了也不碍事。"""
    if given:
        return given
    cands = [os.environ.get("GUJI_OLD_NEW_CELLS") or ""]
    for root in (Path.home(), Path("/home/user")):
        cands += [str(root / d) for d in CELLS_DIRS]
    for c in cands:
        if c and any((Path(c) / f"{book}{ext}").exists() for ext in (".tsv.gz", ".tsv")):
            return c
    return ""


def unmapped_votes(ws: Path, book: str, new_rev: str) -> dict | None:
    """换单门写的「旧单票无法对位」清单（不拦，交复审）：{n, tsv}；没有就 None。"""
    f = ws / "reports" / book / "_publish" / new_rev / "旧单票无法对位.tsv"
    if not f.exists():
        return None
    n = sum(1 for ln in f.read_text(encoding="utf-8").splitlines()[1:] if ln.strip())
    return {"n": n, "tsv": str(f)} if n else None


def drop_sandbox(sandbox: Path, book: str) -> None:
    """只清本册的沙箱 <_packs/标签>/<册>；标签目录空了再删。同标签各册共用 _packs/<标签>，整目录删会删掉别的册（vol43）。"""
    shutil.rmtree(sandbox / book, ignore_errors=True)
    try:
        sandbox.rmdir()
    except OSError:
        pass


def free_gb(path: Path) -> float:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free / 2 ** 30


class Lock:
    """同一工作区同时只许一个 auto_cycle：两个进程共用 book-text 检出和 _packs，会互相 checkout／清掉对方的东西。"""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                pid = int(self.path.read_text().split()[0])
                os.kill(pid, 0)
                cmd = Path(f"/proc/{pid}/cmdline")
                if cmd.exists() and b"auto_cycle" not in cmd.read_bytes():
                    pid = None                  # 容器重启后 pid 被别的进程占了：不是 auto_cycle，当死锁
            except (ValueError, IndexError, ProcessLookupError, PermissionError, OSError):
                pid = None
            if pid and pid != os.getpid():
                raise SystemExit(f"✗ 这个工作区已有 auto_cycle 在跑（pid {pid}，{self.path}）；等它跑完，或确认它已死后删掉锁文件")
        self.path.write_text(f"{os.getpid()} {dt.datetime.now(dt.timezone.utc).isoformat()}\n")
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"books": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def keep_untracked(book_text: Path, dest: Path) -> list[str]:
    """book-text 里 Book/ 下未跟踪的文件（待重标清单 NNN.punct-stale.json 等）拷到 dest 留底，返回相对路径。"""
    r = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "Book"], cwd=book_text,
                       capture_output=True, text=True)
    got = []
    for rel in (r.stdout or "").splitlines():
        src = Path(book_text) / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest / rel)
            got.append(rel)
    return got


def clean_book_text(book_text: Path) -> None:
    subprocess.run(["git", "checkout", "--", "."], cwd=book_text)
    subprocess.run(["git", "clean", "-fdq", "--", "Book"], cwd=book_text)


def recover_running(ws: Path, state: dict, book_text: Path) -> list[str]:
    """上次跑到一半被杀（状态还是 running）的册：清 book-text 未提交改动和本册沙箱，状态退回待做。返回这些册。"""
    hit = [b for b, v in state["books"].items() if v.get("verdict") == "running"]
    if hit:
        clean_book_text(book_text)
    for b in hit:
        lab = state["books"][b].get("main")
        if lab:
            drop_sandbox(ws / "_packs" / lab, b)
        state["books"][b] = {**state["books"][b], "verdict": "interrupted", "why": "上次跑到一半被中断，已清 book-text 与本册沙箱，重做"}
    return hit


_GUARD_RE = re.compile(r"✗ book-text[^\n]*这步失败：([^\n]*)")


def guard_list(ws: Path, book: str, cycle_dir: Path, out: str) -> dict:
    """守卫拦下（guard-stop）时出「待重挂锚点清单」：问题原文、留待重挂的锚点（cellmap/left_volNN.tsv）、格级对照表，
    并写 <cycle>/待重挂锚点.tsv。切坏（人裁账不平：受保护的格在新包里没了／落字≠人裁）交切分线，挪不了的标点专名交 A33。"""
    m = list(_GUARD_RE.finditer(out))
    problem = m[-1].group(1).strip() if m else fail_reason(out)
    left_rows: list[str] = []
    header = "层\t条目\t旧锚\t新锚\t内容\t原因码｜说明"
    for f in sorted((cycle_dir / "cellmap").glob("left_vol*.tsv")):
        lines = f.read_text(encoding="utf-8").splitlines()
        if lines:
            header = lines[0]
        left_rows += [ln for ln in lines[1:] if ln.strip()]
    table = next(iter(sorted((cycle_dir / "cellmap").glob("old_new_cells_vol*.tsv"))), None)
    stale = sorted(cycle_dir.glob("export/*.punct-stale.json")) + sorted(cycle_dir.glob("book-text-未提交/**/*.punct-stale.json"))
    out_tsv = cycle_dir / "待重挂锚点.tsv"
    out_tsv.write_text(header + "\n" + "".join(r + "\n" for r in left_rows), encoding="utf-8")
    to = []
    if "人裁账不平" in problem or "框" in problem:
        to.append("切分线（切坏／人裁格在新包里没了）")
    if re.search(r"标点|专名", problem) or left_rows:
        to.append("A33（标点专名锚点挪不了）")
    to = to or ["先看 apply.out"]
    return {"problem": problem[:600], "left": len(left_rows), "left_tsv": str(out_tsv),
            "table": str(table) if table else None, "stale": [str(x) for x in stale],
            "export": str(cycle_dir / "export"), "to": to,
            "summary": f"待重挂锚点 {len(left_rows)} 条（{out_tsv}），交 {'、'.join(to)}"}


def write_guard_report(ws: Path, state: dict, day: str, book_text: Path, text_id: str) -> Path | None:
    rows = {b: v for b, v in state["books"].items() if v.get("verdict") == "guard-stop"}
    um = {b: v["unmapped"] for b, v in state["books"].items() if v.get("verdict") == "done" and v.get("unmapped")}
    if not rows and not um:
        return None
    md = [f"# 待重挂锚点清单（auto_cycle，{day}）"]
    if rows:
        md += ["", "## 守卫拦下的册", "",
               "线上单没换（守卫在推库之前），新单已出在 reports/<册>/_publish/。修好后跑同一条 auto_cycle 加 `--resume-guard`，"
               "或单册：`guji swap book-text --books <册> -w <工作区> --book-text <检出> --text-id <书ID> --push --sheet`。", "",
               "| 册 | 交谁 | 问题 | 留待重挂 | 清单 | 对照表 |", "|---|---|---|---|---|---|"]
    for b, v in sorted(rows.items()):
        g = v.get("guard") or {}
        md.append(f"| {b} | {'、'.join(g.get('to') or [])} | {str(g.get('problem', v.get('why', ''))).replace('|', '／')[:300]} "
                  f"| {g.get('left', '?')} | `{g.get('left_tsv', '')}` | `{g.get('table') or ''}` |")
    if rows:
        md += ["", "补落命令（修好后）：", "", "```",
               f"python scripts/zhengli/auto_cycle.py --books {','.join(sorted(rows))} -w {ws} --book-text {book_text} --resume-guard",
               "```"]
    if um:
        md += ["", "## 旧单票无法对位（换图源前出的旧单，按格级对照表对不到新格；没拦，交复审）", "",
               "| 册 | 格数 | 清单 |", "|---|---|---|"]
        md += [f"| {b} | {u['n']} | `{u['tsv']}` |" for b, u in sorted(um.items())]
    md.append("")
    p = ws / "reports" / "_auto_cycle" / f"待重挂-{day}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(md), encoding="utf-8")
    return p


def resume_guard(ws: Path, book: str, book_text: Path, text_id: str) -> dict:
    """守卫拦下的册修好后：guji swap book-text --push --sheet（按格级对照表重落 book-text、补推已出的新单、db sync）。"""
    env = {**os.environ, "GUJI_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8", "GUJI_DB_NO_GLYPH": "1"}
    r = sh([*GUJI, "swap", "book-text", "--books", book, "-w", str(ws), "--book-text", str(book_text),
            "--text-id", text_id, "--cv", str(CV), "--push", "--sheet"], cwd=CV, env=env)
    out = r.stdout + r.stderr
    try:
        res = json.loads(r.stdout[r.stdout.index("{"):]).get(book, {})
    except (ValueError, AttributeError):
        res = {}
    sheet = str(res.get("sheet", ""))
    if res.get("status") == "pushed" and sheet.startswith("pushed"):
        return {"verdict": "done", "why": f"守卫拦下后补落 book-text 并补推新单（{sheet}）", "new_rev": sheet.split()[1]}
    if res.get("status") == "guard-stop":
        return {"verdict": "guard-stop", "why": "补落仍被守卫拦下：" + str(res.get("why", ""))[:300]}
    return {"verdict": "blocked", "why": f"补落没成（{res.get('status')}，{sheet}）：" + fail_reason(out)}


def run_book(ws: Path, book: str, book_text: Path, d: dict, reviewer: str, ack_unlanded: str = "", cells_dir: str = "") -> dict:
    env = {**os.environ, "GUJI_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8"}
    label, rev = d["main"], d["online_rev"]
    man = pc.pack_info(ws, book, label)
    if not man or not man.get("cv_commit"):
        return {"verdict": "blocked", "why": f"main 包 {label} 的 manifest 没有 cv_commit"}
    eng = engine_for(man["cv_commit"])
    cells_dir = default_cells(book, cells_dir)
    # 页表／原图：登记过的册从 R2 取，几秒
    if sh([*GUJI, "source", "pull", book, "-w", str(ws)], cwd=CV, env=env).returncode:
        return {"verdict": "blocked", "why": "guji source pull 失败"}
    pl = sh([sys.executable, HERE / "proof_cycle.py", "plan", "--book", book, "-w", str(ws), "--no-pull",
             "--pack", label, "--engine", str(eng), "--reviewer", reviewer,
             # 判 go 的理由是零票：plan 照出空计划（draft 当场读网站再核一遍是 0 票，不是就拒）
             *(["--allow-empty"] if (d.get("status") or {}).get("voted") == 0 else [])], cwd=CV, env=env)
    plan_path = ws / "reports" / book / "_cycle" / rev / "plan.json"
    if pl.returncode or not plan_path.exists():
        return {"verdict": "blocked", "why": "plan 失败：" + (pl.stdout + pl.stderr).strip()[-300:]}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    sandbox = ws / "_packs" / label
    if not (sandbox / book).is_dir():
        return {"verdict": "blocked", "why": f"plan 之后没有产物沙箱 {sandbox}"}
    if not (sandbox / book / PACK_MARK).exists():
        # 取包核过 sha、解完才写 .pack.json；没有＝上次解到一半被杀或被别的进程清过，不拿半截产物换单
        drop_sandbox(sandbox, book)
        return {"verdict": "blocked", "why": f"产物沙箱 {sandbox / book} 不完整（没有 {PACK_MARK}），已清；再跑会重新取包"}
    ap = sh([sys.executable, HERE / "proof_cycle.py", "apply", "--book", book, "-w", str(ws),
             "--plan", str(plan_path), "--hash", plan["hash"], "--book-text", str(book_text),
             "--reuse-products", str(sandbox), "--no-web",
             *(["--ack-unlanded-votes", ack_unlanded] if ack_unlanded else []),
             *(["--cells", cells_dir] if cells_dir else [])], cwd=CV, env=env)
    log = plan_path.parent / "执行记录.md"
    out = ap.stdout + ap.stderr
    (plan_path.parent / "apply.out").write_text(out, encoding="utf-8")
    if ap.returncode and re.search(r"book-text.{0,8}这步失败|工作区有未提交的改动", out):
        # book-text 这步没过（格级对照表守卫拦下、或本地检查不过）：线上单还没换（这步在推库之前）；清掉未提交的改动。
        # 切坏的（框对不上）交切分线重出包，切分没错、锚点挪不了的交 A33；修好后 `guji swap book-text --books <册> --push --sheet` 补落文本、补推单
        keep_untracked(book_text, plan_path.parent / "book-text-未提交")   # 待重标清单 punct-stale 等先留底，下面要清
        subprocess.run(["git", "checkout", "--", "."], cwd=book_text)
        subprocess.run(["git", "clean", "-fdq", "--", "Book"], cwd=book_text)      # 待重标清单 NNN.punct-stale.json 是未跟踪文件，不清会混进下一册的提交
        drop_sandbox(sandbox, book)      # 守卫拦下也清沙箱（0.3–5.6GB，不清云端盘会写满）；产物在 reports/<册>/_cycle/<rev>/export，交 A33 用
        gl = guard_list(ws, book, plan_path.parent, out)
        return {"verdict": "guard-stop", "why": "book-text 守卫／本地检查不过，线上单未换；" + gl["summary"]
                + "；修好后 auto_cycle --resume-guard（即 guji swap book-text --push --sheet）",
                "log": str(log), "guard": gl}
    if ap.returncode:
        subprocess.run(["git", "checkout", "--", "."], cwd=book_text)
        drop_sandbox(sandbox, book)
        return {"verdict": "blocked", "why": f"apply 失败（退出码 {ap.returncode}）：" + fail_reason(out),
                "log": str(log)}
    new_rev = rp.next_rev(rev, rp.chapter_of(book))
    drop_sandbox(sandbox, book)       # 云端盘小：沙箱 0.3–5.6GB，用完即清（只清本册）
    um = unmapped_votes(ws, book, new_rev)
    return {"verdict": "done", "why": f"写人裁 {plan['ready']} 条，挂起 {plan['held']}"
            + (f"；旧单票无法对位 {um['n']} 格（交复审，{um['tsv']}）" if um else ""),
            "new_rev": new_rev, "log": str(log), **({"unmapped": um} if um else {})}


def publish_all(books_done: list[tuple[str, str]], text_id: str) -> dict[str, str]:
    """统一发一次网站，等跑完，对每个新单做读者侧冒烟。返回 {册: 问题或 ok}。"""
    since = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = subprocess.run(["gh", "workflow", "run", "proofing-sync.yml", "-R", rp.WEB_REPO, "--ref", "main",
                        "-f", "target=production", "-f", "parts=publish", "-f", "dry_run=false"],
                       capture_output=True, text=True)
    if r.returncode:
        return {b: "网站发布触发失败：" + r.stderr.strip()[-200:] for b, _ in books_done}
    concl = rp.wait_publish(since, timeout_s=3600)
    if concl != "success":
        return {b: f"网站发布 {concl or '等超时'}" for b, _ in books_done}
    out = {}
    for b, rev in books_done:
        bad = rp.smoke(text_id, rp.chapter_of(b), rev)
        out[b] = "ok" if not bad else "冒烟不过：" + "；".join(bad[:3])
    return out


def to_publish(state: dict) -> list[tuple[str, str]]:
    """历次 done 而还没发布冒烟成功的册。"""
    return [(b, v["new_rev"]) for b, v in sorted(state["books"].items())
            if v.get("verdict") == "done" and v.get("new_rev") and v.get("publish") != "ok"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--books", required=True, help="如 vol20-vol98 或 vol23,vol24")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--book-text", required=True)
    ap.add_argument("--reviewer", default="sheldon")
    ap.add_argument("--only-decide", action="store_true", help="只出每册的结论，不动手")
    ap.add_argument("--dry-run", action="store_true", help="同 --only-decide")
    ap.add_argument("--max", type=int, default=0, help="最多重出几册（试跑用）")
    ap.add_argument("--no-publish", action="store_true", help="最后不统一发网站")
    ap.add_argument("--cells", default="", help="旧单出在换图源之前时的格级对照表目录（old_new_cells/，内有 <册>.tsv.gz），透传 apply --cells")
    ap.add_argument("--land-votes", action="store_true",
                    help="线上单有票没投完的册也换：plan 把票落成人裁；落不了（如页图与页表对不上）的由 apply 票账门拦下列出，不丢票")
    ap.add_argument("--ack-unlanded-votes", default="", metavar="原因",
                    help="旧单上的票没落完也照换（写明原因），原样交给 proof_cycle apply → republish issue；swap run 透传")
    ap.add_argument("--state", default="", help="状态文件（缺省 <工作区>/reports/_auto_cycle/state.json）")
    ap.add_argument("--fresh", action="store_true", help="不看旧状态，从头判（旧状态改名留底）")
    ap.add_argument("--retry-blocked", action="store_true", help="上次 guard-stop／blocked 的册也重跑（缺省跳过）")
    ap.add_argument("--resume-guard", action="store_true",
                    help="只处理上次 guard-stop 的册：修好后 guji swap book-text --push --sheet 补落文本、补推新单，成了算 done")
    ap.add_argument("--max-minutes", type=float, default=0,
                    help="跑满这么多分钟就不再开新册（后台命令 2 小时上限，给 100 左右）；同一条命令再跑接着做")
    ap.add_argument("--publish-now", action="store_true", help="还有册没跑完也先把已 done 的发站冒烟")
    a = ap.parse_args(argv)
    from ensure_manager import ensure as _ensure_manager  # 搬去 manager 的命令要它（拆分 P2）
    _ensure_manager()
    ws = Path(a.workspace).resolve()
    book_text = Path(a.book_text).resolve()
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    outdir = ws / "reports" / "_auto_cycle"
    outdir.mkdir(parents=True, exist_ok=True)
    tsv = outdir / f"{day}.tsv"
    sp = Path(a.state) if a.state else outdir / "state.json"
    if a.fresh and sp.exists():
        sp.rename(sp.with_name(f"{sp.stem}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"))
    started = time.monotonic()
    books = parse_books(a.books)
    with Lock(outdir / ".lock"):
        state = load_state(sp)
        state.setdefault("books", {})
        hit = recover_running(ws, state, book_text)
        if hit:
            print(f"上次中断的册已清理、重做：{','.join(hit)}", flush=True)
            save_state(sp, state)
        text_id = rp.text_id_of(ws)
        stopped_early, ran = False, 0
        for book in books:
            prev = state["books"].get(book) or {}
            if a.resume_guard:
                if prev.get("verdict") != "guard-stop":
                    continue
            elif prev.get("verdict") in SKIP_DONE and not main_changed(ws, book, prev):
                print(f"{book}\t→ done\t（状态文件：已做）{prev.get('why', '')}", flush=True)
                continue
            elif prev.get("verdict") in SKIP_STOPPED and not a.retry_blocked:
                print(f"{book}\t→ {prev['verdict']}\t（状态文件：上次拦下，--retry-blocked 重试）{str(prev.get('why', ''))[:200]}", flush=True)
                continue
            if a.max_minutes and (time.monotonic() - started) / 60 >= a.max_minutes:
                print(f"已跑满 {a.max_minutes:g} 分钟，停在 {book} 之前；同一条命令再跑接着做", flush=True)
                stopped_early = True
                break
            if a.resume_guard:
                d = {**prev, **resume_guard(ws, book, book_text, text_id), "at": dt.datetime.now(dt.timezone.utc).isoformat()}
                print(f"{book}\t→ {d['verdict']}\t{d['why']}", flush=True)
            else:
                d = decide(ws, book, a.land_votes)
                print(f"{book}\t{d['verdict']}\t{d['why']}", flush=True)
                if d["verdict"] == "go" and not (a.only_decide or a.dry_run) and (not a.max or ran < a.max):
                    ran += 1
                    gb = free_gb(ws)
                    if gb < MIN_FREE_GB:
                        print(f"✗ 盘只剩 {gb:.1f}GB（要 ≥ {MIN_FREE_GB:g}，GUJI_CYCLE_MIN_FREE_GB 可调）：停在 {book} 之前，"
                              f"先清 {ws / '_packs'}、cache、旧 export", flush=True)
                        stopped_early = True
                        break
                    state["books"][book] = {**d, "verdict": "running", "at": dt.datetime.now(dt.timezone.utc).isoformat()}
                    save_state(sp, state)
                    d = {**d, **run_book(ws, book, book_text, d, a.reviewer, a.ack_unlanded_votes, a.cells)}
                    print(f"{book}\t→ {d['verdict']}\t{d['why']}", flush=True)
                d["at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            if not (a.only_decide or a.dry_run):
                state["books"][book] = d
                save_state(sp, state)
            with tsv.open("a", encoding="utf-8") as f:
                f.write("\t".join([book, d["verdict"], str(d.get("online_rev", "")), str(d.get("new_rev", "")),
                                   str(d["why"]).replace("\t", " ").replace("\n", " ")[:300]]) + "\n")
        rep = write_guard_report(ws, state, day, book_text, text_id)
        if rep:
            print(f"待重挂锚点清单：{rep}", flush=True)
        left = [b for b in books if (state["books"].get(b) or {}).get("verdict") in (None, "running", "interrupted", "go")]
        pending_pub = [x for x in to_publish(state) if x[0] in books]
        if pending_pub and not a.no_publish and not (a.only_decide or a.dry_run):
            if (left or stopped_early) and not a.publish_now:
                print(f"还有 {len(left)} 册没跑完：已换好的 {len(pending_pub)} 册先不发站，跑完再统一发（--publish-now 不等）", flush=True)
            else:
                res = publish_all(pending_pub, text_id)
                for b, s_ in res.items():
                    print(f"{b}\t发布/冒烟\t{s_}", flush=True)
                    state["books"][b]["publish"] = s_
                    with tsv.open("a", encoding="utf-8") as f:
                        f.write(f"{b}\t发布冒烟\t\t\t{s_}\n")
                save_state(sp, state)
    rows = {b: state["books"].get(b) or {} for b in books}
    return 1 if any(r.get("verdict") in ("blocked",) for r in rows.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
