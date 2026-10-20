"""实验记录：每存一份产物包，就在工作区仓（guji-workspace）里留一页 `experiments/<册>/<标签>.md`。

为什么（sheldon 10-20）：工作区仓要记录跑过哪些实验。每个实验的配置和最终报告按标签分开，积累在仓里，
谁 clone 都能看到别人正在做和做完的实验、历史。具体数据不在这里：产物在 R2 的产物包，人裁、字形库在中心库。

一页记：开头的「摘要」（`--summary` 写的目的、改了什么、结论；给了 `--report` 时自动加结果一行）、
各步最后一次跑的时间与耗时（从产物 manifest 读，看得出这一轮从哪步起重跑）、标签、存包时刻与说明、
存包时的基线（该册 main）、三样版本（cv、语料库、字形库）和中心库 rev、存包时的册配置原文、
`guji products diff` 的报告。`pack promote` 再往页尾追一行「标为 main」。
（「每跑完一次都在记录里简单总结配置和结果，方便别人看」：sheldon 10-20。）
只写文件，不提交：提交、推送由跑实验的人做（工作区仓的提交规矩照旧）。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DIR = "experiments"

_README = """# 实验记录

每份产物包（`guji products pack push`）一页：`<册>/<标签>.md`。标签是 `cv<版本>-c<语料库号>-g<字形库号>-<改动名>`。
页里有这次的三样版本、中心库 rev、册配置、前后对比报告；`★ 标为 main` 的是该册当前的正式结果。

