# -*- coding: utf-8 -*-
"""报告的两张静态图，纯 SVG、零依赖（仓里没有 matplotlib）：

- `forest`：每个指标 × 范围一行，点 = 变体减基线的差（百分点），横线 = 页簇配对自助法 95% CI，
  竖线 = 0。单系列，不要图例。
- `channels`：按通道的放行格数，基线与变体两根并排横条（分类色第 1、2 位，带图例）。

颜色走 skill `dataviz` 的参考调色板，亮暗两套写在 SVG 自己的 `<style>` 里（`prefers-color-scheme`），
数字与标签用文字色，不用系列色。
"""
from __future__ import annotations

from html import escape

STYLE = """<style>
.s{fill:#fcfcfb}.t{fill:#0b0b0b}.t2{fill:#52514e}.m{fill:#898781}.g{stroke:#e1e0d9}.z{stroke:#898781}
.c1{fill:#2a78d6;stroke:#2a78d6}.c2{fill:#eb6834}
@media (prefers-color-scheme:dark){.s{fill:#1a1a19}.t{fill:#fff}.t2{fill:#c3c2b7}.g{stroke:#2c2c2a}
.c1{fill:#3987e5;stroke:#3987e5}.c2{fill:#d95926}}
text{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;font-size:12px}
</style>"""

SCOPE_ZH = {"body": "正文", "nonbody": "非正文", "all": "全部", "unknown": "页型未知"}
METRIC_ZH = {"admit_rate": "放行率", "review_rate": "送审率", "admit_err_rate": "放行错误率"}


def _svg(w: int, h: int, body: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{escape(title)}">{STYLE}<title>{escape(title)}</title>'
            f'<rect class="s" width="{w}" height="{h}"/>{body}</svg>')


def forest(comp: dict, base: str, variant: str) -> str:
    rows = []
    for sc in ("body", "nonbody"):
        blk = comp["overall"].get(sc)
        if not blk:
            continue
        for m, zh in METRIC_ZH.items():
            b = blk[m]
            rows.append((f"{zh}·{SCOPE_ZH[sc]}", b["diff"], b["ci"], b.get("no_power")))
    vals = [abs(x) for _, d, ci, _ in rows for x in ([d] if d is not None else []) + (list(ci) if ci else [])]
    span = max(vals + [0.001]) * 1.15
    W, L, R, top, rh = 720, 130, 190, 34, 26
    H = top + rh * len(rows) + 30
    pw = W - L - R

    def x(v):
        return L + (v + span) / (2 * span) * pw
    out = [f'<text class="t" x="12" y="20" font-weight="600">{escape(variant)} − {escape(base)}：差值与 95% CI（百分点）</text>']
    for i in range(len(rows) + 1):
        y = top + i * rh
        out.append(f'<line class="g" x1="{L}" x2="{W - R}" y1="{y}" y2="{y}" stroke-width="1"/>')
    out.append(f'<line class="z" x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{top}" y2="{top + rh * len(rows)}" stroke-width="1"/>')
    for i, (label, d, ci, nop) in enumerate(rows):
        cy = top + i * rh + rh / 2
        out.append(f'<text class="t2" x="{L - 8}" y="{cy + 4:.1f}" text-anchor="end">{escape(label)}</text>')
        if d is None:
            out.append(f'<text class="m" x="{x(0) + 6:.1f}" y="{cy + 4:.1f}">无检验力</text>')
            continue
        if ci:
            out.append(f'<line class="c1" x1="{x(ci[0]):.1f}" x2="{x(ci[1]):.1f}" y1="{cy:.1f}" y2="{cy:.1f}" stroke-width="2" stroke-linecap="round"/>')
        out.append(f'<circle class="c1" cx="{x(d):.1f}" cy="{cy:.1f}" r="4.5"/>')
        txt = f"{d * 100:+.2f}" + (f" [{ci[0] * 100:+.2f}, {ci[1] * 100:+.2f}]" if ci else "")
        out.append(f'<text class="t2" x="{W - R + 8}" y="{cy + 4:.1f}">{escape(txt)}</text>')
    yb = top + rh * len(rows) + 18
    for v in (-span, 0, span):
        out.append(f'<text class="m" x="{x(v):.1f}" y="{yb}" text-anchor="middle">{v * 100:+.2f}</text>')
    return _svg(W, H, "".join(out), f"{variant} 相对 {base} 的指标差值")


def channels(comp: dict, base: str, variant: str, top_n: int = 12) -> str:
    rows = comp["by_channel"][:top_n]
    if not rows:
        return _svg(320, 40, '<text class="m" x="12" y="24">没有放行格</text>', "按通道放行格数")
    mx = max(max(r["A"], r["B"]) for r in rows) or 1
    W, L, R, top, bh, gap = 640, 130, 60, 52, 9, 2
    rh = bh * 2 + gap + 10
    H = top + rh * len(rows) + 8
    pw = W - L - R
    out = [f'<text class="t" x="12" y="20" font-weight="600">按通道的放行格数</text>',
           f'<rect class="c1" x="{L}" y="30" width="10" height="10" rx="2"/><text class="t2" x="{L + 14}" y="39">{escape(base)}</text>',
           f'<rect class="c2" x="{L + 80}" y="30" width="10" height="10" rx="2"/><text class="t2" x="{L + 94}" y="39">{escape(variant)}</text>']
    for i, r in enumerate(rows):
        y = top + i * rh
        out.append(f'<text class="t2" x="{L - 8}" y="{y + bh + 4}" text-anchor="end">{escape(r["channel"])}</text>')
        for j, (k, cls) in enumerate((("A", "c1"), ("B", "c2"))):
            w = max(1.0, r[k] / mx * pw) if r[k] else 0
            yy = y + j * (bh + gap)
            if w:
                out.append(f'<rect class="{cls}" x="{L}" y="{yy}" width="{w:.1f}" height="{bh}" rx="2"/>')
        d = r["B"] - r["A"]
        if d:
            out.append(f'<text class="t2" x="{L + max(r["A"], r["B"]) / mx * pw + 6:.1f}" y="{y + bh + 4}">{d:+d}</text>')
    return _svg(W, H, "".join(out), "按通道放行格数")
