# -*- coding: utf-8 -*-
"""康熙字典字頭切圖的交叉驗證：把「可能標錯的字」全部挑出來人審。

## 為什麼需要

`kangxi_headwords.py` 的賦字靠序列對齊（CNN 相似度 + Needleman–Wunsch），
抽檢估計錯標率約 1%。1% 對「訓練樣本 / 檢索模板」這類用途無所謂，但如果要
**確保每一個字都對**，就不能靠抽檢，必須逐條過三道獨立證據，任何一道不通過
就進人審隊列。自動方法無法自證 100%；本腳本做的是**讓錯誤可被發現**，
把「假設正確」變成「逐條驗過」。

## 三道獨立證據

| 道 | 證據 | 與對齊算法的獨立性 |
|---|---|---|
| A 字體模板 | 切圖 vs 該字四套字體渲染圖的 CNN embedding 餘弦 | 用同一網絡，但比的是**這一個字**，不受序列對齊影響 |
| B 字統網康熙 | 切圖 vs 字統網同名字的康熙切圖（70×70 縮圖）| **完全獨立**：字統網的標籤來自它自己的數據庫，與我們的對齊無關 |
| C 同字自洽 | 同一個字在 12 冊裡的多個切圖彼此相似度 | 獨立於單條匹配：同字多例互相印證，離群的那個可疑 |

判定（`verdict` 列）：
- `pass`   —— A 高分，且 B 存在時 B 也高分，且 C 不離群 → 可直接採信
- `review` —— 任一道低分 / B 與 A 衝突 / C 離群 → 進人審隊列
- `nob`    —— B 不存在（字統網沒有這個字），只有 A、C 通過 → 次級可信，可選擇性抽審

## 用法

    python scripts/kangxi_crossval.py --crops D:/data/glyph-sources/kangxi/crops \
        --zitools D:/data/glyph-sources/zitools/p1 D:/data/glyph-sources/zitools/p2 \
        --out D:/data/glyph-sources/kangxi/crossval
    python scripts/kangxi_crossval.py ... --review-html     # 出人審頁面

產物：
    crossval/report.tsv      逐字：char, file, simA, simB, simC, verdict, reason
    crossval/summary.txt     各檔計數
    crossval/review.html     人審頁面（切圖 + 字體渲染對照 + 分數），只列 review 檔
"""
from __future__ import annotations

import argparse
import base64
import collections
import csv
import glob
import os
import re
from pathlib import Path

import cv2
import numpy as np


def imread_u(path) -> np.ndarray | None:
    """Windows 下 cv2.imread 吃不了非 ASCII 路徑，走 imdecode。"""
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE) if buf.size else None


def load_our_crops(d: Path):
    """{char: [(path, norm64), ...]}"""
    from open_guji_cv.clustering.normalize import normalize_patch
    out = collections.defaultdict(list)
    for f in sorted(glob.glob(str(d / "KX*.png"))):
        m = re.search(r"_(.+)\.png$", os.path.basename(f))
        if not m:
            continue
        ch = m.group(1)
        if ch == "unk" or len(ch) != 1:
            continue
        im = imread_u(f)
        if im is None or im.size == 0:
            continue
        try:
            n = normalize_patch(im)
        except Exception:  # noqa: BLE001
            continue
        if n.any():
            out[ch].append((f, n.astype(np.uint8)))
    return dict(out)


def load_zitools_kangxi(dirs):
    """字統網的康熙切圖 {char: [norm64, ...]}——標籤取 glyph_char（圖上真正的字）。"""
    from open_guji_cv.clustering.normalize import normalize_patch
    out = collections.defaultdict(list)
    for d in dirs:
        d = Path(d)
        man = d / "manifest.tsv"
        if not man.exists():
            continue
        with open(man, encoding="utf-8") as f:
            for r in csv.reader(f, delimiter="\t"):
                if len(r) < 8 or r[5] != "kangxi" or len(r[1]) != 1:
                    continue
                im = imread_u(d / r[7])
                if im is None or im.size == 0:
                    continue
                try:
                    n = normalize_patch(im)
                except Exception:  # noqa: BLE001
                    continue
                if n.any():
                    out[r[1]].append(n.astype(np.uint8))
    return dict(out)


