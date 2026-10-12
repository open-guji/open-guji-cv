# 已作废:runt10_exclusion_proposal.jsonl

排除名单 2026-09-20 起**不收 `seg_defect`**(用户定:bxgb 131 条 seg_defect 全是真字,藏进名单会让 Step7 准入闸看不到)。这 10 格改走**逐列字数人裁**(`review/slot_count_cards.py`,答案=该列实际字数 20),根因与验证见 `overlays/n20_resolve_*.png`、dataset 分支 `claude/C5-tail-runt-review-1012` 的 `char-segmentation/tail-runt-review/README.md`。`runt10_exclusion_proposal.jsonl` 保留作记录,**不要写入 `crop_exclusions`**。
