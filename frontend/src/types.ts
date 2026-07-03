// バックエンドAPIに対応する型定義

export type ProjectTask = "detect" | "segment";

export interface ProjectSummary {
  name: string;
  description: string;
  task: ProjectTask;
  created_at: string | null;
  image_count: number;
  label_count: number;
  class_count: number;
  train_count: number;
}

export interface ClassItem {
  id: number;
  name: string;
  color: string;
}

export interface ClassInput {
  name: string;
  color?: string;
}

export interface ImportItem {
  filename: string;
  status: string;
  width: number | null;
  height: number | null;
  hash: string | null;
  detail: string;
}

export interface FolderImportResponse {
  project_name: string;
  imported_count: number;
  skipped_count: number;
  duplicate_count: number;
  broken_count: number;
  unsupported_count: number;
  items: ImportItem[];
}

export interface ImageInfo {
  filename: string;
  width: number;
  height: number;
  size_bytes: number;
  sha1: string;
  has_label: boolean;
  low_resolution: boolean;
}

export interface UploadResultItem {
  original_name: string;
  stored_name: string | null;
  status: string;
  detail: string;
}

export interface UploadResponse {
  results: UploadResultItem[];
  added: number;
  skipped: number;
}

export interface AnnotationItem {
  class_id: number;
  x_center: number;
  y_center: number;
  width: number;
  height: number;
}

export interface PolygonPoint {
  x: number;
  y: number;
}

// segment（polygon）アノテーション。points は正規化座標(0〜1)。
export interface PolygonItem {
  type: "polygon";
  class_id: number;
  points: PolygonPoint[];
  source?: "manual" | "sam";
}

export interface AnnotationGetResponse {
  image_id: string;
  image_name: string;
  image_width: number;
  image_height: number;
  task: ProjectTask;
  // detect: AnnotationItem[], segment: PolygonItem[]
  annotations: AnnotationItem[] | PolygonItem[];
}

export interface AnnotationSaveResponse {
  status: string;
  label_path: string;
  annotation_count: number;
  task: ProjectTask;
}

// --- SAM支援アノテーション ---
export interface SamSettings {
  model: string;
  device: string;
  polygon_simplify_epsilon: number;
  min_area: number;
  max_points: number;
  merge_nearby_regions: boolean;
  merge_distance_px: number;
}

export interface SamBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface SamPromptPayload {
  type: "box" | "point";
  box?: SamBox | null;
  positive_points: PolygonPoint[];
  negative_points: PolygonPoint[];
}

export interface SamProposeRequest {
  source: string;
  class_id: number;
  prompt: SamPromptPayload;
  settings?: SamSettings | null;
}

export interface SamCandidate {
  candidate_id: string;
  score: number | null;
  area: number | null;
  points: PolygonPoint[];
  bbox: SamBox | null;
  merged?: boolean | null;
  source_mask_count?: number | null;
}

export interface SamProposeResponse {
  project_name: string;
  image_id: string;
  class_id: number;
  source: string;
  candidates: SamCandidate[];
  message: string | null;
}

export interface LabelIssue {
  severity: "error" | "warning";
  type: string;
  image_id: string | null;
  image_name: string | null;
  label_path: string | null;
  line_number: number | null;
  message: string;
}

export interface ClassStat {
  class_id: number;
  class_name: string;
  bbox_count: number;
  image_count: number;
}

export interface ValidationSummary {
  image_count: number;
  label_file_count: number;
  annotated_image_count: number;
  empty_label_image_count: number;
  missing_label_count: number;
  orphan_label_count: number;
  total_bbox_count: number;
  error_count: number;
  warning_count: number;
}

export interface LabelValidationResponse {
  project_name: string;
  summary: ValidationSummary;
  class_stats: ClassStat[];
  issues: LabelIssue[];
}

