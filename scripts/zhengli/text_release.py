#!/usr/bin/env python3
"""一册文本冲 1.0：锁输入、一条命令跑完 1.0 检查（M10 复盘第 6、7 项，A32，2026-10-23）。

册005 冲 1.0 的一天里，别的会话改了中心库的参照本、格位表和册 yaml 的字组列表，close-check 1a 判「参数变了」全册过期，
只能由用户拍板「照现产物冻结」；1.0 检查又是十几个命令手串。本脚本三件事：

  pin        冲 1.0 开始时记下这册的输入指纹（册 yaml、语料版本与语料包、参照本、逐列格位表、字组配置、glyph_pin、
             出单用的产物包与 cv 提交），写进数据目录 `feedback/lists/release/<册>.pin.json`，随 `guji db sync` 进中心库。
             这份文件在＝这册在冲 1.0：别的会话改这几样之前先 `check-pin` 看一眼；要改就等冻结之后按升版流程走。
  check-pin  现在的输入和 pin 比，变了的逐项列出并分两类：
               本册   册 yaml 变了（本册的代码参数）——冻结前要么退回、要么重跑并重新 pin；
               共享   语料、参照本、格位表、字组配置被别处更新——冻结时记一笔即可，不算失败（close-check 1a 同理）。
             退出码：0 没变；2 只有共享输入变；1 本册输入变。
  run        1.0 检查按标准顺序一次跑完（只读，不写中心库、不打 tag），全过就停在「请用户点头」：
               1 输入锁（check-pin）  2 G0 票账（线上单）  3 G1 待审与「看不出」≤2%（decision_build）
               4 G3 close-check（终校档，用钉住的引擎跑）  5 G3b/G3c 读者侧冒烟（线上单与图）
               6 出口动作里冻结前就能核的项（exit-check E3 E4 E10 E11）
             报告写 `<工作区>/reports/<册>/_release/<时刻>/1.0检查.md` 与 `result.json`。用户点头之后：
             `guji freeze register <册> --execute`、book-text 1.0 PR、合并后 `guji exit-check` 全项（标准 §4 第 7–9 步）。

  python scripts/zhengli/text_release.py pin --book vol06 -w $WS --pack <标签> [--engine <cv worktree>]
  python scripts/zhengli/text_release.py check-pin --book vol06 -w $WS
  python scripts/zhengli/text_release.py run --book vol06 -w $WS --book-text <book-text 仓> [--engine <cv worktree>]
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
SHARED = ("corpus", "references", "layout", "groups")


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _sha_tree(root: Path) -> str | None:
    """目录下全部文件（相对路径＋内容）合起来的 sha256；目录不在返回 None。"""
    if not root.is_dir():
        return None
    h = hashlib.sha256()
    for f in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(str(f.relative_to(root)).encode("utf-8") + b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()


def pin_path(ws: Path, book: str) -> Path:
    return rp.data_dir(ws) / "feedback" / "lists" / "release" / f"{book}.pin.json"


def fingerprint(ws: Path, book: str) -> dict:
    """这册 1.0 要锁的输入，各项一个指纹（缺的记 None）。"""
    import yaml
    data = rp.data_dir(ws)
    y = data / "books" / f"{book}.yaml"
    doc = yaml.safe_load(y.read_text(encoding="utf-8")) if y.exists() else {}
    corpus = doc.get("corpus")
    refs = {r["file"]: _sha(data / "corpus" / r["file"]) for r in doc.get("references") or [] if isinstance(r, dict) and r.get("file")}
    import re
    m = re.search(r"^\s*layout_prior:\s*(\S+)", y.read_text(encoding="utf-8"), re.M) if y.exists() else None
    layout = m.group(1) if m else None
    return {
        "yaml": _sha(y),
        "corpus": {"version": corpus, "pack": _sha_tree(data / "config" / "corpus-pack" / f"v{corpus}") if corpus else None},
        "references": refs,
        "layout": {"path": layout, "sha": _sha(data / layout) if layout else None},
        "groups": _sha_tree(data / "config" / "groups"),
        "glyph_pin": doc.get("glyph_pin"),
    }


def drift(pinned: dict, now: dict) -> list[dict]:
    """逐项比，返回变了的：{item, kind: 本册|共享, was, now}。glyph_pin 记在本册（yaml 里的数）。"""
    out = []
    for k in ("yaml", "glyph_pin", *SHARED):
        if pinned.get(k) != now.get(k):
            out.append({"item": k, "kind": "共享" if k in SHARED else "本册", "was": pinned.get(k), "now": now.get(k)})
    return out


def cmd_pin(a) -> int:
    ws, book = Path(a.workspace).resolve(), a.book
    p = pin_path(ws, book)
    if p.exists() and not a.force:
        sys.exit(f"✗ {book} 已经 pin 过（{p}）：冲 1.0 期间不重 pin；确要按现在的输入重来加 --force（写明原因进 --note）")
    engine = Path(a.engine).resolve() if a.engine else CV
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=engine, capture_output=True, text=True).stdout.strip()
    doc = {"book": book, "sprint": "1.0", "pinned_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "pack": a.pack, "engine_commit": head or None, "note": a.note or "",
           "inputs": fingerprint(ws, book)}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{book} 冲 1.0 输入已锁 → {p}（随 guji db sync 进中心库）\n" + json.dumps(doc, ensure_ascii=False, indent=1))
    return 0


def check_pin(ws: Path, book: str) -> dict:
    p = pin_path(ws, book)
    if not p.exists():
        return {"pinned": False, "drift": [], "rc": 0}
    pinned = json.loads(p.read_text(encoding="utf-8"))
    d = drift(pinned["inputs"], fingerprint(ws, book))
    rc = 1 if any(x["kind"] == "本册" for x in d) else (2 if d else 0)
    return {"pinned": True, "pin": pinned, "drift": d, "rc": rc}


def cmd_check_pin(a) -> int:
    r = check_pin(Path(a.workspace).resolve(), a.book)
    if not r["pinned"]:
        print(f"{a.book} 没有 pin（没在冲 1.0）")
        return 0
    if not r["drift"]:
        print(f"{a.book} 输入与 pin（{r['pin']['pinned_at']}）一致")
    for x in r["drift"]:
        print(f"{'✗' if x['kind'] == '本册' else '⚠'} {x['kind']}输入 {x['item']} 变了：{json.dumps(x['was'], ensure_ascii=False)[:120]}"
              f" → {json.dumps(x['now'], ensure_ascii=False)[:120]}")
    return r["rc"]


# ───────────────────────── run ─────────────────────────

def _run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def gate(gid: str, name: str, ok: bool | None, detail: str) -> dict:
    return {"id": gid, "name": name, "ok": ok, "detail": detail}


def cmd_run(a) -> int:
    ws, book = Path(a.workspace).resolve(), a.book
    chapter, text_id = rp.chapter_of(book), rp.text_id_of(ws)
    env = {**os.environ, "GUJI_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8"}
    engine = Path(a.engine).resolve() if a.engine else CV
    env_eng = {**env, "PYTHONPATH": str(engine)} if engine != CV else env
    text_dir = rp.book_text_dir(Path(a.book_text), text_id)
    out = ws / "reports" / book / "_release" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    gates: list[dict] = []

    # 1 输入锁
    cp = check_pin(ws, book)
    if not cp["pinned"]:
        gates.append(gate("L", "输入锁", None, "没有 pin：先 text_release.py pin（冲 1.0 开始时）"))
    else:
        own = [x["item"] for x in cp["drift"] if x["kind"] == "本册"]
        shared = [x["item"] for x in cp["drift"] if x["kind"] == "共享"]
        gates.append(gate("L", "输入锁", not own, ("本册输入变了：" + "、".join(own) + "；" if own else "")
                          + ("共享输入被别处更新（冻结时记一笔，不算失败）：" + "、".join(shared) if shared else "与 pin 一致" if not own else "")))

    # 2 G0 票账
    online = rp.proofing_path(ws, text_id, chapter)
    sheet = json.loads(online.read_text(encoding="utf-8")) if online.exists() else {"cells": []}
    rev = sheet.get("rev")
    votes, src = rp.old_rev_votes(ws, text_id, rev) if rev else ([], "无线上单")
    led = rp.ticket_ledger(ws, book, text_id, rev, votes, a.held and [ln.split("\t")[0] for ln in
                                                                    Path(a.held).read_text(encoding="utf-8").splitlines()[1:] if ln.strip()])
    gates.append(gate("G0", "票账", not led["counts"]["未落"], rp.ledger_md(led) + f"（{src}）"))

    # 3 G1 待审与看不出
    pend = [c for c in sheet.get("cells") or [] if c.get("review") != "human"]
    dec = out / f"{chapter}.decision.json"
    p = _run([sys.executable, HERE / "decision_build.py", "--char", text_dir / f"{chapter}.char.json", "--pending", online,
              "--events-dir", rp.data_dir(ws) / "feedback" / "events", "--book", book, "--out", dec], env=env)
    items = json.loads(dec.read_text(encoding="utf-8")).get("items", []) if dec.exists() else []
    unclear = [i for i in items if not i.get("reason")]
    n_cells = sum(len(col.get("cells") or []) for pg in json.loads((text_dir / f"{chapter}.char.json").read_text(encoding="utf-8"))["pages"]
                  for col in pg.get("columns") or [])
    open_cells = [c["cell"] for c in pend if c["cell"] not in {i.get("a") or i.get("cell") for i in items}]
    share = len(unclear) / max(1, len(pend)) if pend else 0.0
    ok1 = p.returncode in (0, 2) and not open_cells and share <= 0.02
    gates.append(gate("G1", "待审清零、看不出 ≤ 待审格 2%", ok1,
                      f"线上单 {rev} {len(pend)} 格；decision.json {len(items)} 条（看不出 {len(unclear)}，占 {share:.1%}）；"
                      f"既没定字也没进 decision 的 {len(open_cells)} 格" + (f"（{'、'.join(open_cells[:10])}）" if open_cells else "")
                      + f"；全册 {n_cells} 格"))

    # 4 G3 close-check（钉住的引擎）
    p = _run([*GUJI, "close-check", book, "--pending", "--json"], cwd=engine, env=env_eng)
    try:
        cc = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        cc = None
    bad = [f"{x.get('id')} {x.get('name') or ''}".strip() for x in (cc or {}).get("items", []) if x.get("ok") is False] if cc else []
    gates.append(gate("G3", "close-check（终校档，引擎 " + (str(engine) if engine != CV else "本仓") + "）",
                      p.returncode == 0 if cc is not None else None,
                      ("不过：" + "、".join(bad[:12]) if bad else "全过") if cc is not None else f"没跑成：{(p.stderr or p.stdout)[-300:]}"))

    # 5 G3b/G3c 读者侧
    sm = rp.smoke(text_id, chapter, rev, tries=1) if rev else ["没有线上单"]
    gates.append(gate("G3c", "读者侧：线上单与图取得到", not sm, "全部 200" if not sm else "；".join(sm[:8])))

    # 6 出口动作里冻结前能核的
    p = _run([*GUJI, "exit-check", book, "--text-dir", text_dir, "--json"], cwd=CV, env=env)
    try:
        ex = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        ex = {"items": []}
    pre = [x for x in ex.get("items", []) if x["id"] in ("E3", "E4", "E10", "E11")]
    gates.append(gate("E", "出口动作（冻结前能核的 E3 E4 E10 E11）", all(x["ok"] is not False for x in pre) if pre else None,
                      "；".join(f"{x['id']} {'✓' if x['ok'] else '✗' if x['ok'] is False else '—'} {x.get('detail', '')[:80]}" for x in pre)))

    ok = all(g["ok"] is not False for g in gates) and all(g["ok"] is not None for g in gates if g["id"] in ("G0", "G1", "G3"))
    res = {"book": book, "rev": rev, "ok": ok, "gates": gates, "out": str(out)}
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# {book} 1.0 检查（线上单 {rev}）", "", "| 门 | 项 | 结果 | 说明 |", "|---|---|---|---|"]
    md += [f"| {g['id']} | {g['name']} | {'✓' if g['ok'] else '✗' if g['ok'] is False else '—'} | {g['detail']} |" for g in gates]
    md += ["", "**全过：请用户点头冻结 1.0**（之后 `guji freeze register --execute`、book-text 1.0 PR、合并后 exit-check 全项）"
           if ok else "**有门不过：不冻结。** 达不到标准的书退回 A31／A30，或回精校再走一轮。"]
    (out / "1.0检查.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("pin", help="冲 1.0 开始：锁这册的输入")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p.add_argument("--pack", help="出单／冻结用的产物包标签")
    p.add_argument("--engine", help="钉住的 cv worktree（记它的 HEAD）；缺省本仓")
    p.add_argument("--note", help="为什么 pin（重 pin 时写原因）")
    p.add_argument("--force", action="store_true", help="已 pin 过也按现在的输入重来")
    p = sp.add_parser("check-pin", help="现在的输入和 pin 比（退出码 0 没变／2 只有共享输入变／1 本册输入变）")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p = sp.add_parser("run", help="1.0 检查一次跑完（只读），全过停在「请用户点头」")
    p.add_argument("--book", required=True)
    p.add_argument("-w", "--workspace", required=True)
    p.add_argument("--book-text", required=True, help="book-text 仓")
    p.add_argument("--engine", help="钉住的 cv worktree（close-check 用它跑）；缺省本仓")
    p.add_argument("--held", help="cellvotes draft 的 held.tsv（G0 认作挂起）")
    a = ap.parse_args(argv)
    return {"pin": cmd_pin, "check-pin": cmd_check_pin, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
