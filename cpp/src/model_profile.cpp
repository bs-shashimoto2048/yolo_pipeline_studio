#include "yps/model_profile.hpp"

namespace yps {

ModelProfile digital_profile() {
  ModelProfile p;
  p.name = "digital";
  p.onnx_path = "projects/meter_src002/exports/onnx/digital_production_v1/model.onnx";
  p.pt_sha256 = "630d84287f983dac334815d04c6652f88de8164956c779d94f855645394d4b61";
  p.onnx_sha256 = "512b669b02df383be15419ca0ca34dd0749fb3235e84a90d884e3d0a4660d0b0";
  p.roi.enabled = false;
  p.resize_width = 640;
  p.grayscale = true;
  p.sharpen = true;
  p.sharpen_strength = 1.0f;
  p.input_h = 384;
  p.input_w = 640;
  p.num_classes = 10;
  p.conf = 0.60f;
  p.iou = 0.70f;
  p.max_det = 300;
  p.agnostic_nms = false;
  return p;
}

ModelProfile drum_profile() {
  ModelProfile p;
  p.name = "drum";
  p.onnx_path = "projects/meter_src004/exports/onnx/drum_production_v1/model.onnx";
  p.pt_sha256 = "cadd1d7df52b94004331be2d3c79c7dbc306c93802b3f5c3d455f2121061f595";
  p.onnx_sha256 = "09fc0d56d54293f7dbf9afa667cf4561b318c44fb00bb17fd8d85adbd6cd8332";
  p.roi.enabled = true;
  p.roi.x0 = 835;
  p.roi.y0 = 374;
  p.roi.x1 = 1354;
  p.roi.y1 = 480;
  p.resize_width = 640;
  p.grayscale = true;
  p.sharpen = true;
  p.sharpen_strength = 1.0f;
  p.input_h = 160;
  p.input_w = 640;
  p.num_classes = 10;
  p.conf = 0.80f;
  p.iou = 0.70f;
  p.max_det = 300;
  p.agnostic_nms = false;
  return p;
}

}  // namespace yps