export interface DatasetCreateRequest {
  dataset_name: string;
  train_ratio: number;
  val_ratio: number;
  test_ratio: number;
  seed: number;
  include_empty_labels: boolean;
  include_unlabeled_images: boolean;
  overwrite: boolean;
  image_source: string;
  use_selection: boolean;
  include_review_images: boolean;
}

export interface DatasetSummary {
  train_image_count: number;
  val_image_count: number;
  test_image_count: number;
  total_image_count: number;
  class_count: number;
}

export interface DatasetCreateResponse {
  project_name: string;
  dataset_name: string;
  dataset_path: string;
  summary: DatasetSummary;
  data_yaml_path: string;
  image_source: string;
  warning: string | null;
}

export interface PreprocessSettings {
  job_name: string;
  overwrite: boolean;
  output_format: string;
  resize_enabled: boolean;
  resize_mode: string | null;
  resize_size: number;
  resize_width: number;
  resize_height: number;
  keep_aspect_ratio: boolean;
  padding: boolean;
  padding_color: string;
  brightness_enabled: boolean;
  brightness: number;
  contrast_enabled: boolean;
  contrast: number;
  grayscale_enabled: boolean;
  binary_enabled: boolean;
  binary_threshold: number;
  binary_invert: boolean;
  sharpen_enabled: boolean;
  sharpen_strength: number;
  clahe_enabled: boolean;
  clahe_clip_limit: number;
  clahe_tile_grid_size: number;
}

export interface PreprocessRunResponse {
  project_name: string;
  job_name: string;
  status: string;
  input_count: number;
  processed_count: number;
  skipped_count: number;
  processed_dir: string;
  metadata_path: string;
  warning: string | null;
}

export interface PreprocessInfoResponse {
  project_name: string;
  has_processed_images: boolean;
  processed_count: number;
  processed_dir: string;
  metadata: Record<string, unknown> | null;
}

export interface PreprocessPreviewResponse {
  project_name: string;
  image_id: string;
  before_url: string;
  preview_url: string;
  before_width: number;
  before_height: number;
  after_width: number;
  after_height: number;
}

export interface SelectionRotateResponse {
  image_id: string;
  source: string;
  angle: number;
  width: number;
  height: number;
  warning: string | null;
}

export interface SelectionRunRequest {
  source: string;
  min_width: number;
  min_height: number;
  blur_threshold: number;
  dark_threshold: number;
  bright_threshold: number;
  detect_duplicates: boolean;
  overwrite: boolean;
}

export interface SelectionItem {
  image_id: string;
  image_name: string;
  source: string;
  width: number;
  height: number;
  status: string;
  warnings: string[];
  reasons: string[];
  hash: string | null;
  brightness_mean: number | null;
  blur_score: number | null;
  duplicate_of: string | null;
  manual_reason: string | null;
}

export interface SelectionSummary {
  image_count: number;
  included_count: number;
  excluded_count: number;
  review_count: number;
  duplicate_count: number;
  small_count: number;
  dark_count: number;
  bright_count: number;
  blur_count: number;
}

export interface SelectionRunResponse {
  project_name: string;
  source: string;
  summary: SelectionSummary;
  selection_path: string;
}

export interface SelectionGetResponse {
  project_name: string;
  source: string;
  summary: SelectionSummary;
  items: SelectionItem[];
}

export interface ReportCreateRequest {
  report_name?: string | null;
  include_images?: boolean;
  include_predictions?: boolean;
  include_analysis?: boolean;
  format: string;
}

export interface ReportGenerateResponse {
  project_name: string;
  report_id: string;
  created_at: string;
  markdown_path: string | null;
  json_path: string;
}

export interface ReportListItem {
  report_id: string;
  created_at: string | null;
  markdown_path: string | null;
  json_path: string;
}

export interface ReportListResponse {
  project_name: string;
  reports: ReportListItem[];
}

export interface ReportDetailResponse {
  project_name: string;
  report_id: string;
  content: Record<string, unknown>;
}

