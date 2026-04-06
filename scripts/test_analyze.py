"""在 data/ 下的 8 本书上运行 analyze，对比检测结果与已知标注。"""
import sys
sys.path.insert(0, ".")

from open_guji_cv.pipeline import GujiPipeline

BOOKS = [
    "data/book1", "data/book2", "data/book3", "data/book4",
    "data/book5", "data/book6", "data/book7", "data/book8",
]

# 已知标注（来自 README）
EXPECTED = {
    "data/book1": {"page_type": "cut_half",   "lines": 8,  "color": "bw",      "border": "double", "marginal": False},
    "data/book2": {"page_type": "uncut_full", "lines": 9,  "color": "bw",      "border": "double", "marginal": False},
    "data/book3": {"page_type": "cut_half",   "lines": 8,  "color": "colored",  "border": "double", "marginal": False},
    "data/book4": {"page_type": "cut_half",   "lines": 8,  "color": "colored",  "border": "double", "marginal": True},
    "data/book5": {"page_type": "cut_half",   "lines": 9,  "color": "bw",      "border": "double", "marginal": True},
    "data/book6": {"page_type": "cut_half",   "lines": 8,  "color": "bw",      "border": "double", "marginal": False},
    "data/book7": {"page_type": "table",      "lines": 0,  "color": "bw",      "border": "single", "marginal": False},
    "data/book8": {"page_type": "spread",     "lines": 9,  "color": "colored",  "border": "double", "marginal": False},
}

pipeline = GujiPipeline()

for book in BOOKS:
    print(f"\n{'='*60}")
    print(f"  {book}")
    print(f"{'='*60}")

    try:
        profile = pipeline.analyze(book)
    except Exception as e:
        print(f"  ERROR: {e}")
        continue

    exp = EXPECTED.get(book, {})

    def check(label, detected, expected):
        ok = "OK" if detected == expected else "MISMATCH"
        print(f"  {label:20s}: {str(detected):15s} (expected: {str(expected):15s}) [{ok}]")

    check("page_type",      profile.page_type,         exp.get("page_type"))
    check("lines_per_page", profile.lines_per_page,    exp.get("lines"))
    check("color_mode",     profile.color_mode,         exp.get("color"))
    check("border_style",   profile.border_style,       exp.get("border"))
    check("has_marginal",   profile.has_marginal_notes, exp.get("marginal"))

    # 额外信息
    print(f"  {'border_wear':20s}: {profile.border_wear}")
    print(f"  {'chars_per_line':20s}: {profile.chars_per_line}")
    print(f"  {'interferences':20s}: {profile.interferences}")
    print(f"  {'confidence':20s}: {profile.detection_confidence}")
