// yps_infer: Issue #48 C++ ONNX Runtime inference PoC CLI。
//
// 使い方:
//   yps_infer.exe --profile digital|drum --image <path> [--raw] [--onnx <path>]
//                  [--provider cpu|cuda] [--warmup N] [--benchmark N] [--json]
//
// --raw を指定しない場合、--image は既にproduction前処理済み（ROI/resize/grayscale/
// sharpen適用後）の画像であることを前提とする（Issue #47のfixture画像と同じ扱い、
// letterbox以降のみを実行する）。--raw指定時は生カメラ画像からフル前処理を行う。
#include "yps/letterbox.hpp"
#include "yps/model_profile.hpp"
#include "yps/nms.hpp"
#include "yps/onnx_model.hpp"
#include "yps/preprocess.hpp"

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>

namespace {

using Clock = std::chrono::high_resolution_clock;
double ms_since(Clock::time_point t0) {
  return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

struct Stats {
  double mean = 0, median = 0, p95 = 0, min = 0, max = 0;
};

Stats compute_stats(std::vector<double> v) {
  Stats s;
  if (v.empty()) return s;
  std::sort(v.begin(), v.end());
  s.min = v.front();
  s.max = v.back();
  s.mean = std::accumulate(v.begin(), v.end(), 0.0) / v.size();
  s.median = v[v.size() / 2];
  s.p95 = v[std::min(v.size() - 1, static_cast<size_t>(v.size() * 0.95))];
  return s;
}

struct Args {
  std::string profile_name;
  std::string image_path;
  std::string onnx_override;
  std::string provider = "cpu";
  bool raw = false;
  bool json = false;
  int warmup = 0;
  int benchmark = 0;
  std::string dump_preprocessed;  // Issue #48 §16: preprocess parity診断用
};

bool parse_args(int argc, char** argv, Args* a) {
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    auto next = [&](const char* flag) -> std::string {
      if (i + 1 >= argc) {
        std::cerr << "ERROR: " << flag << " requires a value\n";
        std::exit(2);
      }
      return argv[++i];
    };
    if (arg == "--profile") a->profile_name = next("--profile");
    else if (arg == "--image") a->image_path = next("--image");
    else if (arg == "--onnx") a->onnx_override = next("--onnx");
    else if (arg == "--provider") a->provider = next("--provider");
    else if (arg == "--raw") a->raw = true;
    else if (arg == "--json") a->json = true;
    else if (arg == "--warmup") a->warmup = std::stoi(next("--warmup"));
    else if (arg == "--benchmark") a->benchmark = std::stoi(next("--benchmark"));
    else if (arg == "--dump-preprocessed") a->dump_preprocessed = next("--dump-preprocessed");
    else {
      std::cerr << "ERROR: unknown argument: " << arg << "\n";
      return false;
    }
  }
  if (a->profile_name.empty() || a->image_path.empty()) {
    std::cerr << "ERROR: --profile and --image are required\n";
    return false;
  }
  return true;
}

struct RunResult {
  double preprocess_ms = 0, inference_ms = 0, postprocess_ms = 0, total_ms = 0;
  std::vector<yps::Detection> detections;
  std::string reading;
};

RunResult run_once(const cv::Mat& image_in, const yps::ModelProfile& profile, bool raw,
                    yps::OnnxModel* model) {
  const auto t_total0 = Clock::now();

  const auto t_pre0 = Clock::now();
  cv::Mat processed = raw ? yps::preprocess_image(image_in, profile) : image_in;
  const int orig_h = processed.rows;
  const int orig_w = processed.cols;
  yps::LetterBoxResult lb = yps::letterbox(processed, profile.input_h, profile.input_w);

  // BGR HWC uint8 -> RGB CHW float32 [0,1], batch dim追加
  cv::Mat rgb;
  cv::cvtColor(lb.image, rgb, cv::COLOR_BGR2RGB);
  cv::Mat rgb_f32;
  rgb.convertTo(rgb_f32, CV_32F, 1.0 / 255.0);

  const int H = rgb_f32.rows, W = rgb_f32.cols;
  std::vector<float> tensor(static_cast<size_t>(3) * H * W);
  std::vector<cv::Mat> channels(3);
  for (int c = 0; c < 3; ++c) {
    channels[c] = cv::Mat(H, W, CV_32F, tensor.data() + static_cast<size_t>(c) * H * W);
  }
  cv::split(rgb_f32, channels);
  const double preprocess_ms = ms_since(t_pre0);

  const auto t_inf0 = Clock::now();
  std::vector<int64_t> input_shape = {1, 3, H, W};
  yps::OnnxOutputInfo out_info;
  std::vector<float> raw_out = model->run(tensor, input_shape, &out_info);
  const double inference_ms = ms_since(t_inf0);

  if (out_info.shape.size() != 3 || out_info.shape[0] != 1) {
    std::cerr << "ERROR: unexpected output shape (expected [1, C, N])\n";
    std::exit(5);
  }
  const int channels_out = static_cast<int>(out_info.shape[1]);
  const int anchors_out = static_cast<int>(out_info.shape[2]);
  const int num_classes = channels_out - 4;
  if (num_classes != profile.num_classes) {
    std::cerr << "ERROR: output shape mismatch: expected num_classes=" << profile.num_classes
               << " got " << num_classes << "\n";
    std::exit(5);
  }

  const auto t_post0 = Clock::now();
  auto dets = yps::decode_and_nms(raw_out.data(), channels_out, anchors_out, num_classes,
                                   profile.conf, profile.iou, profile.max_det,
                                   profile.agnostic_nms);
  yps::scale_boxes_inplace(dets, lb.ratio, lb.pad_left, lb.pad_top, orig_h, orig_w);
  std::string reading = yps::reading_from_detections(dets);
  const double postprocess_ms = ms_since(t_post0);

  RunResult r;
  r.preprocess_ms = preprocess_ms;
  r.inference_ms = inference_ms;
  r.postprocess_ms = postprocess_ms;
  r.total_ms = ms_since(t_total0);
  r.detections = dets;
  r.reading = reading;
  return r;
}

}  // namespace

