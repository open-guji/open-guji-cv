# -*- coding: utf-8 -*-
"""把 `border-detection/bottom-offset` 的 68 条人工金标转成**绝对页面坐标**并冻结。

## 为什么要单独冻结一份

`items.jsonl` 存的 `y_left`/`y_right` 是标注时"通栏带裁剪图坐标"，不是绝对
页面坐标——裁剪图的 `crop_top` 本身是标注当时的算法输出（`res.bottom`）现算
出来的（公式见 `open_guji_cv/review/border_cards.py::page_bottom_cards`），
没有存进金标 JSON。想要绝对坐标就必须用同一份公式反推 `crop_top`，而这个
反推依赖"当时用来算 `res.bottom` 的那份代码"——**不是现在仓库里的代码**。
这一点在本轮踩了一次实的坑，记录下来防止后人重蹈：

## ⚠️ 真实踩过的坑：用"现在的代码"反推，会拿到错误的 crop_top

第一版尝试直接用当前 `open_guji_cv.utils.border_geometry.detect_borders`
现跑一遍拿 `res.bottom`。表面上很合理："`detect_borders` 是纯函数，同一张
原图+同一份代码=同一个结果，跟磁盘上产物的 mtime 无关"——这个论证本身没错，
**但少想了一步：产物写下的时间点和标注发生的时间点之间，代码本身可能已经
改过**。核实过程：

1. 68 条标注全部发生在 2026-09-12T02:50~02:59 UTC（`items.jsonl` 的
   `history[].ts`）。
2. `git log` 一开始只看到"标注之后没有 commit 碰 border_geometry.py/
   peak_line_search.py"，像是安全的——**但漏算了本地时区**：
   `git log --since` 默认按本地墙钟解释时间，而本仓提交都是 `-0700`
   时区，跟标注时间戳的 UTC 没对齐，筛漏了紧跟在标注之后的三个提交。
3. 改用"每个提交的 committer date 转 UTC 再比较"重新筛，找到
   `41695c0949`（2026-09-12T03:29:07 UTC，仅比最晚一条标注晚 30 分钟）
   **确实改了 `find_horizontal_border`**——新增"搜索带边界锁死"修复
   （`boundary_slack` 那段），提交信息里点名的两个实测页正是
   `vol03/7`、`vol02/26`。
4. 直接证据：`products/vol02/border_detect/_manifest.jsonl` 里 `p0026`
   有 4 条历史记录，`code_rev` 从 `1d404fe0fa` 变到 `575a4f6269` 时
   **sha256 跟着变了**——同一张原图，边界锁死修复上线前后 `res.bottom`
   真的不一样（vol02/26 实测：修复前 y≈2589~2602，修复后 y≈2698~2711，
   差 100+px）。拿修复后的值反推 `crop_top`，再加标注时的相对坐标，会把
   绝对坐标算到**页面空白处**（本轮拿 vol02/26 验证时肉眼查过：算出来的
   "金标"落在墨量为 0 的纯白区域，明显不对，才顺藤摸瓜查出这个坑）。

**结论：68 条标注全部发生在 `41695c0949` 之前，必须用那个提交之前
（`41695c0949^`）的 `peak_line_search.py`/`border_geometry.py` 现跑
`detect_borders` 来反推 `crop_top`，不能用当前代码、也不能直接信磁盘上
`border_detect` 产物（它可能已经被后续任何一次 `--force` 重算覆盖成
新代码的结果）。**本脚本用 `git show <rev>:path` 把旧版模块单独落盘到
临时目录、动态 import，在不改动当前工作区代码的情况下跑出"标注当时"的
`res.bottom`。

## 转换可信性的验证

1. 用旧版代码反推的 `crop_top`，vol02/26 换算出的绝对坐标 y≈2721.8/2733.4，
   正好落在页面上那条清晰可见的实体版框墨条（实测墨量峰值区间
   y≈2745~2770）附近——跟视觉位置吻合，不再是空白纸面。
2. `--verify` 会在若干页面上画出"转换后的绝对坐标"叠加图，人眼确认
   落在版框线视觉位置上。

## 用法

    python scripts/freeze_bottom_offset_gold.py
        # 生成 open-guji-dataset/border-detection/bottom-offset/frozen_absolute.jsonl

    python scripts/freeze_bottom_offset_gold.py --verify vol02:26,vol03:7
        # 额外画几张核对图到 /tmp，人工确认坐标落点
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.core.book import load_book  # noqa: E402

GOLD_DIR = ROOT.parent / "open-guji-dataset" / "border-detection" / "bottom-offset"
SRC = GOLD_DIR / "items.jsonl"
OUT = GOLD_DIR / "frozen_absolute.jsonl"
PAGE_BAND_MARGIN = 260  # 必须跟 border_cards.py::page_bottom_cards 完全一致

# 68 条标注全部发生在这个提交之前（见上面模块 docstring 的坑）——反推
# crop_top 必须用它的"上一个版本"，不能用 HEAD。写死而不是每次现查，
# 是因为这是本批金标的固有属性，不随后续改动变化。
LABEL_TIME_PARENT_REV = "41695c0949^"


def _load_prefix_module():
    """把标注当时（`LABEL_TIME_PARENT_REV`）的 peak_line_search.py +
    border_geometry.py 落到临时目录、动态 import，不碰当前工作区文件。"""
    tmp = Path(tempfile.mkdtemp(prefix="pls_prefix_"))
    pls_src = subprocess.run(
        ["git", "show", f"{LABEL_TIME_PARENT_REV}:open_guji_cv/utils/peak_line_search.py"],
        cwd=ROOT, capture_output=True, check=True, encoding="utf-8").stdout
    bg_src = subprocess.run(
        ["git", "show", f"{LABEL_TIME_PARENT_REV}:open_guji_cv/utils/border_geometry.py"],
        cwd=ROOT, capture_output=True, check=True, encoding="utf-8").stdout
    bg_src = bg_src.replace("from .peak_line_search import", "from peak_line_search_prefix import")
    (tmp / "peak_line_search_prefix.py").write_text(pls_src, encoding="utf-8")
    (tmp / "border_geometry_prefix.py").write_text(bg_src, encoding="utf-8")

    sys.path.insert(0, str(tmp))
    # 先 import peak_line_search_prefix 让它正常挂进 sys.modules（普通 import，
    # 不用 spec 手动跑）——dataclass 内部会用 cls.__module__ 去 sys.modules 反查
    # 自己的模块做类型解析，手动 exec_module 不挂 sys.modules 会导致 KeyError。
    import peak_line_search_prefix  # noqa: F401
    spec = importlib.util.spec_from_file_location(
        "border_geometry_prefix", tmp / "border_geometry_prefix.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["border_geometry_prefix"] = mod
    spec.loader.exec_module(mod)
    return mod


_PREFIX_MOD = _load_prefix_module()


# 2026-09-13 又标了一批（vol02/71-188 共 120 条，另有 64/70 两条改标到外边框）。
# **这批的参照系跟 09-12 那批不同**：09-12 标注时下版框跨页先验救援还不存在，
# 09-13 标注时控制台读的已经是带救援的代码。crop_top 依赖标注当时的 `res.bottom`，
# 所以必须**按每条标注自己的时间**选版本，不能一刀切——这正是上一轮栽过的坑
# 的同一个形状（当时是"标注后 30 分钟代码改过"，这次是"两批标注隔着一次改动"）。
RESCUE_LANDED = "2026-09-13"      # 这天起的标注按"带救援"的当前代码反推
BOOK_GAP = {"vol01": 325.0, "vol02": 328.0, "vol03": 326.0}   # 与 books/*.yaml 一致


def _labelled_after_rescue(item: dict) -> bool:
    """这条标注是不是在救援上线之后做的（按 history 里最后一次改动的时间）。"""
    ts = [h.get("ts", "") for h in item.get("history", [])]
    return bool(ts) and max(ts) >= RESCUE_LANDED


def crop_top_for(book: str, page: int, after_rescue: bool) -> float | None:
    """复刻 `page_bottom_cards` 里的 crop_top 公式，用**标注当时**的 `detect_borders`
    （见模块 docstring"真实踩过的坑"）——不读磁盘产物，每次现跑对应版本的算法。

    `after_rescue`：True 用当前代码（带下版框救援，需传 book_gap），False 用
    `LABEL_TIME_PARENT_REV` 那个版本（救援尚不存在）。
    """
    b = load_book(book)
    gray = cv2.imread(str(b.raw_path(page)), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    h, w = gray.shape
    if after_rescue:
        from open_guji_cv.utils.border_geometry import detect_borders as _cur
        bottom = _cur(gray, expected_cols=9, book_bottom_gap=BOOK_GAP.get(book)).bottom
    else:
        bottom = _PREFIX_MOD.detect_borders(gray, expected_cols=9).bottom
    y_right = bottom.y_at_right
    y_left = bottom.y_at_right + bottom.slope * (w - 1)
    return max(0.0, min(y_left, y_right) - PAGE_BAND_MARGIN)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verify", default="", help="book:page,book:page 逗号分隔，画核对图")
    a = ap.parse_args()

    items = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
    out_lines = []
    missing = []
    for d in items:
        book, page = d["anchor"]["book"], d["anchor"]["page"]
        exp = d["expected"]
        if "y_left" not in exp or "y_right" not in exp:
            missing.append((book, page, "expected 缺 y_left/y_right"))
            continue
        after = _labelled_after_rescue(d)
        crop_top = crop_top_for(book, page, after)
        if crop_top is None:
            missing.append((book, page, "原图或产物缺失"))
            continue
        rec = dict(book=book, page=page,
                   y_left_abs=round(exp["y_left"] + crop_top, 2),
                   y_right_abs=round(exp["y_right"] + crop_top, 2),
                   crop_top=round(crop_top, 2),
                   verdict=exp.get("verdict"),
                   ref="rescue" if after else "prefix")   # 这条用了哪个参照系
        out_lines.append(rec)

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out_lines) + "\n",
                   encoding="utf-8")
    print(f"冻结 {len(out_lines)}/{len(items)} 条 → {OUT}")
    if missing:
        print(f"跳过 {len(missing)} 条：")
        for m in missing:
            print(" ", m)

    if a.verify:
        verify_dir = Path("/tmp/bottom_offset_verify")
        verify_dir.mkdir(parents=True, exist_ok=True)
        by_key = {(r["book"], r["page"]): r for r in out_lines}
        for spec in a.verify.split(","):
            book, page_s = spec.split(":")
            page = int(page_s)
            r = by_key.get((book, page))
            if r is None:
                print(f"验证跳过 {book}/{page}：未冻结")
                continue
            b = load_book(book)
            gray = cv2.imread(str(b.raw_path(page)), cv2.IMREAD_GRAYSCALE)
            h, w = gray.shape
            y0 = int(min(r["y_left_abs"], r["y_right_abs"])) - 80
            y1 = int(max(r["y_left_abs"], r["y_right_abs"])) + 80
            y0, y1 = max(0, y0), min(h, y1)
            strip = cv2.cvtColor(gray[y0:y1], cv2.COLOR_GRAY2BGR)
            # 画金标线：两点 (x=0, y_right_abs) 与 (x=w-1, y_left_abs)（新坐标系
            # x 向左递增，参见 border_geometry.py 顶部注释）——这里仍在旧坐标画，
            # 旧坐标 x=0 对应新坐标 x=w-1，所以 (旧x=0)→y_right_abs、(旧x=w-1)→y_left_abs。
            x0, x1 = 0, w - 1
            yy0, yy1 = int(round(r["y_right_abs"])) - y0, int(round(r["y_left_abs"])) - y0
            cv2.line(strip, (x0, yy0), (x1, yy1), (0, 0, 235), 2)
            out_path = verify_dir / f"{book}_{page}.jpg"
            cv2.imwrite(str(out_path), strip, [cv2.IMWRITE_JPEG_QUALITY, 90])
            print(f"核对图 → {out_path}（红线=转换后的绝对坐标金标线）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
