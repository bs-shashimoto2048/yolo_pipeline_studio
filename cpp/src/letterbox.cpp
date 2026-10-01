#include "yps/letterbox.hpp"

#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <cmath>

namespace yps {

namespace {
// Pythonの round() は0.5を偶数へ丸める(banker's rounding)が、LetterBox.get_paramsは
// 常に +-0.1 のオフセットを加えてから round() するため、本実装が扱う値が厳密に *.5 に
// 一致するケースは実質発生しない（Issue #47で実測したDigital/Drumの値でも非該当）。
// そのため「0.5から遠ざける」通常のround-half-away-from-zeroで実用上同一の結果になる。
int py_round(double v) {
  return static_cast<int>(std::floor(v + 0.5));
}
}  // namespace

LetterBoxResult letterbox(const cv::Mat& img, int new_h, int new_w, int stride, int padding_value) {
  (void)stride;  // auto=False相当のため、strideへの丸め(np.mod)は行わない（Issue #47契約どおり）
  const int h0 = img.rows;
  const int w0 = img.cols;

  const double r = std::min(static_cast<double>(new_h) / h0, static_cast<double>(new_w) / w0);
  // scaleup=True固定（production既定と同一、ダウンスケールのみに制限しない）

  const int new_unpad_w = py_round(w0 * r);
  const int new_unpad_h = py_round(h0 * r);

  double dw = new_w - new_unpad_w;
  double dh = new_h - new_unpad_h;
  // auto=False: np.mod(dw, stride)による切り詰めは行わない（固定shapeへ正確に合わせる）

  // center=True
  dw /= 2.0;
  dh /= 2.0;

  const int top = py_round(dh - 0.1);
  const int bottom = py_round(dh + 0.1);
  const int left = py_round(dw - 0.1);
  const int right = py_round(dw + 0.1);

  cv::Mat resized;
  if (w0 != new_unpad_w || h0 != new_unpad_h) {
    cv::resize(img, resized, cv::Size(new_unpad_w, new_unpad_h), 0, 0, cv::INTER_LINEAR);
  } else {
    resized = img;
  }

  LetterBoxResult out;
  cv::copyMakeBorder(resized, out.image, top, bottom, left, right, cv::BORDER_CONSTANT,
                      cv::Scalar(padding_value, padding_value, padding_value));
  out.ratio = r;
  out.pad_left = left;
  out.pad_top = top;
  return out;
}

}  // namespace yps