export interface DatasetListItem {
  dataset_name: string;
  dataset_path: string;
  created_at: string | null;
  train_image_count: number;
  val_image_count: number;
  test_image_count: number;
  class_count: number;
  task?: ProjectTask;
  data_yaml_path: string;
}

export interface DatasetListResponse {
  project_name: string;
  datasets: DatasetListItem[];
}

export interface TrainJobCreateRequest {
  dataset_name: string;
  job_name: string;
  task?: ProjectTask | null;
  model: string;
  epochs: number;
  imgsz: number;
  batch: number;
  device: string;
  workers: number;
  patience: number;
  seed: number;
  overwrite: boolean;
  augmentation_preset?: string | null;
  augmentation_params?: Record<string, number> | null;
}

export interface TrainJobStartResponse {
  project_name: string;
  job_id: string;
  job_name: string;
  status: string;
  run_path: string;
  log_path: string;
}

export interface TrainJobInfo {
  project_name: string | null;
  job_id: string;
  job_name: string | null;
  dataset_name: string | null;
  task?: ProjectTask | null;
  model: string | null;
  epochs: number | null;
  imgsz: number | null;
  batch: number | null;
  device: string | null;
  workers: number | null;
  patience: number | null;
  seed: number | null;
  status: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  return_code: number | null;
  run_path: string | null;
  best_model_path: string | null;
  last_model_path: string | null;
  results_csv_path: string | null;
  message: string | null;
}

export interface TrainJobListResponse {
  project_name: string;
  jobs: TrainJobInfo[];
}

export interface TrainLogLine {
  level: "error" | "warning" | "info" | "normal";
  text: string;
}

export interface TrainLogResponse {
  job_id: string;
  log: string;
  lines: TrainLogLine[];
  error_summary: string | null;
}

export interface EvaluationSummary {
  epoch: number | null;
  precision: number | null;
  recall: number | null;
  map50: number | null;
  map50_95: number | null;
  mask_precision: number | null;
  mask_recall: number | null;
  mask_map50: number | null;
  mask_map50_95: number | null;
  train_box_loss: number | null;
  train_cls_loss: number | null;
  train_dfl_loss: number | null;
  val_box_loss: number | null;
  val_cls_loss: number | null;
  val_dfl_loss: number | null;
}

export interface Artifact {
  name: string;
  type: string;
  path: string;
  url: string;
}

export interface EvaluationResponse {
  project_name: string;
  job_id: string;
  status: string;
  run_path: string;
  has_results_csv: boolean;
  has_best_model: boolean;
  has_last_model: boolean;
  summary: EvaluationSummary | null;
  artifacts: Artifact[];
}

export interface MetricsResponse {
  project_name: string;
  job_id: string;
  columns: string[];
  rows: Record<string, number | string | null>[];
}

export interface PredictJobCreateRequest {
  predict_job_name: string;
  train_job_id: string;
  weight_type: string;
  source_type: string;
  image_ids: string[];
  conf: number;
  iou: number;
  imgsz: number;
  device: string;
  save_txt: boolean;
  save_conf: boolean;
  overwrite: boolean;
  preprocess_mode: string;
}

export interface PredictJobStartResponse {
  project_name: string;
  predict_job_id: string;
  status: string;
  prediction_path: string;
  log_path: string;
}

export interface PredictJobInfo {
  project_name: string | null;
  predict_job_id: string;
  predict_job_name: string | null;
  train_job_id: string | null;
  weight_type: string | null;
  source_type: string | null;
  status: string;
  conf: number | null;
  iou: number | null;
  imgsz: number | null;
  device: string | null;
  save_txt: boolean | null;
  save_conf: boolean | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  return_code: number | null;
  message: string | null;
  image_count: number | null;
  detection_count: number | null;
  total_count: number | null;
  processed_count: number | null;
  prediction_path: string | null;
  results_json_path: string | null;
}

export interface PredictJobListResponse {
  project_name: string;
  jobs: PredictJobInfo[];
}

