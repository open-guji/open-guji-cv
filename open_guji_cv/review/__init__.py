"""（拆分 P2 第四批，2026-11-04：本包的 alt_cands, batches, border_cards, borrow_first, cards, causes, cell_shrink_rand, cutline_default, event_write, group_view, invert_cards, jiazhu_cards, label_batches, pending_reason, proof_fields, reasons, seg_causes, seg_defect, shadow, slot_count_cards 已搬去 guji-manager `guji_manager.review`。）

Review 层：审查批次登记 + 卡片壳 + 两种传输。

**批次是人裁的调度单位**：一批卡片、一个 URL（artifact 模式）或一个控制台页面
（server 模式）、一份裁决。登记文件 `review/batches/<id>.json` 取代手写的
`artifacts/README.md` 表格——URL 台账、进度、收割状态都在里面。

设计文档：doc/console_architecture.md §4.3
"""
