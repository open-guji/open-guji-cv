"""三条版式的缺省实现（2026-11-09，书级代码第 2 步：由 books/ 改名而来，代码原样）。

- `keben`：刻本／写本链（keben_body_v2）——原 `impl/keben`（殿本四庫總目）
- `modern`：现代排印本链（modern_body）——原 `impl/modern`（北行日錄）
- `free`：自由版式链（keben_free）——原 `impl/free`（幼學）

这里是 global 代码：书的 `code/` 没覆盖的模块都走它们。只为一本书改的东西放那本书仓的 `code/`
（`core/book_code.py`、`doc/design/书级代码.md`）。缺省实现之间不互相 import，只用 `seg/` 原语。
"""
