// production_deployment_baseline_v1（Issue #47）/ docs/CPP_DEPLOYMENT_CONTRACT.md の
// 値をそのまま持つ、project固有のprofile構造体。
//
// JSON parserライブラリを追加導入するほどではない（Issue #48 §43で明示的に許容されている
// 「最初は明確なprofile structでも可」の方針を採用）ため、値はここへ直接定義し、
// data_manifests/production_deployment_baseline_v1.json とコメントで対応関係を明記する。
// 値を変更する場合は、そのJSON/docsも同時に更新すること（どちらかだけが古くなるのを防ぐ）。
#pragma once

#include <string>

namespace yps {

struct RoiRect {
  bool enabled = false;
  int x0 = 0, y0 = 0, x1 = 0, y1 = 0;
};

struct ModelProfile {
  std::string name;            // "digital" | "drum"
  std::string onnx_path;       // 既定のONNXファイルパス（CLIで上書き可能）
  std::string pt_sha256;       // production_deployment_baseline_v1.json と照合用（参考表示のみ）
  std::string onnx_sha256;     // 同上

  // 前処理契約（docs/CPP_DEPLOYMENT_CONTRACT.md「Input preprocessing」）
  RoiRect roi;
  int resize_width = 640;      // resize_mode=width固定（現production両projectとも同一）
  bool grayscale = true;
  bool sharpen = true;
  float sharpen_strength = 1.0f;

  // letterbox / ONNX tensor契約
  int input_h = 0;             // 非正方形rect shape（Digital=384, Drum=160）
  int input_w = 640;
  int num_classes = 10;

  // 推論/NMS契約（production-inference-contract-v1 と同一）
  float conf = 0.0f;           // project固有（Digital=0.60, Drum=0.80）
  float iou = 0.70f;
  int max_det = 300;
  bool agnostic_nms = false;
};

// data_manifests/production_deployment_baseline_v1.json の digital/drum セクションと
// 1:1対応する既定値を返す。
ModelProfile digital_profile();
ModelProfile drum_profile();

}  // namespace yps
