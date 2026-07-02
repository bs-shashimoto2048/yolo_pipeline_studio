"""誤検出分析関連スキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class AnalysisRequest(BaseModel):
    """誤検出分析リクエスト（しきい値はサービス側で 0〜1 を検証）。"""

    iou_threshold: float = 0.5
    conf_threshold: float = 0.25


class Bbox(BaseModel):
    x_center: float
    y_center: float
    width: float
    height: float


class AnalysisItem(BaseModel):
    """画像内の1判定（tp / fp / fn / class_mismatch）。"""

    type: str
    class_id: int | None = None  # 予測クラス（fnはGTクラス）
    class_name: str | None = None
    gt_class_id: int | None = None  # class_mismatch時のGTクラス
    gt_class_name: str | None = None
    confidence: float | None = None
    iou: float | None = None
    prediction_bbox: Bbox | None = None
    ground_truth_bbox: Bbox | None = None


class AnalysisCounts(BaseModel):
    ground_truth_count: int = 0
    prediction_count: int = 0
    tp_count: int = 0
    fp_count: int = 0
    fn_count: int = 0
    class_mismatch_count: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


class ClassStat(AnalysisCounts):
    class_id: int
    class_name: str | None = None


class ImageResult(AnalysisCounts):
    image_id: str
    image_name: str
    result_image_url: str | None = None
    items: list[AnalysisItem] = []


class AnalysisSummary(AnalysisCounts):
    image_count: int = 0


class AnalysisResponse(BaseModel):
    project_name: str
    predict_job_id: str
    iou_threshold: float
    conf_threshold: float
    summary: AnalysisSummary
    class_stats: list[ClassStat] = []
    image_results: list[ImageResult] = []
