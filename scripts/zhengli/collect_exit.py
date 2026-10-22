#!/usr/bin/env python3
"""粗校出口取数（GUJI-556 / 设计 GUJI-543 §3.3）：对一册自动取 R1、R2、R3、R5 的数，检查 R4 异常表，
生成 exit_report.py 要吃的 input.json（可再直接拼出报告）。

用法：
  python scripts/zhengli/collect_exit.py vol04 -w $WS --export-dir DIR --anomaly vol04-异常表.json \
        [--reason "R3 原因归并一句话"] [-o vol04-input.json] [--report vol04-粗校报告.md]
可移植：核心是 collect(book, ws, export_dir, anomaly)->dict；CLI 只是薄壳。
前提：`guji` 在 PATH（或 --guji 指定）、`python` 能 import open_guji_cv（R2 在进程内调 gates.query），
GUJI_PRODUCTS_DIR 指向要查的产物目录。只读：不重算、不写 cv、不写事件。

失败不静默：命令缺／超时／产物缺 → 该项 result=FAIL 并写原因，不补默认值。
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CLASS_ZH = {"other": "其他", "lib_miss": "库缺字", "occluded": "印章遮挡", "near_form": "近形字",
            "ji_yi_si": "己已巳", "replace_align": "整理本替换对齐", "ref_conflict": "参照冲突", "variant": "异体"}
GATES = ["border_detect_gate", "column_gate", "row_segment_gate"]
STEP_BAD = ("stale", "missing", "failed", "blocked")


# ---------------------------------------------------------------- 小工具
def _run(cmd: list[str], timeout: int = 900) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        raise RuntimeError(f"命令不存在：{cmd[0]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"命令超时（{timeout}s）：{' '.join(cmd[:4])} …")


def _json_after_header(text: str) -> dict:
    """guji 的 --json 输出第一行是「工作区 …」头，截到第一个 `{` 再解析。"""
    i = text.find("{")
    if i < 0:
        raise RuntimeError("输出里没有 JSON：" + text[:200])
    return json.loads(text[i:])


def _fail(cmd: str, why: str) -> dict:
    return {"result": "FAIL", "number": why, "cmd": cmd, "attach": ""}


def _count(v) -> int:
    return len(v) if isinstance(v, (list, tuple, dict)) else int(v or 0)


def _cv_version() -> str:
    try:
        import open_guji_cv
        root = Path(open_guji_cv.__file__).resolve().parent.parent
        rc, out, _ = _run(["git", "-C", str(root), "describe", "--tags", "--always", "--long"], 60)
        rc2, sha, _ = _run(["git", "-C", str(root), "rev-parse", "--short=8", "HEAD"], 60)
        if rc == 0 and rc2 == 0:
            return f"{sha.strip()}（{out.strip()}）"
    except Exception as e:  # noqa: BLE001
        return f"未知（{type(e).__name__}: {e}）"
    return "未知"


# ---------------------------------------------------------------- R5 ＋ close-check
def _supports_tier(guji: str) -> bool:
    _, out, err = _run([guji, "close-check", "--help"], 120)
    return "--tier" in out + err


def _close_check(book, ws, export_dir, guji, notes=None, pending=None) -> tuple[dict | None, str, str | None]:
    """返回 (close-check JSON, 命令串, 错误)。cv 没有 --tier 时不带，粗校档在 _r5 里手工剔第 2 项。"""
    cmd = [guji, "close-check", book, "-w", str(ws), "--json"]
    if export_dir:
        cmd += ["--export-dir", str(export_dir)]
    if notes:
        cmd += ["--notes", str(notes)]
    if pending:
        cmd += ["--pending", str(pending)]     # 2c：□ 在公众待审单上也算有去向（GUJI-624）
    tier = _supports_tier(guji)
    if tier:
        cmd += ["--tier", "rough"]
    shown = " ".join(["guji"] + cmd[1:]).replace(str(ws), "$WS")
    try:
        rc, out, err = _run(cmd)
        res = _json_after_header(out)
    except Exception as e:  # noqa: BLE001
        return None, shown, f"{type(e).__name__}: {e}"
    res["_tier_native"] = tier
    return res, shown, None


def _export(book, ws, export_dir: Path, guji) -> str | None:
    """export_dir 里已有 lines.md 就复用；否则跑 guji export format。返回错误或 None。"""
    if list(export_dir.glob("*.lines.md")):
        return None
    export_dir.mkdir(parents=True, exist_ok=True)
    try:
        rc, out, err = _run([guji, "export", "format", book, "-w", str(ws), "--out", str(export_dir)])
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    if rc != 0:
        return f"guji export format 退出码 {rc}：{(err or out)[-300:]}"
    return None


def _r5(cc, cmd, err, export_err) -> dict:
    if export_err:
        return _fail(cmd, f"导出失败：{export_err}")
    if err or cc is None:
        return _fail(cmd, f"close-check 出错：{err}")
    items = cc["items"]
    # 粗校档：第 2 项（待审清零）只报数不计。老 cv 没有 --tier，这里手工剔除；有就以 cv 自己的判定为准。
    machine = [it for it in items if it["status"] not in ("manual", "skip")]
    if not cc.get("_tier_native"):
        machine = [it for it in machine if it["no"] != "2"]
    bad = [it for it in machine if it["status"] != "pass"]
    manual = sorted(it["no"] for it in items if it["status"] == "manual")
    skip = sorted(it["no"] for it in items if it["status"] == "skip")
    ok_nos = "/".join(it["no"] for it in machine if it["status"] == "pass")
    exp = [it for it in items if it["no"] in ("10", "11")]
    exp_txt = "；".join(f"{it['no']} {it['detail']}" for it in exp)
    num = (f"close-check 粗校档（第 2 项待审不计"
           f"{'，cv 自带 --tier rough' if cc.get('_tier_native') else '，cv 无 --tier，按 Maren 口径手工剔除'}）："
           + (f"未过 {', '.join(it['no'] + ' ' + it['status'] + '：' + it['detail'] for it in bad)}；" if bad else "")
           + f"机器项 {ok_nos} 过；人工项 {'/'.join(manual)} 待人确认；{'/'.join(skip) or '无'} 未给 notes／未查。{exp_txt}")
    return {"result": "FAIL" if bad else "PASS", "number": num, "cmd": cmd, "attach": ""}


# ---------------------------------------------------------------- R1
def _r1(book, ws, cc, guji) -> dict:
    cmd = f"guji status {book} --pages all -w $WS --json；guji close-check（1b、2b）"
    try:
        rc, out, err = _run([guji, "status", book, "--pages", "all", "-w", str(ws), "--json"])
        st = _json_after_header(out)
    except Exception as e:  # noqa: BLE001
        return _fail(cmd, f"status 出错：{type(e).__name__}: {e}")
    steps = st["steps"]
    bad = {sid: {k: d["counts"][k] for k in STEP_BAD if d["counts"].get(k)} for sid, d in steps.items()}
    bad = {k: v for k, v in bad.items() if v}
    n_pages = _count(st.get("pages"))
    cache = next((it for it in (cc or {}).get("items", []) if it["no"] == "1b"), None)
    clos = next((it for it in (cc or {}).get("items", []) if it["no"] == "2b"), None)
    gaps, mism = _count(st.get("closure_gaps")), _count(st.get("closure_mismatches"))
    problems = []
    if bad:
        problems.append("、".join(f"{s} " + "/".join(f"{k}{c}" for k, c in v.items()) for s, v in bad.items()))
    if cache is None or cache["status"] != "pass":
        problems.append("缓存体检 " + (cache["status"] + "：" + cache["detail"] if cache else "未取到"))
    if clos is None or clos["status"] != "pass":
        problems.append("收尾闸 " + (clos["status"] + "：" + clos["detail"] if clos else "未取到"))
    if problems:
        return {"result": "FAIL", "cmd": cmd, "attach": "",
                "number": f"{len(steps)} 步×{n_pages} 页：" + "；".join(problems)}
    return {"result": "PASS", "cmd": cmd, "attach": "",
            "number": f"{len(steps)} 步×{n_pages} 页全部新鲜，stale/缺失/失败/阻塞=0；缓存错位 0 列；"
                      f"收尾闸已定字没出字 {gaps}、人裁字≠放行字 {mism}（报告项）"}


# ---------------------------------------------------------------- 钉版（提示，不判 FAIL）
def _pins(book) -> dict:
    """册 yaml 的钉版三项：cv_version、corpus、glyph_pin（GUJI-656，`doc/版本号规矩.md` 第七节）。

    只报不判：没钉的项进 warn，exit_report 在总判前单列一行。读不到册配置也只记 warn。"""
    try:
        from open_guji_cv.core.book import load_book
        b = load_book(book)
    except Exception as e:  # noqa: BLE001
        return {"warn": [f"读不到册配置：{type(e).__name__}: {e}"]}
    pins = {"cv_version": b.cv_version, "corpus": b.corpus, "glyph_pin": b.glyph_pin}
    pins["warn"] = [f"没钉 {k}" for k, v in pins.items() if v is None]
    return pins


# ---------------------------------------------------------------- R4 异常表 ＋ R2
def parse_anomaly(path: Path) -> list[dict]:
    """读异常表：每个数据行 → {n, text, concl}。只要行，不管格式问题（要问题清单用 `load_anomaly`）。"""
    return load_anomaly(path)[0]


def load_anomaly(path: Path) -> tuple[list[dict], list[str]]:
    """读异常表，返回（数据行, 格式问题）。问题都带行号，一条一句人话，不再是「格式一错整表 FAIL」（GUJI-666）。

    两种格式，按后缀认：
    - `.json`（推荐）：`{"book": "vol04", "rows": [{"n": 1, "text": "p79 col3 …", "cause": "…", "concl": "…",
      "pages": [79], "cols": [[79, 3]]}]}`；`pages`／`cols` 可选，给了就按它算「有去向」，不再从「现象」里抠 pN colM；
    - 其他（`.md`）：`| # | 现象 | 原因 | 结论 | … |`，结论列＝第 4 个单元格。以 `|` 开头却读不出来的行会报行号。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return (_load_anomaly_json(text) if path.suffix.lower() == ".json" else _load_anomaly_md(text))


