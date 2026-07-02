"""アノテーション関連スキーマ。

detect（物体検出）は YOLO bbox 形式、segment（セグメンテーション）は YOLO
segmentation（polygon）形式を扱う。1プロジェクトは detect / segment のどちらか
一方に固定されるため、レスポンスの annotations の中身は task により切り替わる。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnnotationItem(BaseModel):
    """1つのbbox（YOLO正規化形式）。"""

    class_id: int = Field(..., ge=0, description="クラスID（0始まりの整数）")
    x_center: float = Field(..., description="中心X（画像幅に対する0〜1）")
    y_center: float = Field(..., description="中心Y（画像高さに対する0〜1）")
    width: float = Field(..., description="幅（0〜1）")
    height: float = Field(..., description="高さ（0〜1）")


class PolygonPoint(BaseModel):
    """polygon頂点（正規化座標）。"""

    x: float = Field(..., description="X（画像幅に対する0〜1）")
    y: float = Field(..., description="Y（画像高さに対する0〜1）")


class PolygonItem(BaseModel):
    """1つのpolygon（YOLO segmentation 正規化形式）。"""

    type: Literal["polygon"] = "polygon"
    class_id: int = Field(..., ge=0, description="クラスID（0始まりの整数）")
    points: list[PolygonPoint] = Field(default_factory=list, description="頂点（3点以上）")
    source: str = Field("manual", description="生成元: manual / sam（将来対応）")


class AnnotationGetResponse(BaseModel):
    """アノテーション取得レスポンス。

    annotations は task により以下のいずれか:
    - detect: {class_id, x_center, y_center, width, height}
    - segment: {type:"polygon", class_id, points:[{x,y}...], source}
    """

    image_id: str
    image_name: str
    image_width: int
    image_height: int
    task: str = "detect"
    annotations: list[dict[str, Any]] = Field(default_factory=list)


class AnnotationSaveRequest(BaseModel):
    """アノテーション保存リクエスト。空配列も許可（ネガティブ画像）。

    detect は bbox dict、segment は polygon dict を渡す。中身の検証は
    annotation_service が task に応じて行う（不正は400）。
    """

    annotations: list[dict[str, Any]] = Field(default_factory=list)


class AnnotationSaveResponse(BaseModel):
    """アノテーション保存レスポンス。"""

    status: str = "saved"
    label_path: str
    annotation_count: int
    task: str = "detect"
