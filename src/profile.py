"""BookProfile —— 一本古籍的版式特征描述。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class BookProfile:
    """一本古籍的版式特征描述，由 Phase 1 自动生成或手动指定。

    Attributes:
        color_mode: "bw"（黑白）或 "colored"（彩色）
        background_color: 底色描述，如 "red", "yellow", None（无底色/白底）
        text_color: 文字颜色，通常为 "black"
        border_color: 边框颜色，如 "black", "red"
        page_type: "cut_half"（已剪切半页）或 "uncut_full"（未剪切整页）
        lines_per_page: 每半页的行数（如 8 或 9）
        border_style: 边框样式，"double"（双层：外粗内细）或 "single"
        border_wear: 边框磨损程度，"light" / "medium" / "heavy"
        interferences: 干扰项列表，如 ["spine_shadow", "stains", "white_margin", "page_number"]
        chars_per_line: 每行字数，None 表示不固定
        has_marginal_notes: 是否有夹注
        auto_detected: True 表示自动检测生成，False 表示手动指定
        detection_confidence: 各项检测的置信度，key 为特征名
    """

    # ─── 颜色 ───
    color_mode: str = "bw"
    background_color: str | None = None
    text_color: str = "black"
    border_color: str = "black"

    # ─── 页面布局 ───
    page_type: str = "cut_half"
    lines_per_page: int = 8

    # ─── 边框 ───
    border_style: str = "double"
    border_wear: str = "medium"

    # ─── 干扰项 ───
    interferences: list[str] = field(default_factory=list)

    # ─── 文字 ───
    chars_per_line: int | None = 21
    has_marginal_notes: bool = False

    # ─── 元信息 ───
    auto_detected: bool = True
    detection_confidence: dict[str, float] = field(default_factory=dict)

    # ─── 序列化 ───

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BookProfile:
        """从字典创建 BookProfile，忽略未知字段。"""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def save(self, path: str | Path) -> None:
        """保存为 JSON 文件。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> BookProfile:
        """从 JSON 文件加载。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def update(self, **kwargs) -> None:
        """更新指定字段。"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    # ─── 便利属性 ───

    @property
    def is_colored(self) -> bool:
        return self.color_mode == "colored"

    @property
    def is_uncut(self) -> bool:
        return self.page_type == "uncut_full"

    @property
    def has_spine_shadow(self) -> bool:
        return "spine_shadow" in self.interferences

    @property
    def has_white_margin(self) -> bool:
        return "white_margin" in self.interferences

    @property
    def has_stains(self) -> bool:
        return "stains" in self.interferences

    def __repr__(self) -> str:
        parts = [
            f"颜色={self.color_mode}",
            f"页面={self.page_type}",
            f"行数={self.lines_per_page}",
            f"干扰={self.interferences}",
        ]
        if self.has_marginal_notes:
            parts.append("有夹注")
        return f"BookProfile({', '.join(parts)})"
