"""刻本古籍字符聚类识别（Phase 4~7）。

模块总览（详细设计见 .claude/doc/char_clustering_design.md）：

- ids            全局字符实例 ID（book:page:col:idx）
- extractor      M1 字符提取（phase3 网格 → 单字图块数据集）
- normalize      M2 图块归一化（Sauvola 二值化 + 质心居中缩放）
- features       M2 特征后端注册表（raw / hog）
- verify         M3 两两配准验证（保守聚类的核心判据）
- clusterer      M3 分块 + kNN + 验证 + 全连接合并
- variants       异体字→正字（语义层）映射表
- candidates     M4 簇级候选生成（字形库 kNN / OCR / 弱先验融合）
- lm             M5 语言模型后端（字符 n-gram，语义层）
- context_rank   M5 列 lattice + beam search 上下文排序
- feedback       M7 标签事件流重放 + 阈值标定
- glyph_library  M8 跨书字形库
- synth          合成刻本数据生成（测试 / benchmark）
"""

from .ids import CharId, make_id, parse_id
from .extractor import CharExtractor, CharInstance
from .clusterer import ConservativeClusterer
from .glyph_library import GlyphLibrary

__all__ = [
    "CharId", "make_id", "parse_id",
    "CharExtractor", "CharInstance",
    "ConservativeClusterer",
    "GlyphLibrary",
]