数据不在这里：产物用 `guji products pack fetch <册> --label <标签>` 取回，人裁、字形库在中心库（`guji db sync`）。
方法见 ai-team `domain/CV/规范/受控重跑方法论.md`、cv `doc/受控重跑.md`。
"""


def record_path(ws_root: Path, book: str, label: str) -> Path:
    return Path(ws_root) / DIR / book / f"{label}.md"


def _ver_table(v: dict) -> list[str]:
    def g(k):
        x = v.get(k)
        return "—" if x is None or x == "" else str(x)
    revs = v.get("db_revs") or {}
    rev_s = "、".join(f"{k}（{n} 页）" for k, n in sorted(revs.items(), key=lambda kv: -kv[1])) or g("db_rev")
    return ["| cv | cv commit | 语料库 | 底库 | 字形库钉号 | 人裁指纹 | 中心库 rev（seed_admit 跑时） |",
            "|---|---|---|---|---|---|---|",
            f"| {g('cv')} | {g('cv_commit')[:12]} | {g('corpus')} | {g('corpus_base')} | {g('glyph_pin')} | "
            f"{g('human_fp')} | {rev_s} |"]


def _la(ts: float) -> str:
    """洛杉矶时间（规矩：时间一律写洛杉矶）。夏令时按美国规则粗算：3 月第二个周日到 11 月第一个周日。"""
    u = datetime.fromtimestamp(ts, timezone.utc)
    y = u.year
    def nth_sunday(month, n):
        d = datetime(y, month, 1, tzinfo=timezone.utc)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    dst = nth_sunday(3, 2) + timedelta(hours=10) <= u < nth_sunday(11, 1) + timedelta(hours=9)
    return (u - timedelta(hours=7 if dst else 8)).strftime("%m-%d %H:%M")


def run_table(products_root: Path, book: str) -> list[str]:
    """各步最后一次跑：页数、cv 版本、起止时刻（洛杉矶）、耗时合计。看得出这一轮从哪步起重跑、哪步最慢。"""
    d = Path(products_root) / book
    rows = []
    for m in sorted(d.glob("*/_manifest.jsonl")):
        last: dict = {}
        for ln in m.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("status") == "ok" and r.get("ts"):
                last[r.get("key")] = r
        if not last:
            continue
        ts = [r["ts"] for r in last.values()]
        el = [float(r.get("elapsed") or 0) for r in last.values()]
        cvs = sorted({str(r.get("cv_version")) for r in last.values() if r.get("cv_version")})
        rows.append((max(ts), m.parent.name, len(last), "、".join(cvs) or "—",
                     min(t - e for t, e in zip(ts, el)), sum(el)))
    if not rows:
        return []
    rows.sort()
    out = ["| 步 | 页 | cv | 最后一轮起 → 止（洛杉矶） | 耗时合计 |", "|---|---|---|---|---|"]
    for end, step, n, cv, start, cpu in rows:
        out.append(f"| {step} | {n} | {cv} | {_la(start)} → {_la(end)} | {cpu / 60:.1f} 分 |")
    return out


def result_line(report_dir: Path | None) -> str | None:
    """`guji products diff` 的 summary.json → 一行结果。"""
    f = Path(report_dir) / "summary.json" if report_dir else None
    if not f or not f.is_file():
        return None
    s = json.loads(f.read_text(encoding="utf-8"))
    a, b = s.get("a") or {}, s.get("b") or {}
    cols = s.get("columns") or {}
    fl = s.get("flips") or {}
    def rate(x):
        return f"{x['review_rate'] * 100:.2f}%" if x.get("review_rate") is not None else "?"
    ch = "、".join(f"{k} {v}" for k, v in cols.items() if k != "same" and v)
    return (f"送审 {a.get('review')} → {b.get('review')}（人审率 {rate(a)} → {rate(b)}）；"
            f"变了的列 {ch or '无'}；放行字变 {fl.get('放行字变', 0)}、"
            f"admit→review {fl.get('admit→review', 0)}、review→admit {fl.get('review→admit', 0)}")


def write_record(ws_root: Path, book: str, man: dict, *, base_label: str | None = None,
                 book_yaml: str | None = None, report_dir: Path | None = None,
                 summary: str | None = None, products_root: Path | None = None) -> Path:
    """`man` 是 `packs.push_products` 返回的包 manifest。已有同名页（同标签重存）整页重写。

    `summary`：人写的摘要（目的、改了什么、怎么跑、结论）；`products_root`：本次存包的产物根，读各步 manifest
    出「各步运行」表。"""
    ws_root = Path(ws_root)
    (ws_root / DIR).mkdir(parents=True, exist_ok=True)
    readme = ws_root / DIR / "README.md"
    if not readme.exists():
        readme.write_text(_README, encoding="utf-8")
    label = man["label"]
    res = result_line(report_dir)
    runs = run_table(products_root, book) if products_root else []
    lines = [f"# {label}", "", "## 摘要", ""]
    lines += [summary.strip(), ""] if summary else ["（存包时没给 `--summary`）", ""]
    if res:
        lines += [f"**结果**：{res}", ""]
    if runs:
        lines += ["**各步运行**（产物 manifest，最近一轮先后）：", "", *runs, ""]
    lines += ["## 基本信息", "",
             f"- 册：{book}",
             f"- 存包：{man.get('created', '')}" + (f"；说明：{man['note']}" if man.get("note") else ""),
             f"- 基线（存包时该册的 main）：{('`' + base_label + '`') if base_label else '—'}",
             f"- 包：`{man.get('name', '')}`（{man.get('files', '?')} 个文件，{(man.get('bytes') or 0) / 1e6:.1f} MB）"
             f"；取回 `guji products pack fetch {book} --label {label} --to <目录>`",
             "", "## 版本", "", *_ver_table(man.get("versions") or {}), ""]
    if book_yaml:
        lines += ["## 册配置（存包时）", "", "```yaml", book_yaml.rstrip("\n"), "```", ""]
    lines += ["## 前后对比", ""]
    rep = Path(report_dir) / "report.md" if report_dir else None
    if rep and rep.is_file():
        body = rep.read_text(encoding="utf-8").splitlines()
        if body and body[0].startswith("# "):
            body = body[1:]
        lines += [("#" + ln) if ln.startswith("#") else ln for ln in body]
    else:
        lines += ["（存包时没给 `--report <diff 目录>`）"]
    lines += ["", "## 记事", ""]
    p = record_path(ws_root, book, label)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def note_main(ws_root: Path, book: str, label: str, note: str = "") -> Path | None:
    """`pack promote`：在该标签那页尾追一行「★ 标为 main」。没有那页（老包）返回 None。"""
    p = record_path(ws_root, book, label)
    if not p.exists():
        return None
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"- {ts} ★ 标为 main" + (f"：{note}" if note else "") + "\n")
    return p