int main(int argc, char** argv) {
  Args args;
  if (!parse_args(argc, argv, &args)) return 2;

  yps::ModelProfile profile;
  if (args.profile_name == "digital") profile = yps::digital_profile();
  else if (args.profile_name == "drum") profile = yps::drum_profile();
  else {
    std::cerr << "ERROR: unknown profile: " << args.profile_name << " (expected digital|drum)\n";
    return 2;
  }
  const std::string onnx_path = args.onnx_override.empty() ? profile.onnx_path : args.onnx_override;

  cv::Mat image = cv::imread(args.image_path, cv::IMREAD_COLOR);
  if (image.empty()) {
    std::cerr << "ERROR: image missing or unreadable: " << args.image_path << "\n";
    return 3;
  }

  if (!args.dump_preprocessed.empty()) {
    // Issue #48 §16 preprocess parity診断専用: ONNX推論は行わず、letterbox前の
    // 前処理結果（raw->ROI/resize/grayscale/sharpen後）だけを書き出す。
    cv::Mat processed = args.raw ? yps::preprocess_image(image, profile) : image;
    if (!cv::imwrite(args.dump_preprocessed, processed)) {
      std::cerr << "ERROR: failed to write dump: " << args.dump_preprocessed << "\n";
      return 7;
    }
    std::cout << "dumped preprocessed image: " << args.dump_preprocessed
               << " shape=" << processed.cols << "x" << processed.rows << "\n";
    return 0;
  }

  yps::OnnxModel* model = nullptr;
  double session_create_ms = 0.0;
  double first_inference_ms = 0.0;
  try {
    const auto t0 = Clock::now();
    model = new yps::OnnxModel(onnx_path, args.provider);
    session_create_ms = ms_since(t0);
  } catch (const std::exception& e) {
    std::cerr << "ERROR: ONNX session creation failed (model=" << onnx_path
               << ", provider=" << args.provider << "): " << e.what() << "\n";
    return 4;
  }

  {
    // Issue #48 §37: session creation/model loadとは別に、初回推論（CUDA kernel
    // compile/context初期化等を含む）の時間を明示的に切り分けて記録する。
    const auto t0 = Clock::now();
    run_once(image, profile, args.raw, model);
    first_inference_ms = ms_since(t0);
  }

  std::vector<double> pre_t, inf_t, post_t, total_t;
  RunResult last;
  try {
    for (int i = 0; i < args.warmup; ++i) run_once(image, profile, args.raw, model);

    const int iters = std::max(1, args.benchmark);
    for (int i = 0; i < iters; ++i) {
      last = run_once(image, profile, args.raw, model);
      pre_t.push_back(last.preprocess_ms);
      inf_t.push_back(last.inference_ms);
      post_t.push_back(last.postprocess_ms);
      total_t.push_back(last.total_ms);
    }
  } catch (const std::exception& e) {
    std::cerr << "ERROR: inference failed: " << e.what() << "\n";
    delete model;
    return 6;
  }

  if (args.json) {
    std::ostringstream os;
    auto dump_stats = [&](const Stats& s) {
      os << "{\"mean\":" << s.mean << ",\"median\":" << s.median << ",\"p95\":" << s.p95
         << ",\"min\":" << s.min << ",\"max\":" << s.max << "}";
    };
    os << "{";
    os << "\"profile\":\"" << args.profile_name << "\",";
    os << "\"provider\":\"" << args.provider << "\",";
    os << "\"reading\":\"" << last.reading << "\",";
    os << "\"count\":" << last.detections.size() << ",";
    os << "\"detections\":[";
    for (size_t i = 0; i < last.detections.size(); ++i) {
      const auto& d = last.detections[i];
      if (i) os << ",";
      os << "{\"x1\":" << d.x1 << ",\"y1\":" << d.y1 << ",\"x2\":" << d.x2
         << ",\"y2\":" << d.y2 << ",\"conf\":" << d.conf << ",\"cls\":" << d.cls << "}";
    }
    os << "],";
    os << "\"preprocess_ms\":"; dump_stats(compute_stats(pre_t)); os << ",";
    os << "\"inference_ms\":"; dump_stats(compute_stats(inf_t)); os << ",";
    os << "\"postprocess_ms\":"; dump_stats(compute_stats(post_t)); os << ",";
    os << "\"end_to_end_ms\":"; dump_stats(compute_stats(total_t)); os << ",";
    os << "\"session_create_ms\":" << session_create_ms << ",";
    os << "\"first_inference_ms\":" << first_inference_ms;
    os << "}";
    std::cout << os.str() << "\n";
  } else {
    std::printf("session_create_ms=%.3f first_inference_ms=%.3f\n", session_create_ms,
                first_inference_ms);
    std::cout << "profile=" << args.profile_name << " provider=" << args.provider
               << " reading=" << last.reading << " count=" << last.detections.size() << "\n";
    for (const auto& d : last.detections) {
      std::cout << "  cls=" << d.cls << " conf=" << d.conf << " bbox=[" << d.x1 << "," << d.y1
                 << "," << d.x2 << "," << d.y2 << "]\n";
    }
    if (args.benchmark > 0) {
      auto print_stats = [](const char* label, const Stats& s) {
        std::printf("%-14s mean=%.3fms median=%.3fms p95=%.3fms min=%.3fms max=%.3fms\n", label,
                     s.mean, s.median, s.p95, s.min, s.max);
      };
      print_stats("preprocess", compute_stats(pre_t));
      print_stats("inference", compute_stats(inf_t));
      print_stats("postprocess", compute_stats(post_t));
      print_stats("end_to_end", compute_stats(total_t));
      const double fps = 1000.0 / compute_stats(total_t).mean;
      std::printf("end_to_end FPS (mean-based): %.2f\n", fps);
    }
  }

  delete model;
  return 0;
}
