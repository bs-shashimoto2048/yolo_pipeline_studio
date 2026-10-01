// ONNX Runtime C++ セッションの薄いラッパー（Issue #48）。
// input name / shape / output name / shape はdeployment baseline
// （data_manifests/production_deployment_baseline_v1.json）の値をCLI/ModelProfile経由で
// 受け取り、ここへ文字列をハードコードしない（Issue #48 §17）。
#pragma once

#include <onnxruntime_cxx_api.h>

#include <string>
#include <vector>

namespace yps {

struct OnnxOutputInfo {
  std::string name;
  std::vector<int64_t> shape;
};

class OnnxModel {
 public:
  // provider: "cpu" | "cuda"
  OnnxModel(const std::string& onnx_path, const std::string& provider);

  // input: NCHW float32、tensorはcaller側でcontiguousに保持すること。
  // 戻り値: output0の生データ（channels*num_anchors個のfloat、batch=1前提）と
  // そのshape情報。
  std::vector<float> run(const std::vector<float>& input_nchw,
                          const std::vector<int64_t>& input_shape, OnnxOutputInfo* out_info);

  const std::string& input_name() const { return input_name_; }
  const std::string& output_name() const { return output_name_; }

 private:
  Ort::Env env_;
  Ort::SessionOptions session_options_;
  Ort::Session session_{nullptr};
  Ort::MemoryInfo memory_info_{nullptr};
  std::string input_name_;
  std::string output_name_;
  std::string provider_;
};

}  // namespace yps
