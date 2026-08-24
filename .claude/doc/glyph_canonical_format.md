# 字形图块统一存储格式（canonical form）

> 2026-08-24 定稿并完成迁移。实现：`open_guji_cv/clustering/canonical.py`；
> 迁移脚本：`scripts/canonicalize_glyph_store.py`。背景：扩库要引入多来源
> 字形（管线裁切 / 字体渲染 / 字典扫描 / 外部数据集），各来源图片尺寸、
> 灰度、居中方式都不一样，必须先统一存储格式，否则库内不可比。

## 1. 规格

| 维度 | 决定 | 理由 |
|---|---|---|
| 画布 | **200×200 固定** | 行业并没有统一标准（各数据集 64/96/128/224 都有，200×200 只是某些项目的选择，不是规范）。选 200 的依据：≈ 本项目扫描件单字原生分辨率的上界（book9all 实测高 127~167、宽 103~175，中位 133×117），匹配层 64×64 的 3 倍余量，算法升级到更高分辨率时真源不用重做 |
| 文件格式 | **8-bit 灰度 PNG，白底(255)黑字** | 无损；管线裁切本来就近二值（s6 产物 0/255），存灰度对它无成本；扫描/渲染来源保留灰度信息，二值化交给下游（Sauvola 是匹配层的事，参数会演进，真源不预烧） |
| 缩放 | **等比、只缩不放**：墨迹外接框超出内容区（200×(1−2×0.12)=152px）才 INTER_AREA 缩小，否则保持原生像素 | 实测结论（见 §3）：放大重采样 + 下游再二值化会让 pairs 金标的 coverage 判定翻转 10/60；只缩不放降到 1/60、逐实例自扰动 0。代价是画布内墨迹大小不完全统一——可接受，因为匹配层（normalize_patch）反正要做自己的缩放居中，相对字号元数据在 instances 表（width/height/bbox）也没丢 |
| 居中 | **墨迹质心（centroid）对准画布中心**，clamp 不出界 | 与匹配层 normalize_patch 的居中规则同一套，全库唯一算法。不用 bbox 几何中心：质心对笔画分布不对称的字（如「戈」「乙」）更稳定，且和匹配层一致意味着 canonical 图直接喂 normalize_patch 时居中几乎是 no-op |
| 纵横比 | **保留真实纵横比** | 匹配层的 ±20% 各向异性拉伸是算法技巧，不进真源 |
| 清理 | 边缘残渣清理（`remove_edge_specks` + `_drop_stray_components`，连灰晕一起抹白）**只在原始裁切 → canonical 这一次发生** | 这些贴边启发式只对「带 padding 的原始裁切」几何有效。canonical 图约定为干净单字、墨迹不贴边，下游再跑这些规则自然退化为 no-op，不会误咬「丨刂囗」类贴边笔画。字体渲染等本就干净的来源可 `clean=False` 跳过 |
| 不做 | 二值化 / 骨架化 / 笔宽归一 | 全是匹配层派生物（derived，带 algo_version），rebuild 时按当前算法重算。真源只做几何统一 |

一句话：**canonical = 干净单字 + 统一画布 + 统一居中，其余一切留给匹配层。**

## 2. 数据流

```
管线：phase4 原始裁切 ──to_canonical(clean=True)──┐   （glyph_db.import_book 里做）
字体：render → 大图留白 ─to_canonical(clean=False)─┼→ glyph_store/patches/*.png（真源）
扫描：切分净化后的裁切 ─to_canonical(clean=True)──┘        │ rebuild
                                                 normalize_patch → 64×64 派生物（norm/skel/feat）
查询侧：簇代表原始图块 → to_canonical → normalize_patch → query()
```

- 入库口：`glyph_db.import_book()` 在写 `instances.patch_png` 时统一转
  canonical；`export_store()` 顺带清理不被引用的孤儿 PNG。
- 查询侧对称：`GlyphKnnSource.propose()` 同样先 `to_canonical` 再
  `normalize_patch`——库侧派生物算自 canonical 图，两边预处理必须走同一条路。
- phase4/phase5 的中间产物**不受影响**（聚类、verify 仍在各书输出目录的
  原始裁切上进行），canonical 只管跨书字形库这一层。

## 3. 迁移记录与验证（2026-08-24）

`scripts/canonicalize_glyph_store.py`（支持 --dry-run）对 book9all 的
94 个被引用图块执行迁移，并删除 53 个孤儿 PNG（30 个 export 遗留 +
23 个旧 GlyphLibrary 时代的 g_*.png 64×64 二值遗留物）。验证三道：

1. **逐实例自扰动**：旧图归一 vs 新图归一，94/94 判 same（最差 f1=0.995）；
2. **pairs 金标**（可比 60 对）：overlap 判定翻转 0，coverage 翻转 1
   （0.995→0.989，阈值 0.992 贴线抖动，该对本就在操作点边缘）；
3. **自查询回归**：每个 exemplar 以 canonical 图查库，top-1 命中本字且
   verdict=same，94/94。

选型实验（同一套金标）：放大插值 cubic/linear/lanczos/nearest 的 coverage
翻转分别为 10/9/13/11，只缩不放 = 1。故规格定为只缩不放。

## 4. 对外部来源的约定（P1 起适用）

- **字体渲染**：直接渲染到 ≤152px 字面并留足白边（画布 ≥200），
  `to_canonical(clean=False)`。不要先渲小图再依赖放大。
- **字典扫描**（康熙等）：先完成切分与去噪（等价 phase4 的职责），
  canonical 化时 `clean=True` 兜底。
- 高分辨率来源（>152px 字面）会被 INTER_AREA 缩小——这是唯一有损路径，
  可接受（信息只多不少）。
- `edition_tag` 按来源分域（`font:jigmo` / `kangxi-scan` / …），
  见 glyph_db_expansion_research.md §4。
