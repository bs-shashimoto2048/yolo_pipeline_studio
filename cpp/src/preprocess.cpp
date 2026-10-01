#include "yps/preprocess.hpp"
#include "yps/model_profile.hpp"

#include <opencv2/imgproc.hpp>
#include <algorithm>

namespace yps {

namespace {

cv::Mat apply_resize_width(const cv::Mat& img, int target_w) {
  const int nw = target_w;
  const int nh = std::max(1, static_cast<int>(std::lround(
                            static_cast<double>(img.rows) * target_w / img.cols)));
  cv::Mat out;
  // PIL既定(BICUBIC)の近似としてINTER_CUBICを使う（known limitation、ヘッダ参照）。
  cv::resize(img, out, cv::Size(nw, nh), 0, 0, cv::INTER_CUBIC);
  return out;
}

cv::Mat apply_grayscale_to_rgb3(const cv::Mat& bgr) {
  cv::Mat gray;
  cv::cvtColor(bgr, gray, cv::COLOR_BGR2GRAY);
  cv::Mat out;
  cv::cvtColor(gray, out, cv::COLOR_GRAY2BGR);  // R=G=Bの3ch化（Python側のconvert("L").convert("RGB")相当）
  return out;
}

cv::Mat apply_sharpen(const cv::Mat& img, float strength) {
  // PILの ImageFilter.UnsharpMask(radius=2, percent=strength*100, threshold=2) の近似。
  // 一般的なunsharp mask（Gaussian blur差分の加算）で代替する（known limitation、ヘッダ参照）。
  cv::Mat blurred;
  cv::GaussianBlur(img, blurred, cv::Size(0, 0), 2.0);
  cv::Mat sharpened;
  cv::addWeighted(img, 1.0 + strength, blurred, -strength, 0, sharpened);
  return sharpened;
}

}  // namespace

cv::Mat preprocess_image(const cv::Mat& raw_bgr, const ModelProfile& profile) {
  cv::Mat img = raw_bgr;

  if (profile.roi.enabled) {
    // ROI有効時: crop -> resize -> grayscale -> sharpen
    cv::Rect roi(profile.roi.x0, profile.roi.y0, profile.roi.x1 - profile.roi.x0,
                 profile.roi.y1 - profile.roi.y0);
    img = img(roi).clone();
    img = apply_resize_width(img, profile.resize_width);
    if (profile.grayscale) img = apply_grayscale_to_rgb3(img);
    if (profile.sharpen) img = apply_sharpen(img, profile.sharpen_strength);
  } else {
    // ROI無効時: grayscale -> sharpen -> resize
    if (profile.grayscale) img = apply_grayscale_to_rgb3(img);
    if (profile.sharpen) img = apply_sharpen(img, profile.sharpen_strength);
    img = apply_resize_width(img, profile.resize_width);
  }
  return img;
}

}  // namespace yps