export interface PredictLogResponse {
  predict_job_id: string;
  log: string;
}

export interface Detection {
  class_id: number;
  class_name: string | null;
  confidence: number;
  x_center: number;
  y_center: number;
  width: number;
  height: number;
}

export interface PredictResultItem {
  image_id: string;
  image_name: string;
  result_image_url: string | null;
  detections: Detection[];
}

export interface PredictResultsResponse {
  project_name: string;
  predict_job_id: string;
  image_count: number;
  detection_count: number;
  results: PredictResultItem[];
}

// --- 映像（カメラ）推論 ---
export interface CameraInfo {
  index: number;
  label: string;
}

export interface CameraListResponse {
  cameras: CameraInfo[];
}

export interface VideoJobCreateRequest {
  video_job_name: string;
  train_job_id: string;
  weight_type: string;
  camera_index: number;
  video_fps: number;
  infer_fps: number;
  conf: number;
  iou: number;
  imgsz: number;
  device: string;
  preprocess_mode: string;
  overwrite: boolean;
}

export interface VideoJobInfo {
  project_name: string | null;
  video_job_id: string;
  train_job_id: string | null;
  weight_type: string | null;
  camera_index: number | null;
  video_fps: number | null;
  infer_fps: number | null;
  preprocess_mode: string | null;
  status: string;
  message: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  stream_url: string | null;
}

export interface VideoJobListResponse {
  project_name: string;
  jobs: VideoJobInfo[];
}

export interface AnalysisBbox {
  x_center: number;
  y_center: number;
  width: number;
  height: number;
}

export interface AnalysisItem {
  type: "tp" | "fp" | "fn" | "class_mismatch";
  class_id: number | null;
  class_name: string | null;
  gt_class_id: number | null;
  gt_class_name: string | null;
  confidence: number | null;
  iou: number | null;
  prediction_bbox: AnalysisBbox | null;
  ground_truth_bbox: AnalysisBbox | null;
}

export interface AnalysisCounts {
  ground_truth_count: number;
  prediction_count: number;
  tp_count: number;
  fp_count: number;
  fn_count: number;
  class_mismatch_count: number;
  precision: number;
  recall: number;
  f1: number;
}

export interface AnalysisClassStat extends AnalysisCounts {
  class_id: number;
  class_name: string | null;
}

export interface AnalysisImageResult extends AnalysisCounts {
  image_id: string;
  image_name: string;
  result_image_url: string | null;
  items: AnalysisItem[];
}

export interface AnalysisSummary extends AnalysisCounts {
  image_count: number;
}

export interface AnalysisResponse {
  project_name: string;
  predict_job_id: string;
  iou_threshold: number;
  conf_threshold: number;
  summary: AnalysisSummary;
  class_stats: AnalysisClassStat[];
  image_results: AnalysisImageResult[];
}

export interface LatestAnalysis {
  predict_job_id: string;
  tp_count: number;
  fp_count: number;
  fn_count: number;
  class_mismatch_count: number;
  precision: number;
  recall: number;
  f1: number;
}

export interface ExperimentListItem {
  experiment_id: string;
  train_job_id: string;
  status: string;
  dataset_name: string | null;
  model: string | null;
  epochs: number | null;
  imgsz: number | null;
  batch: number | null;
  device: string | null;
  created_at: string | null;
  finished_at: string | null;
  train_image_count: number | null;
  val_image_count: number | null;
  class_count: number | null;
  precision: number | null;
  recall: number | null;
  map50: number | null;
  map50_95: number | null;
  best_model_path: string | null;
  augmentation_preset: string | null;
  latest_analysis: LatestAnalysis | null;
}

export interface ExperimentListResponse {
  project_name: string;
  experiments: ExperimentListItem[];
}

