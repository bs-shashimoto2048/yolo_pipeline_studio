// docs/CPP_DEPLOYMENT_CONTRACT.md「Input preprocessing」の再移植（Issue #48）。
//
// 既知の近似（ビット完全一致ではない箇所、必ずdocs/CPP_INFERENCE_BENCHMARK.mdの
// 「known limitations」で明記すること）:
//   - resize: PIL既定のBICUBICに対し、本実装はcv2.INTER_CUBICを使う（同系統だが
//     カーネル係数が異なるため厳密には非一致）。
//   - sharpen: PILの ImageFilter.UnsharpMask(radius=2, percent=strength*100, threshold=2)
//     に対し、本実装は一般的なGaussian unsharp maskで近似する（PIL内部実装とは非一致）。
// これらの近似は「ONNX/NMS/reading parity」の主判定（Stage 1/2, 30+30件、Issue #47と
// 同じ既にproduction前処理済みのfixture画像を使う）には影響しない
// （そちらはletterbox以降のみを再現するため、本ファイルの関数は経由しない）。
// 本ファイルはend-to-end benchmarkと、rawからのpreprocess parity診断（diagnostic、
// 合否判定ではない）でのみ使用する。
#pragma once

#include <opencv2/core.hpp>

namespace yps {

struct RoiRect;
struct ModelProfile;

// raw（カメラ直後、BGR, uint8）から、letterbox直前までのYOLO入力用画像を生成する。
// profile.roi.enabled に応じて ROI→resize→grayscale→sharpen（Drum）または
// grayscale→sharpen→resize（Digital）の順で適用する
// （backend/app/services/preprocess_service.py の分岐と同一）。
cv::Mat preprocess_image(const cv::Mat& raw_bgr, const ModelProfile& profile);

}  // namespace yps
