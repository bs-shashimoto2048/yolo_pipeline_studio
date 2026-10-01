# YOLO Tuning Studio - C++ ONNX Runtime inference PoC (Issue #48)
#
# production_deployment_baseline_v1 (Issue #47) を C++ で再現する最小PoC。
# 依存は ONNX Runtime C++ と OpenCV C++ のみ（third_party/ 配下のローカル展開済み
# prebuilt binaryを使う。vcpkg等のpackage managerは導入していない。巨大binaryは
# 一切Gitへcommitしない、third_party/はgitignore対象）。
#
# third_party配置（手動ダウンロード・展開、本リポジトリには含まれない）:
#   cpp/third_party/onnxruntime/   onnxruntime-win-x64-1.23.2.zip の展開結果
#                                  (https://github.com/microsoft/onnxruntime/releases)
#   cpp/third_party/opencv2/       opencv-4.10.0-windows.exe の展開結果 build/ ディレクトリ
#                                  (https://github.com/opencv/opencv/releases)
# 取得・配置手順の詳細は docs/CPP_INFERENCE_BENCHMARK.md を参照。

cmake_minimum_required(VERSION 3.20)
project(yps_cpp_inference_poc LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(MSVC)
  # ソースファイル中の日本語コメント(UTF-8)が、既定のシステムcodepage(例: 932)誤解釈で
  # 構文エラーを起こすのを防ぐ（実ビルドで実際に発生し判明したため追加）。
  add_compile_options(/utf-8)
endif()

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

set(THIRD_PARTY_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party" CACHE PATH
    "third-party dependency root (ONNX Runtime / OpenCV prebuilt)")
set(ORT_DIR "${THIRD_PARTY_DIR}/onnxruntime" CACHE PATH "ONNX Runtime C++ prebuilt root")

# --- OpenCV（同梱のOpenCVConfig.cmakeを使う） ---
set(OpenCV_DIR "${THIRD_PARTY_DIR}/opencv2" CACHE PATH "OpenCV prebuilt root (contains OpenCVConfig.cmake)")
find_package(OpenCV REQUIRED)

# --- ONNX Runtime（公式zip配布にはCMake configが同梱されないため手動で指定） ---
find_path(ORT_INCLUDE_DIR onnxruntime_cxx_api.h PATHS "${ORT_DIR}/include" REQUIRED)
find_library(ORT_LIB onnxruntime PATHS "${ORT_DIR}/lib" REQUIRED)
set(ORT_DLL "${ORT_DIR}/lib/onnxruntime.dll")

add_library(yps_core
  src/letterbox.cpp
  src/nms.cpp
  src/preprocess.cpp
  src/model_profile.cpp
  src/onnx_model.cpp
)
target_include_directories(yps_core PUBLIC include "${ORT_INCLUDE_DIR}")
target_link_libraries(yps_core PUBLIC ${OpenCV_LIBS} "${ORT_LIB}")

add_executable(yps_infer src/main.cpp)
target_link_libraries(yps_infer PRIVATE yps_core)

add_executable(yps_smoke smoke/parity_smoke.cpp)
target_link_libraries(yps_smoke PRIVATE yps_core)

# 実行時にONNX Runtime/OpenCVのDLLが見つかるよう、ビルド出力ディレクトリへコピーする
# （PATH変更やインストール手順を要求しない、開発時の利便性のため）。
foreach(tgt yps_infer yps_smoke)
  add_custom_command(TARGET ${tgt} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "${ORT_DLL}" "$<TARGET_FILE_DIR:${tgt}>"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "${THIRD_PARTY_DIR}/onnxruntime/lib/onnxruntime_providers_shared.dll" "$<TARGET_FILE_DIR:${tgt}>"
  )
  if(WIN32)
    add_custom_command(TARGET ${tgt} POST_BUILD
      COMMAND ${CMAKE_COMMAND} -E copy_if_different "${OpenCV_DIR}/x64/vc16/bin/opencv_world4100.dll" "$<TARGET_FILE_DIR:${tgt}>"
    )
  endif()
endforeach()
