"""SAM支援アノテーション関連スキーマ。

座標はすべて画像幅・高さで正規化した 0.0〜1.0 で扱う。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# 許可モデル / デバイス
ALLOWED_SAM_MODELS = ("sam_b.pt", "sam_l.pt", "sam2_t.pt", "sam2_b.pt")
ALLOWED_SAM_DEVICES = ("auto", "cpu", "cuda")


class SamSettings(BaseModel):
    """SAM設定。"""

    model: str = "sam2_t.pt"
    device: str = "auto"
    polygon_simplify_epsilon: float = 2.0
    min_area: int = 50
    max_points: int = 300
    # 近接領域マージ（SAM Point で複数点→複数領域を1つにまとめる）
    merge_nearby_regions: bool = True
    merge_distance_px: int = 8


class SamBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class SamPoint(BaseModel):
    x: float
    y: float


class SamPrompt(BaseModel):
    """SAMプロンプト。type=box は box、type=point は positive/negative_points を使う。"""

    type: str = "box"  # box | point
    box: SamBox | None = None
    positive_points: list[SamPoint] = Field(default_factory=list)
    negative_points: list[SamPoint] = Field(default_factory=list)


class SamProposeRequest(BaseModel):
    """SAM候補生成リクエスト。"""

    source: str = "auto"  # auto | raw | processed
    class_id: int = Field(0, ge=0)
    prompt: SamPrompt
    settings: SamSettings | None = None  # 省略時は保存済み設定を使用


class SamCandidate(BaseModel):
    """SAM候補polygon（正規化座標）。"""

    candidate_id: str
    score: float | None = None
    area: float | None = None  # ピクセル面積
    points: list[SamPoint]
    bbox: SamBox | None = None
    merged: bool | None = None  # 複数領域をまとめた候補か
    source_mask_count: int | None = None  # 元となったmask/領域数


class SamProposeResponse(BaseModel):
    project_name: str
    image_id: str
    class_id: int
    source: str
    candidates: list[SamCandidate]
    message: str | None = None