class Emb:
    """CNN embedding；模板向量按字快取。"""

    def __init__(self, ckpt="cache/glyph_cnn_r4/best.pt"):
        import torch
        from open_guji_cv.clustering.cnn_candidates import CnnCandidates
        self.cc = CnnCandidates(ckpt)
        if not self.cc._ensure():
            raise SystemExit(f"checkpoint 不可用: {ckpt}")
        self.torch = torch
        self.dev = self.cc._dev
        self._tpl: dict[str, np.ndarray] = {}

    def vecs(self, imgs) -> np.ndarray:
        """[64² {0,1}] → L2 normalised 向量矩陣。"""
        if not len(imgs):
            return np.zeros((0, 256), np.float32)
        out = []
        for i in range(0, len(imgs), 256):
            x = self.torch.tensor(np.stack(imgs[i:i + 256])[:, None].astype(np.float32), device=self.dev)
            with self.torch.no_grad():
                e, _, _ = self.cc._net(x)
            e = e / (e.norm(dim=1, keepdim=True) + 1e-9)
            out.append(e.cpu().numpy())
        return np.vstack(out).astype(np.float32)

    def template(self, ch: str) -> np.ndarray | None:
        """該字四套字體渲染圖的平均向量。"""
        if ch in self._tpl:
            return self._tpl[ch]
        from open_guji_cv.clustering.font_candidates import _font_files
        from open_guji_cv.clustering.synth import render_char
        ims = []
        for fp in _font_files():
            try:
                im = render_char(ch, fp, size=64)
            except Exception:  # noqa: BLE001
                continue
            if im is not None and im.any():
                ims.append(im.astype(np.uint8))
        if not ims:
            self._tpl[ch] = None
            return None
        v = self.vecs(ims).mean(0)
        v = v / (np.linalg.norm(v) + 1e-9)
        self._tpl[ch] = v.astype(np.float32)
        return self._tpl[ch]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crops", default="D:/data/glyph-sources/kangxi/crops")
    ap.add_argument("--zitools", nargs="*", default=["D:/data/glyph-sources/zitools/p1",
                                                     "D:/data/glyph-sources/zitools/p2"])
    ap.add_argument("--out", default="D:/data/glyph-sources/kangxi/crossval")
    ap.add_argument("--ckpt", default="cache/glyph_cnn_r4/best.pt")
    ap.add_argument("--tau-a", type=float, default=0.62, help="A（字體模板）通過線")
    ap.add_argument("--tau-b", type=float, default=0.55, help="B（字統網康熙）通過線")
    ap.add_argument("--tau-c", type=float, default=0.60, help="C（同字自洽）通過線；同字只有 1 例時跳過")
    ap.add_argument("--review-html", action="store_true")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print("載入我方切圖…", flush=True)
    ours = load_our_crops(Path(a.crops))
    n_imgs = sum(len(v) for v in ours.values())
    print(f"  {n_imgs} 張 / {len(ours)} 字", flush=True)
    print("載入字統網康熙切圖…", flush=True)
    zt = load_zitools_kangxi(a.zitools)
    print(f"  {sum(len(v) for v in zt.values())} 張 / {len(zt)} 字", flush=True)

    emb = Emb(a.ckpt)
    rows = []
    for i, (ch, lst) in enumerate(sorted(ours.items())):
        if i % 500 == 0:
            print(f"  {i}/{len(ours)} 字…", flush=True)
        V = emb.vecs([n for _, n in lst])            # 我方各例向量
        tpl = emb.template(ch)
        simA = V @ tpl if tpl is not None else np.full(len(lst), np.nan)
        if ch in zt:
            Z = emb.vecs(zt[ch])
            simB = (V @ Z.T).max(1)                  # 與字統網任一張最像的那個分
        else:
            simB = np.full(len(lst), np.nan)
        if len(lst) > 1:                             # 同字自洽：與同字其他例的最大相似
            S = V @ V.T
            np.fill_diagonal(S, -1)
            simC = S.max(1)
        else:
            simC = np.full(len(lst), np.nan)
        for (f, _), sa, sb, sc in zip(lst, simA, simB, simC):
            reasons = []
            if not np.isnan(sa) and sa < a.tau_a:
                reasons.append(f"A低({sa:.2f})")
            if np.isnan(sa):
                reasons.append("A缺(字體無此字)")
            if not np.isnan(sb) and sb < a.tau_b:
                reasons.append(f"B衝突({sb:.2f})")
            if not np.isnan(sc) and sc < a.tau_c:
                reasons.append(f"C離群({sc:.2f})")
            if reasons:
                verdict = "review"
            elif np.isnan(sb):
                verdict = "nob"
            else:
                verdict = "pass"
            rows.append((ch, os.path.basename(f), f"{sa:.3f}" if not np.isnan(sa) else "",
                         f"{sb:.3f}" if not np.isnan(sb) else "",
                         f"{sc:.3f}" if not np.isnan(sc) else "",
                         verdict, ";".join(reasons)))

    with open(out / "report.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["char", "file", "simA_font", "simB_zitools", "simC_self", "verdict", "reason"])
        w.writerows(rows)

    cnt = collections.Counter(r[5] for r in rows)
    hasB = sum(1 for r in rows if r[3])
    lines = [
        f"總計 {len(rows)} 張 / {len(ours)} 字",
        f"  pass   {cnt['pass']:6d} ({cnt['pass']/max(len(rows),1):.1%})  三道全過（含字統網獨立佐證）",
        f"  nob    {cnt['nob']:6d} ({cnt['nob']/max(len(rows),1):.1%})  字統網無此字，A/C 過",
        f"  review {cnt['review']:6d} ({cnt['review']/max(len(rows),1):.1%})  進人審",
        f"字統網可佐證的張數 {hasB} ({hasB/max(len(rows),1):.1%})",
        "",
        "review 原因分布：",
    ]
    rc = collections.Counter(re.sub(r"\([^)]*\)", "", r[6]) for r in rows if r[5] == "review")
    lines += [f"  {k or '(空)'}: {v}" for k, v in rc.most_common()]
    (out / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

    if a.review_html:
        write_review_html(out, [r for r in rows if r[5] == "review"], Path(a.crops), zt)
        print(f"人審頁面 → {out/'review.html'}")


def write_review_html(out: Path, rows, crops: Path, zt):
    """人審頁面：每條一行——我方切圖 / 字統網同字圖 / 字體渲染，附分數與原因。"""
    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.synth import render_char

    def b64(img: np.ndarray) -> str:
        ok, buf = cv2.imencode(".png", img)
        return base64.b64encode(buf.tobytes()).decode() if ok else ""

    parts = ["""<!doctype html><meta charset=utf-8><title>康熙切圖人審</title>
<style>body{font:14px system-ui;margin:20px}table{border-collapse:collapse}
td,th{border:1px solid #ddd;padding:6px;text-align:center}img{height:80px;image-rendering:pixelated}
.r{color:#b00}</style><h2>康熙字頭切圖：待人審</h2>
<p>逐條核對「我方切圖」是否確實是所標的字。左起：我方切圖、字統網同字康熙圖、字體渲染。</p>
<table><tr><th>標籤</th><th>我方切圖</th><th>字統網康熙</th><th>字體</th><th>A字體</th><th>B字統</th><th>C自洽</th><th>原因</th></tr>"""]
    fonts = _font_files()
    for ch, fname, sa, sb, sc, _v, reason in rows[:3000]:
        im = imread_u(crops / fname)
        c1 = f'<img src="data:image/png;base64,{b64(im)}">' if im is not None else "?"
        c2 = f'<img src="data:image/png;base64,{b64(zt[ch][0] * 255)}">' if ch in zt and zt[ch] else "—"
        c3 = "—"
        for fp in fonts:
            try:
                r = render_char(ch, fp, size=64)
            except Exception:  # noqa: BLE001
                continue
            if r is not None and r.any():
                c3 = f'<img src="data:image/png;base64,{b64(r * 255)}">'
                break
        parts.append(f"<tr><td style='font-size:28px'>{ch}</td><td>{c1}</td><td>{c2}</td><td>{c3}</td>"
                     f"<td>{sa}</td><td>{sb}</td><td>{sc}</td><td class=r>{reason}</td></tr>")
    parts.append("</table>")
    (out / "review.html").write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main()
