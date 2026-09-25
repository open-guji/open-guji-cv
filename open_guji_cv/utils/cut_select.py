# -*- coding: utf-8 -*-
"""切点候选的**裁判**：类别无关归属 U-Net（v2）给每条候选切线打「一致率」，Step3 据此在候选池里选。

背景（overview `Step3-逐字切分/05-高级切分算法.md` 实验六～七，2026-09-14，frame_ok 906 / 标签可信 673）：
现役规则（窄走廊绕得开就用窄走廊，否则直线）大块错（≥150 px 墨划错边）5.2%；候选池 {直线, 窄走廊, 宽走廊}
里几乎总有对的（三选一上限 0.7%），错在**选**。让 U-Net 对双格窗口出一张逐像素归属图，再给每条候选算
「U-Net 置信加权的一致率」，取最高者：px 均值 31.4→14.0、≤20px 84%→86%、大块错 5.2%→1.5%。
更聪明的选法（模板贴合度、合议、学习排序、识别身份、真金标微调、身份条件网络）都不比它好，见 05 卡。

用法：`judge = get_judge()`（进程内单例，懒加载；没有 torch / 权重就返回 None，调用方按旧规则走），
`judge.scores(col_gray, x_lo, x_hi, y0, y1, y_line, seams)` → 每条候选一个 [0,1] 分数（None = 这一处判不了）。
候选的 seam 用**列图坐标**（与 `SeamCandidate.y` 同口径，从 content_x[0] 起每 x 一个 y；直线传 None）。

权重：`models/partition_unet_v2/model.pt`（11 MB，与 `glyph_cnn_r4` 同理进 Git——合成对训练 16 轮要 GPU 约 1 小时，
不可确定性重建）。训练脚本与实验记录在 `experiments/touch_resolve/train_partition_unet_v2.py`。
**换权重会让 Step3 产物过期**：`ckpt_fingerprint()`（mtime_ns:size）进 `RowSegmentParams.judge_fingerprint`。

归属图口径（与实验一致，别改）：
- 画布 288×192，窗口按比例缩放贴在 top=8 处；输入 2 通道 = [墨, 归一化行坐标]；
- 网络出 3 类 (背景/上/下)，**墨像素取上/下两类谁大**（不是三类 argmax：背景类归下字会多 30% 误差）；
- 连通体多数票只对面积 ≤ `CC_MAX` 的连通体生效（大连通体两边都占是真粘连，整块翻边是大块错的主要来源）。
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CANVAS_H, CANVAS_W = 288, 192
CANVAS_TOP = 8
CC_MAX = 400
MAJORITY = 0.85
INK_TH = 128
JUDGE_MARGIN = 0.005
PENDING_BLOB = 60
"""顺序闸的挡卡门槛（2026-09-15 用 60 条分层抽样标定，overview 10 卡第十一节）：多候选切点里
**所选切法与 U-Net 归属的分歧最大块 ≥ 这么多像素**才挡人，其余放行。

标定数据：vol02 全书顺序闸挡着 1045 条多候选切点，按 dis_unet 分三档抽样各 20 条，请人只判「这条线切得对不对」
（用户的标准偏严：差一点、即使不影响识别也算切错）：

| 档位 | dis_unet | 整批 | 抽样切坏 | 该档坏率 |
|---|---|---|---|---|
| 近似 | <20 | 779 | 0/20 | 0% |
| 中等 | 20–60 | 184 | 1/20 | 5% |
| 较大 | 60–100 | 82 | **7/20** | **35%** |

