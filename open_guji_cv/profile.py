"""BookProfile —— 一本古籍的版式特征描述。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class BookProfile:
    """一本古籍的版式特征描述，由 recognize-profile 自动生成或手动指定。

    分层结构：
      1. 版面 (layout)     — 物理页面布局
      2. 内容格式 (content) — 乌丝栏 / 无栏线 / 表格 / 插图
      3. 字体 (font)       — 印刷 / 手写
      4. 内容数据           — 行数、字数、夹注
      5. 颜色 (color)      — 底色、文字、边框颜色
      6. 边框 (border)     — 样式、磨损
      7. 干扰项             — 阴影、页边距等
      8. 元信息             — 自动检测标志、置信度
    """

    # ─── 1. 版面：物理页面布局 ───
    # "cut_half"   已剪切的半页（最常见）
    # "uncut_full" 未剪切的筒子页，需从中缝分页
    # "spread"     对开拍照，两页平摊，中间有中缝
    layout: str = "cut_half"

    # 版心位置（仅 cut_half 有意义）："left" | "right"
    banxin_position: str | None = None

    # ─── 2. 内容格式 ───
    # "regular"      乌丝栏（正常分栏，竖线分隔的列）
    # "no_line"      无栏线（有分栏但无竖线分隔）
    # "table"        表格页面
    # "illustration" 插图页面
    content_format: str = "regular"

    # ─── 3. 字体 ───
    # "printed"     印刷/刻本
    # "handwritten" 手写/抄本
    font_type: str = "printed"

    # ─── 4. 内容数据（取决于 content_format） ───
    lines_per_page: int = 8
    fixed_chars_per_line: bool = True     # 每行字数是否固定
    chars_per_line: int | None = 21       # 仅 fixed_chars_per_line=True 时有意义
    has_marginal_notes: bool = False      # 是否有夹注

    # ─── 5. 颜色 ───
    color_mode: str = "bw"                 # "bw" | "colored"
    background_color: str = "white"        # "white" | "xuan" | "other"
    text_color: str = "black"              # "black" | "red" | "other"
    border_color: str = "black"            # "black" | "red" | "other"

    # ─── 6. 边框 ───
    # "double" 外粗内细 | "single" | "hsingle_vdouble" 上下单左右双
    border_style: str = "double"
    # "none" | "light" | "medium" | "heavy"
    border_wear: str = "medium"

    # ─── 7. 干扰项 ───
    # "spine_shadow" 书脊阴影 | "margin" 页边距
    interferences: list[str] = field(default_factory=list)
    margin_color: str | None = None        # "white" | "black" | "other" | None

    # ─── 8. 跳过配置 ───
    skip_pages: list[int] = field(default_factory=list)
    skip_steps: list[str] = field(default_factory=list)

    # ─── 9. 元信息 ───
    auto_detected: bool = True
    detection_confidence: dict[str, float] = field(default_factory=dict)

    # ─── 序列化 ───

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BookProfile:
        """从字典创建 BookProfile，忽略未知字段。

        兼容旧版字段：
        - page_type → layout + content_format
        - background_color: null → "white", "orange" → "xuan"
        - interferences: "white_margin" → "margin", 移除 "stains"
        """
        data = dict(data)  # 不修改原字典

        # 向后兼容：page_type → layout + content_format
        if "page_type" in data and "layout" not in data:
            pt = data.pop("page_type")
            if pt == "table":
                data["layout"] = "cut_half"
                data.setdefault("content_format", "table")
            else:
                data["layout"] = pt

        # 向后兼容：background_color 旧值映射
        bg = data.get("background_color")
        if bg is None:
            data["background_color"] = "white"
        elif bg in ("orange", "yellow"):
            data["background_color"] = "xuan"
        elif bg == "red":
            data["background_color"] = "other"

        # 向后兼容：border_color 旧值
        bc = data.get("border_color")
        if bc == "orange":
            data["border_color"] = "red"

        # 向后兼容：interferences 旧值
        intf = data.get("interferences")
        if intf is not None:
            new_intf = []
            for i in intf:
                if i == "white_margin":
                    new_intf.append("margin")
                elif i in ("stains", "water_damage"):
                    continue
                else:
                    new_intf.append(i)
            data["interferences"] = new_intf

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
        return self.layout == "uncut_full"

    @property
    def is_spread(self) -> bool:
        return self.layout == "spread"

    @property
    def is_table(self) -> bool:
        return self.content_format == "table"

    @property
    def needs_split(self) -> bool:
        return self.layout in ("uncut_full", "spread")

    # 兼容旧代码读取 page_type
    @property
    def page_type(self) -> str:
        return self.layout

    @property
    def has_spine_shadow(self) -> bool:
        return "spine_shadow" in self.interferences

    @property
    def has_margin(self) -> bool:
        return "margin" in self.interferences

    # 向后兼容
    @property
    def has_white_margin(self) -> bool:
        return self.has_margin

    def __repr__(self) -> str:
        parts = [
            f"版面={self.layout}",
            f"格式={self.content_format}",
            f"颜色={self.color_mode}",
        ]
        if self.content_format in ("regular", "no_line"):
            parts.append(f"行数={self.lines_per_page}")
            if self.has_marginal_notes:
                parts.append("有夹注")
        elif self.content_format == "table":
            parts.append(f"栏数={self.lines_per_page}")
        if self.interferences:
            parts.append(f"干扰={self.interferences}")
        return f"BookProfile({', '.join(parts)})"
