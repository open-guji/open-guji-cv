# fa 發𤼵（同义，按刻形拆判）

## 字形差别
發 ⿱癶㢭：右下 殳（几下又）；𤼵 ⿱癶矤：右下 矢（像 大，长撇长捺）。一眼可分。
殿本 vol21–50 两形都有，𤼵 成片出现在一些页段（vol41、vol45–46、vol48–50 等）。字形库没有 𤼵，库把它排成 發（分差内常紧咬 登 𫉬 顧），
放行字跟整理本走，于是放行成 發 的格里混着刻 𤼵 的；送审格里也有 𤼵。

## 怎么判
方法数组：整字 HOG＋岭回归（`ids_online.SPECS["fa"]`，取右下框 `region=(0.4,1,0.4,1)`，48×48，λ=1，去碎墨），
SHAPE 组，补放与复核改码位（`registry.py` SHAPE_GROUPS）。
- 门槛 0.5。
- 陪衬 `tolerate`：登務條𫉬顧（登務條 进模板库，判成它们＝弃权；𫉬顧 只放行入口）。
- 整理本两形混用，**不要求**补放与整理本同字。
- 模板库 `config/groups/fa/ids_bank.json`：505 格（發 245、𤼵 80，陪衬 登務條 各 60）。

## 评测
建库：`research/m7/glyph_expand/build_shape_pair.py fa <原图> <工作区> <产物> --char-patch --labels=<dataset>/char-groups/variant/fa/sheldon_labels.jsonl --write --dataset=…`。
按册留出 505 格：不设门槛只错 1 格（vol49:49:9:11 發→𤼵，margin 0.12），**门槛 0.5 起 0 错**，给对 發 241、𤼵 77（共 80）。

离线回放 vol21–50 main 包（`replay_groups.py --groups shi,fa --patches`，2026-10-26；这些册的格都在模板库里，是样本内）：
补放 31（全是 𤼵）、改码位 發→𤼵 77、复核照旧 359、仍送审 1；放行结果与标签不一致的只有 2 格（标 𤼵、仍是 發，margin 不够没改）。

## 人工数据
`dataset char-groups/variant/fa/sheldon_labels.jsonl`（468 行，2026-10-25/26）：
- 标注页（https://claude.ai/artifact/9bbu5iubFNW9HgH3Hf4jCR，db 集合 fa）预填机器判的刻形（右下 HOG，A24 逐张看过），
  sheldon 过了一遍，点了 34 格；没点的按预填（src「其余」，建库每册每字 ≤12）。
- 复核 2 格（10-26）：建组后按册留出高把握判反的 vol36:55:2:19（改 𤼵）、vol46:119:1:21（改 發），都是机器对。
- vol48:61:5:7 看图更正为 𤼵（预填误作 發、未被点；与同页 𤼵 同刻形）。
计数：發 357、𤼵 111。`labels.jsonl`／`crops/`／`split.json` 是建库用的 505 格。

## 现状与待办
- 上线：vol21–50 各册 `group_flow` 加 fa；模板库随发版。vol01–20 有没有 𤼵 还没查。