8 条切坏的 dis_unet 全部落在 54–85（ok 的中位数只有 25）。取 60：挡 82 条（8%）覆盖估计 29 条坏字，
放行 963 条里估计漏 9 条（占放行 1.0%、全书 4633 个切点的 0.2%）。人工从 1045 降到 82 条，省 92%。
≥100 的另由 `ESCALATE_BLOB` 升级出卡（L2′），两者衔接。"""

ESCALATE_BLOB = 100
"""L2′ 分歧探针（2026-09-15，overview 10 卡「梯次裁决」）：最终选中的切法与 U-Net 归属的**分歧最大连通块**
≥ 这么多像素，就把这个切点标成 `escalate=True`——不改选法，只是「本层拿不准，给下游再审」：
顺序闸把它当待审出卡，将来 L3（扩池）/ L4（识别置信否决）只对这些条目干活。
门槛来历：673 条金标里选对的条目分歧块 p95=51 / p99=124 px；几何候选全错、只有 U-Net 对的 4 条 241–983 px。
100 把后者全部抓住、误升级约 5%（升级总量 ≈3% 的粘连切点，≈0.4 条/页）。"""
"""改选门槛：最优候选的一致率要比现役规则选中的高出这么多才改选。2026-09-14 在 673 条金标列上扫过
（`experiments/touch_resolve/verify_prod_judge.py`）：δ=0 改选 81 条（变好 47 / 变差 34），δ=0.005 改选 47 条
（36 / 11），大块错都是 5.6%→1.9%，≤20px 85.7%→86.8%——同样的收益，少引入三分之二的小倒退。"""

DEFAULT_CKPT = Path(__file__).resolve().parents[2] / "models" / "partition_unet_v2" / "model.pt"

GUIDED_BAND = 45
"""L3 扩池：U-Net 引导缝的走廊半宽。升级切点的正确缝常在现役直线 25–35 px 外（文言 −25、學亦 +24），
窄走廊 ±20 够不着，±40 的宽走廊只在窄走廊穿墨时才开；这里给 ±45。"""


def guided_seam_from_owner(owner: np.ndarray, y_line_local: int, band: int = GUIDED_BAND,
                           step: int = 2, turn: float = 0.02) -> np.ndarray | None:
    """U-Net **引导**的缝：在直线 ±band 走廊里走一条每列最多移 step 行的路径，代价 = 这一列切在 y 时
    归属错的墨像素数（U-Net 说是下字却在缝上方的 + 说是上字却在缝下方的）+ turn×纵向移动。
    2026-09-15 实验十：按列取「换手行」会画出字的轮廓（归属交错 / 整字翻边时根本不是一条切线），
    有约束的 seam DP 才给出可用的切线；三条有金标的升级点（學亦、文言、119:9:15）正确缝由它进池。
    返回窗口局部坐标的逐 x 行号；owner 全空返回 None。"""
    h, w = owner.shape
    if h < 3 or w < 1 or not (owner > 0).any():
        return None
    up = (owner == 1).astype(np.int32)
    dn = (owner == 2).astype(np.int32)
    cum_dn = np.cumsum(dn, axis=0)
    cum_up = np.cumsum(up, axis=0)
    tot_up = cum_up[-1]
    ys = np.arange(h)[:, None]
    prev = np.clip(ys - 1, 0, h - 1)
    above_dn = np.where(ys > 0, np.take_along_axis(cum_dn, prev, axis=0), 0)
    below_up = tot_up[None, :] - np.where(ys > 0, np.take_along_axis(cum_up, prev, axis=0), 0)
    mis = (above_dn + below_up).astype(np.float64)
    lo, hi = max(0, y_line_local - band), min(h - 1, y_line_local + band)
    if hi <= lo:
        return None
    n = hi - lo + 1
    rows = np.arange(lo, hi + 1)
    tie = 1e-4 * np.abs(rows - y_line_local)
    cost = mis[lo:hi + 1, 0] + tie
    back = np.zeros((w, n), dtype=np.int16)
    offsets = np.arange(-step, step + 1)
    for x in range(1, w):
        cand = np.full((len(offsets), n), np.inf)
        for i, d in enumerate(offsets):
            if d >= 0:
                cand[i, d:] = cost[:n - d] + turn * d
            else:
                cand[i, :n + d] = cost[-d:] + turn * (-d)
        best_i = np.argmin(cand, axis=0)
        cost = cand[best_i, np.arange(n)] + mis[lo:hi + 1, x] + tie
        back[x] = offsets[best_i]
    j = int(np.argmin(cost))
    out = np.empty(w, dtype=int)
    for x in range(w - 1, -1, -1):
        out[x] = lo + j
        if x > 0:
            j = int(np.clip(j - int(back[x, j]), 0, n - 1))
    return out




def ckpt_fingerprint(path: str | Path | None = None) -> str:
    """权重文件的轻量指纹 (mtime_ns, size)；文件不存在返回空串（= 裁判不可用，按旧规则）。

    **没装 torch 也返回空串**（2026-09-25）：此前只看权重文件，没 torch 的机器上
    `get_judge()` 静默返回 None、Step3 按旧规则切，指纹却与装了 torch 时一模一样，
    产物照报新鲜。vol02 实测一轮这样跑出来：U-Net 改选 213 → 0、升级人审 96 → 0、
    人裁收敛 186 → 105，`status` 全绿。现在「裁判不可用」进指纹，装/卸 torch 都会让
    Step3 过期。"""
    import importlib.util
    if importlib.util.find_spec("torch") is None:
        return ""
    p = Path(path) if path else DEFAULT_CKPT
    try:
        st = os.stat(p)
    except OSError:
        return ""
    return hashlib.sha1(f"{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:12]


def owner_from_seam(win_ink: np.ndarray, seam_local: np.ndarray) -> np.ndarray:
    """一条缝（窗口局部坐标、每 x 一个 y）→ owner 图（1=上 2=下），只在墨像素上有值。"""
    h, w = win_ink.shape
    ys = np.arange(h)[:, None]
    above = ys < np.asarray(seam_local[:w])[None, :]
    owner = np.where(above, 1, 2).astype(np.uint8)
    owner[win_ink == 0] = 0
    return owner


def _build_model():
    import torch
    import torch.nn as nn

    def block(i, o, dil=1):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=dil, dilation=dil), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                             nn.Conv2d(o, o, 3, padding=dil, dilation=dil), nn.BatchNorm2d(o), nn.ReLU(inplace=True))

    class UNet(nn.Module):
        def __init__(self, ch=(24, 48, 96, 160, 256), n_cls=3):
            super().__init__()
            self.e1 = block(2, ch[0]); self.e2 = block(ch[0], ch[1]); self.e3 = block(ch[1], ch[2])
            self.e4 = block(ch[2], ch[3]); self.e5 = block(ch[3], ch[4], dil=2)
            self.pool = nn.MaxPool2d(2)
            self.u4 = nn.ConvTranspose2d(ch[4], ch[3], 2, stride=2); self.d4 = block(ch[3] * 2, ch[3])
            self.u3 = nn.ConvTranspose2d(ch[3], ch[2], 2, stride=2); self.d3 = block(ch[2] * 2, ch[2])
            self.u2 = nn.ConvTranspose2d(ch[2], ch[1], 2, stride=2); self.d2 = block(ch[1] * 2, ch[1])
            self.u1 = nn.ConvTranspose2d(ch[1], ch[0], 2, stride=2); self.d1 = block(ch[0] * 2, ch[0])
            self.out = nn.Conv2d(ch[0], n_cls, 1)

        def forward(self, x):
            e1 = self.e1(x); e2 = self.e2(self.pool(e1)); e3 = self.e3(self.pool(e2))
            e4 = self.e4(self.pool(e3)); e5 = self.e5(self.pool(e4))
            d4 = self.d4(torch.cat([self.u4(e5), e4], 1)); d3 = self.d3(torch.cat([self.u3(d4), e3], 1))
            d2 = self.d2(torch.cat([self.u2(d3), e2], 1)); d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
            return self.out(d1)

    return UNet()


def _to_canvas(gray: np.ndarray, top: int = CANVAS_TOP):
    import cv2
    h, w = gray.shape
    s = min(1.0, (CANVAS_H - top) / h, CANVAS_W / w)
    if s < 1.0:
        gray = cv2.resize(gray, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    img = np.full((CANVAS_H, CANVAS_W), 255, np.uint8)
    img[top: top + gray.shape[0], : gray.shape[1]] = gray
    return img, s


def _make_input(img: np.ndarray):
    import torch
    ink = (255 - img).astype(np.float32) / 255.0
    yy = np.linspace(0, 1, CANVAS_H, dtype=np.float32)[:, None].repeat(CANVAS_W, axis=1)
    return torch.from_numpy(np.stack([ink, yy], 0))


class UNetJudge:
    """进程内持有一份网络。`owner()` 出归属图，`scores()` 给候选打分。任何异常都返回 None，不抛。"""

    def __init__(self, ckpt: str | Path | None = None, device: str | None = None):
        import torch
        self.ckpt = Path(ckpt) if ckpt else DEFAULT_CKPT
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.net = _build_model().to(self.device)
        self.net.load_state_dict(torch.load(self.ckpt, map_location=self.device)["state"])
        self.net.eval()
        self.fingerprint = ckpt_fingerprint(self.ckpt)

    def owner(self, win_gray: np.ndarray, ink_threshold: int = INK_TH, cc_max: int | None = CC_MAX):
        """双格窗口灰度 → (墨掩膜 W, owner 1/2/0, 置信 |pA−pB|)。"""
        import cv2
        import torch
        W = (win_gray < ink_threshold).astype(np.uint8)
        cimg, s = _to_canvas(win_gray)
        x = _make_input(cimg)[None].to(self.device)
        with torch.no_grad():
            prob = torch.softmax(self.net(x)[0], 0).cpu().numpy()
        prob = prob[:, CANVAS_TOP:]
        h, w = win_gray.shape
        if s < 1.0:
            ph, pw = int(h * s), int(w * s)
            prob = np.stack([cv2.resize(prob[k][:ph, :pw], (w, h), interpolation=cv2.INTER_LINEAR)
                             for k in range(prob.shape[0])])
        else:
            prob = prob[:, :h, :w]
        pA, pB = prob[1], prob[2]
        raw = np.where(W > 0, np.where(pA >= pB, 1, 2), 0).astype(np.uint8)
        conf = np.abs(pA - pB)
        owner = raw.copy()
        n_cc, lab, st, _ = cv2.connectedComponentsWithStats(W, connectivity=8)
        for i in range(1, n_cc):
            if cc_max is not None and st[i, cv2.CC_STAT_AREA] > cc_max:
                continue
            m = lab == i
            v = raw[m]
            nA, nB = int((v == 1).sum()), int((v == 2).sum())
            if nA >= MAJORITY * (nA + nB):
                owner[m] = 1
            elif nB >= MAJORITY * (nA + nB):
                owner[m] = 2
        return W, owner, conf

    def scores(self, col_gray: np.ndarray, x_lo: int, x_hi: int, y0: int, y1: int, y_line: float,
               seams: list, ink_threshold: int = INK_TH) -> list[float] | None:
        """每条候选的 U-Net 置信加权一致率（`assess()` 的第一项）。"""
        r = self.assess(col_gray, x_lo, x_hi, y0, y1, y_line, seams, ink_threshold)
        return None if r is None else r[0]

    def guided_seam(self, col_gray: np.ndarray, x_lo: int, x_hi: int, y0: int, y1: int, y_line: float,
                    ink_threshold: int = INK_TH, band: int = GUIDED_BAND) -> np.ndarray | None:
        """L3 扩池用：U-Net 引导缝（**列图坐标**，长度 x_hi−x_lo）。判不了返回 None。"""
        try:
            y0, y1 = int(max(0, y0)), int(min(col_gray.shape[0], y1))
            if y1 - y0 < 4 or x_hi - x_lo < 4:
                return None
            win = col_gray[y0:y1, x_lo:x_hi]
            _, ou, _ = self.owner(win, ink_threshold)
            sm = guided_seam_from_owner(ou, int(round(y_line)) - y0, band=band)
            return None if sm is None else sm + y0
        except Exception as e:
            log.warning("guided seam failed at y=%s: %s", y_line, e)
            return None

    def assess(self, col_gray: np.ndarray, x_lo: int, x_hi: int, y0: int, y1: int, y_line: float,
               seams: list, ink_threshold: int = INK_TH) -> tuple[list[float], list[int]] | None:
        """每条候选的 (U-Net 置信加权一致率, 与 U-Net 归属分歧的最大连通块面积 px)。
        `seams[i]` 是列图坐标的逐 x y（长度 x_hi−x_lo）或 None（直线 y_line）。判不了返回 None。"""
        try:
            y0, y1 = int(max(0, y0)), int(min(col_gray.shape[0], y1))
            if y1 - y0 < 4 or x_hi - x_lo < 4:
                return None
            win = col_gray[y0:y1, x_lo:x_hi]
            W, ou, conf = self.owner(win, ink_threshold)
            ink = W > 0
            if not ink.any():
                return None
            cw = conf[ink]
            denom = float(cw.sum())
            if denom <= 1e-6:
                return None
            import cv2
            out: list[float] = []
            dis: list[int] = []
            n = x_hi - x_lo
            for sm in seams:
                arr = np.full(n, int(round(y_line))) if sm is None else np.asarray(sm, dtype=int)
                if arr.shape[0] != n:
                    return None
                o = owner_from_seam(W, arr - y0)
                eq = (o[ink] == ou[ink])
                out.append(round(float((cw * eq).sum() / denom), 4))
                m = ink & (o != ou)
                if m.any():
                    _, _, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
                    dis.append(int(st[1:, cv2.CC_STAT_AREA].max()))
                else:
                    dis.append(0)
            return out, dis
        except Exception as e:  # 裁判出错不能拖垮切分：按旧规则走
            log.warning("cut judge failed at y=%s: %s", y_line, e)
            return None


_JUDGE: dict[str, "UNetJudge | None"] = {}


def get_judge(ckpt: str | Path | None = None) -> "UNetJudge | None":
    """进程内单例。没有 torch、权重缺失或加载失败 → None（只警告一次）。"""
    key = str(Path(ckpt) if ckpt else DEFAULT_CKPT)
    if key in _JUDGE:
        return _JUDGE[key]
    judge = None
    try:
        if Path(key).exists():
            judge = UNetJudge(key)
        else:
            log.warning("cut judge 权重不存在：%s（Step3 按旧规则选切法）", key)
    except Exception as e:
        log.warning("cut judge 加载失败：%s（Step3 按旧规则选切法）", e)
    _JUDGE[key] = judge
    return judge