def _load_anomaly_json(text: str) -> tuple[list[dict], list[str]]:
    import json
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [f"JSON 第 {e.lineno} 行第 {e.colno} 列：{e.msg}"]
    items = doc.get("rows") if isinstance(doc, dict) else doc
    if not isinstance(items, list):
        return [], ["顶层要是 {\"rows\": [...]} 或直接是数组"]
    rows, problems, seen = [], [], set()
    for i, it in enumerate(items, 1):
        where = f"rows[{i}]"
        if not isinstance(it, dict):
            problems.append(f"{where} 不是对象")
            continue
        n = str(it.get("n", "")).strip()
        if not re.fullmatch(r"\d+", n):
            problems.append(f"{where} 的 n 要是数字，现在是 {it.get('n')!r}")
            continue
        where = f"第 {n} 行（rows[{i}]）"
        if n in seen:
            problems.append(f"{where} 序号重复")
        seen.add(n)
        for k in ("text", "concl"):
            if k in it and not isinstance(it[k], str):
                problems.append(f"{where} 的 {k} 要是字符串")
        row = {"n": n, "text": str(it.get("text") or "").strip(), "concl": str(it.get("concl") or "").strip()}
        if not row["text"]:
            problems.append(f"{where} 没有 text（现象）")
        pages = it.get("pages")
        if pages is not None:
            if not (isinstance(pages, list) and all(isinstance(x, int) for x in pages)):
                problems.append(f"{where} 的 pages 要是整数数组")
            else:
                row["pages"] = pages
        cols = it.get("cols")
        if cols is not None:
            if not (isinstance(cols, list) and all(isinstance(x, list) and len(x) == 2 and all(isinstance(y, int) for y in x) for x in cols)):
                problems.append(f"{where} 的 cols 要是 [页, 列] 的数组")
            else:
                row["cols"] = [tuple(x) for x in cols]
        rows.append(row)
    return rows, problems


