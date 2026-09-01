"""单字图块的切分质量：标注格式 + 自检能力评测。

这一步测什么
------------
列切分成单字之后，图块可能有三类毛病（与人工审查用的标记词一致）：

- `contaminated` 混入了不属于本字的墨——界行竖线、版框、上下邻字的残余；
- `truncated`    本字的墨被切掉了一部分；
- `not_text`     这个格位根本不是字（版框角、整条横线、空格位）。

`clean` 是四类里的正例。

为什么按「墨迹」判而不是按「框」判
----------------------------------
图块多裁一点空白**不算失败**——空白不影响下游归一化与识别。所以质量
判定只看墨：混入=多了别人的墨，截断=少了自己的墨，与外接框大小无关。
逐像素的细粒度指标（keep_recall / drop_precision）在合成数据集
`char-segmentation/cells` 上跑，那里能造出逐像素金标；本数据集是**真实
图块**，人工按上述四类给实例级标签，两者互补。

评测的是「自检」而非「切分」
----------------------------
人工标签描述的是**当前**输出的质量，重跑切分后标签就不再对应，无法用作
可自动重跑的回归基准。真正能自动化、也真正有用的问题是：**管线能不能
自己发现这些坏图块**，把它们送进人工审查队列。所以指标是逐类的检出率
与误报率，被测对象是 CharInstance.flags。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = 1

QUALITIES = ("clean", "contaminated", "truncated", "not_text")
DEFECTS = ("contaminated", "truncated", "not_text")

# flag 分两层，用途不同，必须分开报：
#   确定层 成因明确、实测零误报 → 下游可以**直接自动处理**（剥掉界行、
#          丢弃版框格位），不必惊动人；
#   疑似层 用召回换精确 → 只用于把图块送进**人工审查队列**。
# 把两层合成一个「检出率」会同时掩盖两件事：确定层能不能免检地用，
# 以及审查队列会被多少噪声灌满。
CERTAIN_FLAGS = ("rule_bar", "edge_blob", "frame_bars")
SUSPECT_FLAGS = ("wide_gap", "boundary_ink", "off_center",
                 "suspect_empty", "bad_seg")


@dataclass
class InstanceQuality:
    """一个单字图块的质量标注。"""
    book: str
    page: str
    col: int
    idx: int
    quality: str
    layout: str = "rigid"          # 所在列的列型（rigid|elastic），分层用
    defect: str | None = None      # contaminated 的子类：rule_bar（竖界行）/
                                   # frame_bar（横版框、邻字压线）/ 其他。
                                   # 上游要修的是**哪一种定位偏差**，只知道
                                   # 「脏」不够——竖线是切窗横向偏移，横线是
                                   # 网格纵向越界，两条修法完全不同。
    seed: str | None = None        # 抽样来源，用于说明采样偏置
    label_origin: str = "human"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.quality not in QUALITIES:
            raise ValueError(f"未知质量标签 {self.quality!r}，应为 {QUALITIES}")

    @property
    def key(self) -> str:
        """跨册唯一。数据集收了两册之后，只用 page:col:idx 会撞车。"""
        return f"{self.book}/{self.page}:{self.col}:{self.idx}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InstanceQuality":
        # 只取已声明字段：review_recrop 条目带 old_bbox/corrected_bbox 等
        # 溯源键（eval_recrop.py 专用），未知键不应炸
        d = {k: v for k, v in d.items()
             if k in cls.__dataclass_fields__ and k != "schema_version"}
        return cls(**d)


def load_dataset(path: str | Path) -> list[InstanceQuality]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [InstanceQuality.from_dict(r) for r in rows]


def save_dataset(items: list[InstanceQuality], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=1),
        encoding="utf-8")


def evaluate_self_detection(gold: list[InstanceQuality],
                            flags_by_key: dict[str, list[str]]) -> dict:
    """管线自检能力：坏图块能否被 flags 标出，好图块会不会被误报。

    flags_by_key: {"page:col:idx": [flag, ...]}，取自 CharInstance.flags。
    只要有任意 flag 就算「被标记」——驱动人工审查的是有没有进队列，
    而不是标了哪个具体原因。
    """
    per_class: dict[str, dict] = {}
    for q in QUALITIES:
        items = [g for g in gold if g.quality == q]
        if not items:
            continue
        n_flagged = sum(1 for g in items if flags_by_key.get(g.key))
        per_class[q] = {
            "n": len(items),
            "n_flagged": n_flagged,
            "rate": round(n_flagged / len(items), 4),
        }
    layers = {}
    for name, keep in (("certain", CERTAIN_FLAGS), ("all", None)):
        sub = {k: ([f for f in v if f in keep] if keep else v)
               for k, v in flags_by_key.items()}
        d = [g for g in gold if g.quality in DEFECTS]
        c = [g for g in gold if g.quality == "clean"]
        tp = sum(1 for g in d if sub.get(g.key))
        fp = sum(1 for g in c if sub.get(g.key))
        layers[name] = {
            "defect_recall": round(tp / len(d), 4) if d else 0.0,
            "flag_precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "false_alarm_rate": round(fp / len(c), 4) if c else 0.0,
        }

    n_defect = sum(per_class[q]["n"] for q in DEFECTS if q in per_class)
    n_defect_flagged = sum(per_class[q]["n_flagged"]
                           for q in DEFECTS if q in per_class)
    clean = per_class.get("clean", {"n": 0, "n_flagged": 0})
    tp, fp = n_defect_flagged, clean["n_flagged"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / n_defect if n_defect else 0.0
    return {
        "per_class": per_class,
        "defect_recall": round(recall, 4),
        "flag_precision": round(precision, 4),
        "false_alarm_rate": round(clean["n_flagged"] / clean["n"], 4)
                            if clean["n"] else 0.0,
        "n_defect": n_defect,
        "n_clean": clean["n"],
        "layers": layers,
    }


def format_report(report: dict) -> str:
    out = ["【逐类检出率】"]
    for q, v in report["per_class"].items():
        tag = "缺陷" if q in DEFECTS else "正例"
        out.append(f"  {q:<13}({tag}) n={v['n']:>3}  被标记 {v['n_flagged']:>3}"
                   f"  {v['rate']:>6.0%}")
    out += ["",
            f"缺陷检出率 {report['defect_recall']:.0%}"
            f"（{report['n_defect']} 个缺陷）",
            f"标记精确率 {report['flag_precision']:.0%}",
            f"正例误报率 {report['false_alarm_rate']:.0%}"
            f"（{report['n_clean']} 个正例）"]
    lay = report.get("layers")
    if lay:
        out += ["", "【分层】两层用途不同，不能只看合并数字",
                f"  确定层（{'/'.join(CERTAIN_FLAGS)}）"
                f"  召回 {lay['certain']['defect_recall']:>4.0%}"
                f"  精确 {lay['certain']['flag_precision']:>4.0%}"
                f"  误报 {lay['certain']['false_alarm_rate']:>4.0%}"
                "   → 可直接自动处理",
                f"  ＋疑似层（{'/'.join(SUSPECT_FLAGS[:2])} 等）"
                f"  召回 {lay['all']['defect_recall']:>4.0%}"
                f"  精确 {lay['all']['flag_precision']:>4.0%}"
                f"  误报 {lay['all']['false_alarm_rate']:>4.0%}"
                "   → 送人工审查"]
    return "\n".join(out)
