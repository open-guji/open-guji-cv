"""图像 IO 工具，支持 Windows 非 ASCII 路径。

## 读图一律字节读入再 imdecode（2026-10-05，overview#407）

原先 `imread` 先试 `cv2.imread`、返回 None 才退到 `np.fromfile + imdecode`。Windows
下工作区路径含中文（`96mid1ogzk-欽定四庫全書總目武英殿刻本`），第一步**必然**失败并打一条
`imread_(...): can't open/read file` 警告——哪怕文件好好的、第二步也读成功了。vol02 一轮
`glyph_match` 打出 8,980 条这种假警告，真读失败混在里面根本看不出来。现在直接走字节读入，
不再碰 `cv2.imread`。

## 两种口径

- 默认（`strict=False`，老口径，调用方很多靠它）：文件不存在抛 `FileNotFoundError`
  （`np.fromfile` 本来就这样）；文件在但解不出来（空文件、坏 PNG）返回 None。
- `strict=True`：解不出来也抛 `ImageReadError`。**读管线输入（缓存字块、列图、原图）的
  路径用这个**——读不到就该停下这一页，不能拿 None 往下走成垃圾结果。
"""

from pathlib import Path

import cv2
import numpy as np


class ImageReadError(OSError):
    """图片文件在、但解不出来（空文件／坏文件／不是图）。`strict=True` 时抛。"""


def imread(image_path: str, flags=cv2.IMREAD_COLOR, *, strict: bool = False) -> np.ndarray | None:
    """读取图片，支持 Windows 非 ASCII 路径（字节读入 + imdecode，不经 `cv2.imread`）。

    文件不存在 → `FileNotFoundError`（两种口径都是）；解不出来 → `strict` 时抛
    `ImageReadError`，否则返回 None。
    """
    p = str(image_path)
    buf = np.fromfile(p, dtype=np.uint8)          # 不存在 → FileNotFoundError；是目录 → OSError
    img = cv2.imdecode(buf, flags) if buf.size else None
    if img is None and strict:
        raise ImageReadError(f"图片解不出来（{buf.size} 字节）: {p}")
    return img


def imwrite(path: str, img: np.ndarray) -> bool:
    """写入图片，支持 Windows 非 ASCII 路径。"""
    ext = Path(path).suffix
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(str(path))
        return True
    return False