def _load_anomaly_md(text: str) -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    for no, ln in enumerate(text.splitlines(), 1):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells):
            continue                                              # 分隔行 |---|---|
        if not re.fullmatch(r"\d+", cells[0]):
            if re.match(r"#?\s*\d", cells[0]):                  # 像序号又不是纯数字（"1." "#2" "3）"）：多半是手误，报出来
                problems.append(f"第 {no} 行：序号格要写纯数字，现在是「{cells[0][:12]}」（该行不计入）")
            continue                                              # 其余（表头、别的表）不管
        if len(cells) < 4:
            problems.append(f"第 {no} 行：只有 {len(cells)} 格，要 `| # | 现象 | 原因 | 结论 |` 至少 4 格（该行不计入）")
            continue
        rows.append({"n": cells[0], "text": cells[1], "concl": cells[3]})
    return rows, problems


def _coverage(rows: list[dict]) -> tuple[set[int], set[tuple[int, int]]]:
    """异常表「现象」栏提到的页（pN）和页:列（同一分句里的 pN … colM／cM 笛卡尔积，宁宽勿窄，见 README）。"""
    pages, cols = set(), set()
    for r in rows:
        if not r["concl"] or r["concl"] in ("—", "-"):
            continue            # 没结论的行不算「有去向」
        if "pages" in r or "cols" in r:                 # 结构化异常表给了页／列，不再从现象里抠
            pages.update(r.get("pages", []))
            cols.update(tuple(c) for c in r.get("cols", []))
            pages.update(p for p, _ in r.get("cols", []))
            continue
        for seg in re.split(r"[;；]", r["text"]):
            ps = [int(x) for x in re.findall(r"(?<![A-Za-z])p\s*(\d+)", seg)]
            cs = [int(x) for x in re.findall(r"(?:col|c)\s*(\d+)", seg)]
            pages.update(ps)
            cols.update((p, c) for p in ps for c in cs)
    return pages, cols


