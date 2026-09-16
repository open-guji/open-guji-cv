"""raw_page：原始扫描页。由 Book 提供，不由任何 Step 产出（image_keep）。"""

from ...core.spec import RAW_TL, ProductKindSpec
from ...core.step import register_kind

RAW_PAGE = register_kind(ProductKindSpec(
    id="raw_page", title="原始扫描页", storage="image_keep", unit="page",
    coord_space=RAW_TL, ext="png"))
