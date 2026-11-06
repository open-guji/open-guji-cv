# 私用码映射真字·第一步脚本（A24 2026-11-06）

结果与说明见 ai-team `domain/CV/交接/私用码映射-第一步-2026-11-06/`。研究脚本，不进 Step、不进指纹、不改任何产物。

- `scan_all.py`：流式扫殆知阁 0001–1500（`curl` 取、不落盘），统计未映上的私用码用量。
- `build_candidates.py`：總目 142 码候选表（殆知阁源＋维基 Module:SKchar／SKchar2＋siku-qiefen-v2 文本层＋IDS 反查，合并 F→E 对照、待收字登记、code_table）。
- `make_review_items.py`：候选表 → `guji-manager review-pages build char_card --no-rest-ok` 的 items（本书切图从 v2 页图按文本层字框裁，维基 SKQS 标准图并排；需 guji-manager ≥ char_card 1.5.0）。