def _r4(anomaly: Path | None) -> tuple[dict, list[dict]]:
    cmd = "人工看图（异常表见附件）"
    if anomaly is None or not anomaly.is_file():
        return _fail(cmd, f"没有异常表：{anomaly}"), []
    rows, problems = load_anomaly(anomaly)
    empty = [r["n"] for r in rows if not r["concl"] or r["concl"] in ("—", "-")]
    att = anomaly.name
    if problems:
        shown = "；".join(problems[:5]) + (f"；…共 {len(problems)} 处" if len(problems) > 5 else "")
        return {"result": "FAIL", "number": f"异常表格式有问题：{shown}", "cmd": cmd, "attach": att}, rows
    if not rows:
        return {"result": "FAIL", "number": "异常表里没有数据行", "cmd": cmd, "attach": att}, rows
    if empty:
        return {"result": "FAIL", "number": f"异常表 {len(rows)} 行，第 {','.join(empty)} 行没有结论",
                "cmd": cmd, "attach": att}, rows
    return {"result": "PASS", "number": f"异常表 {len(rows)} 行，每行都有结论", "cmd": cmd, "attach": att}, rows


def _r2(book, rows) -> dict:
    cmd = "python -m open_guji_cv.gates.query（gate_summary／blocked_units，三道闸）"
    try:
        from open_guji_cv.gates.query import blocked_units
        from open_guji_cv.products.store import ProductStore
        store = ProductStore()
        units: dict[tuple[int, int | None], list[str]] = {}
        for g in GATES:
            for u in blocked_units(book, None, store, g):
                units.setdefault((u["page"], u.get("column")), []).append(f"{g}:{u['status']}")
    except Exception as e:  # noqa: BLE001
        return _fail(cmd, f"取闸数据出错：{type(e).__name__}: {e}")
    cov_pages, cov_cols = _coverage(rows)
    pg_units = sorted(k for k in units if k[1] is None)
    col_units = sorted(k for k in units if k[1] is not None)
    # 页级失败的页，其列级失败随页处理，不再单独要求
    col_units = [k for k in col_units if (k[0], None) not in units]
    miss = [f"p{p}" for p, _ in pg_units if p not in cov_pages] + \
           [f"p{p} col{c}" for p, c in col_units if (p, c) not in cov_cols]
    desc = f"三道闸共 {len(pg_units)} 页＋{len(col_units)} 列失败"
    if not (pg_units or col_units):
        return {"result": "PASS", "number": "三道闸无失败页／列", "cmd": cmd, "attach": ""}
    if miss:
        return {"result": "FAIL", "cmd": cmd, "attach": "",
                "number": f"{desc}；异常表里找不到去向的 {len(miss)} 处：{'、'.join(miss[:20])}{'…' if len(miss) > 20 else ''}"}
    return {"result": "PASS", "cmd": cmd, "attach": "异常表",
            "number": f"{desc}，全部在异常表有结论的行里出现"}


