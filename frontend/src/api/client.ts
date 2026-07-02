// バックエンドAPIクライアント
import type {
  AnalysisResponse,
  AugmentationParams,
  AugmentationPreset,
  AugmentationPresetListResponse,
  AnnotationGetResponse,
  AnnotationItem,
  AnnotationSaveResponse,
  PolygonItem,
  ProjectTask,
  SamSettings,
  SamProposeRequest,
  SamProposeResponse,
  ClassInput,
  ClassItem,
  DatasetCreateRequest,
  FolderImportResponse,
  DatasetCreateResponse,
  DatasetListResponse,
  EvaluationResponse,
  ExperimentDetailResponse,
  ExperimentListResponse,
  ImageInfo,
  MetricsResponse,
  LabelValidationResponse,
  ModelDetailResponse,
  ModelListResponse,
  ModelPackageResponse,
  OnnxExportCreateRequest,
  OnnxExportInfo,
  OnnxExportListResponse,
  OnnxExportLogResponse,
  OnnxExportStartResponse,
  PreprocessInfoResponse,
  PreprocessPreviewResponse,
  PreprocessRunResponse,
  PreprocessSettings,
  SelectionGetResponse,
  SelectionRotateResponse,
  SelectionRunRequest,
  SelectionRunResponse,
  ReportCreateRequest,
  ReportDetailResponse,
  ReportGenerateResponse,
  ReportListResponse,
  SelectedModelResponse,
  PredictJobCreateRequest,
  PredictJobInfo,
  PredictJobListResponse,
  PredictJobStartResponse,
  PredictLogResponse,
  PredictResultsResponse,
  CameraListResponse,
  VideoJobCreateRequest,
  VideoJobInfo,
  VideoJobListResponse,
  ProjectSummary,
  TrainJobCreateRequest,
  TrainJobInfo,
  TrainJobListResponse,
  TrainJobStartResponse,
  TrainLogResponse,
  UploadResponse,
} from "../types";

