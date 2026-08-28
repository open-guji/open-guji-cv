"""投影峰匹配找版框线：批量跑竖直界行/边框 + 上下边框，画到图上，出报告页。

核心算法在 `open_guji_cv/utils/peak_line_search.py`，算法设计记录见
`.claude/doc/peak_line_search.md`。这个脚本只是调用入口 + 画图 + 拼报告页。

用法：
    # 单页，只打印结果 + 存一张叠加图
    PYTHONIOENCODING=utf-8 python scripts/find_border_lines.py path/to/page.png \
        --expected-cols 9 --out overlay.png

    # 批量几页，出一份汇总报告（HTML，可发布成 Artifact）
    PYTHONIOENCODING=utf-8 python scripts/find_border_lines.py \
        --pages vol02/133:9 vol02/135:9 vol01/33:9 vol01/90:9 vol01/171:9 \
        --root /path/to/s3裁剪产物根目录 --report out_report.html
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from open_guji_cv.utils.peak_line_search import (
    LineMatch,
    find_horizontal_border,
    find_vertical_lines,
)

INK_THRESHOLD = 128  # 灰度 < 128 记黑


def analyze_page(gray: np.ndarray, expected_cols: int | None = None) -> dict:
    """跑一页：竖直线（界行+左右边框）+ 上下边框。返回可 JSON 化的结果。"""
    mask = (gray < INK_THRESHOLD).astype(np.float64)
    expected_lines = (expected_cols + 1) if expected_cols else None
    vlines = find_vertical_lines(mask, expected_count=expected_lines)
    top = find_horizontal_border(mask, "top")
    bottom = find_horizontal_border(mask, "bottom")
    return dict(
        h=gray.shape[0], w=gray.shape[1],
        vertical=[_match_to_dict(v) for v in vlines],
        top=_match_to_dict(top),
        bottom=_match_to_dict(bottom),
    )


def _match_to_dict(m: LineMatch) -> dict:
    return dict(position=m.position, slope=m.slope, angle_deg=m.angle_deg,
                score=m.score, width=m.width, proj=m.proj)


def draw_overlay(bgr: np.ndarray, result: dict) -> np.ndarray:
    """把竖直线 + 上下边框画在原图上（BGR）。"""
    vis = bgr.copy()
    h, w = vis.shape[:2]
    yc, xc = h / 2.0, w / 2.0

    for v in result["vertical"]:
        y1, y2 = 0, h - 1
        x1 = v["position"] + v["slope"] * (y1 - yc)
        x2 = v["position"] + v["slope"] * (y2 - yc)
        cv2.line(vis, (int(round(x1)), y1), (int(round(x2)), y2), (235, 170, 40), 3, cv2.LINE_AA)

    for key, color in (("top", (0, 210, 230)), ("bottom", (60, 220, 60))):
        b = result[key]
        x1, x2 = 0, w - 1
        y1 = b["position"] + b["slope"] * (x1 - xc)
        y2 = b["position"] + b["slope"] * (x2 - xc)
        cv2.line(vis, (int(x1), int(round(y1))), (int(x2), int(round(y2))), color, 3, cv2.LINE_AA)
    return vis


def _imread_gray(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        buf = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    return img


def _imread_bgr(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        buf = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img


def _build_report(pages: list[dict], out_path: Path) -> None:
    """拼一份多页汇总报告（内嵌 base64 图，单文件可直接发布）。"""
    sections = []
    for p in pages:
        img_b64 = base64.b64encode(cv2.imencode(".png", p["overlay_small"])[1]).decode()
        v_rows = "".join(
            f'<tr class="{"low" if v["width"]<=2 else ""}"><td>{v["position"]:+.1f}</td><td>{v["angle_deg"]:+.2f}°</td>'
            f'<td>{v["score"]:.1f}</td><td>{v["width"]:.0f}px</td></tr>'
            for v in p["result"]["vertical"])
        sections.append(f'''
        <section class="page-block">
          <div class="page-head">
            <h2>{p["name"]}</h2>
            <span class="tag">{p["tag"]}</span>
            <span class="badge">{len(p["result"]["vertical"])} 条竖直线</span>
          </div>
          <div class="row">
            <img class="full-img" src="data:image/png;base64,{img_b64}" alt="{p["name"]}">
            <div class="side">
              <div class="hb">
                <div class="hb-row {'low' if p["result"]["top"]["width"]<=2 else ''}"><span class="k">顶部边框</span>
                  y={p["result"]["top"]["position"]:+.1f}
                  ({p["result"]["top"]["angle_deg"]:+.2f}°)
                  分数 {p["result"]["top"]["score"]:.1f}
                  {'⚠ 宽度仅' + str(int(p["result"]["top"]["width"])) + 'px，疑似触边/低置信' if p["result"]["top"]["width"]<=2 else ''}</div>
                <div class="hb-row {'low' if p["result"]["bottom"]["width"]<=2 else ''}"><span class="k">底部边框</span>
                  y={p["result"]["bottom"]["position"]:+.1f}
                  ({p["result"]["bottom"]["angle_deg"]:+.2f}°)
                  分数 {p["result"]["bottom"]["score"]:.1f}
                  {'⚠ 宽度仅' + str(int(p["result"]["bottom"]["width"])) + 'px，疑似触边/低置信' if p["result"]["bottom"]["width"]<=2 else ''}</div>
              </div>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>位置</th><th>倾角</th><th>分数</th><th>宽</th></tr></thead>
                  <tbody>{v_rows}</tbody>
                </table>
              </div>
            </div>
          </div>
        </section>''')

    html = f'''<!doctype html>
<title>版框线批量检测</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  --bg: #f7f5f0; --surface: #ffffff; --surface-2: #f0ece3;
  --ink: #211d17; --muted: #746a5a; --border: #e3ddd0;
  --v-line: #d97a1f; --top-line: #1b8fa0; --bottom-line: #3f7a4e;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #17150f; --surface: #211d16; --surface-2: #2a251c;
    --ink: #ede6d8; --muted: #a89a82; --border: #3a3325;
    --v-line: #e6a04a; --top-line: #4fc4d8; --bottom-line: #6fbb84;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #17150f; --surface: #211d16; --surface-2: #2a251c;
  --ink: #ede6d8; --muted: #a89a82; --border: #3a3325;
  --v-line: #e6a04a; --top-line: #4fc4d8; --bottom-line: #6fbb84;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font-family: "Noto Sans SC", system-ui, sans-serif; line-height: 1.6; }}
main {{ max-width: 1200px; margin: 0 auto; padding: 48px 24px 88px; }}
h1 {{ font-size: 24px; font-weight: 700; margin: 0 0 8px; }}
.lede {{ color: var(--muted); font-size: 14px; max-width: 76ch; margin: 0 0 32px; line-height: 1.6; }}
.page-block {{ margin-bottom: 48px; padding-top: 24px; border-top: 1px solid var(--border); }}
.page-block:first-of-type {{ border-top: none; padding-top: 0; }}
.page-head {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }}
.page-head h2 {{ font-size: 19px; margin: 0; }}
.tag {{ font-size: 12px; padding: 3px 9px; border-radius: 4px; background: var(--surface-2); color: var(--muted); }}
.badge {{ font-size: 12px; padding: 3px 9px; border-radius: 999px; background: var(--surface-2); color: var(--muted); margin-left: auto; }}
.row {{ display: grid; grid-template-columns: 1.3fr 1fr; gap: 20px; }}
@media (max-width: 800px) {{ .row {{ grid-template-columns: 1fr; }} }}
.full-img {{ width: 100%; height: auto; border-radius: 6px; border: 1px solid var(--border); }}
.hb {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
  padding: 12px 14px; margin-bottom: 12px; font-size: 13px; }}
.hb-row {{ margin-bottom: 6px; }} .hb-row:last-child {{ margin-bottom: 0; }}
.hb-row .k {{ color: var(--muted); margin-right: 8px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 5px 8px; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; }}
tr.low td {{ color: #b23a2e; font-weight: 600; }}
.hb-row.low {{ color: #b23a2e; }}
</style>
<main>
  <h1>版框线批量检测（peak_line_search）</h1>
  <p class="lede">竖直线（橙）= 界行 + 左右边框；顶部边框（青）/ 底部边框（绿）。
  表格里标红的行是宽度 ≤2px 的低置信结果——真实版框线宽一般 4~9px，
  宽度异常窄往往意味着算法撞到了搜索窗口边界，不是真的找到一条线。</p>
  {"".join(sections)}
</main>
'''
    out_path.write_text(html, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", nargs="?", help="单页图片路径")
    ap.add_argument("--expected-cols", type=int, default=None, help="预期列数（有的话更准）")
    ap.add_argument("--out", type=Path, default=None, help="单页叠加图输出路径")
    ap.add_argument("--pages", nargs="*", default=None,
                     help="批量模式：book/page:expected_cols 列表，如 vol02/133:9")
    ap.add_argument("--root", type=Path, default=None, help="批量模式：<root>/<book>/<page>.png")
    ap.add_argument("--report", type=Path, default=None, help="批量模式：报告输出路径")
    ap.add_argument("--display-scale", type=float, default=0.6, help="报告里图片缩放比例")
    args = ap.parse_args()

    if args.pages:
        assert args.root and args.report, "--pages 需要同时给 --root 和 --report"
        pages = []
        for spec in args.pages:
            name, _, cols = spec.partition(":")
            expected_cols = int(cols) if cols else None
            book, page = name.split("/")
            img_path = args.root / book / f"{page}.png"
            gray = _imread_gray(img_path)
            bgr = _imread_bgr(img_path)
            result = analyze_page(gray, expected_cols=expected_cols)
            overlay = draw_overlay(bgr, result)
            h, w = overlay.shape[:2]
            small = cv2.resize(overlay, (int(w * args.display_scale), int(h * args.display_scale)))
            print(f"{name}: {len(result['vertical'])} 条竖直线, "
                  f"top y={result['top']['position']:.1f}, bottom y={result['bottom']['position']:.1f}")
            pages.append(dict(name=name, tag=f"{expected_cols or '?'} 列",
                               result=result, overlay_small=small))
        _build_report(pages, args.report)
        print("written", args.report)
        return

    assert args.image, "单页模式需要给图片路径"
    gray = _imread_gray(Path(args.image))
    bgr = _imread_bgr(Path(args.image))
    result = analyze_page(gray, expected_cols=args.expected_cols)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        overlay = draw_overlay(bgr, result)
        cv2.imwrite(str(args.out), overlay)
        print("written", args.out)


if __name__ == "__main__":
    main()