def _r6(book, rows) -> dict:
    """R6 整页整列不丢字不错位（GUJI-661）：`ops/col_gate` 扫 Step3，报出的每一列要么异常表有结论，要么别报。"""
    cmd = "python scripts/zhengli/col_gate.py --book <册>（open_guji_cv/ops/col_gate.py）"
    try:
        from open_guji_cv.ops.col_gate import scan_book
        found, n = scan_book(book)
    except Exception as e:  # noqa: BLE001
        return _fail(cmd, f"扫描出错：{type(e).__name__}: {e}")
    if not n:
        return _fail(cmd, "没有 Step3 产物可扫")
    cov_pages, cov_cols = _coverage(rows)
    miss = []
    for f in found:
        p, c = f["page"], f.get("col")
        if (c is not None and (p, c) in cov_cols) or (c is None and p in cov_pages):
            continue
        miss.append(f"p{p}" + (f" col{c}" if c is not None else f" 缺列@x{f.get('x0')}") + f"（{'丢字 ' + str(f['n']) if f['kind'] == 'dropped' else '整列没切出'}）")
    if not miss:
        return {"result": "PASS", "cmd": cmd, "attach": "",
                "number": f"扫 {n} 页，报 {len(found)} 处，全部在异常表有结论" if found else f"扫 {n} 页，无整列丢字"}
    return {"result": "FAIL", "cmd": cmd, "attach": "",
            "number": f"扫 {n} 页，报 {len(found)} 处；异常表里找不到去向的 {len(miss)} 处：{'、'.join(miss[:20])}{'…' if len(miss) > 20 else ''}"}


# ---------------------------------------------------------------- R3
def _r3(cc, export_dir: Path | None, reason: str | None) -> dict:
    cmd = "guji close-check（第 2 项 class_counts）；总格数取导出 pages.json"
    item = next((it for it in (cc or {}).get("items", []) if it["no"] == "2"), None)
    if item is None or item["status"] in ("error", "skip") or not item.get("data"):
        why = f"{item['status']}：{item['detail']}" if item else "close-check 没出第 2 项"
        return {"result": "FAIL", "number": f"取不到待审数（{why}）", "reason": "", "cmd": cmd, "attach": ""}
    cc_counts = item["data"]
    n = sum(cc_counts.values())
    total = None
    if export_dir:
        for pj in export_dir.glob("*.pages.json"):
            d = json.loads(pj.read_text(encoding="utf-8"))
            total = (total or 0) + sum(len(p["cells"]) for p in d["pages"])
    if not total:
        return {"result": "FAIL", "number": f"待审 {n} 格，但取不到总格数（导出 pages.json 缺）", "reason": "",
                "cmd": cmd, "attach": ""}
    m = re.search(r"看图判错\s*(\d+)", item["detail"])
    nv = f"；其中看图判错 {m.group(1)}" if m else ""
    rate = n / total * 100
    verdict = "达标" if rate < 1 else "未达标"
    cls = "、".join(f"{CLASS_ZH.get(k, k)} {v}" for k, v in sorted(cc_counts.items(), key=lambda kv: -kv[1]))
    r = f"{n} 格分类（根因未逐类核）：{cls}。"
    r += reason if reason else "（原因归并待人补一行：--reason）"
    return {"result": "REPORT", "cmd": cmd, "attach": "",
            "number": f"待审 {n} 格 / {total} 格 = {rate:.2f}%（目标<1%，{verdict}{nv}）", "reason": r}


