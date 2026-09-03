"""统一评测报告。

手册里三条量法纪律，在这里变成字段而不是靠人记：

- **比值要连着分母读**：每个指标带 `numerator` / `denominator`，没有分母的指标标出来；
- **分层的分层报**：`strata` 里逐层给数，不合成一个总数；
- **先查漂移再谈数字**：`stale_gold` / `uncertain_skipped` 必填，为 None 表示没查过，
  报告会显式说「未查漂移」而不是假装干净。
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field


@dataclass
class Metric:
    name: str
    value: float | str | None
    numerator: int | None = None
    denominator: int | None = None
    unit: str = ""          # "%" / "px" / ""
    note: str = ""

    def fmt(self) -> str:
        v = self.value
        s = f"{v:.4g}{self.unit}" if isinstance(v, (int, float)) else str(v)
        if self.denominator is not None:
            frac = f"{self.numerator}/{self.denominator}" if self.numerator is not None else f"n={self.denominator}"
            s += f"（{frac}）"
        return s


@dataclass
class EvalReport:
    eval_id: str
    shard: str
    # ok      跑通了，指标见 metrics
    # regressed 跑通了，但**评测结论是不合格**（回归门失败等）——这是有效结果，
    #           不是运行失败；混为一谈会让「门坏了」和「门拦住了」看起来一样
    # failed  没跑起来（缺产物 / 报错 / 解析不出指标）
    # skipped 前提不满足，没跑
    status: str = "ok"                       # ok | regressed | failed | skipped
    gate: str = ""                           # 回归门结论原文
    metrics: list[Metric] = field(default_factory=list)
    strata: dict[str, list[Metric]] = field(default_factory=dict)
    n_gold: int | None = None
    stale_gold: int | None = None            # None = 没查过漂移
    uncertain_skipped: int | None = None
    baseline_delta: dict[str, float] = field(default_factory=dict)
    elapsed: float = 0.0
    exit_code: int | None = None
    command: str = ""
    stdout_tail: str = ""
    error: str = ""
    ts: float = field(default_factory=time.time)

    def metric(self, name: str) -> Metric | None:
        return next((m for m in self.metrics if m.name == name), None)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["warnings"] = self.warnings()
        return d

    def warnings(self) -> list[str]:
        """报告自己会说出哪里不可信。"""
        w = []
        if self.stale_gold is None:
            w.append("未查金标漂移——上游重生过产物的话，这些数字可能挂在已失效的键上")
        elif self.stale_gold:
            w.append(f"{self.stale_gold} 条金标已过期（图变了），数字要打折扣")
        if self.uncertain_skipped:
            w.append(f"跳过 {self.uncertain_skipped} 条 uncertain（人工也判不准，不进指标）")
        if any(m.denominator is None for m in self.metrics):
            w.append("有指标没有分母，比值不可单独比较")
        return w

    def summary_line(self) -> str:
        head = f"{self.eval_id} · {self.shard}"
        if self.status != "ok":
            return f"{head}: {self.status} {self.error[:80]}"
        ms = "  ".join(f"{m.name} {m.fmt()}" for m in self.metrics[:4])
        return f"{head}: {ms}  ({self.elapsed:.1f}s)"


# ── 从 stdout 抠指标 ─────────────────────────────────────────────────
# 评测脚本各印各的，这里只认几种反复出现的形状；认不出就留空，
# **不猜**——报告里宁可少一个数，也不能给一个编的数。
_LINE_PATTERNS = [
    # 整行一个指标：「缺陷检出率 50%（316 个缺陷）」
    re.compile(r"^\s*(?P<name>[一-鿿\w /]+?)\s+(?P<val>[\d.]+)%(?:（(?P<den>\d+)\s*[^）]*）)?\s*$"),
    # 「界行落入列框: 0.57%」「均值：2.7px」
    re.compile(r"^\s*(?P<name>[一-鿿\w /]+?)[:：]\s*(?P<val>[\d.]+)(?P<unit>%|px)?\s*$"),
]
# 回归门类的分数形状：「回归门：31/31 通过」「全清页 36/39」。
# 这类评测的指标本来就是「几个里过了几个」，分子分母都在，正是报告要的。
_FRACTION = re.compile(r"(?P<name>[一-鿿][一-鿿\w ]{0,14}?)[:：]?\s*(?P<num>\d+)\s*/\s*(?P<den>\d+)")
# 「残余率（带框组仍有框渣）  0/55 (0%)」——名字带括号说明、分数后跟半角百分比。
# 全角括号的说明要先摘掉，否则名字会把说明吃进去。
_FRAC_PCT = re.compile(r"^\s*(?P<name>[一-鿿][^（(]{0,20}?)\s*(?:（[^）]*）)?\s+"
                       r"(?P<num>\d+)\s*/\s*(?P<den>\d+)\s*[(（]\s*(?P<pct>[\d.]+)%")
# 行内含多个字段：「all  页 36 列 290  列型准确率 91.4%  elastic P/R/F1 0.88/0.88/0.88」
# 这类行 eval_layout / eval_pagetype 都在用，整行正则认不出来。
_INLINE = re.compile(r"(?P<name>[一-鿿][一-鿿\w /]{1,14}?)\s+(?P<val>\d+(?:\.\d+)?)(?P<unit>%|px)")
# 行首的分层名：「body 页 12 列 108 …」
_STRATUM = re.compile(r"^\s*(?P<s>[a-z_]{3,14}|全部|总体)\s+页")


# 逐类明细行的表头词：这些行是「每一类各多少」，不是总体指标。
# 抓进来会把六行同名的「策略判对」堆满 limit，把真正的总体指标挤掉。
_DETAIL_HEAD = re.compile(r"^\s{2,}\S+\s+\((?:切分|跳过|正例|缺陷)\)|^\s{2,}\w+\s+\(")


# 尾部汇总行：「review_recrop 40 条：含住+盖墨通过 33，未过但有 flag 兜底 1，无声放行 6」
# 「left-cut：穿边点 113，救回 83/96（86%），无承载格 17」
# 这类行在一堆逐条明细之后，是真正的总体结论；明细行数量多，会把 limit 吃光，
# 所以**先扫尾部汇总行**再扫其余。
_SUMMARY_HINT = re.compile(r"(通过|救回|命中|过闸|放行|检出|覆盖|穿边点|条：|：\s*\d)")
_KV = re.compile(r"(?P<name>[一-鿿][一-鿿\w +/-]{0,16}?)\s+(?P<num>\d+)(?:\s*/\s*(?P<den>\d+))?"
                 r"(?:（(?P<pct>[\d.]+)%）)?")


def _parse_summary_lines(lines: list[str], add) -> None:
    """扫尾部像汇总的行，抠出「名 数」「名 数/数（百分比）」。"""
    for line in lines:
        if not _SUMMARY_HINT.search(line) or line.strip().startswith(("✗", "✓", "-")):
            continue
        for m in _KV.finditer(line):
            name, num = m.group("name").strip(), int(m.group("num"))
            den = int(m.group("den")) if m.group("den") else None
            pct = m.group("pct")
            if pct is not None:
                add(name, float(pct), "%", den)
            elif den:
                add(name, round(100.0 * num / den, 2), "%", den)
            else:
                add(name, num, "")


def parse_metrics(text: str, limit: int = 12) -> list[Metric]:
    out: list[Metric] = []
    seen: set[str] = set()

    def add(name: str, val: float, unit: str = "", den: int | None = None) -> None:
        name = name.strip()
        if not name or name in seen or name.isdigit() or len(out) >= limit:
            return
        out.append(Metric(name=name, value=val, denominator=den, unit=unit))
        seen.add(name)

    for line in text.splitlines():
        line = line.rstrip()
        if not line or len(line) > 200 or len(out) >= limit:
            continue
        if _DETAIL_HEAD.match(line):
            continue          # 逐类明细，不是总体指标
        fp = _FRAC_PCT.match(line)
        if fp:
            add(fp.group("name"), float(fp.group("pct")), "%", int(fp.group("den")))
            if out:
                out[-1].numerator = int(fp.group("num"))
            continue
        fm = _FRACTION.search(line)
        if fm and "%" not in line:
            num, den = int(fm.group("num")), int(fm.group("den"))
            if den and num <= den:
                add(fm.group("name") or "通过率", round(100.0 * num / den, 2), "%", den)
                out[-1].numerator = num
                continue
        matched = False
        for pat in _LINE_PATTERNS:
            m = pat.match(line)
            if not m:
                continue
            g = m.groupdict()
            try:
                val = float(g["val"])
            except (TypeError, ValueError):
                break
            add(g["name"], val, g.get("unit") or ("%" if "%" in line else ""),
                int(g["den"]) if g.get("den") else None)
            matched = True
            break
        if matched:
            continue
        # 行内多字段：分层行给指标加前缀，免得 body / toc 的同名指标互相覆盖
        st = _STRATUM.match(line)
        prefix = f"{st.group('s')} " if st else ""
        n_cols = re.search(r"列\s+(\d+)", line)
        for m in _INLINE.finditer(line):
            try:
                val = float(m.group("val"))
            except ValueError:
                continue
            add(prefix + m.group("name"), val, m.group("unit"),
                int(n_cols.group(1)) if n_cols else None)

    # 兜底：正文里一个百分比指标都没抠到（全是逐条明细 + 一行尾部汇总），
    # 才去解析尾部汇总行。放在最后，免得把 instance_quality 那种本来就有
    # 「缺陷检出率 50%」的好指标挤掉。
    if not out:
        _parse_summary_lines([l for l in text.splitlines()[-8:] if l.strip()], add)
    return out
