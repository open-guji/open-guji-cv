# book9 全书簇识别种子（Claude 视觉识别）

对 book9 完整书（204 页，30285 字符实例）聚类后 size≥4 的 492 个簇，
由 Claude 视觉识别产生的簇级候选（474 簇识别成功、18 个非字残片，
覆盖 5272 实例 / 全书 17%）。

- `mapping.json`      识别清单批次 → 簇 id 映射（clustering.vlm_assist.make_sheets 产物）
- `recognitions.json` 识别结果，语法见 `open_guji_cv/clustering/vlm_assist.py`
                      （"字"=高置信；"字1|字2"=多候选；"~"=低置信；null=非字残片）

用途：在有完整环境的机器上重跑聚类后，用
`clustering.vlm_assist.import_recognitions()` 导入为 candidates.json，
供 review 界面预填候选（一键确认全簇），或与 OCR 候选融合。
注意簇 id 与本仓库当前算法版本的聚类结果对应；算法变更后需重新识别。
