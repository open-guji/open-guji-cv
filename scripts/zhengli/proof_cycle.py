#!/usr/bin/env python3
"""一轮精校：线上单的票 → 人裁事件 → 受影响页重跑 → book-text 升版（dev）→ 新单上线（GUJI-730 P1-2）。

第四、五册这一轮要三四个会话、三次「推库」手工串：落票、重跑、升版、重出单、传图、发网站各做各的。
用户 10-22 定：流程化操作不再逐次批准，靠检查门兜底。本脚本把一轮串成两步，中间只隔一份计划文件：

  plan    只读（不写中心库）：拉库 → 取出单版产物包 rev-<rev>（republish push 存的；没有就退回 --cord）
          → `guji cellvotes draft` 出「可写／挂起／跳过」→ 写 `plan.json`＋`计划.md`（要写几条、批次名、
          哪几页要重跑、包的 cv 版本），计划带哈希。产出在 <工作区>/reports/<册>/_cycle/<rev>/。
  apply   按计划原样执行，任何一处和计划对不上就停（不猜、不放宽）：
          1. 核哈希；草稿文件没变；线上单还是计划时那个 rev
          2. `guji cellvotes write`（锚按出单版产物算）→ `guji db sync`
          3. 本机 cv 必须就是包的 cv_commit（不是就停：混进别版切分，格号又会漂；从该 commit 的 worktree 跑，
             或 --allow-cv-drift 明说照跑）；在沙箱产物根（包解出来的那份）重跑有票的页到 seed_admit
          4. 导出 char／cord（同 republish from-pack）
          5. `republish.py prep` → `push --yes --sync --book-text`：过出单门、换单门，存新单的产物包，
             升 book-text minor 并提交、推到 dev，推库后触发网站 proofing-sync
          6. book-text 升版提交到 dev（不开 PR；每日合并时 CHANGES 的 #TBD 换成当天合并 PR 的号）
          每步结果写进 `执行记录.md`；中途停了可以改正后重跑 apply（write 有幂等键，不会重复写）。

  python scripts/zhengli/proof_cycle.py plan  --book vol04 -w $WS [--reviewer sheldon] [--cord <出单版 cord>]
  python scripts/zhengli/proof_cycle.py apply --book vol04 -w $WS --plan <plan.json> --hash <计划哈希> \
      --book-text <book-text 仓> [--allow-cv-drift] [--dry-run]
  python scripts/zhengli/proof_cycle.py audit --book vol04 -w $WS [--rev 004-r6] [--held held.tsv]   # 只读：G0 票账
  python scripts/zhengli/proof_cycle.py status --book vol06 -w $WS     # 只读：线上单投完没有（退出码 0＝可以落票了）

M10 复盘第 4 项（10-23，册006 起）：
  - 重跑缺省**全册** seed_admit（约 3 分钟）：只重跑有票的页会漏掉早有人裁、产物却比人裁旧的格（册005 41:9:7）。
    `--voted-pages-only` 退回旧做法。
  - **引擎与工具分开**：`plan --engine <出单版 cv 的 worktree>`，重跑用那份 cv（PYTHONPATH 指过去），出单、落票、导出
    用本仓（dev）。核的是 engine 的 HEAD 等于包的 cv_commit，不再要求本仓就是那个提交。
  - 线上单没有 rev-<rev> 包时 `plan --pack <标签>` 指定出单用的包（如 main 包）。
  - **人裁改字与机器改字分开**：导出后和 book-text 现文逐格比，变了的格里，最新人裁就是新字的算人裁改字，进文本；
    其余是机器改判（无票变字），文本里退回旧字，格放进下一张单的复审清单（「机器改判 A→B，无人裁，请核」）。
    未冻结册的变字一律进待审（用户 10-20 定），不自行放行。
  - 出单换成 `republish.py issue`：挂起里能回网站的（cellvotes 的 recheck.tsv）和机器改判一起作复审格，
    只发这一章、等发布、冒烟。
  - `status`：线上单有几格、投了几格、最后一票多久以前；全投完，或投过八成且一小时没新票，就算投完。
    定时任务（云端 trigger）每半小时跑一次，投完了就 plan＋apply，用户只管在网站上投票。

票缺省直接读网站 KV（要 CELLREVIEW_TOKEN）；没有令牌就读中心库快照（每日同步之后才有）。
仍要用户点头的（不在本脚本里）：打 1.0 标签与冻结、解冻、放宽放行规则、越过检查门的 --ack-*。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CV = HERE.parents[1]
sys.path.insert(0, str(HERE))
import republish as rp  # noqa: E402

GUJI = [sys.executable, "-m", "open_guji_cv.cli_v2"]


def sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else ""


RECHECK_HEAD = "格位\t说明\t旧人裁\t旧人裁的字\t旧人裁时间\n"


def merge_recheck(dst: Path, extra: Path) -> int:
    """把别处发现的疑点（如重标时看出的字错）并进本轮的复审清单：同格以 extra 为准。返回并进的格数。

    extra 与 recheck.tsv 同格式（格位<TAB>说明<TAB>旧人裁 id<TAB>旧人裁的字<TAB>旧人裁时间，首行表头）；
    格位写不写 `vol06:` 前缀都行。旧人裁 id 填了，网站卡片会写明「已有判断」，新票按有意推翻照写。"""
    def rows(p: Path) -> dict[str, str]:
        out = {}
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines()[1:]:
                if ln.strip():
                    first = ln.split("\t", 1)[0].strip()
                    cell = first.split(":", 1)[1] if first.count(":") == 3 else first   # vol06:9:6:10 → 9:6:10
                    out[cell] = "\t".join([cell, *ln.split("\t")[1:]])
        return out
    have, add = rows(dst), rows(extra)
    have.update(add)
    dst.write_text(RECHECK_HEAD + "".join(r + "\n" for r in have.values()), encoding="utf-8")
    return len(add)


def plan_hash(plan: dict) -> str:
    """计划本身的哈希（不含 hash 字段）：apply 必须给对，确保执行的就是这一份。"""
    body = {k: v for k, v in plan.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def voted_pages(drafts: Path) -> list[int]:
    pages = set()
    for line in drafts.read_text(encoding="utf-8").splitlines() if drafts.exists() else []:
        if line.strip():
            row = json.loads(line)
            parts = str(row.get("id") or "").split(":")     # 控制台事件行：id = <册>:页:列:格
            if len(parts) >= 2 and parts[1].isdigit():
                pages.add(int(parts[1]))
    return sorted(pages)


def pack_info(ws: Path, book: str, label: str) -> dict | None:
    """包的 manifest（cv_version、cv_commit）；没有这个包返回 None。"""
    sys.path.insert(0, str(CV))
    try:
        from open_guji_cv.datastore import packs as PK
        src = PK._client()
        name = f"{PK._prefix(PK._ws_name(), book)}/{label}"
        return json.loads(PK._call(src, "GET", f"{name}/manifest.json", raw=True))
    except Exception as e:  # noqa: BLE001 —— 取不到就当没有，退回 --cord
        print(f"ⓘ 取不到产物包 {label}：{e}")
        return None


def cmd_plan(a) -> int:
    ws, book = Path(a.workspace).resolve(), a.book
    chapter, text_id = rp.chapter_of(book), rp.text_id_of(ws)
    env = {**os.environ, "GUJI_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8"}
    if not a.no_pull and rp.run([*GUJI, "db", "pull", "-w", ws], cwd=CV, env=env).returncode:
        return 1
    online = rp.proofing_path(ws, text_id, chapter)
    if not online.exists():
        sys.exit(f"✗ 数据目录没有线上单 {online}")
    rev = json.loads(online.read_text(encoding="utf-8")).get("rev")
    out = ws / "reports" / book / "_cycle" / rev
    draft = out / "draft"
    label = a.pack or rp.pack_label(rev)
    man = pack_info(ws, book, label)
    cmd = [*GUJI, "cellvotes", "draft", book, "--site-book", text_id, "--rev", rev, "--out", draft, "-w", ws]
    cmd += ["--from-kv"] if os.environ.get("CELLREVIEW_TOKEN") else []
    if man:
        cmd += ["--pack", label]
    elif a.cord:
        cmd += ["--cord", a.cord]
    else:
        sys.exit(f"✗ 线上单 {rev} 没有出单版产物包 {label}，要给 --cord（出单那一版 book-text 的 {chapter}.cord.json）")
    if rp.run(cmd, cwd=CV, env=env).returncode:
        return 1
    meta = json.loads((draft / "meta.json").read_text(encoding="utf-8"))
    if a.recheck_extra:
        n_extra = merge_recheck(draft / "recheck.tsv", Path(a.recheck_extra))
        print(f"另加复审 {n_extra} 格（{a.recheck_extra}）")
    pages = voted_pages(draft / "drafts.jsonl")
    engine = str(Path(a.engine).resolve()) if a.engine else None
    plan = {
        "book": book, "text_id": text_id, "chapter": chapter, "rev": rev,
        "batch": f"H-web-{book}-{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')}-{rev}",
        "reviewer": a.reviewer, "draft_dir": str(draft),
        "drafts_sha": sha_file(draft / "drafts.jsonl"), "ready": meta["ready"], "held": meta["held"],
        "skipped": len(meta.get("skipped") or []), "votes": meta["n_votes"], "votes_from": meta["votes_from"],
        "pack": label if man else None, "pack_cv_commit": (man or {}).get("cv_commit"),
        "pack_cv_version": (man or {}).get("cv_version"), "cord": None if man else str(a.cord),
        "pages": pages, "full_book": not a.voted_pages_only, "engine": engine,
        "engine_commit": engine_head(Path(engine)) if engine else None,
        "recheck": sum(1 for ln in (draft / "recheck.tsv").read_text(encoding="utf-8").splitlines()[1:] if ln.strip())
        if (draft / "recheck.tsv").exists() else 0,
        "created": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    plan["hash"] = plan_hash(plan)
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = [f"# {book} 一轮精校计划（线上单 {rev}）", "",
          f"- 票：{meta['votes_from']}；有效 {meta['n_votes']} 条",
          f"- **写人裁 {plan['ready']} 条**（批次 `{plan['batch']}`，裁决人 {a.reviewer}）；挂起 {plan['held']}、跳过 {plan['skipped']}"
          f"（明细 `{draft / 'report.md'}`、`held.tsv`）",
          f"- 锚：{'出单版产物包 ' + label + '（cv ' + str(plan['pack_cv_version']) + '，' + str(plan['pack_cv_commit'])[:9] + '）' if man else '对 --cord ' + str(a.cord)}",
          f"- 重跑{'全册' if plan['full_book'] else f'有票的 {len(pages)} 页'}到 seed_admit"
          f"（引擎 {'本仓' if not engine else engine + ' @ ' + str(plan['engine_commit'])[:9]}），导出，"
          f"人裁改字进文本、机器改判退回旧字进复审，升 book-text minor（提交到 dev），重出单并只发这一章",
          f"- 挂起里回网站再看 {plan['recheck']} 格（recheck.tsv）",
          f"- 计划哈希 `{plan['hash']}`", "",
          f"执行：`python scripts/zhengli/proof_cycle.py apply --book {book} -w {ws} --plan {out / 'plan.json'} "
          f"--hash {plan['hash']} --book-text <book-text 仓>`"]
    (out / "计划.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


def verify(plan: dict, given_hash: str, ws: Path) -> list[str]:
    """apply 前逐条核：哈希、草稿文件、线上单 rev。返回不对的地方（空 = 可以执行）。"""
    bad = []
    if plan_hash(plan) != plan.get("hash") or given_hash != plan.get("hash"):
        bad.append(f"计划哈希对不上（给的 {given_hash}，计划 {plan.get('hash')}，重算 {plan_hash(plan)}）")
    if sha_file(Path(plan["draft_dir"]) / "drafts.jsonl") != plan["drafts_sha"]:
        bad.append("草稿 drafts.jsonl 在计划之后被改过")
    online = rp.proofing_path(ws, plan["text_id"], plan["chapter"])
    now = json.loads(online.read_text(encoding="utf-8")).get("rev") if online.exists() else None
    if now != plan["rev"]:
        bad.append(f"线上单已从 {plan['rev']} 换成 {now}：重出计划")
    return bad


class Log:
    def __init__(self, path: Path, dry: bool):
        self.path, self.dry = path, dry
        self.lines = [f"# 执行记录 {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}" + ("（演练）" if dry else ""), ""]

    def step(self, name: str, cmd, ok_codes: tuple[int, ...] = (0,), **kw) -> bool:
        cmd = [str(c) for c in cmd]
        if self.dry:
            self.lines.append(f"- [演练] {name}：`{' '.join(cmd)}`")
            print(f"[演练] {name}: {' '.join(cmd)}")
            ok = True
        else:
            rc = rp.run(cmd, **kw).returncode
            ok = rc in ok_codes
            self.lines.append(f"- {'✓' if rc == 0 else ('⚠' if ok else '✗')} {name}" + (f"（退出码 {rc}）" if rc else ""))
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        return ok

    def note(self, s: str) -> None:
        self.lines.append(f"- {s}")
        print(s)
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def cmd_apply(a) -> int:
    ws, book = Path(a.workspace).resolve(), a.book
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    if plan["book"] != book:
        sys.exit(f"✗ 计划是 {plan['book']} 的")
    bad = verify(plan, a.hash, ws)
    if bad:
        sys.exit("✗ 计划对不上，不执行：\n  " + "\n  ".join(bad))
    out = Path(a.plan).parent
    log = Log(out / "执行记录.md", a.dry_run)
    env = {**os.environ, "GUJI_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8"}

    # 2. 落票、推库
    if plan["ready"]:
        if not log.step("写人裁并消费", [*GUJI, "cellvotes", "write", book, plan["draft_dir"], "--batch", plan["batch"],
                                    "--reviewer", plan["reviewer"], "-w", ws], cwd=CV, env=env):
            return 1
        if not log.step("推库（guji db sync）", [*GUJI, "db", "sync", "-w", ws], cwd=CV, env=env):
            return 1
    else:
        log.note("没有可写的票，跳过落票")

    if not a.dry_run:                       # G0 票账：写完之后每一票都该有去向
        votes, src = rp.old_rev_votes(ws, plan["text_id"], plan["rev"])
        held = [ln.split("\t")[0] for ln in (Path(plan["draft_dir"]) / "held.tsv").read_text(encoding="utf-8").splitlines()[1:] if ln.strip()]
        log.note(rp.ledger_md(rp.ticket_ledger(ws, book, plan["text_id"], plan["rev"], votes, held)) + f"（票源：{src}）")

    # 3. 重跑：只能用出单那一版 cv（引擎），否则混进别版切分；工具（落票、导出、出单）用本仓
    engine = Path(plan["engine"]) if plan.get("engine") else CV
    if plan["pack"]:
        head = engine_head(engine)
        if plan["pack_cv_commit"] and not head.startswith(plan["pack_cv_commit"][:7]) and not a.allow_cv_drift:
            sys.exit(f"✗ 引擎 cv（{engine}）是 {head[:9]}，出单版产物包是 {plan['pack_cv_commit'][:9]}（{plan['pack_cv_version']}）："
                     f"plan 加 --engine <那个 commit 的 worktree>，或加 --allow-cv-drift 明说照跑（人裁已推库，重跑 apply 不会重复写）")
        sandbox = Path(a.reuse_products).resolve() if a.reuse_products else Path(plan["draft_dir"]).parent / "products"
        env_sb = {**env, "GUJI_PRODUCTS_DIR": str(sandbox)}
        if a.reuse_products:
            if not (sandbox / book).is_dir():
                sys.exit(f"✗ --reuse-products {sandbox} 下没有 {book} 的产物")
        elif not (sandbox / book).is_dir():
            if not log.step("取出单版产物包到沙箱", [*GUJI, "products", "pack", "fetch", book, "--label", plan["pack"],
                                              "--to", sandbox, "-w", ws], cwd=CV, env=env):
                return 1
    else:
        sandbox, env_sb = rp.products_root(ws), env
        log.note("ⓘ 没有出单版产物包：在本机产物根上重跑（要自己担保本机产物就是出单那一版）")
    if plan.get("pack"):                    # 出单版包的备注记下来源包，auto_cycle 靠它判断线上单是不是基于现在的 main
        env_sb = {**env_sb, "GUJI_ISSUE_SRC_PACK": plan["pack"]}
    env_eng = {**env_sb, "PYTHONPATH": str(engine)} if engine != CV else env_sb
    # 旧引擎经 engine_run.py 跑：读中心库时跳过它不认的新事件种类（不然一推新种类，每页都失败）
    guji_eng = [sys.executable, HERE / "engine_run.py"] if engine != CV else GUJI
    # --stop-on-error：一页失败就非零退出，免得带着失败的产物接着导出、出单
    if a.reuse_products:
        log.note(f"产物用现成的 {sandbox}（引擎换版本后自己从头跑好的），不再重跑 seed_admit")
    elif plan.get("full_book", False):
        if not log.step("全册重跑 seed_admit", [*guji_eng, "pipeline", "keben_body_v2", book, "--from", "seed_admit",
                                               "--to", "seed_admit", "--stop-on-error", "-w", ws], cwd=engine, env=env_eng):
            return 1
    elif plan["pages"] and not log.step(f"重跑 {len(plan['pages'])} 页到 seed_admit",
                                        [*guji_eng, "pipeline", "keben_body_v2", book, "--pages", ",".join(map(str, plan["pages"])),
                                         "--to", "seed_admit", "--stop-on-error", "-w", ws], cwd=engine, env=env_eng):
        return 1

    # 4. 导出（book-text 先切到最新 dev：现文、文本版本都以 dev 为准，2026-10-24 起流程化小改直接提交 dev）
    if not a.dry_run:
        rp.book_text_to_dev(Path(a.book_text))
    tv = rp.online_text_version(Path(a.book_text), plan["text_id"], plan["chapter"])
    export = out / "export"
    cmd = [sys.executable, CV / "scripts/export_guji_format.py", "--products", sandbox, "--book", book,
           "--chapter", plan["chapter"], "--out", export, "--format", "char-cord", "--keys", "cv", "--text-version", tv]
    for flag, f in (("--meta", rp.meta_file(book, out)),
                    ("--split-table", CV / "doc/formats/samples/guji_page_v0.2/split_table_siku.json")):
        if f and Path(f).exists():
            cmd += [flag, f]
    if not log.step("导出 char／cord", cmd, cwd=CV, env=env_sb):
        return 1

    # 4b. 人裁改字进文本，机器改判退回旧字、进复审
    recheck = out / "recheck.tsv"
    rows = []
    if not a.dry_run:
        old_char = rp.book_text_dir(Path(a.book_text), plan["text_id"]) / f"{plan['chapter']}.char.json"
        new_char = export / f"{plan['chapter']}.char.json"
        sp = split_changes(old_char, new_char, human_chars_of(ws, book))
        if sp["machine"]:
            revert_cells(new_char, {a_: o for a_, o, _ in sp["machine"]})
        log.note(f"文本改动 {len(sp['human']) + len(sp['machine'])} 格：人裁 {len(sp['human'])} 格进文本；"
                 f"机器改判 {len(sp['machine'])} 格退回旧字、进复审"
                 + (f"（{'、'.join(f'{x}:{o}→{n}' for x, o, n in sp['machine'][:10])}）" if sp["machine"] else ""))
        dr = Path(plan["draft_dir"]) / "recheck.tsv"
        rows = [ln for ln in dr.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()] if dr.exists() else []
        rows += [f"{x}\t机器改判「{o or '□'}」→「{n or '□'}」，无人裁，请核\t\t\t" for x, o, n in sp["machine"]]
        recheck.write_text("格位\t说明\t旧人裁\t旧人裁的字\t旧人裁时间\n" + "".join(r + "\n" for r in rows), encoding="utf-8")

    # 5. 一条命令出单：过出单门、换单门，传图、存包、升 book-text、推库、只发这一章、等发布、冒烟
    new_rev = rp.next_rev(plan["rev"], plan["chapter"])
    note = (f"{book} 精校一轮：{plan['rev']} 的 {plan['ready']} 条人裁（{plan['batch']}），待审单 {new_rev}")
    issue = [sys.executable, HERE / "republish.py", "issue", "--book", book, "-w", ws, "--export-dir", export,
             "--rev", new_rev, "--book-text", a.book_text, "--note", note,
             "--held-file", Path(plan["draft_dir"]) / "held.tsv"]
    if rows:
        issue += ["--recheck", recheck]
    if engine != CV:
        issue += ["--engine", engine]
    if a.ack_unlanded_votes:
        issue += ["--ack-unlanded-votes", a.ack_unlanded_votes]
    if getattr(a, "no_web", False):          # 批量时每册不单独触发网站发布，由 auto_cycle 最后统一发一次
        issue += ["--no-publish-web"]
    cv_commit = plan.get("engine_commit") if engine != CV else plan["pack_cv_commit"]   # 重跑用的是哪份 cv 就记哪份
    if cv_commit:
        issue += ["--cv-commit", cv_commit]
    cv_version = engine_version(engine) if engine != CV else plan["pack_cv_version"]
    if cv_version:
        issue += ["--cv-version", cv_version]
    # 退出码 2＝单子已推库、网站已发布、文本已推 dev，只是读者侧冒烟没过：记 ⚠ 照常收尾，冒烟另查
    if not log.step(f"出新单 {new_rev}（复审 {len(rows)} 格）并上线", issue, ok_codes=(0, 2), cwd=CV, env=env_sb):
        return 1

    # 6. book-text：republish issue 已把文本升版提交并推到 dev（不开 PR），每日合并进 main
    log.note(f"book-text：文本升版已推到 dev，每日合并（洛杉矶 03:30）进 main")
    log.note(f"完成：写 {plan['ready']} 条、新单 {new_rev} 已推并触发网站发布")
    if not a.dry_run:                       # 后台「文本整理」的人审进度（所有册）；republish push 已写过一次，这里兜底
        import progress_report
        progress_report.try_run(book, plan["text_id"], log=log.note)
    return 0


def engine_version(engine: Path) -> str | None:
    """引擎 worktree 的版本号：HEAD 上的 vX.Y.Z 标签去掉 v；没有标签返回 None（出单不写版本）。"""
    p = subprocess.run(["git", "describe", "--tags", "--exact-match", "--match", "v[0-9]*"], cwd=engine,
                       capture_output=True, text=True)
    return p.stdout.strip().lstrip("v") or None


def engine_head(engine: Path) -> str:
    if Path(engine).resolve() == CV.resolve():
        return rp.git_head()
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=engine, capture_output=True, text=True).stdout.strip()


def _cells(char_json: Path) -> dict[str, str]:
    d = json.loads(Path(char_json).read_text(encoding="utf-8"))
    return {c["a"]: c.get("c") or "" for p in d.get("pages") or [] for col in p.get("columns") or [] for c in col.get("cells") or []}


def human_chars_of(ws: Path, book: str) -> dict[str, str]:
    """每格最新一条定字人裁的字（{格位: 字}；无字＝""）。读数据目录事件，口径同 pending_route.deciding。"""
    from pending_route import cell_of, deciding
    last: dict[str, tuple[str, str]] = {}
    if str(rp.CV) not in sys.path:
        sys.path.insert(0, str(rp.CV))
    from open_guji_cv.core.event_files import RevGate, iter_event_dicts
    gate = RevGate(books_dir=rp.data_dir(ws) / "books")   # 换图源：切过的册只认锚里页表 rev 相符的
    for e in iter_event_dicts(rp.data_dir(ws) / "feedback" / "events", gate=gate):
        k = deciding(e)
        c = cell_of(e, book) if k else None
        if c and str(e.get("ts", "")) >= last.get(c, ("", ""))[0]:
            last[c] = (str(e.get("ts", "")), (e.get("payload") or {}).get("shape") or "")
    if gate.note():
        print(f"  ⓘ {gate.note()}", file=sys.stderr)
    return {c: ch for c, (_, ch) in last.items()}


def split_changes(old_char: Path, new_char: Path, human: dict[str, str]) -> dict:
    """新导出对 book-text 现文逐格比：变了的格里，最新人裁就是新字的＝人裁改字，其余＝机器改判（无票变字）。
    格号两边对不上的（重切）不在这里管，交 republish 的差异单。"""
    o, n = _cells(old_char), _cells(new_char)
    human_ch, machine = [], []
    for a_ in sorted(set(o) & set(n), key=rp._key):
        if o[a_] == n[a_]:
            continue
        (human_ch if human.get(a_) and human[a_] == n[a_] else machine).append((a_, o[a_], n[a_]))
    return {"human": human_ch, "machine": machine}


def revert_cells(char_json: Path, old: dict[str, str]) -> None:
    """机器改判的格在导出里退回旧字（未冻结册的变字一律进待审，不自行放进文本）。"""
    d = json.loads(Path(char_json).read_text(encoding="utf-8"))
    for p in d.get("pages") or []:
        for col in p.get("columns") or []:
            for c in col.get("cells") or []:
                if c["a"] in old:
                    if old[c["a"]]:
                        c["c"] = old[c["a"]]
                    else:
                        c.pop("c", None)
    Path(char_json).write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def sheet_status(ws: Path, book: str, idle_min: int = 60, share: float = 0.8) -> dict:
    """线上单投完没有：每格（不含 review=human）都有票，或投过 share 且最后一票已过 idle_min 分钟。"""
    import time
    text_id, chapter = rp.text_id_of(ws), rp.chapter_of(book)
    doc = json.loads(rp.proofing_path(ws, text_id, chapter).read_text(encoding="utf-8"))
    rev = doc.get("rev")
    cells = {c["cell"] for c in doc.get("cells") or [] if c.get("review") != "human"}
    votes, src = rp.old_rev_votes(ws, text_id, rev)
    sys.path.insert(0, str(CV))
    from open_guji_cv.feedback.web_votes import latest_votes
    latest, _ = latest_votes(votes, text_id, rev)
    voted = {v["a"] for v in latest} & cells
    last = max(((float(v.get("ts") or 0) / (1000 if float(v.get("ts") or 0) > 1e11 else 1)) for v in latest), default=0.0)
    idle = (time.time() - last) / 60 if last else None
    full = bool(cells) and voted >= cells
    done = full or (bool(cells) and len(voted) >= share * len(cells) and idle is not None and idle >= idle_min)
    return {"rev": rev, "cells": len(cells), "voted": len(voted), "idle_min": round(idle, 1) if idle is not None else None,
            "done": done, "why": "全投完" if full else (f"投过 {share:.0%} 且 {idle_min} 分钟没新票" if done else "还在投"),
            "src": src}


def cmd_status(a) -> int:
    st = sheet_status(Path(a.workspace).resolve(), a.book, a.idle_min, a.share)
    print(json.dumps(st, ensure_ascii=False))
    return 0 if st["done"] else 3


def cmd_audit(a) -> int:
    """只读：某张单（缺省线上那张）的 G0 票账。"""
    ws, book = Path(a.workspace).resolve(), a.book
    text_id, chapter = rp.text_id_of(ws), rp.chapter_of(book)
    rev = a.rev or json.loads(rp.proofing_path(ws, text_id, chapter).read_text(encoding="utf-8")).get("rev")
    votes, src = rp.old_rev_votes(ws, text_id, rev)
    held = [ln.split("\t")[0] for ln in Path(a.held).read_text(encoding="utf-8").splitlines()[1:] if ln.strip()] if a.held else []
    led = rp.ticket_ledger(ws, book, text_id, rev, votes, held)
    print(rp.ledger_md(led) + f"（票源：{src}）")
    return 1 if led["counts"]["未落"] else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("plan")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p.add_argument("--reviewer", default="sheldon", help="裁决人（网页投票的人）")
    p.add_argument("--cord", help="没有出单版产物包时：出单那一版 book-text 的 <章>.cord.json")
    p.add_argument("--pack", help="出单用的产物包标签（缺省 rev-<线上单 rev>；老单没存 rev 包时给 main 包的标签）")
    p.add_argument("--engine", help="出单版 cv 的 worktree（重跑用它；缺省本仓，须就是包的 cv_commit）")
    p.add_argument("--recheck-extra", help="另加复审的格（同 recheck.tsv 格式）：别处发现的疑点，拿不准的回网站再看")
    p.add_argument("--voted-pages-only", action="store_true", help="只重跑有票的页（旧做法；缺省全册 seed_admit）")
    p.add_argument("--no-pull", action="store_true")
    p = sp.add_parser("apply")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--hash", required=True, help="计划哈希（计划.md 里有）")
    p.add_argument("--book-text", required=True, help="book-text 仓（工作区干净；apply 会切到最新 dev）")
    p.add_argument("--reuse-products", help="产物沙箱用这份现成的（引擎换版本后自己从头跑好了，不取出单版包、不再重跑 seed_admit）；"
                                           "配合 plan --engine <新版 worktree> 与 --allow-cv-drift")
    p.add_argument("--ack-unlanded-votes", help="旧单还有票没落成人裁（如图形格）也照换单；写明原因，原样交给 republish issue")
    p.add_argument("--allow-cv-drift", action="store_true", help="本机 cv 与出单版不同也照跑重跑那一步")
    p.add_argument("--dry-run", action="store_true", help="只核计划、打出要跑的命令，不执行")
    p.add_argument("--no-web", action="store_true", help="出单、推库、升 book-text，但不触发网站发布、不冒烟（批量用，最后统一发）")
    p = sp.add_parser("audit", help="只读：一张单的 G0 票账（写入／一致／看不出／挂起／未落），有未落退出码 1")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p.add_argument("--rev", help="缺省线上单")
    p.add_argument("--held", help="cellvotes draft 的 held.tsv")
    p = sp.add_parser("status", help="只读：线上单投完没有（退出码 0＝投完了，3＝还在投）")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p.add_argument("--idle-min", type=int, default=60, help="投过 --share 之后多少分钟没新票算投完（缺省 60）")
    p.add_argument("--share", type=float, default=0.8)
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "apply": cmd_apply, "audit": cmd_audit, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
