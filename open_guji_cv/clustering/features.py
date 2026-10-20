"""M2 特征后端注册表。

特征只用于粗分块与近邻检索，不作为合并依据（合并只信 verify 配准验证），
因此换后端不影响聚类正确性，只影响碎片率和速度。

输入统一为归一二值图批次 (N, S, S) uint8 {0,1}，输出 (N, D) float32，行 L2 归一。
"""

from __future__ import annotations

import cv2
import numpy as np

from .normalize import NORM_SIZE, soft_patch


class BaseFeature:
    """特征后端基类。"""

    name: str = "base"

    def extract(self, patches: np.ndarray) -> np.ndarray:
        """(N, S, S) uint8 {0,1} → (N, D) float32，行 L2 归一。"""
        raise NotImplementedError

    @staticmethod
    def _l2_normalize(mat: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (mat / norms).astype(np.float32)


class RawDownsample(BaseFeature):
    """基线：模糊后降采样 16×16 展平。零调参、零依赖。"""

    name = "raw"

    def __init__(self, grid: int = 16):
        self.grid = grid

    def extract(self, patches: np.ndarray) -> np.ndarray:
        feats = np.empty((len(patches), self.grid * self.grid), dtype=np.float32)
        for i, p in enumerate(patches):
            soft = soft_patch(p)
            small = cv2.resize(soft, (self.grid, self.grid),
                               interpolation=cv2.INTER_AREA)
            feats[i] = small.ravel()
        return self._l2_normalize(feats)


class HogFeature(BaseFeature):
    """HOG：对笔画方向敏感，区分形近字优于 raw。默认后端。

    纯 numpy/Sobel 实现（OpenCV 5.x 已移除 cv2.HOGDescriptor），
    8×8 cell / 9 方向 / 2×2-cell 块 L2 归一，行为与经典 HOG 一致。
    """

    name = "hog"

    def __init__(self, size: int = NORM_SIZE, cell: int = 8, nbins: int = 9):
        self.size = size
        self.cell = cell
        self.nbins = nbins

    def _hog_single(self, img: np.ndarray) -> np.ndarray:
        gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
        mag = np.sqrt(gx * gx + gy * gy)
        # 无符号方向 [0, π)
        ang = np.mod(np.arctan2(gy, gx), np.pi)
        bins = np.minimum((ang / np.pi * self.nbins).astype(int), self.nbins - 1)

        n = self.size // self.cell
        # 整张图一次 np.add.at（2026-10-20，提速）：原来 64 个格各调一次。每个 bin 只属于一个格，
        # 而一个格的像素在整图按行展开里的相对次序与按格切片展开相同，所以每个 bin 的
        # float32 累加次序不变，直方图逐位相同。
        hist = np.zeros((n, n, self.nbins), dtype=np.float32)
        e = n * self.cell                       # 格外的边角像素原来就不计
        bins, mag = bins[:e, :e], mag[:e, :e]
        cell_idx = self._cell_index(bins.shape)
        np.add.at(hist.reshape(-1), (cell_idx + bins).ravel(), mag.ravel())

        # 2×2-cell 块 L2 归一（滑动步长 1 cell）。范数直接写 sqrt(x·x)——就是 np.linalg.norm
        # 对一维 float32 的做法，结果逐位相同，省掉它每次的 Python 开销（每张图 49 次）。
        # 各块一次取齐（每行就是原来 hist[by:by+2, bx:bx+2].ravel() 的拷贝），逐块 dot 不变，
        # 除法整批做；范数为 0 的块本来全是 0，除以 1 仍是 0。
        B = hist.reshape(-1)[self._block_index(n)]
        norms = np.array([np.sqrt(b.dot(b)) for b in B], dtype=np.float32)
        return (B / np.where(norms > 0, norms, np.float32(1))[:, None]).ravel()

    def _block_index(self, n: int) -> np.ndarray:
        """(块数, 4×nbins) 的下标：第 k 行是第 k 个 2×2 块按 hist[by:by+2, bx:bx+2].ravel() 的次序。"""
        cache = self.__dict__.setdefault("_blk_idx", {})
        hit = cache.get(n)
        if hit is None:
            ids = np.arange(n * n * self.nbins).reshape(n, n, self.nbins)
            hit = np.stack([ids[by:by + 2, bx:bx + 2].ravel()
                            for by in range(n - 1) for bx in range(n - 1)])
            cache[n] = hit
        return hit

    def _cell_index(self, shape: tuple[int, int]) -> np.ndarray:
        """每个像素所属格在 hist 展平后的起点（格号 × nbins），按图尺寸缓存。"""
        cache = self.__dict__.setdefault("_cell_idx", {})
        hit = cache.get(shape)
        if hit is None:
            h, w = shape
            n = self.size // self.cell
            cy = np.arange(h) // self.cell
            cx = np.arange(w) // self.cell
            hit = ((cy[:, None] * n + cx[None, :]) * self.nbins).astype(np.intp)
            cache[shape] = hit
        return hit

    def extract(self, patches: np.ndarray) -> np.ndarray:
        feats = [self._hog_single(soft_patch(p) * 255.0) for p in patches]
        return self._l2_normalize(np.asarray(feats, dtype=np.float32))


FEATURE_BACKENDS: dict[str, type[BaseFeature]] = {
    "raw": RawDownsample,
    "hog": HogFeature,
    # "emb": CnnEmbedding —— P5 可选增强，由 M7 训练后注册
}

DEFAULT_FEATURE = "hog"


def get_feature(name: str = DEFAULT_FEATURE) -> BaseFeature:
    if name not in FEATURE_BACKENDS:
        raise ValueError(f"未知特征后端: {name!r}（可选: {sorted(FEATURE_BACKENDS)}）")
    return FEATURE_BACKENDS[name]()