export interface ExperimentDataset {
  dataset_name: string | null;
  train_image_count: number | null;
  val_image_count: number | null;
  test_image_count: number | null;
  total_image_count: number | null;
  class_count: number | null;
  train_ratio: number | null;
  val_ratio: number | null;
  test_ratio: number | null;
  include_empty_labels: boolean | null;
  include_unlabeled_images: boolean | null;
  seed: number | null;
}

export interface ExperimentEvaluation {
  precision: number | null;
  recall: number | null;
  map50: number | null;
  map50_95: number | null;
  train_box_loss: number | null;
  val_box_loss: number | null;
  has_best_model: boolean;
  has_last_model: boolean;
  has_results_csv: boolean;
}

export interface ExperimentPrediction {
  predict_job_id: string;
  status: string | null;
  image_count: number | null;
  detection_count: number | null;
  analysis: Omit<LatestAnalysis, "predict_job_id"> | null;
}

export interface ExperimentDetailResponse {
  project_name: string;
  experiment_id: string;
  train_job: TrainJobInfo | null;
  dataset: ExperimentDataset | null;
  evaluation: ExperimentEvaluation | null;
  predictions: ExperimentPrediction[];
}

export interface ModelItem {
  model_id: string;
  train_job_id: string;
  weight_type: string;
  model_path: string;
  exists: boolean;
  file_size_bytes: number | null;
  created_at: string | null;
  train_status: string | null;
  dataset_name: string | null;
  base_model: string | null;
  epochs: number | null;
  imgsz: number | null;
  batch: number | null;
  device: string | null;
  precision: number | null;
  recall: number | null;
  map50: number | null;
  map50_95: number | null;
  augmentation_preset: string | null;
  latest_analysis: LatestAnalysis | null;
  is_selected: boolean;
}

export interface ModelPackageResponse {
  project_name: string;
  model_id: string;
  package_id: string;
  status: string;
  zip_path: string;
  files: string[];
}

export interface OnnxExportCreateRequest {
  train_job_id: string;
  weight_type: string;
  export_job_name?: string | null;
  imgsz?: number | null;
  opset: number;
  simplify: boolean;
  dynamic: boolean;
  half: boolean;
  device: string;
  overwrite: boolean;
}

export interface OnnxExportInfo {
  project_name: string | null;
  export_job_id: string;
  train_job_id: string | null;
  weight_type: string | null;
  source_weight_path: string | null;
  task: string | null;
  format: string | null;
  imgsz: number | null;
  opset: number | null;
  simplify: boolean | null;
  dynamic: boolean | null;
  half: boolean | null;
  device: string | null;
  status: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  return_code: number | null;
  onnx_path: string | null;
  export_path: string | null;
  message: string | null;
}

export interface OnnxExportStartResponse {
  project_name: string;
  export_job_id: string;
  status: string;
  export_path: string;
  log_path: string;
}

export interface OnnxExportListResponse {
  project_name: string;
  exports: OnnxExportInfo[];
}

export interface OnnxExportLogResponse {
  export_job_id: string;
  log: string;
  lines: TrainLogLine[];
  error_summary: string | null;
}

export interface ModelListResponse {
  project_name: string;
  selected_model_id: string | null;
  models: ModelItem[];
}

export interface ModelDetailResponse {
  project_name: string;
  model_id: string;
  train_job_id: string;
  weight_type: string;
  model_path: string;
  exists: boolean;
  file_size_bytes: number | null;
  train_job: TrainJobInfo | null;
  evaluation: ExperimentEvaluation | null;
  predictions: ExperimentPrediction[];
  is_selected: boolean;
}

export interface SelectedModelResponse {
  project_name: string;
  selected_model_id: string;
  train_job_id: string;
  weight_type: string;
  model_path: string;
  selected_at: string | null;
  memo: string;
}

export type AugmentationParams = Record<string, number>;

export interface AugmentationPreset {
  name: string;
  description: string;
  params: AugmentationParams;
  builtin: boolean;
}

export interface AugmentationPresetListResponse {
  project_name: string;
  presets: AugmentationPreset[];
}
