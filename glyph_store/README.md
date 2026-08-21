# 字形庫（真源）

本目錄是跨書字形庫的**持久真源**，隨倉庫版本管理。
`glyphdb.sqlite` 是可重建的索引，不納入版本控制。

```
python -m open_guji_cv glyph-db rebuild --store glyph_store
```

未導出：未標註實例的圖塊（可從掃描件重跑）、派生表示
（norm/skeleton/feat 是原始圖的純函數，算法升級時必須重算）、
聚類成員（過程資產）。
