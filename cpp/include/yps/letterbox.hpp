// Ultralytics `LetterBox`（auto=False, center=True, scale_fill=False, scaleup=True,
// stride=32, padding_value=114）の忠実な再移植（Issue #48 §15）。
// 参照実装: .venv/Lib/site-packages/ultralytics/data/augment.py の LetterBox クラス
// （get_params/apply_image）。「見た目が似ている実装」ではなく、同一の計算式
// （scale/new_unpad/padding/round）を1行ずつ対応させている。
#pragma once

#include <opencv2/core.hpp>

namespace yps {

struct LetterBoxResult {
  cv::Mat image;        // padded image（新形状 new_h x new_w）
  double ratio = 1.0;    // scale ratio r（width/heightで共通、Ultralyticsと同じ前提）
  int pad_left = 0;
  int pad_top = 0;
};

// new_h/new_w: 目的shape（Digitalは384x640、Drumは160x640、Issue #47で確定した
// production rect推論の非正方形shapeを静的に指定する。auto=falseで常に固定）。
LetterBoxResult letterbox(const cv::Mat& img, int new_h, int new_w, int stride = 32,
                           int padding_value = 114);

}  // namespace yps
