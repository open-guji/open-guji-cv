"""中心库的读端：pipeline 只留 ``client``（按 sha 从 R2 取钉版文件，取模型、字体、底库语料要用）。

（拆分 P5，2026-11-04：表结构、导入、核对、工作区同步、R2 上传、页表等——connect, gitsource, importer,
materialize, neonapi, packs, pull, r2, scope, sources, workcopy, wsbridge 与 schema.sql——已搬去
guji-manager `guji_manager.datastore`，命令行 ``python -m guji_manager.datastore``。）
"""
