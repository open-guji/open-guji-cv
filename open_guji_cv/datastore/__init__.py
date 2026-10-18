"""中心库（Neon Postgres ＋ R2）的表结构、导入、核对与图片上传（GUJI-603 / GUJI-605）。

设计见 ai-team `通用/中心库设计.md`。本包不进任何 Step 的 ``code_deps``，改它不会让产物过期。

- ``schema.sql``  表结构（可重复执行）
- ``scope``       guji-workspace 里哪些文件进库、落哪张表
- ``importer``    某个 git 提交 → Postgres，幂等
- ``verify``      库与提交逐行、逐文件核对
- ``r2``          刻例图、锚图按 sha256 上 R2（默认只出清单）

命令行：``python -m open_guji_cv.datastore --help``。
"""
