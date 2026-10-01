// C++ smoke test（Issue #48 §45）。
//
// backend/tests/fixtures/production_smoke_v1.json の公式fixture stem（既に
// production前処理済み）に対し、production_inference_contract_golden_v1.json と
// 同一のexpected readingが得られることを確認する。
// production weight/ONNX artifactがローカルに無い環境ではSKIPする
// （backend/tests/smoke_*.pyと同じ方針）。
//
// repo rootから実行すること:
//   cpp\build\Release\yps_smoke.exe
#include "yps/letterbox.hpp"
#include "yps/model_profile.hpp"
#include "yps/nms.hpp"
#include "yps/onnx_model.hpp"

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {
int g_pass = 0, g_fail = 0, g_skip = 0;

void check(const std::string& label, bool cond) {
  std::cout << (cond ? "OK   " : "FAIL ") << label << "\n";
  if (cond) ++g_pass; else ++g_fail;
}

void skip(const std::string& label) {
  std::cout << "SKIP " << label << "\n";
  ++g_skip;
}

struct Fixture {
  std::string stem;
  std::string expected_reading;
};

std::string infer_reading(const yps::ModelProfile& profile, const std::string& image_path) {
  cv::Mat img = cv::imread(image_path, cv::IMREAD_COLOR);
  if (img.empty()) throw std::runtime_error("image not found: " + image_path);

  yps::OnnxModel model(profile.onnx_path, "cpu");
  yps::LetterBoxResult lb = yps::letterbox(img, profile.input_h, profile.input_w);
  cv::Mat rgb, rgb_f32;
  cv::cvtColor(lb.image, rgb, cv::COLOR_BGR2RGB);
  rgb.convertTo(rgb_f32, CV_32F, 1.0 / 255.0);
  const int H = rgb_f32.rows, W = rgb_f32.cols;
  std::vector<float> tensor(static_cast<size_t>(3) * H * W);
  std::vector<cv::Mat> channels(3);
  for (int c = 0; c < 3; ++c)
    channels[c] = cv::Mat(H, W, CV_32F, tensor.data() + static_cast<size_t>(c) * H * W);
  cv::split(rgb_f32, channels);

  std::vector<int64_t> shape = {1, 3, H, W};
  yps::OnnxOutputInfo out_info;
  std::vector<float> raw = model.run(tensor, shape, &out_info);
  const int channels_out = static_cast<int>(out_info.shape[1]);
  const int anchors_out = static_cast<int>(out_info.shape[2]);
  auto dets = yps::decode_and_nms(raw.data(), channels_out, anchors_out, profile.num_classes,
                                   profile.conf, profile.iou, profile.max_det,
                                   profile.agnostic_nms);
  yps::scale_boxes_inplace(dets, lb.ratio, lb.pad_left, lb.pad_top, img.rows, img.cols);
  return yps::reading_from_detections(dets);
}

}  // namespace

int main() {
  const fs::path repo_root = fs::current_path();

  struct ProjectCase {
    std::string key;
    yps::ModelProfile profile;
    std::string source_dir;
    std::vector<Fixture> fixtures;
  };

  std::vector<ProjectCase> cases = {
      {"digital", yps::digital_profile(),
       "projects/yolo26_digital/datasets/matched_source_v1/images/train",
       {{"src_002_20260903_142400", "0215234"}, {"src_002_20260906_032000", "0215257"}}},
      {"drum", yps::drum_profile(),
       "projects/yolo26_dram_crop/datasets/matched_source_v1/images/train",
       {{"src_004_20260906_002400", "3718333"}, {"src_004_20260904_134800", "3718227"}}},
  };

  for (const auto& c : cases) {
    const fs::path onnx_path = repo_root / c.profile.onnx_path;
    if (!fs::exists(onnx_path)) {
      skip("[" + c.key + "] ONNX artifact not available locally (" + onnx_path.string() + ")");
      continue;
    }
    for (const auto& fx : c.fixtures) {
      const fs::path img_path = repo_root / c.source_dir / (fx.stem + ".jpg");
      if (!fs::exists(img_path)) {
        skip("[" + c.key + "] fixture image not available locally (" + img_path.string() + ")");
        continue;
      }
      try {
        const std::string reading = infer_reading(c.profile, img_path.string());
        check("[" + c.key + "] " + fx.stem + ": reading == " + fx.expected_reading +
                  " (got " + reading + ")",
              reading == fx.expected_reading);
      } catch (const std::exception& e) {
        check("[" + c.key + "] " + fx.stem + ": inference did not throw (" +
                  std::string(e.what()) + ")",
              false);
      }
    }
  }

  std::cout << "\n" << g_pass << " passed, " << g_fail << " failed, " << g_skip << " skipped\n";
  if (g_fail > 0) return 1;
  std::cout << "\nALL CPP PARITY SMOKE TESTS PASSED (or safely skipped)\n";
  return 0;
}