const BASE = "/api";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  async health(): Promise<{ message: string }> {
    return handle(await fetch(`${BASE}/health`));
  },

  async listProjects(): Promise<ProjectSummary[]> {
    return handle(await fetch(`${BASE}/projects`));
  },

  async createProject(
    name: string,
    description = "",
    task: ProjectTask = "detect"
  ): Promise<ProjectSummary> {
    return handle(
      await fetch(`${BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, task }),
      })
    );
  },

  async deleteProject(name: string): Promise<{ message: string }> {
    return handle(
      await fetch(`${BASE}/projects/${encodeURIComponent(name)}`, { method: "DELETE" })
    );
  },

  async getProject(name: string): Promise<ProjectSummary> {
    return handle(await fetch(`${BASE}/projects/${name}`));
  },

  async getClasses(name: string): Promise<{ classes: ClassItem[] }> {
    return handle(await fetch(`${BASE}/projects/${name}/classes`));
  },

  async saveClasses(
    name: string,
    classes: ClassInput[]
  ): Promise<{ classes: ClassItem[] }> {
    return handle(
      await fetch(`${BASE}/projects/${name}/classes`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ classes }),
      })
    );
  },

  async listImages(
    name: string,
    source = "raw"
  ): Promise<{ images: ImageInfo[]; total: number }> {
    return handle(
      await fetch(`${BASE}/projects/${name}/images?source=${encodeURIComponent(source)}`)
    );
  },

  async uploadImages(name: string, files: FileList): Promise<UploadResponse> {
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    return handle(
      await fetch(`${BASE}/projects/${name}/images`, {
        method: "POST",
        body: form,
      })
    );
  },

  async importFolder(
    name: string,
    files: File[],
    allowedExtensions: string[],
    includeSubfolders: boolean
  ): Promise<FolderImportResponse> {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    allowedExtensions.forEach((e) => form.append("allowed_extensions", e));
    form.append("include_subfolders", String(includeSubfolders));
    return handle(
      await fetch(`${BASE}/projects/${name}/images/import-folder`, {
        method: "POST",
        body: form,
      })
    );
  },

  async getAnnotations(
    name: string,
    imageId: string
  ): Promise<AnnotationGetResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/images/${encodeURIComponent(
          imageId
        )}/annotations`
      )
    );
  },

  async saveAnnotations(
    name: string,
    imageId: string,
    annotations: AnnotationItem[]
  ): Promise<AnnotationSaveResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/images/${encodeURIComponent(
          imageId
        )}/annotations`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ annotations }),
        }
      )
    );
  },

  // segment（polygon）保存。annotations は PolygonItem[]（points は正規化座標）。
  async saveSegmentAnnotations(
    name: string,
    imageId: string,
    annotations: PolygonItem[]
  ): Promise<AnnotationSaveResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/images/${encodeURIComponent(
          imageId
        )}/annotations`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ annotations }),
        }
      )
    );
  },

  // --- SAM支援アノテーション ---
  async getSamSettings(name: string): Promise<SamSettings> {
    return handle(await fetch(`${BASE}/projects/${name}/sam/settings`));
  },

  async saveSamSettings(name: string, settings: SamSettings): Promise<SamSettings> {
    return handle(
      await fetch(`${BASE}/projects/${name}/sam/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      })
    );
  },

  async samPropose(
    name: string,
    imageId: string,
    req: SamProposeRequest
  ): Promise<SamProposeResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/images/${encodeURIComponent(imageId)}/sam/propose`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(req),
        }
      )
    );
  },

  async validateLabels(name: string): Promise<LabelValidationResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/labels/validate`, {
        method: "POST",
      })
    );
  },

  async listDatasets(name: string): Promise<DatasetListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/datasets`));
  },

  async createDataset(
    name: string,
    req: DatasetCreateRequest
  ): Promise<DatasetCreateResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/datasets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      })
    );
  },

  async listTrainJobs(name: string): Promise<TrainJobListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/train-jobs`));
  },

  async startTrainJob(
    name: string,
    req: TrainJobCreateRequest
  ): Promise<TrainJobStartResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/train-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      })
    );
  },

  async getTrainJob(name: string, jobId: string): Promise<TrainJobInfo> {
    return handle(
      await fetch(`${BASE}/projects/${name}/train-jobs/${encodeURIComponent(jobId)}`)
    );
  },

  async getTrainLogs(name: string, jobId: string): Promise<TrainLogResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/train-jobs/${encodeURIComponent(jobId)}/logs`
      )
    );
  },

  async getEvaluation(name: string, jobId: string): Promise<EvaluationResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/train-jobs/${encodeURIComponent(jobId)}/evaluation`
      )
    );
  },

  async getMetrics(name: string, jobId: string): Promise<MetricsResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/train-jobs/${encodeURIComponent(jobId)}/metrics`
      )
    );
  },

  async listPredictJobs(name: string): Promise<PredictJobListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/predict-jobs`));
  },

  async startPredictJob(
    name: string,
    req: PredictJobCreateRequest
  ): Promise<PredictJobStartResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/predict-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      })
    );
  },

  async getPredictJob(name: string, jobId: string): Promise<PredictJobInfo> {
    return handle(
      await fetch(`${BASE}/projects/${name}/predict-jobs/${encodeURIComponent(jobId)}`)
    );
  },

  async getPredictLogs(name: string, jobId: string): Promise<PredictLogResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/predict-jobs/${encodeURIComponent(jobId)}/logs`
      )
    );
  },

  async getPredictResults(
    name: string,
    jobId: string
  ): Promise<PredictResultsResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/predict-jobs/${encodeURIComponent(jobId)}/results`
      )
    );
  },

  // --- 映像（カメラ）推論 ---
  async listCameras(name: string): Promise<CameraListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/cameras`));
  },

  async listVideoJobs(name: string): Promise<VideoJobListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/video-jobs`));
  },

  async startVideoJob(name: string, req: VideoJobCreateRequest): Promise<VideoJobInfo> {
    return handle(
      await fetch(`${BASE}/projects/${name}/video-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      })
    );
  },

  async getVideoJob(name: string, jobId: string): Promise<VideoJobInfo> {
    return handle(
      await fetch(`${BASE}/projects/${name}/video-jobs/${encodeURIComponent(jobId)}`)
    );
  },

  async stopVideoJob(name: string, jobId: string): Promise<VideoJobInfo> {
    return handle(
      await fetch(`${BASE}/projects/${name}/video-jobs/${encodeURIComponent(jobId)}/stop`, {
        method: "POST",
      })
    );
  },

  videoStreamUrl(name: string, jobId: string): string {
    return `${BASE}/projects/${name}/video-jobs/${encodeURIComponent(jobId)}/stream`;
  },

  async runAnalysis(
    name: string,
    predictJobId: string,
    iouThreshold: number,
    confThreshold: number
  ): Promise<AnalysisResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/predict-jobs/${encodeURIComponent(predictJobId)}/analysis`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ iou_threshold: iouThreshold, conf_threshold: confThreshold }),
        }
      )
    );
  },

  async getAnalysis(name: string, predictJobId: string): Promise<AnalysisResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/predict-jobs/${encodeURIComponent(predictJobId)}/analysis`
      )
    );
  },

  async listExperiments(name: string): Promise<ExperimentListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/experiments`));
  },

  async getExperiment(
    name: string,
    experimentId: string
  ): Promise<ExperimentDetailResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/experiments/${encodeURIComponent(experimentId)}`)
    );
  },

  async listModels(name: string): Promise<ModelListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/models`));
  },

  async getModel(
    name: string,
    trainJobId: string,
    weightType: string
  ): Promise<ModelDetailResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/models/${encodeURIComponent(trainJobId)}/${encodeURIComponent(weightType)}`
      )
    );
  },

  async getSelectedModel(name: string): Promise<SelectedModelResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/models/selected`));
  },

  async setSelectedModel(
    name: string,
    trainJobId: string,
    weightType: string,
    memo: string
  ): Promise<SelectedModelResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/models/selected`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ train_job_id: trainJobId, weight_type: weightType, memo }),
      })
    );
  },

  // --- モデル配布パッケージ出力 ---
  weightDownloadUrl(name: string, trainJobId: string, weight: string): string {
    return `${BASE}/projects/${name}/model-export/${encodeURIComponent(trainJobId)}/${weight}/download`;
  },

  packageDownloadUrl(name: string, packageId: string): string {
    return `${BASE}/projects/${name}/model-packages/${encodeURIComponent(packageId)}/download`;
  },

  async createModelPackage(
    name: string,
    trainJobId: string,
    weight: string,
    opts?: { include_onnx?: boolean; onnx_export_job_id?: string | null }
  ): Promise<ModelPackageResponse> {
    return handle(
      await fetch(
        `${BASE}/projects/${name}/model-export/${encodeURIComponent(trainJobId)}/${weight}/package`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            include_onnx: opts?.include_onnx ?? false,
            onnx_export_job_id: opts?.onnx_export_job_id ?? null,
          }),
        }
      )
    );
  },

  // --- ONNXエクスポート ---
  async startOnnxExport(
    name: string,
    req: OnnxExportCreateRequest
  ): Promise<OnnxExportStartResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/onnx-exports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      })
    );
  },

  async listOnnxExports(name: string): Promise<OnnxExportListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/onnx-exports`));
  },

  async getOnnxExport(name: string, exportJobId: string): Promise<OnnxExportInfo> {
    return handle(
      await fetch(`${BASE}/projects/${name}/onnx-exports/${encodeURIComponent(exportJobId)}`)
    );
  },

  async getOnnxExportLogs(name: string, exportJobId: string): Promise<OnnxExportLogResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/onnx-exports/${encodeURIComponent(exportJobId)}/logs`)
    );
  },

  onnxDownloadUrl(name: string, exportJobId: string): string {
    return `${BASE}/projects/${name}/onnx-exports/${encodeURIComponent(exportJobId)}/download`;
  },

  async listPresets(name: string): Promise<AugmentationPresetListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/augmentation/presets`));
  },

  async getPreset(name: string, presetName: string): Promise<AugmentationPreset> {
    return handle(
      await fetch(`${BASE}/projects/${name}/augmentation/presets/${encodeURIComponent(presetName)}`)
    );
  },

  async savePreset(
    name: string,
    presetName: string,
    description: string,
    params: AugmentationParams
  ): Promise<AugmentationPreset> {
    return handle(
      await fetch(`${BASE}/projects/${name}/augmentation/presets/${encodeURIComponent(presetName)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description, params }),
      })
    );
  },

  async deletePreset(name: string, presetName: string): Promise<{ message: string }> {
    return handle(
      await fetch(`${BASE}/projects/${name}/augmentation/presets/${encodeURIComponent(presetName)}`, {
        method: "DELETE",
      })
    );
  },

  async getSelection(name: string): Promise<SelectionGetResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/selection`));
  },

  async runSelection(
    name: string,
    req: SelectionRunRequest
  ): Promise<SelectionRunResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/selection/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      })
    );
  },

  async updateSelectionStatus(
    name: string,
    imageId: string,
    status: string,
    manualReason?: string
  ): Promise<{ image_id: string; status: string; manual_reason: string | null }> {
    return handle(
      await fetch(`${BASE}/projects/${name}/selection/images/${encodeURIComponent(imageId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, manual_reason: manualReason ?? null }),
      })
    );
  },

  async listReports(name: string): Promise<ReportListResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/reports`));
  },

  async generateReport(
    name: string,
    req: ReportCreateRequest
  ): Promise<ReportGenerateResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      })
    );
  },

  async getReport(name: string, reportId: string): Promise<ReportDetailResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/reports/${encodeURIComponent(reportId)}`)
    );
  },

  reportDownloadUrl(name: string, reportId: string, format: string): string {
    return `${BASE}/projects/${name}/reports/${encodeURIComponent(reportId)}/download?format=${format}`;
  },

  imageUrl(name: string, filename: string, source = "raw"): string {
    return `${BASE}/projects/${name}/images/${encodeURIComponent(filename)}?source=${encodeURIComponent(source)}`;
  },

  thumbnailUrl(name: string, filename: string, source = "raw"): string {
    return `${BASE}/projects/${name}/images/${encodeURIComponent(
      filename
    )}/thumbnail?source=${encodeURIComponent(source)}`;
  },

  async getPreprocessInfo(name: string): Promise<PreprocessInfoResponse> {
    return handle(await fetch(`${BASE}/projects/${name}/preprocess`));
  },

  async runPreprocess(
    name: string,
    settings: PreprocessSettings
  ): Promise<PreprocessRunResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/preprocess/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      })
    );
  },

  async previewPreprocess(
    name: string,
    settings: PreprocessSettings,
    imageId?: string
  ): Promise<PreprocessPreviewResponse> {
    const q = imageId ? `?image_id=${encodeURIComponent(imageId)}` : "";
    return handle(
      await fetch(`${BASE}/projects/${name}/preprocess/preview${q}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      })
    );
  },

  async rotateSelectionImage(
    name: string,
    imageId: string,
    angle: number,
    source = "processed"
  ): Promise<SelectionRotateResponse> {
    return handle(
      await fetch(`${BASE}/projects/${name}/selection/images/${encodeURIComponent(imageId)}/rotate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source, angle }),
      })
    );
  },
};