# ---------------------------------------------------------------- 主函数
def collect(book: str, ws, export_dir=None, anomaly=None, reason: str | None = None,
            guji: str = "guji", pending=None, cc_json=None) -> dict:
    ws = Path(ws)
    os.environ["GUJI_WORKSPACE"] = str(ws)      # 进程内调 cv（R2）要它；guji 子命令走 -w
    export_dir = Path(export_dir) if export_dir else None
    anomaly = Path(anomaly) if anomaly else None
    export_err = _export(book, ws, export_dir, guji) if export_dir else "没给 --export-dir"
    if cc_json:     # 复用已跑好的 `close-check --tier rough --json`（一遍约 5 分钟，zl.py close 步已跑过）
        cc, cc_err = _json_after_header(Path(cc_json).read_text(encoding="utf-8")), None
        cc["_tier_native"] = cc.get("tier") == "rough"
        cc_cmd = f"guji close-check {book} -w $WS --json --tier {cc.get('tier', 'final')}（复用 {Path(cc_json).name}）"
    else:
        cc, cc_cmd, cc_err = _close_check(book, ws, export_dir if not export_err else None, guji,
                                        pending=pending)
    r4, rows = _r4(anomaly)
    items = {
        "R1": _r1(book, ws, cc, guji),
        "R2": _r2(book, rows),
        "R3": _r3(cc, export_dir, reason),
        "R4": r4,
        "R5": _r5(cc, cc_cmd, cc_err, export_err),
        "R6": _r6(book, rows),
    }
    gen = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%m-%d %H:%M PDT")
    return {"book": book, "cv_version": _cv_version(), "generated": gen, "items": items, "pins": _pins(book)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--export-dir", help="导出目录；没有 lines.md 就现跑 guji export format")
    ap.add_argument("--anomaly", help="R4 异常表：.json（推荐，格式错报行号）或 .md（| # | 现象 | 原因 | 结论 |）")
    ap.add_argument("--reason", help="R3 原因归并一句话（人写）")
    ap.add_argument("--pending", help="原样转给 close-check 第 2c 项（□去向，GUJI-624）；不给时 close-check 缺省读中心库"
                                      "本册本章的待审单（数据目录 feedback/lists/proofing/<书>/<章>.pending.json，GUJI-711）")
    ap.add_argument("--guji", default="guji")
    ap.add_argument("--close-check-json", help="已跑好的 close-check --json 输出文件：复用它，不再跑一遍（约 5 分钟）")
    ap.add_argument("-o", "--out", help="input.json 输出路径（缺省打印到 stdout）")
    ap.add_argument("--report", help="同时用 exit_report.py 拼出 Markdown 报告到此路径")
    a = ap.parse_args(argv)
    data = collect(a.book, a.workspace, a.export_dir, a.anomaly, a.reason, a.guji, a.pending, a.close_check_json)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    elif not a.report:
        print(text)
    if not a.report:
        return 0
    if not a.out:
        print("--report 需要同时给 -o", file=sys.stderr)
        return 2
    spec = importlib.util.spec_from_file_location("exit_report", Path(__file__).with_name("exit_report.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(a.out)
    Path(a.report).write_text(buf.getvalue(), encoding="utf-8")
    print(buf.getvalue())
    return rc


if __name__ == "__main__":
    sys.exit(main())
