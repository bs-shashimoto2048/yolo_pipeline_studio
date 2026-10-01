// Ultralytics `ultralytics.utils.nms.non_max_suppression` 相当の再実装（Issue #48）。
// 対象は「best class only」パス（multi_label=False、本production contractの既定）。
// end2end=False、rotated=False、masks無し（nc=0相当の自動検出はdecode側で行う）。
#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace yps {

struct Detection {
  float x1, y1, x2, y2;  // xyxy
  float conf;
  int cls;
};

// raw: ONNX生出力（[1, 4+num_classes, num_anchors]をrow-majorでflattenしたもの）。
// channels = 4+num_classes, num_anchors = N。
// 戻り値のbboxはletterbox座標系（まだ元画像座標へは戻していない）。
std::vector<Detection> decode_and_nms(const float* raw, int channels, int num_anchors,
                                       int num_classes, float conf_thres, float iou_thres,
                                       int max_det, bool agnostic);

// Ultralytics `scale_boxes`相当: letterbox座標系 -> 元画像座標系。
// ratio/pad_left/pad_topはletterbox()の戻り値をそのまま渡す（auto-inferと数式上同一）。
void scale_boxes_inplace(std::vector<Detection>& dets, double ratio, int pad_left, int pad_top,
                          int orig_h, int orig_w);

// reading construction: bbox中心x座標（元画像座標系）昇順でsortし、class_idを連結する
// （smoke_production_integration.py の _reading_from_detections と同一規約）。
std::string reading_from_detections(const std::vector<Detection>& dets);

}  // namespace yps
