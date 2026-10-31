#!/usr/bin/env python3
"""标 main 之后无人值守重出线上单：对每册判断「要不要重出」→ 能自动就自动跑 proof_cycle plan＋apply。

不经任何人沟通，只看中心库里的三样东西：
  1. 册的 main 产物包（`guji products pack list` 里带 ★ 的那个）和它的时间；
  2. 线上单的 rev，以及这个 rev 的出单版包 `rev-<rev>` 的时间（republish issue 出单时存的）；
  3. 线上单的票（proof_cycle status：cells／voted／idle）。

判定（每册一个结论，见 decide()）：
  fresh      线上单的出单版包比 main 包新或同时 → 不用重出
  waiting    main 比线上单新，但线上单已有票且还没投完 → 等投完（status 的 done）再来；不动票
  go         main 比线上单新，且（零票，或票已投完） → plan＋apply（有票时 plan 先把票落成人裁）
  no-main    册没有 main 包
  no-sheet   册没有线上单（首次出单走 republish issue，不归这里）
  blocked    plan／apply 任一步失败：写进汇总，不重试、不放宽任何门

用法（云端，需 GUJI_DATA_TOKEN／GH_TOKEN／CELLREVIEW_TOKEN，kaiyuanguji-web 的 actions 写权限）：
  python scripts/zhengli/auto_cycle.py --books vol20-vol98 -w $WS --book-text <book-text 仓> [--dry-run] [--only-decide]
结果追加到 <工作区>/reports/_auto_cycle/<日期>.tsv；每册一行：册、结论、旧 rev、新 rev、格数、原因。
全部册跑完后统一触发一次网站发布（proofing-sync，不限 only），等跑完，再对每个新单做读者侧冒烟。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
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


def decide(ws: Path, book: str) -> dict:
    """返回 {verdict, why, main, online_rev, status}。只读。"""
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
    if rev_pack and rev_pack["time"] >= main["time"]:
        return {**base, "verdict": "fresh", "why": f"线上单 {rev} 的出单版包 {rev_pack['time']} 不早于 main 包 {main['time']}"}
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


def run_book(ws: Path, book: str, book_text: Path, d: dict, reviewer: str) -> dict:
    env = {**os.environ, "GUJI_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8"}
    label, rev = d["main"], d["online_rev"]
    man = pc.pack_info(ws, book, label)
    if not man or not man.get("cv_commit"):
        return {"verdict": "blocked", "why": f"main 包 {label} 的 manifest 没有 cv_commit"}
    eng = engine_for(man["cv_commit"])
    # 页表／原图：登记过的册从 R2 取，几秒
    if subprocess.run([*GUJI, "source", "pull", book, "-w", str(ws)], cwd=CV, env=env, capture_output=True).returncode:
        return {"verdict": "blocked", "why": "guji source pull 失败"}
    pl = subprocess.run([sys.executable, HERE / "proof_cycle.py", "plan", "--book", book, "-w", str(ws), "--no-pull",
                         "--pack", label, "--engine", str(eng), "--reviewer", reviewer],
                        cwd=CV, env=env, capture_output=True, text=True)
    plan_path = ws / "reports" / book / "_cycle" / rev / "plan.json"
    if pl.returncode or not plan_path.exists():
        return {"verdict": "blocked", "why": "plan 失败：" + (pl.stdout + pl.stderr).strip()[-300:]}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    sandbox = ws / "_packs" / label
    if not (sandbox / book).is_dir():
        return {"verdict": "blocked", "why": f"plan 之后没有产物沙箱 {sandbox}"}
    ap = subprocess.run([sys.executable, HERE / "proof_cycle.py", "apply", "--book", book, "-w", str(ws),
                         "--plan", str(plan_path), "--hash", plan["hash"], "--book-text", str(book_text),
                         "--reuse-products", str(sandbox), "--no-web"],
                        cwd=CV, env=env, capture_output=True, text=True)
    log = plan_path.parent / "执行记录.md"
    if ap.returncode:
        return {"verdict": "blocked", "why": f"apply 失败（退出码 {ap.returncode}）：" + (ap.stdout + ap.stderr).strip()[-300:],
                "log": str(log)}
    new_rev = rp.next_rev(rev, rp.chapter_of(book))
    return {"verdict": "done", "why": f"写人裁 {plan['ready']} 条，挂起 {plan['held']}", "new_rev": new_rev, "log": str(log)}


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
    a = ap.parse_args(argv)
    ws = Path(a.workspace).resolve()
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    outdir = ws / "reports" / "_auto_cycle"
    outdir.mkdir(parents=True, exist_ok=True)
    tsv = outdir / f"{day}.tsv"
    done: list[tuple[str, str]] = []
    rows: dict[str, dict] = {}
    for book in parse_books(a.books):
        d = decide(ws, book)
        print(f"{book}\t{d['verdict']}\t{d['why']}", flush=True)
        if d["verdict"] == "go" and not (a.only_decide or a.dry_run) and (not a.max or len(done) < a.max):
            d = {**d, **run_book(ws, book, Path(a.book_text), d, a.reviewer)}
            print(f"{book}\t→ {d['verdict']}\t{d['why']}", flush=True)
            if d["verdict"] == "done":
                done.append((book, d["new_rev"]))
        rows[book] = d
        with tsv.open("a", encoding="utf-8") as f:
            f.write("\t".join([book, d["verdict"], str(d.get("online_rev", "")), str(d.get("new_rev", "")),
                               str(d["why"]).replace("\t", " ").replace("\n", " ")[:300]]) + "\n")
    if done and not a.no_publish:
        res = publish_all(done, rp.text_id_of(ws))
        for b, s in res.items():
            print(f"{b}\t发布/冒烟\t{s}", flush=True)
            with tsv.open("a", encoding="utf-8") as f:
                f.write(f"{b}\t发布冒烟\t\t\t{s}\n")
    return 1 if any(r["verdict"] == "blocked" for r in rows.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
